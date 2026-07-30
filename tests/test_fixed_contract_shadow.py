from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from conftest import PolicyFactory
from market_monitor import (
    ContinuityGap,
    ContinuousOrderBook,
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
from radar_runtime.fixed_contract_shadow import FixedContractShadowRuntimeAdapter
from radar_runtime.runtime import (
    AcceptedBookReceipt,
    AcceptedIndexReceipt,
    CausalCause,
    CausalCommit,
    FactBoundary,
    FailureScope,
    RadarReducer,
    RpcState,
)
from short_vol_radar.detector import EpisodeTracker, TrackerState
from short_vol_radar.evidence import EvidenceWriter
from short_vol_radar.policy import load_policy_bytes
from short_vol_radar.radar import TickerState
from short_vol_underwriting import (
    DownstreamEvidenceWriter,
    FixedContractShadowOwner,
    RuntimeBindings,
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
    tracker.episode_id = "sha256:" + "e" * 64
    tracker.activation_band_id = policies.radar.tte_bands[0].band_id
    tracker.activation_causal_seq = 1
    reducer.trackers["BTC-SHORT"] = tracker
    reducer.option_books = {
        "BTC-SHORT": ContinuousOrderBook("BTC-SHORT"),
        "BTC-LONG": ContinuousOrderBook("BTC-LONG"),
    }
    return reducer, adapter, owner


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
