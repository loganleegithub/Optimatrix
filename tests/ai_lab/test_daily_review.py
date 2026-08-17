from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from optimatrix.ai_lab.canonical import ValidationError
from optimatrix.ai_lab.daily_review import run_next_daily_review
from optimatrix.ai_lab.hindsight_evidence import OfficialIndexEvidence, SessionNotEndedError
from optimatrix.ai_lab.memory import AiLabMemoryStore
from optimatrix.ai_lab.web_projection import (
    WORKBENCH_REVIEW_FILENAME,
    WorkbenchReviewProjectionReader,
    read_workbench_review_projection,
    write_daily_state,
    write_workbench_review_projection,
)
from optimatrix.decision import schedule_decision_windows, unassessed_decision_record
from optimatrix.lifecycle import WindowOutcome, window_outcome_eligibility
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.session import current_deribit_session
from optimatrix.workbench import build_workbench_document, write_workbench
from tests.ai_lab.test_hindsight_evidence import _history
from tests.test_workbench import _snapshot


def test_daily_review_waits_for_outcomes_then_appends_once_and_projects_web(
    policy,
    tmp_path,
) -> None:
    ledger_root = tmp_path / "ledger"
    lab_root = tmp_path / "ai-lab"
    session_id, records, outcomes = _unknown_population(policy)
    ledger = ObservationLedger(ledger_root)
    for record in records:
        ledger.append(record)
    for outcome in outcomes[:-1]:
        ledger.append_outcome(outcome)
    evidence = _evidence(session_id)
    fetches: list[str] = []

    def fetch(*, session_id: str) -> OfficialIndexEvidence:
        fetches.append(session_id)
        return evidence

    waiting = run_next_daily_review(
        ledger_root=ledger_root,
        lab_root=lab_root,
        first_session_id=session_id,
        policy=policy,
        fetch_evidence=fetch,
    )

    assert waiting.status == "NOT_READY"
    assert waiting.detail == "WINDOW_OUTCOMES_INCOMPLETE:95/96"
    assert fetches == []
    assert not (lab_root / "policy-quality-reviews.jsonl").exists()

    ledger.append_outcome(outcomes[-1])
    completed = run_next_daily_review(
        ledger_root=ledger_root,
        lab_root=lab_root,
        first_session_id=session_id,
        policy=policy,
        fetch_evidence=fetch,
    )

    assert completed.status == "SUCCEEDED"
    assert completed.target_session_id == session_id
    assert completed.review_id is not None
    assert Path(completed.report_json or "").is_file()
    assert Path(completed.report_markdown or "").is_file()
    assert fetches == [session_id]
    assert AiLabMemoryStore(lab_root).verify()["policy_quality_review_count"] == 1

    next_session_id = (
        (datetime.fromisoformat(session_id.replace("Z", "+00:00")) + timedelta(days=1))
        .isoformat()
        .replace("+00:00", "Z")
    )

    def next_not_ended(*, session_id: str) -> OfficialIndexEvidence:
        fetches.append(session_id)
        raise SessionNotEndedError("not ended")

    repeated = run_next_daily_review(
        ledger_root=ledger_root,
        lab_root=lab_root,
        first_session_id=session_id,
        policy=policy,
        fetch_evidence=next_not_ended,
    )
    assert repeated.status == "NOT_READY"
    assert repeated.target_session_id == next_session_id
    assert repeated.detail == "SESSION_NOT_ENDED_BY_DERIBIT_CLOCK"
    assert fetches == [session_id, next_session_id]
    assert AiLabMemoryStore(lab_root).verify()["policy_quality_review_count"] == 1

    at = datetime.fromisoformat(session_id.replace("Z", "+00:00")) + timedelta(hours=1)
    write_daily_state(
        root=lab_root,
        status="SUCCEEDED",
        updated_at=at,
        target_session_id=session_id,
        detail="AI_LAB_POLICY_QUALITY_REVIEW_RECORDED",
        review_id=completed.review_id,
    )
    projection = write_workbench_review_projection(
        memory=AiLabMemoryStore(lab_root),
        generated_at=at,
        root=lab_root,
    )
    restored = read_workbench_review_projection(root=lab_root)
    assert restored == projection
    assert restored["reviews"][0]["session_id"] == session_id
    assert len(restored["reviews"][0]["windows"]) == 96

    read_result = WorkbenchReviewProjectionReader(lab_root).read()
    document = build_workbench_document(
        _snapshot(),
        completed_session_reviews=read_result,
    )
    assert document["review"]["completed"]["status"] == "AVAILABLE"
    assert document["review"]["completed"]["reviews"][0]["review_id"] == completed.review_id

    export = write_workbench(
        _snapshot(),
        tmp_path / "workbench",
        completed_session_reviews=read_result,
    )
    first_window_id = restored["reviews"][0]["windows"][0]["decision_window_id"]
    assert first_window_id not in export.data_path.read_text(encoding="utf-8")
    assert first_window_id in export.review_data_path.read_text(encoding="utf-8")
    review_data_mtime = export.review_data_path.stat().st_mtime_ns
    write_workbench(
        _snapshot(),
        tmp_path / "workbench",
        completed_session_reviews=read_result,
    )
    assert export.review_data_path.stat().st_mtime_ns == review_data_mtime


def test_daily_review_keeps_zero_record_session_in_registered_denominator(
    policy,
    tmp_path,
) -> None:
    ledger_root = tmp_path / "ledger"
    lab_root = tmp_path / "ai-lab"
    session_id, _records, _outcomes = _unknown_population(policy)
    evidence = _evidence(session_id)

    completed = run_next_daily_review(
        ledger_root=ledger_root,
        lab_root=lab_root,
        first_session_id=session_id,
        policy=policy,
        fetch_evidence=lambda *, session_id: evidence,
    )

    assert completed.status == "SUCCEEDED"
    payload = AiLabMemoryStore(lab_root).current_review_entries()[0]["review"]
    assert payload["expected_window_count"] == 96
    assert payload["recorded_decision_count"] == 0
    assert payload["recorded_outcome_count"] == 0
    assert payload["unknown_window_count"] == 96


def test_report_before_memory_append_makes_crash_boundary_recoverable(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    ledger_root = tmp_path / "ledger"
    lab_root = tmp_path / "ai-lab"
    session_id, records, outcomes = _unknown_population(policy)
    ledger = ObservationLedger(ledger_root)
    for record in records:
        ledger.append(record)
    for outcome in outcomes:
        ledger.append_outcome(outcome)
    evidence = _evidence(session_id)
    fetch_count = 0

    def fetch(*, session_id: str) -> OfficialIndexEvidence:
        nonlocal fetch_count
        fetch_count += 1
        return evidence

    with monkeypatch.context() as patch:
        patch.setattr(
            AiLabMemoryStore,
            "append_review",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValidationError("SIMULATED_CRASH_BEFORE_MEMORY_APPEND")
            ),
        )
        with pytest.raises(ValidationError, match="SIMULATED_CRASH"):
            run_next_daily_review(
                ledger_root=ledger_root,
                lab_root=lab_root,
                first_session_id=session_id,
                policy=policy,
                fetch_evidence=fetch,
            )

    reports_after_crash = tuple((lab_root / "reports").rglob("policy-quality-review.json"))
    assert len(reports_after_crash) == 1
    assert not (lab_root / "policy-quality-reviews.jsonl").exists()

    recovered = run_next_daily_review(
        ledger_root=ledger_root,
        lab_root=lab_root,
        first_session_id=session_id,
        policy=policy,
        fetch_evidence=fetch,
    )
    assert recovered.status == "SUCCEEDED"
    assert fetch_count == 1
    assert tuple((lab_root / "reports").rglob("policy-quality-review.json")) == reports_after_crash
    assert AiLabMemoryStore(lab_root).verify()["policy_quality_review_count"] == 1


def test_corrupt_web_projection_fails_closed_for_display_without_raising(
    policy,
    tmp_path,
) -> None:
    lab_root = tmp_path / "ai-lab"
    path = lab_root / WORKBENCH_REVIEW_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": "foreign"}), encoding="utf-8")

    result = WorkbenchReviewProjectionReader(lab_root).read()

    assert result == {
        "status": "UNAVAILABLE",
        "reason": "AI_LAB_REVIEW_PROJECTION_INVALID",
        "projection": None,
    }
    document = build_workbench_document(_snapshot(), completed_session_reviews=result)
    assert document["review"]["completed"]["status"] == "UNAVAILABLE"
    assert document["runtime"]["status"] == "SNAPSHOT_ONLY"


def test_corrupt_operational_state_cannot_block_review_projection_or_next_state_write(
    tmp_path,
) -> None:
    lab_root = tmp_path / "ai-lab"
    state_path = lab_root / "daily-review-state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{foreign", encoding="utf-8")
    at = datetime(2026, 8, 18, 9, tzinfo=UTC)

    projection = write_workbench_review_projection(
        memory=AiLabMemoryStore(lab_root),
        generated_at=at,
        root=lab_root,
    )
    assert projection["automation"]["status"] == "FAILED"
    assert projection["automation"]["detail"] == "DAILY_REVIEW_STATE_INVALID"

    state = write_daily_state(
        root=lab_root,
        status="NOT_READY",
        updated_at=at,
        target_session_id="2026-08-19T08:00:00Z",
        detail="SESSION_NOT_ENDED_BY_DERIBIT_CLOCK",
    )
    assert state["status"] == "NOT_READY"
    assert json.loads(state_path.read_text(encoding="utf-8")) == state


def _unknown_population(policy) -> tuple[str, tuple, tuple]:
    anchor = datetime(2026, 8, 16, 12, tzinfo=UTC)
    session = current_deribit_session(anchor, phase_policy=policy.session)
    windows = schedule_decision_windows(
        session=session,
        channel_id=policy.channel_id,
        policy=policy.window,
    )
    records = tuple(
        unassessed_decision_record(
            window=window,
            decision_policy_id=policy.identity,
            known_at=window.input_deadline,
            observation=None,
        )
        for window in windows
    )
    outcomes = tuple(_unknown_outcome(record, session.end) for record in records)
    return session.session_id, records, outcomes


def _unknown_outcome(record, expiry: datetime) -> WindowOutcome:
    horizon_end = max(expiry, record.window.ends_at + timedelta(minutes=15))
    return WindowOutcome(
        decision_window_id=record.window.identity,
        horizon_starts_at=record.window.ends_at,
        horizon_ends_at=horizon_end,
        known_at=horizon_end + timedelta(minutes=1),
        future_path_known=False,
        future_path_continuous=None,
        expiry_settlement=None,
        future_path=None,
        regime_labels=(),
        reason="PUBLIC_PATH_MISSING",
        eligibility=window_outcome_eligibility(
            decision_evaluable=False,
            future_path_known=False,
            future_path_continuous=None,
        ),
    )


def _evidence(session_id: str) -> OfficialIndexEvidence:
    expiry = datetime.fromisoformat(session_id.replace("Z", "+00:00"))
    return OfficialIndexEvidence.from_history(
        session_id=session_id,
        requested_at=expiry + timedelta(hours=1),
        history=_history(session_id),
    )
