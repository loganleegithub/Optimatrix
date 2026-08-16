from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Self

from optimatrix.ai_lab.canonical import (
    JsonObject,
    ValidationError,
    parse_decimal,
    parse_utc,
    require_bool,
    require_content_id,
    require_int,
    require_text,
    require_text_list,
    seal_object,
    strict_fields,
    verify_seal,
)

SPEC_SCHEMA = "optimatrix.ai-lab.policy-spec.v1"
EXPORT_SCHEMA = "optimatrix.ai-lab.decision-window-export.v1"
PLAN_SCHEMA = "optimatrix.ai-lab.experiment-plan.v1"

SPEC_NAMESPACE = "OptimatrixAiLabFrozenPolicySpecV1"
DECISION_NAMESPACE = "OptimatrixAiLabExportedDecisionV1"
EXPORT_NAMESPACE = "OptimatrixAiLabDecisionWindowExportV1"
PLAN_NAMESPACE = "OptimatrixAiLabExperimentPlanV1"


class SpecRole(StrEnum):
    BASE = "BASE"
    CHALLENGER = "CHALLENGER"


class DecisionResult(StrEnum):
    UNKNOWN = "UNKNOWN"
    ABSTAIN = "ABSTAIN"
    REVIEW = "REVIEW"
    CANDIDATE = "CANDIDATE"


class PathKind(StrEnum):
    FULL_PATH = "FULL_PATH"
    SUMMARY_ONLY = "SUMMARY_ONLY"
    MISSING = "MISSING"


class PathActuality(StrEnum):
    ACTUAL_PUBLIC_PATH = "ACTUAL_PUBLIC_PATH"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"


class SplitMode(StrEnum):
    CHRONOLOGICAL = "CHRONOLOGICAL"
    WALK_FORWARD = "WALK_FORWARD"


@dataclass(frozen=True)
class FrozenSpec:
    spec_id: str
    role: SpecRole
    version: str
    name: str
    frozen_at: datetime
    trained_through: datetime
    external_policy_id: str
    implementation_id: str
    limitations: tuple[str, ...]

    @classmethod
    def seal(cls, draft: Mapping[str, object]) -> JsonObject:
        value = seal_object(draft, id_field="spec_id", namespace=SPEC_NAMESPACE)
        cls.from_object(value)
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {
                "schema_version",
                "spec_id",
                "status",
                "role",
                "version",
                "name",
                "frozen_at",
                "trained_through",
                "external_policy_id",
                "implementation_id",
                "limitations",
            },
            "frozen_spec",
        )
        if item["schema_version"] != SPEC_SCHEMA:
            raise ValidationError("unsupported frozen spec schema")
        if item["status"] != "FROZEN":
            raise ValidationError("policy spec status must be FROZEN")
        verify_seal(item, id_field="spec_id", namespace=SPEC_NAMESPACE)
        frozen_at = parse_utc(item["frozen_at"], "frozen_spec.frozen_at")
        trained_through = parse_utc(item["trained_through"], "frozen_spec.trained_through")
        if trained_through > frozen_at:
            raise ValidationError("frozen spec cannot be trained after it was frozen")
        return cls(
            spec_id=require_content_id(item["spec_id"], "frozen_spec.spec_id"),
            role=SpecRole(require_text(item["role"], "frozen_spec.role")),
            version=require_text(item["version"], "frozen_spec.version"),
            name=require_text(item["name"], "frozen_spec.name"),
            frozen_at=frozen_at,
            trained_through=trained_through,
            external_policy_id=require_content_id(
                item["external_policy_id"], "frozen_spec.external_policy_id"
            ),
            implementation_id=require_text(
                item["implementation_id"], "frozen_spec.implementation_id"
            ),
            limitations=require_text_list(item["limitations"], "frozen_spec.limitations"),
        )


@dataclass(frozen=True)
class ExportedDecision:
    decision_record_id: str
    spec_id: str
    decision_policy_id: str
    known_at: datetime
    causal_input_ends_at: datetime
    result: DecisionResult
    blockers: tuple[str, ...]

    @classmethod
    def seal(cls, draft: Mapping[str, object]) -> JsonObject:
        value = seal_object(
            draft,
            id_field="decision_record_id",
            namespace=DECISION_NAMESPACE,
        )
        cls.from_object(value)
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {
                "decision_record_id",
                "spec_id",
                "decision_policy_id",
                "known_at",
                "causal_input_ends_at",
                "result",
                "blockers",
            },
            "exported_decision",
        )
        verify_seal(item, id_field="decision_record_id", namespace=DECISION_NAMESPACE)
        result = DecisionResult(require_text(item["result"], "exported_decision.result"))
        blockers = require_text_list(item["blockers"], "exported_decision.blockers")
        if result is DecisionResult.UNKNOWN and not blockers:
            raise ValidationError("UNKNOWN exported decision requires a blocker")
        if result is DecisionResult.CANDIDATE and blockers:
            raise ValidationError("CANDIDATE exported decision cannot have blockers")
        known_at = parse_utc(item["known_at"], "exported_decision.known_at")
        causal_input_ends_at = parse_utc(
            item["causal_input_ends_at"], "exported_decision.causal_input_ends_at"
        )
        if causal_input_ends_at > known_at:
            raise ValidationError("decision cannot use an input that was not yet known")
        return cls(
            decision_record_id=require_content_id(
                item["decision_record_id"], "exported_decision.decision_record_id"
            ),
            spec_id=require_content_id(item["spec_id"], "exported_decision.spec_id"),
            decision_policy_id=require_content_id(
                item["decision_policy_id"], "exported_decision.decision_policy_id"
            ),
            known_at=known_at,
            causal_input_ends_at=causal_input_ends_at,
            result=result,
            blockers=blockers,
        )


@dataclass(frozen=True)
class PathPoint:
    observed_at: datetime
    known_at: datetime
    index_price_usd: Decimal

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {"observed_at", "known_at", "index_price_usd"},
            "future_path.point",
        )
        observed_at = parse_utc(item["observed_at"], "future_path.point.observed_at")
        known_at = parse_utc(item["known_at"], "future_path.point.known_at")
        if observed_at > known_at:
            raise ValidationError("future path point cannot be known before observation")
        return cls(
            observed_at=observed_at,
            known_at=known_at,
            index_price_usd=parse_decimal(
                item["index_price_usd"], "future_path.point.index_price_usd", positive=True
            ),
        )


@dataclass(frozen=True)
class FullFuturePath:
    kind: PathKind
    actuality: PathActuality
    source_id: str
    method_id: str
    starts_at: datetime
    ends_at: datetime
    known_at: datetime
    continuous: bool
    points: tuple[PathPoint, ...]

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {
                "kind",
                "actuality",
                "source_id",
                "method_id",
                "starts_at",
                "ends_at",
                "known_at",
                "continuous",
                "points",
            },
            "full_future_path",
        )
        if item["kind"] != PathKind.FULL_PATH:
            raise ValidationError("full future path kind mismatch")
        starts_at = parse_utc(item["starts_at"], "full_future_path.starts_at")
        ends_at = parse_utc(item["ends_at"], "full_future_path.ends_at")
        known_at = parse_utc(item["known_at"], "full_future_path.known_at")
        if starts_at >= ends_at or ends_at > known_at:
            raise ValidationError("full future path boundaries are invalid")
        raw_points = item["points"]
        if not isinstance(raw_points, list):
            raise ValidationError("full_future_path.points must be an array")
        points = tuple(PathPoint.from_object(point) for point in raw_points)
        if len(points) < 2:
            raise ValidationError("full future path requires at least two points")
        if points[0].observed_at != starts_at or points[-1].observed_at != ends_at:
            raise ValidationError("full future path points must own both declared boundaries")
        if any(left.observed_at >= right.observed_at for left, right in pairwise(points)):
            raise ValidationError("full future path points must be strictly chronological")
        if any(point.known_at > known_at for point in points):
            raise ValidationError("full future path cannot precede a point's known-at boundary")
        return cls(
            kind=PathKind.FULL_PATH,
            actuality=PathActuality(require_text(item["actuality"], "full_future_path.actuality")),
            source_id=require_text(item["source_id"], "full_future_path.source_id"),
            method_id=require_text(item["method_id"], "full_future_path.method_id"),
            starts_at=starts_at,
            ends_at=ends_at,
            known_at=known_at,
            continuous=require_bool(item["continuous"], "full_future_path.continuous"),
            points=points,
        )


@dataclass(frozen=True)
class SummaryFuturePath:
    kind: PathKind
    actuality: PathActuality
    source_id: str
    method_id: str
    starts_at: datetime
    ends_at: datetime
    known_at: datetime
    observation_count: int
    summary: JsonObject

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {
                "kind",
                "actuality",
                "source_id",
                "method_id",
                "starts_at",
                "ends_at",
                "known_at",
                "observation_count",
                "summary",
            },
            "summary_future_path",
        )
        if item["kind"] != PathKind.SUMMARY_ONLY:
            raise ValidationError("summary future path kind mismatch")
        starts_at = parse_utc(item["starts_at"], "summary_future_path.starts_at")
        ends_at = parse_utc(item["ends_at"], "summary_future_path.ends_at")
        known_at = parse_utc(item["known_at"], "summary_future_path.known_at")
        if starts_at >= ends_at or ends_at > known_at:
            raise ValidationError("summary future path boundaries are invalid")
        summary = item["summary"]
        if not isinstance(summary, dict):
            raise ValidationError("summary_future_path.summary must be an object")
        return cls(
            kind=PathKind.SUMMARY_ONLY,
            actuality=PathActuality(
                require_text(item["actuality"], "summary_future_path.actuality")
            ),
            source_id=require_text(item["source_id"], "summary_future_path.source_id"),
            method_id=require_text(item["method_id"], "summary_future_path.method_id"),
            starts_at=starts_at,
            ends_at=ends_at,
            known_at=known_at,
            observation_count=require_int(
                item["observation_count"], "summary_future_path.observation_count", minimum=1
            ),
            summary=deepcopy(summary),
        )


@dataclass(frozen=True)
class MissingFuturePath:
    kind: PathKind
    reason: str

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(value, {"kind", "reason"}, "missing_future_path")
        if item["kind"] != PathKind.MISSING:
            raise ValidationError("missing future path kind mismatch")
        return cls(
            kind=PathKind.MISSING,
            reason=require_text(item["reason"], "missing_future_path.reason"),
        )


FuturePath = FullFuturePath | SummaryFuturePath | MissingFuturePath


def parse_future_path(value: object) -> FuturePath:
    if not isinstance(value, dict):
        raise ValidationError("future_path must be an object")
    kind = value.get("kind")
    if kind == PathKind.FULL_PATH:
        return FullFuturePath.from_object(value)
    if kind == PathKind.SUMMARY_ONLY:
        return SummaryFuturePath.from_object(value)
    if kind == PathKind.MISSING:
        return MissingFuturePath.from_object(value)
    raise ValidationError(f"unsupported future path kind: {kind!r}")


@dataclass(frozen=True)
class ExportedWindow:
    decision_window_id: str
    market_session_id: str
    starts_at: datetime
    ends_at: datetime
    input_deadline: datetime
    base_decision: ExportedDecision
    challenger_decision: ExportedDecision
    future_path: FuturePath

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {
                "decision_window_id",
                "market_session_id",
                "starts_at",
                "ends_at",
                "input_deadline",
                "base_decision",
                "challenger_decision",
                "future_path",
            },
            "exported_window",
        )
        starts_at = parse_utc(item["starts_at"], "exported_window.starts_at")
        ends_at = parse_utc(item["ends_at"], "exported_window.ends_at")
        input_deadline = parse_utc(item["input_deadline"], "exported_window.input_deadline")
        if starts_at >= ends_at or ends_at > input_deadline:
            raise ValidationError("exported DecisionWindow boundaries are invalid")
        base = ExportedDecision.from_object(item["base_decision"])
        challenger = ExportedDecision.from_object(item["challenger_decision"])
        for label, decision in (("base", base), ("challenger", challenger)):
            if not starts_at <= decision.causal_input_ends_at <= ends_at:
                raise ValidationError(f"{label} decision causal input is outside its Window")
            if decision.known_at > input_deadline:
                raise ValidationError(f"{label} decision was known after the input deadline")
        future_path = parse_future_path(item["future_path"])
        if isinstance(future_path, (FullFuturePath, SummaryFuturePath)) and (
            future_path.starts_at <= max(base.known_at, challenger.known_at)
        ):
            raise ValidationError("future path must start strictly after both frozen decisions")
        return cls(
            decision_window_id=require_content_id(
                item["decision_window_id"], "exported_window.decision_window_id"
            ),
            market_session_id=require_text(
                item["market_session_id"], "exported_window.market_session_id"
            ),
            starts_at=starts_at,
            ends_at=ends_at,
            input_deadline=input_deadline,
            base_decision=base,
            challenger_decision=challenger,
            future_path=future_path,
        )


@dataclass(frozen=True)
class DecisionWindowExport:
    export_id: str
    exported_at: datetime
    producer_id: str
    source_repository_commit: str
    source_contracts: tuple[str, ...]
    windows: tuple[ExportedWindow, ...]

    @classmethod
    def seal(cls, draft: Mapping[str, object]) -> JsonObject:
        prepared = deepcopy(dict(draft))
        windows = prepared.get("windows")
        if not isinstance(windows, list):
            raise ValidationError("decision-window export draft requires a windows array")
        for window in windows:
            if not isinstance(window, dict):
                raise ValidationError("decision-window export window must be an object")
            for field in ("base_decision", "challenger_decision"):
                decision = window.get(field)
                if not isinstance(decision, dict):
                    raise ValidationError(f"{field} must be an object")
                if "decision_record_id" not in decision:
                    window[field] = ExportedDecision.seal(decision)
        value = seal_object(prepared, id_field="export_id", namespace=EXPORT_NAMESPACE)
        cls.from_object(value)
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {
                "schema_version",
                "export_id",
                "exported_at",
                "producer_id",
                "source_repository_commit",
                "source_contracts",
                "windows",
            },
            "decision_window_export",
        )
        if item["schema_version"] != EXPORT_SCHEMA:
            raise ValidationError("unsupported DecisionWindow export schema")
        verify_seal(item, id_field="export_id", namespace=EXPORT_NAMESPACE)
        raw_windows = item["windows"]
        if not isinstance(raw_windows, list):
            raise ValidationError("decision_window_export.windows must be an array")
        windows = tuple(ExportedWindow.from_object(window) for window in raw_windows)
        if not windows:
            raise ValidationError("DecisionWindow export must contain at least one Window")
        ids = tuple(window.decision_window_id for window in windows)
        if len(set(ids)) != len(ids):
            raise ValidationError("DecisionWindow export contains duplicate Window identities")
        if any(
            left.starts_at >= right.starts_at or left.ends_at > right.starts_at
            for left, right in pairwise(windows)
        ):
            raise ValidationError(
                "exported DecisionWindows must be chronological and non-overlapping"
            )
        exported_at = parse_utc(item["exported_at"], "decision_window_export.exported_at")
        known_boundaries = [
            boundary
            for window in windows
            for boundary in (
                window.base_decision.known_at,
                window.challenger_decision.known_at,
                getattr(window.future_path, "known_at", None),
            )
            if boundary is not None
        ]
        if exported_at < max(known_boundaries):
            raise ValidationError("export cannot predate a contained fact")
        return cls(
            export_id=require_content_id(item["export_id"], "decision_window_export.export_id"),
            exported_at=exported_at,
            producer_id=require_text(item["producer_id"], "decision_window_export.producer_id"),
            source_repository_commit=require_text(
                item["source_repository_commit"],
                "decision_window_export.source_repository_commit",
            ),
            source_contracts=require_text_list(
                item["source_contracts"], "decision_window_export.source_contracts"
            ),
            windows=windows,
        )

    def validate_specs(self, base: FrozenSpec, challenger: FrozenSpec) -> None:
        if base.role is not SpecRole.BASE or challenger.role is not SpecRole.CHALLENGER:
            raise ValidationError("experiment requires one BASE and one CHALLENGER spec")
        if base.spec_id == challenger.spec_id:
            raise ValidationError("Base and Challenger specs must be distinct")
        for window in self.windows:
            pairs = ((window.base_decision, base), (window.challenger_decision, challenger))
            for decision, spec in pairs:
                if decision.spec_id != spec.spec_id:
                    raise ValidationError("exported decision does not bind its frozen spec")
                if decision.decision_policy_id != spec.external_policy_id:
                    raise ValidationError(
                        "exported decision does not bind the spec's Policy identity"
                    )


@dataclass(frozen=True)
class EvaluationFold:
    fold_id: str
    training_ends_at: datetime
    evaluation_starts_at: datetime
    evaluation_ends_at: datetime

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {"fold_id", "training_ends_at", "evaluation_starts_at", "evaluation_ends_at"},
            "evaluation_fold",
        )
        training_ends_at = parse_utc(item["training_ends_at"], "fold.training_ends_at")
        evaluation_starts_at = parse_utc(item["evaluation_starts_at"], "fold.evaluation_starts_at")
        evaluation_ends_at = parse_utc(item["evaluation_ends_at"], "fold.evaluation_ends_at")
        if training_ends_at >= evaluation_starts_at or evaluation_starts_at >= evaluation_ends_at:
            raise ValidationError("training must end before a positive evaluation interval")
        return cls(
            fold_id=require_text(item["fold_id"], "fold.fold_id"),
            training_ends_at=training_ends_at,
            evaluation_starts_at=evaluation_starts_at,
            evaluation_ends_at=evaluation_ends_at,
        )

    def owns(self, window: ExportedWindow) -> bool:
        return (
            self.evaluation_starts_at <= window.starts_at
            and window.ends_at <= self.evaluation_ends_at
        )


@dataclass(frozen=True)
class PromotionGateSpec:
    min_comparable_windows: int
    max_incomparable_fraction: Decimal
    require_actual_paths: bool

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {
                "min_comparable_windows",
                "max_incomparable_fraction",
                "require_actual_paths",
            },
            "promotion_gate",
        )
        fraction = parse_decimal(
            item["max_incomparable_fraction"], "promotion_gate.max_incomparable_fraction"
        )
        if not Decimal(0) <= fraction <= Decimal(1):
            raise ValidationError("promotion max incomparable fraction must be in [0, 1]")
        return cls(
            min_comparable_windows=require_int(
                item["min_comparable_windows"],
                "promotion_gate.min_comparable_windows",
                minimum=1,
            ),
            max_incomparable_fraction=fraction,
            require_actual_paths=require_bool(
                item["require_actual_paths"], "promotion_gate.require_actual_paths"
            ),
        )


@dataclass(frozen=True)
class ExperimentPlan:
    plan_id: str
    mode: SplitMode
    registered_at: datetime
    folds: tuple[EvaluationFold, ...]
    evaluator_id: str
    metric_ids: tuple[str, ...]
    promotion_gate: PromotionGateSpec

    @classmethod
    def seal(cls, draft: Mapping[str, object]) -> JsonObject:
        value = seal_object(draft, id_field="plan_id", namespace=PLAN_NAMESPACE)
        cls.from_object(value)
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {
                "schema_version",
                "plan_id",
                "status",
                "mode",
                "registered_at",
                "folds",
                "evaluator_id",
                "metric_ids",
                "promotion_gate",
            },
            "experiment_plan",
        )
        if item["schema_version"] != PLAN_SCHEMA:
            raise ValidationError("unsupported experiment plan schema")
        if item["status"] != "FROZEN":
            raise ValidationError("experiment plan status must be FROZEN")
        verify_seal(item, id_field="plan_id", namespace=PLAN_NAMESPACE)
        mode = SplitMode(require_text(item["mode"], "experiment_plan.mode"))
        raw_folds = item["folds"]
        if not isinstance(raw_folds, list):
            raise ValidationError("experiment_plan.folds must be an array")
        folds = tuple(EvaluationFold.from_object(fold) for fold in raw_folds)
        if (mode is SplitMode.CHRONOLOGICAL and len(folds) != 1) or (
            mode is SplitMode.WALK_FORWARD and len(folds) < 2
        ):
            raise ValidationError(
                "chronological requires one fold; walk-forward requires at least two"
            )
        if len({fold.fold_id for fold in folds}) != len(folds):
            raise ValidationError("fold identities must be unique")
        if any(
            left.evaluation_starts_at >= right.evaluation_starts_at
            or left.evaluation_ends_at > right.evaluation_starts_at
            for left, right in pairwise(folds)
        ):
            raise ValidationError("evaluation folds must be chronological and non-overlapping")
        registered_at = parse_utc(item["registered_at"], "experiment_plan.registered_at")
        if registered_at > folds[0].evaluation_starts_at:
            raise ValidationError(
                "declared plan registration timestamp must not follow evaluation start"
            )
        return cls(
            plan_id=require_content_id(item["plan_id"], "experiment_plan.plan_id"),
            mode=mode,
            registered_at=registered_at,
            folds=folds,
            evaluator_id=require_text(item["evaluator_id"], "experiment_plan.evaluator_id"),
            metric_ids=require_text_list(item["metric_ids"], "experiment_plan.metric_ids"),
            promotion_gate=PromotionGateSpec.from_object(item["promotion_gate"]),
        )

    def validate_specs(self, base: FrozenSpec, challenger: FrozenSpec) -> None:
        if max(base.frozen_at, challenger.frozen_at) > self.registered_at:
            raise ValidationError(
                "declared spec freeze timestamps must not follow the plan's declared timestamp"
            )
        for fold in self.folds:
            if base.trained_through > fold.training_ends_at:
                raise ValidationError(
                    "Base training boundary leaks beyond a fold's training period"
                )
            if challenger.trained_through > fold.training_ends_at:
                raise ValidationError(
                    "Challenger training boundary leaks beyond a fold's training period"
                )

    def fold_for(self, window: ExportedWindow) -> EvaluationFold | None:
        owners = tuple(fold for fold in self.folds if fold.owns(window))
        if len(owners) > 1:
            raise ValidationError("DecisionWindow belongs to more than one evaluation fold")
        return owners[0] if owners else None


def seal_document(kind: str, draft: Mapping[str, object]) -> JsonObject:
    sealers: dict[str, Callable[[Mapping[str, object]], JsonObject]] = {
        "spec": FrozenSpec.seal,
        "export": DecisionWindowExport.seal,
        "plan": ExperimentPlan.seal,
    }
    try:
        sealer = sealers[kind]
    except KeyError as exc:
        raise ValidationError(f"unsupported seal kind: {kind}") from exc
    return sealer(draft)
