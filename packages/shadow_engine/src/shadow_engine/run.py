"""Pure run-level accounting for one bounded fixed-Policy public Shadow."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from market_tape import canonical_digest

RUN_CONTRACT_ID = "FIXED_POLICY_PUBLIC_SHADOW_RUN"
RUN_RECEIPT_TYPE = "SHORT_VOL_PUBLIC_SHADOW_RUN_RECEIPT"
OPPORTUNITY_RECORD_TYPE = "SHORT_VOL_PUBLIC_SHADOW_OPPORTUNITY_RECORD"
NO_TRADE_COMPARATOR_ID = "CONTEMPORANEOUS_NO_TRADE_ZERO"


class AdmissionClass(StrEnum):
    OPPORTUNITY_UNKNOWN = "OPPORTUNITY_UNKNOWN"
    NO_ENTRY = "NO_ENTRY"
    ADMITTED = "ADMITTED"
    CONCURRENCY_BLOCKED = "CONCURRENCY_BLOCKED"


class MaturityClass(StrEnum):
    MATURE_CLOSED = "MATURE_CLOSED"
    MATURE_UNEXITABLE = "MATURE_UNEXITABLE"
    MATURE_UNKNOWN = "MATURE_UNKNOWN"
    IMMATURE_UNKNOWN = "IMMATURE_UNKNOWN"


def classify_admission(
    *,
    decision_complete: bool,
    decision_action: str | None,
    capacity_available: bool,
) -> tuple[AdmissionClass, str]:
    if decision_action is None:
        return AdmissionClass.OPPORTUNITY_UNKNOWN, "NO_CANONICAL_EVENT_IN_SLOT"
    if not decision_complete:
        return AdmissionClass.OPPORTUNITY_UNKNOWN, "DECISION_OR_BINDING_INCOMPLETE"
    if decision_action in {"WATCH", "ABSTAIN"}:
        return AdmissionClass.NO_ENTRY, f"DECISION_{decision_action}"
    if decision_action != "RESEARCH_CANDIDATE":
        raise ValueError("unsupported fixed-Policy Decision action")
    if capacity_available:
        return AdmissionClass.ADMITTED, "CANDIDATE_AND_CAPACITY_AVAILABLE"
    return AdmissionClass.CONCURRENCY_BLOCKED, "EXISTING_ACTUAL_EXPOSURE_OPEN"


@dataclass(frozen=True, slots=True)
class OpportunitySummary:
    slot_index: int
    event_backed: bool
    decision_complete: bool
    decision_action: str | None
    admission_class: AdmissionClass
    admission_reason: str
    entry_receipt_digest: str | None
    outcome_receipt_digest: str | None
    outcome_status: str | None
    maturity_class: MaturityClass | None
    observed_executable_pnl_usdc: Decimal | None

    def __post_init__(self) -> None:
        if self.slot_index < 0 or not self.admission_reason:
            raise ValueError("opportunity identity or admission reason is invalid")
        if self.event_backed != (self.decision_action is not None):
            raise ValueError("event-backed opportunity and Decision presence disagree")
        expected, _ = classify_admission(
            decision_complete=self.decision_complete,
            decision_action=self.decision_action,
            capacity_available=self.admission_class is not AdmissionClass.CONCURRENCY_BLOCKED,
        )
        if expected is not self.admission_class:
            raise ValueError("opportunity admission classification changed")
        admitted = self.admission_class is AdmissionClass.ADMITTED
        if admitted != (self.entry_receipt_digest is not None):
            raise ValueError("admission and Entry receipt presence disagree")
        if (self.outcome_receipt_digest is None) != (self.outcome_status is None):
            raise ValueError("Outcome receipt and status presence disagree")
        if (self.outcome_status is None) != (self.maturity_class is None):
            raise ValueError("Outcome status and maturity presence disagree")
        if self.outcome_status is not None and not admitted:
            raise ValueError("only an admitted Entry can have an Outcome")
        if self.outcome_status not in {None, "CLOSED", "UNEXITABLE", "UNKNOWN"}:
            raise ValueError("unsupported Outcome status")
        if self.maturity_class is MaturityClass.MATURE_CLOSED:
            if self.outcome_status != "CLOSED" or self.observed_executable_pnl_usdc is None:
                raise ValueError("mature CLOSED result lacks executable PnL")
        elif self.observed_executable_pnl_usdc is not None:
            raise ValueError("non-CLOSED strategy result must retain null PnL")
        if self.maturity_class is MaturityClass.MATURE_UNEXITABLE and (
            self.outcome_status != "UNEXITABLE"
        ):
            raise ValueError("UNEXITABLE maturity and Outcome disagree")
        if (
            self.maturity_class
            in {
                MaturityClass.MATURE_UNKNOWN,
                MaturityClass.IMMATURE_UNKNOWN,
            }
            and self.outcome_status != "UNKNOWN"
        ):
            raise ValueError("UNKNOWN maturity and Outcome disagree")

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class RunAccounting:
    due_opportunity_count: int
    event_backed_decision_count: int
    no_event_slot_count: int
    admission_counts: dict[str, int]
    action_counts: dict[str, int]
    entry_count: int
    outcome_count: int
    maturity_counts: dict[str, int]
    no_trade_comparator_count: int
    no_trade_pnl_usdc: Decimal
    closed_pnl_subtotal_usdc: Decimal
    null_strategy_result_count: int
    strategy_total_pnl_usdc: Decimal | None
    final_open_exposure_count: int
    maximum_concurrent_exposure_count: int

    @classmethod
    def from_opportunities(
        cls,
        opportunities: tuple[OpportunitySummary, ...],
        *,
        due_count: int,
        require_complete: bool = True,
    ) -> RunAccounting:
        if due_count <= 0:
            raise ValueError("due opportunity count must be positive")
        if len(opportunities) != due_count:
            raise ValueError("opportunity denominator is incomplete")
        if tuple(item.slot_index for item in opportunities) != tuple(range(due_count)):
            raise ValueError("opportunity slots are not exact and ordered")
        admissions = Counter(item.admission_class.value for item in opportunities)
        actions = Counter(
            item.decision_action for item in opportunities if item.decision_action is not None
        )
        maturity = Counter(
            item.maturity_class.value for item in opportunities if item.maturity_class is not None
        )
        entry_count = admissions[AdmissionClass.ADMITTED.value]
        outcome_count = sum(item.outcome_status is not None for item in opportunities)
        if require_complete and maturity[MaturityClass.IMMATURE_UNKNOWN.value]:
            raise ValueError("complete run cannot contain an immature Entry")
        if require_complete and outcome_count != entry_count:
            raise ValueError("complete run requires one Outcome per admitted Entry")
        if actions["RESEARCH_CANDIDATE"] != (
            admissions[AdmissionClass.ADMITTED.value]
            + admissions[AdmissionClass.CONCURRENCY_BLOCKED.value]
        ):
            raise ValueError("candidate actions and admission partition disagree")
        incomplete_event_backed = sum(
            item.event_backed and not item.decision_complete for item in opportunities
        )
        no_event = sum(not item.event_backed for item in opportunities)
        if (
            incomplete_event_backed + no_event
            != admissions[AdmissionClass.OPPORTUNITY_UNKNOWN.value]
        ):
            raise ValueError("UNKNOWN opportunity accounting changed")
        if sum(admissions.values()) != due_count:
            raise ValueError("admission classes do not partition the denominator")
        if sum(actions.values()) + no_event != due_count:
            raise ValueError("Decision action and no-event accounting changed")
        if sum(maturity.values()) != outcome_count:
            raise ValueError("maturity partitions do not cover every Outcome")
        closed_subtotal = sum(
            (
                item.observed_executable_pnl_usdc
                for item in opportunities
                if item.observed_executable_pnl_usdc is not None
            ),
            start=Decimal("0"),
        )
        null_count = sum(
            item.outcome_status is not None and item.observed_executable_pnl_usdc is None
            for item in opportunities
        )
        final_open = (
            maturity[MaturityClass.MATURE_UNEXITABLE.value]
            + maturity[MaturityClass.MATURE_UNKNOWN.value]
            + maturity[MaturityClass.IMMATURE_UNKNOWN.value]
        )
        if final_open > 1:
            raise ValueError("final open exposure exceeds the single-exposure contract")
        if maturity[MaturityClass.MATURE_CLOSED.value] + final_open != entry_count:
            raise ValueError("closed and final-open exposure accounting changed")
        return cls(
            due_opportunity_count=due_count,
            event_backed_decision_count=due_count - no_event,
            no_event_slot_count=no_event,
            admission_counts={item.value: admissions[item.value] for item in AdmissionClass},
            action_counts={
                action: actions[action] for action in ("RESEARCH_CANDIDATE", "WATCH", "ABSTAIN")
            },
            entry_count=entry_count,
            outcome_count=outcome_count,
            maturity_counts={item.value: maturity[item.value] for item in MaturityClass},
            no_trade_comparator_count=due_count,
            no_trade_pnl_usdc=Decimal("0"),
            closed_pnl_subtotal_usdc=closed_subtotal,
            null_strategy_result_count=null_count,
            strategy_total_pnl_usdc=(closed_subtotal if null_count == 0 else None),
            final_open_exposure_count=final_open,
            maximum_concurrent_exposure_count=min(1, entry_count),
        )

    @property
    def digest(self) -> str:
        return canonical_digest(self)
