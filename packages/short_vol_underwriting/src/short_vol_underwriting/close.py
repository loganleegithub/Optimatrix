from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from options_domain import ComponentBookQuoteKind, ComponentBookVerticalQuote

from short_vol_underwriting.admission import (
    AdmissionRefreshWitness,
    ComponentBookPairWitness,
    RpcAdmissionRefreshWitness,
    RpcRequestIntent,
    SubscriptionAdmissionRefreshWitness,
)
from short_vol_underwriting.domain import (
    CloseEconomics,
    compute_close_economics,
    compute_component_close_economics,
)
from short_vol_underwriting.identity import canonical_identity, require_identity
from short_vol_underwriting.model import FactBoundary, PredicateTruth


class CloseQuoteState(StrEnum):
    COMPONENT_BOOK_CLOSE_QUOTE = "COMPONENT_BOOK_CLOSE_QUOTE"
    ATOMIC_COMBO_CLOSE_QUOTE = "ATOMIC_COMBO_CLOSE_QUOTE"
    LEGGED_CLOSE_REFERENCE = "LEGGED_CLOSE_REFERENCE"
    UNEXECUTABLE = "UNEXECUTABLE"
    UNKNOWN = "UNKNOWN"


class CloseOptionAvailability(StrEnum):
    TRADEABLE = "TRADEABLE"
    UNEXECUTABLE = "UNEXECUTABLE"
    UNKNOWN = "UNKNOWN"


class CloseAtomicAvailability(StrEnum):
    ACTIVE = "ACTIVE"
    KNOWN_UNAVAILABLE = "KNOWN_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class CloseBookAvailability(StrEnum):
    FULL_QUANTITY = "FULL_QUANTITY"
    INSUFFICIENT = "INSUFFICIENT"
    UNKNOWN = "UNKNOWN"


class CloseOpportunityEligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"


class PostCloseAttemptStatus(StrEnum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    DEADLINE_LATE = "DEADLINE_LATE"
    RETIRED = "RETIRED"
    NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE = "NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE"
    NOT_REQUESTABLE_UNKNOWN = "NOT_REQUESTABLE_UNKNOWN"
    CENSORED = "CENSORED"


class PostCloseAttemptOwner(StrEnum):
    ORDINARY = "ORDINARY"
    STOP = "STOP"
    FAILURE = "FAILURE"


@dataclass(frozen=True)
class CloseQuoteFacts:
    option_availability: CloseOptionAvailability
    atomic_availability: CloseAtomicAvailability
    component_reference: PredicateTruth
    book_availability: CloseBookAvailability
    consumed_levels: tuple[tuple[Decimal, Decimal], ...]
    component_quote: ComponentBookVerticalQuote | None = None


@dataclass(frozen=True)
class CloseOpportunity:
    eligibility: CloseOpportunityEligibility
    eligibility_reason: str
    economics: CloseEconomics | None


@dataclass(frozen=True)
class NormalizedCloseQuote:
    state: CloseQuoteState
    consumed_levels: tuple[tuple[Decimal, Decimal], ...]
    fingerprint_members: tuple[object, ...]


def normalize_close_quote(facts: CloseQuoteFacts) -> NormalizedCloseQuote:
    """Apply the first matching quote rule and retain only facts that rule consumed."""
    if facts.component_quote is not None:
        quote = facts.component_quote
        if quote.kind is not ComponentBookQuoteKind.CLOSE:
            return NormalizedCloseQuote(
                CloseQuoteState.UNKNOWN,
                (),
                ("COMPONENT_QUOTE_KIND_MISMATCH",),
            )
        levels = tuple(
            (level.price, level.amount)
            for leg in (quote.short_leg, quote.long_leg)
            for level in leg.stressed.consumed
        )
        return NormalizedCloseQuote(
            CloseQuoteState.COMPONENT_BOOK_CLOSE_QUOTE,
            levels,
            (quote.fingerprint_members,),
        )
    if facts.option_availability is CloseOptionAvailability.UNEXECUTABLE:
        return NormalizedCloseQuote(
            CloseQuoteState.UNEXECUTABLE,
            (),
            (facts.option_availability.value,),
        )
    if facts.option_availability is CloseOptionAvailability.UNKNOWN:
        return NormalizedCloseQuote(
            CloseQuoteState.UNKNOWN,
            (),
            (facts.option_availability.value,),
        )
    if facts.atomic_availability is CloseAtomicAvailability.KNOWN_UNAVAILABLE:
        members = (
            facts.option_availability.value,
            facts.atomic_availability.value,
            facts.component_reference.value,
        )
        if facts.component_reference is PredicateTruth.TRUE:
            return NormalizedCloseQuote(CloseQuoteState.LEGGED_CLOSE_REFERENCE, (), members)
        if facts.component_reference is PredicateTruth.FALSE:
            return NormalizedCloseQuote(CloseQuoteState.UNEXECUTABLE, (), members)
        return NormalizedCloseQuote(CloseQuoteState.UNKNOWN, (), members)
    if facts.atomic_availability is CloseAtomicAvailability.UNKNOWN:
        return NormalizedCloseQuote(
            CloseQuoteState.UNKNOWN,
            (),
            (
                facts.option_availability.value,
                facts.atomic_availability.value,
            ),
        )
    members = (
        facts.option_availability.value,
        facts.atomic_availability.value,
        facts.book_availability.value,
    )
    if facts.book_availability is CloseBookAvailability.UNKNOWN:
        return NormalizedCloseQuote(CloseQuoteState.UNKNOWN, (), members)
    if facts.book_availability is CloseBookAvailability.FULL_QUANTITY:
        if not facts.consumed_levels:
            return NormalizedCloseQuote(
                CloseQuoteState.UNKNOWN,
                (),
                (*members, "MALFORMED_OR_MISSING_LEVEL"),
            )
        for level in facts.consumed_levels:
            if (
                not isinstance(level, tuple)
                or len(level) != 2
                or not all(isinstance(member, Decimal) for member in level)
            ):
                return NormalizedCloseQuote(
                    CloseQuoteState.UNKNOWN,
                    (),
                    (*members, "MALFORMED_OR_MISSING_LEVEL"),
                )
            price, amount = level
            if not price.is_finite() or not amount.is_finite() or amount <= 0:
                return NormalizedCloseQuote(
                    CloseQuoteState.UNKNOWN,
                    (),
                    (*members, "MALFORMED_OR_MISSING_LEVEL"),
                )
        return NormalizedCloseQuote(
            CloseQuoteState.ATOMIC_COMBO_CLOSE_QUOTE,
            facts.consumed_levels,
            (*members, facts.consumed_levels),
        )
    if facts.consumed_levels:
        return NormalizedCloseQuote(
            CloseQuoteState.UNKNOWN,
            (),
            (*members, "MALFORMED_UNEXPECTED_LEVEL"),
        )
    return NormalizedCloseQuote(CloseQuoteState.UNEXECUTABLE, (), members)


def classify_close_quote(facts: CloseQuoteFacts) -> CloseQuoteState:
    """Apply the frozen six-rule classifier in first-match order."""
    return normalize_close_quote(facts).state


def evaluate_close_opportunity(
    *,
    quote_state: CloseQuoteState,
    full_quantity_btc: Decimal,
    consumed_levels: tuple[tuple[Decimal, Decimal], ...],
    close_direction: str,
    short_leg_taker_commission_fraction: Decimal | None,
    long_leg_taker_commission_fraction: Decimal | None,
    fee_rate_index_fraction: Decimal,
    close_index_usdc_per_btc: Decimal | None,
    net_entry_credit_usdc: Decimal,
    component_quote: ComponentBookVerticalQuote | None = None,
) -> CloseOpportunity:
    """Apply the frozen eligibility rules without consulting ignored later facts."""
    if quote_state in {
        CloseQuoteState.UNEXECUTABLE,
        CloseQuoteState.LEGGED_CLOSE_REFERENCE,
    }:
        return CloseOpportunity(
            CloseOpportunityEligibility.INELIGIBLE,
            quote_state.value,
            None,
        )
    if quote_state is CloseQuoteState.UNKNOWN:
        return CloseOpportunity(
            CloseOpportunityEligibility.UNKNOWN,
            "CLOSE_QUOTE_UNKNOWN",
            None,
        )
    commissions = (
        short_leg_taker_commission_fraction,
        long_leg_taker_commission_fraction,
    )
    if any(value is None or not value.is_finite() or value < 0 for value in commissions):
        return CloseOpportunity(
            CloseOpportunityEligibility.UNKNOWN,
            "COMMISSION_UNKNOWN",
            None,
        )
    if any(value is not None and value > fee_rate_index_fraction for value in commissions):
        return CloseOpportunity(
            CloseOpportunityEligibility.INELIGIBLE,
            "COMMISSION_ABOVE_FROZEN_RESERVE",
            None,
        )
    if (
        close_index_usdc_per_btc is None
        or not close_index_usdc_per_btc.is_finite()
        or close_index_usdc_per_btc <= 0
    ):
        return CloseOpportunity(
            CloseOpportunityEligibility.UNKNOWN,
            "CLOSE_INDEX_UNKNOWN",
            None,
        )
    if quote_state is CloseQuoteState.COMPONENT_BOOK_CLOSE_QUOTE:
        if component_quote is None or component_quote.kind is not ComponentBookQuoteKind.CLOSE:
            return CloseOpportunity(
                CloseOpportunityEligibility.UNKNOWN,
                "COMPONENT_CLOSE_QUOTE_UNKNOWN",
                None,
            )
        economics = compute_component_close_economics(
            quote=component_quote,
            net_entry_credit_usdc=net_entry_credit_usdc,
        )
        return CloseOpportunity(
            CloseOpportunityEligibility.ELIGIBLE,
            "FULL_QUANTITY_COMPONENT_BOOK_QUOTE",
            economics,
        )
    economics = compute_close_economics(
        direction=close_direction,
        full_quantity_btc=full_quantity_btc,
        consumed_levels=consumed_levels,
        index_usdc_per_btc=close_index_usdc_per_btc,
        fee_rate_index_fraction=fee_rate_index_fraction,
        net_entry_credit_usdc=net_entry_credit_usdc,
    )
    return CloseOpportunity(
        CloseOpportunityEligibility.ELIGIBLE,
        "FULL_QUANTITY_ATOMIC_QUOTE",
        economics,
    )


@dataclass
class PostCloseAttempt:
    anchor_identity: str
    first_close_action_identity: str
    origin_boundary: FactBoundary
    scheduled_identity: str
    request_id: int | None
    canonical_combo_identity: str | None
    request_instrument_name: str | None
    origin_quote_witness: SubscriptionAdmissionRefreshWitness | None
    _intent_taken: bool = False
    sent_boundary: FactBoundary | None = None
    terminal_status: PostCloseAttemptStatus | None = None
    terminal_owner: PostCloseAttemptOwner | None = None
    terminal_identity: str | None = None
    terminal_boundary: FactBoundary | None = None
    matched_response_identity: str | None = None
    terminal_unknown_reasons: tuple[str, ...] = ()

    @classmethod
    def schedule(
        cls,
        *,
        anchor_identity: str,
        first_close_action_identity: str,
        canonical_combo_identity: str,
        request_id: int,
        boundary: FactBoundary,
        request_instrument_name: str,
        origin_quote_witness: SubscriptionAdmissionRefreshWitness,
    ) -> PostCloseAttempt:
        require_identity(anchor_identity, "anchor_identity")
        require_identity(first_close_action_identity, "first_close_action_identity")
        require_identity(canonical_combo_identity, "canonical_combo_identity")
        if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 0:
            raise ValueError("request_id must be a non-negative integer")
        if not request_instrument_name:
            raise ValueError("request instrument name must be non-empty")
        if (
            origin_quote_witness.canonical_combo_identity != canonical_combo_identity
            or origin_quote_witness.instrument_name != request_instrument_name
            or (
                origin_quote_witness.boundary != boundary
                and not boundary.is_strictly_after(origin_quote_witness.boundary)
            )
        ):
            raise ValueError("post-CLOSE origin quote witness does not match the scheduled scope")
        instrument_name = request_instrument_name
        params = {"instrument_name": instrument_name, "depth": 10000}
        identity = canonical_identity(
            "ScheduledPostCloseQuoteAttemptIdentity",
            anchor_identity,
            first_close_action_identity,
            request_id,
            "public/get_order_book",
            params,
            boundary.as_object(),
        )
        return cls(
            anchor_identity=anchor_identity,
            first_close_action_identity=first_close_action_identity,
            origin_boundary=boundary,
            scheduled_identity=identity,
            request_id=request_id,
            canonical_combo_identity=canonical_combo_identity,
            request_instrument_name=instrument_name,
            origin_quote_witness=origin_quote_witness,
        )

    @classmethod
    def not_requestable(
        cls,
        *,
        anchor_identity: str,
        first_close_action_identity: str,
        status: PostCloseAttemptStatus,
        boundary: FactBoundary,
    ) -> PostCloseAttempt:
        if status not in {
            PostCloseAttemptStatus.NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE,
            PostCloseAttemptStatus.NOT_REQUESTABLE_UNKNOWN,
        }:
            raise ValueError("not-requestable attempt requires an exact marker status")
        require_identity(anchor_identity, "anchor_identity")
        require_identity(first_close_action_identity, "first_close_action_identity")
        scheduled = canonical_identity(
            "ScheduledPostCloseQuoteAttemptIdentity",
            anchor_identity,
            first_close_action_identity,
            status.value,
            "public/get_order_book",
            None,
            boundary.as_object(),
        )
        attempt = cls(
            anchor_identity=anchor_identity,
            first_close_action_identity=first_close_action_identity,
            origin_boundary=boundary,
            scheduled_identity=scheduled,
            request_id=None,
            canonical_combo_identity=None,
            request_instrument_name=None,
            origin_quote_witness=None,
        )
        attempt._terminalize(
            status=status,
            owner=PostCloseAttemptOwner.ORDINARY,
            boundary=boundary,
            matched_response_identity=None,
            allow_same_boundary=True,
        )
        return attempt

    def take_request_intent(self) -> RpcRequestIntent | None:
        if (
            self._intent_taken
            or self.request_id is None
            or self.canonical_combo_identity is None
            or self.terminal_status is not None
        ):
            return None
        self._intent_taken = True
        return RpcRequestIntent(
            request_id=self.request_id,
            purpose="POST_CLOSE_QUOTE",
            method="public/get_order_book",
            params=MappingProxyType(
                {
                    "instrument_name": self.request_instrument_name,
                    "depth": 10000,
                }
            ),
            scheduled_identity=self.scheduled_identity,
            origin_boundary=self.origin_boundary,
            owner_identity=self.anchor_identity,
        )

    def mark_sent(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
        send_budget_ms: int,
    ) -> bool:
        if (
            request_id != self.request_id
            or self.terminal_status is not None
            or self.sent_boundary is not None
        ):
            return False
        if not boundary.is_strictly_after(self.origin_boundary):
            raise ValueError("post-CLOSE SENT must be strictly after first CLOSE")
        if (
            boundary.received_monotonic_ms - self.origin_boundary.received_monotonic_ms
            > send_budget_ms
        ):
            return self._terminalize(
                status=PostCloseAttemptStatus.DEADLINE_LATE,
                owner=PostCloseAttemptOwner.ORDINARY,
                boundary=boundary,
                matched_response_identity=None,
            )
        self.sent_boundary = boundary
        return True

    def accept_subscription(
        self,
        *,
        witness: SubscriptionAdmissionRefreshWitness,
    ) -> bool:
        if self.terminal_status is not None or not self.subscription_qualifies(witness):
            return False
        return self._terminalize(
            status=PostCloseAttemptStatus.SUCCESS,
            owner=PostCloseAttemptOwner.ORDINARY,
            boundary=witness.boundary,
            matched_response_identity=witness.source_identity,
        )

    def subscription_qualifies(
        self,
        witness: SubscriptionAdmissionRefreshWitness,
        *,
        previous_witness: SubscriptionAdmissionRefreshWitness | None = None,
        canonical_combo_identity: str | None = None,
        instrument_name: str | None = None,
    ) -> bool:
        """Check one unbroken natural quote without consuming the one-shot attempt."""
        origin = self.origin_quote_witness
        previous = previous_witness or origin
        expected_combo_identity = self.canonical_combo_identity or canonical_combo_identity
        expected_instrument_name = self.request_instrument_name or instrument_name
        if (
            expected_combo_identity is None
            or expected_instrument_name is None
            or witness.canonical_combo_identity != expected_combo_identity
            or witness.instrument_name != expected_instrument_name
            or witness.boundary.runtime_identity != self.origin_boundary.runtime_identity
            or not witness.boundary.is_strictly_after(self.origin_boundary)
        ):
            return False
        if previous is None:
            return witness.snapshot_kind == "snapshot"
        if (
            previous.canonical_combo_identity != expected_combo_identity
            or previous.instrument_name != expected_instrument_name
            or previous.boundary.runtime_identity != self.origin_boundary.runtime_identity
            or (
                previous != origin and not previous.boundary.is_strictly_after(self.origin_boundary)
            )
            or not witness.boundary.is_strictly_after(previous.boundary)
        ):
            return False
        same_generation = (
            witness.session_epoch == previous.session_epoch
            and witness.subscription_generation == previous.subscription_generation
        )
        if not same_generation:
            return witness.snapshot_kind == "snapshot"
        if witness.change_id <= previous.change_id:
            return False
        if witness.snapshot_kind == "change" and witness.prev_change_id != previous.change_id:
            return False
        return True

    def accept_response(
        self,
        *,
        witness: RpcAdmissionRefreshWitness,
        response_budget_ms: int,
    ) -> bool:
        if (
            witness.request_id != self.request_id
            or self.terminal_status is not None
            or self.sent_boundary is None
        ):
            return False
        if not witness.boundary.is_strictly_after(self.sent_boundary):
            raise ValueError("matched response must be strictly after SENT")
        invalid = (
            self.canonical_combo_identity is None
            or self.request_instrument_name is None
            or witness.canonical_combo_identity != self.canonical_combo_identity
            or witness.instrument_name != self.request_instrument_name
            or dict(witness.request_params)
            != {"instrument_name": self.request_instrument_name, "depth": 10000}
            or witness.candidate_origin_boundary != self.origin_boundary
            or witness.sent_boundary != self.sent_boundary
            or witness.boundary.runtime_identity != self.origin_boundary.runtime_identity
            or witness.market_frontier_session_epoch != witness.boundary.session_epoch
            or witness.change_id != witness.market_frontier_change_id
            or not witness.response_matches_frontier
            or not witness.response_covers_full_quantity
            or not witness.payload_matches_request
            or not witness.payload_well_formed
        )
        if (
            witness.boundary.received_monotonic_ms - self.sent_boundary.received_monotonic_ms
            > response_budget_ms
        ):
            return self._terminalize(
                status=PostCloseAttemptStatus.DEADLINE_LATE,
                owner=PostCloseAttemptOwner.ORDINARY,
                boundary=witness.boundary,
                matched_response_identity=None,
            )
        if invalid:
            return self._terminalize(
                status=PostCloseAttemptStatus.ERROR,
                owner=PostCloseAttemptOwner.ORDINARY,
                boundary=witness.boundary,
                matched_response_identity=None,
            )
        return self._terminalize(
            status=PostCloseAttemptStatus.SUCCESS,
            owner=PostCloseAttemptOwner.ORDINARY,
            boundary=witness.boundary,
            matched_response_identity=witness.source_identity,
        )

    def accept_refresh(
        self,
        *,
        witness: AdmissionRefreshWitness,
        response_budget_ms: int,
    ) -> bool:
        if isinstance(witness, SubscriptionAdmissionRefreshWitness):
            return self.accept_subscription(witness=witness)
        return self.accept_response(
            witness=witness,
            response_budget_ms=response_budget_ms,
        )

    def fail(
        self,
        *,
        request_id: int,
        status: PostCloseAttemptStatus,
        boundary: FactBoundary,
    ) -> bool:
        if status not in {
            PostCloseAttemptStatus.ERROR,
            PostCloseAttemptStatus.DEADLINE_LATE,
            PostCloseAttemptStatus.RETIRED,
        }:
            raise ValueError("ordinary request failure status is invalid")
        if request_id != self.request_id or self.terminal_status is not None:
            return False
        lower = self.sent_boundary or self.origin_boundary
        if not boundary.is_strictly_after(lower):
            raise ValueError("request failure must be causally later")
        return self._terminalize(
            status=status,
            owner=PostCloseAttemptOwner.ORDINARY,
            boundary=boundary,
            matched_response_identity=None,
        )

    def censor(self, *, boundary: FactBoundary, owner: PostCloseAttemptOwner) -> bool:
        if owner not in {PostCloseAttemptOwner.STOP, PostCloseAttemptOwner.FAILURE}:
            raise ValueError("censor owner must be STOP or FAILURE")
        if self.terminal_status is not None:
            return False
        return self._terminalize(
            status=PostCloseAttemptStatus.CENSORED,
            owner=owner,
            boundary=boundary,
            matched_response_identity=None,
        )

    def _terminalize(
        self,
        *,
        status: PostCloseAttemptStatus,
        owner: PostCloseAttemptOwner,
        boundary: FactBoundary,
        matched_response_identity: str | None,
        allow_same_boundary: bool = False,
    ) -> bool:
        if self.terminal_status is not None:
            return False
        if not allow_same_boundary and not boundary.is_strictly_after(self.origin_boundary):
            raise ValueError("post-CLOSE attempt terminal must be causally later")
        if matched_response_identity is not None:
            require_identity(matched_response_identity, "matched_response_identity")
        self.terminal_status = status
        self.terminal_owner = owner
        self.terminal_boundary = boundary
        self.matched_response_identity = matched_response_identity
        self.terminal_identity = canonical_identity(
            "PostCloseAttemptTerminalIdentity",
            self.scheduled_identity,
            status.value,
            owner.value,
            boundary.as_object(),
        )
        return True


@dataclass
class ComponentPostCloseAttempt:
    anchor_identity: str
    first_close_action_identity: str
    short_option_identity: str
    long_option_identity: str
    short_instrument_name: str
    long_instrument_name: str
    short_request_id: int
    long_request_id: int
    origin_boundary: FactBoundary
    scheduled_identity: str
    _intents_taken: bool = False
    sent_boundaries: dict[int, FactBoundary] = field(default_factory=dict)
    terminal_status: PostCloseAttemptStatus | None = None
    terminal_owner: PostCloseAttemptOwner | None = None
    terminal_identity: str | None = None
    terminal_boundary: FactBoundary | None = None
    matched_response_identity: str | None = None
    terminal_unknown_reasons: tuple[str, ...] = ()
    terminal_pair_timing: dict[str, object] | None = None
    terminal_pair_limits: dict[str, int] | None = None

    @classmethod
    def schedule(
        cls,
        *,
        anchor_identity: str,
        first_close_action_identity: str,
        short_option_identity: str,
        long_option_identity: str,
        short_instrument_name: str,
        long_instrument_name: str,
        short_request_id: int,
        long_request_id: int,
        boundary: FactBoundary,
    ) -> ComponentPostCloseAttempt:
        for value, field_name in (
            (anchor_identity, "anchor_identity"),
            (first_close_action_identity, "first_close_action_identity"),
            (short_option_identity, "short_option_identity"),
            (long_option_identity, "long_option_identity"),
        ):
            require_identity(value, field_name)
        if short_request_id == long_request_id:
            raise ValueError("component post-CLOSE request ids must be distinct")
        for request_id in (short_request_id, long_request_id):
            if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 0:
                raise ValueError("request_id must be a non-negative integer")
        if not short_instrument_name or not long_instrument_name:
            raise ValueError("component post-CLOSE instrument names must be non-empty")
        params = (
            {"instrument_name": short_instrument_name, "depth": 10000},
            {"instrument_name": long_instrument_name, "depth": 10000},
        )
        identity = canonical_identity(
            "ScheduledComponentPostCloseAttemptIdentity",
            anchor_identity,
            first_close_action_identity,
            [short_request_id, long_request_id],
            "public/get_order_book",
            params,
            boundary.as_object(),
        )
        return cls(
            anchor_identity=anchor_identity,
            first_close_action_identity=first_close_action_identity,
            short_option_identity=short_option_identity,
            long_option_identity=long_option_identity,
            short_instrument_name=short_instrument_name,
            long_instrument_name=long_instrument_name,
            short_request_id=short_request_id,
            long_request_id=long_request_id,
            origin_boundary=boundary,
            scheduled_identity=identity,
        )

    @property
    def request_ids(self) -> tuple[int, int]:
        return self.short_request_id, self.long_request_id

    def take_request_intents(self) -> tuple[RpcRequestIntent, ...]:
        if self._intents_taken or self.terminal_status is not None:
            return ()
        self._intents_taken = True
        values = (
            (
                self.short_request_id,
                "COMPONENT_POST_CLOSE_SHORT_REFRESH",
                self.short_instrument_name,
            ),
            (
                self.long_request_id,
                "COMPONENT_POST_CLOSE_LONG_REFRESH",
                self.long_instrument_name,
            ),
        )
        return tuple(
            RpcRequestIntent(
                request_id=request_id,
                purpose=purpose,
                method="public/get_order_book",
                params=MappingProxyType({"instrument_name": name, "depth": 10000}),
                scheduled_identity=self.scheduled_identity,
                origin_boundary=self.origin_boundary,
                owner_identity=self.anchor_identity,
            )
            for request_id, purpose, name in values
        )

    def mark_sent(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
        send_budget_ms: int,
    ) -> bool:
        if (
            request_id not in self.request_ids
            or request_id in self.sent_boundaries
            or self.terminal_status is not None
        ):
            return False
        if not boundary.is_strictly_after(self.origin_boundary):
            raise ValueError("component post-CLOSE SENT must be strictly after first CLOSE")
        if (
            boundary.received_monotonic_ms - self.origin_boundary.received_monotonic_ms
            > send_budget_ms
        ):
            return self._terminalize(
                status=PostCloseAttemptStatus.DEADLINE_LATE,
                owner=PostCloseAttemptOwner.ORDINARY,
                boundary=boundary,
                matched_response_identity=None,
            )
        self.sent_boundaries[request_id] = boundary
        return True

    def accept_pair(
        self,
        *,
        witness: ComponentBookPairWitness,
        response_budget_ms: int,
        maximum_source_skew_ms: int,
        maximum_receive_skew_ms: int,
    ) -> bool:
        if self.terminal_status is not None:
            return False
        expected = (
            (
                witness.short,
                self.short_request_id,
                self.short_option_identity,
                self.short_instrument_name,
            ),
            (
                witness.long,
                self.long_request_id,
                self.long_option_identity,
                self.long_instrument_name,
            ),
        )
        timing_unknown_reasons = witness.timing_unknown_reasons(
            maximum_source_skew_ms=maximum_source_skew_ms,
            maximum_receive_skew_ms=maximum_receive_skew_ms,
        )
        self.terminal_pair_timing = witness.timing_as_object()
        self.terminal_pair_limits = {
            "maximum_source_skew_ms": maximum_source_skew_ms,
            "maximum_receive_skew_ms": maximum_receive_skew_ms,
        }
        invalid = bool(timing_unknown_reasons)
        for member, request_id, option_identity, instrument_name in expected:
            sent = self.sent_boundaries.get(request_id)
            invalid = invalid or (
                sent is None
                or member.request_id != request_id
                or member.canonical_option_identity != option_identity
                or member.instrument_name != instrument_name
                or member.owner_origin_boundary != self.origin_boundary
                or member.sent_boundary != sent
                or not member.payload_matches_request
                or not member.payload_well_formed
            )
            if sent is not None:
                if not member.boundary.is_strictly_after(sent):
                    raise ValueError("component post-CLOSE response must be strictly after SENT")
                if (
                    member.boundary.received_monotonic_ms - sent.received_monotonic_ms
                    > response_budget_ms
                ):
                    invalid = True
        if invalid:
            self.terminal_unknown_reasons = timing_unknown_reasons
        return self._terminalize(
            status=(PostCloseAttemptStatus.ERROR if invalid else PostCloseAttemptStatus.SUCCESS),
            owner=PostCloseAttemptOwner.ORDINARY,
            boundary=witness.boundary,
            matched_response_identity=(None if invalid else witness.pair_identity),
        )

    def fail(
        self,
        *,
        request_id: int,
        status: PostCloseAttemptStatus,
        boundary: FactBoundary,
    ) -> bool:
        if status not in {
            PostCloseAttemptStatus.ERROR,
            PostCloseAttemptStatus.DEADLINE_LATE,
            PostCloseAttemptStatus.RETIRED,
        }:
            raise ValueError("ordinary request failure status is invalid")
        if request_id not in self.request_ids or self.terminal_status is not None:
            return False
        lower = self.sent_boundaries.get(request_id, self.origin_boundary)
        if not boundary.is_strictly_after(lower):
            raise ValueError("component post-CLOSE failure must be causally later")
        return self._terminalize(
            status=status,
            owner=PostCloseAttemptOwner.ORDINARY,
            boundary=boundary,
            matched_response_identity=None,
        )

    def censor(self, *, boundary: FactBoundary, owner: PostCloseAttemptOwner) -> bool:
        if owner not in {PostCloseAttemptOwner.STOP, PostCloseAttemptOwner.FAILURE}:
            raise ValueError("censor owner must be STOP or FAILURE")
        if self.terminal_status is not None:
            return False
        return self._terminalize(
            status=PostCloseAttemptStatus.CENSORED,
            owner=owner,
            boundary=boundary,
            matched_response_identity=None,
        )

    def _terminalize(
        self,
        *,
        status: PostCloseAttemptStatus,
        owner: PostCloseAttemptOwner,
        boundary: FactBoundary,
        matched_response_identity: str | None,
    ) -> bool:
        if self.terminal_status is not None:
            return False
        if not boundary.is_strictly_after(self.origin_boundary):
            raise ValueError("component post-CLOSE terminal must be causally later")
        if matched_response_identity is not None:
            require_identity(matched_response_identity, "matched_response_identity")
        self.terminal_status = status
        self.terminal_owner = owner
        self.terminal_boundary = boundary
        self.matched_response_identity = matched_response_identity
        self.terminal_identity = canonical_identity(
            "ComponentPostCloseAttemptTerminalIdentity",
            self.scheduled_identity,
            status.value,
            owner.value,
            boundary.as_object(),
        )
        return True
