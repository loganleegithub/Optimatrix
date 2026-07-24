from __future__ import annotations

import json
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, localcontext
from pathlib import Path
from typing import cast

import pytest
from market_tape import (
    CanonicalEvent,
    EventKind,
    PublicShadowJournalReader,
    PublicShadowJournalWriter,
    canonical_digest,
)
from radar_runtime.outcome_identity import outcome_runtime_source_identity
from radar_runtime.runtime_identity import runtime_source_identity
from radar_runtime.shadow_bundle import business_funnel_report
from radar_runtime.shadow_identity import (
    RUN_RUNTIME_SOURCE_SCOPE,
    run_runtime_source_identity,
    runtime_environment_identity,
)
from radar_runtime.shadow_report_identity import (
    RUN_REPORT_OPTIONAL_SOURCE_SCOPE,
    RUN_REPORT_SOURCE_SCOPE,
    run_report_source_identity,
)
from radar_runtime.shadow_runtime import (
    MAXIMUM_OPPORTUNITY_COMMIT_LATENCY_MS,
    RUN_RECEIPT_PATH,
    SEALED_RUN_SECONDS,
    _HardCutoffReached,
    _incomplete_public_run,
    _OnlineRunController,
    _reconstruct_operational_evidence,
    _synthetic_events,
    build_run_contract,
    compose_run,
    replay_shadow,
    run_synthetic_shadow,
)
from shadow_engine.run import (
    AdmissionClass,
    MaturityClass,
    OpportunitySummary,
    RunAccounting,
    classify_admission,
)
from short_vol_radar import RadarProjector


def _summary(
    slot: int,
    *,
    action: str | None,
    complete: bool,
    capacity: bool = True,
    outcome: str | None = None,
    maturity: MaturityClass | None = None,
    pnl: Decimal | None = None,
) -> OpportunitySummary:
    admission, reason = classify_admission(
        decision_complete=complete,
        decision_action=action,
        capacity_available=capacity,
    )
    return OpportunitySummary(
        slot_index=slot,
        event_backed=action is not None,
        decision_complete=complete,
        decision_action=action,
        admission_class=admission,
        admission_reason=reason,
        entry_receipt_digest=("e" * 64 if admission is AdmissionClass.ADMITTED else None),
        outcome_receipt_digest=("o" * 64 if outcome is not None else None),
        outcome_status=outcome,
        maturity_class=maturity,
        observed_executable_pnl_usdc=pnl,
    )


@pytest.mark.parametrize(
    ("complete", "action", "capacity", "expected"),
    (
        (False, "ABSTAIN", True, AdmissionClass.OPPORTUNITY_UNKNOWN),
        (True, "WATCH", True, AdmissionClass.NO_ENTRY),
        (True, "ABSTAIN", True, AdmissionClass.NO_ENTRY),
        (True, "RESEARCH_CANDIDATE", True, AdmissionClass.ADMITTED),
        (True, "RESEARCH_CANDIDATE", False, AdmissionClass.CONCURRENCY_BLOCKED),
        (False, None, True, AdmissionClass.OPPORTUNITY_UNKNOWN),
    ),
)
def test_admission_partition_is_fail_closed(
    complete: bool,
    action: str | None,
    capacity: bool,
    expected: AdmissionClass,
) -> None:
    admission, reason = classify_admission(
        decision_complete=complete,
        decision_action=action,
        capacity_available=capacity,
    )
    assert admission is expected
    assert reason


def test_complete_run_accounting_keeps_no_trade_zero_separate_from_null_strategy_pnl() -> None:
    opportunities = (
        _summary(
            0,
            action="RESEARCH_CANDIDATE",
            complete=True,
            outcome="CLOSED",
            maturity=MaturityClass.MATURE_CLOSED,
            pnl=Decimal("12.50"),
        ),
        _summary(
            1,
            action="RESEARCH_CANDIDATE",
            complete=True,
            capacity=False,
        ),
        _summary(2, action="WATCH", complete=True),
        _summary(
            3,
            action="RESEARCH_CANDIDATE",
            complete=True,
            outcome="UNKNOWN",
            maturity=MaturityClass.MATURE_UNKNOWN,
            pnl=None,
        ),
        *(_summary(slot, action="ABSTAIN", complete=True) for slot in range(4, 11)),
        _summary(11, action=None, complete=False),
    )
    accounting = RunAccounting.from_opportunities(opportunities, due_count=12)

    assert accounting.admission_counts == {
        "OPPORTUNITY_UNKNOWN": 1,
        "NO_ENTRY": 8,
        "ADMITTED": 2,
        "CONCURRENCY_BLOCKED": 1,
    }
    assert accounting.entry_count == accounting.outcome_count == 2
    assert accounting.no_trade_comparator_count == 12
    assert accounting.no_trade_pnl_usdc == Decimal("0")
    assert accounting.closed_pnl_subtotal_usdc == Decimal("12.50")
    assert accounting.null_strategy_result_count == 1
    assert accounting.strategy_total_pnl_usdc is None
    assert accounting.final_open_exposure_count == 1
    assert accounting.maximum_concurrent_exposure_count == 1


def test_complete_run_rejects_immature_entry_and_strategy_zero_for_unknown() -> None:
    opportunities = (
        *(_summary(slot, action="ABSTAIN", complete=True) for slot in range(11)),
        _summary(
            11,
            action="RESEARCH_CANDIDATE",
            complete=True,
            outcome="UNKNOWN",
            maturity=MaturityClass.IMMATURE_UNKNOWN,
        ),
    )
    with pytest.raises(ValueError, match="immature"):
        RunAccounting.from_opportunities(opportunities, due_count=12)

    with pytest.raises(ValueError, match="null"):
        _summary(
            0,
            action="RESEARCH_CANDIDATE",
            complete=True,
            outcome="UNKNOWN",
            maturity=MaturityClass.MATURE_UNKNOWN,
            pnl=Decimal("0"),
        )


def test_business_funnel_reports_both_candidate_denominators_and_partitions() -> None:
    report = business_funnel_report(
        {
            "due_opportunity_count": 12,
            "admission_counts": {
                "OPPORTUNITY_UNKNOWN": 6,
                "NO_ENTRY": 3,
                "ADMITTED": 2,
                "CONCURRENCY_BLOCKED": 1,
            },
            "action_counts": {
                "RESEARCH_CANDIDATE": 3,
                "WATCH": 1,
                "ABSTAIN": 5,
            },
        }
    )

    assert report == {
        "report_type": "FIXED_POLICY_PUBLIC_SHADOW_BUSINESS_FUNNEL_REPORT",
        "due_opportunity_count": 12,
        "complete_decision_count": 6,
        "candidate_count": 3,
        "opportunity_partition": {
            "OPPORTUNITY_UNKNOWN": 6,
            "NO_ENTRY": 3,
            "ADMITTED": 2,
            "CONCURRENCY_BLOCKED": 1,
        },
        "raw_candidate_rate": "0.25",
        "candidate_rate_given_complete": "0.5",
        "rate_semantics": "COUNTS_AUTHORITATIVE_DECIMAL_RENDERING_ONLY",
        "decimal_rendering": {
            "precision": 28,
            "rounding": "ROUND_HALF_EVEN",
        },
        "interpretation": "DESCRIPTIVE_ONLY_NOT_QUALIFICATION",
    }


def test_business_funnel_decimal_rendering_ignores_global_context() -> None:
    accounting = {
        "due_opportunity_count": 12,
        "admission_counts": {
            "OPPORTUNITY_UNKNOWN": 0,
            "NO_ENTRY": 11,
            "ADMITTED": 1,
            "CONCURRENCY_BLOCKED": 0,
        },
        "action_counts": {
            "RESEARCH_CANDIDATE": 1,
        },
    }
    baseline = business_funnel_report(accounting)

    with localcontext() as global_context:
        global_context.prec = 6
        global_context.rounding = ROUND_DOWN
        changed_context = business_funnel_report(accounting)

    assert baseline["raw_candidate_rate"] == "0.08333333333333333333333333333"
    assert changed_context == baseline
    assert canonical_digest(changed_context) == canonical_digest(baseline)


def test_business_funnel_complete_zero_keeps_raw_zero_and_conditional_null() -> None:
    report = business_funnel_report(
        {
            "due_opportunity_count": 4,
            "admission_counts": {
                "OPPORTUNITY_UNKNOWN": 4,
                "NO_ENTRY": 0,
                "ADMITTED": 0,
                "CONCURRENCY_BLOCKED": 0,
            },
            "action_counts": {
                "RESEARCH_CANDIDATE": 0,
                "WATCH": 0,
                "ABSTAIN": 4,
            },
        }
    )

    assert report["raw_candidate_rate"] == "0"
    assert report["candidate_rate_given_complete"] is None
    assert json.loads(json.dumps(report))["candidate_rate_given_complete"] is None


def test_business_funnel_due_zero_keeps_both_rates_null() -> None:
    report = business_funnel_report(
        {
            "due_opportunity_count": 0,
            "admission_counts": {
                "OPPORTUNITY_UNKNOWN": 0,
                "NO_ENTRY": 0,
                "ADMITTED": 0,
                "CONCURRENCY_BLOCKED": 0,
            },
            "action_counts": {
                "RESEARCH_CANDIDATE": 0,
                "WATCH": 0,
                "ABSTAIN": 0,
            },
        }
    )

    serialized = json.loads(json.dumps(report))
    assert serialized["raw_candidate_rate"] is None
    assert serialized["candidate_rate_given_complete"] is None


def test_deterministic_synthetic_run_has_full_denominator_and_fresh_replay(
    tmp_path: Path,
) -> None:
    run = run_synthetic_shadow(tmp_path / "run")
    replay = replay_shadow(tmp_path / "run", tmp_path / "replay")
    accounting = run["accounting"]

    assert isinstance(accounting, dict)
    assert accounting["due_opportunity_count"] == 12
    assert accounting["entry_count"] == accounting["outcome_count"] == 2
    assert accounting["maturity_counts"]["MATURE_CLOSED"] == 2
    assert accounting["maturity_counts"]["IMMATURE_UNKNOWN"] == 0
    assert accounting["admission_counts"]["CONCURRENCY_BLOCKED"] >= 1
    assert accounting["no_event_slot_count"] >= 1
    assert accounting["no_trade_comparator_count"] == 12
    assert accounting["no_trade_pnl_usdc"] == "0"
    assert accounting["maximum_concurrent_exposure_count"] == 1
    assert replay["computation_reconstructed"] is True
    assert replay["prefix_causality_verified"] is True
    assert replay["online_persistence_external_attested"] is False
    for layer in (
        "schedule",
        "fact",
        "decision",
        "admission",
        "entry",
        "outcome",
        "maturity",
        "no_trade",
        "aggregate",
        "run_receipt",
    ):
        assert type(replay[f"{layer}_drift_count"]) is int
        assert replay[f"{layer}_drift_count"] == 0


def _controller(
    tmp_path: Path,
) -> tuple[
    _OnlineRunController,
    PublicShadowJournalWriter,
    RadarProjector,
    list[int],
    dict[str, object],
]:
    decision_identity = runtime_source_identity(require_clean=False)
    outcome_identity = outcome_runtime_source_identity(require_clean=False)
    run_identity = run_runtime_source_identity(require_clean=False)
    contract = build_run_contract(
        run_id="online-controller-test",
        fact_provenance="synthetic",
        created_at="2026-07-23T00:00:00+00:00",
        decision_identity=decision_identity,
        outcome_identity=outcome_identity,
        run_identity=run_identity,
        environment=runtime_environment_identity(),
    )
    clock = [0]
    writer = PublicShadowJournalWriter(
        tmp_path / "online",
        run_contract=contract,
        elapsed_ms=lambda: clock[0],
    )
    controller = _OnlineRunController(
        root=tmp_path / "online",
        writer=writer,
        run_contract=contract,
        decision_identity=decision_identity,
        outcome_identity=outcome_identity,
        elapsed_ms=lambda: clock[0],
    )
    projector = RadarProjector()
    controller.attach_projector(projector)
    return controller, writer, projector, clock, contract


def test_online_controller_commits_each_opportunity_before_later_facts(
    tmp_path: Path,
) -> None:
    controller, writer, projector, clock, contract = _controller(tmp_path)
    events = _synthetic_events()
    for event in events:
        clock[0] = event.collector_elapsed_ms
        controller.before_event(event)
        controller.after_event(event, projector.ingest(event))
        probe = controller.due_probe(
            now_elapsed_ms=clock[0],
            active_connection=True,
        )
        if probe is not None:
            acquisition = controller.begin_probe(
                probe[0],
                probe[1],
                request_id=1_000 + event.capture_seq,
            )
            controller.commit_probe_rpc_result(
                probe[0],
                attempt=probe[1],
                acquisition_ordinal=acquisition,
                request_id=1_000 + event.capture_seq,
                method="public/subscribe",
                result="ACKNOWLEDGED",
                error=None,
                actual_elapsed_ms=clock[0],
            )
            controller.finish_probe(
                probe[0],
                probe[1],
                state="SUBSCRIPTION_ACKNOWLEDGED",
                request_id=1_000 + event.capture_seq,
                error=None,
                acquisition_ordinal=acquisition,
            )
            probe[0]["satisfied"] = True
    assert controller.origin_elapsed_ms is not None
    seal_end = controller.origin_elapsed_ms + SEALED_RUN_SECONDS * 1_000
    clock[0] = seal_end
    controller.advance_time(seal_end)
    controller.due_probe(now_elapsed_ms=seal_end, active_connection=False)
    writer.seal_fact_segments(seal_end)
    durable = PublicShadowJournalReader(tmp_path / "online").read_committed_events()
    reconstructed = compose_run(
        durable,
        run_contract=contract,
        decision_identity=runtime_source_identity(require_clean=False),
        outcome_identity=outcome_runtime_source_identity(require_clean=False),
        fact_seal_digest="controller-test-fact-seal",
    )
    assert list(controller.records) == list(reconstructed.opportunities)
    assert not controller.incomplete_reasons
    writer.seal(seal_end, complete=True, incomplete_reasons=())
    assert PublicShadowJournalReader(tmp_path / "online").verify().opportunity_count == 12


def test_online_runtime_and_offline_report_source_scopes_are_separate() -> None:
    online_paths = set(RUN_RUNTIME_SOURCE_SCOPE)
    report_paths = set(RUN_REPORT_SOURCE_SCOPE)
    online_identity = run_runtime_source_identity(require_clean=False)
    report_identity = run_report_source_identity(require_clean=False)

    assert "apps/radar_runtime/src/radar_runtime/shadow_runtime.py" in online_paths
    assert "apps/radar_runtime/src/radar_runtime/shadow_bundle.py" not in online_paths
    assert "apps/radar_runtime/src/radar_runtime/shadow_bundle.py" in report_paths
    assert "apps/radar_runtime/src/radar_runtime/shadow_report_identity.py" in report_paths
    assert "apps/radar_runtime/src/radar_runtime/shadow_report_identity.py" not in online_paths
    assert RUN_REPORT_OPTIONAL_SOURCE_SCOPE == ("offline_audits",)
    assert online_paths.isdisjoint(report_paths)
    assert report_identity.online_runtime_source_id == online_identity.runtime_source_id
    assert report_identity.online_runtime_source_digest == online_identity.runtime_source_digest


def test_late_opportunity_commit_is_anomaly_when_causal_order_is_preserved(
    tmp_path: Path,
) -> None:
    controller, writer, projector, clock, _contract = _controller(tmp_path)
    for event in _synthetic_events():
        clock[0] = event.collector_elapsed_ms
        controller.before_event(event)
        controller.after_event(event, projector.ingest(event))
        if controller.origin_elapsed_ms is not None:
            break
    assert controller.origin_elapsed_ms is not None
    record = controller._no_event_record(0)
    trigger = cast(int, record["interval_end_elapsed_ms"])
    clock[0] = trigger + MAXIMUM_OPPORTUNITY_COMMIT_LATENCY_MS + 1

    controller._commit_opportunity(record, trigger)

    assert controller.incomplete_reasons == []
    assert controller.operational_anomalies == ["OPPORTUNITY_COMMIT_LATENCY_BREACH"]
    writer.interrupt(("INJECTED_OPERATIONAL_ANOMALY_TEST",))


def test_negative_opportunity_commit_latency_remains_incomplete(tmp_path: Path) -> None:
    controller, writer, projector, clock, _contract = _controller(tmp_path)
    for event in _synthetic_events():
        clock[0] = event.collector_elapsed_ms
        controller.before_event(event)
        controller.after_event(event, projector.ingest(event))
        if controller.origin_elapsed_ms is not None:
            break
    assert controller.origin_elapsed_ms is not None
    record = controller._no_event_record(0)
    trigger = cast(int, record["interval_end_elapsed_ms"])
    clock[0] = trigger - 1

    controller._commit_opportunity(record, trigger)

    assert controller.operational_anomalies == []
    assert controller.incomplete_reasons == ["OPPORTUNITY_COMMIT_LATENCY_BREACH"]
    writer.interrupt(("INJECTED_NEGATIVE_LATENCY_TEST",))


def test_operational_anomalies_reconstruct_from_actual_causal_times() -> None:
    event = replace(_synthetic_events()[0], capture_seq=1, collector_elapsed_ms=1_000)
    opportunities: tuple[dict[str, object], ...] = (
        {
            "event_backed": True,
            "cutoff_capture_seq": 1,
        },
    )
    commits: tuple[dict[str, object], ...] = (
        {
            "commit_type": "OPPORTUNITY_COMMIT",
            "opportunity_ordinal": 1,
            "commit_elapsed_ms": 7_000,
        },
        {
            "commit_type": "NETWORK_OPEN_INTENT_COMMIT",
            "retry_dispatch_breach": True,
        },
        {
            "commit_type": "PLATFORM_PROBE_STATE_COMMIT",
            "state": "MISSED_DEADLINE",
        },
        {
            "commit_type": "PLATFORM_PROBE_STATE_COMMIT",
            "state": "OMITTED_BEFORE_LATER_FACT",
        },
    )

    latencies, anomalies = _reconstruct_operational_evidence(
        commits,
        opportunities,
        (event,),
    )

    assert latencies == [6_000]
    assert anomalies == {
        "NETWORK_RETRY_DISPATCH_LATE": 1,
        "OPPORTUNITY_COMMIT_LATENCY_BREACH": 1,
        "PLATFORM_PROBE_MISSED_DEADLINE": 1,
        "PLATFORM_PROBE_TIMER_ORDER_BREACH": 1,
    }


def test_incomplete_public_prefix_never_persists_successful_run_receipt(
    tmp_path: Path,
) -> None:
    controller, writer, _projector, clock, contract = _controller(tmp_path)
    clock[0] = 60_000
    result = _incomplete_public_run(
        output=tmp_path / "online",
        writer=writer,
        controller=controller,
        elapsed_ms=clock[0],
        reasons=("INITIAL_SETUP_TIMEOUT",),
        contract=contract,
    )

    assert result["complete"] is False
    assert not (tmp_path / "online" / RUN_RECEIPT_PATH).exists()
    verified = PublicShadowJournalReader(tmp_path / "online").verify(allow_incomplete=True)
    assert verified.complete is False


def test_setup_deadline_fact_is_excluded_before_segment_commit(tmp_path: Path) -> None:
    controller, writer, _projector, clock, _contract = _controller(tmp_path)
    clock[0] = 60_000
    late = replace(
        _synthetic_events()[0],
        collector_elapsed_ms=60_000,
    )

    with pytest.raises(_HardCutoffReached):
        controller.before_event(late)

    assert writer.last_capture_seq is None
    assert "INITIAL_ORIGIN_DEADLINE_MISSED" in controller.incomplete_reasons
    writer.interrupt(("INITIAL_ORIGIN_DEADLINE_MISSED",))
    verified = PublicShadowJournalReader(tmp_path / "online").verify(allow_incomplete=True)
    assert verified.events == ()
    assert verified.segments[-1].planned_end_elapsed_ms == 60_000


def test_probe_deadline_wakeup_never_backdates_or_catches_up_expired_attempts(
    tmp_path: Path,
) -> None:
    controller, writer, projector, clock, _contract = _controller(tmp_path)
    entry_event = None
    for event in _synthetic_events():
        clock[0] = event.collector_elapsed_ms
        controller.before_event(event)
        controller.after_event(event, projector.ingest(event))
        if controller.active_exposure:
            entry_event = event
            break
    assert entry_event is not None
    clock[0] = entry_event.collector_elapsed_ms + 60_000
    next_attempt = controller.due_probe(
        now_elapsed_ms=clock[0],
        active_connection=True,
    )
    assert next_attempt is not None
    assert next_attempt[1] == 1
    assert "PLATFORM_PROBE_MISSED_DEADLINE" in controller.operational_anomalies
    assert "PLATFORM_PROBE_MISSED_DEADLINE" not in controller.incomplete_reasons
    controller.finish_probe(
        next_attempt[0],
        next_attempt[1],
        state="SEND_OR_RESPONSE_FAILED",
        request_id=10,
        error="InjectedFailure",
    )

    clock[0] = entry_event.collector_elapsed_ms + 180_000
    assert (
        controller.due_probe(
            now_elapsed_ms=clock[0],
            active_connection=True,
        )
        is None
    )
    assert controller.operational_anomalies.count("PLATFORM_PROBE_MISSED_DEADLINE") == 2
    writer.interrupt(("INJECTED_PROBE_DEADLINE_TEST",))


def test_reconnect_with_open_exposure_retires_old_probe_and_creates_bootstrap_obligation(
    tmp_path: Path,
) -> None:
    controller, writer, projector, clock, _contract = _controller(tmp_path)
    for event in _synthetic_events():
        clock[0] = event.collector_elapsed_ms
        controller.before_event(event)
        controller.after_event(event, projector.ingest(event))
        if controller.active_exposure:
            break
    initial = controller._probe_obligations[-1]
    probe = controller.due_probe(
        now_elapsed_ms=clock[0],
        active_connection=True,
    )
    assert probe is not None
    acquisition = controller.begin_probe(probe[0], probe[1], request_id=77)
    controller.commit_probe_rpc_result(
        probe[0],
        attempt=probe[1],
        acquisition_ordinal=acquisition,
        request_id=77,
        method="public/subscribe",
        result="ACKNOWLEDGED",
        error=None,
        actual_elapsed_ms=clock[0],
    )
    controller.finish_probe(
        probe[0],
        probe[1],
        state="PAIR_RECEIVED",
        request_id=78,
        error=None,
        acquisition_ordinal=acquisition,
    )
    initial["satisfied"] = True

    clock[0] += 10
    last_capture_seq = writer.last_capture_seq
    assert last_capture_seq is not None
    reconnect = CanonicalEvent(
        capture_seq=last_capture_seq + 1,
        collector_received_at_ms=1_800_000_000_000 + clock[0],
        collector_elapsed_ms=clock[0],
        exchange_timestamp_ms=None,
        channel="control",
        event_kind=EventKind.RECONNECT,
        instrument_name=None,
        raw_payload='{"reason":"InjectedDisconnect"}',
    )
    controller.connection_generation = 2
    controller.before_event(reconnect)
    controller.after_event(reconnect, projector.ingest(reconnect))

    replacement = controller._probe_obligations[-1]
    assert initial["retired"] is True
    assert replacement["attempt_zero_mode"] == "RECONNECT_BOOTSTRAP"
    assert replacement["connection_generation"] == 2
    assert replacement["trigger_capture_seq"] == reconnect.capture_seq
    assert (
        controller.due_probe(
            now_elapsed_ms=clock[0],
            active_connection=False,
        )
        is None
    )
    assert replacement["attempts"] == {}

    commits = [
        json.loads(line)
        for line in (tmp_path / "online" / "causal-commits.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    reconnect_fact_index = next(
        index
        for index, item in enumerate(commits)
        if item.get("commit_type") == "FACT_COMMIT"
        and item.get("capture_seq") == reconnect.capture_seq
    )
    assert [
        item["commit_type"] for item in commits[reconnect_fact_index : reconnect_fact_index + 3]
    ] == [
        "FACT_COMMIT",
        "PLATFORM_PROBE_STATE_COMMIT",
        "PLATFORM_PROBE_OBLIGATION_COMMIT",
    ]
    writer.interrupt(("INJECTED_RECONNECT_TEST",))
