from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from optimatrix.ai_lab.canonical import (
    JsonObject,
    ValidationError,
    parse_utc,
    require_content_id,
    require_text,
    seal_object,
    strict_fields,
    utc_text,
    verify_seal,
)
from optimatrix.ai_lab.models import (
    PLAN_SCHEMA,
    SPEC_SCHEMA,
    ExperimentPlan,
    FrozenSpec,
    SpecRole,
)

REGISTRATION_SCHEMA = "optimatrix.ai-lab.experiment-registration.v1"
REGISTRATION_NAMESPACE = "OptimatrixAiLabExperimentRegistrationV1"
LOCAL_TIME_AUTHORITY = "LOCAL_WALL_CLOCK_UNATTESTED"
APPEND_ORDER_SCOPE = "SAME_AUDIT_STORE_ONLY"


@dataclass(frozen=True)
class SpecRegistrationReference:
    schema_version: str
    spec_id: str
    role: SpecRole
    version: str
    external_policy_id: str
    implementation_id: str

    @classmethod
    def from_spec(cls, spec: FrozenSpec) -> Self:
        return cls(
            schema_version=SPEC_SCHEMA,
            spec_id=spec.spec_id,
            role=spec.role,
            version=spec.version,
            external_policy_id=spec.external_policy_id,
            implementation_id=spec.implementation_id,
        )

    @classmethod
    def from_object(cls, value: object, name: str) -> Self:
        item = strict_fields(
            value,
            {
                "schema_version",
                "spec_id",
                "role",
                "version",
                "external_policy_id",
                "implementation_id",
            },
            name,
        )
        if item["schema_version"] != SPEC_SCHEMA:
            raise ValidationError(f"{name} has an unsupported spec schema")
        return cls(
            schema_version=SPEC_SCHEMA,
            spec_id=require_content_id(item["spec_id"], f"{name}.spec_id"),
            role=SpecRole(require_text(item["role"], f"{name}.role")),
            version=require_text(item["version"], f"{name}.version"),
            external_policy_id=require_content_id(
                item["external_policy_id"], f"{name}.external_policy_id"
            ),
            implementation_id=require_text(item["implementation_id"], f"{name}.implementation_id"),
        )

    def as_object(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "role": self.role.value,
            "version": self.version,
            "external_policy_id": self.external_policy_id,
            "implementation_id": self.implementation_id,
        }


@dataclass(frozen=True)
class PlanRegistrationReference:
    schema_version: str
    plan_id: str
    mode: str
    evaluator_id: str

    @classmethod
    def from_plan(cls, plan: ExperimentPlan) -> Self:
        return cls(
            schema_version=PLAN_SCHEMA,
            plan_id=plan.plan_id,
            mode=plan.mode.value,
            evaluator_id=plan.evaluator_id,
        )

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {"schema_version", "plan_id", "mode", "evaluator_id"},
            "experiment_registration.plan",
        )
        if item["schema_version"] != PLAN_SCHEMA:
            raise ValidationError("registration has an unsupported plan schema")
        return cls(
            schema_version=PLAN_SCHEMA,
            plan_id=require_content_id(item["plan_id"], "experiment_registration.plan.plan_id"),
            mode=require_text(item["mode"], "experiment_registration.plan.mode"),
            evaluator_id=require_text(
                item["evaluator_id"], "experiment_registration.plan.evaluator_id"
            ),
        )

    def as_object(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "mode": self.mode,
            "evaluator_id": self.evaluator_id,
        }


@dataclass(frozen=True)
class ExperimentRegistration:
    registration_id: str
    recorded_at: datetime
    base_spec: SpecRegistrationReference
    challenger_spec: SpecRegistrationReference
    plan: PlanRegistrationReference
    local_time_authority: str
    append_order_scope: str

    @classmethod
    def create(
        cls,
        *,
        base: FrozenSpec,
        challenger: FrozenSpec,
        plan: ExperimentPlan,
        recorded_at: datetime,
    ) -> JsonObject:
        if base.role is not SpecRole.BASE or challenger.role is not SpecRole.CHALLENGER:
            raise ValidationError("registration requires one BASE and one CHALLENGER spec")
        draft: JsonObject = {
            "schema_version": REGISTRATION_SCHEMA,
            "recorded_at": utc_text(recorded_at),
            "base_spec": SpecRegistrationReference.from_spec(base).as_object(),
            "challenger_spec": SpecRegistrationReference.from_spec(challenger).as_object(),
            "plan": PlanRegistrationReference.from_plan(plan).as_object(),
            "local_time_authority": LOCAL_TIME_AUTHORITY,
            "append_order_scope": APPEND_ORDER_SCOPE,
        }
        value = seal_object(
            draft,
            id_field="registration_id",
            namespace=REGISTRATION_NAMESPACE,
        )
        cls.from_object(value)
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = strict_fields(
            value,
            {
                "schema_version",
                "registration_id",
                "recorded_at",
                "base_spec",
                "challenger_spec",
                "plan",
                "local_time_authority",
                "append_order_scope",
            },
            "experiment_registration",
        )
        if item["schema_version"] != REGISTRATION_SCHEMA:
            raise ValidationError("unsupported experiment registration schema")
        verify_seal(item, id_field="registration_id", namespace=REGISTRATION_NAMESPACE)
        base = SpecRegistrationReference.from_object(
            item["base_spec"], "experiment_registration.base_spec"
        )
        challenger = SpecRegistrationReference.from_object(
            item["challenger_spec"], "experiment_registration.challenger_spec"
        )
        if base.role is not SpecRole.BASE or challenger.role is not SpecRole.CHALLENGER:
            raise ValidationError("registration spec roles are invalid")
        if item["local_time_authority"] != LOCAL_TIME_AUTHORITY:
            raise ValidationError("registration must disclose its unattested local clock")
        if item["append_order_scope"] != APPEND_ORDER_SCOPE:
            raise ValidationError("registration must disclose its same-store order scope")
        return cls(
            registration_id=require_content_id(
                item["registration_id"], "experiment_registration.registration_id"
            ),
            recorded_at=parse_utc(item["recorded_at"], "experiment_registration.recorded_at"),
            base_spec=base,
            challenger_spec=challenger,
            plan=PlanRegistrationReference.from_object(item["plan"]),
            local_time_authority=LOCAL_TIME_AUTHORITY,
            append_order_scope=APPEND_ORDER_SCOPE,
        )

    def matches(
        self,
        *,
        base: FrozenSpec,
        challenger: FrozenSpec,
        plan: ExperimentPlan,
    ) -> bool:
        return (
            self.base_spec == SpecRegistrationReference.from_spec(base)
            and self.challenger_spec == SpecRegistrationReference.from_spec(challenger)
            and self.plan == PlanRegistrationReference.from_plan(plan)
        )


def registration_reference(
    registration: ExperimentRegistration,
    *,
    event_id: str,
    event_sequence: int,
) -> JsonObject:
    return {
        "registration_id": registration.registration_id,
        "registration_event_id": require_content_id(event_id, "registration_event_id"),
        "registration_event_sequence": event_sequence,
        "recorded_at": utc_text(registration.recorded_at),
        "local_time_authority": registration.local_time_authority,
        "append_order_scope": registration.append_order_scope,
    }
