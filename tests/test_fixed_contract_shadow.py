from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import radar_runtime.runtime as runtime_module
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
    RpcPurpose,
    RpcState,
    ShadowRpcIntent,
)
from short_vol_radar.black import DecimalInterval
from short_vol_radar.bucket import RadarBucketEpisodeTracker
from short_vol_radar.detector import (
    EpisodeTracker,
    TrackerState,
)
from short_vol_radar.evidence import RadarEventSink
from short_vol_radar.policy import load_policy_bytes
from short_vol_radar.radar import (
    CurrentDisposition,
    CurrentEvaluation,
    DeltaBucket,
    TickerState,
)
from short_vol_radar.score import (
    LeaderCoverage,
    RadarBucketKey,
    RadarScoreInputs,
    ScoreBand,
    build_radar_score_packet,
    compute_radar_score,
    compute_unsigned_oi_concentration,
)
from short_vol_underwriting import (
    CloseAtomicAvailability,
    CloseOptionAvailability,
    FixedContractShadowOwner,
    RuntimeBindings,
    ShadowCaseStore,
    ShadowCaseStoreError,
    ShadowStateStore,
    SourceFact,
    SubscriptionAdmissionRefreshWitness,
    canonical_identity,
    designate_selected_decision_episode,
    load_policy_chain,
    selected_decision_batch_identity,
)
from short_vol_underwriting import (
    FactBoundary as DownstreamFactBoundary,
)
from short_vol_underwriting.constants import (
    INVERSE_BTC_POSITION_POLICY_IDENTITY,
    INVERSE_BTC_RADAR_POLICY_IDENTITY,
    INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
)

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class _ResponseScoreCalculation:
    """Minimum immutable core calculation used by the reducer response-path test."""

    band: Any
    rule: Any
    target_bid: Any
    target_ask: Any
    stressed_executable_bid_iv: DecimalInterval
    delta: DecimalInterval
    delta_bucket: DeltaBucket
    delta_clue_eligible: bool
    target_spread_ticks: Decimal
    richness: DecimalInterval
    baseline: Any
    score_result: Any = None

    @property
    def clue_eligible(self) -> bool:
        return bool(self.band.clue_eligible and self.delta_clue_eligible)


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


class _HistoryCaseStoreObserver:
    def __init__(self, history: _HistoryObserver, case_store: ShadowCaseStore) -> None:
        self.history = history
        self.case_store = case_store

    def on_record(
        self,
        value: Mapping[str, object],
        state: ShadowStateStore,
    ) -> None:
        self.history.on_record(value, state)
        self.case_store.on_record(value, state)


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
            ComboLeg("BTC-1JAN00-101000-C", Decimal("-0.1")),
            ComboLeg("BTC-1JAN00-102000-C", Decimal("0.1")),
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
        "bids": [["new", "0.00300", "0.1"]],
        "asks": [["new", "0.00301", "0.1"]],
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
            "index_name": "btc_usd",
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


def _settled_transaction(
    adapter: FixedContractShadowRuntimeAdapter,
    *,
    reducer: RadarReducer,
    commit: CausalCommit,
) -> tuple[ShadowRpcIntent, ...]:
    """Project a unit-test score recomputation at the supplied settled boundary."""
    _recompute_test_score_boundary(reducer, commit.boundary)
    return adapter.on_settled_transaction(reducer=reducer, commit=commit)


def _recompute_test_score_boundary(
    reducer: RadarReducer,
    boundary: FactBoundary,
) -> None:
    for bucket_tracker in reducer.bucket_trackers.values():
        episode = bucket_tracker.episode
        if episode is None:
            continue
        name = episode.leader_instrument_name
        prior = reducer.score_packets.get(name)
        result = reducer.score_results.get(name)
        calculation = getattr(reducer.results.get(name), "calculation", None)
        if prior is None or result is None or calculation is None:
            continue
        reducer.score_packets[name] = build_radar_score_packet(
            policy_identity=reducer.policy.identity,
            fact_boundary={
                "code_identity": reducer.code_identity,
                "runtime_identity": reducer.runtime_identity,
                "session_epoch": boundary.session_epoch,
                "ingress_seq": boundary.ingress_seq,
                "received_monotonic_ms": boundary.received_monotonic_ms,
                "causal_seq": boundary.causal_seq,
            },
            bucket_key=episode.bucket_key,
            leader_instrument_name=name,
            result=result,
            oi_diagnostic=prior.oi_diagnostic,
            stressed_richness=calculation.richness,
            leader_coverage=prior.leader_coverage,
        )


def _rpc_response(
    adapter: FixedContractShadowRuntimeAdapter,
    *,
    reducer: RadarReducer,
    request_id: int,
    result: object,
    sent_boundary: FactBoundary,
    boundary: FactBoundary,
) -> tuple[ShadowRpcIntent, ...]:
    _recompute_test_score_boundary(reducer, boundary)
    return adapter.on_rpc_response(
        request_id=request_id,
        result=result,
        sent_boundary=sent_boundary,
        boundary=boundary,
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


def _install_v2_episode(
    reducer: RadarReducer,
    *,
    instrument_name: str = "BTC-1JAN00-101000-C",
    activation_causal_seq: int = 1,
    received_monotonic_ms: int = 110,
    score_band: ScoreBand = ScoreBand.HIGH,
    delta_bucket: DeltaBucket = DeltaBucket.WING_15_30,
) -> str:
    instrument = reducer.options[instrument_name]
    tte_band = reducer.policy.tte_bands[0]
    rule = tte_band.option_rules[instrument.option_type]
    score_result = compute_radar_score(
        reducer.policy.score_model,
        RadarScoreInputs(
            stressed_richness=DecimalInterval(Decimal("1.30"), Decimal("1.31")),
            stressed_executable_bid_iv=DecimalInterval(Decimal("0.49"), Decimal("0.51")),
            local_same_type_mark_iv=Decimal("0.40"),
            surface_source_skew_ms=0,
            current_expiry_atm_mark_iv=Decimal("0.50"),
            adjacent_expiry_atm_mark_iv=Decimal("0.40"),
            term_source_skew_ms=0,
            adverse_semivariance_share=DecimalInterval(Decimal(0), Decimal(0)),
            jump_share=DecimalInterval(Decimal(0), Decimal(0)),
            target_spread_ticks=DecimalInterval(Decimal(1), Decimal(1)),
            bid_consumed_level_count=2,
            ask_consumed_level_count=2,
        ),
    )
    score_result = replace(score_result, band=score_band)
    bucket_key = RadarBucketKey(
        tte_band_id=tte_band.band_id,
        expiry_ms=instrument.expiration_timestamp_ms,
        option_type=instrument.option_type,
        delta_bucket=delta_bucket.value,
    )
    packet = build_radar_score_packet(
        policy_identity=reducer.policy.identity,
        fact_boundary={
            "code_identity": reducer.code_identity,
            "runtime_identity": reducer.runtime_identity,
            "session_epoch": 1,
            "ingress_seq": activation_causal_seq,
            "received_monotonic_ms": received_monotonic_ms,
            "causal_seq": activation_causal_seq,
        },
        bucket_key=bucket_key,
        leader_instrument_name=instrument_name,
        result=score_result,
        oi_diagnostic=compute_unsigned_oi_concentration(
            open_interest=Decimal(1),
            option_gamma=Decimal("0.01"),
            bucket_total_unsigned_gamma_weight=Decimal("0.01"),
        ),
        stressed_richness=DecimalInterval(Decimal("1.30"), Decimal("1.31")),
        leader_coverage=LeaderCoverage.COMPLETE,
    )
    bucket_tracker = RadarBucketEpisodeTracker(
        runtime_identity=reducer.runtime_identity,
        policy_identity=reducer.policy.identity,
        bucket_key=bucket_key,
        score_model=reducer.policy.score_model,
        clue_eligible=True,
    )
    separation = max(rule.minimum_separation_ms, 1)
    for index in range(rule.activation_observation_count):
        trusted_ms = 1_000_000 + index * separation
        bucket_tracker.observe(
            packet=packet,
            observation_identity=("test-v2-score", instrument_name, index),
            causal_seq=activation_causal_seq,
            trusted_time=TimeInterval(trusted_ms, trusted_ms),
            rule=rule,
        )
    assert bucket_tracker.episode is not None
    reducer.bucket_trackers[bucket_key] = bucket_tracker
    reducer.score_bucket_keys[instrument_name] = bucket_key
    reducer.score_results[instrument_name] = score_result
    reducer.score_packets[instrument_name] = packet
    reducer.bucket_leader_by_key[bucket_key] = instrument_name
    reducer.bucket_leader_coverage[bucket_key] = LeaderCoverage.COMPLETE
    compatibility = EpisodeTracker(
        runtime_identity=reducer.runtime_identity,
        policy_identity=reducer.policy.identity,
        instrument_name=instrument_name,
    )
    compatibility.state = (
        TrackerState.ACTIVE if score_band is ScoreBand.HIGH else TrackerState.ARMED
    )
    compatibility.episode_id = (
        bucket_tracker.episode.episode_identity if score_band is ScoreBand.HIGH else None
    )
    compatibility.activation_band_id = tte_band.band_id if score_band is ScoreBand.HIGH else None
    compatibility.activation_causal_seq = (
        activation_causal_seq if score_band is ScoreBand.HIGH else None
    )
    reducer.trackers[instrument_name] = compatibility
    calculation = SimpleNamespace(
        baseline=SimpleNamespace(window_diagnostics=()),
        delta=SimpleNamespace(lower=Decimal("0.19"), upper=Decimal("0.21")),
        delta_bucket=delta_bucket,
        executable_bid_iv=SimpleNamespace(lower=Decimal("0.49"), upper=Decimal("0.51")),
        stressed_executable_bid_iv=SimpleNamespace(lower=Decimal("0.49"), upper=Decimal("0.51")),
        richness=SimpleNamespace(lower=Decimal("1.30"), upper=Decimal("1.31")),
        band=tte_band,
        rule=rule,
        delta_clue_eligible=True,
        target_spread_ticks=Decimal("2"),
        target_bid=SimpleNamespace(consumed=()),
        target_ask=SimpleNamespace(consumed=()),
        score_result=score_result,
    )
    reducer.results[instrument_name] = cast(
        Any,
        SimpleNamespace(
            calculation=calculation,
            current_evaluation=SimpleNamespace(calculation=calculation),
            detector_state=compatibility.detector_state,
            reason=None,
            band_id=tte_band.band_id,
            known_evaluation=True,
            full_formula_evaluation=True,
            score_result=score_result,
            score_packet=packet,
        ),
    )
    return bucket_tracker.episode.episode_identity


def _shadow_system(
    tmp_path: Path,
) -> tuple[RadarReducer, FixedContractShadowRuntimeAdapter, FixedContractShadowOwner]:
    policies = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json",
        underwriting_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-underwriting.json",
        position_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-position.json",
        radar_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )
    runtime_identity = "sha256:" + "b" * 64
    bindings = RuntimeBindings(
        code_identity="a" * 40,
        runtime_identity=runtime_identity,
        radar_policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_policy_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_policy_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
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
            policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
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
        instrument_name="BTC-1JAN00-101000-C",
        expiration_timestamp_ms=946_684_800_000,
        strike=Decimal("101000"),
        option_type=OptionType.CALL,
        amount=amount,
        lifecycle_state=InstrumentLifecycleState.OPEN,
        is_active=True,
        taker_commission=Decimal("0.0003"),
        price_tick=PriceTickMetadata(Decimal("0.00001")),
    )
    long = OptionInstrument(
        instrument_name="BTC-1JAN00-102000-C",
        expiration_timestamp_ms=946_684_800_000,
        strike=Decimal("102000"),
        option_type=OptionType.CALL,
        amount=amount,
        lifecycle_state=InstrumentLifecycleState.OPEN,
        is_active=True,
        taker_commission=Decimal("0.0003"),
        price_tick=PriceTickMetadata(Decimal("0.00001")),
    )
    reducer.catalog_options = {short.instrument_name: short, long.instrument_name: long}
    reducer.options = dict(reducer.catalog_options)
    reducer.option_catalog.source_complete = True
    reducer.option_catalog.complete = True
    reducer.combos["BTC-COMBO"] = ComboInstrument(
        instrument_name="BTC-COMBO",
        state="active",
        legs=(
            ComboLeg("BTC-1JAN00-101000-C", Decimal("1")),
            ComboLeg("BTC-1JAN00-102000-C", Decimal("-1")),
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
            "bids": [["new", "0.00300", "0.1"]],
            "asks": [["new", "0.00301", "0.1"]],
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
    reducer.tickers["BTC-1JAN00-101000-C"] = TickerState(
        forward_usdc=Decimal("100000"),
        underlying_index="index_price",
        source_timestamp_ms=1_000_000,
        signed_delta=Decimal("0.2"),
        mark_iv_fraction=Decimal("0.5"),
    )
    _install_v2_episode(reducer)
    reducer.option_books = {}
    for instrument_name, bid, ask in (
        ("BTC-1JAN00-101000-C", "0.00300", "0.00301"),
        ("BTC-1JAN00-102000-C", "0.00100", "0.00101"),
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


def test_activation_scope_uses_episode_packet_when_current_packet_cache_is_absent(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    instrument_name = "BTC-1JAN00-101000-C"
    _install_v2_episode(reducer, instrument_name=instrument_name)
    tracker = next(
        value
        for value in reducer.bucket_trackers.values()
        if value.episode is not None and value.episode.leader_instrument_name == instrument_name
    )
    assert tracker.episode is not None
    activation_packet = tracker.episode.activation_packet
    reducer.score_packets.pop(instrument_name)

    snapshots = reducer.active_radar_scope_snapshots(
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        )
    )

    assert len(snapshots) == 1
    assert snapshots[0].episode_identity == tracker.episode.episode_identity
    assert snapshots[0].activation_score_packet is activation_packet
    assert snapshots[0].radar_score_packet is activation_packet

    intents = adapter.on_settled_transaction(
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    assert len(_object_payloads(owner, "UNDERWRITING_DECISION_BATCH_DESIGNATION")) == 1
    assert len(owner.active_candidate_identities) == 1
    assert len(intents) == 2


def _activate_real_episode(reducer: RadarReducer) -> str:
    rule = reducer.policy.tte_bands[0].option_rules[OptionType.CALL]
    reducer.bucket_trackers.clear()
    reducer.score_bucket_keys.clear()
    reducer.score_results.clear()
    reducer.score_packets.clear()
    reducer.bucket_leader_by_key.clear()
    reducer.bucket_leader_coverage.clear()
    return _install_v2_episode(
        reducer,
        activation_causal_seq=rule.activation_observation_count,
        received_monotonic_ms=120,
    )


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
    reducer.bucket_trackers.clear()
    reducer.score_packets.clear()
    reducer.score_results.clear()
    reducer.score_bucket_keys.clear()
    reducer.bucket_leader_by_key.clear()
    reducer.bucket_leader_coverage.clear()
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
    intents = _settled_transaction(
        adapter,
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
    assert facts.short_leg_instrument_name == "BTC-1JAN00-101000-C"
    assert facts.atomic_state == expected_atomic_state
    assert [value["object_kind"] for value in owner.state_store.objects] == [
        "UNDERWRITING_AVAILABILITY_EVALUATION",
        "UNDERWRITING_DECISION_BATCH_DESIGNATION",
    ]
    assert _object_payloads(owner, "SELECTED_UNDERWRITING_DECISION") == []


def test_same_activation_batch_designates_before_action_and_unknown_has_no_fallback(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    second_name = "BTC-1JAN00-100500-C"
    second = replace(
        reducer.options["BTC-1JAN00-101000-C"],
        instrument_name=second_name,
        strike=Decimal("100500"),
    )
    reducer.options[second_name] = second
    reducer.catalog_options[second_name] = second
    reducer.tickers[second_name] = replace(reducer.tickers["BTC-1JAN00-101000-C"])
    second_book = ContinuousOrderBook(second_name)
    second_book.apply(
        {
            "type": "snapshot",
            "instrument_name": second_name,
            "change_id": 10,
            "timestamp": 1_000_010,
            "bids": [["new", "0.00300", "0.1"]],
            "asks": [["new", "0.00301", "0.1"]],
        },
        110,
    )
    reducer.option_books[second_name] = second_book
    reducer.accepted_book_receipts[second_name] = AcceptedBookReceipt(
        instrument_name=second_name,
        snapshot_kind="snapshot",
        prev_change_id=None,
        change_id=10,
        source_timestamp_ms=1_000_010,
        session_epoch=1,
        subscription_generation=1,
        boundary=FactBoundary(1, 1, 110, 1),
    )
    _install_v2_episode(
        reducer,
        instrument_name=second_name,
        delta_bucket=DeltaBucket.NEAR_ATM_30_40,
    )
    episodes = tuple(
        sorted(
            tracker.episode.episode_identity
            for tracker in reducer.bucket_trackers.values()
            if tracker.episode is not None
        )
    )
    batch_identity = selected_decision_batch_identity(
        bindings=owner.bindings,
        activation_causal_seq=1,
    )
    designated = designate_selected_decision_episode(
        bindings=owner.bindings,
        batch_identity=batch_identity,
        episode_identities=episodes,
    )
    designated_instrument = next(
        tracker.episode.leader_instrument_name
        for tracker in reducer.bucket_trackers.values()
        if tracker.episode is not None and tracker.episode.episode_identity == designated
    )
    reducer.tickers.pop(designated_instrument)

    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    (designation,) = _object_payloads(owner, "UNDERWRITING_DECISION_BATCH_DESIGNATION")
    assert designation["batch_member_episode_identities"] == list(episodes)
    assert designation["designated_episode_identity"] == designated
    assert _object_payloads(owner, "SELECTED_UNDERWRITING_DECISION") == []
    assert len(_object_payloads(owner, "CANDIDATE_ACTIVATION")) == 1
    assert len(intents) == 2


def test_inactive_underwriting_scope_transitions_once_then_stays_settled(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    active_commit = _commit(
        causal_seq=1,
        monotonic_ms=110,
        cause=CausalCause.COMBO_BOOK_CHANGED,
    )
    admission_intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=active_commit,
    )
    assert len(admission_intents) == 2
    assert {str(intent.params["instrument_name"]) for intent in admission_intents} == {
        "BTC-1JAN00-101000-C",
        "BTC-1JAN00-102000-C",
    }
    (active,) = adapter._underwriting_by_scope.values()
    assert active.active_episode_identity is not None

    reducer.trackers.clear()
    reducer.bucket_trackers.clear()
    reducer.score_packets.clear()
    reducer.score_results.clear()
    reducer.score_bucket_keys.clear()
    reducer.bucket_leader_by_key.clear()
    reducer.bucket_leader_coverage.clear()
    inactive_commit = _commit(
        causal_seq=2,
        monotonic_ms=120,
        cause=CausalCause.TICKER_APPLIED,
    )
    assert (
        _settled_transaction(
            adapter,
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
    assert _settled_transaction(adapter, reducer=reducer, commit=unrelated_commit) == ()
    assert adapter._underwriting_by_scope == {}
    assert owner.state_store.revision == inactive_revision
    assert tuple(owner.state_store.objects) == inactive_objects

    next_episode = _install_v2_episode(
        reducer,
        activation_causal_seq=4,
        received_monotonic_ms=140,
    )
    _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=4,
            monotonic_ms=140,
            cause=CausalCause.COMBO_BOOK_CHANGED,
        ),
    )
    assert owner.state_store.revision > inactive_revision
    assert any(
        facts.active_episode_identity == next_episode
        for facts in adapter._underwriting_by_scope.values()
    )


def test_episode_retirement_reconciles_an_already_terminal_candidate_attempt(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    assert len(intents) == 2
    assert owner.retained_state_counts["active_candidates"] == 1
    (record,) = owner._candidates.values()
    episode_identity = record.facts.active_episode_identity
    assert episode_identity is not None
    attempt_boundary = DownstreamFactBoundary(
        code_identity=owner.bindings.code_identity,
        runtime_identity=owner.bindings.runtime_identity,
        session_epoch=1,
        ingress_seq=2,
        received_monotonic_ms=120,
        causal_seq=2,
    )
    assert record.attempt.invalidate_before_refresh(
        source_identity=canonical_identity("TestAttemptTerminal", episode_identity),
        boundary=attempt_boundary,
    )
    owner._emit_admission_terminal(record)

    transition = owner.retire_radar_episode(
        episode_identity,
        boundary=replace(
            attempt_boundary,
            ingress_seq=3,
            received_monotonic_ms=130,
            causal_seq=3,
        ),
    )

    assert owner.retained_state_counts["active_candidates"] == 0
    assert [item.object_kind for item in transition.emitted] == ["CANDIDATE_INVALIDATION"]
    assert _terminal_outcomes(owner) == ["KNOWN_INVALIDATED_BEFORE_REFRESH"]


def test_episode_retirement_clears_candidate_from_an_interrupted_terminal_transition(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    assert len(intents) == 2
    (record,) = owner._candidates.values()
    episode_identity = record.facts.active_episode_identity
    assert episode_identity is not None
    interrupted_boundary = DownstreamFactBoundary(
        code_identity=owner.bindings.code_identity,
        runtime_identity=owner.bindings.runtime_identity,
        session_epoch=1,
        ingress_seq=2,
        received_monotonic_ms=120,
        causal_seq=2,
    )
    owner._begin_transition()
    owner._terminalize_candidate_before_refresh(
        record,
        reasons=("SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN",),
        boundary=interrupted_boundary,
    )
    assert record.state.lifecycle.value == "INVALIDATED"
    assert owner.retained_state_counts["active_candidates"] == 1

    transition = owner.retire_radar_episode(
        episode_identity,
        boundary=replace(
            interrupted_boundary,
            ingress_seq=3,
            received_monotonic_ms=130,
            causal_seq=3,
        ),
    )

    assert transition.emitted == ()
    assert owner.retained_state_counts["active_candidates"] == 0
    assert _terminal_outcomes(owner) == ["KNOWN_INVALIDATED_BEFORE_REFRESH"]


def test_no_active_radar_episode_skips_review_context_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer, adapter, _owner = _shadow_system(tmp_path)
    reducer.trackers.clear()
    reducer.bucket_trackers.clear()
    reducer.score_packets.clear()

    def unexpected_review_projection(_reducer: RadarReducer) -> dict[str, object]:
        raise AssertionError("review contexts have no consumer without an active Radar Episode")

    monkeypatch.setattr(adapter, "_review_contexts", unexpected_review_projection)

    assert (
        _settled_transaction(
            adapter,
            reducer=reducer,
            commit=_commit(
                causal_seq=1,
                monotonic_ms=110,
                cause=CausalCause.OPTION_BOOK_FACT,
            ),
        )
        == ()
    )


def test_frozen_component_selection_skips_unused_review_context_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer, adapter, _owner = _shadow_system(tmp_path)
    first = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    assert len(first) == 2
    assert len(adapter._frozen_component_by_episode) == 1

    def unexpected_review_projection(_reducer: RadarReducer) -> dict[str, object]:
        raise AssertionError("frozen component selection does not consume review contexts")

    monkeypatch.setattr(adapter, "_review_contexts", unexpected_review_projection)

    assert (
        _settled_transaction(
            adapter,
            reducer=reducer,
            commit=_commit(
                causal_seq=2,
                monotonic_ms=120,
                cause=CausalCause.OPTION_BOOK_FACT,
            ),
        )
        == ()
    )


def test_frozen_component_structure_does_not_switch_to_a_later_protective_leg(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    first_intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.COMBO_BOOK_CHANGED,
        ),
    )
    assert len(first_intents) == 2
    (current_facts,) = adapter._underwriting_by_scope.values()
    assert current_facts.long_leg_instrument_name == "BTC-1JAN00-102000-C"

    original = reducer.options["BTC-1JAN00-102000-C"]
    alternative = replace(
        original,
        instrument_name="BTC-1JAN00-101500-C",
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
            "bids": [["new", "0.00120", "0.1"]],
            "asks": [["new", "0.00121", "0.1"]],
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
        _settled_transaction(
            adapter,
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
    assert current_facts.long_leg_instrument_name == "BTC-1JAN00-102000-C"
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
        _settled_transaction(
            adapter,
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

    original = reducer.options["BTC-1JAN00-102000-C"]
    better = replace(
        original,
        instrument_name="BTC-1JAN00-103000-C",
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
            "bids": [["new", "0.00049", "0.1"]],
            "asks": [["new", "0.00050", "0.1"]],
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

    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=2,
            monotonic_ms=120,
            cause=CausalCause.OPTION_CATALOG,
        ),
    )

    (complete,) = adapter._underwriting_by_scope.values()
    assert complete.long_leg_instrument_name == "BTC-1JAN00-103000-C"
    assert complete.protective_leg_selection_rule_identity is not None
    assert complete.candidate_protective_leg_count == 2
    assert len(intents) == 2
    assert owner.retained_state_counts["active_candidates"] == 1


def test_underwriting_selector_can_choose_candidate_outside_radar_display_top_three(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    original = reducer.options["BTC-1JAN00-102000-C"]
    first_boundary = FactBoundary(1, 1, 110, 1)
    for suffix, strike, bid, ask in (
        ("A", "101250", "0.00126", "0.00127"),
        ("B", "101500", "0.00122", "0.00123"),
        ("C", "101750", "0.00113", "0.00114"),
    ):
        alternative = replace(
            original,
            instrument_name=f"BTC-1JAN00-102000-C-{suffix}",
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
        for reference in adapter._review_contexts(reducer)[
            "BTC-1JAN00-101000-C"
        ].legged_structure.references
    }
    assert len(top_three) == 3
    assert "BTC-1JAN00-102000-C" not in top_three

    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    (current_facts,) = adapter._underwriting_by_scope.values()
    assert current_facts.long_leg_instrument_name == "BTC-1JAN00-102000-C"
    assert len(intents) == 2
    assert owner.retained_state_counts["active_candidates"] == 1


@pytest.mark.parametrize("variant", ("inactive", "amount_ineligible"))
def test_known_illegal_protective_leg_without_book_does_not_poison_selection(
    tmp_path: Path,
    variant: str,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    original = reducer.options["BTC-1JAN00-102000-C"]
    if variant == "inactive":
        illegal = replace(
            original,
            instrument_name="BTC-1JAN00-103000-C",
            strike=Decimal("103000"),
            lifecycle_state=InstrumentLifecycleState.INACTIVE,
            is_active=False,
        )
    else:
        illegal = replace(
            original,
            instrument_name="BTC-1JAN00-103000-C",
            strike=Decimal("103000"),
            amount=AmountMetadata(
                contract_size=Decimal("1"),
                min_trade_amount=Decimal("0.2"),
                qty_tick_size=Decimal("0.1"),
            ),
        )
    reducer.options[illegal.instrument_name] = illegal
    reducer.catalog_options[illegal.instrument_name] = illegal

    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_CATALOG,
        ),
    )

    (facts,) = adapter._underwriting_by_scope.values()
    assert facts.long_leg_instrument_name == "BTC-1JAN00-102000-C"
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
    original = reducer.options["BTC-1JAN00-102000-C"]
    unknown = (
        replace(original, amount=None) if field == "amount" else replace(original, price_tick=None)
    )
    reducer.options[unknown.instrument_name] = unknown
    reducer.catalog_options[unknown.instrument_name] = unknown

    assert (
        _settled_transaction(
            adapter,
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
    assert facts.component_blockers == (f"BTC-1JAN00-102000-C:{reason}",)
    assert owner.retained_state_counts["active_candidates"] == 0


def test_underwriting_selector_keeps_missing_legal_leg_input_unknown(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    missing = replace(
        reducer.options["BTC-1JAN00-102000-C"],
        instrument_name="BTC-1JAN00-103000-C",
        strike=Decimal("103000"),
    )
    reducer.options[missing.instrument_name] = missing
    reducer.catalog_options[missing.instrument_name] = missing

    intents = _settled_transaction(
        adapter,
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
    assert facts.component_blockers == ("BTC-1JAN00-103000-C:BOOK_UNKNOWN",)
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
    _settled_transaction(adapter, reducer=reducer, commit=commit)

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
    tracker = reducer.trackers["BTC-1JAN00-101000-C"]
    replacements = {
        "runtime": exact.replace(reducer.runtime_identity, "sha256:" + "c" * 64, 1),
        "policy": exact.replace(reducer.policy.identity, "sha256:" + "d" * 64, 1),
        "instrument": exact.replace("BTC-1JAN00-101000-C", "BTC-1JAN00-99000-C", 1),
        "activation_seq": exact.rsplit(":", 1)[0] + ":1",
        "truncated": exact[:-1],
    }
    tracker.episode_id = replacements[variant]

    with pytest.raises(ValueError):
        _settled_transaction(
            adapter,
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
            instrument_name="BTC-1JAN00-101000-C",
            expiration_timestamp_ms=946_684_800_000,
            strike=Decimal("101000"),
            option_type=OptionType.CALL,
            amount=None,
        ),
        canonical_identity("ShortIdentity"),
        _downstream_source("ShortSource"),
    )
    long = _OptionSource(
        OptionInstrument(
            instrument_name="BTC-1JAN00-102000-C",
            expiration_timestamp_ms=946_684_800_000,
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
            instrument_name="BTC-1JAN00-101000-C",
            expiration_timestamp_ms=946_684_800_000,
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
                ComboLeg("BTC-1JAN00-101000-C", Decimal("1")),
                ComboLeg("BTC-1JAN00-102000-C", Decimal("-1")),
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
    amount = reducer.options["BTC-1JAN00-101000-C"].amount
    assert amount is not None
    short = _OptionSource(
        reducer.options["BTC-1JAN00-101000-C"],
        canonical_identity("ShortIdentity"),
        _downstream_source("ShortSource"),
    )
    long = _OptionSource(
        reducer.options["BTC-1JAN00-102000-C"],
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
    bid_price: str = "0.00300",
    ask_price: str = "0.00301",
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
    reducer.tickers["BTC-1JAN00-101000-C"] = replace(
        reducer.tickers["BTC-1JAN00-101000-C"],
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
        reducer.options["BTC-1JAN00-101000-C"],
        lifecycle_state=InstrumentLifecycleState.DELIVERED,
        is_active=False,
    )
    long = replace(
        reducer.options["BTC-1JAN00-102000-C"],
        lifecycle_state=InstrumentLifecycleState.ARCHIVIZED,
        is_active=False,
    )
    reducer.options = {"BTC-1JAN00-101000-C": short, "BTC-1JAN00-102000-C": long}
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
    reducer: RadarReducer,
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
        is_short = instrument_name == "BTC-1JAN00-101000-C"
        amount = "0.1" if is_short else long_amount
        accepted_seq = first_causal_seq + 2 + offset
        _rpc_response(
            adapter,
            reducer=reducer,
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
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="0.00300",
        short_ask="0.00301",
        long_bid="0.00100",
        long_ask="0.00101",
    )
    return intents


def test_component_candidate_requires_both_strictly_later_option_book_responses(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    assert len(intents) == 2
    assert {str(intent.params["instrument_name"]) for intent in intents} == {
        "BTC-1JAN00-101000-C",
        "BTC-1JAN00-102000-C",
    }
    assert owner.state_store.retained_state_counts["active_or_latest_terminal_cases"] == 0
    (selected,) = _object_payloads(owner, "SELECTED_UNDERWRITING_DECISION")
    assert selected["economic_action"] == "CANDIDATE"
    assert selected["enrollment_route"] == "ADMITTED_SHADOW_TRADE"

    sent = FactBoundary(1, 2, 120, 2)
    first = next(
        intent for intent in intents if intent.params["instrument_name"] == "BTC-1JAN00-101000-C"
    )
    adapter.on_request_sent(request_id=first.request_id, boundary=sent)
    assert (
        _rpc_response(
            adapter,
            reducer=reducer,
            request_id=first.request_id,
            result=_rest_option_book(
                "BTC-1JAN00-101000-C",
                bid_price="0.00300",
                ask_price="0.00301",
                change_id=11,
            ),
            sent_boundary=sent,
            boundary=FactBoundary(1, 3, 130, 3),
        )
        == ()
    )
    assert not _object_payloads(owner, "SHADOW_ENTRY")
    assert owner.state_store.retained_state_counts["active_or_latest_terminal_cases"] == 0

    second = next(
        intent for intent in intents if intent.params["instrument_name"] == "BTC-1JAN00-102000-C"
    )
    second_sent = FactBoundary(1, 4, 140, 4)
    adapter.on_request_sent(request_id=second.request_id, boundary=second_sent)
    _rpc_response(
        adapter,
        reducer=reducer,
        request_id=second.request_id,
        result=_rest_option_book(
            "BTC-1JAN00-102000-C",
            bid_price="0.00100",
            ask_price="0.00101",
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
    assert entry["selected_underwriting_decision"]["selected_economic_action"] == "CANDIDATE"
    assert entry["selected_underwriting_decision"]["refreshed_economic_action"] == "CANDIDATE"
    assert entry["entry_refresh_terminal_outcome"] == "ENTRY_EMITTED"
    assert entry["entry_refresh_terminal_unknown_reasons"] == []
    (research_row,) = workbench_module._decision_control_rows(
        workbench_module._objects_by_kind(owner.state_store.objects)
    )
    assert research_row["refresh_terminal_outcome"] == "ENTRY_EMITTED"
    assert research_row["refresh_unknown_reasons"] == []
    assert research_row["protective_leg_selection_rule_identity"] is not None
    assert research_row["candidate_protective_leg_count"] == 1
    assert _object_payloads(owner, "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN") == []
    assert owner.state_store.retained_state_counts["active_or_latest_terminal_cases"] == 1


def test_reducer_rpc_response_recomputes_exact_score_boundary_before_pair_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    short_name = "BTC-1JAN00-101000-C"
    long_name = "BTC-1JAN00-102000-C"
    band = reducer.policy.tte_bands[0]
    rule = band.option_rules[OptionType.CALL]
    diagnostic = SimpleNamespace(
        lookback_minutes=60,
        variance_rate_per_minute=Decimal("0.0001"),
        positive_semivariance_share=Decimal("0.2"),
        negative_semivariance_share=Decimal("0.8"),
        jump_share=Decimal("0.1"),
        maximum_absolute_return=Decimal("0.01"),
        net_return=Decimal("0"),
    )
    calculation = _ResponseScoreCalculation(
        band=band,
        rule=rule,
        target_bid=SimpleNamespace(consumed=(object(), object())),
        target_ask=SimpleNamespace(consumed=(object(), object())),
        stressed_executable_bid_iv=DecimalInterval(Decimal("0.49"), Decimal("0.51")),
        delta=DecimalInterval(Decimal("0.19"), Decimal("0.21")),
        delta_bucket=DeltaBucket.WING_15_30,
        delta_clue_eligible=True,
        target_spread_ticks=Decimal("2"),
        richness=DecimalInterval(Decimal("1.30"), Decimal("1.31")),
        baseline=SimpleNamespace(
            window_diagnostics=(diagnostic,),
            selected_lookback_minutes=None,
        ),
    )

    def response_current_evaluation(**kwargs: object) -> CurrentEvaluation:
        instrument = cast(OptionInstrument, kwargs["instrument"])
        if instrument.instrument_name != short_name:
            return CurrentEvaluation(
                disposition=CurrentDisposition.UNKNOWN,
                reason="TEST_NON_LEADER_UNKNOWN",
                known_evaluation=False,
                full_formula_evaluation=False,
                band_id=None,
            )
        return CurrentEvaluation(
            disposition=CurrentDisposition.SCORE_PENDING,
            reason="V2_SCORE_FEATURES_PENDING",
            known_evaluation=False,
            full_formula_evaluation=False,
            band_id=band.band_id,
            calculation=cast(Any, calculation),
        )

    monkeypatch.setattr(
        runtime_module,
        "calculate_current_evaluation",
        response_current_evaluation,
    )
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    assert len(intents) == 2
    response_settle_causes: list[CausalCause] = []
    original_settled_transaction = adapter.on_settled_transaction

    def record_response_settle(
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
    ) -> tuple[ShadowRpcIntent, ...]:
        response_settle_causes.append(commit.cause)
        return original_settled_transaction(reducer=reducer, commit=commit)

    monkeypatch.setattr(adapter, "on_settled_transaction", record_response_settle)
    reducer._causal_seq = 1
    reducer._schedule_shadow_intents(intents)
    requests = reducer._take_commands()
    assert len(requests) == 2
    requests_by_name = {str(request.params["instrument_name"]): request for request in requests}

    short_request = requests_by_name[short_name]
    assert (
        reducer.reduce(
            InboundEnvelope(
                {},
                session_epoch=1,
                ingress_seq=1,
                received_monotonic_ms=120,
                control_event=SendControlEvent(
                    kind=SendControlKind.SEND_COMPLETED,
                    request_id=short_request.request_id,
                    boundary_monotonic_ms=120,
                ),
            ),
            processed_monotonic_ms=120,
        )
        == ()
    )
    first_commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": short_request.request_id,
                "result": _rest_option_book(
                    short_name,
                    bid_price="0.00300",
                    ask_price="0.00301",
                    change_id=11,
                ),
            },
            session_epoch=1,
            ingress_seq=2,
            received_monotonic_ms=130,
        ),
        processed_monotonic_ms=130,
    )
    first_packet = reducer.score_packets[short_name]
    assert first_packet.fact_boundary["ingress_seq"] == 2
    assert first_packet.fact_boundary["causal_seq"] == 3
    premium_factor = next(
        factor for factor in first_packet.result.factors if factor.name.value == "A"
    )
    assert premium_factor.normalized is not None
    assert not _object_payloads(owner, "SHADOW_ENTRY")
    assert not any(command.purpose is RpcPurpose.ADMISSION_REFRESH for command in first_commands)

    long_request = requests_by_name[long_name]
    assert (
        reducer.reduce(
            InboundEnvelope(
                {},
                session_epoch=1,
                ingress_seq=3,
                received_monotonic_ms=140,
                control_event=SendControlEvent(
                    kind=SendControlKind.SEND_COMPLETED,
                    request_id=long_request.request_id,
                    boundary_monotonic_ms=140,
                ),
            ),
            processed_monotonic_ms=140,
        )
        == ()
    )
    second_commands = reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "id": long_request.request_id,
                "result": _rest_option_book(
                    long_name,
                    bid_price="0.00100",
                    ask_price="0.00101",
                    change_id=11,
                ),
            },
            session_epoch=1,
            ingress_seq=4,
            received_monotonic_ms=150,
        ),
        processed_monotonic_ms=150,
    )
    assert not any(command.purpose is RpcPurpose.ADMISSION_REFRESH for command in second_commands)
    second_packet = reducer.score_packets[short_name]
    assert second_packet.fact_boundary["ingress_seq"] == 4
    assert second_packet.fact_boundary["causal_seq"] == 5
    assert second_packet.fact_boundary != first_packet.fact_boundary

    (entry,) = _object_payloads(owner, "SHADOW_ENTRY")
    assert entry["selection_score_packet"]["fact_boundary"]["causal_seq"] == 1
    refresh_packet = entry["entry_refresh_score_packet"]
    assert refresh_packet["fact_boundary"] == second_packet.as_object()["fact_boundary"]
    assert refresh_packet["result"] == second_packet.as_object()["result"]
    assert refresh_packet["sampling_metadata"]["kind"] == "CANONICAL_HIGH"
    assert (
        entry["selection_score_packet"]["sampling_metadata"] == refresh_packet["sampling_metadata"]
    )
    assert len(_object_payloads(owner, "SELECTED_UNDERWRITING_DECISION")) == 1
    assert response_settle_causes == [
        CausalCause.SHADOW_RPC_RESPONSE,
        CausalCause.SHADOW_RPC_RESPONSE,
    ]


def test_mid_bucket_confirmation_reaches_paired_refresh_and_opens_only_control(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    reducer.trackers.clear()
    reducer.bucket_trackers.clear()
    reducer.score_packets.clear()
    reducer.score_results.clear()
    reducer.score_bucket_keys.clear()
    reducer.bucket_leader_by_key.clear()
    reducer.bucket_leader_coverage.clear()
    review_identity = _install_v2_episode(reducer, score_band=ScoreBand.MID)

    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    assert len(intents) == 2
    (facts,) = adapter._underwriting_by_scope.values()
    assert facts.active_episode_identity is None
    assert facts.radar_research_review_identity == review_identity
    assert facts.radar_research_activation_seq == 1
    assert facts.radar_score_packet is not None
    assert facts.radar_score_packet.result.band is ScoreBand.MID
    (selected,) = _object_payloads(owner, "SELECTED_UNDERWRITING_DECISION")
    assert selected["selection_kind"] == "RADAR_SCORE_BAND_NO_TRADE_CONTROL"
    assert selected["active_episode_identity"] is None
    assert selected["radar_research_review_identity"] == review_identity
    assert not _object_payloads(owner, "CANDIDATE_ACTIVATION")

    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="0.00300",
        short_ask="0.00301",
        long_bid="0.00100",
        long_ask="0.00101",
    )

    assert not _object_payloads(owner, "SHADOW_ENTRY")
    (control,) = _object_payloads(owner, "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OPEN")
    assert control["enrollment_kind"] == "RADAR_SCORE_BAND_NO_TRADE_CONTROL"
    assert control["selection_score_packet"]["result"]["band"] == "MID"
    assert control["entry_refresh_score_packet"]["fact_boundary"]["causal_seq"] == 5


def test_same_causal_batch_high_suppresses_mid_control_designation(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    mid_name = "BTC-1JAN00-100500-C"
    mid_option = replace(
        reducer.options["BTC-1JAN00-101000-C"],
        instrument_name=mid_name,
        strike=Decimal("100500"),
    )
    reducer.options[mid_name] = mid_option
    reducer.catalog_options[mid_name] = mid_option
    reducer.tickers[mid_name] = replace(reducer.tickers["BTC-1JAN00-101000-C"])
    mid_book = ContinuousOrderBook(mid_name)
    mid_book.apply(
        {
            "type": "snapshot",
            "instrument_name": mid_name,
            "change_id": 10,
            "timestamp": 1_000_010,
            "bids": [["new", "0.00300", "0.1"]],
            "asks": [["new", "0.00301", "0.1"]],
        },
        110,
    )
    reducer.option_books[mid_name] = mid_book
    reducer.accepted_book_receipts[mid_name] = AcceptedBookReceipt(
        instrument_name=mid_name,
        snapshot_kind="snapshot",
        prev_change_id=None,
        change_id=10,
        source_timestamp_ms=1_000_010,
        session_epoch=1,
        subscription_generation=1,
        boundary=FactBoundary(1, 1, 110, 1),
    )
    mid_identity = _install_v2_episode(
        reducer,
        instrument_name=mid_name,
        score_band=ScoreBand.MID,
        delta_bucket=DeltaBucket.NEAR_ATM_30_40,
    )

    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    assert len(adapter._underwriting_by_scope) == 2
    assert any(
        facts.radar_research_review_identity == mid_identity
        for facts in adapter._underwriting_by_scope.values()
    )
    (selected,) = _object_payloads(owner, "SELECTED_UNDERWRITING_DECISION")
    assert selected["selection_kind"] == "HIGH_ACTION_BLIND"
    assert selected["active_episode_identity"] is not None
    assert selected["radar_research_review_identity"] is None
    assert len(intents) == 2
    assert owner.active_candidate_identities
    assert owner.active_decision_control_identities == frozenset()
    assert not _object_payloads(owner, "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OPEN")


def test_selected_abstain_uses_one_future_pair_without_candidate_or_shadow_entry(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    boundary = FactBoundary(1, 1, 110, 1)
    short_book = ContinuousOrderBook("BTC-1JAN00-101000-C")
    short_book.apply(
        {
            "type": "snapshot",
            "instrument_name": "BTC-1JAN00-101000-C",
            "change_id": 10,
            "timestamp": 1_000_010,
            "bids": [["new", "0.00150", "0.1"]],
            "asks": [["new", "0.00151", "0.1"]],
        },
        110,
    )
    reducer.option_books["BTC-1JAN00-101000-C"] = short_book
    reducer.accepted_book_receipts["BTC-1JAN00-101000-C"] = AcceptedBookReceipt(
        instrument_name="BTC-1JAN00-101000-C",
        snapshot_kind="snapshot",
        prev_change_id=None,
        change_id=10,
        source_timestamp_ms=1_000_010,
        session_epoch=1,
        subscription_generation=1,
        boundary=boundary,
    )

    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    assert len(intents) == 2
    (selection,) = _object_payloads(owner, "SELECTED_UNDERWRITING_DECISION")
    assert selection["economic_action"] == "ABSTAIN"
    assert selection["enrollment_route"] == "SELECTED_UNDERWRITING_DECISION_CONTROL"
    assert _object_payloads(owner, "CANDIDATE_ACTIVATION") == []

    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="0.00150",
        short_ask="0.00151",
        long_bid="0.00100",
        long_ask="0.00101",
    )

    (opened,) = _object_payloads(
        owner,
        "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN",
    )
    observation = opened["selected_underwriting_decision"]
    assert observation["selected_economic_action"] == "ABSTAIN"
    assert observation["refreshed_economic_action"] == "ABSTAIN"
    assert opened["enrollment_kind"] == "SELECTED_UNDERWRITING_DECISION_CONTROL"
    assert _object_payloads(owner, "SHADOW_ENTRY") == []
    assert owner.retained_state_counts["active_trades"] == 1


def test_selected_candidate_that_fails_refresh_uses_that_same_pair_for_no_trade_case(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    assert len(intents) == 2

    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="0.00150",
        short_ask="0.00151",
        long_bid="0.00100",
        long_ask="0.00101",
    )

    assert len(_object_payloads(owner, "CANDIDATE_ACTIVATION")) == 1
    assert _object_payloads(owner, "SHADOW_ENTRY") == []
    (opened,) = _object_payloads(owner, "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN")
    observation = opened["selected_underwriting_decision"]
    assert observation["selected_economic_action"] == "CANDIDATE"
    assert observation["refreshed_economic_action"] == "ABSTAIN"
    assert opened["entry_refresh_attempt_kind"] == "CANDIDATE_ADMISSION"
    assert opened["entry_refresh_terminal_outcome"] == "KNOWN_COMPLETE_NO_ENTRY"
    (research_row,) = workbench_module._decision_control_rows(
        workbench_module._objects_by_kind(owner.state_store.objects)
    )
    assert research_row["refresh_terminal_outcome"] == "KNOWN_COMPLETE_NO_ENTRY"
    assert owner.retained_state_counts["active_decision_control_attempts"] == 0


def test_selected_control_full_quantity_failure_is_exact_workbench_unknown(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    short_book = ContinuousOrderBook("BTC-1JAN00-101000-C")
    short_book.apply(
        {
            "type": "snapshot",
            "instrument_name": "BTC-1JAN00-101000-C",
            "change_id": 10,
            "timestamp": 1_000_010,
            "bids": [["new", "0.00150", "0.1"]],
            "asks": [["new", "0.00151", "0.1"]],
        },
        110,
    )
    reducer.option_books["BTC-1JAN00-101000-C"] = short_book
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="0.00150",
        short_ask="0.00151",
        long_bid="0.00100",
        long_ask="0.00101",
        long_amount="0.05",
    )

    (terminal,) = _object_payloads(
        owner,
        "UNDERWRITING_DECISION_CONTROL_ATTEMPT_TERMINAL",
    )
    assert terminal["terminal_outcome"] == "UNKNOWN_CONSUMED"
    assert terminal["terminal_unknown_reasons"] == ["COMPONENT_PAIR_LONG_FULL_QUANTITY_NOT_COVERED"]
    assert _object_payloads(owner, "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN") == []
    (research_row,) = workbench_module._decision_control_rows(
        workbench_module._objects_by_kind(owner.state_store.objects)
    )
    assert research_row["refresh_terminal_outcome"] == "UNKNOWN_CONSUMED"
    assert research_row["refresh_unknown_reasons"] == terminal["terminal_unknown_reasons"]


def test_selected_abstain_that_refreshes_to_candidate_requires_canonical_admission(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    short_book = ContinuousOrderBook("BTC-1JAN00-101000-C")
    short_book.apply(
        {
            "type": "snapshot",
            "instrument_name": "BTC-1JAN00-101000-C",
            "change_id": 10,
            "timestamp": 1_000_010,
            "bids": [["new", "0.00150", "0.1"]],
            "asks": [["new", "0.00151", "0.1"]],
        },
        110,
    )
    reducer.option_books["BTC-1JAN00-101000-C"] = short_book
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="0.00300",
        short_ask="0.00301",
        long_bid="0.00100",
        long_ask="0.00101",
    )

    (terminal,) = _object_payloads(
        owner,
        "UNDERWRITING_DECISION_CONTROL_ATTEMPT_TERMINAL",
    )
    assert terminal["terminal_outcome"] == ("REFRESHED_CANDIDATE_REQUIRES_CANONICAL_ADMISSION")
    assert terminal["refreshed_economic_action"] == "CANDIDATE"
    assert terminal["refreshed_failed_predicates"] == []
    assert len(terminal["refreshed_predicate_margin_vector"]) == 6
    assert all(item["passes"] for item in terminal["refreshed_predicate_margin_vector"])
    assert _object_payloads(owner, "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN") == []
    assert _object_payloads(owner, "CANDIDATE_ACTIVATION") == []
    assert _object_payloads(owner, "SHADOW_ENTRY") == []
    (research_row,) = workbench_module._decision_control_rows(
        workbench_module._objects_by_kind(owner.state_store.objects)
    )
    assert research_row["refresh_terminal_outcome"] == (
        "REFRESHED_CANDIDATE_REQUIRES_CANONICAL_ADMISSION"
    )
    assert research_row["selected_economic_action"] == "ABSTAIN"
    assert research_row["refreshed_economic_action"] == "CANDIDATE"
    assert research_row["refreshed_failed_predicates"] == []
    assert (
        research_row["refreshed_predicate_margin_vector"]
        == terminal["refreshed_predicate_margin_vector"]
    )
    assert research_row["case_state"] == "NOT_OPENED"
    assert research_row["protective_leg_selection_rule_identity"] is not None
    assert research_row["candidate_protective_leg_count"] == 0
    assert owner.retained_state_counts["active_trades"] == 0


def test_selected_abstain_opens_one_durable_control_case(tmp_path: Path) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    short_book = ContinuousOrderBook("BTC-1JAN00-101000-C")
    short_book.apply(
        {
            "type": "snapshot",
            "instrument_name": "BTC-1JAN00-101000-C",
            "change_id": 10,
            "timestamp": 1_000_010,
            "bids": [["new", "0.00150", "0.1"]],
            "asks": [["new", "0.00151", "0.1"]],
        },
        110,
    )
    reducer.option_books["BTC-1JAN00-101000-C"] = short_book
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    cases = tmp_path / "cases"
    cases.mkdir()
    case_store = ShadowCaseStore(
        cases,
        bindings=owner.bindings,
        policies=owner.policies,
    )
    owner.state_store.observer = case_store

    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="0.00150",
        short_ask="0.00151",
        long_bid="0.00100",
        long_ask="0.00101",
    )

    assert case_store.case_count == 1
    (case_directory,) = cases.iterdir()
    opened = json.loads((case_directory / "opened.json").read_text())
    assert opened["enrollment_kind"] == "SELECTED_UNDERWRITING_DECISION_CONTROL"
    assert opened["shadow_entry_identity"] is None
    assert opened["selected_underwriting_decision"]["selected_economic_action"] == "ABSTAIN"
    assert opened["selected_underwriting_decision"]["refreshed_economic_action"] == "ABSTAIN"
    assert opened["structure"]["entry_component_pair_timing"] == {
        "global_continuity_epochs": [1, 1],
        "receive_skew_ms": 10,
        "session_epochs": [1, 1],
        "source_timestamp_skew_ms": 0,
    }
    assert opened["structure"]["entry_component_pair_limits"] == {
        "maximum_receive_skew_ms": 4_000,
        "maximum_source_skew_ms": 6_000,
    }

    original_opened = json.dumps(opened)
    selected = opened["selected_underwriting_decision"]
    selected["selected_economic_action"] = "CANDIDATE"
    selected["selected_failed_predicates"] = []
    for margin in selected["selected_predicate_margin_vector"]:
        value = abs(Decimal(str(margin["signed_margin"]))) + 1
        margin["signed_margin"] = int(value) if margin["unit"] == "LEVEL_COUNT" else str(value)
        margin["passes"] = True
    (case_directory / "opened.json").write_text(json.dumps(opened), encoding="utf-8")
    with pytest.raises(ShadowCaseStoreError, match="selected decision identity mismatch"):
        case_store.read_case(str(opened["case_id"]))

    opened = json.loads(original_opened)
    selected = opened["selected_underwriting_decision"]
    refreshed_fingerprint = canonical_identity("TamperedRefreshedEconomicFingerprint")
    selected["refreshed_consumed_economic_fact_fingerprint"] = refreshed_fingerprint
    selected["refreshed_underwriting_action_identity"] = canonical_identity(
        "CaseOpenRefreshedUnderwritingActionIdentity",
        selected["selected_underwriting_decision_identity"],
        refreshed_fingerprint,
        selected["refreshed_economic_action"],
        opened["underwriting"]["protective_leg_selection_rule_identity"],
        opened["underwriting"]["candidate_protective_leg_count"],
        DownstreamFactBoundary.from_object(selected["refreshed_fact_boundary"]).as_object(),
    )
    (case_directory / "opened.json").write_text(json.dumps(opened), encoding="utf-8")
    with pytest.raises(
        ShadowCaseStoreError,
        match="refreshed Underwriting projection is inconsistent",
    ):
        case_store.read_case(str(opened["case_id"]))


def test_component_admission_pair_over_skew_budget_is_exact_unknown_without_case(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    short_intent = next(
        value for value in intents if value.params["instrument_name"] == "BTC-1JAN00-101000-C"
    )
    long_intent = next(
        value for value in intents if value.params["instrument_name"] == "BTC-1JAN00-102000-C"
    )
    short_sent = FactBoundary(1, 2, 120, 2)
    long_sent = FactBoundary(1, 3, 121, 3)
    adapter.on_request_sent(request_id=short_intent.request_id, boundary=short_sent)
    adapter.on_request_sent(request_id=long_intent.request_id, boundary=long_sent)
    _rpc_response(
        adapter,
        reducer=reducer,
        request_id=short_intent.request_id,
        result=_rest_option_book(
            "BTC-1JAN00-101000-C",
            bid_price="0.00300",
            ask_price="0.00301",
            change_id=11,
            timestamp_ms=1_000_000,
        ),
        sent_boundary=short_sent,
        boundary=FactBoundary(1, 4, 130, 4),
    )
    _rpc_response(
        adapter,
        reducer=reducer,
        request_id=long_intent.request_id,
        result=_rest_option_book(
            "BTC-1JAN00-102000-C",
            bid_price="0.00100",
            ask_price="0.00101",
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
    ("variant", "expected_reasons"),
    (
        (
            "session",
            (
                "COMPONENT_PAIR_SESSION_EPOCH_MISMATCH",
                "PLATFORM_CURRENTNESS_UNKNOWN",
            ),
        ),
        ("continuity", ("COMPONENT_PAIR_CONTINUITY_EPOCH_MISMATCH",)),
    ),
)
def test_component_admission_pair_epoch_mismatch_is_exact_unknown_without_case(
    tmp_path: Path,
    variant: str,
    expected_reasons: tuple[str, ...],
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    short_intent = next(
        value for value in intents if value.params["instrument_name"] == "BTC-1JAN00-101000-C"
    )
    long_intent = next(
        value for value in intents if value.params["instrument_name"] == "BTC-1JAN00-102000-C"
    )
    short_sent = FactBoundary(1, 2, 120, 2)
    long_sent = FactBoundary(1, 3, 121, 3)
    adapter.on_request_sent(request_id=short_intent.request_id, boundary=short_sent)
    adapter.on_request_sent(request_id=long_intent.request_id, boundary=long_sent)
    _rpc_response(
        adapter,
        reducer=reducer,
        request_id=short_intent.request_id,
        result=_rest_option_book(
            "BTC-1JAN00-101000-C",
            bid_price="0.00300",
            ask_price="0.00301",
            change_id=11,
        ),
        sent_boundary=short_sent,
        boundary=FactBoundary(1, 4, 130, 4),
    )
    if variant == "continuity":
        reducer._global_continuity_epoch += 1
    _rpc_response(
        adapter,
        reducer=reducer,
        request_id=long_intent.request_id,
        result=_rest_option_book(
            "BTC-1JAN00-102000-C",
            bid_price="0.00100",
            ask_price="0.00101",
            change_id=11,
        ),
        sent_boundary=long_sent,
        boundary=FactBoundary(2 if variant == "session" else 1, 5, 150, 5),
    )

    assert not _object_payloads(owner, "SHADOW_ENTRY")
    assert _terminal_outcomes(owner) == ["UNKNOWN_CONSUMED"]
    terminal = _object_payloads(owner, "ADMISSION_ATTEMPT_TERMINAL")[-1]
    assert terminal["terminal_unknown_reasons"] == list(expected_reasons)


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

    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="0.00310",
        short_ask="0.00311",
        long_bid="0.00100",
        long_ask="0.00101",
    )

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
    assert economics["width_usd_per_btc"] == "1000"
    underwriting = opened["underwriting"]
    selected = opened["selected_underwriting_decision"]
    assert isinstance(underwriting, Mapping)
    assert isinstance(selected, Mapping)
    assert underwriting["predicate_margin_vector"] == selected["refreshed_predicate_margin_vector"]
    assert underwriting["predicate_margin_vector"] != selected["selected_predicate_margin_vector"]
    entry_payload = entry["payload"]
    assert isinstance(entry_payload, Mapping)
    assert (
        underwriting["protective_leg_selection_rule_identity"]
        == entry_payload["entry_underwriting_protective_leg_selection_rule_identity"]
    )
    assert underwriting["candidate_protective_leg_count"] == 1


def test_no_active_combo_is_only_a_diagnostic_and_does_not_block_shadow_entry(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    reducer.combos.clear()
    reducer.combo_books.clear()
    reducer.accepted_book_receipts.pop("BTC-COMBO")
    reducer.combo_catalog.complete = True
    reducer.combo_catalog.source_complete = True

    intents = _settled_transaction(
        adapter,
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
        reducer=reducer,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="0.00300",
        short_ask="0.00301",
        long_bid="0.00100",
        long_ask="0.00101",
    )
    (entry,) = _object_payloads(owner, "SHADOW_ENTRY")
    assert entry["atomic_state_diagnostic"] == "NO_ACTIVE_COMBO"
    assert entry["execution_model"] == "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL"


def test_selected_candidate_insufficient_long_depth_is_exact_current_unknown(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )

    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="0.00300",
        short_ask="0.00301",
        long_bid="0.00100",
        long_ask="0.00101",
        long_amount="0.05",
    )

    assert not _object_payloads(owner, "SHADOW_ENTRY")
    assert _terminal_outcomes(owner) == ["UNKNOWN_CONSUMED"]
    (terminal,) = _object_payloads(owner, "ADMISSION_ATTEMPT_TERMINAL")
    assert terminal["terminal_unknown_reasons"] == ["COMPONENT_PAIR_LONG_FULL_QUANTITY_NOT_COVERED"]
    assert terminal["selected_underwriting_decision_identity"]
    assert terminal["activation_batch_identity"]
    assert all(
        value["object_kind"] != "CANDIDATE_INVALIDATION" for value in owner.state_store.objects
    )
    (research_row,) = workbench_module._decision_control_rows(
        workbench_module._objects_by_kind(owner.state_store.objects)
    )
    assert research_row["refresh_terminal_outcome"] == "UNKNOWN_CONSUMED"
    assert research_row["refresh_unknown_reasons"] == terminal["terminal_unknown_reasons"]
    assert research_row["case_state"] == "NOT_OPENED"
    assert research_row["enrollment_identity"] is None
    assert owner.state_store.retained_state_counts["active_or_latest_terminal_cases"] == 0


def test_one_component_admission_rpc_failure_retires_the_pair_without_case(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    intents = _settled_transaction(
        adapter,
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
    close_intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=6,
            monotonic_ms=160,
            cause=CausalCause.TIME_BOUNDARY,
        ),
    )
    assert len(close_intents) == 2
    assert {str(intent.params["instrument_name"]) for intent in close_intents} == {
        "BTC-1JAN00-101000-C",
        "BTC-1JAN00-102000-C",
    }

    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=close_intents,
        first_causal_seq=7,
        change_id=12,
        short_bid="0.00249",
        short_ask="0.00250",
        long_bid="0.00149",
        long_ask="0.00150",
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


def test_selected_abstain_case_reuses_strictly_future_position_outcome_without_canonical_counts(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    short_book = ContinuousOrderBook("BTC-1JAN00-101000-C")
    short_book.apply(
        {
            "type": "snapshot",
            "instrument_name": "BTC-1JAN00-101000-C",
            "change_id": 10,
            "timestamp": 1_000_010,
            "bids": [["new", "0.00150", "0.1"]],
            "asks": [["new", "0.00151", "0.1"]],
        },
        110,
    )
    reducer.option_books["BTC-1JAN00-101000-C"] = short_book
    cases = tmp_path / "cases"
    cases.mkdir()
    case_store = ShadowCaseStore(
        cases,
        bindings=owner.bindings,
        policies=owner.policies,
    )
    owner.state_store.observer = case_store

    enrollment_intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=1,
            monotonic_ms=110,
            cause=CausalCause.OPTION_BOOK_FACT,
        ),
    )
    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=enrollment_intents,
        first_causal_seq=2,
        change_id=11,
        short_bid="0.00150",
        short_ask="0.00151",
        long_bid="0.00100",
        long_ask="0.00101",
    )
    control_open = next(
        value
        for value in owner.state_store.objects
        if value["object_kind"] == "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN"
    )
    control_identity = str(control_open["object_identity"])
    case_id = case_store.case_id_for_enrollment(control_identity)
    assert case_id is not None

    _set_platform_usable(reducer, False)
    close_intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=6,
            monotonic_ms=160,
            cause=CausalCause.TIME_BOUNDARY,
        ),
    )
    _settle_component_pair(
        adapter=adapter,
        reducer=reducer,
        intents=close_intents,
        first_causal_seq=7,
        change_id=12,
        short_bid="0.00149",
        short_ask="0.00150",
        long_bid="0.00099",
        long_ask="0.00100",
    )

    result = case_store.read_case(case_id)
    assert result.status.value == "COMPLETE"
    assert result.opened["enrollment_kind"] == "SELECTED_UNDERWRITING_DECISION_CONTROL"
    assert result.outcome is not None
    assert result.outcome["terminal_state"] == "MATURE_KNOWN"
    assert not any(
        value["object_kind"] in {"CANDIDATE_ACTIVATION", "SHADOW_ENTRY", "SHADOW_OUTCOME"}
        for value in owner.state_store.objects
    )
    assert any(
        value["object_kind"] == "SELECTED_UNDERWRITING_DECISION_CONTROL_OUTCOME"
        for value in owner.state_store.objects
    )


def test_component_close_pair_over_skew_is_workbench_visible_business_unknown(
    tmp_path: Path,
) -> None:
    reducer, adapter, owner = _shadow_system(tmp_path)
    cases = tmp_path / "cases"
    cases.mkdir()
    case_store = ShadowCaseStore(
        cases,
        bindings=owner.bindings,
        policies=owner.policies,
    )
    owner.state_store.observer = _HistoryCaseStoreObserver(
        _HISTORY_BY_OWNER[id(owner)],
        case_store,
    )
    _admit_component_shadow(reducer, adapter)
    _set_platform_usable(reducer, False)
    close_intents = _settled_transaction(
        adapter,
        reducer=reducer,
        commit=_commit(
            causal_seq=6,
            monotonic_ms=160,
            cause=CausalCause.TIME_BOUNDARY,
        ),
    )
    short_intent = next(
        value for value in close_intents if value.params["instrument_name"] == "BTC-1JAN00-101000-C"
    )
    long_intent = next(
        value for value in close_intents if value.params["instrument_name"] == "BTC-1JAN00-102000-C"
    )
    short_sent = FactBoundary(1, 7, 170, 7)
    long_sent = FactBoundary(1, 8, 171, 8)
    adapter.on_request_sent(request_id=short_intent.request_id, boundary=short_sent)
    adapter.on_request_sent(request_id=long_intent.request_id, boundary=long_sent)
    _rpc_response(
        adapter,
        reducer=reducer,
        request_id=short_intent.request_id,
        result=_rest_option_book(
            "BTC-1JAN00-101000-C",
            bid_price="0.00249",
            ask_price="0.00250",
            change_id=12,
            timestamp_ms=1_000_000,
        ),
        sent_boundary=short_sent,
        boundary=FactBoundary(1, 9, 180, 9),
    )
    _rpc_response(
        adapter,
        reducer=reducer,
        request_id=long_intent.request_id,
        result=_rest_option_book(
            "BTC-1JAN00-102000-C",
            bid_price="0.00149",
            ask_price="0.00150",
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
    close_intents = _settled_transaction(
        adapter,
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
    _rpc_response(
        adapter,
        reducer=reducer,
        request_id=first.request_id,
        result=_rest_option_book(
            first_name,
            bid_price="0.00249",
            ask_price="0.00250",
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
        _settled_transaction(
            adapter,
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


def test_position_projection_only_consumes_relevant_high_frequency_market_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reducer, adapter, _owner = _shadow_system(tmp_path)
    _admit_component_shadow(reducer, adapter)
    projected_anchor_ids: list[str] = []
    original = adapter._project_position

    def count_projection(**kwargs: Any) -> Any:
        projected_anchor_ids.append(kwargs["anchor"].anchor_identity)
        return original(**kwargs)

    monkeypatch.setattr(adapter, "_project_position", count_projection)

    for causal_seq, cause, failure_domain, scopes in (
        (
            6,
            CausalCause.OPTION_BOOK_CHANGED,
            FailureScope.OPTION,
            ("OPTION:BTC-1JAN00-99000-C",),
        ),
        (
            7,
            CausalCause.TICKER_APPLIED,
            FailureScope.OPTION,
            ("OPTION:BTC-1JAN00-102000-C",),
        ),
        (
            8,
            CausalCause.COMBO_BOOK_CHANGED,
            FailureScope.COMBO_LAYER,
            ("OPTION:BTC-1JAN00-101000-C", "OPTION:BTC-1JAN00-102000-C"),
        ),
    ):
        _settled_transaction(
            adapter,
            reducer=reducer,
            commit=CausalCommit(
                boundary=FactBoundary(1, causal_seq, 100 + causal_seq * 10, causal_seq),
                cause=cause,
                failure_domain=failure_domain,
                affected_scopes=scopes,
            ),
        )
    assert projected_anchor_ids == []

    for causal_seq, cause, instrument_name in (
        (9, CausalCause.OPTION_BOOK_FACT, "BTC-1JAN00-101000-C"),
        (10, CausalCause.OPTION_BOOK_CHANGED, "BTC-1JAN00-102000-C"),
        (11, CausalCause.TICKER_APPLIED, "BTC-1JAN00-101000-C"),
    ):
        _settled_transaction(
            adapter,
            reducer=reducer,
            commit=CausalCommit(
                boundary=FactBoundary(1, causal_seq, 100 + causal_seq * 10, causal_seq),
                cause=cause,
                failure_domain=FailureScope.OPTION,
                affected_scopes=(f"OPTION:{instrument_name}",),
            ),
        )
    assert len(projected_anchor_ids) == 3
    assert set(projected_anchor_ids) == set(adapter._anchors)
