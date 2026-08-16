from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from optimatrix.ai_lab.canonical import (
    JsonObject,
    ValidationError,
    decimal_text,
    require_int,
    seal_object,
    utc_text,
)
from optimatrix.ai_lab.memory import AiLabMemoryStore
from optimatrix.ai_lab.models import (
    DecisionResult,
    DecisionWindowExport,
    EvaluationFold,
    ExperimentPlan,
    ExportedWindow,
    FrozenSpec,
    FullFuturePath,
    MissingFuturePath,
    PathActuality,
    SummaryFuturePath,
)
from optimatrix.ai_lab.registration import ExperimentRegistration, registration_reference
from optimatrix.ai_lab.store import AuditStore

MANIFEST_SCHEMA = "optimatrix.ai-lab.experiment-manifest.v3"
RESULT_SCHEMA = "optimatrix.ai-lab.experiment-result.v1"
MANIFEST_NAMESPACE = "OptimatrixAiLabExperimentManifestV1"
RESULT_NAMESPACE = "OptimatrixAiLabExperimentResultV1"

UNAVAILABLE_STRATEGY_METRICS = (
    "UNFILTERED_CONDOR_COMPARATOR",
    "NO_TRADE_ECONOMIC_BASELINE",
    "TAIL_LOSS",
    "EXPECTED_SHORTFALL_CVAR",
    "WORST_SESSION",
    "STRATEGY_DRAWDOWN",
    "CONTRACTUAL_CAP_BREACH_RATE",
    "DECLARED_SCENARIO_LOSS_RATE",
    "FEE_AFTER_ECONOMICS",
    "MISSED_PROFIT",
    "REGIME_STABILITY",
    "POLICY_QUALIFICATION",
)


@dataclass(frozen=True)
class PathDiagnostics:
    terminal_index_change_bps: Decimal
    minimum_index_change_bps: Decimal
    maximum_index_change_bps: Decimal
    maximum_absolute_index_move_bps: Decimal
    observation_count: int

    def as_object(self) -> JsonObject:
        return {
            "terminal_index_change_bps": decimal_text(self.terminal_index_change_bps),
            "minimum_index_change_bps": decimal_text(self.minimum_index_change_bps),
            "maximum_index_change_bps": decimal_text(self.maximum_index_change_bps),
            "maximum_absolute_index_move_bps": decimal_text(self.maximum_absolute_index_move_bps),
            "observation_count": self.observation_count,
        }


class FuturePathEvaluator(Protocol):
    evaluator_id: str
    evidence_scope: str
    qualification_capable: bool

    def evaluate(self, path: FullFuturePath) -> PathDiagnostics: ...


class IndexPathDiagnosticsEvaluator:
    """Path-only diagnostics; deliberately not an options economics evaluator."""

    evaluator_id = "INDEX_PATH_DIAGNOSTICS_V1"
    evidence_scope = "PATH_DIAGNOSTICS_ONLY"
    qualification_capable = False

    def evaluate(self, path: FullFuturePath) -> PathDiagnostics:
        start = path.points[0].index_price_usd
        changes = tuple(
            (point.index_price_usd / start - Decimal(1)) * Decimal(10_000) for point in path.points
        )
        terminal = changes[-1]
        minimum = min(changes)
        maximum = max(changes)
        return PathDiagnostics(
            terminal_index_change_bps=terminal,
            minimum_index_change_bps=minimum,
            maximum_index_change_bps=maximum,
            maximum_absolute_index_move_bps=max(abs(minimum), abs(maximum)),
            observation_count=len(path.points),
        )


class ExperimentRunner:
    def __init__(
        self,
        *,
        evaluator: FuturePathEvaluator | None = None,
    ) -> None:
        self.evaluator = evaluator or IndexPathDiagnosticsEvaluator()

    def run(
        self,
        *,
        base: FrozenSpec,
        challenger: FrozenSpec,
        dataset: DecisionWindowExport,
        plan: ExperimentPlan,
        store: AuditStore,
        registration_id: str,
        recorded_at: datetime,
        memory: AiLabMemoryStore | None = None,
        session_review_ids: tuple[str, ...] = (),
    ) -> JsonObject:
        if plan.evaluator_id != self.evaluator.evaluator_id:
            raise ValidationError("experiment plan names an unavailable evaluator")
        if recorded_at.tzinfo is None:
            raise ValidationError("experiment recorded_at must be timezone-aware UTC")
        if recorded_at < dataset.exported_at:
            raise ValidationError("experiment cannot be recorded before its export exists")
        dataset.validate_specs(base, challenger)
        plan.validate_specs(base, challenger)
        registration, registration_event = store.require_registration(
            registration_id=registration_id,
            base=base,
            challenger=challenger,
            plan=plan,
        )
        if registration.recorded_at > recorded_at:
            raise ValidationError("experiment manifest cannot predate its local registration")
        assigned_members: list[tuple[ExportedWindow, EvaluationFold]] = []
        for window in dataset.windows:
            fold = plan.fold_for(window)
            if fold is not None:
                assigned_members.append((window, fold))
        assigned = tuple(assigned_members)
        if not assigned:
            raise ValidationError("experiment plan selects no exported DecisionWindows")

        eligibility_reviews: tuple[JsonObject, ...] = ()
        if _contains_actual_public_path(dataset):
            if memory is None or not session_review_ids:
                raise ValidationError(
                    "actual-path Challenger experiment requires an eligible Session review"
                )
            eligibility_reviews = tuple(
                memory.require_challenger_eligible(review_id) for review_id in session_review_ids
            )
            _validate_session_first_coverage(
                reviews=eligibility_reviews,
                dataset=dataset,
                base=base,
            )

        manifest = self._manifest(
            base=base,
            challenger=challenger,
            dataset=dataset,
            plan=plan,
            registration=registration,
            registration_event=registration_event,
            recorded_at=recorded_at,
            selected_window_count=len(assigned),
            eligibility_reviews=eligibility_reviews,
        )
        store.append_manifest(manifest)
        result = self._result(
            manifest=manifest,
            assigned=assigned,
            plan=plan,
            recorded_at=recorded_at,
        )
        store.append_result(result)
        return result

    def _manifest(
        self,
        *,
        base: FrozenSpec,
        challenger: FrozenSpec,
        dataset: DecisionWindowExport,
        plan: ExperimentPlan,
        registration: ExperimentRegistration,
        registration_event: Mapping[str, object],
        recorded_at: datetime,
        selected_window_count: int,
        eligibility_reviews: tuple[Mapping[str, object], ...],
    ) -> JsonObject:
        draft: JsonObject = {
            "schema_version": MANIFEST_SCHEMA,
            "recorded_at": utc_text(recorded_at),
            "registration": registration_reference(
                registration,
                event_id=str(registration_event["event_id"]),
                event_sequence=require_int(
                    registration_event["sequence"],
                    "registration_event.sequence",
                    minimum=1,
                ),
            ),
            "input": {
                "schema_version": "optimatrix.ai-lab.decision-window-export.v1",
                "export_id": dataset.export_id,
                "exported_at": utc_text(dataset.exported_at),
                "producer_id": dataset.producer_id,
                "source_repository_commit": dataset.source_repository_commit,
                "source_contracts": list(dataset.source_contracts),
                "selected_window_count": selected_window_count,
            },
            "session_first_gates": (
                [
                    {
                        "review_id": review["review_id"],
                        "session_id": review["session_id"],
                        "verdict": review["verdict"],
                        "challenger_comparison_eligible": review["challenger_comparison_eligible"],
                        "auditable_window_count": review["auditable_window_count"],
                        "expected_window_count": review["expected_window_count"],
                    }
                    for review in eligibility_reviews
                ]
                if eligibility_reviews
                else [
                    {
                        "review_id": None,
                        "status": "SYNTHETIC_MECHANISM_ONLY_NO_SESSION_GATE_CLAIM",
                    }
                ]
            ),
            "specs": {
                "base": _spec_reference(base),
                "challenger": _spec_reference(challenger),
            },
            "split": {
                "plan_id": plan.plan_id,
                "mode": plan.mode.value,
                "declared_registered_at": utc_text(plan.registered_at),
                "folds": [
                    {
                        "fold_id": fold.fold_id,
                        "training_ends_at": utc_text(fold.training_ends_at),
                        "evaluation_starts_at": utc_text(fold.evaluation_starts_at),
                        "evaluation_ends_at": utc_text(fold.evaluation_ends_at),
                    }
                    for fold in plan.folds
                ],
            },
            "evaluation": {
                "evaluator_id": self.evaluator.evaluator_id,
                "evidence_scope": self.evaluator.evidence_scope,
                "metric_ids": list(plan.metric_ids),
                "full_path_required_for_reevaluation": True,
            },
            "promotion_gate": {
                "min_comparable_windows": plan.promotion_gate.min_comparable_windows,
                "max_incomparable_fraction": decimal_text(
                    plan.promotion_gate.max_incomparable_fraction
                ),
                "require_actual_paths": plan.promotion_gate.require_actual_paths,
                "candidate_count_is_gate": False,
                "trade_frequency_is_gate": False,
                "automatic_promotion": "FORBIDDEN",
            },
            "non_claims": [
                "OFFLINE_RESEARCH_ONLY",
                "NO_PRODUCTION_POLICY_ACTIVATION",
                "NO_POLICY_MUTATION_OR_AUTOMATIC_PROMOTION",
                "NO_ORDER_FILL_CAPITAL_OR_EXECUTION_CLAIM",
                "PATH_DIAGNOSTICS_ARE_NOT_EDGE_OR_STRATEGY_ECONOMICS",
                "SYNTHETIC_FIXTURES_PROVE_MECHANISM_ONLY",
                "B3_NATURAL_FORWARD_CHAIN_REMAINS_UNVERIFIED",
                "REGISTRATION_PROVES_ONLY_SAME_STORE_APPEND_ORDER",
                "NO_EXTERNAL_TRUSTED_TIMESTAMP_OR_IMMUTABLE_MEDIA_ATTESTATION",
            ],
        }
        return seal_object(draft, id_field="experiment_id", namespace=MANIFEST_NAMESPACE)

    def _result(
        self,
        *,
        manifest: Mapping[str, object],
        assigned: tuple[tuple[ExportedWindow, EvaluationFold], ...],
        plan: ExperimentPlan,
        recorded_at: datetime,
    ) -> JsonObject:
        comparable_rows: list[JsonObject] = []
        incomparable_rows: list[JsonObject] = []
        path_counts: Counter[str] = Counter()
        for window, fold in assigned:
            path = window.future_path
            path_counts[path.kind.value] += 1
            if isinstance(path, MissingFuturePath):
                incomparable_rows.append(
                    _incomparable(window, fold.fold_id, "FUTURE_PATH_MISSING", path.reason)
                )
                continue
            path_counts[path.actuality.value] += 1
            if isinstance(path, SummaryFuturePath):
                incomparable_rows.append(
                    _incomparable(
                        window,
                        fold.fold_id,
                        "FUTURE_PATH_SUMMARY_ONLY",
                        "SUMMARY_CANNOT_REEVALUATE_PATH_DEPENDENT_CHALLENGER",
                    )
                )
                continue
            if not path.continuous:
                incomparable_rows.append(
                    _incomparable(
                        window,
                        fold.fold_id,
                        "FUTURE_PATH_DISCONTINUOUS",
                        "CONTINUOUS_PATH_REQUIRED",
                    )
                )
                continue
            diagnostics = self.evaluator.evaluate(path)
            comparable_rows.append(
                {
                    "decision_window_id": window.decision_window_id,
                    "fold_id": fold.fold_id,
                    "market_session_id": window.market_session_id,
                    "base_result": window.base_decision.result.value,
                    "challenger_result": window.challenger_decision.result.value,
                    "future_path_actuality": path.actuality.value,
                    "future_path_source_id": path.source_id,
                    "future_path_method_id": path.method_id,
                    "future_path_starts_at": utc_text(path.starts_at),
                    "future_path_ends_at": utc_text(path.ends_at),
                    "path_diagnostics": diagnostics.as_object(),
                }
            )

        total = len(assigned)
        comparable = len(comparable_rows)
        incomparable = len(incomparable_rows)
        reason_counts = Counter(row["reason_code"] for row in incomparable_rows)
        actual_comparable = sum(
            row["future_path_actuality"] == PathActuality.ACTUAL_PUBLIC_PATH
            for row in comparable_rows
        )
        if not comparable_rows:
            evidence_scope = "NO_REEVALUATABLE_FULL_PATH"
        elif actual_comparable == comparable:
            evidence_scope = "EXPORTED_ACTUAL_PATH_DIAGNOSTICS_ONLY"
        else:
            evidence_scope = "SYNTHETIC_MECHANISM_ONLY"
        metric_results = self._metrics(plan.metric_ids, comparable_rows, total)
        unavailable = [
            {
                "metric_id": metric_id,
                "status": "UNAVAILABLE",
                "reason": "STRATEGY_VALUATION_INTERFACE_UNVERIFIED",
                "claim_scope": "NO_EDGE_OR_POLICY_QUALIFICATION",
            }
            for metric_id in UNAVAILABLE_STRATEGY_METRICS
        ]
        promotion = self._promotion_gate(
            plan=plan,
            total=total,
            comparable=comparable,
            actual_comparable=actual_comparable,
        )
        status = (
            "NO_COMPARABLE_WINDOWS"
            if comparable == 0
            else "PARTIAL_INCOMPARABLE"
            if incomparable
            else "COMPLETE_WITH_ECONOMIC_EVIDENCE_UNVERIFIED"
        )
        draft: JsonObject = {
            "schema_version": RESULT_SCHEMA,
            "experiment_id": manifest["experiment_id"],
            "recorded_at": utc_text(recorded_at),
            "status": status,
            "evidence_scope": evidence_scope,
            "comparison_population": {
                "decision_windows": total,
                "comparable_windows": comparable,
                "incomparable_windows": incomparable,
                "known_no_trade_base_windows": _known_no_trade_count(
                    comparable_rows, "base_result"
                ),
                "known_no_trade_challenger_windows": _known_no_trade_count(
                    comparable_rows, "challenger_result"
                ),
                "base_unknown_windows": sum(
                    row["base_result"] == DecisionResult.UNKNOWN for row in comparable_rows
                ),
                "challenger_unknown_windows": sum(
                    row["challenger_result"] == DecisionResult.UNKNOWN for row in comparable_rows
                ),
                "no_trade_windows_are_comparable": True,
            },
            "path_population": dict(sorted(path_counts.items())),
            "incomparable_reason_counts": dict(sorted(reason_counts.items())),
            "incomparable_windows": incomparable_rows,
            "comparable_windows": comparable_rows,
            "metrics": metric_results,
            "unavailable_strategy_metrics": unavailable,
            "promotion_gate": promotion,
            "claim_boundary": {
                "market_edge": "UNVERIFIED",
                "production_maturity": "UNCHANGED",
                "b3_natural_forward_chain": "UNVERIFIED",
                "synthetic_fixture_scope": "MECHANISM_ONLY",
                "candidate_rate_interpretation": "DESCRIPTIVE_ONLY_NOT_A_PROMOTION_GATE",
                "registration_assurance": "SAME_STORE_APPEND_ORDER_ONLY",
            },
        }
        return seal_object(draft, id_field="result_id", namespace=RESULT_NAMESPACE)

    def _metrics(
        self,
        requested: tuple[str, ...],
        rows: list[JsonObject],
        total: int,
    ) -> list[JsonObject]:
        count = len(rows)
        supported: dict[str, tuple[Decimal | int | None, str, str | None]] = {
            "COMPARABLE_WINDOW_COVERAGE": (
                Decimal(count) / Decimal(total),
                "fraction",
                None,
            )
        }
        if count:
            supported.update(
                {
                    "DECISION_AGREEMENT_RATE": (
                        Decimal(sum(row["base_result"] == row["challenger_result"] for row in rows))
                        / Decimal(count),
                        "fraction",
                        None,
                    ),
                    "BASE_CANDIDATE_RATE": (
                        Decimal(sum(row["base_result"] == DecisionResult.CANDIDATE for row in rows))
                        / Decimal(count),
                        "fraction",
                        None,
                    ),
                    "CHALLENGER_CANDIDATE_RATE": (
                        Decimal(
                            sum(
                                row["challenger_result"] == DecisionResult.CANDIDATE for row in rows
                            )
                        )
                        / Decimal(count),
                        "fraction",
                        None,
                    ),
                    "CANDIDATE_COUNT_DELTA": (
                        sum(row["challenger_result"] == DecisionResult.CANDIDATE for row in rows)
                        - sum(row["base_result"] == DecisionResult.CANDIDATE for row in rows),
                        "windows",
                        None,
                    ),
                    "NO_TRADE_AGREEMENT_COUNT": (
                        sum(
                            row["base_result"] in {DecisionResult.ABSTAIN, DecisionResult.REVIEW}
                            and row["challenger_result"]
                            in {DecisionResult.ABSTAIN, DecisionResult.REVIEW}
                            for row in rows
                        ),
                        "windows",
                        None,
                    ),
                }
            )
        output: list[JsonObject] = []
        for metric_id in requested:
            if metric_id == "BASE_SELECTED_MEAN_TERMINAL_INDEX_CHANGE_BPS":
                base_value = _selected_path_mean(rows, "base_result")
                output.append(_metric(metric_id, base_value, "bps", "NO_SELECTED_BASE_WINDOWS"))
            elif metric_id == "CHALLENGER_SELECTED_MEAN_TERMINAL_INDEX_CHANGE_BPS":
                challenger_value = _selected_path_mean(rows, "challenger_result")
                output.append(
                    _metric(
                        metric_id,
                        challenger_value,
                        "bps",
                        "NO_SELECTED_CHALLENGER_WINDOWS",
                    )
                )
            elif metric_id in supported:
                supported_value, unit, reason = supported[metric_id]
                output.append(_metric(metric_id, supported_value, unit, reason))
            else:
                output.append(_metric(metric_id, None, "unknown", "METRIC_NOT_IMPLEMENTED"))
        return output

    def _promotion_gate(
        self,
        *,
        plan: ExperimentPlan,
        total: int,
        comparable: int,
        actual_comparable: int,
    ) -> JsonObject:
        fraction = Decimal(total - comparable) / Decimal(total)
        reasons: list[str] = []
        if comparable < plan.promotion_gate.min_comparable_windows:
            reasons.append("MINIMUM_COMPARABLE_WINDOWS_NOT_MET")
        if fraction > plan.promotion_gate.max_incomparable_fraction:
            reasons.append("MAXIMUM_INCOMPARABLE_FRACTION_EXCEEDED")
        if plan.promotion_gate.require_actual_paths and actual_comparable != comparable:
            reasons.append("ACTUAL_FULL_PATH_REQUIREMENT_NOT_MET")
        if not self.evaluator.qualification_capable:
            reasons.append("STRATEGY_QUALIFICATION_EVALUATOR_UNVERIFIED")
        return {
            "automatic_promotion": "DENIED_FAIL_CLOSED",
            "human_review_status": "NOT_ELIGIBLE" if reasons else "ELIGIBLE_FOR_HUMAN_REVIEW",
            "reasons": reasons,
            "incomparable_fraction": decimal_text(fraction),
            "candidate_count_used": False,
            "trade_frequency_used": False,
            "required_next_action": "SEPARATE_HUMAN_AUTHORITY_TASK" if not reasons else None,
        }


def _contains_actual_public_path(dataset: DecisionWindowExport) -> bool:
    return any(
        isinstance(window.future_path, (FullFuturePath, SummaryFuturePath))
        and window.future_path.actuality is PathActuality.ACTUAL_PUBLIC_PATH
        for window in dataset.windows
    )


def _validate_session_first_coverage(
    *,
    reviews: tuple[Mapping[str, object], ...],
    dataset: DecisionWindowExport,
    base: FrozenSpec,
) -> None:
    if len({review.get("review_id") for review in reviews}) != len(reviews):
        raise ValidationError("Challenger experiment Session reviews must be unique")
    if any(review.get("policy_id") != base.external_policy_id for review in reviews):
        raise ValidationError("Base Policy does not match an eligible Session review")
    covered_window_ids: set[str] = set()
    for review in reviews:
        windows = review.get("windows")
        if not isinstance(windows, list):
            raise ValidationError("eligible Session review has a malformed Window population")
        for window in windows:
            if not isinstance(window, dict) or not isinstance(
                window.get("decision_window_id"), str
            ):
                raise ValidationError("eligible Session review contains a malformed Window")
            covered_window_ids.add(window["decision_window_id"])
    dataset_window_ids = {window.decision_window_id for window in dataset.windows}
    missing = dataset_window_ids - covered_window_ids
    if missing:
        raise ValidationError(
            "actual-path Challenger dataset contains Windows without an eligible Session review"
        )


def _spec_reference(spec: FrozenSpec) -> JsonObject:
    return {
        "spec_id": spec.spec_id,
        "role": spec.role.value,
        "version": spec.version,
        "name": spec.name,
        "declared_frozen_at": utc_text(spec.frozen_at),
        "trained_through": utc_text(spec.trained_through),
        "external_policy_id": spec.external_policy_id,
        "implementation_id": spec.implementation_id,
        "limitations": list(spec.limitations),
    }


def _incomparable(
    window: ExportedWindow,
    fold_id: str,
    reason_code: str,
    detail: str,
) -> JsonObject:
    return {
        "decision_window_id": window.decision_window_id,
        "fold_id": fold_id,
        "base_result": window.base_decision.result.value,
        "challenger_result": window.challenger_decision.result.value,
        "reason_code": reason_code,
        "detail": detail,
    }


def _known_no_trade_count(rows: list[JsonObject], field: str) -> int:
    return sum(row[field] in {DecisionResult.ABSTAIN, DecisionResult.REVIEW} for row in rows)


def _selected_path_mean(rows: list[JsonObject], decision_field: str) -> Decimal | None:
    selected = [
        Decimal(str(row["path_diagnostics"]["terminal_index_change_bps"]))
        for row in rows
        if row[decision_field] == DecisionResult.CANDIDATE
    ]
    return sum(selected, Decimal(0)) / Decimal(len(selected)) if selected else None


def _metric(
    metric_id: str,
    value: Decimal | int | None,
    unit: str,
    unavailable_reason: str | None,
) -> JsonObject:
    promotion_use = (
        "FORBIDDEN"
        if metric_id
        in {"BASE_CANDIDATE_RATE", "CHALLENGER_CANDIDATE_RATE", "CANDIDATE_COUNT_DELTA"}
        else "DIAGNOSTIC_ONLY"
    )
    if value is None:
        return {
            "metric_id": metric_id,
            "status": "UNAVAILABLE",
            "value": None,
            "unit": unit,
            "reason": unavailable_reason,
            "claim_scope": "PATH_DIAGNOSTIC_NOT_STRATEGY_ECONOMICS",
            "promotion_use": promotion_use,
        }
    text = decimal_text(value) if isinstance(value, Decimal) else str(value)
    return {
        "metric_id": metric_id,
        "status": "MEASURED",
        "value": text,
        "unit": unit,
        "reason": None,
        "claim_scope": "PATH_DIAGNOSTIC_NOT_STRATEGY_ECONOMICS",
        "promotion_use": promotion_use,
    }
