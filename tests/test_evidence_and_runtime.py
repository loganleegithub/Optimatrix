from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
import radar_runtime.runtime as runtime_module
import short_vol_radar.evidence as evidence_module
from conftest import PolicyFactory
from market_monitor import (
    PriceLevel,
    TimeInterval,
)
from radar_runtime.deribit_public import (
    ConnectionControlReason,
    DeribitPublicClient,
    InboundEnvelope,
    PublicSessionError,
    SendControlEvent,
)
from radar_runtime.identity import (
    StartupGuardError,
    validate_clean_git_outputs,
)
from radar_runtime.runtime import (
    CausalCause,
    CausalCommit,
    CausalEffect,
    CoverageTracker,
    FactBoundary,
    FailureScope,
    LiveRadarRuntime,
    ScopeCounts,
)
from short_vol_radar.atomic import (
    AtomicMatch,
    AtomicQuote,
    ComboOrderDirection,
    PublicAtomicQuoteState,
)
from short_vol_radar.baseline import BaselineResult
from short_vol_radar.black import DecimalInterval, TotalVolatilityInterval
from short_vol_radar.detector import (
    DetectorCoverage,
    EpisodeEndReason,
)
from short_vol_radar.evidence import (
    AnomalyEvidence,
    AtomicEvidence,
    CoverageBlockingGroup,
    CoverageSegment,
    CoverageState,
    EvidenceError,
    EvidenceWriter,
    project_anomaly_event,
    project_atomic_event,
    project_run_summary,
    ratio_or_none,
)
from short_vol_radar.policy import OptionRule, load_policy_bytes


def anomaly_evidence() -> AnomalyEvidence:
    rule = OptionRule(
        Decimal("0.05"),
        Decimal("0.6"),
        Decimal("1.2"),
        Decimal("0.9"),
        1,
        1,
        0,
    )
    return AnomalyEvidence(
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
        episode_identity="episode",
        causal_seq=10,
        instrument_name="SHORT",
        expiration_timestamp_ms=10_000,
        option_type="call",
        activation_band_id="band",
        aggregate_coverage=DetectorCoverage.COMPLETE,
        target_base_quantity_btc=Decimal("0.1"),
        rule=rule,
        baseline=BaselineResult(
            ((5, Decimal("0.0001")),),
            Decimal("0.0001"),
            Decimal("0.2"),
            Decimal("0.001"),
            Decimal("0.002"),
        ),
        trusted_time=TimeInterval(1_000, 1_001),
        remaining_life_years=DecimalInterval(Decimal("0.01"), Decimal("0.011")),
        consumed_bid_levels=(PriceLevel(Decimal("1"), Decimal("0.1")),),
        forward_usdc=Decimal(100),
        strike_usdc=Decimal(110),
        executable_sell_price_usdc=Decimal(1),
        total_volatility=TotalVolatilityInterval(Decimal("0.1"), Decimal("0.1001")),
        executable_bid_iv=DecimalInterval(Decimal("0.5"), Decimal("0.51")),
        delta=DecimalInterval(Decimal("0.2"), Decimal("0.21")),
        implied_total_variance=DecimalInterval(Decimal("0.01"), Decimal("0.0101")),
        richness=DecimalInterval(Decimal("2.5"), Decimal("2.55")),
    )


def atomic_evidence() -> AtomicEvidence:
    quote = AtomicQuote(
        match=AtomicMatch("COMBO", "LONG", Decimal("0.1"), ComboOrderDirection.BUY),
        consumed_levels=(PriceLevel(Decimal("-5"), Decimal("0.1")),),
        required_side_vwap_usdc_per_btc=Decimal("-5"),
        gross_entry_credit_usdc=Decimal("0.5"),
    )
    return AtomicEvidence(
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
        episode_identity="episode",
        anomaly_activation_seq=10,
        detector_causal_seq=11,
        quote_causal_seq=11,
        short_instrument_name="SHORT",
        combo_legs=(("SHORT", Decimal(-1)), ("LONG", Decimal(1))),
        quote=quote,
        target_base_quantity_btc=Decimal("0.1"),
        source_timestamp_ms=2_000,
    )


def summary_object(
    *,
    runtime_identity: str = "runtime",
    segments: tuple[CoverageSegment, ...] = (
        CoverageSegment(
            0,
            10,
            CoverageState.UNKNOWN,
            reason="RUNTIME_START",
            blocking_reason="RUNTIME_START_PENDING",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.KNOWN_COMPLETE,
            reason="TICKER_APPLIED",
            blocking_reason="NONE",
            affected_scopes=("OPTION:SHORT",),
            global_continuity_epoch=1,
        ),
    ),
) -> dict[str, object]:
    return project_run_summary(
        code_identity="a" * 40,
        runtime_identity=runtime_identity,
        policy_identity="sha256:" + "b" * 64,
        coverage_segments=segments,
        band_suspended_duration_ms=0,
        counts_by_scope=[],
        detector_unknown_transition_count_by_reason={"WARMUP": 1},
        anomaly_end_count_by_reason={EpisodeEndReason.CLEAR: 0},
        known_active_duration_ms_sum_by_end_reason={EpisodeEndReason.CLEAR: 0},
        public_atomic_quote_state_transition_count={},
    )


def current_summary_object(
    *,
    segments: tuple[CoverageSegment, ...] = (
        CoverageSegment(
            0,
            10,
            CoverageState.UNKNOWN,
            reason="RUNTIME_START",
            blocking_reason="RUNTIME_START_PENDING",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.KNOWN_COMPLETE,
            reason="TICKER_APPLIED",
            blocking_reason="NONE",
            affected_scopes=("OPTION:SHORT",),
            global_continuity_epoch=1,
        ),
    ),
) -> dict[str, object]:
    return project_run_summary(
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
        coverage_segments=segments,
        band_suspended_duration_ms=0,
        counts_by_scope=[],
        detector_unknown_transition_count_by_reason={"WARMUP": 1},
        anomaly_end_count_by_reason={EpisodeEndReason.CLEAR: 0},
        known_active_duration_ms_sum_by_end_reason={EpisodeEndReason.CLEAR: 0},
        public_atomic_quote_state_transition_count={},
    )


def test_minimal_events_are_strict_unit_bearing_and_carry_non_claims() -> None:
    anomaly = project_anomaly_event(anomaly_evidence())
    atomic = project_atomic_event(atomic_evidence())
    assert anomaly["object_kind"] == "SHORT_VOL_ANOMALY_EVENT"
    assert anomaly["target_base_quantity_btc"] == "0.1"
    anomaly_non_claims = anomaly["non_claims"]
    assert isinstance(anomaly_non_claims, list)
    assert "NOT_VALIDATED_FORECAST" in anomaly_non_claims
    assert atomic["object_kind"] == "PUBLIC_ATOMIC_QUOTE_EVENT"
    assert atomic["gross_entry_credit_usdc"] == "0.5"
    atomic_non_claims = atomic["non_claims"]
    assert isinstance(atomic_non_claims, list)
    assert "PUBLIC_QUOTE_NOT_FILL" in atomic_non_claims
    assert "full_option_chain" not in json.dumps((anomaly, atomic))


def test_evidence_writer_deduplicates_business_objects(
    tmp_path: Path,
) -> None:
    anomaly = project_anomaly_event(anomaly_evidence())
    atomic = project_atomic_event(atomic_evidence())
    writer = EvidenceWriter(
        tmp_path,
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
    )
    assert writer.write_anomaly(anomaly) is not None
    assert writer.write_anomaly(anomaly) is None
    assert writer.write_atomic(atomic) is not None
    assert writer.write_atomic(atomic) is None
    scope = ScopeCounts("sha256:" + "b" * 64, "call", "band")
    scope.applicable_instrument_count = 1
    scope.distinct_anomaly_episode_count = 1
    scope.anomaly_activation_transition_count = 1
    scope.anomaly_end_count_by_reason[EpisodeEndReason.CENSORED_AT_STOP.value] = 1
    scope.known_active_duration_ms_sum_by_end_reason[EpisodeEndReason.CENSORED_AT_STOP.value] = 0
    scope.public_atomic_quote_state_transition_count[
        PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value
    ] = 1
    summary = summary_object()
    summary["counts_by_scope"] = [scope.as_object()]
    summary["anomaly_end_count_by_reason"] = {
        reason.value: int(reason is EpisodeEndReason.CENSORED_AT_STOP)
        for reason in EpisodeEndReason
    }
    summary["known_active_duration_ms_sum_by_end_reason"] = {
        reason.value: 0 for reason in EpisodeEndReason
    }
    summary["public_atomic_quote_state_transition_count"] = {
        PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value: 1
    }
    writer.write_summary(summary)
    assert len(tuple(tmp_path.glob("*.json"))) == 3


def test_evidence_writer_uses_short_temporary_name_for_long_atomic_identity(
    tmp_path: Path,
) -> None:
    runtime_identity = "sha256:" + "0" * 64
    policy_identity = "sha256:" + "1" * 64
    short_instrument_name = "BTC_USDC-2AUG26-63000-C"
    combo_instrument_name = "BTC_USDC-CS-2AUG26-63000_64500"
    episode_identity = f"{runtime_identity}:{policy_identity}:{short_instrument_name}:416138"
    source = atomic_evidence()
    event = project_atomic_event(
        replace(
            source,
            runtime_identity=runtime_identity,
            policy_identity=policy_identity,
            episode_identity=episode_identity,
            short_instrument_name=short_instrument_name,
            combo_legs=(
                (short_instrument_name, Decimal(-1)),
                ("BTC_USDC-2AUG26-64500-C", Decimal(1)),
            ),
            quote=replace(
                source.quote,
                match=replace(
                    source.quote.match,
                    combo_instrument_name=combo_instrument_name,
                ),
            ),
        )
    )
    writer = EvidenceWriter(
        tmp_path,
        code_identity=source.code_identity,
        runtime_identity=runtime_identity,
        policy_identity=policy_identity,
    )

    path = writer.write_atomic(event)

    assert path is not None
    assert len(path.name.encode()) == 230
    assert (
        path.read_text(encoding="utf-8")
        == json.dumps(
            event,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    assert not tuple(tmp_path.glob(".*.tmp"))


def test_evidence_writer_rejects_conflicting_duplicate_identity(tmp_path: Path) -> None:
    event = project_anomaly_event(anomaly_evidence())
    writer = EvidenceWriter(
        tmp_path,
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
    )
    assert writer.write_anomaly(event) is not None
    conflicting = dict(event)
    conflicting["causal_seq"] = 11

    with pytest.raises(EvidenceError, match="conflicting"):
        writer.write_anomaly(conflicting)


def test_coverage_segments_reject_overlap_gap_negative_and_mismatched_totals() -> None:
    with pytest.raises(EvidenceError, match="overlap or contain a gap"):
        summary_object(
            segments=(
                CoverageSegment(
                    0,
                    10,
                    CoverageState.UNKNOWN,
                    reason="RUNTIME_START",
                    blocking_reason="RUNTIME_START_PENDING",
                    affected_scopes=("GLOBAL",),
                    global_continuity_epoch=1,
                ),
                CoverageSegment(
                    9,
                    20,
                    CoverageState.KNOWN_COMPLETE,
                    reason="TICKER_APPLIED",
                    blocking_reason="NONE",
                    affected_scopes=("OPTION:SHORT",),
                    global_continuity_epoch=1,
                ),
            )
        )
    with pytest.raises(EvidenceError, match="overlap or contain a gap"):
        summary_object(
            segments=(
                CoverageSegment(
                    0,
                    10,
                    CoverageState.UNKNOWN,
                    reason="RUNTIME_START",
                    blocking_reason="RUNTIME_START_PENDING",
                    affected_scopes=("GLOBAL",),
                    global_continuity_epoch=1,
                ),
                CoverageSegment(
                    11,
                    20,
                    CoverageState.KNOWN_COMPLETE,
                    reason="TICKER_APPLIED",
                    blocking_reason="NONE",
                    affected_scopes=("OPTION:SHORT",),
                    global_continuity_epoch=1,
                ),
            )
        )


def test_coverage_ledger_splits_same_state_on_global_continuity_restart() -> None:
    tracker = CoverageTracker(
        0,
        initial_commit=CausalCommit(
            boundary=FactBoundary(1, 0, 0, 0),
            cause=CausalCause.RUNTIME_START,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        ),
    )
    tracker.transition(
        CoverageState.UNKNOWN,
        commit=CausalCommit(
            boundary=FactBoundary(1, 1, 10, 1),
            cause=CausalCause.INDEX_CONTINUITY_GAP,
            failure_domain=FailureScope.CLOCK_INDEX,
            affected_scopes=("GLOBAL",),
        ),
        blocking_reason="INDEX_CONTINUITY_GAP",
        global_continuity_epoch=2,
        force=True,
    )

    assert tracker.close(20) == (
        CoverageSegment(
            0,
            10,
            CoverageState.UNKNOWN,
            reason="RUNTIME_START",
            blocking_reason="RUNTIME_START_PENDING",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.UNKNOWN,
            reason="INDEX_CONTINUITY_GAP",
            blocking_reason="INDEX_CONTINUITY_GAP",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=2,
        ),
    )


def test_coverage_ledger_preserves_trigger_cause_and_true_blocking_reason() -> None:
    tracker = CoverageTracker(
        0,
        initial_commit=CausalCommit(
            boundary=FactBoundary(1, 0, 0, 0),
            cause=CausalCause.RUNTIME_START,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        ),
    )
    commit = CausalCommit(
        boundary=FactBoundary(1, 1, 10, 1),
        cause=CausalCause.OPTION_BOOK_FACT,
        failure_domain=FailureScope.OPTION,
        affected_scopes=("OPTION:SHORT",),
    )
    effect = CausalEffect(
        cause=CausalCause.TICKER_SOURCE_STALE,
        failure_domain=FailureScope.OPTION,
        affected_scopes=("OPTION:SHORT",),
    )
    tracker.transition(
        CoverageState.UNKNOWN,
        commit=commit,
        causal_effect=effect,
        blocking_reason="TICKER_SOURCE_STALE",
        global_continuity_epoch=1,
    )

    summary = current_summary_object(segments=tracker.close(20))
    coverage_segments = summary["coverage_segments"]
    assert isinstance(coverage_segments, list)
    blocked = coverage_segments[1]
    assert blocked == {
        "start_monotonic_ms": 10,
        "end_monotonic_ms": 20,
        "state": "UNKNOWN",
        "trigger_cause": "OPTION_BOOK_FACT",
        "blocking_reason": "TICKER_SOURCE_STALE",
        "affected_scopes": ["OPTION:SHORT"],
        "blocking_groups": [
            {
                "blocking_reason": "TICKER_SOURCE_STALE",
                "affected_scopes": ["OPTION:SHORT"],
            }
        ],
        "global_continuity_epoch": 1,
    }


def test_coverage_ledger_splits_when_reason_to_scope_assignment_changes() -> None:
    tracker = CoverageTracker(
        0,
        initial_commit=CausalCommit(
            boundary=FactBoundary(1, 0, 0, 0),
            cause=CausalCause.RUNTIME_START,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        ),
    )
    scopes = ("OPTION:A", "OPTION:B")
    first_groups = (
        CoverageBlockingGroup("OPTION_BOOK_UNAVAILABLE", ("OPTION:A",)),
        CoverageBlockingGroup("TICKER_SOURCE_STALE", ("OPTION:B",)),
    )
    second_groups = (
        CoverageBlockingGroup("OPTION_BOOK_UNAVAILABLE", ("OPTION:B",)),
        CoverageBlockingGroup("TICKER_SOURCE_STALE", ("OPTION:A",)),
    )
    tracker.transition(
        CoverageState.UNKNOWN,
        commit=CausalCommit(
            boundary=FactBoundary(1, 1, 10, 1),
            cause=CausalCause.OPTION_BOOK_FACT,
            failure_domain=FailureScope.OPTION,
            affected_scopes=scopes,
        ),
        affected_scopes=scopes,
        blocking_reason="CURRENT_SCOPE_INCOMPLETE",
        blocking_groups=first_groups,
        global_continuity_epoch=1,
    )
    tracker.transition(
        CoverageState.UNKNOWN,
        commit=CausalCommit(
            boundary=FactBoundary(1, 2, 15, 2),
            cause=CausalCause.TIME_BOUNDARY,
            failure_domain=FailureScope.OPTION,
            affected_scopes=scopes,
        ),
        affected_scopes=scopes,
        blocking_reason="CURRENT_SCOPE_INCOMPLETE",
        blocking_groups=second_groups,
        global_continuity_epoch=1,
    )

    summary = current_summary_object(segments=tracker.close(20))
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    assert [segment["start_monotonic_ms"] for segment in segments] == [0, 10, 15]
    assert segments[1]["blocking_groups"] != segments[2]["blocking_groups"]


@pytest.mark.parametrize(
    ("blocking_reason", "affected_scopes", "message"),
    (
        (
            "CURRENT_SCOPE_INCOMPLETE",
            ("OPTION:A",),
            "blocking_reason must summarize",
        ),
        (
            "OPTION_BOOK_UNAVAILABLE",
            ("OPTION:B",),
            "affected_scopes must summarize",
        ),
    ),
)
def test_coverage_tracker_rejects_inconsistent_group_summaries_immediately(
    blocking_reason: str,
    affected_scopes: tuple[str, ...],
    message: str,
) -> None:
    tracker = CoverageTracker(
        0,
        initial_commit=CausalCommit(
            boundary=FactBoundary(1, 0, 0, 0),
            cause=CausalCause.RUNTIME_START,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        ),
    )

    with pytest.raises(ValueError, match=message):
        tracker.transition(
            CoverageState.UNKNOWN,
            commit=CausalCommit(
                boundary=FactBoundary(1, 1, 10, 1),
                cause=CausalCause.OPTION_BOOK_FACT,
                failure_domain=FailureScope.OPTION,
                affected_scopes=affected_scopes,
            ),
            affected_scopes=affected_scopes,
            blocking_reason=blocking_reason,
            blocking_groups=(CoverageBlockingGroup("OPTION_BOOK_UNAVAILABLE", ("OPTION:A",)),),
            global_continuity_epoch=1,
        )


def test_zero_and_unknown_denominators_serialize_as_null_semantics() -> None:
    assert ratio_or_none(0, 0) is None
    assert ratio_or_none(0, None) is None
    assert ratio_or_none(1, 2) == Decimal("0.5")
    rates = ScopeCounts("policy", "call", "band").as_object()
    assert rates["known_full_formula_rate_given_known_per_instrument"] is None
    assert rates["complete_aggregate_with_full_formula_rate_given_complete_aggregate"] is None


def test_run_summary_contains_business_evidence_only() -> None:
    summary = summary_object()

    assert "operational_diagnostics" not in summary


def test_git_startup_guard_requires_one_clean_commit() -> None:
    assert validate_clean_git_outputs(head_output="a" * 40 + "\n", status_output="") == "a" * 40
    with pytest.raises(StartupGuardError, match="clean"):
        validate_clean_git_outputs(head_output="a" * 40, status_output=" M file.py\n")
    with pytest.raises(StartupGuardError, match="commit"):
        validate_clean_git_outputs(head_output="short", status_output="")


def test_evidence_publish_failure_leaves_no_partial_final_or_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = anomaly_evidence()
    writer = EvidenceWriter(
        tmp_path,
        code_identity=evidence.code_identity,
        runtime_identity=evidence.runtime_identity,
        policy_identity=evidence.policy_identity,
    )

    def fail_publish(_source: object, _target: object) -> None:
        raise OSError("injected atomic publish failure")

    monkeypatch.setattr(os, "link", fail_publish)
    with pytest.raises(EvidenceError, match="publish"):
        writer.write_anomaly(project_anomaly_event(evidence))

    assert list(tmp_path.iterdir()) == []


def test_continuous_inbound_flow_cannot_starve_absolute_time_boundaries(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    policy = load_policy_bytes(exact, digest)
    runtime = LiveRadarRuntime(
        policy=policy,
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )
    stop_event = asyncio.Event()
    summary_path = tmp_path / "summary.json"
    now_ms = 0
    next_seq = 0
    reduced: list[int] = []
    timer_boundaries: list[int] = []

    class ContinuousClient:
        session_epoch = 1
        queue_high_water_frames = 0
        overflow_count = 0
        received_frame_count = 0

        async def next_envelope(
            self,
            timeout_seconds: float | None = None,
        ) -> InboundEnvelope:
            del timeout_seconds
            nonlocal now_ms, next_seq
            next_seq += 1
            now_ms = next_seq * 400
            if next_seq == 3:
                stop_event.set()
            return InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "method": "heartbeat",
                    "params": {"type": "heartbeat"},
                },
                session_epoch=1,
                ingress_seq=next_seq,
                received_monotonic_ms=now_ms,
            )

        async def send_request(self, **_kwargs: object) -> None:
            raise AssertionError("patched reducer must not emit commands")

        def enqueue_send_control(self, event: SendControlEvent) -> None:
            raise AssertionError(f"patched reducer unexpectedly emitted {event}")

    def reduce_frame(
        frame: InboundEnvelope,
        *,
        processed_monotonic_ms: int,
    ) -> tuple[object, ...]:
        assert processed_monotonic_ms == now_ms
        reduced.append(frame.ingress_seq)
        return ()

    def advance_time(boundary_ms: int) -> tuple[object, ...]:
        timer_boundaries.append(boundary_ms)
        return ()

    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: now_ms)
    monkeypatch.setattr(runtime.reducer, "begin_session", lambda **_kwargs: ())
    monkeypatch.setattr(runtime.reducer, "reduce", reduce_frame)
    monkeypatch.setattr(runtime.reducer, "advance_time", advance_time)
    monkeypatch.setattr(runtime.reducer, "clean_stop", lambda _stop_ms: summary_path)

    assert asyncio.run(runtime.run(ContinuousClient(), stop_event)) == summary_path
    assert reduced == [1, 2, 3]
    assert timer_boundaries == [1_000]


@pytest.mark.parametrize("outcome", ("SUCCESS", "CANCELLED", "ERROR"))
def test_sender_reports_transport_completion_without_mutating_reducer(
    outcome: str,
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )
    command = runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)[0]
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: 1_100)
    started = asyncio.Event()
    release = asyncio.Event()

    class ControlledClient:
        def __init__(self) -> None:
            self.controls: list[object] = []

        async def send_request(self, **_kwargs: object) -> None:
            started.set()
            await release.wait()
            if outcome == "ERROR":
                raise RuntimeError("send failed")

        def enqueue_send_control(self, event: object) -> None:
            self.controls.append(event)

    client = ControlledClient()

    async def scenario() -> tuple[object, ...]:
        task = asyncio.create_task(runtime._send_one(client, command))  # type: ignore[arg-type]
        await started.wait()
        assert (
            runtime.reducer._rpc_lifecycles[command.request_id].state
            is runtime_module.RpcState.SCHEDULED
        )
        if outcome == "CANCELLED":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            await task
        return tuple(client.controls)

    controls = asyncio.run(scenario())

    assert len(controls) == 1
    event = controls[0]
    assert isinstance(event, SendControlEvent)
    assert event.request_id == command.request_id
    assert event.kind.value == ("SEND_COMPLETED" if outcome == "SUCCESS" else "SEND_FAILED")
    assert (None if event.failure is None else event.failure.value) == (
        None if outcome == "SUCCESS" else outcome
    )
    assert (
        runtime.reducer._rpc_lifecycles[command.request_id].state
        is runtime_module.RpcState.SCHEDULED
    )


def test_transport_metrics_finalize_before_sender_exception_propagates(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )

    class FailingClient(DeribitPublicClient):
        async def send_request(self, **_kwargs: object) -> None:
            self.queue_high_water_frames = 7
            raise RuntimeError("sender exploded")

    client = FailingClient(session_epoch=1, rpc_deadline_ms=30_000)
    with pytest.raises(PublicSessionError, match="SET_HEARTBEAT"):
        asyncio.run(runtime.run(client, asyncio.Event()))


def test_send_failure_is_reduced_before_session_failure_propagates(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )

    class SendFailureClient(DeribitPublicClient):
        async def send_request(self, **_kwargs: object) -> None:
            raise OSError("injected transport send failure")

    client = SendFailureClient(session_epoch=1, rpc_deadline_ms=30_000)

    with pytest.raises(PublicSessionError, match="SET_HEARTBEAT"):
        asyncio.run(runtime.run(client, asyncio.Event()))

    lifecycle = next(iter(runtime.reducer._rpc_lifecycles.values()))
    assert lifecycle.state is runtime_module.RpcState.ERROR


def test_failure_barrier_drains_every_already_accepted_application_event(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )
    blocked = asyncio.Event()

    class BufferedFailureClient(DeribitPublicClient):
        async def send_request(self, **_kwargs: object) -> None:
            await blocked.wait()

    client = BufferedFailureClient(session_epoch=1, rpc_deadline_ms=30_000)
    first_received_ms = runtime_module._monotonic_ms()
    client._enqueue_wire_message(
        {"jsonrpc": "2.0", "id": 999_999, "result": "orphan"},
        received_monotonic_ms=first_received_ms,
    )
    client._enqueue_connection_error(
        PublicSessionError("injected connection failure"),
        reason=ConnectionControlReason.TRANSPORT_READ_FAILURE,
    )
    client._enqueue_wire_message(
        {
            "jsonrpc": "2.0",
            "method": "heartbeat",
            "params": {"type": "heartbeat"},
        },
        received_monotonic_ms=runtime_module._monotonic_ms(),
    )

    with pytest.raises(PublicSessionError, match="connection"):
        asyncio.run(runtime.run(client, asyncio.Event()))


def test_blocked_send_clean_stop_drains_cancellation_then_censors_scheduled(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )
    original_begin_session = runtime.reducer.begin_session

    def begin_with_second_queued_command(
        *,
        session_epoch: int,
        monotonic_ms: int,
    ) -> tuple[runtime_module.PendingRpc, ...]:
        commands = original_begin_session(
            session_epoch=session_epoch,
            monotonic_ms=monotonic_ms,
        )
        queued = runtime.reducer._schedule(
            purpose=runtime_module.RpcPurpose.CLOCK_BOOTSTRAP,
            method="public/get_time",
            params={},
            scope="CLOCK_INDEX",
            generation=None,
            origin_boundary=FactBoundary(session_epoch, 0, monotonic_ms, 0),
            failure_scope=FailureScope.CLOCK_INDEX,
        )
        return (*commands, queued)

    monkeypatch.setattr(runtime.reducer, "begin_session", begin_with_second_queued_command)
    stop_event = asyncio.Event()
    send_started = asyncio.Event()
    never_release = asyncio.Event()

    class BlockingClient(DeribitPublicClient):
        send_attempt_count = 0

        async def send_request(self, **_kwargs: object) -> None:
            self.send_attempt_count += 1
            send_started.set()
            await never_release.wait()

        async def next_envelope(
            self,
            timeout_seconds: float | None = None,
        ) -> InboundEnvelope:
            del timeout_seconds
            await stop_event.wait()
            raise TimeoutError

    client = BlockingClient(session_epoch=1, rpc_deadline_ms=30_000)

    async def scenario() -> Path:
        task = asyncio.create_task(runtime.run(client, stop_event))
        await send_started.wait()
        stop_event.set()
        return await task

    asyncio.run(scenario())
    lifecycles = tuple(runtime.reducer._rpc_lifecycles.values())
    assert len(lifecycles) == 2
    assert {lifecycle.state for lifecycle in lifecycles} == {runtime_module.RpcState.CENSORED}
    assert {lifecycle.terminal_from_state for lifecycle in lifecycles} == {
        runtime_module.RpcState.SCHEDULED
    }
    assert client.send_attempt_count == 1


def test_unexpected_sender_cancellation_fails_closed(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )

    async def cancelled_sender(*_args: object, **_kwargs: object) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(runtime, "_sender_loop", cancelled_sender)

    class WaitingClient:
        session_epoch = 1
        queue_high_water_frames = 0
        overflow_count = 0
        enqueued_envelope_count = 0
        received_frame_count = 0
        next_call_count = 0

        async def next_envelope(
            self,
            timeout_seconds: float | None = None,
        ) -> InboundEnvelope:
            del timeout_seconds
            self.next_call_count += 1
            await asyncio.sleep(0)
            if self.next_call_count > 1:
                raise AssertionError("cancelled sender was ignored")
            raise TimeoutError

        async def send_request(self, **_kwargs: object) -> None:
            raise AssertionError("patched sender must own transport calls")

        def enqueue_send_control(self, _event: object) -> None:
            raise AssertionError("patched sender must not emit controls")

    with pytest.raises(PublicSessionError, match="sender"):
        asyncio.run(runtime.run(WaitingClient(), asyncio.Event()))


def test_coverage_cause_has_no_default() -> None:
    with pytest.raises(TypeError):
        CoverageSegment(0, 1, CoverageState.UNKNOWN)  # type: ignore[call-arg]


def test_atomic_causal_invariant_allows_later_quote_only_when_detector_is_same_boundary() -> None:
    evidence_module.validate_atomic_causal_invariant(
        anomaly_activation_seq=10,
        detector_causal_seq=11,
        quote_causal_seq=11,
    )
    with pytest.raises(EvidenceError, match=r"detector.*quote|causal"):
        evidence_module.validate_atomic_causal_invariant(
            anomaly_activation_seq=10,
            detector_causal_seq=10,
            quote_causal_seq=11,
        )
    with pytest.raises(EvidenceError, match=r"activation|causal"):
        evidence_module.validate_atomic_causal_invariant(
            anomaly_activation_seq=12,
            detector_causal_seq=11,
            quote_causal_seq=11,
        )


def test_complete_writer_directory_accepts_anomaly_then_later_normalized_atomic_boundary(
    tmp_path: Path,
) -> None:
    writer = EvidenceWriter(
        tmp_path,
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
    )
    anomaly = project_anomaly_event(anomaly_evidence())
    later_atomic = project_atomic_event(
        replace(
            atomic_evidence(),
            detector_causal_seq=11,
            quote_causal_seq=11,
        )
    )

    writer.write_anomaly(anomaly)
    writer.write_atomic(later_atomic)
    scope = ScopeCounts("sha256:" + "b" * 64, "call", "band")
    scope.applicable_instrument_count = 1
    scope.distinct_anomaly_episode_count = 1
    scope.anomaly_activation_transition_count = 1
    scope.anomaly_end_count_by_reason[EpisodeEndReason.CENSORED_AT_STOP.value] = 1
    scope.known_active_duration_ms_sum_by_end_reason[EpisodeEndReason.CENSORED_AT_STOP.value] = 0
    scope.public_atomic_quote_state_transition_count[
        PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value
    ] = 1
    summary = current_summary_object()
    summary["counts_by_scope"] = [scope.as_object()]
    summary["anomaly_end_count_by_reason"] = {
        reason.value: int(reason is EpisodeEndReason.CENSORED_AT_STOP)
        for reason in EpisodeEndReason
    }
    summary["known_active_duration_ms_sum_by_end_reason"] = {
        reason.value: 0 for reason in EpisodeEndReason
    }
    summary["public_atomic_quote_state_transition_count"] = {
        PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value: 1
    }
    writer.write_summary(summary)

    assert len(tuple(tmp_path.glob("*.json"))) == 3
