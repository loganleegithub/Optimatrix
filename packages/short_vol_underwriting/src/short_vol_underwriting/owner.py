from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from short_vol_underwriting.admission import (
    AdmissionAttempt,
    AdmissionRefreshWitness,
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
    NormalizedCloseQuote,
    PostCloseAttempt,
    PostCloseAttemptOwner,
    PostCloseAttemptStatus,
    classify_close_quote,
    evaluate_close_opportunity,
    normalize_close_quote,
)
from short_vol_underwriting.cohort import (
    AlignedPair,
    Observation,
    RejectedAnchor,
    RejectedAnchorSelector,
)
from short_vol_underwriting.conservation import (
    cohort_conservation_status,
    compute_cohort_rates,
    compute_underwriting_rates,
    derive_cohort_counts,
    derive_underwriting_counts,
    underwriting_conservation_status,
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
    classify_underwriting_action,
    compute_entry_economics,
    compute_shadow_outcome_economics,
)
from short_vol_underwriting.evidence import (
    DownstreamEvidenceWriter,
    RuntimeBindings,
)
from short_vol_underwriting.identity import IdentityError, canonical_identity, require_identity
from short_vol_underwriting.manifest import ValidatedManifest
from short_vol_underwriting.model import (
    FactBoundary,
    OutcomeState,
    PredicateTruth,
    TerminalSource,
)
from short_vol_underwriting.policy import PolicyChain
from short_vol_underwriting.validation import validate_complete_semantic_graph


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
    unknown_reasons: tuple[str, ...] = ()

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
    attempt: AdmissionAttempt
    availability_fingerprint: str
    economic_fingerprint: str


@dataclass
class _TradeRecord:
    rejected: bool
    anchor_identity: str
    slot_identity: str
    entry_boundary: FactBoundary
    entry_facts: UnderwritingFacts
    entry_economics: EntryEconomics
    observation: Observation
    pair: AlignedPair
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
    post_close_attempt: PostCloseAttempt | None = None
    terminal_written: bool = False


class FixedContractShadowOwner:
    """Pure synchronous owner for the accepted downstream business lifecycle."""

    def __init__(
        self,
        *,
        policies: PolicyChain,
        bindings: RuntimeBindings,
        writer: DownstreamEvidenceWriter,
    ) -> None:
        if policies.identities != (
            bindings.radar_policy_identity,
            bindings.underwriting_policy_identity,
            bindings.position_policy_identity,
        ):
            raise ValueError("owner Policy chain and evidence bindings differ")
        self.policies = policies
        self.bindings = bindings
        self.writer = writer
        self._slot_consumed: set[str] = set()
        self._last_availability: dict[
            str,
            tuple[str, UnderwritingAvailability, str],
        ] = {}
        self._emitted_identities: set[tuple[str, str]] = set()
        self._last_underwriting_action: dict[
            str,
            tuple[str, UnderwritingAction, str],
        ] = {}
        self._candidates: dict[str, _CandidateRecord] = {}
        self._trades: dict[str, _TradeRecord] = {}
        self._rejected_selector = RejectedAnchorSelector()
        self._enrollment_start: FactBoundary | None = None
        self._enrollment_end: FactBoundary | None = None
        self._emitted: list[EmittedObject] = []
        self._intents: list[RpcRequestIntent] = []
        self._retirements: list[RpcRetirementIntent] = []
        self._counts: Counter[str] = Counter()
        self._accepting_new_work = True
        self._terminal_boundary: FactBoundary | None = None
        self._terminal_source_identity: str | None = None
        self._terminal_source_kind: TerminalSource | None = None
        self._terminal_summary_written = False

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

    def open_enrollment(self, boundary: FactBoundary) -> None:
        if self._enrollment_start is not None:
            raise ValueError("enrollment start is immutable")
        self._enrollment_start = boundary

    def close_enrollment(self, boundary: FactBoundary) -> None:
        if self._enrollment_start is None or not boundary.is_strictly_after(self._enrollment_start):
            raise ValueError("enrollment cutoff must be strictly after runtime start")
        if self._enrollment_end is not None:
            raise ValueError("enrollment cutoff is immutable")
        self._enrollment_end = boundary

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
        rejected: list[tuple[_UnderwritingEvaluation, str]] = []
        for evaluation in evaluations:
            availability_identity = self._emit_availability(evaluation)
            if evaluation.action is None:
                continue
            action_identity, action_changed = self._emit_underwriting_action(
                evaluation,
                availability_identity=availability_identity,
            )
            if not action_changed:
                continue
            if evaluation.action is UnderwritingAction.CANDIDATE:
                self._activate_candidate(
                    evaluation,
                    action_identity=action_identity,
                    allocate_request_id=allocate_request_id,
                )
            else:
                rejected.append((evaluation, action_identity))
        for slot in sorted(
            {
                evaluation.slot_identity
                for evaluation, _ in rejected
                if evaluation.slot_identity is not None
            }
        ):
            candidates = tuple(
                RejectedAnchor(
                    slot_identity=slot,
                    underwriting_action_identity=action_identity,
                    action=evaluation.action.value,
                    boundary=evaluation.facts.boundary,
                )
                for evaluation, action_identity in rejected
                if evaluation.slot_identity == slot and evaluation.action is not None
            )
            selected = self._rejected_selector.select_boundary(candidates)
            if selected is not None:
                selected_item = next(
                    (item for item in rejected if item[1] == selected.underwriting_action_identity),
                    None,
                )
                if selected_item is not None:
                    evaluation, action_identity = selected_item
                    self._create_rejected_trade(evaluation, action_identity)
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

    def _settle_admission_record(
        self,
        record: _CandidateRecord,
        *,
        refreshed_facts: UnderwritingFacts,
        refresh_witness: AdmissionRefreshWitness,
        evaluation: _UnderwritingEvaluation,
    ) -> None:
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
                response_budget_ms=(self.policies.underwriting.combo_snapshot_response_budget_ms),
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
                send_budget_ms=self.policies.underwriting.combo_snapshot_send_budget_ms,
            ):
                if candidate.attempt.terminal_outcome is not None:
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
                send_budget_ms=self.policies.position.combo_snapshot_send_budget_ms,
            ):
                if attempt.terminal_status is not None:
                    self._emit_post_close_terminal(trade)
                return self._finish_transition()
        return self._finish_transition()

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
            or attempt is None
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
            if record.attempt.request_id != request_id:
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
                attempt is not None
                and attempt.terminal_status is None
                and facts.boundary.is_strictly_after(attempt.origin_boundary)
                and attempt.accept_refresh(
                    witness=witness,
                    response_budget_ms=self.policies.position.combo_snapshot_response_budget_ms,
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
            if attempt is None or attempt.request_id is None:
                raise RuntimeError("terminalized post-CLOSE refresh lacks its attempt")
            if isinstance(witness, SubscriptionAdmissionRefreshWitness):
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

    def finalize_terminal(
        self,
        *,
        manifest: ValidatedManifest,
        terminal_disposition: str,
        terminal_source: Mapping[str, object],
    ) -> OwnerTransition:
        """Write the two immutable terminal summaries after the terminal drain."""
        self._begin_transition()
        if self._terminal_summary_written:
            return self._finish_transition()
        boundary = self._terminal_boundary
        terminal_identity = self._terminal_source_identity
        terminal_kind = self._terminal_source_kind
        if boundary is None or terminal_identity is None or terminal_kind is None:
            raise ValueError("terminal summaries require a committed terminal barrier")
        if any(
            record.state.lifecycle.value == "VALID" for record in self._candidates.values()
        ) or any(
            trade.observation.state is OutcomeState.PENDING for trade in self._trades.values()
        ):
            raise RuntimeError("terminal summaries require a fully drained owner")
        if manifest.runtime_identity != self.bindings.runtime_identity:
            raise ValueError("manifest runtime identity differs from owner bindings")
        if manifest.candidate_commit != self.bindings.code_identity:
            raise ValueError("manifest candidate commit differs from owner bindings")
        start = self._enrollment_start
        if start is None:
            raise ValueError("terminal summaries require a realized runtime start")
        start_trigger = self._manifest_mapping(manifest, "runtime_start_trigger")
        cutoff_trigger = self._manifest_mapping(manifest, "enrollment_cutoff_trigger")
        final_trigger = self._manifest_mapping(manifest, "final_stop_trigger")
        if start.received_monotonic_ms < self._trigger_monotonic_ms(start_trigger):
            raise ValueError("runtime start boundary does not realize the manifest trigger")
        terminal_source_value, expected_terminal_identity = self._validate_terminal_source(
            manifest=manifest,
            terminal_disposition=terminal_disposition,
            terminal_source=terminal_source,
            boundary=boundary,
            final_trigger=final_trigger,
        )
        if expected_terminal_identity != terminal_identity:
            raise ValueError("terminal source identity differs from the committed barrier")
        if terminal_disposition == "PROCESS_FAILURE":
            if terminal_kind is not TerminalSource.FAILURE:
                raise ValueError("process failure must own failure censoring")
        elif terminal_kind is not TerminalSource.STOP:
            raise ValueError("clean/emergency stop must own stop censoring")

        cutoff_realized = self._enrollment_end is not None
        enrollment_end = self._enrollment_end or boundary
        if cutoff_realized:
            if not (
                enrollment_end.is_strictly_after(start)
                and boundary.is_strictly_after(enrollment_end)
            ):
                raise ValueError(
                    "realized enrollment cutoff must be strictly after runtime start "
                    "and strictly before terminal"
                )
            if enrollment_end.received_monotonic_ms < self._trigger_monotonic_ms(cutoff_trigger):
                raise ValueError("enrollment cutoff boundary does not realize the manifest trigger")
            enrollment_end_reason = "PREBOUND_CUTOFF"
        else:
            if not boundary.is_strictly_after(start):
                raise ValueError("terminal-before-cutoff must be strictly after runtime start")
            enrollment_end_reason = "TERMINAL_BEFORE_CUTOFF"

        current_objects = self.writer.objects
        validate_complete_semantic_graph(
            {
                f"{value['object_kind']}:{value['object_identity']}": value
                for value in current_objects
            },
            runtime_start=start,
            enrollment_end=enrollment_end,
            terminal_boundary=boundary,
        )
        underwriting_counts = derive_underwriting_counts(current_objects)
        underwriting_rates = compute_underwriting_rates(underwriting_counts)
        underwriting_status = underwriting_conservation_status(underwriting_counts)
        if underwriting_status != "MET":
            raise RuntimeError("Underwriting terminal conservation is not met")
        underwriting_summary_identity = canonical_identity(
            "UNDERWRITING_POSITION_SUMMARY",
            self.bindings.underwriting_position_contract_digest,
            self.bindings.code_identity,
            self.bindings.runtime_identity,
            self.bindings.radar_policy_identity,
            self.bindings.underwriting_policy_identity,
            self.bindings.position_policy_identity,
            terminal_identity,
            boundary.as_object(),
            underwriting_counts,
            underwriting_rates,
            underwriting_status,
        )
        self._emit(
            "UNDERWRITING_POSITION_SUMMARY",
            underwriting_summary_identity,
            boundary,
            {
                "underwriting_position_summary_identity": underwriting_summary_identity,
                "terminal_source_identity": terminal_identity,
                "terminal_fact_boundary": boundary.as_object(),
                "counts": underwriting_counts,
                "rates": underwriting_rates,
                "conservation_status": underwriting_status,
            },
            self._local_provenance(
                "SUPERVISOR_CONTROL",
                terminal_identity,
                boundary,
            ),
        )

        cohort_counts = derive_cohort_counts(current_objects)
        cohort_rates = compute_cohort_rates(cohort_counts, evidence_status="COMPLETE")
        cohort_status = cohort_conservation_status(
            cohort_counts,
            evidence_status="COMPLETE",
        )
        if cohort_status != "MET":
            raise RuntimeError("Outcome cohort terminal conservation is not met")
        planned_boundary = (
            boundary.as_object() if terminal_disposition == "PLANNED_CLEAN_STOP" else None
        )
        cohort_summary_identity = canonical_identity(
            "CohortSummaryIdentity",
            self.bindings.outcome_contract_identity,
            self.bindings.runtime_identity,
            manifest.manifest_identity,
            boundary.as_object(),
        )
        provenance = [
            *self._local_provenance(
                "SUPERVISOR_CONTROL",
                manifest.manifest_identity,
                start,
            ),
            *self._local_provenance(
                "SUPERVISOR_CONTROL",
                canonical_identity(
                    "PreboundSupervisorTriggerIdentity",
                    start_trigger,
                ),
                start,
            ),
        ]
        if cutoff_realized:
            provenance.extend(
                self._local_provenance(
                    "SUPERVISOR_CONTROL",
                    canonical_identity(
                        "PreboundSupervisorTriggerIdentity",
                        cutoff_trigger,
                    ),
                    enrollment_end,
                )
            )
        provenance.extend(
            self._local_provenance(
                "SUPERVISOR_CONTROL",
                terminal_identity,
                boundary,
            )
        )
        unique_provenance = {
            (str(item["source_role"]), str(item["source_identity"])): item for item in provenance
        }
        self._emit(
            "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
            cohort_summary_identity,
            boundary,
            {
                "cohort_summary_identity": cohort_summary_identity,
                "manifest_identity": manifest.manifest_identity,
                "runtime_start_fact_boundary": start.as_object(),
                "enrollment_end_fact_boundary": enrollment_end.as_object(),
                "enrollment_end_reason": enrollment_end_reason,
                "terminal_fact_boundary": boundary.as_object(),
                "terminal_disposition": terminal_disposition,
                "planned_final_stop_fact_boundary": planned_boundary,
                "terminal_source_identity": terminal_identity,
                "terminal_source": terminal_source_value,
                "evidence_status": "COMPLETE",
                "counts": cohort_counts,
                "rates": cohort_rates,
                "conservation_status": cohort_status,
            },
            tuple(unique_provenance.values()),
        )
        self._terminal_summary_written = True
        return self._finish_transition()

    @staticmethod
    def _manifest_mapping(
        manifest: ValidatedManifest,
        field: str,
    ) -> Mapping[str, object]:
        value = manifest.value[field]
        if not isinstance(value, Mapping):
            raise ValueError(f"manifest {field} must be an object")
        return value

    @staticmethod
    def _trigger_monotonic_ms(trigger: Mapping[str, object]) -> int:
        value = trigger.get("trigger_monotonic_ms")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("manifest trigger monotonic time is invalid")
        return value

    def _validate_terminal_source(
        self,
        *,
        manifest: ValidatedManifest,
        terminal_disposition: str,
        terminal_source: Mapping[str, object],
        boundary: FactBoundary,
        final_trigger: Mapping[str, object],
    ) -> tuple[dict[str, object], str]:
        source = dict(terminal_source)
        if terminal_disposition == "PLANNED_CLEAN_STOP":
            if source != dict(final_trigger):
                raise ValueError("planned stop source must equal the manifest final trigger")
            identity = canonical_identity("PreboundSupervisorTriggerIdentity", source)
            monotonic_ms = source["trigger_monotonic_ms"]
        elif terminal_disposition == "AUTHORIZED_EMERGENCY_STOP":
            expected = (
                "runtime_identity",
                "supervisor_clock_identity",
                "authority_identity",
                "control_monotonic_ms",
                "control_kind",
                "reason",
            )
            if tuple(source) != expected:
                raise ValueError("emergency stop control requires exact keys")
            if (
                source["control_kind"] != "AUTHORIZED_EMERGENCY_STOP"
                or source["reason"]
                not in {
                    "USER_REQUEST",
                    "AUTHORITY_REVOCATION",
                    "EXTERNAL_SAFETY_STOP",
                }
                or source["authority_identity"] != manifest.value["emergency_stop_authority"]
            ):
                raise ValueError("emergency stop control is not authorized")
            identity = canonical_identity("AuthorizedEmergencyStopControlIdentity", source)
            monotonic_ms = source["control_monotonic_ms"]
        elif terminal_disposition == "PROCESS_FAILURE":
            expected = (
                "runtime_identity",
                "supervisor_clock_identity",
                "failure_source_identity",
                "control_monotonic_ms",
                "control_kind",
                "failure_kind",
            )
            if tuple(source) != expected:
                raise ValueError("fatal failure control requires exact keys")
            if source["control_kind"] != "PROCESS_FAILURE" or source["failure_kind"] not in {
                "FATAL_RUNTIME",
                "FATAL_EVIDENCE_INTEGRITY",
            }:
                raise ValueError("fatal failure control is invalid")
            require_identity(source["failure_source_identity"], "failure_source_identity")
            identity = canonical_identity("FatalFailureControlIdentity", source)
            monotonic_ms = source["control_monotonic_ms"]
        else:
            raise ValueError("terminal disposition is invalid")
        if isinstance(monotonic_ms, bool) or not isinstance(monotonic_ms, int):
            raise ValueError("terminal source monotonic time is invalid")
        boundary_time_matches = (
            boundary.received_monotonic_ms >= monotonic_ms
            if terminal_disposition == "PLANNED_CLEAN_STOP"
            else boundary.received_monotonic_ms == monotonic_ms
        )
        if (
            source.get("runtime_identity") != manifest.runtime_identity
            or source.get("supervisor_clock_identity") != manifest.supervisor_clock_identity
            or not boundary_time_matches
        ):
            raise ValueError("terminal source does not create the terminal boundary")
        return source, identity

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
        return (
            facts.short_leg_state in known_states - {"open"}
            or facts.long_leg_state in known_states - {"open"}
            or facts.short_leg_active is False
            or facts.long_leg_active is False
            or facts.option_amounts_aligned is False
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
            "consumed_availability_fact_fingerprint": evaluation.availability_fingerprint,
            "availability": evaluation.availability.value,
            "availability_evaluation_fact_boundary": facts.boundary.as_object(),
            "unknown_reasons": list(facts.unknown_reasons),
        }
        self._emit(
            "UNDERWRITING_AVAILABILITY_EVALUATION",
            identity,
            facts.boundary,
            payload,
            self._facts_provenance(facts),
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
        previous = self._last_underwriting_action.get(evaluation.opportunity_identity)
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
            evaluation.economic_fingerprint,
            facts.boundary.as_object(),
        )
        identity = canonical_identity(
            "UnderwritingActionIdentity",
            underwriting_evaluation_identity,
            evaluation.action.value,
        )
        economics = evaluation.economics
        payload = {
            "underwriting_action_identity": identity,
            "underwriting_availability_evaluation_identity": availability_identity,
            "underwriting_opportunity_key_identity": evaluation.opportunity_identity,
            "consumed_economic_fact_fingerprint": evaluation.economic_fingerprint,
            "economic_action": evaluation.action.value,
            "evaluation_fact_boundary": facts.boundary.as_object(),
            "gross_entry_credit_usdc": economics.gross_entry_credit_usdc,
            "entry_fee_reserve_usdc": economics.entry_fee_reserve_usdc,
            "net_entry_credit_usdc": economics.net_entry_credit_usdc,
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
            self._facts_provenance(facts),
        )
        self._counts[f"underwriting_action_{evaluation.action.value.lower()}_count"] += 1
        self._last_underwriting_action[evaluation.opportunity_identity] = (
            evaluation.economic_fingerprint,
            evaluation.action,
            identity,
        )
        return identity, True

    def _activate_candidate(
        self,
        evaluation: _UnderwritingEvaluation,
        *,
        action_identity: str,
        allocate_request_id: Callable[[], int],
    ) -> None:
        if (
            evaluation.slot_identity is None
            or evaluation.facts.canonical_combo_identity is None
            or evaluation.facts.combo_instrument_name is None
            or evaluation.economic_fingerprint is None
        ):
            raise RuntimeError(
                "Candidate requires slot, combo, instrument, and economic identities"
            )
        facts = evaluation.facts
        candidate_identity = canonical_identity(
            "CandidateIdentity",
            action_identity,
            facts.boundary.as_object(),
        )
        if candidate_identity in self._candidates:
            return
        request_id = allocate_request_id()
        attempt = AdmissionAttempt.schedule(
            candidate_identity=candidate_identity,
            canonical_combo_identity=evaluation.facts.canonical_combo_identity,
            request_id=request_id,
            boundary=facts.boundary,
            request_instrument_name=evaluation.facts.combo_instrument_name,
        )
        record = _CandidateRecord(
            facts=facts,
            state=CandidateState(candidate_identity),
            slot_identity=evaluation.slot_identity,
            attempt=attempt,
            availability_fingerprint=evaluation.availability_fingerprint,
            economic_fingerprint=evaluation.economic_fingerprint,
        )
        self._candidates[candidate_identity] = record
        intent = attempt.take_request_intent()
        if intent is None:
            raise RuntimeError("new admission attempt did not expose one request intent")
        self._emit(
            "CANDIDATE_ACTIVATION",
            candidate_identity,
            facts.boundary,
            {
                "candidate_identity": candidate_identity,
                "underwriting_action_identity": action_identity,
                "underwriting_position_slot_key_identity": evaluation.slot_identity,
                "candidate_activation_fact_boundary": facts.boundary.as_object(),
            },
            self._local_provenance("ANCHOR", action_identity, facts.boundary),
        )
        self._emit(
            "ADMISSION_ATTEMPT_SCHEDULED",
            attempt.scheduled_identity,
            facts.boundary,
            {
                "scheduled_admission_attempt_identity": attempt.scheduled_identity,
                "candidate_identity": candidate_identity,
                "request_id": request_id,
                "request_method": "public/get_order_book",
                "request_params": dict(intent.params),
                "schedule_fact_boundary": facts.boundary.as_object(),
            },
            self._local_provenance("ANCHOR", candidate_identity, facts.boundary),
        )
        self._intents.append(intent)
        self._counts["candidate_count"] += 1

    def _create_rejected_trade(
        self,
        evaluation: _UnderwritingEvaluation,
        action_identity: str,
    ) -> None:
        facts = evaluation.facts
        quote_source = facts.quote_source
        index_source = facts.index_source
        ticker_source = facts.ticker_source
        if (
            evaluation.slot_identity is None
            or evaluation.economics is None
            or evaluation.action is None
            or quote_source is None
            or index_source is None
            or ticker_source is None
        ):
            raise RuntimeError("rejected anchor lacks complete Entry audit facts")
        anchor_identity = canonical_identity(
            "RejectedCounterfactualAnchorIdentity",
            self.bindings.outcome_contract_identity,
            evaluation.slot_identity,
            action_identity,
        )
        if anchor_identity in self._trades:
            return
        payload = {
            "rejected_anchor_identity": anchor_identity,
            "underwriting_position_slot_key": evaluation.slot_identity,
            "underwriting_action_identity": action_identity,
            "underwriting_action": evaluation.action.value,
            "anchor_fact_boundary": facts.boundary.as_object(),
            "canonical_combo_identity": facts.canonical_combo_identity,
            "canonical_leg_identities": [
                facts.short_leg_identity,
                facts.long_leg_identity,
            ],
            "entry_direction": facts.entry_direction,
            "full_quantity_btc": facts.target_quantity_btc,
            "entry_consumed_levels": self._levels(facts.entry_consumed_levels),
            "entry_combo_quote_source_ref": quote_source.as_ref(),
            "entry_commission_source_refs": self._commission_refs(facts),
            "entry_index_usdc_per_btc": facts.index_usdc_per_btc,
            "entry_index_source_identity": index_source.source_identity,
            "entry_index_fact_boundary": index_source.boundary.as_object(),
            "entry_short_leg_mark_iv_fraction": facts.short_mark_iv_fraction,
            "entry_short_leg_mark_iv_source_identity": ticker_source.source_identity,
            "entry_short_leg_mark_iv_fact_boundary": ticker_source.boundary.as_object(),
            "gross_entry_credit_usdc": evaluation.economics.gross_entry_credit_usdc,
            "entry_fee_reserve_usdc": evaluation.economics.entry_fee_reserve_usdc,
            "net_entry_credit_usdc": evaluation.economics.net_entry_credit_usdc,
            "contractual_payoff_max_loss_ex_fees_usdc": (
                evaluation.economics.contractual_payoff_max_loss_ex_fees_usdc
            ),
            "entry_fee_reserved_payoff_loss_usdc": (
                evaluation.economics.entry_fee_reserved_payoff_loss_usdc
            ),
            "underwriting_reserved_loss_usdc": (
                evaluation.economics.underwriting_reserved_loss_usdc
            ),
        }
        self._emit(
            "REJECTED_COUNTERFACTUAL_ANCHOR",
            anchor_identity,
            facts.boundary,
            payload,
            self._local_provenance(
                "ANCHOR",
                action_identity,
                facts.boundary,
            )
            + self._facts_provenance(facts),
        )
        self._create_trade_record(
            rejected=True,
            anchor_identity=anchor_identity,
            slot_identity=evaluation.slot_identity,
            facts=facts,
            economics=evaluation.economics,
        )

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
        if (
            attempt.terminal_identity is None
            or quote_source is None
            or index_source is None
            or ticker_source is None
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
            "canonical_combo_identity": facts.canonical_combo_identity,
            "canonical_leg_identities": [
                facts.short_leg_identity,
                facts.long_leg_identity,
            ],
            "entry_direction": facts.entry_direction,
            "full_quantity_btc": facts.target_quantity_btc,
            "entry_consumed_levels": self._levels(facts.entry_consumed_levels),
            "entry_combo_quote_source_ref": quote_source.as_ref(),
            "entry_commission_source_refs": self._commission_refs(facts),
            "entry_index_usdc_per_btc": facts.index_usdc_per_btc,
            "entry_index_source_ref": index_source.as_ref(),
            "entry_short_leg_mark_iv_fraction": facts.short_mark_iv_fraction,
            "entry_short_leg_mark_iv_source_ref": ticker_source.as_ref(),
            "gross_entry_credit_usdc": economics.gross_entry_credit_usdc,
            "entry_fee_reserve_usdc": economics.entry_fee_reserve_usdc,
            "net_entry_credit_usdc": economics.net_entry_credit_usdc,
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
            "SHADOW_ENTRY",
            entry_identity,
            facts.boundary,
            payload,
            self._facts_provenance(facts),
        )
        self._slot_consumed.add(candidate.slot_identity)
        self._counts["shadow_entry_count"] += 1
        self._create_trade_record(
            rejected=False,
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
        rejected: bool,
        anchor_identity: str,
        slot_identity: str,
        facts: UnderwritingFacts,
        economics: EntryEconomics,
    ) -> None:
        if facts.index_usdc_per_btc is None or facts.index_source is None:
            raise RuntimeError("trade anchor requires a known entry index")
        enrolled = self._is_enrolled(facts.boundary)
        observation = (
            Observation.rejected_counterfactual(
                outcome_contract_identity=self.bindings.outcome_contract_identity,
                rejected_anchor_identity=anchor_identity,
                entry_boundary=facts.boundary,
                cohort_enrolled=enrolled,
            )
            if rejected
            else Observation.admitted(
                outcome_contract_identity=self.bindings.outcome_contract_identity,
                shadow_entry_identity=anchor_identity,
                entry_boundary=facts.boundary,
                cohort_enrolled=enrolled,
            )
        )
        pair = (
            AlignedPair.for_rejected(
                outcome_contract_identity=self.bindings.outcome_contract_identity,
                rejected_anchor_identity=anchor_identity,
                cohort_enrolled=enrolled,
            )
            if rejected
            else AlignedPair.for_admitted(
                outcome_contract_identity=self.bindings.outcome_contract_identity,
                shadow_entry_identity=anchor_identity,
                cohort_enrolled=enrolled,
            )
        )
        record = _TradeRecord(
            rejected=rejected,
            anchor_identity=anchor_identity,
            slot_identity=slot_identity,
            entry_boundary=facts.boundary,
            entry_facts=facts,
            entry_economics=economics,
            observation=observation,
            pair=pair,
            position_state=PositionDecisionState(
                shadow_entry_identity=observation.observation_identity
                if rejected
                else anchor_identity,
                position_policy_identity=self.bindings.position_policy_identity,
                entry_boundary=facts.boundary,
                rejected=rejected,
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
        kind = "REJECTED_COUNTERFACTUAL_OBSERVATION" if rejected else "SHADOW_OUTCOME_OBSERVATION"
        payload = (
            {
                "rejected_observation_identity": observation.observation_identity,
                "rejected_anchor_identity": anchor_identity,
                "start_fact_boundary": facts.boundary.as_object(),
                "aligned_pair_identity": pair.pair_identity,
                "cohort_enrolled": enrolled,
                "lifecycle_state": "PENDING",
            }
            if rejected
            else {
                "shadow_observation_identity": observation.observation_identity,
                "shadow_entry_identity": anchor_identity,
                "start_fact_boundary": facts.boundary.as_object(),
                "aligned_pair_identity": pair.pair_identity,
                "cohort_enrolled": enrolled,
                "lifecycle_state": "PENDING",
            }
        )
        self._emit(
            kind,
            observation.observation_identity,
            facts.boundary,
            payload,
            self._local_provenance("ANCHOR", anchor_identity, facts.boundary),
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
            path = (
                PredicateTruth.TRUE
                if (
                    entry_move
                    >= (
                        self.policies.position.maximum_absolute_index_return_since_entry_fraction
                        * entry.index_usdc_per_btc
                    )
                    or prior_move
                    >= (
                        self.policies.position.maximum_absolute_index_return_since_prior_evaluation_fraction
                        * trade.prior_index
                    )
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
        )

    def _emit_position(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        decision: PositionDecision,
        fingerprint: str,
    ) -> None:
        rejected = trade.rejected
        evaluation_kind = (
            "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION" if rejected else "POSITION_EVALUATION"
        )
        action_kind = "REJECTED_COUNTERFACTUAL_POSITION_ACTION" if rejected else "POSITION_ACTION"
        current_known = (
            facts.current_index_usdc_per_btc is not None and facts.index_source is not None
        )
        entry_index_source = trade.entry_facts.index_source
        entry_ticker_source = trade.entry_facts.ticker_source
        prior_index_source = trade.prior_index_source
        if entry_index_source is None or entry_ticker_source is None or prior_index_source is None:
            raise RuntimeError("Position evaluation lacks retained entry/prior sources")
        current_index_source = facts.index_source if current_known else None
        evaluation_payload: dict[str, object]
        if rejected:
            evaluation_payload = {
                "rejected_position_evaluation_identity": decision.position_evaluation_identity,
                "rejected_observation_identity": trade.observation.observation_identity,
                "consumed_position_fact_fingerprint": fingerprint,
                "evaluation_fact_boundary": facts.boundary.as_object(),
                "ordered_predicate_truth_vector": list(decision.ordered_predicate_truth_vector),
                "entry_index_usdc_per_btc": trade.entry_facts.index_usdc_per_btc,
                "entry_index_source_identity": entry_index_source.source_identity,
                "entry_index_fact_boundary": entry_index_source.boundary.as_object(),
                "entry_short_leg_mark_iv_fraction": (trade.entry_facts.short_mark_iv_fraction),
                "entry_short_leg_mark_iv_source_identity": (entry_ticker_source.source_identity),
                "entry_short_leg_mark_iv_fact_boundary": (entry_ticker_source.boundary.as_object()),
                "prior_evaluation_index_usdc_per_btc": trade.prior_index,
                "prior_evaluation_index_source_identity": (prior_index_source.source_identity),
                "prior_evaluation_index_fact_boundary": (prior_index_source.boundary.as_object()),
                "current_index_usdc_per_btc": (
                    facts.current_index_usdc_per_btc if current_known else None
                ),
                "current_index_source_identity": (
                    current_index_source.source_identity
                    if current_index_source is not None
                    else None
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
        else:
            evaluation_payload = {
                "position_evaluation_identity": decision.position_evaluation_identity,
                "shadow_entry_identity": trade.anchor_identity,
                "consumed_position_fact_fingerprint": fingerprint,
                "evaluation_fact_boundary": facts.boundary.as_object(),
                "ordered_predicate_truth_vector": list(decision.ordered_predicate_truth_vector),
                "entry_index_usdc_per_btc": trade.entry_facts.index_usdc_per_btc,
                "entry_index_source_identity": entry_index_source.source_identity,
                "entry_index_fact_boundary": entry_index_source.boundary.as_object(),
                "entry_short_leg_mark_iv_fraction": (trade.entry_facts.short_mark_iv_fraction),
                "entry_short_leg_mark_iv_source_identity": (entry_ticker_source.source_identity),
                "entry_short_leg_mark_iv_fact_boundary": (entry_ticker_source.boundary.as_object()),
                "prior_evaluation_index_usdc_per_btc": trade.prior_index,
                "prior_evaluation_index_source_identity": prior_index_source.source_identity,
                "prior_evaluation_index_fact_boundary": prior_index_source.boundary.as_object(),
                "current_index_usdc_per_btc": (
                    facts.current_index_usdc_per_btc if current_known else None
                ),
                "current_index_source_identity": (
                    current_index_source.source_identity
                    if current_index_source is not None
                    else None
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
        provenance = self._local_provenance(
            "ANCHOR",
            trade.observation.observation_identity if rejected else trade.anchor_identity,
            trade.entry_boundary,
        )
        provenance += self._local_provenance(
            "POSITION_FACT",
            fingerprint,
            facts.boundary,
        )
        provenance += self._source_provenance(
            "POSITION_FACT",
            trade.entry_facts.ticker_source,
        )
        provenance += self._source_provenance(
            "INDEX",
            trade.entry_facts.index_source,
        )
        provenance += self._source_provenance(
            "INDEX",
            trade.prior_index_source,
        )
        if current_known:
            provenance += self._source_provenance("INDEX", facts.index_source)
        self._emit(
            evaluation_kind,
            decision.position_evaluation_identity,
            facts.boundary,
            evaluation_payload,
            provenance,
        )
        attempt_identity = (
            trade.post_close_attempt.scheduled_identity
            if trade.post_close_attempt is not None
            else None
        )
        action_payload = (
            {
                "rejected_position_action_identity": decision.position_action_identity,
                "rejected_position_evaluation_identity": (decision.position_evaluation_identity),
                "serialized_action": decision.serialized_action,
                "ordered_predicate_truth_vector": list(decision.ordered_predicate_truth_vector),
                "ordered_latched_close_reason_vector": list(
                    decision.ordered_latched_close_reason_vector
                ),
                "first_latched_close_action_identity": (
                    decision.first_latched_close_action_identity
                ),
                "scheduled_post_close_attempt_identity": attempt_identity,
                "action_fact_boundary": facts.boundary.as_object(),
            }
            if rejected
            else {
                "position_action_identity": decision.position_action_identity,
                "position_evaluation_identity": decision.position_evaluation_identity,
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
            }
        )
        self._emit(
            action_kind,
            decision.position_action_identity,
            facts.boundary,
            action_payload,
            self._local_provenance(
                "POSITION_EVALUATION",
                decision.position_evaluation_identity,
                facts.boundary,
            ),
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
    ) -> PostCloseAttempt:
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
                anchor_identity=trade.observation.observation_identity
                if trade.rejected
                else trade.anchor_identity,
                first_close_action_identity=decision.position_action_identity,
                canonical_combo_identity=combo_identity,
                request_id=request_id,
                boundary=facts.boundary,
                rejected=trade.rejected,
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
                anchor_identity=trade.observation.observation_identity
                if trade.rejected
                else trade.anchor_identity,
                first_close_action_identity=decision.position_action_identity,
                status=status,
                boundary=facts.boundary,
                rejected=trade.rejected,
            )
        return attempt

    def _emit_post_close_attempt(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        decision: PositionDecision,
        attempt: PostCloseAttempt,
    ) -> None:
        if trade.rejected:
            return
        terminal_status = attempt.terminal_status
        if attempt.request_id is not None:
            request_member: object = attempt.request_id
        elif terminal_status is not None:
            request_member = terminal_status.value
        else:
            raise RuntimeError("non-requestable post-close attempt requires a terminal status")
        params: object = (
            {
                "instrument_name": trade.entry_facts.combo_instrument_name,
                "depth": 10000,
            }
            if attempt.request_id is not None
            else None
        )
        self._emit(
            "POST_CLOSE_ATTEMPT_SCHEDULED",
            attempt.scheduled_identity,
            facts.boundary,
            {
                "scheduled_post_close_attempt_identity": attempt.scheduled_identity,
                "shadow_entry_identity": trade.anchor_identity,
                "first_latched_close_action_identity": decision.position_action_identity,
                "request_id_or_marker": request_member,
                "request_method": "public/get_order_book",
                "request_params": params,
                "schedule_fact_boundary": facts.boundary.as_object(),
            },
            self._local_provenance(
                "POSITION_ACTION",
                decision.position_action_identity,
                facts.boundary,
            ),
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
        rejected = trade.rejected
        label = (
            "RejectedCounterfactualCloseQuoteEvaluationIdentity"
            if rejected
            else "CloseQuoteEvaluationIdentity"
        )
        structure = canonical_identity(
            "OfficialComboAndCanonicalLegIdentity",
            trade.entry_facts.canonical_combo_identity,
            [
                trade.entry_facts.short_leg_identity,
                trade.entry_facts.long_leg_identity,
            ],
        )
        identity = canonical_identity(
            label,
            trade.observation.observation_identity if rejected else trade.anchor_identity,
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
        payload: dict[str, object] = {
            (
                "rejected_close_quote_evaluation_identity"
                if rejected
                else "close_quote_evaluation_identity"
            ): identity,
            (
                "rejected_observation_identity" if rejected else "shadow_entry_identity"
            ): trade.observation.observation_identity if rejected else trade.anchor_identity,
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
            "gross_close_cashflow_usdc": gross,
            "evaluation_fact_boundary": facts.boundary.as_object(),
        }
        kind = (
            "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION"
            if rejected
            else "CLOSE_QUOTE_EVALUATION"
        )
        provenance = self._local_provenance(
            "ANCHOR",
            trade.observation.observation_identity if rejected else trade.anchor_identity,
            trade.entry_boundary,
        )
        provenance += (
            self._local_provenance(
                "COMBO_QUOTE",
                quote_fingerprint,
                facts.boundary,
            )
            if rejected
            else self._source_provenance(
                "COMBO_QUOTE",
                facts.quote_source,
            )
        )
        self._emit(kind, identity, facts.boundary, payload, provenance)
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
            raise RuntimeError("close opportunity lacks its durable quote evaluation facts")
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
        label = (
            "RejectedCounterfactualCloseOpportunityEvaluationIdentity"
            if trade.rejected
            else "CloseOpportunityEvaluationIdentity"
        )
        identity = canonical_identity(
            label,
            trade.observation.observation_identity if trade.rejected else trade.anchor_identity,
            trade.first_close_decision.position_action_identity,
            close_quote_identity,
            fingerprint,
            opportunity.eligibility.value,
            facts.boundary.as_object(),
        )
        derived_known = economics is not None
        eligibility_reason = self._eligibility_reason(opportunity)
        quote_is_atomic = quote_state is CloseQuoteState.ATOMIC_COMBO_CLOSE_QUOTE
        gross_cashflow = (
            (
                -sum(price * amount for price, amount in facts.close_quote_facts.consumed_levels)
                if facts.close_direction == "BUY"
                else sum(
                    price * amount for price, amount in facts.close_quote_facts.consumed_levels
                )
            )
            if quote_is_atomic
            else None
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
        consumes_index = eligibility_reason in {
            "INDEX_UNKNOWN",
            "ELIGIBLE_COMPLETE",
        }
        not_applicable = eligibility_reason == "KNOWN_ATOMIC_UNAVAILABLE"
        payload = {
            (
                "rejected_close_opportunity_evaluation_identity"
                if trade.rejected
                else "close_opportunity_evaluation_identity"
            ): identity,
            (
                "rejected_observation_identity" if trade.rejected else "shadow_entry_identity"
            ): trade.observation.observation_identity if trade.rejected else trade.anchor_identity,
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
                "KNOWN" if quote_is_atomic else "NOT_APPLICABLE" if not_applicable else "UNKNOWN"
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
        kind = (
            "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION"
            if trade.rejected
            else "CLOSE_OPPORTUNITY_EVALUATION"
        )
        provenance = self._local_provenance(
            "POSITION_ACTION",
            trade.first_close_decision.position_action_identity,
            trade.first_close_decision.action_fact_boundary,
        ) + self._local_provenance(
            "CLOSE_QUOTE_EVALUATION",
            close_quote_identity,
            trade.last_quote_facts.boundary,
        )
        if consumes_commissions:
            provenance += self._source_provenance(
                "COMMISSION",
                facts.short_commission_source,
            ) + self._source_provenance(
                "COMMISSION",
                facts.long_commission_source,
            )
        if consumes_index:
            provenance += self._source_provenance("INDEX", facts.index_source)
        self._emit(kind, identity, facts.boundary, payload, provenance)
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
        if opportunity.economics is None or trade.first_close_decision is None:
            raise RuntimeError("eligible close opportunity lacks complete state")
        if trade.rejected:
            exit_identity = trade.observation.accept_eligible_exit(
                close_opportunity_evaluation_identity=opportunity_identity,
                boundary=facts.boundary,
            )
            if exit_identity is None:
                return
            payload = self._rejected_exit_payload(
                trade,
                facts,
                close_quote_identity,
                opportunity_identity,
                exit_identity,
                opportunity,
            )
            kind = "REJECTED_COUNTERFACTUAL_EXIT"
        else:
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
                self._local_provenance(
                    "CLOSE_OPPORTUNITY_EVALUATION",
                    opportunity_identity,
                    facts.boundary,
                ),
            )
            self._counts["shadow_close_opportunity_count"] += 1
            exit_identity = trade.observation.accept_eligible_exit(
                close_opportunity_evaluation_identity=opportunity_identity,
                boundary=facts.boundary,
            )
            if exit_identity is None:
                return
            payload = self._shadow_exit_payload(
                trade,
                facts,
                opportunity_identity,
                exit_identity,
                opportunity,
            )
            kind = "SHADOW_COUNTERFACTUAL_EXIT"
        if trade.last_quote_facts is None:
            raise RuntimeError("selected exit lacks its close quote root")
        provenance = (
            self._local_provenance(
                "ANCHOR",
                trade.observation.observation_identity,
                trade.entry_boundary,
            )
            + self._local_provenance(
                "POSITION_ACTION",
                trade.first_close_decision.position_action_identity,
                trade.first_close_decision.action_fact_boundary,
            )
            + self._local_provenance(
                "CLOSE_OPPORTUNITY_EVALUATION",
                opportunity_identity,
                facts.boundary,
            )
        )
        if trade.rejected:
            provenance += self._local_provenance(
                "CLOSE_QUOTE_EVALUATION",
                close_quote_identity,
                trade.last_quote_facts.boundary,
            )
            provenance += self._local_provenance(
                "COMBO_QUOTE",
                str(payload["consumed_rule_scoped_quote_fingerprint"]),
                trade.last_quote_facts.boundary,
            )
        else:
            provenance += self._source_provenance(
                "COMBO_QUOTE",
                trade.last_quote_facts.quote_source,
            )
        provenance += self._source_provenance(
            "COMMISSION",
            facts.short_commission_source,
        )
        provenance += self._source_provenance(
            "COMMISSION",
            facts.long_commission_source,
        )
        provenance += self._source_provenance("INDEX", facts.index_source)
        self._emit(
            kind,
            exit_identity,
            facts.boundary,
            payload,
            provenance,
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
        witnesses = (
            self._lifecycle_witnesses(trade, facts)
            if state is OutcomeState.MATURE_UNKNOWN and facts is not None
            else []
        )
        payload: dict[str, object] = {
            (
                "rejected_outcome_identity" if trade.rejected else "shadow_outcome_identity"
            ): trade.observation.terminal_outcome_identity,
            (
                "rejected_observation_identity" if trade.rejected else "shadow_observation_identity"
            ): trade.observation.observation_identity,
            (
                "rejected_anchor_identity" if trade.rejected else "shadow_entry_identity"
            ): trade.anchor_identity,
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
        }
        kind = "REJECTED_COUNTERFACTUAL_OUTCOME" if trade.rejected else "SHADOW_OUTCOME"
        provenance = self._local_provenance(
            "ANCHOR",
            trade.observation.observation_identity,
            trade.entry_boundary,
        )
        if selected_exit is not None:
            provenance += self._local_provenance(
                "SELECTED_EXIT",
                selected_exit,
                boundary,
            )
        else:
            if trade.first_close_decision is not None:
                provenance += self._local_provenance(
                    "POSITION_ACTION",
                    trade.first_close_decision.position_action_identity,
                    trade.first_close_decision.action_fact_boundary,
                )
            if attempt is not None:
                provenance += self._local_provenance(
                    "ATTEMPT_CONTROL",
                    attempt.scheduled_identity,
                    attempt.origin_boundary,
                )
                if attempt.terminal_identity is not None and attempt.terminal_boundary is not None:
                    provenance += self._local_provenance(
                        "ATTEMPT_CONTROL",
                        attempt.terminal_identity,
                        attempt.terminal_boundary,
                    )
            if state is OutcomeState.MATURE_UNKNOWN and facts is not None:
                provenance += self._source_provenance(
                    "INSTRUMENT_LIFECYCLE",
                    facts.lifecycle_short_source,
                )
                provenance += self._source_provenance(
                    "INSTRUMENT_LIFECYCLE",
                    facts.lifecycle_long_source,
                )
            if terminal_source_identity is not None:
                provenance += self._local_provenance(
                    "SUPERVISOR_CONTROL",
                    terminal_source_identity,
                    boundary,
                )
        self._emit(
            kind,
            trade.observation.terminal_outcome_identity,
            boundary,
            payload,
            provenance,
        )
        trade.pair.terminalize(
            state=state,
            terminal_boundary=boundary,
            trade_outcome_identity=trade.observation.terminal_outcome_identity,
            trade_net_pnl_usdc=(
                known_economics.net_pnl_after_public_standard_fee_reserve_usdc
                if known_economics is not None
                else None
            ),
        )
        self._emit_aligned_pair(trade)
        trade.terminal_written = True

    def _emit_aligned_pair(self, trade: _TradeRecord) -> None:
        pair = trade.pair
        if (
            pair.terminal_state is None
            or pair.terminal_boundary is None
            or pair.trade_outcome_identity is None
        ):
            raise RuntimeError("aligned pair is not terminal")
        payload = {
            "aligned_pair_identity": pair.pair_identity,
            "pair_family": "REJECTED" if trade.rejected else "ADMITTED",
            "cohort_enrolled": pair.cohort_enrolled,
            "pair_anchor_identity": pair.pair_anchor_identity,
            "policy_arm": pair.policy_arm,
            "alternative_arm": pair.alternative_arm,
            "trade_observation_identity": trade.observation.observation_identity,
            "trade_outcome_identity": pair.trade_outcome_identity,
            "terminal_state": pair.terminal_state.value,
            "terminal_fact_boundary": pair.terminal_boundary.as_object(),
            "censor_mask": (
                ["STOP"]
                if pair.terminal_state is OutcomeState.CENSORED_AT_STOP
                else ["FAILURE"]
                if pair.terminal_state is OutcomeState.CENSORED_AT_FAILURE
                else []
            ),
            "no_trade_cashflow_usdc": Decimal(0),
            "trade_net_pnl_after_public_standard_fee_reserve_usdc": (pair.trade_net_pnl_usdc),
            "policy_advantage_usdc": pair.policy_advantage_usdc,
            "comparison_availability": (
                "KNOWN" if pair.terminal_state is OutcomeState.MATURE_KNOWN else "UNKNOWN"
            ),
        }
        self._emit(
            "ALIGNED_POLICY_NO_TRADE_PAIR",
            pair.pair_identity,
            pair.terminal_boundary,
            payload,
            self._local_provenance(
                "ANCHOR",
                trade.observation.observation_identity,
                trade.entry_boundary,
            )
            + self._local_provenance(
                "TERMINAL_OUTCOME",
                pair.trade_outcome_identity,
                pair.terminal_boundary,
            ),
        )

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
        if (
            first_close is None
            or trade.last_quote_facts is None
            or trade.last_quote_facts.quote_source is None
        ):
            raise RuntimeError("selected exit lacks its accepted combo quote source")
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
            "combo_quote_source_ref": trade.last_quote_facts.quote_source.as_ref(),
            **base,
        }

    def _rejected_exit_payload(
        self,
        trade: _TradeRecord,
        facts: PositionFacts,
        close_quote_identity: str,
        opportunity_identity: str,
        exit_identity: str,
        opportunity: CloseOpportunity,
    ) -> dict[str, object]:
        base = self._exit_economics_payload(trade, facts, opportunity)
        first_close = trade.first_close_decision
        if (
            first_close is None
            or trade.last_quote_facts is None
            or trade.last_quote_fingerprint is None
        ):
            raise RuntimeError("rejected exit lacks its close quote evaluation")
        return {
            "rejected_exit_identity": exit_identity,
            "rejected_observation_identity": trade.observation.observation_identity,
            "first_latched_close_action_identity": (first_close.position_action_identity),
            "close_quote_evaluation_identity": close_quote_identity,
            "close_opportunity_evaluation_identity": opportunity_identity,
            "selection_fact_boundary": facts.boundary.as_object(),
            "first_latched_close_action_fact_boundary": (
                first_close.action_fact_boundary.as_object()
            ),
            "close_quote_evaluation_fact_boundary": (trade.last_quote_facts.boundary.as_object()),
            "close_opportunity_evaluation_fact_boundary": facts.boundary.as_object(),
            "consumed_rule_scoped_quote_fingerprint": trade.last_quote_fingerprint,
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
            },
            self._local_provenance(
                "ATTEMPT_CONTROL",
                attempt.terminal_source_identity,
                attempt.terminal_boundary,
            ),
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
            self._local_provenance(
                "ANCHOR",
                record.state.candidate_identity,
                record.facts.boundary,
            ),
        )

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
            facts.canonical_combo_identity != record.facts.canonical_combo_identity
            or facts.combo_instrument_name != record.facts.combo_instrument_name
            or facts.short_leg_identity != record.facts.short_leg_identity
            or facts.long_leg_identity != record.facts.long_leg_identity
            or facts.target_quantity_btc != record.facts.target_quantity_btc
            or facts.entry_direction != record.facts.entry_direction
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
        attempt: PostCloseAttempt | None = None,
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
        if not trade.rejected:
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
                },
                self._local_provenance(
                    "ATTEMPT_CONTROL",
                    attempt.terminal_identity,
                    attempt.terminal_boundary,
                ),
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
        attempt: PostCloseAttempt,
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
        label = (
            "RejectedCounterfactualCloseOpportunityEvaluationIdentity"
            if trade.rejected
            else "CloseOpportunityEvaluationIdentity"
        )
        identity = canonical_identity(
            label,
            trade.observation.observation_identity if trade.rejected else trade.anchor_identity,
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
            (
                "rejected_close_opportunity_evaluation_identity"
                if trade.rejected
                else "close_opportunity_evaluation_identity"
            ): identity,
            (
                "rejected_observation_identity" if trade.rejected else "shadow_entry_identity"
            ): trade.observation.observation_identity if trade.rejected else trade.anchor_identity,
            "first_latched_close_action_identity": (
                trade.first_close_decision.position_action_identity
            ),
            "close_quote_evaluation_identity": None,
            "attempt_terminal_identity": attempt.terminal_identity,
            "attempt_terminal_fact_boundary": attempt.terminal_boundary.as_object(),
            "opportunity_economics_business_fingerprint": fingerprint,
            "eligibility": eligibility.value,
            "eligibility_reason": reason,
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
        kind = (
            "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION"
            if trade.rejected
            else "CLOSE_OPPORTUNITY_EVALUATION"
        )
        self._emit(
            kind,
            identity,
            attempt.terminal_boundary,
            payload,
            self._local_provenance(
                "POSITION_ACTION",
                trade.first_close_decision.position_action_identity,
                trade.first_close_decision.action_fact_boundary,
            )
            + self._local_provenance(
                "ATTEMPT_CONTROL",
                attempt.terminal_identity,
                attempt.terminal_boundary,
            ),
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
            attempt is None
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
        provenance: Sequence[Mapping[str, object]],
    ) -> None:
        emitted_key = (kind, identity)
        if emitted_key in self._emitted_identities:
            return
        provenance_by_key: dict[tuple[str, str], Mapping[str, object]] = {}
        for item in provenance:
            key = (str(item["source_role"]), str(item["source_identity"]))
            existing = provenance_by_key.get(key)
            if existing is not None and existing != item:
                raise RuntimeError("one provenance root cannot carry conflicting boundaries")
            provenance_by_key[key] = item
        normalized_provenance = tuple(
            sorted(
                provenance_by_key.values(),
                key=lambda item: (
                    str(item["source_role"]),
                    str(item["source_identity"]),
                ),
            )
        )
        self.writer.write(
            object_kind=kind,
            object_identity=identity,
            fact_boundary=boundary,
            payload=payload,
            source_provenance=normalized_provenance,
        )
        self._emitted_identities.add(emitted_key)
        self._emitted.append(EmittedObject(kind, identity, boundary))

    def _facts_provenance(
        self,
        facts: UnderwritingFacts,
    ) -> tuple[dict[str, object], ...]:
        items: list[dict[str, object]] = []
        for role, source in (
            ("COMBO_QUOTE", facts.quote_source),
            ("COMMISSION", facts.short_instrument_source),
            ("COMMISSION", facts.long_instrument_source),
            ("INDEX", facts.index_source),
            ("POSITION_FACT", facts.ticker_source),
        ):
            items.extend(self._source_provenance(role, source))
        return tuple(items)

    @staticmethod
    def _source_provenance(
        role: str,
        source: SourceFact | None,
    ) -> tuple[dict[str, object], ...]:
        if source is None:
            return ()
        return (
            {
                "source_role": role,
                "source_identity": source.source_identity,
                "receipt_fact_boundary": source.boundary.as_object(),
            },
        )

    @staticmethod
    def _local_provenance(
        role: str,
        identity: str,
        boundary: FactBoundary,
    ) -> tuple[dict[str, object], ...]:
        return (
            {
                "source_role": role,
                "source_identity": identity,
                "receipt_fact_boundary": boundary.as_object(),
            },
        )

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

    def _is_enrolled(self, boundary: FactBoundary) -> bool:
        return (
            self._enrollment_start is not None
            and boundary.is_strictly_after(self._enrollment_start)
            and (self._enrollment_end is None or self._enrollment_end.is_strictly_after(boundary))
        )

    @staticmethod
    def _quote_count_suffix(state: CloseQuoteState) -> str:
        return {
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

    def _finish_transition(self) -> OwnerTransition:
        return OwnerTransition(
            tuple(self._emitted),
            tuple(self._intents),
            tuple(self._retirements),
        )
