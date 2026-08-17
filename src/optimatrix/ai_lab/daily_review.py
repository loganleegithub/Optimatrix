from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from optimatrix.ai_lab.canonical import (
    AI_LAB_DURABLE_ROOT,
    ValidationError,
    parse_utc,
    utc_text,
)
from optimatrix.ai_lab.hindsight_evidence import (
    OfficialIndexEvidence,
    SessionNotEndedError,
    earliest_official_index_evidence,
    fetch_official_index_evidence,
    write_official_index_evidence,
)
from optimatrix.ai_lab.memory import AiLabMemoryStore
from optimatrix.ai_lab.report import write_session_report
from optimatrix.ai_lab.session_review import review_ledger_session
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.session import current_deribit_session


@dataclass(frozen=True)
class DailyReviewResult:
    status: str
    target_session_id: str | None
    detail: str
    review_id: str | None = None
    evidence_id: str | None = None
    report_json: str | None = None
    report_markdown: str | None = None

    def as_object(self) -> dict[str, object]:
        return {
            "status": self.status,
            "target_session_id": self.target_session_id,
            "detail": self.detail,
            "review_id": self.review_id,
            "evidence_id": self.evidence_id,
            "report_json": self.report_json,
            "report_markdown": self.report_markdown,
        }


def run_next_daily_review(
    *,
    ledger_root: Path,
    lab_root: Path = AI_LAB_DURABLE_ROOT,
    first_session_id: str,
    policy: BtcShortVolPolicy,
    fetch_evidence: Callable[..., OfficialIndexEvidence] = fetch_official_index_evidence,
) -> DailyReviewResult:
    """Review at most one ready ended Session; never wait or retry inside the process."""

    first_session = parse_utc(first_session_id, "first_session_id")
    memory = AiLabMemoryStore(lab_root)
    ledger = ObservationLedger(ledger_root)
    records = ledger.read()
    outcomes = ledger.read_outcomes()
    if (
        current_deribit_session(
            first_session - timedelta(microseconds=1),
            phase_policy=policy.session,
        ).session_id
        != first_session_id
    ):
        raise ValidationError("first_session_id must be one canonical Deribit Session expiry")

    records_by_session: dict[str, set[str]] = defaultdict(set)
    for record in records:
        session_id = record.window.market_session_id
        if parse_utc(session_id, "record.window.market_session_id") >= first_session:
            records_by_session[session_id].add(record.window.identity)
    outcomes_by_window = {outcome.decision_window_id: outcome for outcome in outcomes}
    reviewed_sessions = memory.current_review_session_ids()
    target = first_session
    while utc_text(target) in reviewed_sessions:
        target += timedelta(days=1)
    target_session_id = utc_text(target)
    window_ids = records_by_session[target_session_id]
    outcome_count = sum(window_id in outcomes_by_window for window_id in window_ids)
    if outcome_count != len(window_ids):
        return DailyReviewResult(
            status="NOT_READY",
            target_session_id=target_session_id,
            detail=f"WINDOW_OUTCOMES_INCOMPLETE:{outcome_count}/{len(window_ids)}",
        )

    evidence = earliest_official_index_evidence(
        session_id=target_session_id,
        root=lab_root,
    )
    if evidence is None:
        try:
            evidence = fetch_evidence(session_id=target_session_id)
        except SessionNotEndedError:
            return DailyReviewResult(
                status="NOT_READY",
                target_session_id=target_session_id,
                detail="SESSION_NOT_ENDED_BY_DERIBIT_CLOCK",
            )
        write_official_index_evidence(evidence, root=lab_root)
    review = review_ledger_session(
        ledger_root=ledger_root,
        session_id=target_session_id,
        policy=policy,
        official_index_evidence=evidence,
        supersedes_review_id=memory.review_predecessor_id(session_id=target_session_id),
    )
    prior_memory = memory.digest(before_session_id=review.session_id)
    json_path, markdown_path = write_session_report(
        review=review,
        memory=prior_memory,
        root=lab_root,
    )
    _event, appended = memory.append_review(review, recorded_at=evidence.requested_at)
    if not appended:
        raise ValidationError("daily Review selected a Session already present in current memory")
    return DailyReviewResult(
        status="SUCCEEDED",
        target_session_id=target_session_id,
        detail="AI_LAB_POLICY_QUALITY_REVIEW_RECORDED",
        review_id=review.identity,
        evidence_id=evidence.identity,
        report_json=str(json_path),
        report_markdown=str(markdown_path),
    )
