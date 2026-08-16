from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from optimatrix.decision import MarketObservation
from optimatrix.identity import canonical_identity
from optimatrix.market import OptionQuote, OptionType, UnavailableOptionBook
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.pricing import Btc0DteCondorPricing, price_btc_0dte_condor
from optimatrix.products import BTC
from optimatrix.session import current_deribit_session


@dataclass(frozen=True)
class Btc0DteCondorCandidate:
    observation_id: str
    long_put: OptionQuote
    short_put: OptionQuote
    short_call: OptionQuote
    long_call: OptionQuote
    option_amount: Decimal
    pricing: Btc0DteCondorPricing
    net_delta: Decimal
    put_body_distance_sigma: Decimal
    call_body_distance_sigma: Decimal
    policy_blockers: tuple[str, ...]

    @property
    def identity(self) -> str:
        return canonical_identity(
            "Btc0DteCondorCandidateV1",
            self.observation_id,
            self.long_put.instrument_name,
            self.short_put.instrument_name,
            self.short_call.instrument_name,
            self.long_call.instrument_name,
            self.option_amount,
            self.pricing,
            self.net_delta,
            self.put_body_distance_sigma,
            self.call_body_distance_sigma,
            self.policy_blockers,
        )

    @property
    def expiry(self) -> datetime:
        return self.short_put.expiry

    @property
    def minimum_body_distance_sigma(self) -> Decimal:
        return min(self.put_body_distance_sigma, self.call_body_distance_sigma)

    @property
    def close_depth_coverage(self) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        return (
            self.pricing.close_long_put.depth.coverage,
            self.pricing.close_short_put.depth.coverage,
            self.pricing.close_short_call.depth.coverage,
            self.pricing.close_long_call.depth.coverage,
        )


@dataclass(frozen=True)
class Btc0DteCondorSelection:
    selected: Btc0DteCondorCandidate | None
    retained_alternatives: tuple[Btc0DteCondorCandidate, ...]
    legal_structure_count: int
    price_evaluable_count: int
    policy_eligible_count: int
    blockers: tuple[str, ...]
    data_readiness: CandidateDataReadiness
    unavailable_book_names: tuple[str, ...]
    primary_rank_unresolved_book_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (
                self.legal_structure_count,
                self.price_evaluable_count,
                self.policy_eligible_count,
            )
        ):
            raise ValueError("selection counts must be non-negative integers")
        if len(set(self.unavailable_book_names)) != len(self.unavailable_book_names):
            raise ValueError("selection unavailable books must be unique")
        unresolved = set(self.primary_rank_unresolved_book_names)
        if len(unresolved) != len(
            self.primary_rank_unresolved_book_names
        ) or not unresolved.issubset(self.unavailable_book_names):
            raise ValueError("unresolved books must be a unique subset of unavailable books")
        if self.data_readiness is CandidateDataReadiness.PRIMARY_RANK_UNRESOLVED:
            if (
                self.selected is not None
                or not unresolved
                or self.blockers != ("PRIMARY_RANK_UNRESOLVED_BY_MISSING_BOOKS",)
            ):
                raise ValueError("unresolved Primary rank must fail closed with exact evidence")
        elif unresolved:
            raise ValueError("complete Candidate data cannot retain unresolved books")

    @property
    def primary_rank_resolved(self) -> bool:
        return self.data_readiness is CandidateDataReadiness.COMPLETE


class CandidateDataReadiness(StrEnum):
    COMPLETE = "COMPLETE"
    PRIMARY_RANK_UNRESOLVED = "PRIMARY_RANK_UNRESOLVED"


@dataclass(frozen=True)
class Btc0DteCondorEnumeration:
    """Every decision-time four-leg structure that can be priced at the frozen amount."""

    candidates: tuple[Btc0DteCondorCandidate, ...]
    legal_structure_count: int
    data_readiness: CandidateDataReadiness
    unavailable_book_names: tuple[str, ...]
    primary_rank_unresolved_book_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.legal_structure_count < len(self.candidates):
            raise ValueError("legal structure count cannot be below price-evaluable candidates")
        if len(set(self.unavailable_book_names)) != len(self.unavailable_book_names):
            raise ValueError("enumeration unavailable books must be unique")
        unresolved = set(self.primary_rank_unresolved_book_names)
        if len(unresolved) != len(
            self.primary_rank_unresolved_book_names
        ) or not unresolved.issubset(self.unavailable_book_names):
            raise ValueError("enumeration unresolved books must be a unique unavailable subset")
        if self.data_readiness is CandidateDataReadiness.COMPLETE and unresolved:
            raise ValueError("complete enumeration cannot retain unresolved books")
        if self.data_readiness is CandidateDataReadiness.PRIMARY_RANK_UNRESOLVED and not unresolved:
            raise ValueError("unresolved enumeration requires exact missing-book identities")


@dataclass(frozen=True)
class Btc0DteCondorUnderwriting:
    pricing: Btc0DteCondorPricing | None
    net_delta: Decimal
    put_body_distance_sigma: Decimal
    call_body_distance_sigma: Decimal
    legal_blockers: tuple[str, ...]
    structure_limit_blockers: tuple[str, ...]
    economics_blockers: tuple[str, ...]

    @property
    def policy_blockers(self) -> tuple[str, ...]:
        return self.structure_limit_blockers + self.economics_blockers


def underwrite_btc_0dte_condor(
    *,
    observation: MarketObservation,
    long_put: OptionQuote,
    short_put: OptionQuote,
    short_call: OptionQuote,
    long_call: OptionQuote,
    amount: Decimal,
    policy: BtcShortVolPolicy,
) -> Btc0DteCondorUnderwriting:
    """Apply the Decision Policy to one exact four-leg structure.

    Selection and Entry both call this function. Entry supplies the frozen legs, so this function
    evaluates only that structure and never searches for a replacement.
    """

    if observation.channel_id is not policy.channel_id:
        raise ValueError("MarketObservation does not match the Policy channel")
    context = observation.context
    legs = (long_put, short_put, short_call, long_call)
    expected_expiry = current_deribit_session(
        observation.observed_at,
        phase_policy=policy.session,
    ).end
    legal_blockers = btc_condor_legal_blockers(
        long_put=long_put,
        short_put=short_put,
        short_call=short_call,
        long_call=long_call,
        amount=amount,
        forward_price=context.forward_price,
        expected_expiry=expected_expiry,
        policy=policy,
    )

    physical_sigma = context.trailing_realized_variance_proxy.sqrt()
    net_delta = _net_delta(*legs)
    put_distance = _log_distance_sigma(
        strike=short_put.strike,
        forward=context.forward_price,
        physical_sigma=physical_sigma,
    )
    call_distance = _log_distance_sigma(
        strike=short_call.strike,
        forward=context.forward_price,
        physical_sigma=physical_sigma,
    )
    structure_limit_blockers = btc_condor_structure_limit_blockers(
        net_delta=net_delta,
        minimum_body_distance=min(put_distance, call_distance),
        policy=policy,
    )
    pricing = None
    economics_blockers: tuple[str, ...] = ()
    if not legal_blockers:
        pricing = price_btc_0dte_condor(
            long_put=long_put,
            short_put=short_put,
            short_call=short_call,
            long_call=long_call,
            amount=amount,
            boundary_index_price=context.index_price,
        )
        if pricing is not None:
            economics_blockers = btc_condor_economics_blockers(pricing=pricing, policy=policy)
    return Btc0DteCondorUnderwriting(
        pricing=pricing,
        net_delta=net_delta,
        put_body_distance_sigma=put_distance,
        call_body_distance_sigma=call_distance,
        legal_blockers=legal_blockers,
        structure_limit_blockers=structure_limit_blockers,
        economics_blockers=economics_blockers,
    )


def btc_condor_legal_blockers(
    *,
    long_put: OptionQuote,
    short_put: OptionQuote,
    short_call: OptionQuote,
    long_call: OptionQuote,
    amount: Decimal,
    forward_price: Decimal,
    expected_expiry: datetime,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    legs = (long_put, short_put, short_call, long_call)
    legal_blockers = [
        *_put_pair_blockers(
            long_put=long_put,
            short_put=short_put,
            forward_price=forward_price,
            policy=policy,
        ),
        *_short_call_blockers(
            short_call=short_call,
            forward_price=forward_price,
            policy=policy,
        ),
        *_call_pair_blockers(
            short_call=short_call,
            long_call=long_call,
            policy=policy,
        ),
    ]
    if len({leg.instrument_name for leg in legs}) != 4:
        legal_blockers.append("FOUR_LEG_IDENTITIES_NOT_DISTINCT")
    if not _same_product_and_expiry(*legs, expected_expiry=expected_expiry):
        legal_blockers.append("FOUR_LEG_PRODUCT_OR_EXPIRY_INVALID")
    if amount != policy.structure.option_amount:
        legal_blockers.append("OPTION_AMOUNT_OUTSIDE_POLICY")
    return tuple(dict.fromkeys(legal_blockers))


def _put_pair_blockers(
    *,
    long_put: OptionQuote,
    short_put: OptionQuote,
    forward_price: Decimal,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if long_put.instrument_name == short_put.instrument_name:
        blockers.append("FOUR_LEG_IDENTITIES_NOT_DISTINCT")
    if long_put.option_type is not OptionType.PUT or short_put.option_type is not OptionType.PUT:
        blockers.append("FOUR_LEG_OPTION_TYPES_INVALID")
    if not long_put.strike < short_put.strike < forward_price:
        blockers.append("FOUR_LEG_STRIKE_GEOMETRY_INVALID")
    width = short_put.strike - long_put.strike
    if not (
        policy.structure.minimum_wing_width_usd <= width <= policy.structure.maximum_wing_width_usd
    ):
        blockers.append("PUT_WING_WIDTH_OUTSIDE_POLICY")
    if not _short_delta_eligible(short_put, policy):
        blockers.append("SHORT_PUT_DELTA_OUTSIDE_POLICY")
    return tuple(blockers)


def _short_call_blockers(
    *,
    short_call: OptionQuote,
    forward_price: Decimal,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if short_call.option_type is not OptionType.CALL:
        blockers.append("FOUR_LEG_OPTION_TYPES_INVALID")
    if short_call.strike <= forward_price:
        blockers.append("FOUR_LEG_STRIKE_GEOMETRY_INVALID")
    if not _short_delta_eligible(short_call, policy):
        blockers.append("SHORT_CALL_DELTA_OUTSIDE_POLICY")
    return tuple(blockers)


def _call_pair_blockers(
    *,
    short_call: OptionQuote,
    long_call: OptionQuote,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if short_call.instrument_name == long_call.instrument_name:
        blockers.append("FOUR_LEG_IDENTITIES_NOT_DISTINCT")
    if (
        short_call.option_type is not OptionType.CALL
        or long_call.option_type is not OptionType.CALL
    ):
        blockers.append("FOUR_LEG_OPTION_TYPES_INVALID")
    if short_call.strike >= long_call.strike:
        blockers.append("FOUR_LEG_STRIKE_GEOMETRY_INVALID")
    width = long_call.strike - short_call.strike
    if not (
        policy.structure.minimum_wing_width_usd <= width <= policy.structure.maximum_wing_width_usd
    ):
        blockers.append("CALL_WING_WIDTH_OUTSIDE_POLICY")
    return tuple(blockers)


def btc_condor_structure_limit_blockers(
    *,
    net_delta: Decimal,
    minimum_body_distance: Decimal,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if minimum_body_distance < policy.structure.minimum_body_distance_sigma:
        blockers.append("BODY_DISTANCE_TOO_SMALL")
    if abs(net_delta) > policy.structure.maximum_abs_net_delta:
        blockers.append("NET_DELTA_TOO_DIRECTIONAL")
    return tuple(blockers)


def btc_condor_economics_blockers(
    *,
    pricing: Btc0DteCondorPricing,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    blockers: list[str] = []
    underwriting = policy.underwriting
    if pricing.boundary_net_credit_usd < underwriting.minimum_boundary_net_credit_usd:
        blockers.append("BOUNDARY_NET_CREDIT_TOO_SMALL")
    if (
        pricing.boundary_net_credit_usd / pricing.maximum_contractual_payoff_cap_usd
        < underwriting.minimum_credit_to_payoff_cap
    ):
        blockers.append("CREDIT_TO_PAYOFF_CAP_TOO_SMALL")
    if pricing.boundary_reference_loss_usd > underwriting.maximum_boundary_reference_loss_usd:
        blockers.append("BOUNDARY_REFERENCE_LOSS_TOO_HIGH")
    if (
        pricing.combo_standard_fee_native / pricing.native_gross_credit
        > underwriting.maximum_combo_fee_fraction_of_credit
    ):
        blockers.append("COMBO_FEE_BURDEN_TOO_HIGH")
    return tuple(blockers)


def select_btc_0dte_condor(
    *,
    observation: MarketObservation,
    policy: BtcShortVolPolicy,
) -> Btc0DteCondorSelection:
    enumeration = enumerate_btc_0dte_condors(observation=observation, policy=policy)
    legal_count = enumeration.legal_structure_count
    candidates = enumeration.candidates
    evaluable_count = len(candidates)
    eligible = [candidate for candidate in candidates if not candidate.policy_blockers]
    rejected = [blocker for candidate in candidates for blocker in candidate.policy_blockers]
    if enumeration.data_readiness is CandidateDataReadiness.PRIMARY_RANK_UNRESOLVED:
        return Btc0DteCondorSelection(
            selected=None,
            retained_alternatives=(),
            legal_structure_count=legal_count,
            price_evaluable_count=evaluable_count,
            policy_eligible_count=len(eligible),
            blockers=("PRIMARY_RANK_UNRESOLVED_BY_MISSING_BOOKS",),
            data_readiness=enumeration.data_readiness,
            unavailable_book_names=enumeration.unavailable_book_names,
            primary_rank_unresolved_book_names=(enumeration.primary_rank_unresolved_book_names),
        )
    if legal_count == 0:
        return Btc0DteCondorSelection(
            selected=None,
            retained_alternatives=(),
            legal_structure_count=0,
            price_evaluable_count=0,
            policy_eligible_count=0,
            blockers=("NO_LEGAL_FOUR_LEG_STRUCTURE",),
            data_readiness=CandidateDataReadiness.COMPLETE,
            unavailable_book_names=enumeration.unavailable_book_names,
            primary_rank_unresolved_book_names=(),
        )
    if evaluable_count == 0:
        return Btc0DteCondorSelection(
            selected=None,
            retained_alternatives=(),
            legal_structure_count=legal_count,
            price_evaluable_count=0,
            policy_eligible_count=0,
            blockers=("NO_PRICE_EVALUABLE_FOUR_LEG_STRUCTURE",),
            data_readiness=CandidateDataReadiness.COMPLETE,
            unavailable_book_names=enumeration.unavailable_book_names,
            primary_rank_unresolved_book_names=(),
        )
    if not eligible:
        return Btc0DteCondorSelection(
            selected=None,
            retained_alternatives=(),
            legal_structure_count=legal_count,
            price_evaluable_count=evaluable_count,
            policy_eligible_count=0,
            blockers=("NO_POLICY_ELIGIBLE_FOUR_LEG_STRUCTURE", *tuple(dict.fromkeys(rejected))),
            data_readiness=CandidateDataReadiness.COMPLETE,
            unavailable_book_names=enumeration.unavailable_book_names,
            primary_rank_unresolved_book_names=(),
        )
    ordered = tuple(sorted(eligible, key=_rank_key))
    selected = ordered[0]
    alternatives = ordered[1 : 1 + policy.structure.maximum_retained_alternatives]
    return Btc0DteCondorSelection(
        selected=selected,
        retained_alternatives=alternatives,
        legal_structure_count=legal_count,
        price_evaluable_count=evaluable_count,
        policy_eligible_count=len(eligible),
        blockers=(),
        data_readiness=CandidateDataReadiness.COMPLETE,
        unavailable_book_names=enumeration.unavailable_book_names,
        primary_rank_unresolved_book_names=(),
    )


def enumerate_btc_0dte_condors(
    *,
    observation: MarketObservation,
    policy: BtcShortVolPolicy,
) -> Btc0DteCondorEnumeration:
    """Enumerate the frozen Policy geometry without applying its strategy gates.

    The current selector and offline AI Lab share this owner. A member is still required to be a
    legal four-leg product and price-evaluable at the full Policy amount, but its environment,
    structure-limit, and underwriting blockers are retained instead of filtering it away.
    """

    if observation.channel_id is not policy.channel_id:
        raise ValueError("MarketObservation does not match the Policy channel")
    if observation.data_health_blockers:
        raise ValueError("structure enumeration requires healthy MarketObservation data")
    quotes = tuple(sorted(observation.quotes, key=lambda item: item.instrument_name))
    puts = tuple(quote for quote in quotes if quote.option_type is OptionType.PUT)
    calls = tuple(quote for quote in quotes if quote.option_type is OptionType.CALL)
    context = observation.context
    expected_expiry = current_deribit_session(
        observation.observed_at,
        phase_policy=policy.session,
    ).end
    unavailable_book_names = tuple(
        sorted(book.instrument_name for book in observation.unavailable_books)
    )
    primary_rank_unresolved_book_names = _primary_rank_unresolved_books(
        observation=observation,
        policy=policy,
        expected_expiry=expected_expiry,
    )
    legal_count = 0
    candidates: list[Btc0DteCondorCandidate] = []
    for long_put in puts:
        for short_put in puts:
            if _put_pair_blockers(
                long_put=long_put,
                short_put=short_put,
                forward_price=context.forward_price,
                policy=policy,
            ):
                continue
            for short_call in calls:
                if _short_call_blockers(
                    short_call=short_call,
                    forward_price=context.forward_price,
                    policy=policy,
                ):
                    continue
                for long_call in calls:
                    if _call_pair_blockers(
                        short_call=short_call,
                        long_call=long_call,
                        policy=policy,
                    ):
                        continue
                    legal_blockers = btc_condor_legal_blockers(
                        long_put=long_put,
                        short_put=short_put,
                        short_call=short_call,
                        long_call=long_call,
                        amount=policy.structure.option_amount,
                        forward_price=context.forward_price,
                        expected_expiry=expected_expiry,
                        policy=policy,
                    )
                    if legal_blockers:
                        continue
                    underwriting = underwrite_btc_0dte_condor(
                        observation=observation,
                        long_put=long_put,
                        short_put=short_put,
                        short_call=short_call,
                        long_call=long_call,
                        amount=policy.structure.option_amount,
                        policy=policy,
                    )
                    legal_count += 1
                    pricing = underwriting.pricing
                    if pricing is None:
                        continue
                    blockers = underwriting.policy_blockers
                    candidate = Btc0DteCondorCandidate(
                        observation_id=observation.identity,
                        long_put=long_put,
                        short_put=short_put,
                        short_call=short_call,
                        long_call=long_call,
                        option_amount=policy.structure.option_amount,
                        pricing=pricing,
                        net_delta=underwriting.net_delta,
                        put_body_distance_sigma=underwriting.put_body_distance_sigma,
                        call_body_distance_sigma=underwriting.call_body_distance_sigma,
                        policy_blockers=blockers,
                    )
                    candidates.append(candidate)

    return Btc0DteCondorEnumeration(
        candidates=tuple(candidates),
        legal_structure_count=legal_count,
        data_readiness=(
            CandidateDataReadiness.PRIMARY_RANK_UNRESOLVED
            if primary_rank_unresolved_book_names
            else CandidateDataReadiness.COMPLETE
        ),
        unavailable_book_names=unavailable_book_names,
        primary_rank_unresolved_book_names=primary_rank_unresolved_book_names,
    )


def _primary_rank_unresolved_books(
    *,
    observation: MarketObservation,
    policy: BtcShortVolPolicy,
    expected_expiry: datetime,
) -> tuple[str, ...]:
    if not observation.unavailable_books:
        return ()
    books: tuple[OptionQuote | UnavailableOptionBook, ...] = (
        *observation.quotes,
        *observation.unavailable_books,
    )
    puts = tuple(book for book in books if book.option_type is OptionType.PUT)
    calls = tuple(book for book in books if book.option_type is OptionType.CALL)
    physical_sigma = observation.context.trailing_realized_variance_proxy.sqrt()
    put_pairs = tuple(
        (long_put, short_put)
        for long_put in puts
        for short_put in puts
        if _potential_put_pair(
            long_put=long_put,
            short_put=short_put,
            forward_price=observation.context.forward_price,
            physical_sigma=physical_sigma,
            expected_expiry=expected_expiry,
            policy=policy,
        )
    )
    call_pairs = tuple(
        (short_call, long_call)
        for short_call in calls
        for long_call in calls
        if _potential_call_pair(
            short_call=short_call,
            long_call=long_call,
            forward_price=observation.context.forward_price,
            physical_sigma=physical_sigma,
            expected_expiry=expected_expiry,
            policy=policy,
        )
    )
    if not put_pairs or not call_pairs:
        return ()
    unavailable_names = {book.instrument_name for book in observation.unavailable_books}
    unresolved: set[str] = set()
    for put_pair in put_pairs:
        for call_pair in call_pairs:
            candidate_names = {book.instrument_name for book in (*put_pair, *call_pair)}
            unresolved.update(candidate_names & unavailable_names)
    return tuple(sorted(unresolved))


def _potential_put_pair(
    *,
    long_put: OptionQuote | UnavailableOptionBook,
    short_put: OptionQuote | UnavailableOptionBook,
    forward_price: Decimal,
    physical_sigma: Decimal,
    expected_expiry: datetime,
    policy: BtcShortVolPolicy,
) -> bool:
    width = short_put.strike - long_put.strike
    return (
        long_put.instrument_name != short_put.instrument_name
        and _potential_book_scope(long_put, expected_expiry=expected_expiry)
        and _potential_book_scope(short_put, expected_expiry=expected_expiry)
        and long_put.strike < short_put.strike < forward_price
        and policy.structure.minimum_wing_width_usd
        <= width
        <= policy.structure.maximum_wing_width_usd
        and _potential_short_delta(short_put, policy=policy)
        and _log_distance_sigma(
            strike=short_put.strike,
            forward=forward_price,
            physical_sigma=physical_sigma,
        )
        >= policy.structure.minimum_body_distance_sigma
    )


def _potential_call_pair(
    *,
    short_call: OptionQuote | UnavailableOptionBook,
    long_call: OptionQuote | UnavailableOptionBook,
    forward_price: Decimal,
    physical_sigma: Decimal,
    expected_expiry: datetime,
    policy: BtcShortVolPolicy,
) -> bool:
    width = long_call.strike - short_call.strike
    return (
        short_call.instrument_name != long_call.instrument_name
        and _potential_book_scope(short_call, expected_expiry=expected_expiry)
        and _potential_book_scope(long_call, expected_expiry=expected_expiry)
        and forward_price < short_call.strike < long_call.strike
        and policy.structure.minimum_wing_width_usd
        <= width
        <= policy.structure.maximum_wing_width_usd
        and _potential_short_delta(short_call, policy=policy)
        and _log_distance_sigma(
            strike=short_call.strike,
            forward=forward_price,
            physical_sigma=physical_sigma,
        )
        >= policy.structure.minimum_body_distance_sigma
    )


def _potential_book_scope(
    book: OptionQuote | UnavailableOptionBook,
    *,
    expected_expiry: datetime,
) -> bool:
    return book.product == BTC and book.expiry == expected_expiry


def _potential_short_delta(
    book: OptionQuote | UnavailableOptionBook,
    *,
    policy: BtcShortVolPolicy,
) -> bool:
    return isinstance(book, UnavailableOptionBook) or _short_delta_eligible(book, policy)


def _short_delta_eligible(quote: OptionQuote, policy: BtcShortVolPolicy) -> bool:
    absolute = abs(quote.signed_delta)
    return policy.structure.short_delta_min <= absolute <= policy.structure.short_delta_max


def _same_product_and_expiry(
    *legs: OptionQuote,
    expected_expiry: datetime,
) -> bool:
    return (
        all(leg.product == BTC for leg in legs)
        and len({leg.expiry for leg in legs}) == 1
        and legs[0].expiry == expected_expiry
    )


def _net_delta(*legs: OptionQuote) -> Decimal:
    long_put, short_put, short_call, long_call = legs
    return (
        long_put.signed_delta
        - short_put.signed_delta
        - short_call.signed_delta
        + long_call.signed_delta
    )


def _log_distance_sigma(
    *,
    strike: Decimal,
    forward: Decimal,
    physical_sigma: Decimal,
) -> Decimal:
    if physical_sigma <= 0:
        raise ValueError("trailing realized-variance proxy must be positive")
    return abs((strike / forward).ln()) / physical_sigma


def _rank_key(candidate: Btc0DteCondorCandidate) -> tuple[Decimal | str, ...]:
    pricing = candidate.pricing
    credit_ratio = pricing.boundary_net_credit_usd / pricing.maximum_contractual_payoff_cap_usd
    fee_fraction = pricing.combo_standard_fee_native / pricing.native_gross_credit
    minimum_close_coverage = min(candidate.close_depth_coverage)
    return (
        -credit_ratio,
        -pricing.native_net_credit,
        fee_fraction,
        -minimum_close_coverage,
        candidate.long_put.instrument_name,
        candidate.short_put.instrument_name,
        candidate.short_call.instrument_name,
        candidate.long_call.instrument_name,
    )
