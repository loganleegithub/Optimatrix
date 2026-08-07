from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import radar_runtime.workbench as workbench_module
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
    PriceTickMetadata,
)
from radar_runtime.deribit_public import (
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
from short_vol_radar.detector import (
    DetectorObservation,
    DetectorState,
    EpisodeTracker,
    ObservationSignal,
    TrackerState,
)
from short_vol_radar.evidence import RadarEventSink
from short_vol_radar.policy import load_policy_bytes
from short_vol_radar.radar import TickerState
from short_vol_underwriting import (
    CloseAtomicAvailability,
    CloseOptionAvailability,
    FixedContractShadowOwner,
    RuntimeBindings,
    ShadowCaseStore,
    ShadowStateStore,
    SourceFact,
    SubscriptionAdmissionRefreshWitness,
    canonical_identity,
    load_policy_chain,
)
from short_vol_underwriting import (
    FactBoundary as DownstreamFactBoundary,
)
from short_vol_underwriting.constants import (
    POSITION_POLICY_IDENTITY,
    RADAR_POLICY_IDENTITY,
    UNDERWRITING_POLICY_IDENTITY,
)

ROOT = Path(__file__).resolve().parents[1]


class _HistoryObserver:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def on_record(
        self,
        value: Mapping[str, object],
        state: ShadowStateStore,
    ) -> None:
        del state
        self.records.append(dict(value))


_HISTORY_BY_OWNER: dict[int, _HistoryObserver] = {}


def _reducer(tmp_path: Path, policy_factory: PolicyFactory) -> RadarReducer:
    exact, digest = policy_factory()
    reducer = RadarReducer(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        event_sink=RadarEventSink(
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
    )
    downstream = tmp_path / "downstream"
    radar = tmp_path / "radar"
    downstream.mkdir()
    radar.mkdir()
    history = _HistoryObserver()
    owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        state_store=ShadowStateStore(bindings=bindings, observer=history),
    )
    _HISTORY_BY_OWNER[id(owner)] = history
    adapter = FixedContractShadowRuntimeAdapter(owner=owner)
    reducer = RadarReducer(
        policy=policies.radar,
        code_identity="a" * 40,
        event_sink=RadarEventSink(
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
        price_tick=PriceTickMetadata(Decimal("1")),
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
        price_tick=PriceTickMetadata(Decimal("1")),
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
    calculation = SimpleNamespace(
        baseline=SimpleNamespace(window_diagnostics=()),
        delta=SimpleNamespace(lower=Decimal("0.19"), upper=Decimal("0.21")),
        executable_bid_iv=SimpleNamespace(lower=Decimal("0.49"), upper=Decimal("0.51")),
        richness=SimpleNamespace(lower=Decimal("1.30"), upper=Decimal("1.31")),
        band=SimpleNamespace(clue_eligible=True),
        delta_clue_eligible=True,
        target_spread_ticks=Decimal("2"),
        target_bid=SimpleNamespace(consumed=()),
        target_ask=SimpleNamespace(consumed=()),
    )
    reducer.results["BTC-SHORT"] = cast(
        Any,
        SimpleNamespace(
            calculation=calculation,
            current_evaluation=SimpleNamespace(calculation=calculation),
            detector_state=DetectorState.ANOMALY_ACTIVE,
            reason=None,
            band_id=policies.radar.tte_bands[0].band_id,
        ),
    )
    reducer.option_books = {}
    for instrument_name, bid, ask in (
        ("BTC-SHORT", "300", "301"),
        ("BTC-LONG", "100", "101"),
    ):
        option_book = ContinuousOrderBook(instrument_name)
        option_book.apply(
            {
                "type": "snapshot",
                "instrument_name": instrument_name,
                "change_id": 10,
                "timestamp": 1_000_010,
                "bids": [["new", bid, "0.1"]],
                "asks": [["new", ask, "0.1"]],
            },
            110,
        )
        reducer.option_books[instrument_name] = option_book
        reducer.accepted_book_receipts[instrument_name] = AcceptedBookReceipt(
            instrument_name=instrument_name,
            snapshot_kind="snapshot",
            prev_change_id=None,
            change_id=10,
            source_timestamp_ms=1_000_010,
            session_epoch=1,
            subscription_generation=1,
            boundary=first_boundary,
        )
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
                signal=ObservationSignal.ACTIVATE,
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
    assert [value["object_kind"] for value in owner.state_store.objects] == [
        "UNDERWRITING_AVAILABILITY_EVALUATION"
    ]


def test_inactive_underwriting_scope_transitions_once_then_stays_settled(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    active_commit = _commit(
        causal_seq=1,
        monotonic_ms=110,
        cause=CausalCause.COMBO_BOOK_CHANGED,
    )
    admission_intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=active_commit,
    )
    assert len(admission_intents) == 2
    assert {str(intent.params["instrument_name"]) for intent in admission_intents} == {
        "BTC-SHORT",
        "BTC-LONG",
    }
    (active,) = adapter._underwriting_by_scope.values()
    assert active.active_episode_identity is not None

    reducer.trackers.clear()
    inactive_commit = _commit(
        causal_seq=2,
        monotonic_ms=120,
        cause=CausalCause.TICKER_APPLIED,
    )
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=inactive_commit,
        )
        == ()
    )
    assert adapter._underwriting_by_scope == {}
    assert adapter.workbench_underwriting_metadata() == ()
    (invalidation,) = _object_payloads(owner, "CANDIDATE_INVALIDATION")
    assert invalidation["primary_reason"] == "RADAR_POLICY_OR_EPISODE_PAUSED_ENDED_OR_CHANGED"
    assert owner.retained_state_counts["active_candidates"] == 0
    assert owner.retained_state_counts["availability_scopes"] == 0
    assert adapter.retained_state_counts["underwriting_scopes"] == 0
    assert adapter.retained_state_counts["candidate_origins"] == 0
    assert adapter.retained_state_counts["request_contexts"] == 0
    inactive_revision = owner.state_store.revision
    inactive_objects = tuple(owner.state_store.objects)

    unrelated_commit = _commit(
        causal_seq=3,
        monotonic_ms=130,
        cause=CausalCause.TICKER_APPLIED,
    )
    assert adapter.on_settled_transaction(reducer=reducer, commit=unrelated_commit) == ()
    assert adapter._underwriting_by_scope == {}
    assert owner.state_store.revision == inactive_revision
    assert tuple(owner.state_store.objects) == inactive_objects

    next_tracker = EpisodeTracker(
        runtime_identity=reducer.runtime_identity,
        policy_identity=reducer.policy.identity,
        instrument_name="BTC-SHORT",
    )
    next_tracker.state = TrackerState.ACTIVE
    next_tracker.episode_id = f"{reducer.runtime_identity}:{reducer.policy.identity}:BTC-SHORT:4"
    next_tracker.activation_band_id = reducer.policy.tte_bands[0].band_id
    next_tracker.activation_causal_seq = 4
    reducer.trackers["BTC-SHORT"] = next_tracker
    adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=4,
            monotonic_ms=140,
            cause=CausalCause.COMBO_BOOK_CHANGED,
        ),
    )
    assert owner.state_store.revision > inactive_revision
    assert any(
        facts.active_episode_identity == next_tracker.episode_id
        for facts in adapter._underwriting_by_scope.values()
    )


def test_frozen_component_structure_does_not_switch_to_a_later_protective_leg(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    first_intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.COMBO_BOOK_CHANGED,
        ),
    )
    assert len(first_intents) == 2
    (current_facts,) = adapter._underwriting_by_scope.values()
    assert current_facts.long_leg_instrument_name == "BTC-LONG"

    original = reducer.options["BTC-LONG"]
    alternative = replace(
        original,
        instrument_name="BTC-LONG-ALT",
        strike=Decimal("101500"),
    )
    reducer.options[alternative.instrument_name] = alternative
    reducer.catalog_options[alternative.instrument_name] = alternative
    alternative_book = ContinuousOrderBook(alternative.instrument_name)
    alternative_book.apply(
        {
            "type": "snapshot",
            "instrument_name": alternative.instrument_name,
            "change_id": 20,
            "timestamp": 1_000_020,
            "bids": [["new", "120", "0.1"]],
            "asks": [["new", "121", "0.1"]],
        },
        120,
    )
    reducer.option_books[alternative.instrument_name] = alternative_book
    reducer.accepted_book_receipts[alternative.instrument_name] = AcceptedBookReceipt(
        instrument_name=alternative.instrument_name,
        snapshot_kind="snapshot",
        prev_change_id=None,
        change_id=20,
        source_timestamp_ms=1_000_020,
        session_epoch=1,
        subscription_generation=1,
        boundary=FactBoundary(1, 2, 120, 2),
    )

    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=2,
                monotonic_ms=120,
                cause=CausalCause.OPTION_BOOK_FACT,
            ),
        )
        == ()
    )
    (current_facts,) = adapter._underwriting_by_scope.values()
    assert current_facts.long_leg_instrument_name == "BTC-LONG"
    assert current_facts.protective_leg_selection_rule_identity is not None
    assert current_facts.candidate_protective_leg_count == 1
    assert owner.retained_state_counts["active_candidates"] == 1
    assert adapter.retained_state_counts["request_contexts"] == 2


def test_underwriting_selector_waits_for_complete_catalog_before_freezing(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    reducer.option_catalog.complete = False

    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=1,
                monotonic_ms=110,
                cause=CausalCause.OPTION_BOOK_FACT,
            ),
        )
        == ()
    )
    (incomplete,) = adapter._underwriting_by_scope.values()
    assert incomplete.long_leg_instrument_name is None
    assert "OPTION_CATALOG_INCOMPLETE" in incomplete.unknown_reasons

    original = reducer.options["BTC-LONG"]
    better = replace(
        original,
        instrument_name="BTC-LONG-BETTER",
        strike=Decimal("103000"),
    )
    reducer.options[better.instrument_name] = better
    reducer.catalog_options[better.instrument_name] = better
    better_book = ContinuousOrderBook(better.instrument_name)
    better_book.apply(
        {
            "type": "snapshot",
            "instrument_name": better.instrument_name,
            "change_id": 20,
            "timestamp": 1_000_020,
            "bids": [["new", "49", "0.1"]],
            "asks": [["new", "50", "0.1"]],
        },
        120,
    )
    reducer.option_books[better.instrument_name] = better_book
    reducer.accepted_book_receipts[better.instrument_name] = AcceptedBookReceipt(
        instrument_name=better.instrument_name,
        snapshot_kind="snapshot",
        prev_change_id=None,
        change_id=20,
        source_timestamp_ms=1_000_020,
        session_epoch=1,
        subscription_generation=1,
        boundary=FactBoundary(1, 2, 120, 2),
    )
    reducer.option_catalog.complete = True

    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=2,
            monotonic_ms=120,
            cause=CausalCause.OPTION_CATALOG,
        ),
    )

    (complete,) = adapter._underwriting_by_scope.values()
    assert complete.long_leg_instrument_name == "BTC-LONG-BETTER"
    assert complete.protective_leg_selection_rule_identity is not None
    assert complete.candidate_protective_leg_count == 2
    assert len(intents) == 2
    assert owner.retained_state_counts["active_candidates"] == 1


def test_underwriting_selector_can_choose_candidate_outside_radar_display_top_three(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    original = reducer.options["BTC-LONG"]
    first_boundary = FactBoundary(1, 1, 110, 1)
    for suffix, strike, bid, ask in (
        ("A", "101250", "126", "127"),
        ("B", "101500", "122", "123"),
        ("C", "101750", "113", "114"),
    ):
        alternative = replace(
            original,
            instrument_name=f"BTC-LONG-{suffix}",
            strike=Decimal(strike),
        )
        reducer.options[alternative.instrument_name] = alternative
        reducer.catalog_options[alternative.instrument_name] = alternative
        book = ContinuousOrderBook(alternative.instrument_name)
        book.apply(
            {
                "type": "snapshot",
                "instrument_name": alternative.instrument_name,
                "change_id": 10,
                "timestamp": 1_000_010,
                "bids": [["new", bid, "0.1"]],
                "asks": [["new", ask, "0.1"]],
            },
            110,
        )
        reducer.option_books[alternative.instrument_name] = book
        reducer.accepted_book_receipts[alternative.instrument_name] = AcceptedBookReceipt(
            instrument_name=alternative.instrument_name,
            snapshot_kind="snapshot",
            prev_change_id=None,
            change_id=10,
            source_timestamp_ms=1_000_010,
            session_epoch=1,
            subscription_generation=1,
            boundary=first_boundary,
        )

    top_three = {
        reference.long_instrument_name
        for reference in adapter._review_contexts(reducer)["BTC-SHORT"].legged_structure.references
    }
    assert len(top_three) == 3
    assert "BTC-LONG" not in top_three

    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    (current_facts,) = adapter._underwriting_by_scope.values()
    assert current_facts.long_leg_instrument_name == "BTC-LONG"
    assert len(intents) == 2
    assert owner.retained_state_counts["active_candidates"] == 1


@pytest.mark.parametrize("variant", ("inactive", "amount_ineligible"))
def test_known_illegal_protective_leg_without_book_does_not_poison_selection(
    tmp_path: Path,
    variant: str,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    original = reducer.options["BTC-LONG"]
    if variant == "inactive":
        illegal = replace(
            original,
            instrument_name="BTC-LONG-INACTIVE",
            strike=Decimal("103000"),
            lifecycle_state=InstrumentLifecycleState.INACTIVE,
            is_active=False,
        )
    else:
        illegal = replace(
            original,
            instrument_name="BTC-LONG-AMOUNT_INELIGIBLE",
            strike=Decimal("103000"),
            amount=AmountMetadata(
                contract_size=Decimal("1"),
                min_trade_amount=Decimal("0.2"),
                qty_tick_size=Decimal("0.1"),
            ),
        )
    reducer.options[illegal.instrument_name] = illegal
    reducer.catalog_options[illegal.instrument_name] = illegal

    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_CATALOG,
        ),
    )

    (facts,) = adapter._underwriting_by_scope.values()
    assert facts.long_leg_instrument_name == "BTC-LONG"
    assert len(intents) == 2
    assert owner.retained_state_counts["active_candidates"] == 1


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("amount", "AMOUNT_METADATA_UNKNOWN"),
        ("price_tick", "PRICE_TICK_METADATA_UNKNOWN"),
    ),
)
def test_potentially_legal_leg_metadata_unknown_blocks_selection_exactly(
    tmp_path: Path,
    field: str,
    reason: str,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    original = reducer.options["BTC-LONG"]
    unknown = (
        replace(original, amount=None) if field == "amount" else replace(original, price_tick=None)
    )
    reducer.options[unknown.instrument_name] = unknown
    reducer.catalog_options[unknown.instrument_name] = unknown

    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=1,
                monotonic_ms=110,
                cause=CausalCause.OPTION_CATALOG,
            ),
        )
        == ()
    )

    (facts,) = adapter._underwriting_by_scope.values()
    assert facts.long_leg_instrument_name is None
    assert facts.component_state == "COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN"
    assert facts.component_blockers == (f"BTC-LONG:{reason}",)
    assert owner.retained_state_counts["active_candidates"] == 0


def test_underwriting_selector_keeps_missing_legal_leg_input_unknown(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    missing = replace(
        reducer.options["BTC-LONG"],
        instrument_name="BTC-LONG-MISSING",
        strike=Decimal("103000"),
    )
    reducer.options[missing.instrument_name] = missing
    reducer.catalog_options[missing.instrument_name] = missing

    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    (facts,) = adapter._underwriting_by_scope.values()
    assert intents == ()
    assert facts.long_leg_instrument_name is None
    assert facts.component_state == "COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN"
    assert facts.component_blockers == ("BTC-LONG-MISSING:BOOK_UNKNOWN",)
    assert owner.retained_state_counts["active_candidates"] == 0


def test_workbench_underwriting_metadata_reuses_unchanged_snapshot(
    tmp_path: Path,
) -> None:
    reducer, adapter, _owner = _shadow_system(tmp_path)
    reducer.trackers.clear()
    _activate_real_episode(reducer)
    causal_seq = (
        reducer.policy.tte_bands[0].option_rules[OptionType.CALL].activation_observation_count
    )
    commit = _commit(
        causal_seq=causal_seq,
        monotonic_ms=120,
        cause=CausalCause.COMBO_BOOK_CHANGED,
    )
    adapter.on_settled_transaction(reducer=reducer, commit=commit)

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
    assert owner.state_store.objects == ()


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
    for value in _HISTORY_BY_OWNER[id(owner)].records:
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
) -> list[dict[str, Any]]:
    payloads: list[tuple[int, dict[str, Any]]] = []
    for value in _HISTORY_BY_OWNER[id(owner)].records:
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


def _rest_option_book(
    instrument_name: str,
    *,
    bid_price: str,
    ask_price: str,
    change_id: int,
    amount: str = "0.1",
    timestamp_ms: int | None = None,
) -> dict[str, object]:
    return {
        "instrument_name": instrument_name,
        "state": "open",
        "change_id": change_id,
        "timestamp": 1_000_000 + change_id if timestamp_ms is None else timestamp_ms,
        "bids": [[bid_price, amount]],
        "asks": [[ask_price, amount]],
    }


def _settle_component_pair(
    *,
    adapter: FixedContractShadowRuntimeAdapter,
    intents: tuple[ShadowRpcIntent, ...],
    first_causal_seq: int,
    change_id: int,
    short_bid: str,
    short_ask: str,
    long_bid: str,
    long_ask: str,
    long_amount: str = "0.1",
) -> None:
    assert len(intents) == 2
    sent_boundaries: dict[int, FactBoundary] = {}
    for offset, intent in enumerate(intents):
        sent = FactBoundary(
            1,
            first_causal_seq + offset,
            100 + (first_causal_seq + offset) * 10,
            first_causal_seq + offset,
        )
        sent_boundaries[intent.request_id] = sent
        adapter.on_request_sent(request_id=intent.request_id, boundary=sent)

    for offset, intent in enumerate(intents):
        instrument_name = str(intent.params["instrument_name"])
        is_short = instrument_name == "BTC-SHORT"
        amount = "0.1" if is_short else long_amount
        accepted_seq = first_causal_seq + 2 + offset
        adapter.on_rpc_response(
            request_id=intent.request_id,
            result=_rest_option_book(
                instrument_name,
                bid_price=short_bid if is_short else long_bid,
                ask_price=short_ask if is_short else long_ask,
                change_id=change_id,
                amount=amount,
            ),
            sent_boundary=sent_boundaries[intent.request_id],
            boundary=FactBoundary(
                1,
                accepted_seq,
                100 + accepted_seq * 10,
                accepted_seq,
            ),
        )


def _admit_component_shadow(
    reducer: RadarReducer,
    adapter: FixedContractShadowRuntimeAdapter,
) -> tuple[ShadowRpcIntent, ...]:
    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    _settle_component_pair(
        adapter=adapter,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="300",
        short_ask="301",
        long_bid="100",
        long_ask="101",
    )
    return intents


def test_component_candidate_requires_both_strictly_later_option_book_responses(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    assert len(intents) == 2
    assert {str(intent.params["instrument_name"]) for intent in intents} == {
        "BTC-SHORT",
        "BTC-LONG",
    }
    assert owner.state_store.retained_state_counts["active_or_latest_terminal_cases"] == 0

    sent = FactBoundary(1, 2, 120, 2)
    first = next(intent for intent in intents if intent.params["instrument_name"] == "BTC-SHORT")
    adapter.on_request_sent(request_id=first.request_id, boundary=sent)
    assert (
        adapter.on_rpc_response(
            request_id=first.request_id,
            result=_rest_option_book(
                "BTC-SHORT",
                bid_price="300",
                ask_price="301",
                change_id=11,
            ),
            sent_boundary=sent,
            boundary=FactBoundary(1, 3, 130, 3),
        )
        == ()
    )
    assert not _object_payloads(owner, "SHADOW_ENTRY")
    assert owner.state_store.retained_state_counts["active_or_latest_terminal_cases"] == 0

    second = next(intent for intent in intents if intent.params["instrument_name"] == "BTC-LONG")
    second_sent = FactBoundary(1, 4, 140, 4)
    adapter.on_request_sent(request_id=second.request_id, boundary=second_sent)
    adapter.on_rpc_response(
        request_id=second.request_id,
        result=_rest_option_book(
            "BTC-LONG",
            bid_price="100",
            ask_price="101",
            change_id=11,
        ),
        sent_boundary=second_sent,
        boundary=FactBoundary(1, 5, 150, 5),
    )

    (entry,) = _object_payloads(owner, "SHADOW_ENTRY")
    assert entry["execution_model"] == "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL"
    assert entry["canonical_combo_identity"] is None
    assert entry["combo_instrument_name"] is None
    assert entry["entry_component_pair_identity"]
    assert [leg["action"] for leg in entry["entry_component_legs"]] == ["SELL", "BUY"]
    assert [leg["stressed_vwap_usdc_per_btc"] for leg in entry["entry_component_legs"]] == [
        "299",
        "102",
    ]
    assert len(entry["entry_component_quote_source_refs"]) == 2
    assert entry["gross_entry_credit_usdc"] == "19.7"
    assert entry["entry_fee_reserve_usdc"] == "4.275"
    assert entry["net_entry_credit_usdc"] == "15.425"
    assert entry["non_claims"] == [
        "NOT_AN_ORDER",
        "NOT_A_FILL",
        "NOT_AN_ATOMIC_QUOTE",
        "NO_LIQUIDITY_RESERVATION",
        "ATOMIC_EXECUTABILITY_UNPROVEN",
    ]
    assert owner.state_store.retained_state_counts["active_or_latest_terminal_cases"] == 1


def test_component_admission_pair_over_skew_budget_is_exact_unknown_without_case(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    short_intent = next(
        value for value in intents if value.params["instrument_name"] == "BTC-SHORT"
    )
    long_intent = next(value for value in intents if value.params["instrument_name"] == "BTC-LONG")
    short_sent = FactBoundary(1, 2, 120, 2)
    long_sent = FactBoundary(1, 3, 121, 3)
    adapter.on_request_sent(request_id=short_intent.request_id, boundary=short_sent)
    adapter.on_request_sent(request_id=long_intent.request_id, boundary=long_sent)
    adapter.on_rpc_response(
        request_id=short_intent.request_id,
        result=_rest_option_book(
            "BTC-SHORT",
            bid_price="300",
            ask_price="301",
            change_id=11,
            timestamp_ms=1_000_000,
        ),
        sent_boundary=short_sent,
        boundary=FactBoundary(1, 4, 130, 4),
    )
    adapter.on_rpc_response(
        request_id=long_intent.request_id,
        result=_rest_option_book(
            "BTC-LONG",
            bid_price="100",
            ask_price="101",
            change_id=11,
            timestamp_ms=1_007_000,
        ),
        sent_boundary=long_sent,
        boundary=FactBoundary(1, 5, 5_500, 5),
    )

    assert not _object_payloads(owner, "SHADOW_ENTRY")
    assert _terminal_outcomes(owner) == ["UNKNOWN_CONSUMED"]
    terminal = _object_payloads(owner, "ADMISSION_ATTEMPT_TERMINAL")[-1]
    assert terminal["terminal_unknown_reasons"] == [
        "COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED",
        "COMPONENT_PAIR_RECEIVE_SKEW_EXCEEDED",
    ]
    assert terminal["component_pair_timing"] == {
        "session_epochs": [1, 1],
        "global_continuity_epochs": [1, 1],
        "source_timestamp_skew_ms": 7_000,
        "receive_skew_ms": 5_370,
    }
    assert terminal["component_pair_limits"] == {
        "maximum_source_skew_ms": 6_000,
        "maximum_receive_skew_ms": 4_000,
    }


@pytest.mark.parametrize(
    ("variant", "expected_reason"),
    (
        ("session", "COMPONENT_PAIR_SESSION_EPOCH_MISMATCH"),
        ("continuity", "COMPONENT_PAIR_CONTINUITY_EPOCH_MISMATCH"),
    ),
)
def test_component_admission_pair_epoch_mismatch_is_exact_unknown_without_case(
    tmp_path: Path,
    variant: str,
    expected_reason: str,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    short_intent = next(
        value for value in intents if value.params["instrument_name"] == "BTC-SHORT"
    )
    long_intent = next(value for value in intents if value.params["instrument_name"] == "BTC-LONG")
    short_sent = FactBoundary(1, 2, 120, 2)
    long_sent = FactBoundary(1, 3, 121, 3)
    adapter.on_request_sent(request_id=short_intent.request_id, boundary=short_sent)
    adapter.on_request_sent(request_id=long_intent.request_id, boundary=long_sent)
    adapter.on_rpc_response(
        request_id=short_intent.request_id,
        result=_rest_option_book(
            "BTC-SHORT",
            bid_price="300",
            ask_price="301",
            change_id=11,
        ),
        sent_boundary=short_sent,
        boundary=FactBoundary(1, 4, 130, 4),
    )
    if variant == "continuity":
        reducer._global_continuity_epoch += 1
    adapter.on_rpc_response(
        request_id=long_intent.request_id,
        result=_rest_option_book(
            "BTC-LONG",
            bid_price="100",
            ask_price="101",
            change_id=11,
        ),
        sent_boundary=long_sent,
        boundary=FactBoundary(2 if variant == "session" else 1, 5, 150, 5),
    )

    assert not _object_payloads(owner, "SHADOW_ENTRY")
    assert _terminal_outcomes(owner) == ["UNKNOWN_CONSUMED"]
    terminal = _object_payloads(owner, "ADMISSION_ATTEMPT_TERMINAL")[-1]
    assert terminal["terminal_unknown_reasons"] == [expected_reason]


def test_component_shadow_entry_opens_its_durable_case(tmp_path: Path) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    cases = tmp_path / "cases"
    cases.mkdir()
    case_store = ShadowCaseStore(
        cases,
        bindings=owner.bindings,
        policies=owner.policies,
    )
    owner.state_store.observer = case_store

    _admit_component_shadow(reducer, adapter)

    entry = next(
        value for value in owner.state_store.objects if value["object_kind"] == "SHADOW_ENTRY"
    )
    entry_identity = str(entry["object_identity"])
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None
    assert case_store.case_count == 1
    assert case_store.active_case_count == 1
    assert owner.retained_state_counts["active_candidates"] == 0
    assert owner.retained_state_counts["active_trades"] == 1
    opened = case_store.read_case(case_id, runtime_active=True).opened
    economics = opened["entry_economics"]
    assert isinstance(economics, Mapping)
    assert economics["width_usdc_per_btc"] == "1000"


def test_no_active_combo_is_only_a_diagnostic_and_does_not_block_shadow_entry(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    reducer.combos.clear()
    reducer.combo_books.clear()
    reducer.accepted_book_receipts.pop("BTC-COMBO")
    reducer.combo_catalog.complete = True
    reducer.combo_catalog.source_complete = True

    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.COMBO_CATALOG,
        ),
    )
    (facts,) = adapter._underwriting_by_scope.values()
    assert facts.atomic_state == "NO_ACTIVE_COMBO"
    assert facts.component_state == "COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE"
    assert len(intents) == 2

    _settle_component_pair(
        adapter=adapter,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="300",
        short_ask="301",
        long_bid="100",
        long_ask="101",
    )
    (entry,) = _object_payloads(owner, "SHADOW_ENTRY")
    assert entry["atomic_state_diagnostic"] == "NO_ACTIVE_COMBO"
    assert entry["execution_model"] == "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL"


def test_component_admission_with_insufficient_long_depth_is_known_no_entry(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    _settle_component_pair(
        adapter=adapter,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="300",
        short_ask="301",
        long_bid="100",
        long_ask="101",
        long_amount="0.05",
    )

    assert not _object_payloads(owner, "SHADOW_ENTRY")
    assert _terminal_outcomes(owner) == ["KNOWN_INVALIDATED_BEFORE_REFRESH"]
    (invalidation,) = _object_payloads(owner, "CANDIDATE_INVALIDATION")
    assert invalidation["primary_reason"] == "REUNDERWRITING_NO_LONGER_CANDIDATE"
    assert owner.state_store.retained_state_counts["active_or_latest_terminal_cases"] == 0


def test_one_component_admission_rpc_failure_retires_the_pair_without_case(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    first = intents[0]
    adapter.on_request_sent(
        request_id=first.request_id,
        boundary=FactBoundary(1, 2, 120, 2),
    )
    adapter.on_request_failure(
        request_id=first.request_id,
        terminal_state=RpcState.ERROR,
        boundary=FactBoundary(1, 3, 130, 3),
    )

    assert not _object_payloads(owner, "SHADOW_ENTRY")
    assert _terminal_outcomes(owner) == ["UNKNOWN_CONSUMED"]
    assert owner.retained_state_counts["active_candidates"] == 0
    assert adapter.retained_state_counts["request_contexts"] == 0
    assert owner.state_store.retained_state_counts["active_or_latest_terminal_cases"] == 0


def test_component_shadow_entry_closes_from_a_new_paired_snapshot_and_writes_known_outcome(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    _admit_component_shadow(reducer, adapter)

    _set_platform_usable(reducer, False)
    close_intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=6,
            monotonic_ms=160,
            cause=CausalCause.TIME_BOUNDARY,
        ),
    )
    assert len(close_intents) == 2
    assert {str(intent.params["instrument_name"]) for intent in close_intents} == {
        "BTC-SHORT",
        "BTC-LONG",
    }

    _settle_component_pair(
        adapter=adapter,
        intents=close_intents,
        first_causal_seq=7,
        change_id=12,
        short_bid="249",
        short_ask="250",
        long_bid="149",
        long_ask="150",
    )

    (outcome,) = _object_payloads(owner, "SHADOW_OUTCOME")
    assert outcome["terminal_state"] == "MATURE_KNOWN"
    assert outcome["execution_model"] == "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL"
    assert outcome["close_component_pair_identity"]
    assert [leg["action"] for leg in outcome["close_component_legs"]] == ["BUY", "SELL"]
    assert [leg["stressed_vwap_usdc_per_btc"] for leg in outcome["close_component_legs"]] == [
        "251",
        "148",
    ]
    assert outcome["gross_close_cashflow_usdc"] == "-10.3"
    assert outcome["close_fee_reserve_usdc"] == "4.85"
    assert outcome["net_close_cashflow_usdc"] == "-15.15"
    assert outcome["net_pnl_after_public_standard_fee_reserve_usdc"] == "0.275"
    assert outcome["actual_pnl_usdc"] is None
    assert owner.retained_state_counts["active_trades"] == 0
    assert adapter.retained_state_counts["active_anchors"] == 0
    assert owner.state_store.retained_state_counts["latest_terminal_cases"] == 1


def test_component_close_pair_over_skew_is_workbench_visible_business_unknown(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    _admit_component_shadow(reducer, adapter)
    _set_platform_usable(reducer, False)
    close_intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=6,
            monotonic_ms=160,
            cause=CausalCause.TIME_BOUNDARY,
        ),
    )
    short_intent = next(
        value for value in close_intents if value.params["instrument_name"] == "BTC-SHORT"
    )
    long_intent = next(
        value for value in close_intents if value.params["instrument_name"] == "BTC-LONG"
    )
    short_sent = FactBoundary(1, 7, 170, 7)
    long_sent = FactBoundary(1, 8, 171, 8)
    adapter.on_request_sent(request_id=short_intent.request_id, boundary=short_sent)
    adapter.on_request_sent(request_id=long_intent.request_id, boundary=long_sent)
    adapter.on_rpc_response(
        request_id=short_intent.request_id,
        result=_rest_option_book(
            "BTC-SHORT",
            bid_price="249",
            ask_price="250",
            change_id=12,
            timestamp_ms=1_000_000,
        ),
        sent_boundary=short_sent,
        boundary=FactBoundary(1, 9, 180, 9),
    )
    adapter.on_rpc_response(
        request_id=long_intent.request_id,
        result=_rest_option_book(
            "BTC-LONG",
            bid_price="149",
            ask_price="150",
            change_id=12,
            timestamp_ms=1_007_000,
        ),
        sent_boundary=long_sent,
        boundary=FactBoundary(1, 10, 5_500, 10),
    )

    terminal = _object_payloads(owner, "POST_CLOSE_ATTEMPT_TERMINAL")[-1]
    assert terminal["terminal_status"] == "ERROR"
    assert terminal["terminal_unknown_reasons"] == [
        "COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED",
        "COMPONENT_PAIR_RECEIVE_SKEW_EXCEEDED",
    ]
    assert terminal["component_pair_limits"] == {
        "maximum_source_skew_ms": 6_000,
        "maximum_receive_skew_ms": 4_000,
    }
    kinds = workbench_module._objects_by_kind(owner.state_store.objects)
    (row,) = workbench_module._position_rows(
        kinds,
        owner.policies,
        trusted_time=None,
        option_metadata=(),
    )
    assert row["component_pair_business_state"] == "UNKNOWN"
    assert row["component_pair_timing"] == terminal["component_pair_timing"]
    assert row["component_pair_limits"] == terminal["component_pair_limits"]
    assert row["component_pair_unknown_reasons"] == terminal["terminal_unknown_reasons"]
    assert not _object_payloads(owner, "SHADOW_OUTCOME")


def test_partial_component_close_then_rpc_failure_matures_unknown_without_fake_close(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    _admit_component_shadow(reducer, adapter)

    _set_platform_usable(reducer, False)
    close_intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=6,
            monotonic_ms=160,
            cause=CausalCause.TIME_BOUNDARY,
        ),
    )
    sent_boundaries: dict[int, FactBoundary] = {}
    for offset, intent in enumerate(close_intents):
        sent = FactBoundary(1, 7 + offset, 170 + offset * 10, 7 + offset)
        sent_boundaries[intent.request_id] = sent
        adapter.on_request_sent(request_id=intent.request_id, boundary=sent)

    first = close_intents[0]
    first_name = str(first.params["instrument_name"])
    adapter.on_rpc_response(
        request_id=first.request_id,
        result=_rest_option_book(
            first_name,
            bid_price="249",
            ask_price="250",
            change_id=12,
        ),
        sent_boundary=sent_boundaries[first.request_id],
        boundary=FactBoundary(1, 9, 190, 9),
    )
    assert not _object_payloads(owner, "SHADOW_OUTCOME")

    _set_natural_lifecycle_ready(reducer)
    second = close_intents[1]
    adapter.on_request_failure(
        request_id=second.request_id,
        terminal_state=RpcState.ERROR,
        boundary=FactBoundary(1, 10, 200, 10),
    )

    (outcome,) = _object_payloads(owner, "SHADOW_OUTCOME")
    assert outcome["terminal_state"] == "MATURE_UNKNOWN"
    assert outcome["economic_availability"] == "UNKNOWN"
    assert outcome["selected_exit_identity"] is None
    assert outcome["close_component_pair_identity"] is None
    assert outcome["close_component_quote_source_refs"] == []
    assert outcome["close_component_legs"] == []
    assert outcome["gross_close_cashflow_usdc"] is None
    assert adapter.retained_state_counts["request_contexts"] == 0


def test_component_quote_fingerprint_is_stable_scalar_identity_input(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    _admit_component_shadow(reducer, adapter)

    before = tuple(owner.state_store.objects)
    assert (
        adapter.on_settled_transaction(
            reducer=reducer,
            commit=_commit(
                causal_seq=6,
                monotonic_ms=160,
                cause=CausalCause.TIME_BOUNDARY,
            ),
        )
        == ()
    )
    assert tuple(owner.state_store.objects) != before
    assert _object_payloads(owner, "POSITION_ACTION")[-1]["serialized_action"] == "HOLD"
