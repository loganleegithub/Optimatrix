from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import PolicyFactory
from market_monitor import (
    ContinuityGap,
    ContinuousOrderBook,
    TimeInterval,
    TrustedClock,
)
from options_domain import (
    AmountMetadata,
    ComboInstrument,
    ComboLeg,
    InstrumentLifecycleState,
    OptionInstrument,
    OptionType,
)
from radar_runtime.deribit_public import (
    InboundEnvelope,
    SendControlEvent,
    SendControlKind,
)
from radar_runtime.fixed_contract_shadow import (
    FixedContractShadowRuntimeAdapter,
    _atomic_availability,
    _ComboSource,
    _option_availability,
    _OptionSource,
    _required_sources_continuous,
)
from radar_runtime.runtime import (
    AcceptedBookReceipt,
    AcceptedIndexReceipt,
    CausalCause,
    CausalCommit,
    FactBoundary,
    FailureScope,
    PendingRpc,
    RadarReducer,
    RpcState,
    ShadowRpcIntent,
)
from short_vol_radar.black import DecimalInterval
from short_vol_radar.detector import DetectorObservation, EpisodeTracker, TrackerState
from short_vol_radar.evidence import EvidenceWriter
from short_vol_radar.policy import load_policy_bytes
from short_vol_radar.radar import TickerState
from short_vol_underwriting import (
    CloseAtomicAvailability,
    CloseOptionAvailability,
    DownstreamEvidenceWriter,
    FixedContractShadowOwner,
    RuntimeBindings,
    SourceFact,
    SubscriptionAdmissionRefreshWitness,
    canonical_identity,
    load_policy_chain,
)
from short_vol_underwriting import (
    FactBoundary as DownstreamFactBoundary,
)

ROOT = Path(__file__).resolve().parents[1]
RADAR_POLICY_IDENTITY = "sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4"
UNDERWRITING_POLICY_IDENTITY = (
    "sha256:be056d7fad71668954103e1e383372c3b03db9b27b8d03ce0a030d39285629af"
)
POSITION_POLICY_IDENTITY = "sha256:498a298be50cb356f43886ae7ba02d1f6da065233ae9b2b52e9a230cf7f9c439"
UNDERWRITING_CONTRACT_DIGEST = (
    "sha256:9cbaecf57fb1db0dedf782a4ab002b655e43319a1ad7c5880db3d7b4682d4b03"
)
OUTCOME_CONTRACT_DIGEST = "sha256:61a032fe0fe265d66a38bcbb1a3c8498409664fedbda2c8bd0a245180581a695"


def _reducer(tmp_path: Path, policy_factory: PolicyFactory) -> RadarReducer:
    exact, digest = policy_factory()
    reducer = RadarReducer(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="sha256:" + "b" * 64,
            policy_identity=digest,
        ),
        runtime_identity="sha256:" + "b" * 64,
    )
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    reducer.combos["BTC-COMBO"] = ComboInstrument(
        instrument_name="BTC-COMBO",
        state="active",
        legs=(
            ComboLeg("BTC-SHORT", Decimal("-0.1")),
            ComboLeg("BTC-LONG", Decimal("0.1")),
        ),
        amount=AmountMetadata(
            contract_size=Decimal("1"),
            min_trade_amount=Decimal("0.1"),
            qty_tick_size=Decimal("0.1"),
        ),
    )
    return reducer


def _book_payload(
    *,
    kind: str,
    change_id: int,
    timestamp: int,
    prev_change_id: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": kind,
        "instrument_name": "BTC-COMBO",
        "change_id": change_id,
        "timestamp": timestamp,
        "bids": [["new", "300", "0.1"]],
        "asks": [["new", "301", "0.1"]],
    }
    if prev_change_id is not None:
        payload["prev_change_id"] = prev_change_id
        payload["bids"] = []
        payload["asks"] = []
    return payload


def test_successful_book_receipt_retains_exact_subscription_chain_and_failure_does_not_overwrite(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = _reducer(tmp_path, policy_factory)
    snapshot_boundary = FactBoundary(1, 1, 1_010, 2)
    assert reducer._apply_book(
        "BTC-COMBO",
        _book_payload(kind="snapshot", change_id=10, timestamp=2_000),
        snapshot_boundary,
    )
    snapshot = reducer.accepted_book_receipts["BTC-COMBO"]
    assert snapshot.snapshot_kind == "snapshot"
    assert snapshot.prev_change_id is None
    assert snapshot.change_id == 10
    assert snapshot.source_timestamp_ms == 2_000
    assert snapshot.boundary == snapshot_boundary

    change_boundary = FactBoundary(1, 2, 1_020, 3)
    assert reducer._apply_book(
        "BTC-COMBO",
        _book_payload(
            kind="change",
            prev_change_id=10,
            change_id=11,
            timestamp=2_001,
        ),
        change_boundary,
    )
    accepted = reducer.accepted_book_receipts["BTC-COMBO"]
    assert accepted.snapshot_kind == "change"
    assert accepted.prev_change_id == 10
    assert accepted.change_id == 11
    assert accepted.source_timestamp_ms == 2_001
    assert accepted.boundary == change_boundary

    with pytest.raises(ContinuityGap):
        reducer.combo_books["BTC-COMBO"].apply(
            _book_payload(
                kind="change",
                prev_change_id=9,
                change_id=12,
                timestamp=2_002,
            ),
            1_030,
        )
    assert reducer.accepted_book_receipts["BTC-COMBO"] == accepted


def test_successful_index_receipt_retains_exact_value_timestamp_and_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = _reducer(tmp_path, policy_factory)
    reducer.index.start_continuous_coverage(2_000, generation=1)
    reducer.clock = TrustedClock.from_response(
        2_000,
        1_000,
        1_000,
        stale_deadline_ms=10_000,
    )
    reducer._causal_seq = 4
    boundary = FactBoundary(1, 3, 1_030, 4)

    assert reducer._apply_index(
        {
            "index_name": "btc_usdc",
            "timestamp": 2_000,
            "price": "100000.25",
        },
        boundary,
    )

    receipt = reducer.accepted_index_receipt
    assert receipt is not None
    assert receipt.price_usdc_per_btc == Decimal("100000.25")
    assert receipt.source_timestamp_ms == 2_000
    assert receipt.boundary == boundary


def _set_platform_usable(reducer: RadarReducer, usable: bool) -> None:
    reducer.platform.platform_subscription_acknowledged = usable
    reducer.platform.public_methods_subscription_acknowledged = usable
    reducer.platform.lock_snapshot = False if usable else None
    reducer.platform.status_usable = usable
    reducer.platform.maintenance_guard = False if usable else None
    reducer.platform.public_method_guard = True if usable else None
    reducer.platform.post_status_probe = usable
    reducer.platform.fresh_index_coverage = usable


def _commit(*, causal_seq: int, monotonic_ms: int, cause: CausalCause) -> CausalCommit:
    return CausalCommit(
        boundary=FactBoundary(
            session_epoch=1,
            ingress_seq=causal_seq,
            received_monotonic_ms=monotonic_ms,
            causal_seq=causal_seq,
        ),
        cause=cause,
        failure_domain=FailureScope.COMBO_LAYER,
        affected_scopes=("GLOBAL",),
    )


def _apply_combo_change(
    reducer: RadarReducer,
    *,
    boundary: FactBoundary,
    previous_change_id: int,
    change_id: int,
    asks: list[list[str]] | None = None,
) -> None:
    book = reducer.combo_books["BTC-COMBO"]
    payload: dict[str, object] = {
        "type": "change",
        "instrument_name": "BTC-COMBO",
        "prev_change_id": previous_change_id,
        "change_id": change_id,
        "timestamp": 1_000_000 + change_id,
        "bids": [],
        "asks": asks or [],
    }
    book.apply(payload, boundary.received_monotonic_ms)
    reducer.accepted_book_receipts["BTC-COMBO"] = AcceptedBookReceipt(
        instrument_name="BTC-COMBO",
        snapshot_kind="change",
        prev_change_id=previous_change_id,
        change_id=change_id,
        source_timestamp_ms=1_000_000 + change_id,
        session_epoch=1,
        subscription_generation=1,
        boundary=boundary,
    )


def _shadow_system(
    tmp_path: Path,
) -> tuple[RadarReducer, FixedContractShadowRuntimeAdapter, FixedContractShadowOwner]:
    policies = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-fixed-public-shadow-radar.json",
        underwriting_path=ROOT / "policies/short-vol-fixed-public-shadow-underwriting.json",
        position_path=ROOT / "policies/short-vol-fixed-public-shadow-position.json",
        radar_identity=RADAR_POLICY_IDENTITY,
        underwriting_identity=UNDERWRITING_POLICY_IDENTITY,
        position_identity=POSITION_POLICY_IDENTITY,
    )
    runtime_identity = "sha256:" + "b" * 64
    bindings = RuntimeBindings(
        code_identity="a" * 40,
        runtime_identity=runtime_identity,
        radar_policy_identity=RADAR_POLICY_IDENTITY,
        underwriting_policy_identity=UNDERWRITING_POLICY_IDENTITY,
        position_policy_identity=POSITION_POLICY_IDENTITY,
        underwriting_position_contract_digest=UNDERWRITING_CONTRACT_DIGEST,
        outcome_contract_digest=OUTCOME_CONTRACT_DIGEST,
    )
    downstream = tmp_path / "downstream"
    radar = tmp_path / "radar"
    downstream.mkdir()
    radar.mkdir()
    owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        writer=DownstreamEvidenceWriter(downstream, bindings=bindings),
    )
    owner.open_enrollment(
        DownstreamFactBoundary(
            code_identity="a" * 40,
            runtime_identity=runtime_identity,
            session_epoch=1,
            ingress_seq=0,
            received_monotonic_ms=90,
            causal_seq=0,
        )
    )
    owner.close_enrollment(
        DownstreamFactBoundary(
            code_identity="a" * 40,
            runtime_identity=runtime_identity,
            session_epoch=1,
            ingress_seq=99,
            received_monotonic_ms=1_000,
            causal_seq=99,
        )
    )
    adapter = FixedContractShadowRuntimeAdapter(owner=owner)
    reducer = RadarReducer(
        policy=policies.radar,
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            radar,
            code_identity="a" * 40,
            runtime_identity=runtime_identity,
            policy_identity=RADAR_POLICY_IDENTITY,
        ),
        runtime_identity=runtime_identity,
        shadow_adapter=adapter,
    )
    reducer.begin_session(session_epoch=1, monotonic_ms=100)
    _set_platform_usable(reducer, True)
    reducer.clock = TrustedClock.from_response(
        1_000_000,
        100,
        100,
        stale_deadline_ms=45_000,
    )
    amount = AmountMetadata(
        contract_size=Decimal("1"),
        min_trade_amount=Decimal("0.1"),
        qty_tick_size=Decimal("0.1"),
    )
    short = OptionInstrument(
        instrument_name="BTC-SHORT",
        expiration_timestamp_ms=10_000_000,
        strike=Decimal("101000"),
        option_type=OptionType.CALL,
        amount=amount,
        lifecycle_state=InstrumentLifecycleState.OPEN,
        is_active=True,
        taker_commission=Decimal("0.0003"),
    )
    long = OptionInstrument(
        instrument_name="BTC-LONG",
        expiration_timestamp_ms=10_000_000,
        strike=Decimal("102000"),
        option_type=OptionType.CALL,
        amount=amount,
        lifecycle_state=InstrumentLifecycleState.OPEN,
        is_active=True,
        taker_commission=Decimal("0.0003"),
    )
    reducer.catalog_options = {short.instrument_name: short, long.instrument_name: long}
    reducer.options = dict(reducer.catalog_options)
    reducer.option_catalog.source_complete = True
    reducer.option_catalog.complete = True
    reducer.combos["BTC-COMBO"] = ComboInstrument(
        instrument_name="BTC-COMBO",
        state="active",
        legs=(
            ComboLeg("BTC-SHORT", Decimal("1")),
            ComboLeg("BTC-LONG", Decimal("-1")),
        ),
        amount=amount,
    )
    reducer.combo_catalog.source_complete = True
    reducer.combo_catalog.complete = True
    book = ContinuousOrderBook("BTC-COMBO")
    book.apply(
        {
            "type": "snapshot",
            "instrument_name": "BTC-COMBO",
            "change_id": 10,
            "timestamp": 1_000_010,
            "bids": [["new", "300", "0.1"]],
            "asks": [["new", "301", "0.1"]],
        },
        110,
    )
    reducer.combo_books["BTC-COMBO"] = book
    first_boundary = FactBoundary(1, 1, 110, 1)
    reducer.accepted_platform_continuity_boundary = first_boundary
    reducer.accepted_book_receipts["BTC-COMBO"] = AcceptedBookReceipt(
        instrument_name="BTC-COMBO",
        snapshot_kind="snapshot",
        prev_change_id=None,
        change_id=10,
        source_timestamp_ms=1_000_010,
        session_epoch=1,
        subscription_generation=1,
        boundary=first_boundary,
    )
    reducer.accepted_index_receipt = AcceptedIndexReceipt(
        price_usdc_per_btc=Decimal("100000"),
        source_timestamp_ms=1_000_000,
        boundary=first_boundary,
    )
    reducer.tickers["BTC-SHORT"] = TickerState(
        forward_usdc=Decimal("100000"),
        underlying_index="index_price",
        source_timestamp_ms=1_000_000,
        signed_delta=Decimal("0.2"),
        mark_iv_fraction=Decimal("0.5"),
    )
    tracker = EpisodeTracker(
        runtime_identity=runtime_identity,
        policy_identity=RADAR_POLICY_IDENTITY,
        instrument_name="BTC-SHORT",
    )
    tracker.state = TrackerState.ACTIVE
    tracker.episode_id = f"{runtime_identity}:{RADAR_POLICY_IDENTITY}:BTC-SHORT:1"
    tracker.activation_band_id = policies.radar.tte_bands[0].band_id
    tracker.activation_causal_seq = 1
    reducer.trackers["BTC-SHORT"] = tracker
    reducer.option_books = {
        "BTC-SHORT": ContinuousOrderBook("BTC-SHORT"),
        "BTC-LONG": ContinuousOrderBook("BTC-LONG"),
    }
    return reducer, adapter, owner


def _activate_real_episode(reducer: RadarReducer) -> str:
    instrument_name = "BTC-SHORT"
    rule = reducer.policy.tte_bands[0].option_rules[OptionType.CALL]
    tracker = EpisodeTracker(
        runtime_identity=reducer.runtime_identity,
        policy_identity=reducer.policy.identity,
        instrument_name=instrument_name,
    )
    separation_ms = max(rule.minimum_separation_ms, 1)
    activated: str | None = None
    for index in range(rule.activation_observation_count):
        causal_seq = index + 1
        trusted_ms = 1_000_000 + index * separation_ms
        transition = tracker.observe(
            DetectorObservation(
                causal_seq=causal_seq,
                trusted_time=TimeInterval(trusted_ms, trusted_ms),
                band_id=reducer.policy.tte_bands[0].band_id,
                richness=DecimalInterval(rule.activation_ratio, rule.activation_ratio),
            ),
            rule,
        )
        activated = transition.activated_episode_id or activated
    assert activated is not None
    assert tracker.episode_id == (
        f"{reducer.runtime_identity}:{reducer.policy.identity}:"
        f"{instrument_name}:{rule.activation_observation_count}"
    )
    reducer.trackers[instrument_name] = tracker
    return activated


@pytest.mark.parametrize(
    ("projection", "expected_atomic_state"),
    (
        ("no_combo", "NO_ACTIVE_COMBO"),
        ("quoted_unknown", "PUBLIC_ATOMIC_QUOTE_AVAILABLE"),
    ),
)
def test_real_episode_identity_round_trips_without_economic_action(
    tmp_path: Path,
    projection: str,
    expected_atomic_state: str,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    reducer.trackers.clear()
    episode_identity = _activate_real_episode(reducer)
    if projection == "no_combo":
        reducer.combos.clear()
        reducer.combo_books.clear()
        reducer.accepted_book_receipts.clear()
    else:
        reducer.tickers.clear()

    activation_seq = (
        reducer.policy.tte_bands[0].option_rules[OptionType.CALL].activation_observation_count
    )
    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=activation_seq,
            monotonic_ms=120,
            cause=CausalCause.COMBO_BOOK_CHANGED,
        ),
    )

    assert intents == ()
    (facts,) = adapter._underwriting_by_scope.values()
    assert facts.active_episode_identity == episode_identity
    assert facts.short_leg_instrument_name == "BTC-SHORT"
    assert facts.atomic_state == expected_atomic_state
    assert [value["object_kind"] for value in owner.writer.objects] == [
        "UNDERWRITING_AVAILABILITY_EVALUATION"
    ]


def test_inactive_underwriting_scope_transitions_once_then_stays_settled(
    tmp_path: Path,
) -> None:
    reducer, adapter, _owner = _shadow_system(tmp_path)
    reducer.trackers.clear()
    _activate_real_episode(reducer)
    active_commit = _commit(
        causal_seq=2,
        monotonic_ms=120,
        cause=CausalCause.COMBO_BOOK_CHANGED,
    )
    active = adapter._project_underwriting(
        reducer,
        active_commit,
        adapter._boundary(reducer, active_commit.boundary),
    )
    assert len(active) == 1
    assert active[0].active_episode_identity is not None

    reducer.trackers.clear()
    inactive_commit = _commit(
        causal_seq=3,
        monotonic_ms=130,
        cause=CausalCause.TICKER_APPLIED,
    )
    (inactive,) = adapter._project_underwriting(
        reducer,
        inactive_commit,
        adapter._boundary(reducer, inactive_commit.boundary),
    )
    assert inactive.active_episode_identity is None

    unrelated_commit = _commit(
        causal_seq=4,
        monotonic_ms=140,
        cause=CausalCause.TICKER_APPLIED,
    )
    assert (
        adapter._project_underwriting(
            reducer,
            unrelated_commit,
            adapter._boundary(reducer, unrelated_commit.boundary),
        )
        == ()
    )
    assert adapter._underwriting_by_scope[inactive.radar_scope_identity] is inactive


def test_workbench_underwriting_metadata_reuses_unchanged_snapshot(
    tmp_path: Path,
) -> None:
    reducer, adapter, _owner = _shadow_system(tmp_path)
    reducer.trackers.clear()
    _activate_real_episode(reducer)
    commit = _commit(
        causal_seq=2,
        monotonic_ms=120,
        cause=CausalCause.COMBO_BOOK_CHANGED,
    )
    adapter._project_underwriting(
        reducer,
        commit,
        adapter._boundary(reducer, commit.boundary),
    )

    first = adapter.workbench_underwriting_metadata()
    second = adapter.workbench_underwriting_metadata()

    assert first
    assert second is first


@pytest.mark.parametrize(
    "variant",
    ("runtime", "policy", "instrument", "activation_seq", "truncated"),
)
def test_atomic_scope_rejects_unbound_radar_episode_before_economic_action(
    tmp_path: Path,
    variant: str,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    reducer.trackers.clear()
    exact = _activate_real_episode(reducer)
    tracker = reducer.trackers["BTC-SHORT"]
    replacements = {
        "runtime": exact.replace(reducer.runtime_identity, "sha256:" + "c" * 64, 1),
        "policy": exact.replace(reducer.policy.identity, "sha256:" + "d" * 64, 1),
        "instrument": exact.replace("BTC-SHORT", "BTC-OTHER", 1),
        "activation_seq": exact.rsplit(":", 1)[0] + ":1",
        "truncated": exact[:-1],
    }
    tracker.episode_id = replacements[variant]

    with pytest.raises(ValueError):
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=2,
                monotonic_ms=120,
                cause=CausalCause.COMBO_BOOK_CHANGED,
            ),
        )
    assert owner.writer.objects == ()


def _downstream_source(seed: str) -> SourceFact:
    boundary = DownstreamFactBoundary(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        session_epoch=1,
        ingress_seq=1,
        received_monotonic_ms=110,
        causal_seq=1,
    )
    return SourceFact(canonical_identity(seed, boundary.as_object()), boundary)


def test_close_amount_missing_is_unknown_unless_an_earlier_gate_is_known_unexecutable(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    amount = AmountMetadata(
        contract_size=Decimal("1"),
        min_trade_amount=Decimal("0.1"),
        qty_tick_size=Decimal("0.1"),
    )
    short = _OptionSource(
        OptionInstrument(
            instrument_name="BTC-SHORT",
            expiration_timestamp_ms=10_000_000,
            strike=Decimal("101000"),
            option_type=OptionType.CALL,
            amount=None,
        ),
        canonical_identity("ShortIdentity"),
        _downstream_source("ShortSource"),
    )
    long = _OptionSource(
        OptionInstrument(
            instrument_name="BTC-LONG",
            expiration_timestamp_ms=10_000_000,
            strike=Decimal("102000"),
            option_type=OptionType.CALL,
            amount=amount,
        ),
        canonical_identity("LongIdentity"),
        _downstream_source("LongSource"),
    )

    assert _option_availability(short, long, Decimal("0.1")) is CloseOptionAvailability.UNKNOWN

    inactive_short = _OptionSource(
        OptionInstrument(
            instrument_name="BTC-SHORT",
            expiration_timestamp_ms=10_000_000,
            strike=Decimal("101000"),
            option_type=OptionType.CALL,
            amount=None,
            lifecycle_state=InstrumentLifecycleState.INACTIVE,
            is_active=False,
        ),
        short.semantic_identity,
        short.source,
    )
    assert (
        _option_availability(inactive_short, long, Decimal("0.1"))
        is CloseOptionAvailability.UNEXECUTABLE
    )

    reducer = _reducer(tmp_path, policy_factory)
    combo = _ComboSource(
        ComboInstrument(
            instrument_name="BTC-COMBO",
            state="active",
            legs=(
                ComboLeg("BTC-SHORT", Decimal("1")),
                ComboLeg("BTC-LONG", Decimal("-1")),
            ),
            amount=None,
        ),
        canonical_identity("ComboIdentity"),
        _downstream_source("ComboSource"),
    )
    source = _downstream_source("ComboBookSource")
    witness_identity = canonical_identity(
        "SubscriptionAdmissionRefreshSourceIdentity",
        source.boundary.runtime_identity,
        1,
        1,
        combo.semantic_identity,
        "snapshot",
        None,
        10,
        1_000_010,
        source.boundary.as_object(),
    )
    witness = SubscriptionAdmissionRefreshWitness(
        source_identity=witness_identity,
        boundary=source.boundary,
        canonical_combo_identity=combo.semantic_identity,
        instrument_name="BTC-COMBO",
        change_id=10,
        source_timestamp_ms=1_000_010,
        snapshot_kind="snapshot",
        session_epoch=1,
        subscription_generation=1,
        prev_change_id=None,
    )
    assert (
        _atomic_availability(reducer, combo, witness, Decimal("0.1"))
        is CloseAtomicAvailability.UNKNOWN
    )


def test_previously_active_combo_book_gap_is_known_discontinuity(
    tmp_path: Path,
) -> None:
    reducer, _adapter, _owner = _shadow_system(tmp_path)
    amount = reducer.options["BTC-SHORT"].amount
    assert amount is not None
    short = _OptionSource(
        reducer.options["BTC-SHORT"],
        canonical_identity("ShortIdentity"),
        _downstream_source("ShortSource"),
    )
    long = _OptionSource(
        reducer.options["BTC-LONG"],
        canonical_identity("LongIdentity"),
        _downstream_source("LongSource"),
    )
    combo = _ComboSource(
        reducer.combos["BTC-COMBO"],
        canonical_identity("ComboIdentity"),
        _downstream_source("ComboSource"),
    )
    ticker = TickerState(
        forward_usdc=Decimal("100000"),
        underlying_index="index_price",
        source_timestamp_ms=1_000_000,
        signed_delta=Decimal("0.2"),
        mark_iv_fraction=Decimal("0.5"),
    )
    assert (
        _required_sources_continuous(
            platform_current=True,
            trusted=TimeInterval(1_000_000, 1_000_001),
            index=Decimal("100000"),
            ticker=ticker,
            short=short,
            long=long,
            combo=combo,
            witness=None,
            atomic_availability=CloseAtomicAvailability.UNKNOWN,
            previously_accepted_combo_quote=False,
            previously_accepted_index=False,
            previously_accepted_ticker=False,
        )
        is None
    )
    assert (
        _required_sources_continuous(
            platform_current=True,
            trusted=TimeInterval(1_000_000, 1_000_001),
            index=Decimal("100000"),
            ticker=ticker,
            short=short,
            long=long,
            combo=combo,
            witness=None,
            atomic_availability=CloseAtomicAvailability.UNKNOWN,
            previously_accepted_combo_quote=True,
            previously_accepted_index=True,
            previously_accepted_ticker=True,
        )
        is False
    )
    assert (
        _required_sources_continuous(
            platform_current=True,
            trusted=TimeInterval(10_000_000, 10_000_001),
            index=Decimal("100000"),
            ticker=ticker,
            short=short,
            long=long,
            combo=combo,
            witness=None,
            atomic_availability=CloseAtomicAvailability.UNKNOWN,
            previously_accepted_combo_quote=True,
            previously_accepted_index=True,
            previously_accepted_ticker=True,
            natural_terminal_boundary_reached=True,
        )
        is False
    )
    assert (
        _required_sources_continuous(
            platform_current=True,
            trusted=TimeInterval(1_000_000, 1_000_001),
            index=None,
            ticker=ticker,
            short=short,
            long=long,
            combo=combo,
            witness=None,
            atomic_availability=CloseAtomicAvailability.UNKNOWN,
            previously_accepted_combo_quote=False,
            previously_accepted_index=False,
            previously_accepted_ticker=False,
        )
        is None
    )
    assert (
        _required_sources_continuous(
            platform_current=True,
            trusted=TimeInterval(1_000_000, 1_000_001),
            index=None,
            ticker=ticker,
            short=short,
            long=long,
            combo=combo,
            witness=None,
            atomic_availability=CloseAtomicAvailability.UNKNOWN,
            previously_accepted_combo_quote=False,
            previously_accepted_index=True,
            previously_accepted_ticker=False,
        )
        is False
    )
    assert (
        _required_sources_continuous(
            platform_current=True,
            trusted=TimeInterval(1_000_000, 1_000_001),
            index=None,
            ticker=ticker,
            short=short,
            long=long,
            combo=combo,
            witness=None,
            atomic_availability=CloseAtomicAvailability.UNKNOWN,
            previously_accepted_combo_quote=False,
            previously_accepted_index=True,
            previously_accepted_ticker=False,
            natural_terminal_boundary_reached=True,
        )
        is False
    )
    assert (
        _required_sources_continuous(
            platform_current=True,
            trusted=TimeInterval(1_000_000, 1_000_001),
            index=Decimal("100000"),
            ticker=None,
            short=short,
            long=long,
            combo=combo,
            witness=None,
            atomic_availability=CloseAtomicAvailability.UNKNOWN,
            previously_accepted_combo_quote=False,
            previously_accepted_index=False,
            previously_accepted_ticker=False,
        )
        is None
    )
    assert (
        _required_sources_continuous(
            platform_current=True,
            trusted=TimeInterval(1_000_000, 1_000_001),
            index=Decimal("100000"),
            ticker=None,
            short=short,
            long=long,
            combo=combo,
            witness=None,
            atomic_availability=CloseAtomicAvailability.UNKNOWN,
            previously_accepted_combo_quote=False,
            previously_accepted_index=False,
            previously_accepted_ticker=True,
            natural_terminal_boundary_reached=True,
        )
        is False
    )


@pytest.mark.parametrize(
    "state",
    ("inactive", "settlement", "delivered", "archivized"),
)
def test_known_nonactive_combo_lifecycle_is_atomic_unavailability(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    state: str,
) -> None:
    reducer = _reducer(tmp_path, policy_factory)
    combo = _ComboSource(
        ComboInstrument(
            instrument_name="BTC-COMBO",
            state=state,
            legs=reducer.combos["BTC-COMBO"].legs,
            amount=reducer.combos["BTC-COMBO"].amount,
        ),
        canonical_identity("ComboIdentity"),
        _downstream_source("ComboSource"),
    )

    assert (
        _atomic_availability(reducer, combo, None, Decimal("0.1"))
        is CloseAtomicAvailability.KNOWN_UNAVAILABLE
    )


def _rest_combo_book(
    *,
    change_id: int = 10,
    bid_price: str = "300",
    ask_price: str = "301",
) -> dict[str, object]:
    return {
        "instrument_name": "BTC-COMBO",
        "state": "open",
        "change_id": change_id,
        "timestamp": 1_000_010,
        "bids": [[bid_price, "0.1"]],
        "asks": [[ask_price, "0.1"]],
    }


def _terminal_outcomes(owner: FixedContractShadowOwner) -> list[str]:
    outcomes: list[str] = []
    for value in owner.writer.objects:
        if value["object_kind"] != "ADMISSION_ATTEMPT_TERMINAL":
            continue
        payload = value["payload"]
        assert isinstance(payload, dict)
        outcomes.append(str(payload["terminal_outcome"]))
    return outcomes


def _install_shadow_intent(
    reducer: RadarReducer,
    intent: ShadowRpcIntent,
) -> PendingRpc:
    reducer._schedule_shadow_intents((intent,))
    (request,) = reducer._take_commands()
    return request


def _mark_shadow_request_sent(
    reducer: RadarReducer,
    *,
    request_id: int,
    boundary: FactBoundary,
) -> None:
    reducer._apply_send_control(
        SendControlEvent(
            kind=SendControlKind.SEND_COMPLETED,
            request_id=request_id,
            boundary_monotonic_ms=boundary.received_monotonic_ms,
        ),
        boundary=boundary,
    )


def _set_trusted_source_time(
    reducer: RadarReducer,
    *,
    server_ms: int,
    monotonic_ms: int,
) -> None:
    reducer.clock = TrustedClock.from_response(
        server_ms,
        monotonic_ms,
        monotonic_ms,
        stale_deadline_ms=45_000,
    )
    receipt_boundary = FactBoundary(
        1,
        reducer._last_ingress_seq,
        monotonic_ms,
        reducer.causal_seq,
    )
    reducer.accepted_index_receipt = AcceptedIndexReceipt(
        price_usdc_per_btc=Decimal("100000"),
        source_timestamp_ms=server_ms,
        boundary=receipt_boundary,
    )
    reducer.tickers["BTC-SHORT"] = replace(
        reducer.tickers["BTC-SHORT"],
        source_timestamp_ms=server_ms,
    )
    reducer.accepted_platform_continuity_boundary = receipt_boundary


def _object_payloads(
    owner: FixedContractShadowOwner,
    kind: str,
) -> list[dict[str, object]]:
    payloads: list[tuple[int, dict[str, object]]] = []
    for value in owner.writer.objects:
        if value["object_kind"] != kind:
            continue
        payload = value["payload"]
        boundary = value["fact_boundary"]
        assert isinstance(payload, dict)
        assert isinstance(boundary, dict)
        causal_seq = boundary["causal_seq"]
        assert isinstance(causal_seq, int)
        payloads.append((causal_seq, payload))
    return [payload for _causal_seq, payload in sorted(payloads, key=lambda item: item[0])]


def _set_natural_lifecycle_ready(reducer: RadarReducer) -> None:
    short = replace(
        reducer.options["BTC-SHORT"],
        lifecycle_state=InstrumentLifecycleState.DELIVERED,
        is_active=False,
    )
    long = replace(
        reducer.options["BTC-LONG"],
        lifecycle_state=InstrumentLifecycleState.ARCHIVIZED,
        is_active=False,
    )
    reducer.options = {"BTC-SHORT": short, "BTC-LONG": long}
    reducer.catalog_options = dict(reducer.options)


def _replace_entry_bid(reducer: RadarReducer, price: str) -> None:
    book = ContinuousOrderBook("BTC-COMBO")
    book.apply(
        {
            "type": "snapshot",
            "instrument_name": "BTC-COMBO",
            "change_id": 10,
            "timestamp": 1_000_010,
            "bids": [["new", price, "0.1"]],
            "asks": [["new", "301", "0.1"]],
        },
        110,
    )
    reducer.combo_books["BTC-COMBO"] = book


def _admit_and_latch_close(
    reducer: RadarReducer,
    adapter: FixedContractShadowRuntimeAdapter,
) -> int:
    (admission_intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )
    adapter.on_request_sent(
        request_id=admission_intent.request_id,
        boundary=FactBoundary(1, 2, 120, 2),
    )
    _apply_combo_change(
        reducer,
        boundary=FactBoundary(1, 3, 130, 3),
        previous_change_id=10,
        change_id=11,
    )
    adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=3, monotonic_ms=130, cause=CausalCause.COMBO_BOOK_FACT),
    )
    _set_platform_usable(reducer, False)
    _apply_combo_change(
        reducer,
        boundary=FactBoundary(1, 4, 140, 4),
        previous_change_id=11,
        change_id=12,
    )
    (post_close_intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=4, monotonic_ms=140, cause=CausalCause.COMBO_BOOK_FACT),
    )
    return post_close_intent.request_id


def _reject_and_latch_close(
    reducer: RadarReducer,
    adapter: FixedContractShadowRuntimeAdapter,
) -> int:
    _replace_entry_bid(reducer, "170")
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
        )
        == ()
    )
    _set_platform_usable(reducer, False)
    _apply_combo_change(
        reducer,
        boundary=FactBoundary(1, 2, 120, 2),
        previous_change_id=10,
        change_id=11,
    )
    (post_close_intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=2, monotonic_ms=120, cause=CausalCause.COMBO_BOOK_FACT),
    )
    return post_close_intent.request_id


@pytest.mark.parametrize(
    ("rejected", "outcome_kind"),
    (
        (False, "SHADOW_OUTCOME"),
        (True, "REJECTED_COUNTERFACTUAL_OUTCOME"),
    ),
)
def test_ordinary_post_close_failure_settles_natural_mature_unknown(
    tmp_path: Path,
    rejected: bool,
    outcome_kind: str,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    request_id = (
        _reject_and_latch_close(reducer, adapter)
        if rejected
        else _admit_and_latch_close(reducer, adapter)
    )
    _set_natural_lifecycle_ready(reducer)

    adapter.on_request_failure(
        request_id=request_id,
        terminal_state=RpcState.ERROR,
        boundary=FactBoundary(1, 5, 150, 5),
    )

    outcome = next(value for value in owner.writer.objects if value["object_kind"] == outcome_kind)
    payload = outcome["payload"]
    assert isinstance(payload, dict)
    assert payload["terminal_state"] == "MATURE_UNKNOWN"
    assert payload["selected_exit_identity"] is None
    assert payload["post_close_attempt_terminal_owner"] == "ORDINARY"
    witnesses = payload["natural_terminal_lifecycle_witnesses"]
    assert isinstance(witnesses, list)
    assert [value["canonical_leg_role"] for value in witnesses] == ["SHORT", "LONG"]
    pair = next(
        value
        for value in owner.writer.objects
        if value["object_kind"] == "ALIGNED_POLICY_NO_TRADE_PAIR"
    )
    pair_payload = pair["payload"]
    assert isinstance(pair_payload, dict)
    assert pair_payload["terminal_state"] == "MATURE_UNKNOWN"
    assert pair_payload["comparison_availability"] == "UNKNOWN"


def test_first_close_same_boundary_as_natural_lifecycle_cannot_mature(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    (admission_intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )
    adapter.on_request_sent(
        request_id=admission_intent.request_id,
        boundary=FactBoundary(1, 2, 120, 2),
    )
    _apply_combo_change(
        reducer,
        boundary=FactBoundary(1, 3, 130, 3),
        previous_change_id=10,
        change_id=11,
    )
    adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=3, monotonic_ms=130, cause=CausalCause.COMBO_BOOK_FACT),
    )
    _set_natural_lifecycle_ready(reducer)
    _set_platform_usable(reducer, False)
    _apply_combo_change(
        reducer,
        boundary=FactBoundary(1, 4, 140, 4),
        previous_change_id=11,
        change_id=12,
    )
    adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=4, monotonic_ms=140, cause=CausalCause.COMBO_BOOK_FACT),
    )

    assert not any(value["object_kind"] == "SHADOW_OUTCOME" for value in owner.writer.objects)


def test_equal_change_id_with_different_rest_depth_is_unknown_not_entry(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    (intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )
    sent = FactBoundary(1, 2, 120, 2)
    adapter.on_request_sent(request_id=intent.request_id, boundary=sent)

    adapter.on_rpc_response(
        request_id=intent.request_id,
        result=_rest_combo_book(bid_price="299"),
        sent_boundary=sent,
        boundary=FactBoundary(1, 3, 130, 3),
    )

    kinds = [str(value["object_kind"]) for value in owner.writer.objects]
    assert "SHADOW_ENTRY" not in kinds
    assert _terminal_outcomes(owner) == ["UNKNOWN_CONSUMED"]


def test_admission_response_reprojects_contemporaneous_ancillary_facts(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    (intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )
    sent = FactBoundary(1, 2, 120, 2)
    adapter.on_request_sent(request_id=intent.request_id, boundary=sent)

    prior = reducer.tickers["BTC-SHORT"]
    reducer.tickers["BTC-SHORT"] = TickerState(
        forward_usdc=prior.forward_usdc,
        underlying_index=prior.underlying_index,
        source_timestamp_ms=prior.source_timestamp_ms,
        signed_delta=None,
        mark_iv_fraction=prior.mark_iv_fraction,
    )
    adapter.on_rpc_response(
        request_id=intent.request_id,
        result=_rest_combo_book(),
        sent_boundary=sent,
        boundary=FactBoundary(1, 3, 130, 3),
    )

    kinds = [str(value["object_kind"]) for value in owner.writer.objects]
    assert "SHADOW_ENTRY" not in kinds
    assert _terminal_outcomes(owner) == ["KNOWN_INVALIDATED_BEFORE_REFRESH"]
    invalidation = next(
        value for value in owner.writer.objects if value["object_kind"] == "CANDIDATE_INVALIDATION"
    )
    payload = invalidation["payload"]
    assert isinstance(payload, dict)
    assert payload["primary_reason"] == ("SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN")


def test_retired_admission_request_keeps_typed_source_gap_semantics(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    (intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )
    sent = FactBoundary(1, 2, 120, 2)
    adapter.on_request_sent(request_id=intent.request_id, boundary=sent)

    adapter.on_request_failure(
        request_id=intent.request_id,
        terminal_state=RpcState.RETIRED,
        boundary=FactBoundary(1, 3, 130, 3),
    )

    assert _terminal_outcomes(owner) == ["KNOWN_INVALIDATED_BEFORE_REFRESH"]
    invalidation = next(
        value for value in owner.writer.objects if value["object_kind"] == "CANDIDATE_INVALIDATION"
    )
    payload = invalidation["payload"]
    assert isinstance(payload, dict)
    assert payload["primary_reason"] == ("SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN")


def test_fatal_control_may_supersede_pending_stop_control_once(
    tmp_path: Path,
) -> None:
    _reducer_value, adapter, _owner = _shadow_system(tmp_path)
    emergency: dict[str, object] = {
        "control_kind": "AUTHORIZED_EMERGENCY_STOP",
        "reason": "USER_REQUEST",
    }
    fatal: dict[str, object] = {
        "control_kind": "PROCESS_FAILURE",
        "failure_kind": "FATAL_RUNTIME",
    }

    adapter.configure_terminal_control(
        terminal_disposition="AUTHORIZED_EMERGENCY_STOP",
        terminal_source=emergency,
    )
    adapter.configure_terminal_control(
        terminal_disposition="PROCESS_FAILURE",
        terminal_source=fatal,
    )

    assert adapter._configured_terminal_control == ("PROCESS_FAILURE", fatal)
    with pytest.raises(ValueError, match="only fatal failure"):
        adapter.configure_terminal_control(
            terminal_disposition="PROCESS_FAILURE",
            terminal_source=fatal,
        )


def test_platform_currentness_budget_is_inclusive_then_unknown_at_budget_plus_one(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    observed = FactBoundary(1, 1, 1_000, 1)
    reducer.accepted_platform_continuity_boundary = observed
    budget_ms = owner.policies.underwriting.platform_currentness_budget_ms

    def boundary(age_ms: int) -> DownstreamFactBoundary:
        return DownstreamFactBoundary(
            code_identity=reducer.code_identity,
            runtime_identity=reducer.runtime_identity,
            session_epoch=1,
            ingress_seq=2,
            received_monotonic_ms=observed.received_monotonic_ms + age_ms,
            causal_seq=2,
        )

    assert adapter._platform_currentness(
        reducer,
        boundary(budget_ms),
        budget_ms=budget_ms,
    )
    assert (
        adapter._platform_currentness(
            reducer,
            boundary(budget_ms + 1),
            budget_ms=budget_ms,
        )
        is None
    )
    _set_platform_usable(reducer, False)
    assert (
        adapter._platform_currentness(
            reducer,
            boundary(budget_ms + 1),
            budget_ms=budget_ms,
        )
        is False
    )


def test_concrete_adapter_runs_candidate_admission_position_and_future_exit_once(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)

    (admission_intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )
    assert admission_intent.purpose.value == "ADMISSION_REFRESH"
    adapter.on_request_sent(
        request_id=admission_intent.request_id,
        boundary=FactBoundary(1, 2, 120, 2),
    )

    admission_boundary = FactBoundary(1, 3, 130, 3)
    _apply_combo_change(
        reducer,
        boundary=admission_boundary,
        previous_change_id=10,
        change_id=11,
    )
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=3,
                monotonic_ms=130,
                cause=CausalCause.COMBO_BOOK_FACT,
            ),
        )
        == ()
    )
    kinds = [str(value["object_kind"]) for value in owner.writer.objects]
    assert kinds.count("SHADOW_ENTRY") == 1

    _set_platform_usable(reducer, False)
    close_boundary = FactBoundary(1, 4, 140, 4)
    _apply_combo_change(
        reducer,
        boundary=close_boundary,
        previous_change_id=11,
        change_id=12,
    )
    (post_close_intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=4, monotonic_ms=140, cause=CausalCause.COMBO_BOOK_FACT),
    )
    assert post_close_intent.purpose.value == "POST_CLOSE_REFRESH"

    _set_platform_usable(reducer, True)
    exit_boundary = FactBoundary(1, 5, 150, 5)
    _apply_combo_change(
        reducer,
        boundary=exit_boundary,
        previous_change_id=12,
        change_id=13,
        asks=[["delete", "301", "0"], ["new", "302", "0.1"]],
    )
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=5,
                monotonic_ms=150,
                cause=CausalCause.COMBO_BOOK_CHANGED,
            ),
        )
        == ()
    )
    kinds = [str(value["object_kind"]) for value in owner.writer.objects]
    assert kinds.count("SHADOW_ENTRY") == 1
    assert kinds.count("POSITION_ACTION") == 2
    assert kinds.count("POST_CLOSE_ATTEMPT_SCHEDULED") == 1
    assert kinds.count("POST_CLOSE_ATTEMPT_TERMINAL") == 1
    assert kinds.count("SHADOW_CLOSE_OPPORTUNITY") == 1
    assert kinds.count("SHADOW_OUTCOME") == 1

    before = tuple(owner.writer.objects)
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=5,
                monotonic_ms=150,
                cause=CausalCause.COMBO_BOOK_FACT,
            ),
        )
        == ()
    )
    assert tuple(owner.writer.objects) == before


def test_time_polls_use_discrete_business_classes_and_exact_crossings_once(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    (admission_intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )

    before_same_class = tuple(owner.writer.objects)
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(causal_seq=2, monotonic_ms=111, cause=CausalCause.TIME_BOUNDARY),
        )
        == ()
    )
    assert tuple(owner.writer.objects) == before_same_class

    expiry_ms = reducer.options["BTC-SHORT"].expiration_timestamp_ms
    admission_cutoff_ms = expiry_ms - 1_800_000
    _set_trusted_source_time(
        reducer,
        server_ms=admission_cutoff_ms - 10,
        monotonic_ms=111,
    )
    reducer._causal_seq = 2
    reducer._last_boundary_monotonic_ms = 111
    cutoff_crossing = adapter.next_time_boundary_monotonic_ms(
        reducer=reducer,
        after_monotonic_ms=111,
    )
    assert cutoff_crossing is not None
    assert reducer.next_shadow_time_boundary_monotonic_ms(after_monotonic_ms=111) == cutoff_crossing
    assert reducer.clock is not None
    assert reducer.clock.interval_at(cutoff_crossing - 1).upper_ms < admission_cutoff_ms
    assert reducer.clock.interval_at(cutoff_crossing).upper_ms >= admission_cutoff_ms

    reducer._last_wire_received_ms = cutoff_crossing
    reducer.advance_time(cutoff_crossing)
    invalidations = _object_payloads(owner, "CANDIDATE_INVALIDATION")
    assert len(invalidations) == 1
    reasons = invalidations[0]["ordered_applicable_reason_vector"]
    assert isinstance(reasons, list)
    assert "LATEST_ADMISSION_BOUNDARY_REACHED" in reasons
    after_cutoff = tuple(owner.writer.objects)
    reducer._last_wire_received_ms = cutoff_crossing + 1
    reducer.advance_time(cutoff_crossing + 1)
    assert tuple(owner.writer.objects) == after_cutoff
    assert admission_intent.request_id in reducer._reserved_shadow_request_ids


def test_position_latest_exit_and_expiry_cross_at_exact_time_once(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    (admission_intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )
    assert admission_intent.purpose.value == "ADMISSION_REFRESH"
    admission_boundary = FactBoundary(1, 2, 120, 2)
    _apply_combo_change(
        reducer,
        boundary=admission_boundary,
        previous_change_id=10,
        change_id=11,
    )
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=2,
                monotonic_ms=120,
                cause=CausalCause.COMBO_BOOK_FACT,
            ),
        )
        == ()
    )

    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(causal_seq=3, monotonic_ms=130, cause=CausalCause.TIME_BOUNDARY),
        )
        == ()
    )
    assert len(_object_payloads(owner, "POSITION_ACTION")) == 1
    before_same_class = tuple(owner.writer.objects)
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(causal_seq=4, monotonic_ms=131, cause=CausalCause.TIME_BOUNDARY),
        )
        == ()
    )
    assert tuple(owner.writer.objects) == before_same_class

    expiry_ms = reducer.options["BTC-SHORT"].expiration_timestamp_ms
    latest_exit_ms = expiry_ms - owner.policies.position.latest_exit_lead_ms
    _set_trusted_source_time(
        reducer,
        server_ms=latest_exit_ms - 10,
        monotonic_ms=131,
    )
    reducer._causal_seq = 4
    reducer._last_boundary_monotonic_ms = 131
    latest_crossing = adapter.next_time_boundary_monotonic_ms(
        reducer=reducer,
        after_monotonic_ms=131,
    )
    assert latest_crossing is not None
    assert reducer.clock is not None
    assert reducer.clock.interval_at(latest_crossing - 1).upper_ms < latest_exit_ms
    assert reducer.clock.interval_at(latest_crossing).upper_ms >= latest_exit_ms

    reducer._last_wire_received_ms = latest_crossing
    reducer.advance_time(latest_crossing)
    position_actions = _object_payloads(owner, "POSITION_ACTION")
    assert len(position_actions) == 2
    assert position_actions[-1]["primary_close_reason"] == "LATEST_EXIT_BOUNDARY_REACHED"
    assert position_actions[-1]["secondary_close_reasons"] == ["PLATFORM_OR_SOURCE_DISCONTINUITY"]
    after_latest = tuple(owner.writer.objects)
    reducer._last_wire_received_ms = latest_crossing + 1
    reducer.advance_time(latest_crossing + 1)
    assert tuple(owner.writer.objects) == after_latest

    expiry_base_ms = latest_crossing + 2
    _set_trusted_source_time(
        reducer,
        server_ms=expiry_ms - 10,
        monotonic_ms=expiry_base_ms,
    )
    reducer._last_boundary_monotonic_ms = expiry_base_ms
    expiry_crossing = adapter.next_time_boundary_monotonic_ms(
        reducer=reducer,
        after_monotonic_ms=expiry_base_ms,
    )
    assert expiry_crossing is not None
    assert reducer.clock.interval_at(expiry_crossing - 1).lower_ms < expiry_ms
    assert reducer.clock.interval_at(expiry_crossing).lower_ms >= expiry_ms

    reducer._last_wire_received_ms = expiry_crossing
    reducer.advance_time(expiry_crossing)
    position_actions = _object_payloads(owner, "POSITION_ACTION")
    assert len(position_actions) == 3
    assert position_actions[-1]["primary_close_reason"] == ("SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED")
    assert position_actions[-1]["secondary_close_reasons"] == [
        "LATEST_EXIT_BOUNDARY_REACHED",
        "PLATFORM_OR_SOURCE_DISCONTINUITY",
    ]
    after_expiry = tuple(owner.writer.objects)
    reducer._last_wire_received_ms = expiry_crossing + 1
    reducer.advance_time(expiry_crossing + 1)
    assert tuple(owner.writer.objects) == after_expiry


@pytest.mark.parametrize("deadline", ["CLOCK", "PLATFORM", "INDEX", "TICKER"])
def test_currentness_deadlines_cross_exactly_once_and_invalidate_candidate(
    tmp_path: Path,
    deadline: str,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    reducer.pending_rpcs.clear()
    reducer._commands = []
    adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )

    if deadline == "CLOCK":
        after_ms = 110
        expected_crossing_ms = 45_100
    elif deadline == "PLATFORM":
        after_ms = 100_000
        expected_crossing_ms = 100_001
        server_ms = 2_000_000
        reducer.clock = TrustedClock.from_response(
            server_ms,
            after_ms,
            after_ms,
            stale_deadline_ms=45_000,
        )
        reducer.accepted_platform_continuity_boundary = FactBoundary(
            1,
            1,
            after_ms - owner.policies.underwriting.platform_currentness_budget_ms,
            1,
        )
        reducer.accepted_index_receipt = AcceptedIndexReceipt(
            price_usdc_per_btc=Decimal("100000"),
            source_timestamp_ms=server_ms,
            boundary=FactBoundary(1, 2, after_ms, 2),
        )
        reducer.tickers["BTC-SHORT"] = replace(
            reducer.tickers["BTC-SHORT"],
            source_timestamp_ms=server_ms,
        )
    elif deadline == "INDEX":
        after_ms = 1_000
        expected_crossing_ms = 1_001
        index_receipt = reducer.accepted_index_receipt
        assert index_receipt is not None
        server_ms = (
            index_receipt.source_timestamp_ms
            + owner.policies.underwriting.index_currentness_budget_ms
            - 2
        )
        reducer.clock = TrustedClock.from_response(
            server_ms,
            after_ms,
            after_ms,
            stale_deadline_ms=45_000,
        )
        reducer.accepted_platform_continuity_boundary = FactBoundary(
            1,
            2,
            after_ms,
            2,
        )
        reducer.tickers["BTC-SHORT"] = replace(
            reducer.tickers["BTC-SHORT"],
            source_timestamp_ms=server_ms,
        )
    else:
        after_ms = 1_000
        expected_crossing_ms = 1_001
        ticker_timestamp_ms = reducer.tickers["BTC-SHORT"].source_timestamp_ms
        server_ms = (
            ticker_timestamp_ms
            + owner.policies.underwriting.option_ticker_currentness_budget_ms
            - 2
        )
        reducer.clock = TrustedClock.from_response(
            server_ms,
            after_ms,
            after_ms,
            stale_deadline_ms=45_000,
        )
        reducer.accepted_platform_continuity_boundary = FactBoundary(
            1,
            2,
            after_ms,
            2,
        )
        reducer.accepted_index_receipt = AcceptedIndexReceipt(
            price_usdc_per_btc=Decimal("100000"),
            source_timestamp_ms=server_ms,
            boundary=FactBoundary(1, 2, after_ms, 2),
        )

    if after_ms != 110:
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=2,
                monotonic_ms=after_ms,
                cause=CausalCause.TIME_BOUNDARY,
            ),
        )
    before_crossing = tuple(owner.writer.objects)
    assert (
        adapter.next_time_boundary_monotonic_ms(
            reducer=reducer,
            after_monotonic_ms=after_ms,
        )
        == expected_crossing_ms
    )

    reducer._causal_seq = 2
    reducer._last_boundary_monotonic_ms = after_ms
    reducer._last_wire_received_ms = expected_crossing_ms
    reducer.advance_time(expected_crossing_ms)
    invalidations = _object_payloads(owner, "CANDIDATE_INVALIDATION")
    assert len(invalidations) == 1
    assert tuple(owner.writer.objects) != before_crossing

    after_crossing = tuple(owner.writer.objects)
    reducer._last_wire_received_ms = expected_crossing_ms + 1
    reducer.advance_time(expected_crossing_ms + 1)
    assert tuple(owner.writer.objects) == after_crossing


def test_session_gap_settles_hold_to_close_before_first_reconnect_quote(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )
    admission_boundary = FactBoundary(1, 2, 120, 2)
    _apply_combo_change(
        reducer,
        boundary=admission_boundary,
        previous_change_id=10,
        change_id=11,
    )
    adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=2, monotonic_ms=120, cause=CausalCause.COMBO_BOOK_FACT),
    )
    adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=3, monotonic_ms=130, cause=CausalCause.TIME_BOUNDARY),
    )
    assert [
        payload["serialized_action"] for payload in _object_payloads(owner, "POSITION_ACTION")
    ] == ["HOLD"]

    saved_options = dict(reducer.options)
    saved_combos = dict(reducer.combos)
    reducer._causal_seq = 3
    reducer._last_ingress_seq = 3
    reducer._last_boundary_monotonic_ms = 130
    reducer._last_wire_received_ms = 130
    reducer._commands = []
    reducer.prepare_reconnect(CausalCause.TRANSPORT_READ_FAILURE.value)

    position_actions = _object_payloads(owner, "POSITION_ACTION")
    assert [payload["serialized_action"] for payload in position_actions] == [
        "HOLD",
        "CLOSE",
    ]
    assert position_actions[-1]["primary_close_reason"] == ("PLATFORM_OR_SOURCE_DISCONTINUITY")
    position_objects = [
        value for value in owner.writer.objects if value["object_kind"] == "POSITION_ACTION"
    ]
    gap_close_boundary = max(
        (DownstreamFactBoundary.from_object(value["fact_boundary"]) for value in position_objects),
        key=lambda boundary: boundary.causal_seq,
    )
    assert reducer.pending_rpcs == {}
    assert reducer._take_commands() == ()

    reconnect_ms = 140
    reducer.begin_session(session_epoch=2, monotonic_ms=reconnect_ms)
    reducer.pending_rpcs.clear()
    reducer._commands = []
    reducer.catalog_options = dict(saved_options)
    reducer.options = dict(saved_options)
    reducer.option_catalog.source_complete = True
    reducer.option_catalog.complete = True
    reducer.combos = dict(saved_combos)
    reducer.combo_catalog.source_complete = True
    reducer.combo_catalog.complete = True
    _set_platform_usable(reducer, True)
    reducer.clock = TrustedClock.from_response(
        1_000_030,
        reconnect_ms,
        reconnect_ms,
        stale_deadline_ms=45_000,
    )
    quote_boundary = FactBoundary(
        2,
        1,
        reconnect_ms + 1,
        gap_close_boundary.causal_seq + 1,
    )
    reducer._causal_seq = quote_boundary.causal_seq
    reducer._last_ingress_seq = quote_boundary.ingress_seq
    reducer._last_boundary_monotonic_ms = quote_boundary.received_monotonic_ms
    reducer.accepted_platform_continuity_boundary = quote_boundary
    reducer.accepted_index_receipt = AcceptedIndexReceipt(
        price_usdc_per_btc=Decimal("100000"),
        source_timestamp_ms=1_000_030,
        boundary=quote_boundary,
    )
    reducer.tickers["BTC-SHORT"] = TickerState(
        forward_usdc=Decimal("100000"),
        underlying_index="index_price",
        source_timestamp_ms=1_000_030,
        signed_delta=Decimal("0.2"),
        mark_iv_fraction=Decimal("0.5"),
    )
    reconnect_book = ContinuousOrderBook("BTC-COMBO")
    reconnect_book.apply(
        {
            "type": "snapshot",
            "instrument_name": "BTC-COMBO",
            "change_id": 20,
            "timestamp": 1_000_030,
            "bids": [["new", "300", "0.1"]],
            "asks": [["new", "302", "0.1"]],
        },
        quote_boundary.received_monotonic_ms,
    )
    reducer.combo_books["BTC-COMBO"] = reconnect_book
    reducer.accepted_book_receipts["BTC-COMBO"] = AcceptedBookReceipt(
        instrument_name="BTC-COMBO",
        snapshot_kind="snapshot",
        prev_change_id=None,
        change_id=20,
        source_timestamp_ms=1_000_030,
        session_epoch=2,
        subscription_generation=1,
        boundary=quote_boundary,
    )

    adapter.on_settled_transaction(
        reducer=reducer,
        commit=CausalCommit(
            boundary=quote_boundary,
            cause=CausalCause.COMBO_BOOK_FACT,
            failure_domain=FailureScope.COMBO_LAYER,
            affected_scopes=("GLOBAL",),
        ),
    )

    assert quote_boundary.causal_seq > gap_close_boundary.causal_seq
    assert len(_object_payloads(owner, "SHADOW_CLOSE_OPPORTUNITY")) == 1
    assert len(_object_payloads(owner, "SHADOW_OUTCOME")) == 1


@pytest.mark.parametrize("request_state", [RpcState.SCHEDULED, RpcState.SENT])
def test_candidate_subscription_winner_retires_runtime_rpc_and_late_wire_is_orphan_only(
    tmp_path: Path,
    request_state: RpcState,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    (intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )
    request = _install_shadow_intent(reducer, intent)
    next_causal = 2
    next_monotonic = 120
    if request_state is RpcState.SENT:
        _mark_shadow_request_sent(
            reducer,
            request_id=request.request_id,
            boundary=FactBoundary(1, next_causal, next_monotonic, next_causal),
        )
        next_causal += 1
        next_monotonic += 10

    winner = FactBoundary(1, next_causal, next_monotonic, next_causal)
    _apply_combo_change(
        reducer,
        boundary=winner,
        previous_change_id=10,
        change_id=11,
    )
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=next_causal,
                monotonic_ms=next_monotonic,
                cause=CausalCause.COMBO_BOOK_FACT,
            ),
        )
        == ()
    )

    lifecycle = reducer._rpc_lifecycles[request.request_id]
    assert lifecycle.state is RpcState.RETIRED
    assert lifecycle.terminal_from_state is request_state
    assert request.request_id not in reducer.pending_rpcs
    assert request.request_id not in adapter._requests
    assert _terminal_outcomes(owner) == ["ENTRY_EMITTED"]
    assert len(_object_payloads(owner, "SHADOW_ENTRY")) == 1

    after_winner = tuple(owner.writer.objects)
    late_boundary = FactBoundary(1, next_causal + 1, next_monotonic + 10, next_causal + 1)
    _mark_shadow_request_sent(
        reducer,
        request_id=request.request_id,
        boundary=late_boundary,
    )
    orphan_before = reducer.diagnostics.rpc_orphan_late_wire_count
    reducer._apply_response(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": request.request_id,
                "result": _rest_combo_book(change_id=11),
            },
            session_epoch=1,
            ingress_seq=next_causal + 2,
            received_monotonic_ms=next_monotonic + 20,
        )
    )
    assert reducer.diagnostics.rpc_orphan_late_wire_count == orphan_before + 1
    assert tuple(owner.writer.objects) == after_winner


@pytest.mark.parametrize("request_state", [RpcState.SCHEDULED, RpcState.SENT])
def test_post_close_subscription_winner_retires_runtime_rpc_and_late_wire_is_orphan_only(
    tmp_path: Path,
    request_state: RpcState,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    (admission_intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=1, monotonic_ms=110, cause=CausalCause.COMBO_BOOK_CHANGED),
    )
    _install_shadow_intent(reducer, admission_intent)
    admission_boundary = FactBoundary(1, 2, 120, 2)
    _apply_combo_change(
        reducer,
        boundary=admission_boundary,
        previous_change_id=10,
        change_id=11,
    )
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(causal_seq=2, monotonic_ms=120, cause=CausalCause.COMBO_BOOK_FACT),
        )
        == ()
    )

    _set_platform_usable(reducer, False)
    close_boundary = FactBoundary(1, 3, 130, 3)
    _apply_combo_change(
        reducer,
        boundary=close_boundary,
        previous_change_id=11,
        change_id=12,
    )
    (post_close_intent,) = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(causal_seq=3, monotonic_ms=130, cause=CausalCause.COMBO_BOOK_FACT),
    )
    request = _install_shadow_intent(reducer, post_close_intent)
    next_causal = 4
    next_monotonic = 140
    if request_state is RpcState.SENT:
        _mark_shadow_request_sent(
            reducer,
            request_id=request.request_id,
            boundary=FactBoundary(1, next_causal, next_monotonic, next_causal),
        )
        next_causal += 1
        next_monotonic += 10

    _set_platform_usable(reducer, True)
    winner = FactBoundary(1, next_causal, next_monotonic, next_causal)
    _apply_combo_change(
        reducer,
        boundary=winner,
        previous_change_id=12,
        change_id=13,
        asks=[["delete", "301", "0"], ["new", "302", "0.1"]],
    )
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=next_causal,
                monotonic_ms=next_monotonic,
                cause=CausalCause.COMBO_BOOK_FACT,
            ),
        )
        == ()
    )

    lifecycle = reducer._rpc_lifecycles[request.request_id]
    assert lifecycle.state is RpcState.RETIRED
    assert lifecycle.terminal_from_state is request_state
    assert request.request_id not in reducer.pending_rpcs
    assert request.request_id not in adapter._requests
    assert len(_object_payloads(owner, "POST_CLOSE_ATTEMPT_TERMINAL")) == 1
    assert len(_object_payloads(owner, "SHADOW_OUTCOME")) == 1

    after_winner = tuple(owner.writer.objects)
    late_boundary = FactBoundary(1, next_causal + 1, next_monotonic + 10, next_causal + 1)
    _mark_shadow_request_sent(
        reducer,
        request_id=request.request_id,
        boundary=late_boundary,
    )
    orphan_before = reducer.diagnostics.rpc_orphan_late_wire_count
    reducer._apply_response(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": request.request_id,
                "result": _rest_combo_book(change_id=13),
            },
            session_epoch=1,
            ingress_seq=next_causal + 2,
            received_monotonic_ms=next_monotonic + 20,
        )
    )
    assert reducer.diagnostics.rpc_orphan_late_wire_count == orphan_before + 1
    assert tuple(owner.writer.objects) == after_winner
