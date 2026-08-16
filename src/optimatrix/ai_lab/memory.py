from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from optimatrix.ai_lab.canonical import (
    AI_LAB_DURABLE_ROOT,
    JsonObject,
    ValidationError,
    content_id,
    isolated_path,
    parse_utc,
    require_content_id,
    seal_object,
    strict_fields,
    utc_text,
    verify_seal,
)
from optimatrix.ai_lab.session_review import (
    SESSION_REVIEW_NAMESPACE,
    SESSION_REVIEW_SCHEMA,
    SessionReview,
)
from optimatrix.ai_lab.store import HashChainLog

MEMORY_REVIEW_NAMESPACE = "OptimatrixAiLabMemoryReviewV1"
MEMORY_REVIEW_SCHEMA = "optimatrix.ai-lab.memory-review.v1"
MEMORY_DIGEST_NAMESPACE = "OptimatrixAiLabMemoryDigestV1"


@dataclass(frozen=True)
class MemoryDigest:
    prior_review_count: int
    verdict_counts: tuple[tuple[str, int], ...]
    recurring_base_blockers: tuple[tuple[str, int], ...]
    hypothesis_counts: tuple[tuple[str, int], ...]
    prior_sessions: tuple[JsonObject, ...]
    fact_ids: tuple[str, ...]

    @property
    def identity(self) -> str:
        return content_id(MEMORY_DIGEST_NAMESPACE, self._draft())

    def _draft(self) -> JsonObject:
        return {
            "prior_review_count": self.prior_review_count,
            "verdict_counts": dict(self.verdict_counts),
            "recurring_base_blockers": dict(self.recurring_base_blockers),
            "hypothesis_counts": dict(self.hypothesis_counts),
            "prior_sessions": list(self.prior_sessions),
            "fact_ids": list(self.fact_ids),
            "boundary": (
                "Append-only sealed prior Session reviews and structured hypotheses only; no raw "
                "chat, Policy mutation, execution permission, or automatic promotion."
            ),
        }

    def as_object(self) -> JsonObject:
        return {"memory_digest_id": self.identity, **self._draft()}


class AiLabMemoryStore:
    """Separate append-only research memory; never an ObservationLedger or CaseJournal."""

    def __init__(self, root: Path = AI_LAB_DURABLE_ROOT) -> None:
        self.root = isolated_path(root)
        self.reviews = HashChainLog(
            self.root,
            "session-reviews.jsonl",
            "AI_LAB_SESSION_REVIEW",
        )
        self.analyses = HashChainLog(
            self.root,
            "codex-analyses.jsonl",
            "AI_LAB_CODEX_ANALYSIS",
        )

    def append_review(
        self,
        review: SessionReview,
        *,
        recorded_at: datetime,
    ) -> tuple[JsonObject, bool]:
        if recorded_at < parse_utc(review.session_id, "review.session_id"):
            raise ValidationError("AI Lab memory cannot record a Session review before its expiry")
        for event in self.reviews.read():
            payload = _review_memory_payload(event["payload"])
            if payload["session_id"] == review.session_id:
                if payload["review"] != review.as_object():
                    raise ValidationError(
                        "one Session already owns a different append-only AI Lab review"
                    )
                return event, False
        draft: JsonObject = {
            "schema_version": MEMORY_REVIEW_SCHEMA,
            "session_id": review.session_id,
            "recorded_at": utc_text(recorded_at),
            "review": review.as_object(),
        }
        payload = seal_object(
            draft,
            id_field="memory_review_id",
            namespace=MEMORY_REVIEW_NAMESPACE,
        )
        return self.reviews.append(payload, identity_field="memory_review_id")

    def append_analysis(self, analysis: Mapping[str, object]) -> tuple[JsonObject, bool]:
        from optimatrix.ai_lab.codex_analysis import validate_analysis

        parsed = validate_analysis(analysis)
        review_ids = {
            _review_memory_payload(event["payload"])["review"]["review_id"]
            for event in self.reviews.read()
        }
        if parsed["review_id"] not in review_ids:
            raise ValidationError("Codex analysis requires an existing sealed Session review")
        for event in self.analyses.read():
            prior = validate_analysis(event["payload"])
            if prior["review_id"] == parsed["review_id"]:
                if prior != parsed:
                    raise ValidationError(
                        "one Session review already owns a different Codex analysis"
                    )
                return event, False
        return self.analyses.append(parsed, identity_field="analysis_id")

    def digest(self, *, before_session_id: str | None = None) -> MemoryDigest:
        reviews = tuple(
            _review_memory_payload(event["payload"])
            for event in self.reviews.read()
            if before_session_id is None
            or str(event["payload"].get("session_id")) < before_session_id
        )
        allowed_review_ids = {str(item["review"]["review_id"]) for item in reviews}
        analyses = []
        for event in self.analyses.read():
            from optimatrix.ai_lab.codex_analysis import validate_analysis

            analysis = validate_analysis(event["payload"])
            if analysis["review_id"] in allowed_review_ids:
                analyses.append(analysis)
        verdicts: Counter[str] = Counter()
        blockers: Counter[str] = Counter()
        hypotheses: Counter[str] = Counter()
        session_rows: list[JsonObject] = []
        for payload in reviews:
            review = cast(JsonObject, payload["review"])
            verdicts[str(review["verdict"])] += 1
            blocker_counts = review.get("base_blocker_counts")
            if isinstance(blocker_counts, dict):
                for key, value in blocker_counts.items():
                    if isinstance(key, str) and isinstance(value, int):
                        blockers[key] += value
            review_id = require_content_id(review.get("review_id"), "review.review_id")
            session_rows.append(
                {
                    "session_id": payload["session_id"],
                    "review_id": review_id,
                    "verdict": review["verdict"],
                    "successful_opportunity_count": review["successful_opportunity_count"],
                    "challenger_comparison_eligible": review["challenger_comparison_eligible"],
                }
            )
        for analysis in analyses:
            raw_hypotheses = analysis.get("hypotheses")
            if isinstance(raw_hypotheses, list):
                for hypothesis in raw_hypotheses:
                    if isinstance(hypothesis, dict) and isinstance(
                        hypothesis.get("hypothesis_key"), str
                    ):
                        hypotheses[hypothesis["hypothesis_key"]] += 1
        recent_sessions = tuple(session_rows[-12:])
        recent_review_ids = tuple(str(item["review_id"]) for item in recent_sessions)
        recent_analysis_ids = tuple(str(item["analysis_id"]) for item in analyses[-12:])
        return MemoryDigest(
            prior_review_count=len(reviews),
            verdict_counts=tuple(sorted(verdicts.items())),
            recurring_base_blockers=tuple(
                sorted(blockers.items(), key=lambda item: (-item[1], item[0]))[:20]
            ),
            hypothesis_counts=tuple(
                sorted(hypotheses.items(), key=lambda item: (-item[1], item[0]))[:20]
            ),
            prior_sessions=recent_sessions,
            fact_ids=tuple(dict.fromkeys((*recent_review_ids, *recent_analysis_ids))),
        )

    def require_challenger_eligible(self, review_id: str) -> JsonObject:
        identifier = require_content_id(review_id, "review_id")
        for event in self.reviews.read():
            payload = _review_memory_payload(event["payload"])
            review = cast(JsonObject, payload["review"])
            if review.get("review_id") != identifier:
                continue
            if (
                review.get("verdict") != "BASE_FOUND_OPPORTUNITY"
                or review.get("challenger_comparison_eligible") is not True
                or review.get("auditable_window_count") != review.get("expected_window_count")
            ):
                raise ValidationError(
                    "Session review does not authorize a Base-versus-Challenger comparison"
                )
            return review
        raise ValidationError("eligible Session review does not exist in AI Lab memory")

    def verify(self) -> JsonObject:
        reviews = self.reviews.read()
        analyses = self.analyses.read()
        session_ids: set[str] = set()
        review_ids: set[str] = set()
        for event in reviews:
            payload = _review_memory_payload(event["payload"])
            session_id = str(payload["session_id"])
            if session_id in session_ids:
                raise ValidationError("AI Lab memory contains duplicate Sessions")
            session_ids.add(session_id)
            review_ids.add(str(payload["review"]["review_id"]))
        analysis_review_ids: set[str] = set()
        for event in analyses:
            from optimatrix.ai_lab.codex_analysis import validate_analysis

            analysis = validate_analysis(event["payload"])
            review_id = str(analysis["review_id"])
            if review_id not in review_ids:
                raise ValidationError("AI Lab memory contains an orphan Codex analysis")
            if review_id in analysis_review_ids:
                raise ValidationError("AI Lab memory contains duplicate Codex analyses")
            analysis_review_ids.add(review_id)
        return {
            "status": "VALID_AI_LAB_MEMORY",
            "session_review_count": len(reviews),
            "codex_analysis_count": len(analyses),
        }


def _review_memory_payload(value: object) -> JsonObject:
    item = strict_fields(
        value,
        {
            "schema_version",
            "memory_review_id",
            "session_id",
            "recorded_at",
            "review",
        },
        "memory_review",
    )
    if item["schema_version"] != MEMORY_REVIEW_SCHEMA:
        raise ValidationError("unsupported AI Lab memory review schema")
    verify_seal(item, id_field="memory_review_id", namespace=MEMORY_REVIEW_NAMESPACE)
    review = item["review"]
    if not isinstance(review, dict):
        raise ValidationError("memory review payload must contain one review object")
    if review.get("schema_version") != SESSION_REVIEW_SCHEMA:
        raise ValidationError("memory review contains an unsupported Session review")
    verify_seal(review, id_field="review_id", namespace=SESSION_REVIEW_NAMESPACE)
    if item["session_id"] != review.get("session_id"):
        raise ValidationError("memory Session does not match its review")
    return item
