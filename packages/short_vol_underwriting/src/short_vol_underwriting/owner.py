from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from options_domain import ComponentBookLegQuote, ComponentBookQuoteKind, ComponentBookVerticalQuote

from short_vol_underwriting.admission import (
    AdmissionAttempt,
    AdmissionRefreshWitness,
    ComponentAdmissionAttempt,
    ComponentBookPairWitness,
    RefreshClassification,
    RpcAdmissionRefreshWitness,
    RpcRequestIntent,
    SubscriptionAdmissionRefreshWitness,
)
from short_vol_underwriting.close import (
    CloseAtomicAvailability,
    CloseBookAvailability,
    CloseOpportunity,
    CloseOpportunityEligibility,
    CloseOptionAvailability,
    CloseQuoteFacts,
    CloseQuoteState,
    ComponentPostCloseAttempt,
    NormalizedCloseQuote,
    PostCloseAttempt,
    PostCloseAttemptOwner,
    PostCloseAttemptStatus,
    classify_close_quote,
    evaluate_close_opportunity,
    normalize_close_quote,
)
from short_vol_underwriting.constants import (
    ADMISSION_CUTOFF_LEAD_MS,
    POSITION_CLOSE_REASONS,
)
from short_vol_underwriting.domain import (
    AdmissionTerminalOutcome,
    CandidateState,
    EntryEconomics,
    PositionDecision,
    PositionDecisionState,
    UnderwritingAction,
    UnderwritingAvailability,
    UnderwritingThresholdMargins,
    classify_underwriting_action,
    compute_component_entry_economics,
    compute_entry_economics,
    compute_shadow_outcome_economics,
    underwriting_threshold_margins,
)
from short_vol_underwriting.evidence import (
    RuntimeBindings,
    ShadowStateStore,
)
from short_vol_underwriting.identity import IdentityError, canonical_identity, require_identity
from short_vol_underwriting.model import (
    FactBoundary,
    OutcomeState,
    PredicateTruth,
    TerminalSource,
)
from short_vol_underwriting.observation import Observation
from short_vol_underwriting.policy import PolicyChain

COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE = "COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE"
COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN = "COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN"
NO_PROTECTIVE_COMPONENT = "NO_PROTECTIVE_COMPONENT"
NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE = "NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE"


@dataclass(frozen=True)
class SourceFact:
    source_identity: str
    boundary: FactBoundary

    def __post_init__(self) -> None:
        require_identity(self.source_identity, "source_identity")

    def as_ref(self) -> dict[str, object]:
        return {
            "source_identity": self.source_identity,
            "receipt_fact_boundary": self.boundary.as_object(),
        }


def _radar_episode_identity_components(value: object) -> tuple[str, str, str, int]:
    if not isinstance(value, str):
        raise IdentityError("active_episode_identity must be a Radar episode identity")
    digest_length = len("sha256:") + 64
    if len(value) <= digest_length * 2 + 3:
        raise IdentityError("active_episode_identity must be a Radar episode identity")
    runtime_identity = value[:digest_length]
    first_separator = digest_length
    policy_start = first_separator + 1
    policy_end = policy_start + digest_length
    if value[first_separator : first_separator + 1] != ":":
        raise IdentityError("active_episode_identity must be a Radar episode identity")
    policy_identity = value[policy_start:policy_end]
    if value[policy_end : policy_end + 1] != ":":
        raise IdentityError("active_episode_identity must be a Radar episode identity")
    instrument_name, separator, causal_seq_text = value[policy_end + 1 :].rpartition(":")
    require_identity(runtime_identity, "Radar episode runtime identity")
    require_identity(policy_identity, "Radar episode Policy identity")
    if (
        not separator
        or not instrument_name
        or not causal_seq_text.isdigit()
        or str(int(causal_seq_text)) != causal_seq_text
    ):
        raise IdentityError("active_episode_identity must be a Radar episode identity")
    return runtime_identity, policy_identity, instrument_name, int(causal_seq_text)


@dataclass(frozen=True)
class UnderwritingFacts:
    boundary: FactBoundary
    radar_scope_identity: str
    active_episode_identity: str | None
    short_leg_identity: str | None
    long_leg_identity: str | None
    canonical_combo_identity: str | None
    combo_instrument_name: str | None
    option_type: str | None
    short_strike_usdc_per_btc: Decimal | None
    long_strike_usdc_per_btc: Decimal | None
    expiry_ms: int | None
    target_quantity_btc: Decimal
    entry_direction: str | None
    entry_consumed_levels: tuple[tuple[Decimal, Decimal], ...]
    atomic_state: str
    option_catalog_complete: bool
    combo_catalog_complete: bool
    short_leg_state: str | None
    long_leg_state: str | None
    short_leg_active: bool | None
    long_leg_active: bool | None
    option_amounts_aligned: bool | None
    combo_state: str | None
    combo_active: bool | None
    combo_amount_aligned: bool | None
    platform_usable: bool | None
    trusted_time_lower_ms: int | None
    trusted_time_upper_ms: int | None
    short_leg_taker_commission_fraction: Decimal | None
    long_leg_taker_commission_fraction: Decimal | None
    index_usdc_per_btc: Decimal | None
    short_delta: Decimal | None
    short_mark_iv_fraction: Decimal | None
    quote_source: SourceFact | None
    quote_refresh_witness: AdmissionRefreshWitness | None
    short_instrument_source: SourceFact | None
    long_instrument_source: SourceFact | None
    index_source: SourceFact | None
    ticker_source: SourceFact | None
    short_leg_instrument_name: str | None = None
    long_leg_instrument_name: str | None = None
    radar_band_id: str | None = None
    radar_richness_lower: Decimal | None = None
    radar_richness_upper: Decimal | None = None
    unknown_reasons: tuple[str, ...] = ()
    component_state: str = "NOT_EVALUATED"
    component_blockers: tuple[str, ...] = ()
    component_quote: ComponentBookVerticalQuote | None = None
    component_short_quote_source: SourceFact | None = None
    component_long_quote_source: SourceFact | None = None
    component_pair_witness: ComponentBookPairWitness | None = None
    protective_leg_selection_rule_identity: str | None = None
    candidate_protective_leg_count: int | None = None

    def __post_init__(self) -> None:
        require_identity(self.radar_scope_identity, "radar_scope_identity")
        if self.active_episode_identity is not None:
            _radar_episode_identity_components(self.active_episode_identity)
        for identity in (
            self.short_leg_identity,
            self.long_leg_identity,
            self.canonical_combo_identity,
        ):
            if identity is not None:
                require_identity(identity, "Underwriting semantic identity")
        if not self.target_quantity_btc.is_finite() or self.target_quantity_btc <= 0:
            raise ValueError("target quantity must be finite and positive")
        if self.entry_direction not in {None, "BUY", "SELL"}:
            raise ValueError("entry_direction must be BUY, SELL, or absent")
        if self.option_type not in {None, "call", "put"}:
            raise ValueError("option_type must be call, put, or absent")
        for instrument_name in (
            self.short_leg_instrument_name,
            self.long_leg_instrument_name,
        ):
            if instrument_name is not None and not instrument_name:
                raise ValueError("option instrument names must be non-empty when present")
        provenance = (
            self.protective_leg_selection_rule_identity,
            self.candidate_protective_leg_count,
        )
        if any(value is None for value in provenance) and not all(
            value is None for value in provenance
        ):
            raise ValueError("protective-leg selection provenance must be complete or absent")
        if self.protective_leg_selection_rule_identity is not None:
            require_identity(
                self.protective_leg_selection_rule_identity,
                "protective_leg_selection_rule_identity",
            )
            if (
                isinstance(self.candidate_protective_leg_count, bool)
                or not isinstance(self.candidate_protective_leg_count, int)
                or self.candidate_protective_leg_count < 0
            ):
                raise ValueError("candidate protective-leg count must be non-negative")


@dataclass(frozen=True)
class PositionFacts:
    boundary: FactBoundary
    trusted_time_lower_ms: int | None
    trusted_time_upper_ms: int | None
    platform_continuous: bool | None
    required_sources_continuous: bool | None
    canonical_structure_intact: bool | None
    short_leg_state: str | None
    long_leg_state: str | None
    short_leg_active: bool | None
    long_leg_active: bool | None
    current_index_usdc_per_btc: Decimal | None
    current_short_delta: Decimal | None
    current_short_mark_iv_fraction: Decimal | None
    close_quote_facts: CloseQuoteFacts
    close_direction: str
    quote_source: SourceFact | None
    quote_refresh_witness: AdmissionRefreshWitness | None
    short_leg_taker_commission_fraction: Decimal | None
    long_leg_taker_commission_fraction: Decimal | None
    short_commission_source: SourceFact | None
    long_commission_source: SourceFact | None
    index_source: SourceFact | None
    ticker_source: SourceFact | None
    current_combo_subscription_witness: SubscriptionAdmissionRefreshWitness | None = None
    lifecycle_short_source: SourceFact | None = None
    lifecycle_long_source: SourceFact | None = None
    component_quote: ComponentBookVerticalQuote | None = None
    component_short_quote_source: SourceFact | None = None
    component_long_quote_source: SourceFact | None = None
    component_pair_witness: ComponentBookPairWitness | None = None
    component_pair_unknown_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.close_direction not in {"BUY", "SELL"}:
            raise ValueError("close_direction must be BUY or SELL")


@dataclass(frozen=True)
class EmittedObject:
    object_kind: str
    object_identity: str
    boundary: FactBoundary


@dataclass(frozen=True)
class RpcRetirementIntent:
    request_id: int
    boundary: FactBoundary


@dataclass(frozen=True, order=True)
class TrustedTimeBoundary:
    market_time_ms: int
    bound: str
    clock_currentness_budget_ms: int

    def __post_init__(self) -> None:
        if self.market_time_ms < 0:
            raise ValueError("trusted-time boundary must be non-negative")
        if self.bound not in {"LOWER", "UPPER"}:
            raise ValueError("trusted-time boundary must select LOWER or UPPER")
        if self.clock_currentness_budget_ms <= 0:
            raise ValueError("trusted-time boundary clock budget must be positive")


@dataclass(frozen=True)
class OwnerTransition:
    emitted: tuple[EmittedObject, ...]
    request_intents: tuple[RpcRequestIntent, ...]
    rpc_retirements: tuple[RpcRetirementIntent, ...]


@dataclass(frozen=True)
class _UnderwritingEvaluation:
    facts: UnderwritingFacts
    availability: UnderwritingAvailability
    availability_fingerprint: str
    slot_identity: str | None
    opportunity_identity: str | None
    economics: EntryEconomics | None
    economic_fingerprint: str | None
    action: UnderwritingAction | None


@dataclass
class _CandidateRecord:
    facts: UnderwritingFacts
    state: CandidateState
    slot_identity: str
    attempt: AdmissionAttempt | ComponentAdmissionAttempt
    availability_fingerprint: str
    economic_fingerprint: str


@dataclass
class _TradeRecord:
    anchor_identity: str
    slot_identity: str
    entry_boundary: FactBoundary
    entry_facts: UnderwritingFacts
    entry_economics: EntryEconomics
    observation: Observation
    position_state: PositionDecisionState
    prior_index: Decimal
    prior_index_source: SourceFact
    last_position_fingerprint: str | None = None
    last_quote_key: tuple[str, str] | None = None
    last_quote_identity: str | None = None
    last_quote_fingerprint: str | None = None
    last_quote_facts: PositionFacts | None = None
    last_accepted_subscription_witness: SubscriptionAdmissionRefreshWitness | None = None
    last_opportunity_key: tuple[str, str] | None = None
    first_close_decision: PositionDecision | None = None
    post_close_attempt: PostCloseAttempt | ComponentPostCloseAttempt | None = None
    terminal_written: bool = False


class FixedContractShadowOwner:
    """Pure synchronous owner for the accepted downstream business lifecycle."""

    def __init__(
        self,
        *,
        policies: PolicyChain,
        bindings: RuntimeBindings,
        state_store: ShadowStateStore,
    ) -> None:
        if policies.identities != (
            bindings.radar_policy_identity,
            bindings.underwriting_policy_identity,
            bindings.position_policy_identity,
        ):
            raise ValueError("owner Policy chain and runtime bindings differ")
        self.policies = policies
        self.bindings = bindings
        self.state_store = state_store
        self._slot_consumed: set[str] = set()
        self._consumed_slots_by_episode: dict[str, set[str]] = {}
        self._last_availability: dict[
            str,
            tuple[str, UnderwritingAvailability, str],
        ] = {}
        self._last_underwriting_action: dict[
            str,
            tuple[str, UnderwritingAction, str],
        ] = {}
        self._candidates: dict[str, _CandidateRecord] = {}
        self._trades: dict[str, _TradeRecord] = {}
        self._emitted: list[EmittedObject] = []
        self._intents: list[RpcRequestIntent] = []
        self._retirements: list[RpcRetirementIntent] = []
        self._candidate_retirements: set[str] = set()
        self._trade_retirements: set[str] = set()
        self._counts: Counter[str] = Counter()
        self._accepting_new_work = True
        self._terminal_boundary: FactBoundary | None = None
        self._terminal_source_identity: str | None = None
        self._terminal_source_kind: TerminalSource | None = None

    @property
    def retained_state_counts(self) -> Mapping[str, int]:
        return {
            "active_candidates": len(self._candidates),
            "active_trades": len(self._trades),
            "active_consumed_slots": len(self._slot_consumed),
            "availability_scopes": len(self._last_availability),
            "action_scopes": len(self._last_underwriting_action),
        }

    @property
    def active_candidate_identities(self) -> frozenset[str]:
        return frozenset(self._candidates)

    @property
    def active_trade_identities(self) -> frozenset[str]:
        return frozenset(self._trades)

    def retire_underwriting_scope(self, scope_identity: str) -> None:
        self._last_availability.pop(scope_identity, None)
        self._last_underwriting_action.pop(scope_identity, None)
        self.state_store.retire_scope(scope_identity)

    def retire_radar_episode(
        self,
        episode_identity: str,
        *,
        boundary: FactBoundary,
    ) -> OwnerTransition:
        self._begin_transition()
        for record in tuple(self._candidates.values()):
            if record.facts.active_episode_identity != episode_identity:
                continue
            self._terminalize_candidate_before_refresh(
                record,
                reasons=("RADAR_POLICY_OR_EPISODE_PAUSED_ENDED_OR_CHANGED",),
                boundary=boundary,
            )
        transition = self._finish_transition()
        if any(
            record.facts.active_episode_identity == episode_identity
            for record in self._candidates.values()
        ):
            raise RuntimeError("ended Radar episode still owns an active Candidate")
        slots = self._consumed_slots_by_episode.pop(episode_identity, set())
        self._slot_consumed.difference_update(slots)
        return transition

    @property
    def required_combo_instrument_names(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    trade.entry_facts.combo_instrument_name
                    for trade in self._trades.values()
                    if (
                        trade.observation.state is OutcomeState.PENDING
                        and trade.entry_facts.combo_instrument_name is not None
                    )
                }
            )
        )

    @property
    def required_option_instrument_names(self) -> tuple[str, ...]:
        names: set[str] = set()
        for trade in self._trades.values():
            if trade.observation.state is not OutcomeState.PENDING:
                continue
            for name in (
                trade.entry_facts.short_leg_instrument_name,
                trade.entry_facts.long_leg_instrument_name,
            ):
                if name is not None:
                    names.add(name)
        return tuple(sorted(names))

    @property
    def pending_trusted_time_boundaries(self) -> tuple[TrustedTimeBoundary, ...]:
        boundaries: set[TrustedTimeBoundary] = set()
        for record in self._candidates.values():
            if record.state.lifecycle.value != "VALID" or record.facts.expiry_ms is None:
                continue
            boundaries.add(
                TrustedTimeBoundary(
                    record.facts.expiry_ms - ADMISSION_CUTOFF_LEAD_MS,
                    "UPPER",
                    self.policies.underwriting.clock_currentness_budget_ms,
                )
            )
        for trade in self._trades.values():
            expiry_ms = trade.entry_facts.expiry_ms
            if trade.observation.state is not OutcomeState.PENDING or expiry_ms is None:
                continue
            boundaries.add(
                TrustedTimeBoundary(
                    expiry_ms - self.policies.position.latest_exit_lead_ms,
                    "UPPER",
                    self.policies.position.clock_currentness_budget_ms,
                )
            )
            boundaries.add(
                TrustedTimeBoundary(
                    expiry_ms,
                    "LOWER",
                    self.policies.position.clock_currentness_budget_ms,
                )
            )
        return tuple(sorted(boundaries))

    def settle_underwriting(
        self,
        facts: Sequence[UnderwritingFacts],
        *,
        allocate_request_id: Callable[[], int],
    ) -> OwnerTransition:
        for member in facts:
            self._require_target_quantity_integrity(member)
            self._require_radar_episode_binding(member)
        self._begin_transition()
        if not facts or not self._accepting_new_work:
            return self._finish_transition()
        boundaries = {member.boundary for member in facts}
        if len(boundaries) != 1:
            raise ValueError("one Underwriting transaction requires one settled boundary")
        facts_by_scope = {member.radar_scope_identity: member for member in facts}
        handled_scopes: set[str] = set()
        for record in tuple(self._candidates.values()):
            if record.state.lifecycle.value != "VALID":
                continue
            current = facts_by_scope.get(record.facts.radar_scope_identity)
            if current is None or not current.boundary.is_strictly_after(record.facts.boundary):
                continue
            evaluation = self._evaluate_underwriting(current)
            if isinstance(record.attempt, ComponentAdmissionAttempt):
                component_reasons = self._component_candidate_pre_refresh_reasons(
                    record,
                    current,
                )
                if component_reasons:
                    self._terminalize_candidate_before_refresh(
                        record,
                        reasons=component_reasons,
                        boundary=current.boundary,
                    )
                handled_scopes.add(current.radar_scope_identity)
                continue
            pre_refresh_reasons = self._candidate_invalidation_reasons(
                record,
                current,
                evaluation,
                include_non_admission_change=False,
                include_reunderwriting=False,
                include_failed_admission=False,
            )
            witness = current.quote_refresh_witness
            qualifying_subscription = isinstance(
                witness, SubscriptionAdmissionRefreshWitness
            ) and record.attempt.subscription_qualifies(
                witness=witness,
                candidate_quote_witness=self._require_quote_witness(record.facts),
            )
            if pre_refresh_reasons:
                self._terminalize_candidate_before_refresh(
                    record,
                    reasons=pre_refresh_reasons,
                    boundary=current.boundary,
                )
                if (
                    "SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN"
                    in pre_refresh_reasons
                ):
                    handled_scopes.add(current.radar_scope_identity)
            elif qualifying_subscription:
                assert isinstance(witness, SubscriptionAdmissionRefreshWitness)
                self._settle_admission_record(
                    record,
                    refreshed_facts=current,
                    refresh_witness=witness,
                    evaluation=evaluation,
                )
                handled_scopes.add(current.radar_scope_identity)
            else:
                ordinary_reasons = self._candidate_invalidation_reasons(
                    record,
                    current,
                    evaluation,
                    include_non_admission_change=True,
                    include_reunderwriting=True,
                    include_failed_admission=False,
                )
                if ordinary_reasons:
                    self._terminalize_candidate_before_refresh(
                        record,
                        reasons=ordinary_reasons,
                        boundary=current.boundary,
                    )
                else:
                    handled_scopes.add(current.radar_scope_identity)
        evaluations = tuple(
            self._evaluate_underwriting(member)
            for member in facts
            if member.radar_scope_identity not in handled_scopes
        )
        for evaluation in evaluations:
            availability_identity = self._emit_availability(evaluation)
            if evaluation.action is None:
                continue
            action_identity, action_changed = self._emit_underwriting_action(
                evaluation,
                availability_identity=availability_identity,
            )
            if action_changed and evaluation.action is UnderwritingAction.CANDIDATE:
                self._activate_candidate(
                    evaluation,
                    action_identity=action_identity,
                    allocate_request_id=allocate_request_id,
                )
        return self._finish_transition()

    def settle_admission(
        self,
        *,
        candidate_identity: str,
        refreshed_facts: UnderwritingFacts,
        refresh_witness: AdmissionRefreshWitness,
    ) -> OwnerTransition:
        self._require_target_quantity_integrity(refreshed_facts)
        self._require_radar_episode_binding(refreshed_facts)
        self._begin_transition()
        record = self._candidates.get(candidate_identity)
        if record is None or record.state.lifecycle.value != "VALID":
            return self._finish_transition()
        if (
            refreshed_facts.boundary != refresh_witness.boundary
            or refreshed_facts.quote_source is None
            or refreshed_facts.quote_source.source_identity != refresh_witness.source_identity
            or refreshed_facts.quote_source.boundary != refresh_witness.boundary
            or refreshed_facts.quote_refresh_witness != refresh_witness
        ):
            raise ValueError(
                "admission refresh facts and official refresh witness must be identical"
            )
        evaluation = self._evaluate_underwriting(refreshed_facts)
        self._settle_admission_record(
            record,
            refreshed_facts=refreshed_facts,
            refresh_witness=refresh_witness,
            evaluation=evaluation,
        )
        return self._finish_transition()

    def settle_component_admission(
        self,
        *,
        candidate_identity: str,
        refreshed_facts: UnderwritingFacts,
        pair_witness: ComponentBookPairWitness,
    ) -> OwnerTransition:
        """Consume exactly one strictly later two-option snapshot pair."""
        self._require_target_quantity_integrity(refreshed_facts)
        self._require_radar_episode_binding(refreshed_facts)
        self._begin_transition()
        record = self._candidates.get(candidate_identity)
        if (
            record is None
            or record.state.lifecycle.value != "VALID"
            or not isinstance(record.attempt, ComponentAdmissionAttempt)
        ):
            return self._finish_transition()
        short_source = refreshed_facts.component_short_quote_source
        long_source = refreshed_facts.component_long_quote_source
        if (
            refreshed_facts.boundary != pair_witness.boundary
            or refreshed_facts.component_pair_witness != pair_witness
            or short_source is None
            or long_source is None
            or short_source.source_identity != pair_witness.short.source_identity
            or short_source.boundary != pair_witness.short.boundary
            or long_source.source_identity != pair_witness.long.source_identity
            or long_source.boundary != pair_witness.long.boundary
        ):
            raise ValueError("component admission facts and paired witnesses must be identical")
        evaluation = self._evaluate_underwriting(refreshed_facts)
        pair_timing_unknown_reasons = pair_witness.timing_unknown_reasons(
            maximum_source_skew_ms=(
                self.policies.underwriting.maximum_component_pair_source_skew_ms
            ),
            maximum_receive_skew_ms=(
                self.policies.underwriting.maximum_component_pair_receive_skew_ms
            ),
        )
        pre_refresh_reasons = self._component_candidate_pre_refresh_reasons(
            record,
            refreshed_facts,
        )
        if pre_refresh_reasons and not pair_timing_unknown_reasons:
            self._terminalize_candidate_before_refresh(
                record,
                reasons=pre_refresh_reasons,
                boundary=refreshed_facts.boundary,
            )
            return self._finish_transition()
        same_opportunity = (
            evaluation.slot_identity == record.slot_identity
            and refreshed_facts.short_leg_identity == record.facts.short_leg_identity
            and refreshed_facts.long_leg_identity == record.facts.long_leg_identity
            and refreshed_facts.target_quantity_btc == record.facts.target_quantity_btc
        )
        if (
            same_opportunity
            and evaluation.availability is UnderwritingAvailability.EVALUABLE
            and evaluation.action is UnderwritingAction.CANDIDATE
        ):
            classification = RefreshClassification.COMPLETE_CANDIDATE
        elif evaluation.availability is UnderwritingAvailability.EVALUABLE:
            classification = RefreshClassification.COMPLETE_NO_ENTRY
        elif evaluation.availability is UnderwritingAvailability.NOT_EVALUATED:
            classification = RefreshClassification.KNOWN_INVALIDATED
        else:
            classification = RefreshClassification.UNKNOWN
        accepted = record.attempt.accept_pair(
            witness=pair_witness,
            response_budget_ms=(
                self.policies.underwriting.component_book_snapshot_response_budget_ms
            ),
            maximum_source_skew_ms=(
                self.policies.underwriting.maximum_component_pair_source_skew_ms
            ),
            maximum_receive_skew_ms=(
                self.policies.underwriting.maximum_component_pair_receive_skew_ms
            ),
            classification=classification,
        )
        if not accepted:
            return self._finish_transition()
        self._emit_admission_terminal(record)
        if record.attempt.terminal_outcome is AdmissionTerminalOutcome.ENTRY_EMITTED:
            record.state.admit(refreshed_facts.boundary)
            if evaluation.economics is None:
                raise RuntimeError("component Candidate admission lacks complete economics")
            self._create_admitted_trade(record, refreshed_facts, evaluation.economics)
        else:
            reasons = self._candidate_invalidation_reasons(
                record,
                refreshed_facts,
                evaluation,
                include_non_admission_change=False,
                include_reunderwriting=True,
                include_failed_admission=True,
            )
            self._invalidate_candidate(record, reasons, refreshed_facts.boundary)
        self._candidate_retirements.add(record.state.candidate_identity)
        return self._finish_transition()

    def _settle_admission_record(
        self,
        record: _CandidateRecord,
        *,
        refreshed_facts: UnderwritingFacts,
        refresh_witness: AdmissionRefreshWitness,
        evaluation: _UnderwritingEvaluation,
    ) -> None:
        if not isinstance(record.attempt, AdmissionAttempt):
            raise TypeError("legacy admission settlement requires an atomic AdmissionAttempt")
        pre_refresh_reasons = self._candidate_invalidation_reasons(
            record,
            refreshed_facts,
            evaluation,
            include_non_admission_change=False,
            include_reunderwriting=False,
            include_failed_admission=False,
        )
        if pre_refresh_reasons:
            self._terminalize_candidate_before_refresh(
                record,
                reasons=pre_refresh_reasons,
                boundary=refreshed_facts.boundary,
            )
            return
        same_opportunity = (
            evaluation.slot_identity == record.slot_identity
            and refreshed_facts.canonical_combo_identity == record.facts.canonical_combo_identity
            and refreshed_facts.short_leg_identity == record.facts.short_leg_identity
            and refreshed_facts.long_leg_identity == record.facts.long_leg_identity
            and refreshed_facts.target_quantity_btc == record.facts.target_quantity_btc
            and refreshed_facts.entry_direction == record.facts.entry_direction
        )
        if (
            same_opportunity
            and evaluation.availability is UnderwritingAvailability.EVALUABLE
            and evaluation.action is UnderwritingAction.CANDIDATE
        ):
            classification = RefreshClassification.COMPLETE_CANDIDATE
        elif evaluation.availability is UnderwritingAvailability.EVALUABLE:
            classification = RefreshClassification.COMPLETE_NO_ENTRY
        elif evaluation.availability is UnderwritingAvailability.NOT_EVALUATED:
            classification = RefreshClassification.KNOWN_INVALIDATED
        else:
            classification = RefreshClassification.UNKNOWN
        if isinstance(refresh_witness, SubscriptionAdmissionRefreshWitness):
            accepted = record.attempt.accept_subscription_refresh(
                witness=refresh_witness,
                candidate_quote_witness=self._require_quote_witness(record.facts),
                classification=classification,
            )
        elif isinstance(refresh_witness, RpcAdmissionRefreshWitness):
            accepted = record.attempt.accept_response(
                witness=refresh_witness,
                response_budget_ms=(
                    self.policies.underwriting.component_book_snapshot_response_budget_ms
                ),
                classification=classification,
            )
        else:
            raise TypeError("admission refresh witness has an unsupported concrete type")
        if not accepted:
            return
        if isinstance(refresh_witness, SubscriptionAdmissionRefreshWitness):
            self._retirements.append(
                RpcRetirementIntent(
                    request_id=record.attempt.request_id,
                    boundary=refreshed_facts.boundary,
                )
            )
        self._emit_admission_terminal(record)
        if record.attempt.terminal_outcome is AdmissionTerminalOutcome.ENTRY_EMITTED:
            record.state.admit(refreshed_facts.boundary)
            if evaluation.economics is None:
                raise RuntimeError("Candidate admission lacks complete economics")
            self._create_admitted_trade(record, refreshed_facts, evaluation.economics)
        else:
            reasons = self._candidate_invalidation_reasons(
                record,
                refreshed_facts,
                evaluation,
                include_non_admission_change=False,
                include_reunderwriting=True,
                include_failed_admission=True,
            )
            self._invalidate_candidate(record, reasons, refreshed_facts.boundary)
        self._candidate_retirements.add(record.state.candidate_identity)

    def note_request_sent(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
    ) -> OwnerTransition:
        self._begin_transition()
        for candidate in self._candidates.values():
            if candidate.attempt.mark_sent(
                request_id=request_id,
                boundary=boundary,
                send_budget_ms=(self.policies.underwriting.component_book_snapshot_send_budget_ms),
            ):
                if candidate.attempt.terminal_outcome is not None:
                    self._retire_sibling_requests(candidate.attempt, request_id, boundary)
                    self._emit_admission_terminal(candidate)
                    self._invalidate_candidate(
                        candidate,
                        ("FAILED_ADMISSION_EVALUATION_CONSUMED",),
                        boundary,
                    )
                return self._finish_transition()
        for trade in self._trades.values():
            attempt = trade.post_close_attempt
            if attempt is not None and attempt.mark_sent(
                request_id=request_id,
                boundary=boundary,
                send_budget_ms=self.policies.position.component_book_snapshot_send_budget_ms,
            ):
                if attempt.terminal_status is not None:
                    self._retire_sibling_requests(attempt, request_id, boundary)
                    self._emit_post_close_terminal(trade)
                return self._finish_transition()
        return self._finish_transition()

    @staticmethod
    def _request_ids(
        attempt: (
            AdmissionAttempt
            | ComponentAdmissionAttempt
            | PostCloseAttempt
            | ComponentPostCloseAttempt
        ),
    ) -> tuple[int, ...]:
        if isinstance(attempt, (ComponentAdmissionAttempt, ComponentPostCloseAttempt)):
            return attempt.request_ids
        return (attempt.request_id,) if attempt.request_id is not None else ()

    def _retire_sibling_requests(
        self,
        attempt: (
            AdmissionAttempt
            | ComponentAdmissionAttempt
            | PostCloseAttempt
            | ComponentPostCloseAttempt
        ),
        terminal_request_id: int,
        boundary: FactBoundary,
    ) -> None:
        for request_id in self._request_ids(attempt):
            if request_id != terminal_request_id:
                self._retirements.append(RpcRetirementIntent(request_id, boundary))

    def accept_post_close_response(
        self,
        *,
        anchor_identity: str,
        refreshed_facts: PositionFacts,
        refresh_witness: RpcAdmissionRefreshWitness,
    ) -> OwnerTransition:
        """Route one matched post-CLOSE RPC response back to its owning trade."""
        trade = self._trades.get(anchor_identity)
        attempt = trade.post_close_attempt if trade is not None else None
        if (
            trade is None
            or not isinstance(attempt, PostCloseAttempt)
            or attempt.request_id != refresh_witness.request_id
            or refreshed_facts.quote_refresh_witness != refresh_witness
        ):
            self._begin_transition()
            return self._finish_transition()

        def reject_second_attempt() -> int:
            raise RuntimeError("post-CLOSE response cannot schedule another attempt")

        return self.settle_position(
            anchor_identity=anchor_identity,
            facts=refreshed_facts,
            allocate_request_id=reject_second_attempt,
        )

    def accept_component_post_close_response(
        self,
        *,
        anchor_identity: str,
        refreshed_facts: PositionFacts,
        pair_witness: ComponentBookPairWitness,
    ) -> OwnerTransition:
        trade = self._trades.get(anchor_identity)
        attempt = trade.post_close_attempt if trade is not None else None
        if (
            trade is None
            or not isinstance(attempt, ComponentPostCloseAttempt)
            or refreshed_facts.component_pair_witness != pair_witness
            or refreshed_facts.boundary != pair_witness.boundary
        ):
            self._begin_transition()
            return self._finish_transition()

        def reject_second_attempt() -> int:
            raise RuntimeError("component post-CLOSE response cannot schedule another attempt")

        return self.settle_position(
            anchor_identity=anchor_identity,
            facts=refreshed_facts,
            allocate_request_id=reject_second_attempt,
        )

    def note_request_failure(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
        terminal_status: PostCloseAttemptStatus = PostCloseAttemptStatus.ERROR,
    ) -> OwnerTransition:
        self._begin_transition()
        if terminal_status not in {
            PostCloseAttemptStatus.ERROR,
            PostCloseAttemptStatus.DEADLINE_LATE,
            PostCloseAttemptStatus.RETIRED,
        }:
            raise ValueError("request failure requires an ordinary terminal status")
        source_identity = canonical_identity(
            "DownstreamRequestFailureIdentity",
            request_id,
            terminal_status.value,
            boundary.as_object(),
        )
        for record in self._candidates.values():
            if request_id not in self._request_ids(record.attempt):
                continue
            if terminal_status is PostCloseAttemptStatus.RETIRED:
                transitioned = record.attempt.invalidate_before_refresh(
                    source_identity=source_identity,
                    boundary=boundary,
                )
                invalidation_reasons = ("SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN",)
            else:
                transitioned = record.attempt.fail_request(
                    request_id=request_id,
                    source_identity=source_identity,
                    boundary=boundary,
                )
                invalidation_reasons = ("FAILED_ADMISSION_EVALUATION_CONSUMED",)
            if transitioned:
                self._retire_sibling_requests(record.attempt, request_id, boundary)
                self._emit_admission_terminal(record)
                self._invalidate_candidate(
                    record,
                    invalidation_reasons,
                    boundary,
                )
                return self._finish_transition()
        for trade in self._trades.values():
            attempt = trade.post_close_attempt
            if attempt is not None and attempt.fail(
                request_id=request_id,
                status=terminal_status,
                boundary=boundary,
            ):
                self._retire_sibling_requests(attempt, request_id, boundary)
                self._emit_post_close_terminal(trade)
                return self._finish_transition()
        return self._finish_transition()

    def settle_position(
        self,
        *,
        anchor_identity: str,
        facts: PositionFacts,
        allocate_request_id: Callable[[], int],
    ) -> OwnerTransition:
        self._begin_transition()
        trade = self._trades.get(anchor_identity)
        if trade is None or trade.observation.state is not OutcomeState.PENDING:
            return self._finish_transition()
        if not facts.boundary.is_strictly_after(trade.entry_boundary):
            raise ValueError("Position facts must be strictly post-anchor")
        facts = self._normalize_position_facts(facts)
        attempt = trade.post_close_attempt
        refresh_terminalized = False
        pair_witness = facts.component_pair_witness
        if (
            isinstance(attempt, ComponentPostCloseAttempt)
            and pair_witness is not None
            and facts.component_short_quote_source is not None
            and facts.component_long_quote_source is not None
            and facts.component_short_quote_source.source_identity
            == pair_witness.short.source_identity
            and facts.component_short_quote_source.boundary == pair_witness.short.boundary
            and facts.component_long_quote_source.source_identity
            == pair_witness.long.source_identity
            and facts.component_long_quote_source.boundary == pair_witness.long.boundary
            and pair_witness.boundary == facts.boundary
            and attempt.accept_pair(
                witness=pair_witness,
                response_budget_ms=(
                    self.policies.position.component_book_snapshot_response_budget_ms
                ),
                maximum_source_skew_ms=(
                    self.policies.position.maximum_component_pair_source_skew_ms
                ),
                maximum_receive_skew_ms=(
                    self.policies.position.maximum_component_pair_receive_skew_ms
                ),
            )
        ):
            refresh_terminalized = True
        witness = facts.quote_refresh_witness
        if (
            witness is not None
            and facts.quote_source is not None
            and facts.quote_source.source_identity == witness.source_identity
            and facts.quote_source.boundary == witness.boundary
            and witness.boundary == facts.boundary
            and (
                not isinstance(witness, SubscriptionAdmissionRefreshWitness)
                or facts.current_combo_subscription_witness == witness
            )
        ):
            if (
                not isinstance(attempt, ComponentPostCloseAttempt)
                and attempt is not None
                and attempt.terminal_status is None
                and facts.boundary.is_strictly_after(attempt.origin_boundary)
                and attempt.accept_refresh(
                    witness=witness,
                    response_budget_ms=(
                        self.policies.position.component_book_snapshot_response_budget_ms
                    ),
                )
            ):
                refresh_terminalized = True
        post_close_quote_accepted = self._post_close_quote_is_accepted(trade, facts)
        accepted_subscription = facts.current_combo_subscription_witness
        if post_close_quote_accepted and accepted_subscription is not None:
            trade.last_accepted_subscription_witness = accepted_subscription
        normalized_quote = normalize_close_quote(facts.close_quote_facts)
        if (
            facts.close_quote_facts.option_availability is CloseOptionAvailability.TRADEABLE
            and facts.close_quote_facts.atomic_availability is CloseAtomicAvailability.ACTIVE
            and not post_close_quote_accepted
        ):
            normalized_quote = NormalizedCloseQuote(
                CloseQuoteState.UNKNOWN,
                (),
                (
                    CloseOptionAvailability.TRADEABLE.value,
                    CloseAtomicAvailability.ACTIVE.value,
                    "UNACCEPTED_ATOMIC_QUOTE_SOURCE",
                ),
            )
        quote_fingerprint = canonical_identity(
            "ConsumedRuleScopedQuoteFingerprint",
            *normalized_quote.fingerprint_members,
        )
        opportunity = self._opportunity(
            trade,
            facts,
            normalized_quote,
            post_close_quote_accepted=post_close_quote_accepted,
        )
        position_opportunity = self._opportunity(
            trade,
            facts,
            normalized_quote,
            post_close_quote_accepted=True,
        )
        fee_discontinuity = self._fee_discontinuity_truth(facts)
        truths = self._position_truths(
            trade,
            facts,
            normalized_quote,
            position_opportunity,
            fee_discontinuity=fee_discontinuity,
        )
        position_fingerprint = canonical_identity(
            "ConsumedPositionFactFingerprint",
            truths["SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED"].value,
            truths["LATEST_EXIT_BOUNDARY_REACHED"].value,
            facts.platform_continuous,
            facts.required_sources_continuous,
            facts.canonical_structure_intact,
            facts.short_leg_state,
            facts.long_leg_state,
            facts.short_leg_active,
            facts.long_leg_active,
            facts.current_index_usdc_per_btc,
            facts.current_short_delta,
            facts.current_short_mark_iv_fraction,
            fee_discontinuity.value,
            quote_fingerprint,
            position_opportunity.eligibility.value,
            position_opportunity.eligibility_reason,
            (
                {
                    "gross_close_cashflow_usdc": (
                        position_opportunity.economics.gross_close_cashflow_usdc
                    ),
                    "close_fee_reserve_usdc": (
                        position_opportunity.economics.close_fee_reserve_usdc
                    ),
                    "net_close_cashflow_usdc": (
                        position_opportunity.economics.net_close_cashflow_usdc
                    ),
                    "net_close_debit_usdc": (position_opportunity.economics.net_close_debit_usdc),
                    "projected_shadow_net_pnl_usdc": (
                        position_opportunity.economics.projected_shadow_net_pnl_usdc
                    ),
                    "projected_net_loss_usdc": (
                        position_opportunity.economics.projected_net_loss_usdc
                    ),
                }
                if position_opportunity.economics is not None
                else None
            ),
        )
        decision: PositionDecision | None = None
        if position_fingerprint != trade.last_position_fingerprint:
            decision = trade.position_state.evaluate(
                truths,
                facts.boundary,
                consumed_position_fact_fingerprint=position_fingerprint,
            )
            first_close_now = (
                decision.serialized_action == "CLOSE" and trade.first_close_decision is None
            )
            if first_close_now:
                trade.first_close_decision = decision
                trade.observation.latch_close(
                    decision.position_action_identity,
                    facts.boundary,
                )
                trade.post_close_attempt = self._create_post_close_attempt(
                    trade,
                    facts,
                    decision,
                    quote_source_accepted=post_close_quote_accepted,
                    allocate_request_id=allocate_request_id,
                )
            self._emit_position(trade, facts, decision, position_fingerprint)
            if first_close_now:
                if trade.post_close_attempt is None:
                    raise RuntimeError("first CLOSE did not create its one post-close attempt")
                self._emit_post_close_attempt(
                    trade,
                    facts,
                    decision,
                    trade.post_close_attempt,
                )
            trade.last_position_fingerprint = position_fingerprint
            if (
                facts.current_index_usdc_per_btc is not None
                and facts.current_index_usdc_per_btc.is_finite()
                and facts.current_index_usdc_per_btc > 0
                and facts.index_source is not None
            ):
                trade.prior_index = facts.current_index_usdc_per_btc
                trade.prior_index_source = facts.index_source
        quote_conditioning = (
            "PRE_CLOSE"
            if trade.first_close_decision is None
            or trade.first_close_decision.action_fact_boundary == facts.boundary
            else trade.first_close_decision.position_action_identity
        )
        quote_key = (quote_fingerprint, quote_conditioning)
        if quote_key != trade.last_quote_key and post_close_quote_accepted:
            trade.last_quote_identity = self._emit_close_quote(
                trade,
                facts,
                normalized_quote,
                quote_fingerprint,
                quote_conditioning,
            )
            trade.last_quote_fingerprint = quote_fingerprint
            trade.last_quote_facts = facts
            trade.last_quote_key = quote_key
        quote_identity = trade.last_quote_identity
        attempt = trade.post_close_attempt
        if refresh_terminalized:
            if attempt is None or not self._request_ids(attempt):
                raise RuntimeError("terminalized post-CLOSE refresh lacks its attempt")
            if (
                isinstance(attempt, PostCloseAttempt)
                and isinstance(witness, SubscriptionAdmissionRefreshWitness)
                and attempt.request_id is not None
            ):
                self._retirements.append(
                    RpcRetirementIntent(
                        request_id=attempt.request_id,
                        boundary=facts.boundary,
                    )
                )
            self._emit_post_close_terminal(trade)
        if (
            trade.first_close_decision is not None
            and facts.boundary.is_strictly_after(trade.first_close_decision.action_fact_boundary)
            and quote_identity is not None
            and post_close_quote_accepted
        ):
            opportunity_identity = self._emit_close_opportunity(
                trade,
                facts,
                quote_identity,
                opportunity,
            )
            if (
                opportunity_identity is not None
                and opportunity.eligibility is CloseOpportunityEligibility.ELIGIBLE
            ):
                self._select_exit_and_terminalize(
                    trade,
                    facts,
                    quote_identity,
                    opportunity_identity,
                    opportunity,
                )
        if (
            trade.observation.state is OutcomeState.PENDING
            and trade.first_close_decision is not None
            and facts.boundary.is_strictly_after(trade.first_close_decision.action_fact_boundary)
            and self._natural_lifecycle_ready(facts)
            and attempt is not None
            and attempt.terminal_owner is PostCloseAttemptOwner.ORDINARY
        ):
            state = trade.observation.settle_without_exit(
                boundary=facts.boundary,
                ordinary_attempt_terminal=True,
                lifecycle_ready=True,
            )
            if state is OutcomeState.MATURE_UNKNOWN:
                self._emit_terminal_trade(trade, facts=facts, opportunity=None)
        return self._finish_transition()

    def terminate(
        self,
        *,
        boundary: FactBoundary,
        terminal_source_identity: str,
        terminal_source: TerminalSource,
    ) -> OwnerTransition:
        self._begin_transition()
        require_identity(terminal_source_identity, "terminal_source_identity")
        if self._terminal_boundary is not None:
            if (
                boundary != self._terminal_boundary
                or terminal_source_identity != self._terminal_source_identity
                or terminal_source is not self._terminal_source_kind
            ):
                raise ValueError("terminal barrier is immutable")
            return self._finish_transition()
        self._terminal_boundary = boundary
        self._terminal_source_identity = terminal_source_identity
        self._terminal_source_kind = terminal_source
        self._accepting_new_work = False
        for record in self._candidates.values():
            if record.state.lifecycle.value != "VALID":
                continue
            record.attempt.invalidate_before_refresh(
                source_identity=terminal_source_identity,
                boundary=boundary,
            )
            self._emit_admission_terminal(record)
            self._invalidate_candidate(
                record,
                ("RUNTIME_OR_CODE_IDENTITY_CHANGED",),
                boundary,
            )
        owner = (
            PostCloseAttemptOwner.STOP
            if terminal_source is TerminalSource.STOP
            else PostCloseAttemptOwner.FAILURE
        )
        for trade in self._trades.values():
            if trade.observation.state is not OutcomeState.PENDING:
                continue
            if trade.post_close_attempt is not None:
                trade.post_close_attempt.censor(boundary=boundary, owner=owner)
                self._emit_post_close_terminal(trade)
            trade.observation.settle_without_exit(
                boundary=boundary,
                ordinary_attempt_terminal=False,
                lifecycle_ready=False,
                terminal_source=terminal_source,
            )
            self._emit_terminal_trade(
                trade,
                facts=None,
                opportunity=None,
                terminal_source_identity=terminal_source_identity,
            )
        return self._finish_transition()

    def _require_radar_episode_binding(self, facts: UnderwritingFacts) -> None:
        episode_identity = facts.active_episode_identity
        if episode_identity is None:
            return
        runtime_identity, policy_identity, instrument_name, activation_causal_seq = (
            _radar_episode_identity_components(episode_identity)
        )
        if (
            facts.boundary.runtime_identity != self.bindings.runtime_identity
            or runtime_identity != self.bindings.runtime_identity
            or policy_identity != self.bindings.radar_policy_identity
            or instrument_name != facts.short_leg_instrument_name
            or activation_causal_seq > facts.boundary.causal_seq
        ):
            raise IdentityError("Radar episode identity is not bound to its Underwriting facts")

    def _evaluate_underwriting(self, facts: UnderwritingFacts) -> _UnderwritingEvaluation:
        self._require_target_quantity_integrity(facts)
        if self._uses_component_books(facts):
            return self._evaluate_component_underwriting(facts)
        slot_identity = self._slot_identity(facts)
        slot_consumed = slot_identity is not None and slot_identity in self._slot_consumed
        known_negative = (
            facts.active_episode_identity is None
            or slot_consumed
            or facts.atomic_state
            in {
                "NOT_EVALUATED",
                "NO_ACTIVE_COMBO",
                "NO_TARGET_SIZE_CREDIT_QUOTE",
            }
            or self._known_structural_unavailability(facts)
            or (
                facts.expiry_ms is not None
                and facts.trusted_time_upper_ms is not None
                and facts.trusted_time_upper_ms >= facts.expiry_ms - ADMISSION_CUTOFF_LEAD_MS
            )
        )
        if known_negative:
            availability = UnderwritingAvailability.NOT_EVALUATED
        elif facts.atomic_state != "PUBLIC_ATOMIC_QUOTE_AVAILABLE" or not self._facts_complete(
            facts
        ):
            availability = UnderwritingAvailability.UNKNOWN
        else:
            availability = UnderwritingAvailability.EVALUABLE
        availability_fingerprint = canonical_identity(
            "ConsumedAvailabilityFactFingerprint",
            facts.active_episode_identity,
            slot_identity,
            "CONSUMED_BY_SHADOW_ENTRY" if slot_consumed else "AVAILABLE",
            facts.atomic_state,
            facts.option_catalog_complete,
            facts.combo_catalog_complete,
            facts.short_leg_state,
            facts.long_leg_state,
            facts.short_leg_active,
            facts.long_leg_active,
            facts.option_amounts_aligned,
            facts.combo_state,
            facts.combo_active,
            facts.combo_amount_aligned,
            facts.platform_usable,
            self._admission_time_class(facts),
            facts.short_leg_taker_commission_fraction,
            facts.long_leg_taker_commission_fraction,
            facts.unknown_reasons,
        )
        if availability is not UnderwritingAvailability.EVALUABLE:
            return _UnderwritingEvaluation(
                facts,
                availability,
                availability_fingerprint,
                slot_identity,
                None,
                None,
                None,
                None,
            )
        if (
            slot_identity is None
            or facts.canonical_combo_identity is None
            or facts.short_leg_identity is None
            or facts.long_leg_identity is None
            or facts.entry_direction is None
            or facts.short_strike_usdc_per_btc is None
            or facts.long_strike_usdc_per_btc is None
            or facts.index_usdc_per_btc is None
        ):
            raise RuntimeError("EVALUABLE Underwriting is incomplete")
        opportunity = canonical_identity(
            "UnderwritingOpportunityKeyIdentity",
            slot_identity,
            facts.canonical_combo_identity,
            [facts.short_leg_identity, facts.long_leg_identity],
        )
        economics = compute_entry_economics(
            direction=facts.entry_direction,
            full_quantity_btc=facts.target_quantity_btc,
            consumed_levels=facts.entry_consumed_levels,
            index_usdc_per_btc=facts.index_usdc_per_btc,
            short_strike_usdc_per_btc=facts.short_strike_usdc_per_btc,
            long_strike_usdc_per_btc=facts.long_strike_usdc_per_btc,
            fee_rate_index_fraction=self.policies.underwriting.fee_rate_index_fraction,
            future_cost_reserve_usdc=self.policies.underwriting.future_cost_reserve_usdc,
        )
        economic_fingerprint = canonical_identity(
            "ConsumedEconomicFactFingerprint",
            opportunity,
            facts.entry_direction,
            facts.target_quantity_btc,
            facts.entry_consumed_levels,
            facts.index_usdc_per_btc,
            facts.short_delta,
            facts.short_mark_iv_fraction,
            facts.short_leg_taker_commission_fraction,
            facts.long_leg_taker_commission_fraction,
            {
                "gross_entry_credit_usdc": economics.gross_entry_credit_usdc,
                "entry_fee_reserve_usdc": economics.entry_fee_reserve_usdc,
                "net_entry_credit_usdc": economics.net_entry_credit_usdc,
                "payoff_cap_usdc": economics.payoff_cap_usdc,
                "contractual_payoff_max_loss_ex_fees_usdc": (
                    economics.contractual_payoff_max_loss_ex_fees_usdc
                ),
                "entry_fee_reserved_payoff_loss_usdc": (
                    economics.entry_fee_reserved_payoff_loss_usdc
                ),
                "future_cost_reserve_usdc": economics.future_cost_reserve_usdc,
                "underwriting_reserved_loss_usdc": economics.underwriting_reserved_loss_usdc,
            },
        )
        action = classify_underwriting_action(
            availability=availability,
            net_entry_credit_usdc=economics.net_entry_credit_usdc,
            future_cost_reserve_usdc=economics.future_cost_reserve_usdc,
            underwriting_reserved_loss_usdc=economics.underwriting_reserved_loss_usdc,
            maximum_underwriting_reserved_loss_usdc=(
                self.policies.underwriting.maximum_underwriting_reserved_loss_usdc
            ),
            minimum_net_entry_credit_usdc=(
                self.policies.underwriting.minimum_net_entry_credit_usdc
            ),
            payoff_cap_usdc=economics.payoff_cap_usdc,
            minimum_net_credit_to_payoff_cap_fraction=(
                self.policies.underwriting.minimum_net_credit_to_payoff_cap_fraction
            ),
            consumed_level_count=len(facts.entry_consumed_levels),
            maximum_entry_consumed_level_count=(
                self.policies.underwriting.maximum_entry_consumed_level_count
            ),
        )
        return _UnderwritingEvaluation(
            facts,
            availability,
            availability_fingerprint,
            slot_identity,
            opportunity,
            economics,
            economic_fingerprint,
            action,
        )

    @staticmethod
    def _uses_component_books(facts: UnderwritingFacts) -> bool:
        return (
            facts.component_state != "NOT_EVALUATED"
            or facts.component_quote is not None
            or bool(facts.component_blockers)
        )

    def _evaluate_component_underwriting(
        self,
        facts: UnderwritingFacts,
    ) -> _UnderwritingEvaluation:
        slot_identity = self._slot_identity(facts)
        slot_consumed = slot_identity is not None and slot_identity in self._slot_consumed
        known_negative = (
            facts.active_episode_identity is None
            or slot_consumed
            or facts.component_state
            in {NO_PROTECTIVE_COMPONENT, NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE}
            or self._known_structural_unavailability(facts)
            or (
                facts.expiry_ms is not None
                and facts.trusted_time_upper_ms is not None
                and facts.trusted_time_upper_ms >= facts.expiry_ms - ADMISSION_CUTOFF_LEAD_MS
            )
        )
        if known_negative:
            availability = UnderwritingAvailability.NOT_EVALUATED
        elif (
            facts.component_state != COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE
            or not self._facts_complete(facts)
        ):
            availability = UnderwritingAvailability.UNKNOWN
        else:
            availability = UnderwritingAvailability.EVALUABLE
        availability_fingerprint = canonical_identity(
            "ConsumedComponentAvailabilityFactFingerprint",
            facts.active_episode_identity,
            slot_identity,
            "CONSUMED_BY_SHADOW_ENTRY" if slot_consumed else "AVAILABLE",
            facts.component_state,
            facts.component_blockers,
            facts.option_catalog_complete,
            facts.short_leg_state,
            facts.long_leg_state,
            facts.short_leg_active,
            facts.long_leg_active,
            facts.option_amounts_aligned,
            facts.platform_usable,
            self._admission_time_class(facts),
            facts.short_leg_taker_commission_fraction,
            facts.long_leg_taker_commission_fraction,
            facts.unknown_reasons,
        )
        if availability is not UnderwritingAvailability.EVALUABLE:
            return _UnderwritingEvaluation(
                facts,
                availability,
                availability_fingerprint,
                slot_identity,
                None,
                None,
                None,
                None,
            )
        quote = facts.component_quote
        if (
            quote is None
            or slot_identity is None
            or facts.short_leg_identity is None
            or facts.long_leg_identity is None
        ):
            raise RuntimeError("EVALUABLE component-book Underwriting is incomplete")
        opportunity = canonical_identity(
            "ComponentBookUnderwritingOpportunityKeyIdentity",
            slot_identity,
            quote.execution_model,
            [facts.short_leg_identity, facts.long_leg_identity],
        )
        economics = compute_component_entry_economics(
            quote=quote,
            future_cost_reserve_usdc=self.policies.underwriting.future_cost_reserve_usdc,
        )
        economic_fingerprint = canonical_identity(
            "ConsumedComponentEconomicFactFingerprint",
            opportunity,
            self._component_quote_fingerprint_members(quote),
            facts.short_delta,
            facts.short_mark_iv_fraction,
            facts.short_leg_taker_commission_fraction,
            facts.long_leg_taker_commission_fraction,
            {
                "contractual_payoff_max_loss_ex_fees_usdc": (
                    economics.contractual_payoff_max_loss_ex_fees_usdc
                ),
                "entry_fee_reserved_payoff_loss_usdc": (
                    economics.entry_fee_reserved_payoff_loss_usdc
                ),
                "future_cost_reserve_usdc": economics.future_cost_reserve_usdc,
                "underwriting_reserved_loss_usdc": economics.underwriting_reserved_loss_usdc,
            },
        )
        action = classify_underwriting_action(
            availability=availability,
            net_entry_credit_usdc=economics.net_entry_credit_usdc,
            future_cost_reserve_usdc=economics.future_cost_reserve_usdc,
            underwriting_reserved_loss_usdc=economics.underwriting_reserved_loss_usdc,
            maximum_underwriting_reserved_loss_usdc=(
                self.policies.underwriting.maximum_underwriting_reserved_loss_usdc
            ),
            minimum_net_entry_credit_usdc=(
                self.policies.underwriting.minimum_net_entry_credit_usdc
            ),
            payoff_cap_usdc=economics.payoff_cap_usdc,
            minimum_net_credit_to_payoff_cap_fraction=(
                self.policies.underwriting.minimum_net_credit_to_payoff_cap_fraction
            ),
            consumed_level_count=quote.consumed_level_count,
            maximum_entry_consumed_level_count=(
                self.policies.underwriting.maximum_entry_consumed_level_count
            ),
        )
        return _UnderwritingEvaluation(
            facts,
            availability,
            availability_fingerprint,
            slot_identity,
            opportunity,
            economics,
            economic_fingerprint,
            action,
        )

    @staticmethod
    def _component_quote_fingerprint_members(
        quote: ComponentBookVerticalQuote,
    ) -> dict[str, object]:
        return quote.fingerprint_members

    @staticmethod
    def _admission_time_class(facts: UnderwritingFacts) -> str:
        if facts.expiry_ms is None or facts.trusted_time_upper_ms is None:
            return "UNKNOWN"
        if facts.trusted_time_upper_ms >= facts.expiry_ms - ADMISSION_CUTOFF_LEAD_MS:
            return "LATEST_ADMISSION_BOUNDARY_REACHED"
        return "BEFORE_LATEST_ADMISSION_BOUNDARY"

    def _require_target_quantity_integrity(self, facts: UnderwritingFacts) -> None:
        expected = (
            self.policies.radar.target_base_quantity_btc,
            self.policies.underwriting.target_base_quantity_btc,
            self.policies.position.target_base_quantity_btc,
        )
        if any(facts.target_quantity_btc != target for target in expected):
            raise RuntimeError(
                "Underwriting facts target quantity differs from the frozen Policy chain"
            )

    def _facts_complete(self, facts: UnderwritingFacts) -> bool:
        short_strike = facts.short_strike_usdc_per_btc
        long_strike = facts.long_strike_usdc_per_btc
        short_commission = facts.short_leg_taker_commission_fraction
        long_commission = facts.long_leg_taker_commission_fraction
        index = facts.index_usdc_per_btc
        short_delta = facts.short_delta
        short_iv = facts.short_mark_iv_fraction
        decimals = (
            short_strike,
            long_strike,
            short_commission,
            long_commission,
            index,
            short_delta,
            short_iv,
        )
        if self._uses_component_books(facts):
            quote = facts.component_quote
            return (
                facts.active_episode_identity is not None
                and facts.short_leg_identity is not None
                and facts.long_leg_identity is not None
                and facts.short_leg_instrument_name is not None
                and facts.long_leg_instrument_name is not None
                and facts.expiry_ms is not None
                and facts.entry_direction == "SELL"
                and quote is not None
                and quote.kind is ComponentBookQuoteKind.ENTRY
                and quote.execution_model == self.policies.underwriting.execution_model
                and quote.full_quantity_btc == facts.target_quantity_btc
                and quote.short_leg.instrument_name == facts.short_leg_instrument_name
                and quote.long_leg.instrument_name == facts.long_leg_instrument_name
                and facts.option_catalog_complete
                and facts.short_leg_state == "open"
                and facts.long_leg_state == "open"
                and facts.short_leg_active is True
                and facts.long_leg_active is True
                and facts.option_amounts_aligned is True
                and facts.platform_usable is True
                and facts.trusted_time_lower_ms is not None
                and facts.trusted_time_upper_ms is not None
                and facts.component_short_quote_source is not None
                and facts.component_long_quote_source is not None
                and facts.short_instrument_source is not None
                and facts.long_instrument_source is not None
                and facts.index_source is not None
                and facts.ticker_source is not None
                and not facts.unknown_reasons
                and all(value is not None and value.is_finite() for value in decimals)
                and short_commission is not None
                and 0 <= short_commission <= self.policies.underwriting.fee_rate_index_fraction
                and long_commission is not None
                and 0 <= long_commission <= self.policies.underwriting.fee_rate_index_fraction
                and index is not None
                and index > 0
                and short_delta is not None
                and abs(short_delta) <= 1
                and short_iv is not None
                and short_iv >= 0
            )
        return (
            facts.active_episode_identity is not None
            and facts.short_leg_identity is not None
            and facts.long_leg_identity is not None
            and facts.canonical_combo_identity is not None
            and facts.combo_instrument_name is not None
            and facts.expiry_ms is not None
            and facts.entry_direction is not None
            and bool(facts.entry_consumed_levels)
            and facts.option_catalog_complete
            and facts.combo_catalog_complete
            and facts.short_leg_state == "open"
            and facts.long_leg_state == "open"
            and facts.short_leg_active is True
            and facts.long_leg_active is True
            and facts.option_amounts_aligned is True
            and facts.combo_state == "open"
            and facts.combo_active is True
            and facts.combo_amount_aligned is True
            and facts.platform_usable is True
            and facts.trusted_time_lower_ms is not None
            and facts.trusted_time_upper_ms is not None
            and facts.quote_source is not None
            and facts.quote_refresh_witness is not None
            and facts.quote_source.source_identity == facts.quote_refresh_witness.source_identity
            and facts.quote_source.boundary == facts.quote_refresh_witness.boundary
            and facts.short_instrument_source is not None
            and facts.long_instrument_source is not None
            and facts.index_source is not None
            and facts.ticker_source is not None
            and not facts.unknown_reasons
            and all(value is not None and value.is_finite() for value in decimals)
            and short_commission is not None
            and short_commission >= 0
            and short_commission <= self.policies.underwriting.fee_rate_index_fraction
            and long_commission is not None
            and long_commission >= 0
            and long_commission <= self.policies.underwriting.fee_rate_index_fraction
            and index is not None
            and index > 0
            and short_delta is not None
            and abs(short_delta) <= 1
            and short_iv is not None
            and short_iv >= 0
        )

    @staticmethod
    def _known_structural_unavailability(facts: UnderwritingFacts) -> bool:
        known_states = {
            "open",
            "settlement",
            "delivered",
            "archivized",
            "inactive",
            "locked",
            "halted",
        }
        common = (
            facts.short_leg_state in known_states - {"open"}
            or facts.long_leg_state in known_states - {"open"}
            or facts.short_leg_active is False
            or facts.long_leg_active is False
            or facts.option_amounts_aligned is False
        )
        if FixedContractShadowOwner._uses_component_books(facts):
            return common
        return (
            common
            or facts.combo_state in known_states - {"open"}
            or facts.combo_active is False
            or facts.combo_amount_aligned is False
        )

    def _slot_identity(self, facts: UnderwritingFacts) -> str | None:
        if facts.active_episode_identity is None or facts.short_leg_identity is None:
            return None
        return canonical_identity(
            "UnderwritingPositionSlotKeyIdentity",
            self.bindings.runtime_identity,
            self.bindings.radar_policy_identity,
            facts.active_episode_identity,
            facts.short_leg_identity,
            facts.target_quantity_btc,
        )

    def _emit_availability(self, evaluation: _UnderwritingEvaluation) -> str:
        facts = evaluation.facts
        identity = canonical_identity(
            "UnderwritingAvailabilityEvaluationIdentity",
            self.bindings.runtime_identity,
            self.bindings.radar_policy_identity,
            self.bindings.underwriting_policy_identity,
            self.bindings.position_policy_identity,
            facts.radar_scope_identity,
            evaluation.availability_fingerprint,
            evaluation.availability.value,
            facts.boundary.as_object(),
        )
        last = self._last_availability.get(facts.radar_scope_identity)
        if (
            last is not None
            and last[0] == evaluation.availability_fingerprint
            and last[1] is evaluation.availability
        ):
            return last[2]
        self._last_availability[facts.radar_scope_identity] = (
            evaluation.availability_fingerprint,
            evaluation.availability,
            identity,
        )
        payload: dict[str, object] = {
            "underwriting_availability_evaluation_identity": identity,
            "radar_scope_or_short_leg_identity": facts.radar_scope_identity,
            "active_episode_identity": facts.active_episode_identity,
            "consumed_availability_fact_fingerprint": evaluation.availability_fingerprint,
            "availability": evaluation.availability.value,
            "availability_evaluation_fact_boundary": facts.boundary.as_object(),
            "component_state": facts.component_state,
            "component_blockers": list(facts.component_blockers),
            "structure_reviewable": (
                facts.short_leg_identity is not None and facts.long_leg_identity is not None
            ),
            "component_book_counterfactual_evaluable": (
                facts.component_state == COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE
            ),
            "atomic_state_diagnostic": facts.atomic_state,
            "unknown_reasons": list(facts.unknown_reasons),
        }
        self._emit(
            "UNDERWRITING_AVAILABILITY_EVALUATION",
            identity,
            facts.boundary,
            payload,
        )
        self._counts[
            f"underwriting_availability_{evaluation.availability.value.lower()}_count"
        ] += 1
        return identity

    def _emit_underwriting_action(
        self,
        evaluation: _UnderwritingEvaluation,
        *,
        availability_identity: str,
    ) -> tuple[str, bool]:
        if (
            evaluation.action is None
            or evaluation.opportunity_identity is None
            or evaluation.economics is None
            or evaluation.economic_fingerprint is None
        ):
            raise RuntimeError("Underwriting action requires complete evaluation")
        facts = evaluation.facts
        previous = self._last_underwriting_action.get(facts.radar_scope_identity)
        if (
            previous is not None
            and previous[0] == evaluation.economic_fingerprint
            and previous[1] is evaluation.action
        ):
            return previous[2], False
        underwriting_evaluation_identity = canonical_identity(
            "UnderwritingEvaluationIdentity",
            evaluation.opportunity_identity,
            self.bindings.underwriting_policy_identity,
            self.bindings.position_policy_identity,
            facts.protective_leg_selection_rule_identity,
            facts.candidate_protective_leg_count,
            evaluation.economic_fingerprint,
            facts.boundary.as_object(),
        )
        identity = canonical_identity(
            "UnderwritingActionIdentity",
            underwriting_evaluation_identity,
            evaluation.action.value,
        )
        economics = evaluation.economics
        margins = self._underwriting_threshold_margins(evaluation)
        payload = {
            "underwriting_action_identity": identity,
            "underwriting_availability_evaluation_identity": availability_identity,
            "underwriting_opportunity_key_identity": evaluation.opportunity_identity,
            "active_episode_identity": facts.active_episode_identity,
            "consumed_economic_fact_fingerprint": evaluation.economic_fingerprint,
            "economic_action": evaluation.action.value,
            "decision_blockers": list(
                self._underwriting_decision_blockers(evaluation, margins.failed_predicates)
            ),
            "failed_predicates": list(margins.failed_predicates),
            "predicate_margin_vector": list(margins.as_vector()),
            "selected_long_leg_instrument_name": facts.long_leg_instrument_name,
            "protective_leg_selection_rule_identity": (
                facts.protective_leg_selection_rule_identity
            ),
            "candidate_protective_leg_count": facts.candidate_protective_leg_count,
            "entry_consumed_level_count": self._entry_consumed_level_count(facts),
            "evaluation_fact_boundary": facts.boundary.as_object(),
            "gross_entry_credit_usdc": economics.gross_entry_credit_usdc,
            "entry_fee_reserve_usdc": economics.entry_fee_reserve_usdc,
            "net_entry_credit_usdc": economics.net_entry_credit_usdc,
            "width_usdc_per_btc": economics.width_usdc_per_btc,
            "payoff_cap_usdc": economics.payoff_cap_usdc,
            "contractual_payoff_max_loss_ex_fees_usdc": (
                economics.contractual_payoff_max_loss_ex_fees_usdc
            ),
            "entry_fee_reserved_payoff_loss_usdc": (economics.entry_fee_reserved_payoff_loss_usdc),
            "future_cost_reserve_usdc": economics.future_cost_reserve_usdc,
            "underwriting_reserved_loss_usdc": economics.underwriting_reserved_loss_usdc,
            "actual_all_in_max_loss_usdc": None,
            "actual_all_in_max_loss_availability": "UNKNOWN",
        }
        self._emit(
            "UNDERWRITING_ACTION",
            identity,
            facts.boundary,
            payload,
        )
        self._counts[f"underwriting_action_{evaluation.action.value.lower()}_count"] += 1
        self._last_underwriting_action[facts.radar_scope_identity] = (
            evaluation.economic_fingerprint,
            evaluation.action,
            identity,
        )
        return identity, True

    def _underwriting_decision_blockers(
        self,
        evaluation: _UnderwritingEvaluation,
        failed_predicates: tuple[str, ...],
    ) -> tuple[str, ...]:
        action = evaluation.action
        if action is None:
            return ()
        abstain_predicates = {
            "NON_POSITIVE_NET_ENTRY_CREDIT",
            "CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE",
            "UNDERWRITING_RESERVED_LOSS_LIMIT",
        }
        watch_predicates = {
            "MINIMUM_NET_ENTRY_CREDIT",
            "MINIMUM_NET_CREDIT_TO_PAYOFF_CAP",
            "ENTRY_CONSUMED_LEVEL_LIMIT",
        }
        if action is UnderwritingAction.ABSTAIN:
            return tuple(value for value in failed_predicates if value in abstain_predicates)
        if action is UnderwritingAction.WATCH:
            return tuple(value for value in failed_predicates if value in watch_predicates)
        return ()

    def _underwriting_threshold_margins(
        self,
        evaluation: _UnderwritingEvaluation,
    ) -> UnderwritingThresholdMargins:
        economics = evaluation.economics
        if economics is None:
            raise RuntimeError("Underwriting margins require complete economics")
        policy = self.policies.underwriting
        return underwriting_threshold_margins(
            economics=economics,
            consumed_level_count=self._entry_consumed_level_count(evaluation.facts),
            maximum_underwriting_reserved_loss_usdc=(
                policy.maximum_underwriting_reserved_loss_usdc
            ),
            minimum_net_entry_credit_usdc=policy.minimum_net_entry_credit_usdc,
            minimum_net_credit_to_payoff_cap_fraction=(
                policy.minimum_net_credit_to_payoff_cap_fraction
            ),
            maximum_entry_consumed_level_count=policy.maximum_entry_consumed_level_count,
        )

    @staticmethod
    def _entry_consumed_level_count(facts: UnderwritingFacts) -> int:
        if facts.component_quote is not None:
            return facts.component_quote.consumed_level_count
        return len(facts.entry_consumed_levels)

    def _activate_candidate(
        self,
        evaluation: _UnderwritingEvaluation,
        *,
        action_identity: str,
        allocate_request_id: Callable[[], int],
    ) -> None:
        facts = evaluation.facts
        if evaluation.slot_identity is None or evaluation.economic_fingerprint is None:
            raise RuntimeError("Candidate requires slot and economic identities")
        candidate_identity = canonical_identity(
            "CandidateIdentity",
            action_identity,
            facts.boundary.as_object(),
        )
        if candidate_identity in self._candidates:
            return
        if self._uses_component_books(facts):
            if (
                facts.short_leg_identity is None
                or facts.long_leg_identity is None
                or facts.short_leg_instrument_name is None
                or facts.long_leg_instrument_name is None
            ):
                raise RuntimeError("component Candidate requires one frozen two-leg structure")
            component_attempt = ComponentAdmissionAttempt.schedule(
                candidate_identity=candidate_identity,
                short_option_identity=facts.short_leg_identity,
                long_option_identity=facts.long_leg_identity,
                short_request_id=allocate_request_id(),
                long_request_id=allocate_request_id(),
                boundary=facts.boundary,
                short_instrument_name=facts.short_leg_instrument_name,
                long_instrument_name=facts.long_leg_instrument_name,
            )
            attempt: AdmissionAttempt | ComponentAdmissionAttempt = component_attempt
            intents = component_attempt.take_request_intents()
        else:
            if facts.canonical_combo_identity is None or facts.combo_instrument_name is None:
                raise RuntimeError("atomic Candidate requires combo and instrument identities")
            attempt = AdmissionAttempt.schedule(
                candidate_identity=candidate_identity,
                canonical_combo_identity=facts.canonical_combo_identity,
                request_id=allocate_request_id(),
                boundary=facts.boundary,
                request_instrument_name=facts.combo_instrument_name,
            )
            intent = attempt.take_request_intent()
            intents = () if intent is None else (intent,)
        record = _CandidateRecord(
            facts=facts,
            state=CandidateState(candidate_identity),
            slot_identity=evaluation.slot_identity,
            attempt=attempt,
            availability_fingerprint=evaluation.availability_fingerprint,
            economic_fingerprint=evaluation.economic_fingerprint,
        )
        self._candidates[candidate_identity] = record
        if not intents:
            raise RuntimeError("new admission attempt did not expose request intents")
        self._emit(
            "CANDIDATE_ACTIVATION",
            candidate_identity,
            facts.boundary,
            {
                "candidate_identity": candidate_identity,
                "underwriting_action_identity": action_identity,
                "underwriting_position_slot_key_identity": evaluation.slot_identity,
                "active_episode_identity": facts.active_episode_identity,
                "candidate_activation_fact_boundary": facts.boundary.as_object(),
            },
        )
        self._emit(
            "ADMISSION_ATTEMPT_SCHEDULED",
            attempt.scheduled_identity,
            facts.boundary,
            {
                "scheduled_admission_attempt_identity": attempt.scheduled_identity,
                "candidate_identity": candidate_identity,
                "execution_model": (
                    facts.component_quote.execution_model
                    if facts.component_quote is not None
                    else "PUBLIC_ATOMIC_COMBO"
                ),
                "request_method": "public/get_order_book",
                "requests": [
                    {"request_id": intent.request_id, "request_params": dict(intent.params)}
                    for intent in intents
                ],
                "schedule_fact_boundary": facts.boundary.as_object(),
            },
        )
        self._intents.extend(intents)
        self._counts["candidate_count"] += 1

    def _create_admitted_trade(
        self,
        candidate: _CandidateRecord,
        facts: UnderwritingFacts,
        economics: EntryEconomics,
    ) -> None:
        attempt = candidate.attempt
        quote_source = facts.quote_source
        index_source = facts.index_source
        ticker_source = facts.ticker_source
        component_quote = facts.component_quote
        component_sources = (
            facts.component_short_quote_source,
            facts.component_long_quote_source,
        )
        if (
            attempt.terminal_identity is None
            or index_source is None
            or ticker_source is None
            or (component_quote is None and quote_source is None)
            or (
                component_quote is not None
                and (
                    any(source is None for source in component_sources)
                    or facts.component_pair_witness is None
                )
            )
        ):
            raise RuntimeError("Entry requires terminal admission identity and complete sources")
        entry_identity = canonical_identity(
            "ShadowEntryIdentity",
            candidate.state.candidate_identity,
            facts.boundary.as_object(),
        )
        payload = {
            "shadow_entry_identity": entry_identity,
            "candidate_identity": candidate.state.candidate_identity,
            "admission_attempt_terminal_identity": attempt.terminal_identity,
            "underwriting_position_slot_key_identity": candidate.slot_identity,
            "entry_fact_boundary": facts.boundary.as_object(),
            "active_episode_identity": facts.active_episode_identity,
            "radar_scope_identity": facts.radar_scope_identity,
            "execution_model": (
                component_quote.execution_model
                if component_quote is not None
                else "PUBLIC_ATOMIC_COMBO"
            ),
            "component_state": facts.component_state,
            "atomic_state_diagnostic": facts.atomic_state,
            "radar_band_id": facts.radar_band_id,
            "radar_richness_interval": (
                {
                    "lower": facts.radar_richness_lower,
                    "upper": facts.radar_richness_upper,
                }
                if facts.radar_richness_lower is not None and facts.radar_richness_upper is not None
                else None
            ),
            "canonical_combo_identity": facts.canonical_combo_identity,
            "combo_instrument_name": facts.combo_instrument_name,
            "short_leg_instrument_name": facts.short_leg_instrument_name,
            "long_leg_instrument_name": facts.long_leg_instrument_name,
            "expiry_ms": facts.expiry_ms,
            "option_type": facts.option_type,
            "short_strike_usdc_per_btc": facts.short_strike_usdc_per_btc,
            "long_strike_usdc_per_btc": facts.long_strike_usdc_per_btc,
            "canonical_leg_identities": [
                facts.short_leg_identity,
                facts.long_leg_identity,
            ],
            "entry_direction": facts.entry_direction,
            "full_quantity_btc": facts.target_quantity_btc,
            "entry_consumed_levels": (
                self._levels(facts.entry_consumed_levels) if component_quote is None else []
            ),
            "entry_combo_quote_source_ref": (
                quote_source.as_ref() if quote_source is not None else None
            ),
            "entry_component_pair_identity": (
                facts.component_pair_witness.pair_identity
                if facts.component_pair_witness is not None
                else None
            ),
            "entry_component_pair_timing": (
                facts.component_pair_witness.timing_as_object()
                if facts.component_pair_witness is not None
                else None
            ),
            "entry_component_legs": (
                [
                    self._component_leg_payload("SHORT", component_quote.short_leg),
                    self._component_leg_payload("LONG", component_quote.long_leg),
                ]
                if component_quote is not None
                else []
            ),
            "entry_component_quote_source_refs": (
                [
                    {"canonical_leg_role": role, **source.as_ref()}
                    for role, source in zip(
                        ("SHORT", "LONG"),
                        component_sources,
                        strict=True,
                    )
                    if source is not None
                ]
                if component_quote is not None
                else []
            ),
            "entry_commission_source_refs": self._commission_refs(facts),
            "entry_index_usdc_per_btc": facts.index_usdc_per_btc,
            "entry_index_source_ref": index_source.as_ref(),
            "entry_short_leg_mark_iv_fraction": facts.short_mark_iv_fraction,
            "entry_short_leg_mark_iv_source_ref": ticker_source.as_ref(),
            "gross_entry_credit_usdc": economics.gross_entry_credit_usdc,
            "entry_fee_reserve_usdc": economics.entry_fee_reserve_usdc,
            "net_entry_credit_usdc": economics.net_entry_credit_usdc,
            "width_usdc_per_btc": economics.width_usdc_per_btc,
            "payoff_cap_usdc": economics.payoff_cap_usdc,
            "contractual_payoff_max_loss_ex_fees_usdc": (
                economics.contractual_payoff_max_loss_ex_fees_usdc
            ),
            "entry_fee_reserved_payoff_loss_usdc": (economics.entry_fee_reserved_payoff_loss_usdc),
            "future_cost_reserve_usdc": economics.future_cost_reserve_usdc,
            "underwriting_reserved_loss_usdc": economics.underwriting_reserved_loss_usdc,
            "actual_all_in_max_loss_usdc": None,
            "actual_all_in_max_loss_availability": "UNKNOWN",
            "non_claims": (
                [
                    "NOT_AN_ORDER",
                    "NOT_A_FILL",
                    "NOT_AN_ATOMIC_QUOTE",
                    "NO_LIQUIDITY_RESERVATION",
                    "ATOMIC_EXECUTABILITY_UNPROVEN",
                ]
                if component_quote is not None
                else []
            ),
        }
        self._emit(
            "SHADOW_ENTRY",
            entry_identity,
            facts.boundary,
            payload,
        )
        self._slot_consumed.add(candidate.slot_identity)
        episode_identity = facts.active_episode_identity
        if episode_identity is None:
            raise RuntimeError("admitted Candidate lacks its active Radar episode")
        self._consumed_slots_by_episode.setdefault(episode_identity, set()).add(
            candidate.slot_identity
        )
        self._counts["shadow_entry_count"] += 1
        self._create_trade_record(
            anchor_identity=entry_identity,
            slot_identity=candidate.slot_identity,
            facts=facts,
            economics=economics,
        )
        for other in self._candidates.values():
            if (
                other is not candidate
                and other.slot_identity == candidate.slot_identity
                and other.state.lifecycle.value == "VALID"
            ):
                other.attempt.invalidate_before_refresh(
                    source_identity=entry_identity,
                    boundary=facts.boundary,
                )
                self._emit_admission_terminal(other)
                self._invalidate_candidate(
                    other,
                    ("POSITION_SLOT_CONSUMED_BY_SHADOW_ENTRY",),
                    facts.boundary,
                )

    def _create_trade_record(
        self,
        *,
        anchor_identity: str,
        slot_identity: str,
        facts: UnderwritingFacts,
        economics: EntryEconomics,
    ) -> None:
        if facts.index_usdc_per_btc is None or facts.index_source is None:
            raise RuntimeError("trade anchor requires a known entry index")
        observation = Observation.admitted(
            outcome_contract_identity=self.bindings.outcome_contract_identity,
            shadow_entry_identity=anchor_identity,
            entry_boundary=facts.boundary,
        )
        record = _TradeRecord(
            anchor_identity=anchor_identity,
            slot_identity=slot_identity,
            entry_boundary=facts.boundary,
            entry_facts=facts,
            entry_economics=economics,
            observation=observation,
            position_state=PositionDecisionState(
                shadow_entry_identity=anchor_identity,
                position_policy_identity=self.bindings.position_policy_identity,
                entry_boundary=facts.boundary,
            ),
            prior_index=facts.index_usdc_per_btc,
            prior_index_source=facts.index_source,
            last_accepted_subscription_witness=(
                facts.quote_refresh_witness
                if isinstance(
                    facts.quote_refresh_witness,
                    SubscriptionAdmissionRefreshWitness,
                )
                and facts.quote_refresh_witness.canonical_combo_identity
                == facts.canonical_combo_identity
                and facts.quote_refresh_witness.instrument_name == facts.combo_instrument_name
                else None
            ),
        )
        self._trades[anchor_identity] = record
        self._emit(
            "SHADOW_OUTCOME_OBSERVATION",
            observation.observation_identity,
            facts.boundary,
            {
                "shadow_observation_identity": observation.observation_identity,
                "shadow_entry_identity": anchor_identity,
                "start_fact_boundary": facts.boundary.as_object(),
                "lifecycle_state": "PENDING",
            },
        )

    def _position_truths(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        quote: NormalizedCloseQuote,
        opportunity: CloseOpportunity,
        *,
        fee_discontinuity: PredicateTruth,
    ) -> dict[str, PredicateTruth]:
        quote_state = quote.state
        expiry = trade.entry_facts.expiry_ms
        terminal_leg = {"settlement", "delivered", "archivized"}
        known_leg = terminal_leg | {"open", "inactive", "locked", "halted"}
        if (
            facts.short_leg_state in terminal_leg
            or facts.long_leg_state in terminal_leg
            or (
                expiry is not None
                and facts.trusted_time_lower_ms is not None
                and facts.trusted_time_lower_ms >= expiry
            )
        ):
            settlement = PredicateTruth.TRUE
        elif (
            expiry is not None
            and facts.trusted_time_upper_ms is not None
            and facts.trusted_time_upper_ms < expiry
            and facts.short_leg_state in known_leg
            and facts.long_leg_state in known_leg
        ):
            settlement = PredicateTruth.FALSE
        else:
            settlement = PredicateTruth.UNKNOWN
        if expiry is None or facts.trusted_time_upper_ms is None:
            latest = PredicateTruth.UNKNOWN
        elif facts.trusted_time_upper_ms >= expiry - self.policies.position.latest_exit_lead_ms:
            latest = PredicateTruth.TRUE
        else:
            latest = PredicateTruth.FALSE
        continuity_values = (
            facts.platform_continuous,
            facts.required_sources_continuous,
            facts.canonical_structure_intact,
        )
        leg_discontinuity = tuple(
            self._option_lifecycle_discontinuity(state, active)
            for state, active in (
                (facts.short_leg_state, facts.short_leg_active),
                (facts.long_leg_state, facts.long_leg_active),
            )
        )
        if (
            any(value is False for value in continuity_values)
            or any(value is PredicateTruth.TRUE for value in leg_discontinuity)
            or fee_discontinuity is PredicateTruth.TRUE
        ):
            discontinuity = PredicateTruth.TRUE
        elif (
            all(value is True for value in continuity_values)
            and all(value is PredicateTruth.FALSE for value in leg_discontinuity)
            and fee_discontinuity is PredicateTruth.FALSE
        ):
            discontinuity = PredicateTruth.FALSE
        else:
            discontinuity = PredicateTruth.UNKNOWN
        if opportunity.economics is None:
            maximum_loss = PredicateTruth.UNKNOWN
        elif (
            opportunity.economics.projected_net_loss_usdc
            >= self.policies.position.maximum_projected_net_loss_usdc
        ):
            maximum_loss = PredicateTruth.TRUE
        else:
            maximum_loss = PredicateTruth.FALSE
        entry = trade.entry_facts
        if (
            facts.current_short_delta is None
            or facts.current_index_usdc_per_btc is None
            or entry.short_strike_usdc_per_btc is None
            or entry.option_type is None
        ):
            short_risk = PredicateTruth.UNKNOWN
        else:
            strike_reached = (
                facts.current_index_usdc_per_btc >= entry.short_strike_usdc_per_btc
                if entry.option_type == "call"
                else facts.current_index_usdc_per_btc <= entry.short_strike_usdc_per_btc
            )
            short_risk = (
                PredicateTruth.TRUE
                if (
                    abs(facts.current_short_delta)
                    >= self.policies.position.maximum_absolute_short_delta
                    or strike_reached
                )
                else PredicateTruth.FALSE
            )
        if facts.current_index_usdc_per_btc is None or entry.index_usdc_per_btc is None:
            path = PredicateTruth.UNKNOWN
        else:
            entry_move = abs(facts.current_index_usdc_per_btc - entry.index_usdc_per_btc)
            prior_move = abs(facts.current_index_usdc_per_btc - trade.prior_index)
            prior_return_limit = (
                self.policies.position.maximum_absolute_index_return_since_prior_evaluation_fraction
            )
            path = (
                PredicateTruth.TRUE
                if (
                    entry_move
                    >= (
                        self.policies.position.maximum_absolute_index_return_since_entry_fraction
                        * entry.index_usdc_per_btc
                    )
                    or prior_move >= (prior_return_limit * trade.prior_index)
                )
                else PredicateTruth.FALSE
            )
        if facts.current_short_mark_iv_fraction is None or entry.short_mark_iv_fraction is None:
            volatility = PredicateTruth.UNKNOWN
        else:
            volatility = (
                PredicateTruth.TRUE
                if (
                    facts.current_short_mark_iv_fraction - entry.short_mark_iv_fraction
                    >= self.policies.position.maximum_short_mark_iv_increase_fraction
                )
                else PredicateTruth.FALSE
            )
        if quote_state in {
            CloseQuoteState.UNEXECUTABLE,
            CloseQuoteState.LEGGED_CLOSE_REFERENCE,
        }:
            liquidity = PredicateTruth.TRUE
        elif quote_state is CloseQuoteState.UNKNOWN:
            liquidity = PredicateTruth.UNKNOWN
        else:
            liquidity = (
                PredicateTruth.TRUE
                if len(quote.consumed_levels)
                > self.policies.position.maximum_close_consumed_level_count
                else PredicateTruth.FALSE
            )
        if opportunity.economics is None:
            economic = PredicateTruth.UNKNOWN
        else:
            economics = opportunity.economics
            economic = (
                PredicateTruth.TRUE
                if (
                    economics.projected_shadow_net_pnl_usdc
                    >= self.policies.position.minimum_take_profit_usdc
                    or economics.net_close_debit_usdc
                    <= (
                        self.policies.position.maximum_remaining_premium_fraction
                        * trade.entry_economics.net_entry_credit_usdc
                    )
                )
                else PredicateTruth.FALSE
            )
        return dict(
            zip(
                POSITION_CLOSE_REASONS,
                (
                    settlement,
                    latest,
                    discontinuity,
                    maximum_loss,
                    short_risk,
                    path,
                    volatility,
                    liquidity,
                    economic,
                ),
                strict=True,
            )
        )

    def _opportunity(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        quote: NormalizedCloseQuote,
        *,
        post_close_quote_accepted: bool,
    ) -> CloseOpportunity:
        if not post_close_quote_accepted:
            return CloseOpportunity(
                CloseOpportunityEligibility.UNKNOWN,
                "UNACCEPTED_POST_CLOSE_QUOTE",
                None,
            )
        entry = trade.entry_facts
        return evaluate_close_opportunity(
            quote_state=quote.state,
            full_quantity_btc=entry.target_quantity_btc,
            consumed_levels=quote.consumed_levels,
            close_direction=facts.close_direction,
            short_leg_taker_commission_fraction=(
                facts.short_leg_taker_commission_fraction
                if facts.short_commission_source is not None
                else None
            ),
            long_leg_taker_commission_fraction=(
                facts.long_leg_taker_commission_fraction
                if facts.long_commission_source is not None
                else None
            ),
            fee_rate_index_fraction=self.policies.position.fee_rate_index_fraction,
            close_index_usdc_per_btc=(
                facts.current_index_usdc_per_btc if facts.index_source is not None else None
            ),
            net_entry_credit_usdc=trade.entry_economics.net_entry_credit_usdc,
            component_quote=facts.component_quote,
        )

    def _emit_position(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        decision: PositionDecision,
        fingerprint: str,
    ) -> None:
        current_known = (
            facts.current_index_usdc_per_btc is not None and facts.index_source is not None
        )
        entry_index_source = trade.entry_facts.index_source
        entry_ticker_source = trade.entry_facts.ticker_source
        prior_index_source = trade.prior_index_source
        if entry_index_source is None or entry_ticker_source is None or prior_index_source is None:
            raise RuntimeError("Position evaluation lacks retained entry/prior sources")
        current_index_source = facts.index_source if current_known else None
        evaluation_payload: dict[str, object] = {
            "position_evaluation_identity": decision.position_evaluation_identity,
            "shadow_entry_identity": trade.anchor_identity,
            "consumed_position_fact_fingerprint": fingerprint,
            "evaluation_fact_boundary": facts.boundary.as_object(),
            "ordered_predicate_truth_vector": list(decision.ordered_predicate_truth_vector),
            "entry_index_usdc_per_btc": trade.entry_facts.index_usdc_per_btc,
            "entry_index_source_identity": entry_index_source.source_identity,
            "entry_index_fact_boundary": entry_index_source.boundary.as_object(),
            "entry_short_leg_mark_iv_fraction": trade.entry_facts.short_mark_iv_fraction,
            "entry_short_leg_mark_iv_source_identity": entry_ticker_source.source_identity,
            "entry_short_leg_mark_iv_fact_boundary": entry_ticker_source.boundary.as_object(),
            "prior_evaluation_index_usdc_per_btc": trade.prior_index,
            "prior_evaluation_index_source_identity": prior_index_source.source_identity,
            "prior_evaluation_index_fact_boundary": prior_index_source.boundary.as_object(),
            "current_index_usdc_per_btc": (
                facts.current_index_usdc_per_btc if current_known else None
            ),
            "current_index_source_identity": (
                current_index_source.source_identity if current_index_source is not None else None
            ),
            "current_index_fact_boundary": (
                current_index_source.boundary.as_object()
                if current_index_source is not None
                else None
            ),
            "current_index_availability": "KNOWN" if current_known else "UNKNOWN",
            "next_evaluation_index_usdc_per_btc": (
                facts.current_index_usdc_per_btc if current_known else trade.prior_index
            ),
        }
        self._emit(
            "POSITION_EVALUATION",
            decision.position_evaluation_identity,
            facts.boundary,
            evaluation_payload,
        )
        attempt_identity = (
            trade.post_close_attempt.scheduled_identity
            if trade.post_close_attempt is not None
            else None
        )
        self._emit(
            "POSITION_ACTION",
            decision.position_action_identity,
            facts.boundary,
            {
                "position_action_identity": decision.position_action_identity,
                "position_evaluation_identity": decision.position_evaluation_identity,
                "shadow_entry_identity": trade.anchor_identity,
                "serialized_action": decision.serialized_action,
                "ordered_predicate_truth_vector": list(decision.ordered_predicate_truth_vector),
                "ordered_latched_close_reason_vector": list(
                    decision.ordered_latched_close_reason_vector
                ),
                "primary_close_reason": decision.primary_close_reason,
                "secondary_close_reasons": list(decision.secondary_close_reasons),
                "first_latched_close_action_identity": (
                    decision.first_latched_close_action_identity
                ),
                "scheduled_post_close_attempt_identity": attempt_identity,
                "action_fact_boundary": facts.boundary.as_object(),
            },
        )
        self._counts[f"position_{decision.serialized_action.lower()}_count"] += 1

    def _create_post_close_attempt(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        decision: PositionDecision,
        *,
        quote_source_accepted: bool,
        allocate_request_id: Callable[[], int],
    ) -> PostCloseAttempt | ComponentPostCloseAttempt:
        if self._uses_component_books(trade.entry_facts):
            entry = trade.entry_facts
            if (
                entry.short_leg_identity is None
                or entry.long_leg_identity is None
                or entry.short_leg_instrument_name is None
                or entry.long_leg_instrument_name is None
            ):
                raise RuntimeError("component post-CLOSE attempt lacks its frozen legs")
            component_attempt = ComponentPostCloseAttempt.schedule(
                anchor_identity=trade.anchor_identity,
                first_close_action_identity=decision.position_action_identity,
                short_option_identity=entry.short_leg_identity,
                long_option_identity=entry.long_leg_identity,
                short_instrument_name=entry.short_leg_instrument_name,
                long_instrument_name=entry.long_leg_instrument_name,
                short_request_id=allocate_request_id(),
                long_request_id=allocate_request_id(),
                boundary=facts.boundary,
            )
            intents = component_attempt.take_request_intents()
            if len(intents) != 2:
                raise RuntimeError("component post-CLOSE attempt lacks two request intents")
            self._intents.extend(intents)
            return component_attempt
        combo_identity = trade.entry_facts.canonical_combo_identity
        combo_name = trade.entry_facts.combo_instrument_name
        current_witness = facts.current_combo_subscription_witness
        quote_source = facts.quote_source
        if (
            quote_source_accepted
            and facts.close_quote_facts.atomic_availability is CloseAtomicAvailability.ACTIVE
            and combo_identity is not None
            and combo_name is not None
            and current_witness is not None
            and quote_source is not None
            and quote_source.source_identity == current_witness.source_identity
            and quote_source.boundary == current_witness.boundary
        ):
            request_id = allocate_request_id()
            attempt = PostCloseAttempt.schedule(
                anchor_identity=trade.anchor_identity,
                first_close_action_identity=decision.position_action_identity,
                canonical_combo_identity=combo_identity,
                request_id=request_id,
                boundary=facts.boundary,
                request_instrument_name=combo_name,
                origin_quote_witness=current_witness,
            )
            intent = attempt.take_request_intent()
            if intent is None:
                raise RuntimeError("new post-CLOSE attempt lacks request intent")
            self._intents.append(intent)
        else:
            status = (
                PostCloseAttemptStatus.NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE
                if facts.close_quote_facts.atomic_availability
                is CloseAtomicAvailability.KNOWN_UNAVAILABLE
                else PostCloseAttemptStatus.NOT_REQUESTABLE_UNKNOWN
            )
            attempt = PostCloseAttempt.not_requestable(
                anchor_identity=trade.anchor_identity,
                first_close_action_identity=decision.position_action_identity,
                status=status,
                boundary=facts.boundary,
            )
        return attempt

    def _emit_post_close_attempt(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        decision: PositionDecision,
        attempt: PostCloseAttempt | ComponentPostCloseAttempt,
    ) -> None:
        terminal_status = attempt.terminal_status
        request_ids = self._request_ids(attempt)
        if request_ids:
            request_member: object = list(request_ids)
        elif terminal_status is not None:
            request_member = terminal_status.value
        else:
            raise RuntimeError("non-requestable post-close attempt requires a terminal status")
        params: object = (
            [
                {"instrument_name": name, "depth": 10000}
                for name in (
                    trade.entry_facts.short_leg_instrument_name,
                    trade.entry_facts.long_leg_instrument_name,
                )
            ]
            if isinstance(attempt, ComponentPostCloseAttempt)
            else (
                {
                    "instrument_name": trade.entry_facts.combo_instrument_name,
                    "depth": 10000,
                }
                if request_ids
                else None
            )
        )
        if isinstance(attempt, ComponentPostCloseAttempt):
            execution_model: object = self.policies.position.execution_model
        else:
            execution_model = "PUBLIC_ATOMIC_COMBO"
        self._emit(
            "POST_CLOSE_ATTEMPT_SCHEDULED",
            attempt.scheduled_identity,
            facts.boundary,
            {
                "scheduled_post_close_attempt_identity": attempt.scheduled_identity,
                "shadow_entry_identity": trade.anchor_identity,
                "first_latched_close_action_identity": decision.position_action_identity,
                "request_id_or_marker": request_member,
                "execution_model": execution_model,
                "request_method": "public/get_order_book",
                "request_params": params,
                "schedule_fact_boundary": facts.boundary.as_object(),
            },
        )
        if attempt.terminal_status is not None:
            self._emit_post_close_terminal(trade, attempt=attempt)

    def _emit_close_quote(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        quote: NormalizedCloseQuote,
        quote_fingerprint: str,
        conditioning: str,
    ) -> str:
        quote_state = quote.state
        structure = canonical_identity(
            "ComponentBookAndCanonicalLegIdentity",
            self.policies.position.execution_model,
            [
                trade.entry_facts.short_leg_identity,
                trade.entry_facts.long_leg_identity,
            ],
        )
        identity = canonical_identity(
            "CloseQuoteEvaluationIdentity",
            trade.anchor_identity,
            self.bindings.position_policy_identity,
            structure,
            facts.close_direction,
            trade.entry_facts.target_quantity_btc,
            quote_fingerprint,
            quote_state.value,
            conditioning,
            facts.boundary.as_object(),
        )
        gross: Decimal | None = None
        if quote_state is CloseQuoteState.ATOMIC_COMBO_CLOSE_QUOTE:
            total = sum(
                (price * amount for price, amount in quote.consumed_levels),
                Decimal(0),
            )
            gross = -total if facts.close_direction == "BUY" else total
        elif (
            quote_state is CloseQuoteState.COMPONENT_BOOK_CLOSE_QUOTE
            and facts.component_quote is not None
        ):
            gross = facts.component_quote.gross_cashflow_usdc
        payload: dict[str, object] = {
            "close_quote_evaluation_identity": identity,
            "shadow_entry_identity": trade.anchor_identity,
            "first_latched_close_action_identity": (
                trade.first_close_decision.position_action_identity
                if trade.first_close_decision is not None
                else None
            ),
            "canonical_combo_identity": trade.entry_facts.canonical_combo_identity,
            "canonical_leg_identities": [
                trade.entry_facts.short_leg_identity,
                trade.entry_facts.long_leg_identity,
            ],
            "close_direction": facts.close_direction,
            "full_quantity_btc": trade.entry_facts.target_quantity_btc,
            "consumed_rule_scoped_quote_fingerprint": quote_fingerprint,
            "close_quote_state": quote_state.value,
            "close_conditioning": conditioning,
            "consumed_levels": self._levels(quote.consumed_levels),
            "component_pair_identity": (
                facts.component_pair_witness.pair_identity
                if facts.component_pair_witness is not None
                else None
            ),
            "component_pair_timing": (
                facts.component_pair_witness.timing_as_object()
                if facts.component_pair_witness is not None
                else None
            ),
            "component_pair_unknown_reasons": list(facts.component_pair_unknown_reasons),
            "component_legs": (
                [
                    self._component_leg_payload("SHORT", facts.component_quote.short_leg),
                    self._component_leg_payload("LONG", facts.component_quote.long_leg),
                ]
                if facts.component_quote is not None
                else []
            ),
            "component_quote_source_refs": [
                {"canonical_leg_role": role, **source.as_ref()}
                for role, source in (
                    ("SHORT", facts.component_short_quote_source),
                    ("LONG", facts.component_long_quote_source),
                )
                if source is not None
            ],
            "gross_close_cashflow_usdc": gross,
            "evaluation_fact_boundary": facts.boundary.as_object(),
            "non_claims": (
                [
                    "NOT_AN_ORDER",
                    "NOT_A_FILL",
                    "NOT_AN_ATOMIC_QUOTE",
                    "NO_LIQUIDITY_RESERVATION",
                    "ATOMIC_EXECUTABILITY_UNPROVEN",
                ]
                if facts.component_quote is not None
                else []
            ),
        }
        self._emit("CLOSE_QUOTE_EVALUATION", identity, facts.boundary, payload)
        self._counts[f"close_quote_{self._quote_count_suffix(quote_state)}_count"] += 1
        return identity

    def _emit_close_opportunity(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        close_quote_identity: str,
        opportunity: CloseOpportunity,
    ) -> str | None:
        if trade.first_close_decision is None:
            raise RuntimeError("close opportunity requires first CLOSE")
        if trade.last_quote_facts is None:
            raise RuntimeError("close opportunity lacks its current quote evaluation facts")
        economics = opportunity.economics
        quote_state = classify_close_quote(facts.close_quote_facts)
        fingerprint = self._close_opportunity_business_fingerprint(
            facts=facts,
            quote_state=quote_state,
            opportunity=opportunity,
        )
        opportunity_key = (close_quote_identity, fingerprint)
        if opportunity_key == trade.last_opportunity_key:
            return None
        identity = canonical_identity(
            "CloseOpportunityEvaluationIdentity",
            trade.anchor_identity,
            trade.first_close_decision.position_action_identity,
            close_quote_identity,
            fingerprint,
            opportunity.eligibility.value,
            facts.boundary.as_object(),
        )
        derived_known = economics is not None
        eligibility_reason = self._eligibility_reason(opportunity)
        quote_has_known_cashflow = quote_state in {
            CloseQuoteState.ATOMIC_COMBO_CLOSE_QUOTE,
            CloseQuoteState.COMPONENT_BOOK_CLOSE_QUOTE,
        }
        gross_cashflow = (
            (
                -sum(price * amount for price, amount in facts.close_quote_facts.consumed_levels)
                if facts.close_direction == "BUY"
                else sum(
                    price * amount for price, amount in facts.close_quote_facts.consumed_levels
                )
            )
            if quote_state is CloseQuoteState.ATOMIC_COMBO_CLOSE_QUOTE
            else (
                facts.component_quote.gross_cashflow_usdc
                if quote_state is CloseQuoteState.COMPONENT_BOOK_CLOSE_QUOTE
                and facts.component_quote is not None
                else None
            )
        )
        consumes_commissions = eligibility_reason in {
            "COMMISSION_UNKNOWN",
            "COMMISSION_ABOVE_POLICY",
            "INDEX_UNKNOWN",
            "ELIGIBLE_COMPLETE",
        }
        serializes_commissions = eligibility_reason in {
            "COMMISSION_ABOVE_POLICY",
            "INDEX_UNKNOWN",
            "ELIGIBLE_COMPLETE",
        }
        consumes_index = eligibility_reason in {"INDEX_UNKNOWN", "ELIGIBLE_COMPLETE"}
        not_applicable = eligibility_reason == "KNOWN_ATOMIC_UNAVAILABLE"
        payload = {
            "close_opportunity_evaluation_identity": identity,
            "shadow_entry_identity": trade.anchor_identity,
            "first_latched_close_action_identity": (
                trade.first_close_decision.position_action_identity
            ),
            "close_quote_evaluation_identity": close_quote_identity,
            "attempt_terminal_identity": None,
            "attempt_terminal_fact_boundary": None,
            "opportunity_economics_business_fingerprint": fingerprint,
            "eligibility": opportunity.eligibility.value,
            "eligibility_reason": eligibility_reason,
            "evaluation_fact_boundary": facts.boundary.as_object(),
            "gross_close_cashflow_usdc": (
                economics.gross_close_cashflow_usdc if economics is not None else gross_cashflow
            ),
            "gross_cashflow_availability": (
                "KNOWN"
                if quote_has_known_cashflow
                else "NOT_APPLICABLE"
                if not_applicable
                else "UNKNOWN"
            ),
            "short_leg_taker_commission_fraction": (
                facts.short_leg_taker_commission_fraction if serializes_commissions else None
            ),
            "long_leg_taker_commission_fraction": (
                facts.long_leg_taker_commission_fraction if serializes_commissions else None
            ),
            "commission_source_refs": (
                self._position_commission_refs(facts) if consumes_commissions else []
            ),
            "close_index_usdc_per_btc": (
                facts.current_index_usdc_per_btc
                if consumes_index and facts.index_source is not None
                else None
            ),
            "index_source_ref": (
                facts.index_source.as_ref()
                if consumes_index and facts.index_source is not None
                else None
            ),
            "close_fee_reserve_usdc": (
                economics.close_fee_reserve_usdc if economics is not None else None
            ),
            "net_close_cashflow_usdc": (
                economics.net_close_cashflow_usdc if economics is not None else None
            ),
            "net_close_debit_usdc": (
                economics.net_close_debit_usdc if economics is not None else None
            ),
            "projected_shadow_net_pnl_usdc": (
                economics.projected_shadow_net_pnl_usdc if economics is not None else None
            ),
            "projected_net_loss_usdc": (
                economics.projected_net_loss_usdc if economics is not None else None
            ),
            "derived_economics_availability": (
                "KNOWN" if derived_known else "NOT_APPLICABLE" if not_applicable else "UNKNOWN"
            ),
        }
        self._emit("CLOSE_OPPORTUNITY_EVALUATION", identity, facts.boundary, payload)
        trade.last_opportunity_key = opportunity_key
        self._counts[f"close_opportunity_{opportunity.eligibility.value.lower()}_count"] += 1
        return identity

    def _select_exit_and_terminalize(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        close_quote_identity: str,
        opportunity_identity: str,
        opportunity: CloseOpportunity,
    ) -> None:
        del close_quote_identity
        if opportunity.economics is None or trade.first_close_decision is None:
            raise RuntimeError("eligible close opportunity lacks complete state")
        self._emit(
            "SHADOW_CLOSE_OPPORTUNITY",
            opportunity_identity,
            facts.boundary,
            self._shadow_close_opportunity_payload(
                trade,
                facts,
                opportunity_identity,
                opportunity,
            ),
        )
        self._counts["shadow_close_opportunity_count"] += 1
        exit_identity = trade.observation.accept_eligible_exit(
            close_opportunity_evaluation_identity=opportunity_identity,
            boundary=facts.boundary,
        )
        if exit_identity is None:
            return
        self._emit(
            "SHADOW_COUNTERFACTUAL_EXIT",
            exit_identity,
            facts.boundary,
            self._shadow_exit_payload(
                trade,
                facts,
                opportunity_identity,
                exit_identity,
                opportunity,
            ),
        )
        self._emit_terminal_trade(trade, facts=facts, opportunity=opportunity)

    def _emit_terminal_trade(
        self,
        trade: _TradeRecord,
        *,
        facts: PositionFacts | None,
        opportunity: CloseOpportunity | None,
        terminal_source_identity: str | None = None,
    ) -> None:
        if trade.terminal_written or trade.observation.terminal_outcome_identity is None:
            return
        boundary = trade.observation.reducer.terminal_boundary
        if boundary is None:
            raise RuntimeError("terminal observation lacks terminal boundary")
        state = trade.observation.state
        selected_exit = trade.observation.selected_exit_identity
        attempt = trade.post_close_attempt
        known_economics = (
            compute_shadow_outcome_economics(
                gross_entry_credit_usdc=trade.entry_economics.gross_entry_credit_usdc,
                entry_fee_reserve_usdc=trade.entry_economics.entry_fee_reserve_usdc,
                gross_close_cashflow_usdc=opportunity.economics.gross_close_cashflow_usdc,
                close_fee_reserve_usdc=opportunity.economics.close_fee_reserve_usdc,
            )
            if (
                state is OutcomeState.MATURE_KNOWN
                and opportunity is not None
                and opportunity.economics is not None
            )
            else None
        )
        close_economics = opportunity.economics if opportunity is not None else None
        component_close_facts = (
            facts
            if (
                known_economics is not None
                and facts is not None
                and facts.component_quote is not None
                and facts.component_pair_witness is not None
                and facts.component_short_quote_source is not None
                and facts.component_long_quote_source is not None
            )
            else None
        )
        witnesses = (
            self._lifecycle_witnesses(trade, facts)
            if state is OutcomeState.MATURE_UNKNOWN and facts is not None
            else []
        )
        payload: dict[str, object] = {
            "shadow_outcome_identity": trade.observation.terminal_outcome_identity,
            "shadow_observation_identity": trade.observation.observation_identity,
            "shadow_entry_identity": trade.anchor_identity,
            "execution_model": (
                trade.entry_facts.component_quote.execution_model
                if trade.entry_facts.component_quote is not None
                else "PUBLIC_ATOMIC_COMBO"
            ),
            "terminal_state": state.value,
            "terminal_fact_boundary": boundary.as_object(),
            "selected_exit_identity": selected_exit,
            "first_latched_close_action_identity": (
                trade.first_close_decision.position_action_identity
                if trade.first_close_decision is not None
                else None
            ),
            "first_latched_close_action_fact_boundary": (
                trade.first_close_decision.action_fact_boundary.as_object()
                if trade.first_close_decision is not None
                else None
            ),
            "scheduled_post_close_attempt_identity": (
                attempt.scheduled_identity if attempt is not None else None
            ),
            "scheduled_post_close_attempt_fact_boundary": (
                attempt.origin_boundary.as_object() if attempt is not None else None
            ),
            "post_close_attempt_terminal_identity": (
                attempt.terminal_identity if attempt is not None else None
            ),
            "post_close_attempt_terminal_status": (
                attempt.terminal_status.value
                if attempt is not None and attempt.terminal_status is not None
                else None
            ),
            "post_close_attempt_terminal_owner": (
                attempt.terminal_owner.value
                if attempt is not None and attempt.terminal_owner is not None
                else None
            ),
            "post_close_attempt_terminal_fact_boundary": (
                attempt.terminal_boundary.as_object()
                if attempt is not None and attempt.terminal_boundary is not None
                else None
            ),
            "natural_terminal_lifecycle_witnesses": witnesses,
            "censor_mask": (
                ["STOP"]
                if state is OutcomeState.CENSORED_AT_STOP
                else ["FAILURE"]
                if state is OutcomeState.CENSORED_AT_FAILURE
                else []
            ),
            "terminal_supervisor_source_identity": terminal_source_identity,
            "gross_entry_credit_usdc": trade.entry_economics.gross_entry_credit_usdc,
            "entry_fee_reserve_usdc": trade.entry_economics.entry_fee_reserve_usdc,
            "net_entry_credit_usdc": trade.entry_economics.net_entry_credit_usdc,
            "contractual_payoff_max_loss_ex_fees_usdc": (
                trade.entry_economics.contractual_payoff_max_loss_ex_fees_usdc
            ),
            "entry_fee_reserved_payoff_loss_usdc": (
                trade.entry_economics.entry_fee_reserved_payoff_loss_usdc
            ),
            "underwriting_reserved_loss_usdc": (
                trade.entry_economics.underwriting_reserved_loss_usdc
            ),
            "gross_close_cashflow_usdc": (
                close_economics.gross_close_cashflow_usdc
                if known_economics is not None and close_economics is not None
                else None
            ),
            "close_fee_reserve_usdc": (
                close_economics.close_fee_reserve_usdc
                if known_economics is not None and close_economics is not None
                else None
            ),
            "net_close_cashflow_usdc": (
                close_economics.net_close_cashflow_usdc
                if known_economics is not None and close_economics is not None
                else None
            ),
            "gross_pnl_usdc": (
                known_economics.gross_pnl_usdc if known_economics is not None else None
            ),
            "total_public_fee_reserve_usdc": (
                known_economics.total_public_fee_reserve_usdc
                if known_economics is not None
                else None
            ),
            "net_pnl_after_public_standard_fee_reserve_usdc": (
                known_economics.net_pnl_after_public_standard_fee_reserve_usdc
                if known_economics is not None
                else None
            ),
            "net_loss_usdc": (
                known_economics.net_loss_usdc if known_economics is not None else None
            ),
            "economic_availability": "KNOWN" if known_economics is not None else "UNKNOWN",
            "close_component_pair_identity": (
                component_close_facts.component_pair_witness.pair_identity
                if component_close_facts is not None
                and component_close_facts.component_pair_witness is not None
                else None
            ),
            "close_component_quote_source_refs": (
                [
                    {"canonical_leg_role": role, **source.as_ref()}
                    for role, source in (
                        ("SHORT", component_close_facts.component_short_quote_source),
                        ("LONG", component_close_facts.component_long_quote_source),
                    )
                    if source is not None
                ]
                if component_close_facts is not None
                else []
            ),
            "close_component_legs": (
                [
                    self._component_leg_payload(
                        "SHORT", component_close_facts.component_quote.short_leg
                    ),
                    self._component_leg_payload(
                        "LONG", component_close_facts.component_quote.long_leg
                    ),
                ]
                if component_close_facts is not None
                and component_close_facts.component_quote is not None
                else []
            ),
            "actual_entry_fee_usdc": None,
            "actual_close_fee_usdc": None,
            "actual_total_fee_usdc": None,
            "actual_pnl_usdc": None,
            "actual_exposure_quantity_btc": None,
            "actual_exposure_duration_ms": None,
            "actual_all_in_loss_usdc": None,
            "actual_all_in_max_loss_usdc": None,
            "actual_fill_identity": None,
            "actual_settlement_cashflow_usdc": None,
            "actual_availability": {
                "actual_entry_fee_usdc": "UNKNOWN",
                "actual_close_fee_usdc": "UNKNOWN",
                "actual_total_fee_usdc": "UNKNOWN",
                "actual_pnl_usdc": "UNKNOWN",
                "actual_exposure_quantity_btc": "UNKNOWN",
                "actual_exposure_duration_ms": "UNKNOWN",
                "actual_all_in_loss_usdc": "UNKNOWN",
                "actual_all_in_max_loss_usdc": "UNKNOWN",
                "actual_fill_identity": "UNKNOWN",
                "actual_settlement_cashflow_usdc": "UNKNOWN",
            },
            "non_claims": (
                [
                    "NOT_AN_ORDER",
                    "NOT_A_FILL",
                    "NOT_AN_ATOMIC_QUOTE",
                    "NO_LIQUIDITY_RESERVATION",
                    "ATOMIC_EXECUTABILITY_UNPROVEN",
                ]
                if trade.entry_facts.component_quote is not None
                else []
            ),
        }
        self._emit(
            "SHADOW_OUTCOME",
            trade.observation.terminal_outcome_identity,
            boundary,
            payload,
        )
        trade.terminal_written = True
        self._trade_retirements.add(trade.anchor_identity)

    def _shadow_close_opportunity_payload(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        identity: str,
        opportunity: CloseOpportunity,
    ) -> dict[str, object]:
        economics = opportunity.economics
        first_close = trade.first_close_decision
        index_source = facts.index_source
        if economics is None or first_close is None or index_source is None:
            raise RuntimeError("eligible opportunity lacks economics")
        return {
            "shadow_close_opportunity_identity": identity,
            "close_opportunity_evaluation_identity": identity,
            "shadow_entry_identity": trade.anchor_identity,
            "first_latched_close_action_identity": (first_close.position_action_identity),
            "opportunity_fact_boundary": facts.boundary.as_object(),
            "canonical_combo_identity": trade.entry_facts.canonical_combo_identity,
            "canonical_leg_identities": [
                trade.entry_facts.short_leg_identity,
                trade.entry_facts.long_leg_identity,
            ],
            "close_direction": facts.close_direction,
            "full_quantity_btc": trade.entry_facts.target_quantity_btc,
            "consumed_levels": self._levels(facts.close_quote_facts.consumed_levels),
            "commission_source_refs": self._position_commission_refs(facts),
            "index_source_ref": index_source.as_ref(),
            "gross_close_cashflow_usdc": economics.gross_close_cashflow_usdc,
            "close_fee_reserve_usdc": economics.close_fee_reserve_usdc,
            "net_close_cashflow_usdc": economics.net_close_cashflow_usdc,
            "net_close_debit_usdc": economics.net_close_debit_usdc,
            "projected_shadow_net_pnl_usdc": (economics.projected_shadow_net_pnl_usdc),
            "projected_net_loss_usdc": economics.projected_net_loss_usdc,
        }

    def _shadow_exit_payload(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        opportunity_identity: str,
        exit_identity: str,
        opportunity: CloseOpportunity,
    ) -> dict[str, object]:
        base = self._exit_economics_payload(trade, facts, opportunity)
        first_close = trade.first_close_decision
        retained = trade.last_quote_facts
        if first_close is None or retained is None:
            raise RuntimeError("selected exit lacks its accepted quote source")
        if retained.component_quote is not None:
            if (
                retained.component_pair_witness is None
                or retained.component_short_quote_source is None
                or retained.component_long_quote_source is None
            ):
                raise RuntimeError("selected component exit lacks its paired quote sources")
            component_pair_identity: object = retained.component_pair_witness.pair_identity
            component_source_refs: object = [
                {"canonical_leg_role": role, **source.as_ref()}
                for role, source in (
                    ("SHORT", retained.component_short_quote_source),
                    ("LONG", retained.component_long_quote_source),
                )
            ]
            combo_source_ref: object = None
        else:
            if retained.quote_source is None:
                raise RuntimeError("selected exit lacks its accepted combo quote source")
            component_pair_identity = None
            component_source_refs = []
            combo_source_ref = retained.quote_source.as_ref()
        return {
            "shadow_counterfactual_exit_identity": exit_identity,
            "shadow_observation_identity": trade.observation.observation_identity,
            "first_latched_close_action_identity": (first_close.position_action_identity),
            "close_opportunity_evaluation_identity": opportunity_identity,
            "shadow_close_opportunity_identity": opportunity_identity,
            "selection_fact_boundary": facts.boundary.as_object(),
            "first_latched_close_action_fact_boundary": (
                first_close.action_fact_boundary.as_object()
            ),
            "close_opportunity_evaluation_fact_boundary": facts.boundary.as_object(),
            "combo_quote_source_ref": combo_source_ref,
            "component_pair_identity": component_pair_identity,
            "component_quote_source_refs": component_source_refs,
            **base,
        }

    def _exit_economics_payload(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        opportunity: CloseOpportunity,
    ) -> dict[str, object]:
        economics = opportunity.economics
        index_source = facts.index_source
        if economics is None or index_source is None:
            raise RuntimeError("exit requires economics")
        return {
            "commission_source_refs": self._position_commission_refs(facts),
            "index_source_ref": index_source.as_ref(),
            "canonical_combo_identity": trade.entry_facts.canonical_combo_identity,
            "canonical_leg_identities": [
                trade.entry_facts.short_leg_identity,
                trade.entry_facts.long_leg_identity,
            ],
            "close_direction": facts.close_direction,
            "full_quantity_btc": trade.entry_facts.target_quantity_btc,
            "consumed_levels": self._levels(facts.close_quote_facts.consumed_levels),
            "component_legs": (
                [
                    self._component_leg_payload("SHORT", facts.component_quote.short_leg),
                    self._component_leg_payload("LONG", facts.component_quote.long_leg),
                ]
                if facts.component_quote is not None
                else []
            ),
            "short_leg_taker_commission_fraction": (
                trade.entry_facts.short_leg_taker_commission_fraction
            ),
            "long_leg_taker_commission_fraction": (
                trade.entry_facts.long_leg_taker_commission_fraction
            ),
            "close_index_usdc_per_btc": facts.current_index_usdc_per_btc,
            "gross_close_cashflow_usdc": economics.gross_close_cashflow_usdc,
            "close_fee_reserve_usdc": economics.close_fee_reserve_usdc,
            "net_close_cashflow_usdc": economics.net_close_cashflow_usdc,
            "net_close_debit_usdc": economics.net_close_debit_usdc,
            "projected_shadow_net_pnl_usdc": (economics.projected_shadow_net_pnl_usdc),
            "projected_net_loss_usdc": economics.projected_net_loss_usdc,
        }

    def _emit_admission_terminal(self, record: _CandidateRecord) -> None:
        attempt = record.attempt
        if (
            attempt.terminal_identity is None
            or attempt.terminal_boundary is None
            or attempt.terminal_outcome is None
            or attempt.terminal_source_identity is None
        ):
            raise RuntimeError("admission terminal is incomplete")
        self._emit(
            "ADMISSION_ATTEMPT_TERMINAL",
            attempt.terminal_identity,
            attempt.terminal_boundary,
            {
                "admission_attempt_terminal_identity": attempt.terminal_identity,
                "scheduled_admission_attempt_identity": attempt.scheduled_identity,
                "candidate_identity": record.state.candidate_identity,
                "active_episode_identity": record.facts.active_episode_identity,
                "terminal_outcome": attempt.terminal_outcome.value,
                "terminal_fact_boundary": attempt.terminal_boundary.as_object(),
                "terminal_source_identity": attempt.terminal_source_identity,
                "matched_response_identity": (
                    attempt.terminal_source_identity
                    if attempt.terminal_outcome
                    in {
                        AdmissionTerminalOutcome.ENTRY_EMITTED,
                        AdmissionTerminalOutcome.KNOWN_COMPLETE_NO_ENTRY,
                    }
                    else None
                ),
                "terminal_unknown_reasons": list(getattr(attempt, "terminal_unknown_reasons", ())),
                "component_pair_timing": getattr(attempt, "terminal_pair_timing", None),
                "component_pair_limits": getattr(attempt, "terminal_pair_limits", None),
            },
        )
        self._counts[f"admission_{attempt.terminal_outcome.value.lower()}_count"] += 1

    def _invalidate_candidate(
        self,
        record: _CandidateRecord,
        reasons: tuple[str, ...],
        boundary: FactBoundary,
    ) -> None:
        if record.state.lifecycle.value != "VALID":
            return
        identity = record.state.invalidate(reasons, boundary)
        primary = next(
            reason
            for reason in (
                "RUNTIME_OR_CODE_IDENTITY_CHANGED",
                "RADAR_POLICY_OR_EPISODE_PAUSED_ENDED_OR_CHANGED",
                "UNDERWRITING_OR_POSITION_POLICY_IDENTITY_CHANGED",
                "POSITION_SLOT_CONSUMED_BY_SHADOW_ENTRY",
                "STRUCTURE_LEG_LIFECYCLE_OR_TARGET_QUANTITY_CHANGED",
                "SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN",
                "LATEST_ADMISSION_BOUNDARY_REACHED",
                "CONSUMED_NON_ADMISSION_BUSINESS_FINGERPRINT_CHANGED",
                "REUNDERWRITING_NO_LONGER_CANDIDATE",
                "FAILED_ADMISSION_EVALUATION_CONSUMED",
            )
            if reason in reasons
        )
        ordered = tuple(
            reason
            for reason in (
                "RUNTIME_OR_CODE_IDENTITY_CHANGED",
                "RADAR_POLICY_OR_EPISODE_PAUSED_ENDED_OR_CHANGED",
                "UNDERWRITING_OR_POSITION_POLICY_IDENTITY_CHANGED",
                "POSITION_SLOT_CONSUMED_BY_SHADOW_ENTRY",
                "STRUCTURE_LEG_LIFECYCLE_OR_TARGET_QUANTITY_CHANGED",
                "SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN",
                "LATEST_ADMISSION_BOUNDARY_REACHED",
                "CONSUMED_NON_ADMISSION_BUSINESS_FINGERPRINT_CHANGED",
                "REUNDERWRITING_NO_LONGER_CANDIDATE",
                "FAILED_ADMISSION_EVALUATION_CONSUMED",
            )
            if reason in reasons
        )
        self._emit(
            "CANDIDATE_INVALIDATION",
            identity,
            boundary,
            {
                "candidate_invalidation_identity": identity,
                "candidate_identity": record.state.candidate_identity,
                "primary_reason": primary,
                "ordered_applicable_reason_vector": list(ordered),
                "terminal_fact_boundary": boundary.as_object(),
            },
        )
        self._candidate_retirements.add(record.state.candidate_identity)

    def _candidate_invalidation_reasons(
        self,
        record: _CandidateRecord,
        facts: UnderwritingFacts,
        evaluation: _UnderwritingEvaluation,
        *,
        include_non_admission_change: bool,
        include_reunderwriting: bool,
        include_failed_admission: bool,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if facts.active_episode_identity != record.facts.active_episode_identity:
            reasons.append("RADAR_POLICY_OR_EPISODE_PAUSED_ENDED_OR_CHANGED")
        if (
            facts.short_leg_identity != record.facts.short_leg_identity
            or facts.long_leg_identity != record.facts.long_leg_identity
            or facts.target_quantity_btc != record.facts.target_quantity_btc
            or facts.entry_direction != record.facts.entry_direction
            or (
                not isinstance(record.attempt, ComponentAdmissionAttempt)
                and (
                    facts.canonical_combo_identity != record.facts.canonical_combo_identity
                    or facts.combo_instrument_name != record.facts.combo_instrument_name
                )
            )
        ):
            reasons.append("STRUCTURE_LEG_LIFECYCLE_OR_TARGET_QUANTITY_CHANGED")
        candidate_witness = record.facts.quote_refresh_witness
        current_witness = facts.quote_refresh_witness
        subscription_discontinuity = (
            isinstance(candidate_witness, SubscriptionAdmissionRefreshWitness)
            and isinstance(current_witness, SubscriptionAdmissionRefreshWitness)
            and (
                current_witness.session_epoch != candidate_witness.session_epoch
                or current_witness.subscription_generation
                != candidate_witness.subscription_generation
                or (
                    current_witness.boundary.is_strictly_after(candidate_witness.boundary)
                    and current_witness.change_id != candidate_witness.change_id
                    and current_witness.snapshot_kind == "change"
                    and current_witness.prev_change_id != candidate_witness.change_id
                )
            )
        )
        if (
            evaluation.availability is UnderwritingAvailability.UNKNOWN
            or subscription_discontinuity
        ):
            reasons.append("SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN")
        if (
            facts.expiry_ms is not None
            and facts.trusted_time_upper_ms is not None
            and facts.trusted_time_upper_ms >= facts.expiry_ms - ADMISSION_CUTOFF_LEAD_MS
        ):
            reasons.append("LATEST_ADMISSION_BOUNDARY_REACHED")
        if include_non_admission_change and (
            evaluation.availability_fingerprint != record.availability_fingerprint
            or evaluation.economic_fingerprint != record.economic_fingerprint
        ):
            reasons.append("CONSUMED_NON_ADMISSION_BUSINESS_FINGERPRINT_CHANGED")
        if include_reunderwriting and evaluation.action is not UnderwritingAction.CANDIDATE:
            reasons.append("REUNDERWRITING_NO_LONGER_CANDIDATE")
        if include_failed_admission:
            reasons.append("FAILED_ADMISSION_EVALUATION_CONSUMED")
        return tuple(dict.fromkeys(reasons))

    def _component_candidate_pre_refresh_reasons(
        self,
        record: _CandidateRecord,
        facts: UnderwritingFacts,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if facts.active_episode_identity != record.facts.active_episode_identity:
            reasons.append("RADAR_POLICY_OR_EPISODE_PAUSED_ENDED_OR_CHANGED")
        if (
            facts.short_leg_identity != record.facts.short_leg_identity
            or facts.long_leg_identity != record.facts.long_leg_identity
            or facts.short_leg_instrument_name != record.facts.short_leg_instrument_name
            or facts.long_leg_instrument_name != record.facts.long_leg_instrument_name
            or facts.target_quantity_btc != record.facts.target_quantity_btc
            or self._known_structural_unavailability(facts)
        ):
            reasons.append("STRUCTURE_LEG_LIFECYCLE_OR_TARGET_QUANTITY_CHANGED")
        if record.slot_identity in self._slot_consumed:
            reasons.append("POSITION_SLOT_CONSUMED_BY_SHADOW_ENTRY")
        if (
            not facts.option_catalog_complete
            or facts.platform_usable is not True
            or facts.trusted_time_lower_ms is None
            or facts.trusted_time_upper_ms is None
            or facts.short_instrument_source is None
            or facts.long_instrument_source is None
            or facts.index_source is None
            or facts.ticker_source is None
        ):
            reasons.append("SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN")
        if (
            facts.expiry_ms is not None
            and facts.trusted_time_upper_ms is not None
            and facts.trusted_time_upper_ms >= facts.expiry_ms - ADMISSION_CUTOFF_LEAD_MS
        ):
            reasons.append("LATEST_ADMISSION_BOUNDARY_REACHED")
        return tuple(dict.fromkeys(reasons))

    def _terminalize_candidate_before_refresh(
        self,
        record: _CandidateRecord,
        *,
        reasons: tuple[str, ...],
        boundary: FactBoundary,
    ) -> None:
        source_identity = canonical_identity(
            "CandidatePreRefreshInvalidationSourceIdentity",
            record.state.candidate_identity,
            list(reasons),
            boundary.as_object(),
        )
        if record.attempt.invalidate_before_refresh(
            source_identity=source_identity,
            boundary=boundary,
        ):
            self._emit_admission_terminal(record)
            self._invalidate_candidate(record, reasons, boundary)

    @staticmethod
    def _require_quote_witness(
        facts: UnderwritingFacts,
    ) -> SubscriptionAdmissionRefreshWitness:
        witness = facts.quote_refresh_witness
        if not isinstance(witness, SubscriptionAdmissionRefreshWitness):
            raise RuntimeError("Candidate lacks its consumed official subscription quote witness")
        return witness

    def _emit_post_close_terminal(
        self,
        trade: _TradeRecord,
        *,
        attempt: PostCloseAttempt | ComponentPostCloseAttempt | None = None,
    ) -> None:
        attempt = attempt or trade.post_close_attempt
        if attempt is None or attempt.terminal_identity is None:
            return
        if (
            attempt.terminal_boundary is None
            or attempt.terminal_status is None
            or attempt.terminal_owner is None
        ):
            raise RuntimeError("post-CLOSE terminal attempt is incomplete")
        self._emit(
            "POST_CLOSE_ATTEMPT_TERMINAL",
            attempt.terminal_identity,
            attempt.terminal_boundary,
            {
                "post_close_attempt_terminal_identity": attempt.terminal_identity,
                "scheduled_post_close_attempt_identity": attempt.scheduled_identity,
                "terminal_status": attempt.terminal_status.value,
                "terminal_owner": attempt.terminal_owner.value,
                "terminal_fact_boundary": attempt.terminal_boundary.as_object(),
                "matched_response_identity": attempt.matched_response_identity,
                "terminal_unknown_reasons": list(getattr(attempt, "terminal_unknown_reasons", ())),
                "shadow_entry_identity": trade.anchor_identity,
                "component_pair_timing": getattr(attempt, "terminal_pair_timing", None),
                "component_pair_limits": getattr(attempt, "terminal_pair_limits", None),
            },
        )
        if (
            attempt.terminal_owner is PostCloseAttemptOwner.ORDINARY
            and attempt.terminal_status
            not in {
                PostCloseAttemptStatus.SUCCESS,
                PostCloseAttemptStatus.CENSORED,
            }
        ):
            self._emit_attempt_close_opportunity(trade, attempt)

    def _emit_attempt_close_opportunity(
        self,
        trade: _TradeRecord,
        attempt: PostCloseAttempt | ComponentPostCloseAttempt,
    ) -> None:
        if (
            trade.first_close_decision is None
            or attempt.terminal_identity is None
            or attempt.terminal_boundary is None
            or attempt.terminal_status is None
        ):
            raise RuntimeError("attempt-owned close opportunity lacks terminal state")
        known_unavailable = (
            attempt.terminal_status
            is PostCloseAttemptStatus.NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE
        )
        eligibility = (
            CloseOpportunityEligibility.INELIGIBLE
            if known_unavailable
            else CloseOpportunityEligibility.UNKNOWN
        )
        reason = "KNOWN_ATOMIC_UNAVAILABLE" if known_unavailable else "QUOTE_OR_ATTEMPT_UNKNOWN"
        fingerprint = canonical_identity(
            "OpportunityEconomicsBusinessFingerprint",
            {
                "attempt_terminal_status": attempt.terminal_status.value,
                "eligibility": eligibility.value,
                "eligibility_reason": reason,
            },
        )
        identity = canonical_identity(
            "CloseOpportunityEvaluationIdentity",
            trade.anchor_identity,
            trade.first_close_decision.position_action_identity,
            attempt.terminal_identity,
            fingerprint,
            eligibility.value,
            attempt.terminal_boundary.as_object(),
        )
        opportunity_key = (attempt.terminal_identity, fingerprint)
        if opportunity_key == trade.last_opportunity_key:
            return
        payload: dict[str, object] = {
            "close_opportunity_evaluation_identity": identity,
            "shadow_entry_identity": trade.anchor_identity,
            "first_latched_close_action_identity": (
                trade.first_close_decision.position_action_identity
            ),
            "close_quote_evaluation_identity": None,
            "attempt_terminal_identity": attempt.terminal_identity,
            "attempt_terminal_fact_boundary": attempt.terminal_boundary.as_object(),
            "opportunity_economics_business_fingerprint": fingerprint,
            "eligibility": eligibility.value,
            "eligibility_reason": reason,
            "component_pair_timing": getattr(attempt, "terminal_pair_timing", None),
            "component_pair_limits": getattr(attempt, "terminal_pair_limits", None),
            "component_pair_unknown_reasons": list(
                getattr(attempt, "terminal_unknown_reasons", ())
            ),
            "evaluation_fact_boundary": attempt.terminal_boundary.as_object(),
            "gross_close_cashflow_usdc": None,
            "gross_cashflow_availability": ("NOT_APPLICABLE" if known_unavailable else "UNKNOWN"),
            "short_leg_taker_commission_fraction": None,
            "long_leg_taker_commission_fraction": None,
            "commission_source_refs": [],
            "close_index_usdc_per_btc": None,
            "index_source_ref": None,
            "close_fee_reserve_usdc": None,
            "net_close_cashflow_usdc": None,
            "net_close_debit_usdc": None,
            "projected_shadow_net_pnl_usdc": None,
            "projected_net_loss_usdc": None,
            "derived_economics_availability": (
                "NOT_APPLICABLE" if known_unavailable else "UNKNOWN"
            ),
        }
        self._emit(
            "CLOSE_OPPORTUNITY_EVALUATION",
            identity,
            attempt.terminal_boundary,
            payload,
        )
        trade.last_opportunity_key = opportunity_key
        self._counts[f"close_opportunity_{eligibility.value.lower()}_count"] += 1

    def _natural_lifecycle_ready(self, facts: PositionFacts) -> bool:
        return (
            facts.short_leg_state in {"delivered", "archivized"}
            and facts.long_leg_state in {"delivered", "archivized"}
            and facts.lifecycle_short_source is not None
            and facts.lifecycle_long_source is not None
        )

    def _fee_discontinuity_truth(self, facts: PositionFacts) -> PredicateTruth:
        values = (
            (
                facts.short_leg_taker_commission_fraction,
                facts.short_commission_source,
            ),
            (
                facts.long_leg_taker_commission_fraction,
                facts.long_commission_source,
            ),
        )
        rate = self.policies.position.fee_rate_index_fraction
        if any(
            value is not None
            and source is not None
            and value.is_finite()
            and value >= 0
            and value > rate
            for value, source in values
        ):
            return PredicateTruth.TRUE
        if all(
            value is not None and source is not None and value.is_finite() and 0 <= value <= rate
            for value, source in values
        ):
            return PredicateTruth.FALSE
        return PredicateTruth.UNKNOWN

    @staticmethod
    def _normalize_position_facts(facts: PositionFacts) -> PositionFacts:
        index = facts.current_index_usdc_per_btc
        if facts.index_source is None or index is None or not index.is_finite() or index <= 0:
            index = None
        delta = facts.current_short_delta
        if facts.ticker_source is None or delta is None or not delta.is_finite() or abs(delta) > 1:
            delta = None
        mark_iv = facts.current_short_mark_iv_fraction
        if facts.ticker_source is None or mark_iv is None or not mark_iv.is_finite() or mark_iv < 0:
            mark_iv = None
        quote_facts = facts.close_quote_facts
        if (
            quote_facts.atomic_availability is CloseAtomicAvailability.ACTIVE
            and facts.quote_source is None
        ):
            quote_facts = replace(
                quote_facts,
                atomic_availability=CloseAtomicAvailability.UNKNOWN,
                book_availability=CloseBookAvailability.UNKNOWN,
                consumed_levels=(),
            )
        lifecycle_states = {
            "open",
            "settlement",
            "delivered",
            "archivized",
            "inactive",
            "locked",
            "halted",
        }
        short_state = facts.short_leg_state if facts.short_leg_state in lifecycle_states else None
        long_state = facts.long_leg_state if facts.long_leg_state in lifecycle_states else None
        return replace(
            facts,
            platform_continuous=(
                facts.platform_continuous if type(facts.platform_continuous) is bool else None
            ),
            required_sources_continuous=(
                facts.required_sources_continuous
                if type(facts.required_sources_continuous) is bool
                else None
            ),
            canonical_structure_intact=(
                facts.canonical_structure_intact
                if type(facts.canonical_structure_intact) is bool
                else None
            ),
            short_leg_state=short_state,
            long_leg_state=long_state,
            short_leg_active=(
                facts.short_leg_active if type(facts.short_leg_active) is bool else None
            ),
            long_leg_active=(
                facts.long_leg_active if type(facts.long_leg_active) is bool else None
            ),
            current_index_usdc_per_btc=index,
            current_short_delta=delta,
            current_short_mark_iv_fraction=mark_iv,
            close_quote_facts=quote_facts,
            index_source=facts.index_source if index is not None else None,
            ticker_source=(
                facts.ticker_source if delta is not None or mark_iv is not None else None
            ),
        )

    @staticmethod
    def _option_lifecycle_discontinuity(
        state: str | None,
        active: bool | None,
    ) -> PredicateTruth:
        if state in {"inactive", "locked", "halted"}:
            return PredicateTruth.TRUE
        if state in {"settlement", "delivered", "archivized"}:
            return PredicateTruth.FALSE
        if state == "open":
            if active is False:
                return PredicateTruth.TRUE
            if active is True:
                return PredicateTruth.FALSE
        return PredicateTruth.UNKNOWN

    @staticmethod
    def _post_close_quote_is_accepted(
        trade: _TradeRecord,
        facts: PositionFacts,
    ) -> bool:
        if facts.component_quote is not None:
            short_source = facts.component_short_quote_source
            long_source = facts.component_long_quote_source
            if short_source is None or long_source is None:
                return False
            first_close = trade.first_close_decision
            if first_close is None:
                return (
                    short_source.boundary.runtime_identity == trade.entry_boundary.runtime_identity
                    and long_source.boundary.runtime_identity
                    == trade.entry_boundary.runtime_identity
                )
            attempt = trade.post_close_attempt
            pair = facts.component_pair_witness
            return bool(
                isinstance(attempt, ComponentPostCloseAttempt)
                and pair is not None
                and pair.boundary.is_strictly_after(first_close.action_fact_boundary)
                and attempt.terminal_status is PostCloseAttemptStatus.SUCCESS
                and attempt.matched_response_identity == pair.pair_identity
                and short_source.source_identity == pair.short.source_identity
                and short_source.boundary == pair.short.boundary
                and long_source.source_identity == pair.long.source_identity
                and long_source.boundary == pair.long.boundary
            )
        source = facts.quote_source
        if source is None:
            return False
        first_close = trade.first_close_decision
        if first_close is None or not facts.boundary.is_strictly_after(
            first_close.action_fact_boundary
        ):
            return FixedContractShadowOwner._subscription_quote_is_accepted(
                trade,
                facts,
            )
        attempt = trade.post_close_attempt
        if (
            not isinstance(attempt, PostCloseAttempt)
            or attempt.terminal_owner is not PostCloseAttemptOwner.ORDINARY
            or not source.boundary.is_strictly_after(first_close.action_fact_boundary)
        ):
            return False
        witness = facts.quote_refresh_witness
        if (
            witness is not None
            and witness.source_identity == source.source_identity
            and witness.boundary == source.boundary
            and witness.boundary == facts.boundary
        ):
            if isinstance(witness, RpcAdmissionRefreshWitness):
                return (
                    attempt.terminal_status is PostCloseAttemptStatus.SUCCESS
                    and attempt.matched_response_identity == source.source_identity
                )
            if isinstance(witness, SubscriptionAdmissionRefreshWitness):
                if facts.current_combo_subscription_witness != witness:
                    return False
                previous_witness = trade.last_accepted_subscription_witness
                if (
                    previous_witness is not None
                    and previous_witness.boundary != attempt.origin_boundary
                    and not previous_witness.boundary.is_strictly_after(attempt.origin_boundary)
                ):
                    previous_witness = None
                return attempt.subscription_qualifies(
                    witness,
                    previous_witness=previous_witness,
                    canonical_combo_identity=trade.entry_facts.canonical_combo_identity,
                    instrument_name=trade.entry_facts.combo_instrument_name,
                )
            return False
        accepted_subscription = trade.last_accepted_subscription_witness
        if (
            accepted_subscription is not None
            and facts.current_combo_subscription_witness == accepted_subscription
            and source.source_identity == accepted_subscription.source_identity
            and source.boundary == accepted_subscription.boundary
        ):
            return True
        retained = trade.last_quote_facts
        return bool(
            retained is not None
            and retained.quote_source == source
            and retained.current_combo_subscription_witness
            == facts.current_combo_subscription_witness
            and retained.boundary.is_strictly_after(first_close.action_fact_boundary)
        )

    @staticmethod
    def _subscription_quote_is_accepted(
        trade: _TradeRecord,
        facts: PositionFacts,
    ) -> bool:
        source = facts.quote_source
        witness = facts.current_combo_subscription_witness
        refresh_witness = facts.quote_refresh_witness
        if (
            source is None
            or witness is None
            or source.source_identity != witness.source_identity
            or source.boundary != witness.boundary
            or witness.canonical_combo_identity != trade.entry_facts.canonical_combo_identity
            or witness.instrument_name != trade.entry_facts.combo_instrument_name
            or witness.boundary.code_identity != trade.entry_boundary.code_identity
            or witness.boundary.runtime_identity != trade.entry_boundary.runtime_identity
            or (
                refresh_witness is not None
                and (
                    not isinstance(
                        refresh_witness,
                        SubscriptionAdmissionRefreshWitness,
                    )
                    or refresh_witness != witness
                )
            )
        ):
            return False
        previous = trade.last_accepted_subscription_witness
        if previous is None:
            return witness.snapshot_kind == "snapshot"
        if witness == previous:
            return True
        if (
            previous.canonical_combo_identity != witness.canonical_combo_identity
            or previous.instrument_name != witness.instrument_name
            or witness.boundary.causal_seq <= previous.boundary.causal_seq
        ):
            return False
        same_generation = (
            witness.session_epoch == previous.session_epoch
            and witness.subscription_generation == previous.subscription_generation
        )
        if not same_generation:
            return witness.snapshot_kind == "snapshot"
        return witness.change_id > previous.change_id and (
            witness.snapshot_kind == "snapshot" or witness.prev_change_id == previous.change_id
        )

    def _lifecycle_witnesses(
        self,
        trade: _TradeRecord,
        facts: PositionFacts | None,
    ) -> list[dict[str, object]]:
        if facts is None or not self._natural_lifecycle_ready(facts):
            raise RuntimeError("natural terminal lacks lifecycle witnesses")
        short_source = facts.lifecycle_short_source
        long_source = facts.lifecycle_long_source
        if short_source is None or long_source is None:
            raise RuntimeError("natural terminal lacks concrete lifecycle source facts")
        return [
            {
                "canonical_leg_role": role,
                "instrument_identity": identity,
                "lifecycle_state": state,
                "source_identity": source.source_identity,
                "witness_fact_boundary": source.boundary.as_object(),
            }
            for role, identity, state, source in (
                (
                    "SHORT",
                    trade.entry_facts.short_leg_identity,
                    facts.short_leg_state,
                    short_source,
                ),
                (
                    "LONG",
                    trade.entry_facts.long_leg_identity,
                    facts.long_leg_state,
                    long_source,
                ),
            )
        ]

    def _emit(
        self,
        kind: str,
        identity: str,
        boundary: FactBoundary,
        payload: Mapping[str, object],
    ) -> None:
        self.state_store.record(
            object_kind=kind,
            object_identity=identity,
            fact_boundary=boundary,
            payload=payload,
        )
        self._emitted.append(EmittedObject(kind, identity, boundary))

    @staticmethod
    def _levels(
        levels: tuple[tuple[Decimal, Decimal], ...],
    ) -> list[dict[str, Decimal]]:
        return [
            {
                "price_usdc_per_btc": price,
                "amount_btc": amount,
            }
            for price, amount in levels
        ]

    def _component_leg_payload(
        self,
        role: str,
        leg: ComponentBookLegQuote,
    ) -> dict[str, object]:
        return {
            "canonical_leg_role": role,
            "instrument_name": leg.instrument_name,
            "action": leg.action.value,
            "raw_consumed_levels": self._levels(
                tuple((level.price, level.amount) for level in leg.raw.consumed)
            ),
            "raw_vwap_usdc_per_btc": leg.raw.vwap,
            "stressed_consumed_levels": self._levels(
                tuple((level.price, level.amount) for level in leg.stressed.consumed)
            ),
            "stressed_vwap_usdc_per_btc": leg.stressed.vwap,
            "fee_reserve_usdc": leg.fee_reserve_usdc,
        }

    @staticmethod
    def _commission_refs(facts: UnderwritingFacts) -> list[dict[str, object]]:
        if facts.short_instrument_source is None or facts.long_instrument_source is None:
            raise RuntimeError("Entry requires two commission source refs")
        return [
            {
                "canonical_leg_role": role,
                **source.as_ref(),
            }
            for role, source in (
                ("SHORT", facts.short_instrument_source),
                ("LONG", facts.long_instrument_source),
            )
        ]

    @staticmethod
    def _position_commission_refs(facts: PositionFacts) -> list[dict[str, object]]:
        return [
            {
                "canonical_leg_role": role,
                **source.as_ref(),
            }
            for role, source in (
                ("SHORT", facts.short_commission_source),
                ("LONG", facts.long_commission_source),
            )
            if source is not None
        ]

    @staticmethod
    def _quote_count_suffix(state: CloseQuoteState) -> str:
        return {
            CloseQuoteState.COMPONENT_BOOK_CLOSE_QUOTE: "component_book",
            CloseQuoteState.ATOMIC_COMBO_CLOSE_QUOTE: "atomic",
            CloseQuoteState.LEGGED_CLOSE_REFERENCE: "legged_reference",
            CloseQuoteState.UNEXECUTABLE: "unexecutable",
            CloseQuoteState.UNKNOWN: "unknown",
        }[state]

    @staticmethod
    def _eligibility_reason(opportunity: CloseOpportunity) -> str:
        if opportunity.eligibility is CloseOpportunityEligibility.ELIGIBLE:
            return "ELIGIBLE_COMPLETE"
        if opportunity.eligibility_reason in {
            CloseQuoteState.UNEXECUTABLE.value,
            CloseQuoteState.LEGGED_CLOSE_REFERENCE.value,
        }:
            return "KNOWN_ATOMIC_UNAVAILABLE"
        if opportunity.eligibility_reason == "COMMISSION_ABOVE_FROZEN_RESERVE":
            return "COMMISSION_ABOVE_POLICY"
        if opportunity.eligibility_reason == "COMMISSION_UNKNOWN":
            return "COMMISSION_UNKNOWN"
        if opportunity.eligibility_reason == "CLOSE_INDEX_UNKNOWN":
            return "INDEX_UNKNOWN"
        return "QUOTE_OR_ATTEMPT_UNKNOWN"

    def _close_opportunity_business_fingerprint(
        self,
        *,
        facts: PositionFacts,
        quote_state: CloseQuoteState,
        opportunity: CloseOpportunity,
    ) -> str:
        reason = self._eligibility_reason(opportunity)
        consumed: dict[str, object] = {"quote_state": quote_state.value}
        if reason not in {
            "KNOWN_ATOMIC_UNAVAILABLE",
            "QUOTE_OR_ATTEMPT_UNKNOWN",
        }:
            consumed["consumed_levels"] = facts.close_quote_facts.consumed_levels
            consumed["commission_availability"] = [
                facts.short_leg_taker_commission_fraction is not None
                and facts.short_commission_source is not None,
                facts.long_leg_taker_commission_fraction is not None
                and facts.long_commission_source is not None,
            ]
        if reason in {
            "COMMISSION_ABOVE_POLICY",
            "INDEX_UNKNOWN",
            "ELIGIBLE_COMPLETE",
        }:
            consumed["commission_values"] = [
                facts.short_leg_taker_commission_fraction,
                facts.long_leg_taker_commission_fraction,
            ]
        if reason in {"INDEX_UNKNOWN", "ELIGIBLE_COMPLETE"}:
            consumed["index_availability"] = (
                "KNOWN"
                if facts.current_index_usdc_per_btc is not None
                and facts.current_index_usdc_per_btc.is_finite()
                and facts.current_index_usdc_per_btc > 0
                and facts.index_source is not None
                else "UNKNOWN"
            )
        if reason == "ELIGIBLE_COMPLETE":
            economics = opportunity.economics
            if economics is None:
                raise RuntimeError("eligible opportunity lacks economics")
            consumed["close_index_usdc_per_btc"] = facts.current_index_usdc_per_btc
            consumed["economics"] = {
                "gross_close_cashflow_usdc": economics.gross_close_cashflow_usdc,
                "close_fee_reserve_usdc": economics.close_fee_reserve_usdc,
                "net_close_cashflow_usdc": economics.net_close_cashflow_usdc,
                "net_close_debit_usdc": economics.net_close_debit_usdc,
                "projected_shadow_net_pnl_usdc": economics.projected_shadow_net_pnl_usdc,
                "projected_net_loss_usdc": economics.projected_net_loss_usdc,
            }
        return canonical_identity(
            "OpportunityEconomicsBusinessFingerprint",
            opportunity.eligibility.value,
            reason,
            consumed,
        )

    def _begin_transition(self) -> None:
        self._emitted = []
        self._intents = []
        self._retirements = []
        self._candidate_retirements = set()
        self._trade_retirements = set()

    def _finish_transition(self) -> OwnerTransition:
        transition = OwnerTransition(
            tuple(self._emitted),
            tuple(self._intents),
            tuple(self._retirements),
        )
        for candidate_identity in sorted(self._candidate_retirements):
            self._candidates.pop(candidate_identity, None)
            self.state_store.retire_candidate(candidate_identity)
        for anchor_identity in sorted(self._trade_retirements):
            self._trades.pop(anchor_identity, None)
            self.state_store.retain_latest_terminal_case(anchor_identity)
        return transition
