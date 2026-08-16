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

MEMORY_REVIEW_NAMESPACE = "OptimatrixAiLabMemoryPolicyQualityReviewV3"
MEMORY_REVIEW_SCHEMA = "optimatrix.ai-lab.memory-policy-quality-review.v3"
MEMORY_DIGEST_NAMESPACE = "OptimatrixAiLabMemoryDigestV4"

POLICY_QUALITY_V1_MEMORY_NAMESPACE = "OptimatrixAiLabMemoryPolicyQualityReviewV1"
POLICY_QUALITY_V1_MEMORY_SCHEMA = "optimatrix.ai-lab.memory-policy-quality-review.v1"
POLICY_QUALITY_V1_REVIEW_NAMESPACE = "OptimatrixAiLabPolicyQualityReviewV1"
POLICY_QUALITY_V1_REVIEW_SCHEMA = "optimatrix.ai-lab.policy-quality-review.v1"
POLICY_QUALITY_V1_STATUS = "SUPERSEDED_BY_PARTIAL_IDENTIFICATION_V2"

POLICY_QUALITY_V2_MEMORY_NAMESPACE = "OptimatrixAiLabMemoryPolicyQualityReviewV2"
POLICY_QUALITY_V2_MEMORY_SCHEMA = "optimatrix.ai-lab.memory-policy-quality-review.v2"
POLICY_QUALITY_V2_REVIEW_NAMESPACE = "OptimatrixAiLabPolicyQualityReviewV2"
POLICY_QUALITY_V2_REVIEW_SCHEMA = "optimatrix.ai-lab.policy-quality-review.v2"
POLICY_QUALITY_V2_STATUS = "SUPERSEDED_BY_RISK_QUALITY_V3"

LEGACY_MEMORY_REVIEW_NAMESPACE = "OptimatrixAiLabMemoryReviewV1"
LEGACY_MEMORY_REVIEW_SCHEMA = "optimatrix.ai-lab.memory-review.v1"
LEGACY_SESSION_REVIEW_NAMESPACE = "OptimatrixAiLabSessionReviewV1"
LEGACY_SESSION_REVIEW_SCHEMA = "optimatrix.ai-lab.session-review.v1"
LEGACY_POLICY_QUALITY_STATUS = "INVALID_FOR_POLICY_QUALITY"


@dataclass(frozen=True)
class MemoryDigest:
    prior_review_count: int
    superseded_policy_quality_v1_review_count: int
    superseded_policy_quality_v2_review_count: int
    invalid_legacy_review_count: int
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
            "superseded_policy_quality_v1_review_count": (
                self.superseded_policy_quality_v1_review_count
            ),
            "superseded_policy_quality_v2_review_count": (
                self.superseded_policy_quality_v2_review_count
            ),
            "invalid_legacy_review_count": self.invalid_legacy_review_count,
            "legacy_policy_quality_status": LEGACY_POLICY_QUALITY_STATUS,
            "verdict_counts": dict(self.verdict_counts),
            "recurring_base_blockers": dict(self.recurring_base_blockers),
            "hypothesis_counts": dict(self.hypothesis_counts),
            "prior_sessions": list(self.prior_sessions),
            "fact_ids": list(self.fact_ids),
            "boundary": (
                "Append-only current Policy-quality reviews and structured hypotheses only. "
                "Superseded V1 all-or-nothing, V2 Policy-blocker-waiving, and legacy "
                "terminal-positive reviews are counted but excluded from verdict memory, Codex "
                "facts, Policy mutation, execution permission, and automatic promotion."
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
            "policy-quality-reviews.jsonl",
            "AI_LAB_POLICY_QUALITY_REVIEW",
        )
        self.legacy_reviews = HashChainLog(
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
        session_events = [
            (event, _review_memory_payload(event["payload"]))
            for event in self.reviews.read()
            if event["payload"].get("session_id") == review.session_id
        ]
        for event, payload in session_events:
            if payload["review"] == review.as_object():
                return event, False
        predecessor_id = (
            str(session_events[-1][1]["review"]["review_id"]) if session_events else None
        )
        if review.supersedes_review_id != predecessor_id:
            raise ValidationError(
                "V3 Policy-quality review must name the exact prior Review it supersedes"
            )
        if any(
            payload["review"].get("schema_version") == SESSION_REVIEW_SCHEMA
            for _event, payload in session_events
        ):
            raise ValidationError("one Session already owns a current V3 Policy-quality review")
        draft: JsonObject = {
            "schema_version": MEMORY_REVIEW_SCHEMA,
            "session_id": review.session_id,
            "recorded_at": utc_text(recorded_at),
            "supersedes_review_id": review.supersedes_review_id,
            "review": review.as_object(),
        }
        payload = seal_object(
            draft,
            id_field="memory_review_id",
            namespace=MEMORY_REVIEW_NAMESPACE,
        )
        return self.reviews.append(payload, identity_field="memory_review_id")

    def review_predecessor_id(self, *, session_id: str) -> str | None:
        matches = [
            _review_memory_payload(event["payload"])
            for event in self.reviews.read()
            if event["payload"].get("session_id") == session_id
        ]
        return str(matches[-1]["review"]["review_id"]) if matches else None

    def append_analysis(self, analysis: Mapping[str, object]) -> tuple[JsonObject, bool]:
        from optimatrix.ai_lab.codex_analysis import validate_analysis

        parsed = validate_analysis(analysis)
        review_ids = {payload["review"]["review_id"] for payload in self._current_review_payloads()}
        if parsed["review_id"] not in review_ids:
            raise ValidationError("Codex analysis requires a current Policy-quality review")
        for event in self.analyses.read():
            prior = validate_analysis(event["payload"])
            if prior["review_id"] == parsed["review_id"]:
                if prior != parsed:
                    raise ValidationError(
                        "one Policy-quality review already owns a different Codex analysis"
                    )
                return event, False
        return self.analyses.append(parsed, identity_field="analysis_id")

    def digest(self, *, before_session_id: str | None = None) -> MemoryDigest:
        all_review_payloads = tuple(
            _review_memory_payload(event["payload"]) for event in self.reviews.read()
        )
        reviews = tuple(
            payload
            for payload in self._current_review_payloads()
            if before_session_id is None or str(payload["session_id"]) < before_session_id
        )
        v1_review_count = sum(
            payload["review"].get("schema_version") == POLICY_QUALITY_V1_REVIEW_SCHEMA
            and (before_session_id is None or str(payload["session_id"]) < before_session_id)
            for payload in all_review_payloads
        )
        v2_review_count = sum(
            payload["review"].get("schema_version") == POLICY_QUALITY_V2_REVIEW_SCHEMA
            and (before_session_id is None or str(payload["session_id"]) < before_session_id)
            for payload in all_review_payloads
        )
        legacy_reviews = tuple(
            _legacy_review_memory_payload(event["payload"])
            for event in self.legacy_reviews.read()
            if before_session_id is None
            or str(event["payload"].get("session_id")) <= before_session_id
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
                    "captured_opportunity_window_count": review[
                        "captured_opportunity_window_count"
                    ],
                    "missed_opportunity_window_count": review["missed_opportunity_window_count"],
                    "over_risk_window_count": review["over_risk_window_count"],
                    "challenger_comparison_eligible": review["challenger_comparison_eligible"],
                }
            )
        for analysis in analyses:
            model_output = analysis.get("model_output")
            raw_hypotheses = (
                model_output.get("hypotheses") if isinstance(model_output, dict) else None
            )
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
            superseded_policy_quality_v1_review_count=v1_review_count,
            superseded_policy_quality_v2_review_count=v2_review_count,
            invalid_legacy_review_count=len(legacy_reviews),
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
        for payload in self._current_review_payloads():
            review = cast(JsonObject, payload["review"])
            if review.get("review_id") != identifier:
                continue
            if (
                review.get("verdict") != "RULE_WELL_CALIBRATED"
                or review.get("challenger_comparison_eligible") is not True
                or review.get("unknown_window_count") != 0
                or not isinstance(review.get("captured_opportunity_window_count"), int)
                or review["captured_opportunity_window_count"] <= 0
            ):
                raise ValidationError(
                    "Policy-quality review does not authorize Base-versus-Challenger comparison"
                )
            return review
        raise ValidationError("eligible Policy-quality review does not exist in AI Lab memory")

    def verify(self) -> JsonObject:
        reviews = self.reviews.read()
        legacy_reviews = self.legacy_reviews.read()
        analyses = self.analyses.read()
        events_by_session: dict[str, list[JsonObject]] = {}
        current_review_ids: set[str] = set()
        all_policy_quality_review_ids: set[str] = set()
        v1_review_count = 0
        v2_review_count = 0
        for event in reviews:
            payload = _review_memory_payload(event["payload"])
            session_id = str(payload["session_id"])
            events_by_session.setdefault(session_id, []).append(payload)
            review_id = str(payload["review"]["review_id"])
            all_policy_quality_review_ids.add(review_id)
            if payload["review"].get("schema_version") == POLICY_QUALITY_V1_REVIEW_SCHEMA:
                v1_review_count += 1
            if payload["review"].get("schema_version") == POLICY_QUALITY_V2_REVIEW_SCHEMA:
                v2_review_count += 1
        for _session_id, payloads in events_by_session.items():
            if len(payloads) > 3:
                raise ValidationError("AI Lab memory contains too many Reviews for one Session")
            schemas = [str(item["review"].get("schema_version")) for item in payloads]
            if len(set(schemas)) != len(schemas):
                raise ValidationError("AI Lab memory contains duplicate Review schema for Session")
            predecessor: str | None = None
            for index, payload in enumerate(payloads):
                schema = payload["review"].get("schema_version")
                if index == 0 and schema == POLICY_QUALITY_V1_REVIEW_SCHEMA:
                    predecessor = str(payload["review"]["review_id"])
                    continue
                if payload.get("supersedes_review_id") != predecessor:
                    raise ValidationError("memory Review has an invalid supersession link")
                if payload["review"].get("supersedes_review_id") != predecessor:
                    raise ValidationError("Policy-quality Review has an invalid supersession link")
                predecessor = str(payload["review"]["review_id"])
            terminal = payloads[-1]
            if terminal["review"].get("schema_version") != SESSION_REVIEW_SCHEMA:
                raise ValidationError("AI Lab Session has no terminal V3 Policy-quality review")
            current_review_ids.add(str(terminal["review"]["review_id"]))
        legacy_session_ids: set[str] = set()
        legacy_review_ids: set[str] = set()
        for event in legacy_reviews:
            payload = _legacy_review_memory_payload(event["payload"])
            session_id = str(payload["session_id"])
            if session_id in legacy_session_ids:
                raise ValidationError("AI Lab memory contains duplicate legacy Sessions")
            legacy_session_ids.add(session_id)
            legacy_review_ids.add(str(payload["review"]["review_id"]))
        all_review_ids = all_policy_quality_review_ids | legacy_review_ids
        analysis_review_ids: set[str] = set()
        legacy_analysis_count = 0
        for event in analyses:
            from optimatrix.ai_lab.codex_analysis import validate_analysis

            analysis = validate_analysis(event["payload"])
            review_id = str(analysis["review_id"])
            if review_id not in all_review_ids:
                raise ValidationError("AI Lab memory contains an orphan Codex analysis")
            if review_id in analysis_review_ids:
                raise ValidationError("AI Lab memory contains duplicate Codex analyses")
            analysis_review_ids.add(review_id)
            if review_id in legacy_review_ids:
                legacy_analysis_count += 1
        return {
            "status": "VALID_AI_LAB_MEMORY",
            "policy_quality_review_count": len(current_review_ids),
            "superseded_policy_quality_v1_review_count": v1_review_count,
            "superseded_policy_quality_v1_status": POLICY_QUALITY_V1_STATUS,
            "superseded_policy_quality_v2_review_count": v2_review_count,
            "superseded_policy_quality_v2_status": POLICY_QUALITY_V2_STATUS,
            "legacy_session_review_count": len(legacy_reviews),
            "legacy_policy_quality_status": LEGACY_POLICY_QUALITY_STATUS,
            "codex_analysis_count": len(analyses) - legacy_analysis_count,
            "legacy_codex_analysis_count": legacy_analysis_count,
        }

    def _current_review_payloads(self) -> tuple[JsonObject, ...]:
        terminal_by_session: dict[str, JsonObject] = {}
        for event in self.reviews.read():
            payload = _review_memory_payload(event["payload"])
            terminal_by_session[str(payload["session_id"])] = payload
        return tuple(
            payload
            for payload in terminal_by_session.values()
            if payload["review"].get("schema_version") == SESSION_REVIEW_SCHEMA
        )


def _review_memory_payload(value: object) -> JsonObject:
    if not isinstance(value, dict):
        raise ValidationError("memory_policy_quality_review must be an object")
    schema = value.get("schema_version")
    if schema == POLICY_QUALITY_V1_MEMORY_SCHEMA:
        item = strict_fields(
            value,
            {
                "schema_version",
                "memory_review_id",
                "session_id",
                "recorded_at",
                "review",
            },
            "memory_policy_quality_review_v1",
        )
        verify_seal(
            item,
            id_field="memory_review_id",
            namespace=POLICY_QUALITY_V1_MEMORY_NAMESPACE,
        )
        expected_review_schema = POLICY_QUALITY_V1_REVIEW_SCHEMA
        review_namespace = POLICY_QUALITY_V1_REVIEW_NAMESPACE
    elif schema in {POLICY_QUALITY_V2_MEMORY_SCHEMA, MEMORY_REVIEW_SCHEMA}:
        item = strict_fields(
            value,
            {
                "schema_version",
                "memory_review_id",
                "session_id",
                "recorded_at",
                "supersedes_review_id",
                "review",
            },
            "memory_policy_quality_review_with_supersession",
        )
        if schema == POLICY_QUALITY_V2_MEMORY_SCHEMA:
            verify_seal(
                item,
                id_field="memory_review_id",
                namespace=POLICY_QUALITY_V2_MEMORY_NAMESPACE,
            )
            expected_review_schema = POLICY_QUALITY_V2_REVIEW_SCHEMA
            review_namespace = POLICY_QUALITY_V2_REVIEW_NAMESPACE
        else:
            verify_seal(item, id_field="memory_review_id", namespace=MEMORY_REVIEW_NAMESPACE)
            expected_review_schema = SESSION_REVIEW_SCHEMA
            review_namespace = SESSION_REVIEW_NAMESPACE
    else:
        raise ValidationError("unsupported AI Lab Policy-quality memory schema")
    review = item["review"]
    if not isinstance(review, dict):
        raise ValidationError("memory review payload must contain one review object")
    if review.get("schema_version") != expected_review_schema:
        raise ValidationError("memory review contains an unsupported Policy-quality review")
    verify_seal(review, id_field="review_id", namespace=review_namespace)
    if item["session_id"] != review.get("session_id"):
        raise ValidationError("memory Session does not match its Policy-quality review")
    if schema in {POLICY_QUALITY_V2_MEMORY_SCHEMA, MEMORY_REVIEW_SCHEMA} and item[
        "supersedes_review_id"
    ] != review.get("supersedes_review_id"):
        raise ValidationError("memory supersession does not match its Policy-quality review")
    return item


def _legacy_review_memory_payload(value: object) -> JsonObject:
    item = strict_fields(
        value,
        {
            "schema_version",
            "memory_review_id",
            "session_id",
            "recorded_at",
            "review",
        },
        "legacy_memory_review",
    )
    if item["schema_version"] != LEGACY_MEMORY_REVIEW_SCHEMA:
        raise ValidationError("unsupported legacy AI Lab memory review schema")
    verify_seal(item, id_field="memory_review_id", namespace=LEGACY_MEMORY_REVIEW_NAMESPACE)
    review = item["review"]
    if not isinstance(review, dict):
        raise ValidationError("legacy memory review must contain one review object")
    if review.get("schema_version") != LEGACY_SESSION_REVIEW_SCHEMA:
        raise ValidationError("legacy memory contains an unsupported Session review")
    verify_seal(review, id_field="review_id", namespace=LEGACY_SESSION_REVIEW_NAMESPACE)
    if item["session_id"] != review.get("session_id"):
        raise ValidationError("legacy memory Session does not match its review")
    return item
