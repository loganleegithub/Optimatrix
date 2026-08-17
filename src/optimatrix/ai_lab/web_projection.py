from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from optimatrix.ai_lab.canonical import (
    AI_LAB_DURABLE_ROOT,
    JsonObject,
    ValidationError,
    canonical_bytes,
    isolated_path,
    parse_utc,
    require_bool,
    require_content_id,
    require_int,
    require_text,
    seal_object,
    strict_fields,
    utc_text,
    verify_seal,
)
from optimatrix.ai_lab.memory import AiLabMemoryStore

WORKBENCH_REVIEW_SCHEMA = "optimatrix.ai-lab.workbench-review-projection.v1"
WORKBENCH_REVIEW_NAMESPACE = "OptimatrixAiLabWorkbenchReviewProjectionV1"
WORKBENCH_REVIEW_FILENAME = "workbench-review-projection.json"
WORKBENCH_REVIEW_LIMIT = 32

DAILY_STATE_SCHEMA = "optimatrix.ai-lab.daily-review-state.v1"
DAILY_STATE_FILENAME = "daily-review-state.json"
DAILY_STATUSES = frozenset({"RUNNING", "NOT_READY", "SUCCEEDED", "FAILED"})


def write_daily_state(
    *,
    root: Path,
    status: str,
    updated_at: object,
    target_session_id: str | None,
    detail: str,
    review_id: str | None = None,
) -> JsonObject:
    if status not in DAILY_STATUSES:
        raise ValidationError("unsupported daily Review status")
    if not isinstance(updated_at, str):
        updated_at = utc_text(updated_at)  # type: ignore[arg-type]
    parse_utc(updated_at, "daily_review_state.updated_at")
    if target_session_id is not None:
        parse_utc(target_session_id, "daily_review_state.target_session_id")
    if review_id is not None:
        require_content_id(review_id, "daily_review_state.review_id")
    if not detail:
        raise ValidationError("daily Review state requires a detail")

    try:
        prior = _read_daily_state(root)
    except (OSError, ValueError):
        prior = _default_daily_state()
    last_success_at = prior.get("last_success_at")
    last_success_session_id = prior.get("last_success_session_id")
    last_success_review_id = prior.get("last_success_review_id")
    if status == "SUCCEEDED":
        if target_session_id is None or review_id is None:
            raise ValidationError("successful daily Review state requires Session and Review")
        last_success_at = updated_at
        last_success_session_id = target_session_id
        last_success_review_id = review_id
    state: JsonObject = {
        "schema_version": DAILY_STATE_SCHEMA,
        "status": status,
        "updated_at": updated_at,
        "target_session_id": target_session_id,
        "detail": detail[:500],
        "review_id": review_id,
        "last_success_at": last_success_at,
        "last_success_session_id": last_success_session_id,
        "last_success_review_id": last_success_review_id,
    }
    _validate_daily_state(state)
    _atomic_json(isolated_path(root) / DAILY_STATE_FILENAME, state)
    return state


def write_workbench_review_projection(
    *,
    memory: AiLabMemoryStore,
    generated_at: object,
    root: Path = AI_LAB_DURABLE_ROOT,
) -> JsonObject:
    if not isinstance(generated_at, str):
        generated_at = utc_text(generated_at)  # type: ignore[arg-type]
    parse_utc(generated_at, "workbench_review_projection.generated_at")
    entries = sorted(
        memory.current_review_entries(),
        key=lambda payload: str(payload["session_id"]),
        reverse=True,
    )[:WORKBENCH_REVIEW_LIMIT]
    draft: JsonObject = {
        "schema_version": WORKBENCH_REVIEW_SCHEMA,
        "generated_at": generated_at,
        "automation": _daily_state_for_projection(root=root, generated_at=generated_at),
        "reviews": [_project_review(payload) for payload in entries],
        "retained_review_count": len(memory.current_review_entries()),
        "display_limit": WORKBENCH_REVIEW_LIMIT,
        "boundary": (
            "Derived read-only presentation. Immutable Review memory and content-addressed reports "
            "remain the source of truth. Missing data stays UNKNOWN; this projection grants no "
            "Policy, promotion, execution, account, order, fill, or capital permission."
        ),
    }
    projection = seal_object(
        draft,
        id_field="projection_id",
        namespace=WORKBENCH_REVIEW_NAMESPACE,
    )
    _validate_workbench_review_projection(projection)
    _atomic_json(isolated_path(root) / WORKBENCH_REVIEW_FILENAME, projection)
    return projection


def read_workbench_review_projection(
    *,
    root: Path = AI_LAB_DURABLE_ROOT,
) -> JsonObject:
    path = isolated_path(root) / WORKBENCH_REVIEW_FILENAME
    if not path.exists():
        raise ValidationError("AI Lab Workbench Review projection does not exist")
    if path.is_symlink() or not path.is_file():
        raise ValidationError("AI Lab Workbench Review projection must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read Workbench Review projection: {exc}") from exc
    return _validate_workbench_review_projection(value)


class WorkbenchReviewProjectionReader:
    """Cache one derived Lab projection without letting presentation stop the Runtime."""

    def __init__(self, root: Path = AI_LAB_DURABLE_ROOT) -> None:
        self.root = isolated_path(root)
        self.path = self.root / WORKBENCH_REVIEW_FILENAME
        self._signature: tuple[int, int, int] | None = None
        self._result: JsonObject | None = None

    def read(self) -> JsonObject:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return {
                "status": "NOT_YET_AVAILABLE",
                "reason": "NO_DAILY_SESSION_REVIEW_PROJECTION",
                "projection": None,
            }
        except OSError:
            return {
                "status": "UNAVAILABLE",
                "reason": "AI_LAB_REVIEW_PROJECTION_STAT_FAILED",
                "projection": None,
            }
        signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        if signature == self._signature and self._result is not None:
            return self._result
        try:
            projection = read_workbench_review_projection(root=self.root)
        except (OSError, ValueError):
            result: JsonObject = {
                "status": "UNAVAILABLE",
                "reason": "AI_LAB_REVIEW_PROJECTION_INVALID",
                "projection": None,
            }
        else:
            result = {"status": "AVAILABLE", "reason": None, "projection": projection}
        self._signature = signature
        self._result = result
        return result


def _project_review(payload: Mapping[str, object]) -> JsonObject:
    review = payload.get("review")
    if not isinstance(review, dict):
        raise ValidationError("current Review memory lacks one Review object")
    windows = review.get("windows")
    curve = review.get("curve")
    if not isinstance(windows, list) or not isinstance(curve, list):
        raise ValidationError("current Review has malformed Window or curve population")
    official = review.get("official_index_evidence")
    official_projection: JsonObject | None = None
    if official is not None:
        if not isinstance(official, dict):
            raise ValidationError("current Review official evidence must be an object or null")
        gaps = official.get("coverage_gaps")
        if not isinstance(gaps, list):
            raise ValidationError("current Review official evidence gaps must be an array")
        official_projection = {
            "evidence_id": official.get("evidence_id"),
            "point_count": official.get("point_count"),
            "cadence_ms": official.get("cadence_ms"),
            "session_coverage_complete": official.get("session_coverage_complete"),
            "coverage_gaps": gaps,
            "boundary": official.get("boundary"),
        }
    return {
        "review_id": review.get("review_id"),
        "session_id": review.get("session_id"),
        "recorded_at": payload.get("recorded_at"),
        "policy_id": review.get("policy_id"),
        "opportunity_definition_id": review.get("opportunity_definition_id"),
        "verdict": review.get("verdict"),
        "verdict_reason": review.get("verdict_reason"),
        "challenger_comparison_eligible": review.get("challenger_comparison_eligible"),
        "population": {
            key: review.get(key)
            for key in (
                "expected_window_count",
                "recorded_decision_count",
                "recorded_outcome_count",
                "curve_observation_count",
                "auditable_window_count",
                "unknown_window_count",
            )
        },
        "bounds": {
            key: review.get(key)
            for key in (
                "coverage_fraction",
                "miss_rate_lower_bound",
                "miss_rate_upper_bound",
                "over_risk_rate_lower_bound",
                "over_risk_rate_upper_bound",
                "opportunity_rate_lower_bound",
                "opportunity_rate_upper_bound",
            )
        },
        "classifications": {
            key: review.get(key)
            for key in (
                "base_candidate_window_count",
                "captured_opportunity_window_count",
                "correct_avoidance_window_count",
                "missed_opportunity_window_count",
                "over_risk_window_count",
                "unknown_window_count",
            )
        },
        "funnel": {
            key: review.get(key)
            for key in (
                "legal_structure_count",
                "price_evaluable_count",
                "control_candidate_count",
                "hindsight_opportunity_structure_count",
                "hindsight_positive_policy_reject_structure_count",
            )
        },
        "evidence_reason_counts": review.get("evidence_reason_counts"),
        "base_blocker_counts": review.get("base_blocker_counts"),
        "official_index_evidence": official_projection,
        "curve": [
            {
                "decision_window_id": point.get("decision_window_id"),
                "starts_at": point.get("starts_at"),
                "index_price_usd": point.get("index_price_usd"),
                "implied_variance_proxy": point.get("implied_variance_proxy"),
                "trailing_realized_variance_proxy": point.get("trailing_realized_variance_proxy"),
                "ex_ante_vrp_proxy_ratio": point.get("ex_ante_vrp_proxy_ratio"),
            }
            for point in windows_or_curve(curve, "curve")
        ],
        "windows": [
            {
                key: window.get(key)
                for key in (
                    "decision_window_id",
                    "starts_at",
                    "base_result",
                    "base_blockers",
                    "evidence_status",
                    "evidence_reasons",
                    "classification",
                    "legal_structure_count",
                    "price_evaluable_count",
                    "control_candidate_count",
                    "hindsight_opportunity_count",
                    "hindsight_positive_policy_reject_count",
                    "control_rejection_counts",
                    "hindsight_rejection_counts",
                    "best_control_result_btc",
                    "best_control_result_usd",
                    "entry_implied_variance_proxy",
                    "hindsight_rv_source",
                    "hindsight_realized_variance_proxy",
                    "selected_candidate_hindsight_reasons",
                )
            }
            for window in windows_or_curve(windows, "windows")
        ],
        "evidence_boundary": review.get("evidence_boundary"),
    }


def windows_or_curve(values: list[object], field: str) -> list[Mapping[str, object]]:
    if not all(isinstance(value, dict) for value in values):
        raise ValidationError(f"current Review {field} must contain objects")
    return values  # type: ignore[return-value]


def _read_daily_state(root: Path) -> JsonObject:
    path = isolated_path(root) / DAILY_STATE_FILENAME
    if not path.exists():
        return _default_daily_state()
    if path.is_symlink() or not path.is_file():
        raise ValidationError("daily Review state must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read daily Review state: {exc}") from exc
    return _validate_daily_state(value)


def _default_daily_state() -> JsonObject:
    return {
        "schema_version": DAILY_STATE_SCHEMA,
        "status": "NOT_READY",
        "updated_at": None,
        "target_session_id": None,
        "detail": "DAILY_REVIEW_HAS_NOT_RUN",
        "review_id": None,
        "last_success_at": None,
        "last_success_session_id": None,
        "last_success_review_id": None,
    }


def _daily_state_for_projection(*, root: Path, generated_at: str) -> JsonObject:
    try:
        return _read_daily_state(root)
    except (OSError, ValueError):
        state = _default_daily_state()
        state.update(
            {
                "status": "FAILED",
                "updated_at": generated_at,
                "detail": "DAILY_REVIEW_STATE_INVALID",
            }
        )
        return _validate_daily_state(state)


def _validate_daily_state(value: object) -> JsonObject:
    item = strict_fields(
        value,
        {
            "schema_version",
            "status",
            "updated_at",
            "target_session_id",
            "detail",
            "review_id",
            "last_success_at",
            "last_success_session_id",
            "last_success_review_id",
        },
        "daily_review_state",
    )
    if item["schema_version"] != DAILY_STATE_SCHEMA or item["status"] not in DAILY_STATUSES:
        raise ValidationError("unsupported daily Review state")
    require_text(item["detail"], "daily_review_state.detail")
    for field in ("updated_at", "target_session_id", "last_success_at", "last_success_session_id"):
        if item[field] is not None:
            parse_utc(item[field], f"daily_review_state.{field}")
    for field in ("review_id", "last_success_review_id"):
        if item[field] is not None:
            require_content_id(item[field], f"daily_review_state.{field}")
    return item


def _validate_workbench_review_projection(value: object) -> JsonObject:
    item = strict_fields(
        value,
        {
            "schema_version",
            "projection_id",
            "generated_at",
            "automation",
            "reviews",
            "retained_review_count",
            "display_limit",
            "boundary",
        },
        "workbench_review_projection",
    )
    if item["schema_version"] != WORKBENCH_REVIEW_SCHEMA:
        raise ValidationError("unsupported Workbench Review projection schema")
    verify_seal(item, id_field="projection_id", namespace=WORKBENCH_REVIEW_NAMESPACE)
    parse_utc(item["generated_at"], "workbench_review_projection.generated_at")
    _validate_daily_state(item["automation"])
    require_text(item["boundary"], "workbench_review_projection.boundary")
    retained = require_int(item["retained_review_count"], "retained_review_count")
    display_limit = require_int(item["display_limit"], "display_limit", minimum=1)
    reviews = item["reviews"]
    if not isinstance(reviews, list) or len(reviews) > display_limit or retained < len(reviews):
        raise ValidationError("Workbench Review projection population is invalid")
    seen_sessions: set[str] = set()
    for index, raw_review in enumerate(reviews):
        review = strict_fields(
            raw_review,
            {
                "review_id",
                "session_id",
                "recorded_at",
                "policy_id",
                "opportunity_definition_id",
                "verdict",
                "verdict_reason",
                "challenger_comparison_eligible",
                "population",
                "bounds",
                "classifications",
                "funnel",
                "evidence_reason_counts",
                "base_blocker_counts",
                "official_index_evidence",
                "curve",
                "windows",
                "evidence_boundary",
            },
            f"workbench_review_projection.reviews[{index}]",
        )
        require_content_id(review["review_id"], "review_id")
        session_id = require_text(review["session_id"], "session_id")
        parse_utc(session_id, "session_id")
        parse_utc(review["recorded_at"], "recorded_at")
        require_bool(review["challenger_comparison_eligible"], "challenger_eligible")
        require_text(review["verdict"], "verdict")
        require_text(review["verdict_reason"], "verdict_reason")
        require_text(review["evidence_boundary"], "evidence_boundary")
        if session_id in seen_sessions:
            raise ValidationError("Workbench Review projection contains duplicate Sessions")
        seen_sessions.add(session_id)
        for field in ("population", "bounds", "classifications", "funnel"):
            if not isinstance(review[field], dict):
                raise ValidationError(f"projected Review {field} must be an object")
        for field in ("curve", "windows"):
            if not isinstance(review[field], list):
                raise ValidationError(f"projected Review {field} must be an array")
    return item


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValidationError(f"refusing to replace symlink: {path}")
    temporary = path.with_name(f".{path.name}.optimatrix-tmp")
    if temporary.is_symlink():
        raise ValidationError(f"temporary projection path is a symlink: {temporary}")
    with temporary.open("wb") as handle:
        handle.write(canonical_bytes(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
