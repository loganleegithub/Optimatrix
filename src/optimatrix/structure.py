from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from optimatrix.decision import MarketObservation
from optimatrix.identity import canonical_identity
from optimatrix.market import OptionQuote, OptionType
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


def select_btc_0dte_condor(
    *,
    observation: MarketObservation,
    policy: BtcShortVolPolicy,
) -> Btc0DteCondorSelection:
    if observation.channel_id is not policy.channel_id:
        raise ValueError("MarketObservation does not match the Policy channel")
    if observation.data_health_blockers:
        raise ValueError("structure selection requires healthy MarketObservation data")
    quotes = tuple(sorted(observation.quotes, key=lambda item: item.instrument_name))
    puts = tuple(quote for quote in quotes if quote.option_type is OptionType.PUT)
    calls = tuple(quote for quote in quotes if quote.option_type is OptionType.CALL)
    context = observation.context
    physical_sigma = context.trailing_realized_variance_proxy.sqrt()
    expected_expiry = current_deribit_session(
        observation.observed_at,
        phase_policy=policy.session,
    ).end

    legal_count = 0
    evaluable_count = 0
    eligible: list[Btc0DteCondorCandidate] = []
    rejected: list[str] = []
    for long_put in puts:
        for short_put in puts:
            if not _legal_put_pair(long_put, short_put, context.forward_price, policy):
                continue
            for short_call in calls:
                if not _short_call_eligible(short_call, context.forward_price, policy):
                    continue
                for long_call in calls:
                    if not _legal_call_pair(short_call, long_call, policy):
                        continue
                    if not _same_product_and_expiry(
                        long_put,
                        short_put,
                        short_call,
                        long_call,
                        expected_expiry=expected_expiry,
                    ):
                        continue
                    legal_count += 1
                    pricing = price_btc_0dte_condor(
                        long_put=long_put,
                        short_put=short_put,
                        short_call=short_call,
                        long_call=long_call,
                        amount=policy.structure.option_amount,
                        boundary_index_price=context.index_price,
                    )
                    if pricing is None:
                        continue
                    evaluable_count += 1
                    net_delta = _net_delta(long_put, short_put, short_call, long_call)
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
                    blockers = _policy_blockers(
                        pricing=pricing,
                        net_delta=net_delta,
                        minimum_body_distance=min(put_distance, call_distance),
                        policy=policy,
                    )
                    candidate = Btc0DteCondorCandidate(
                        observation_id=observation.identity,
                        long_put=long_put,
                        short_put=short_put,
                        short_call=short_call,
                        long_call=long_call,
                        option_amount=policy.structure.option_amount,
                        pricing=pricing,
                        net_delta=net_delta,
                        put_body_distance_sigma=put_distance,
                        call_body_distance_sigma=call_distance,
                        policy_blockers=blockers,
                    )
                    if blockers:
                        rejected.extend(blockers)
                    else:
                        eligible.append(candidate)

    if legal_count == 0:
        return Btc0DteCondorSelection(None, (), 0, 0, 0, ("NO_LEGAL_FOUR_LEG_STRUCTURE",))
    if evaluable_count == 0:
        return Btc0DteCondorSelection(
            None,
            (),
            legal_count,
            0,
            0,
            ("NO_PRICE_EVALUABLE_FOUR_LEG_STRUCTURE",),
        )
    if not eligible:
        return Btc0DteCondorSelection(
            None,
            (),
            legal_count,
            evaluable_count,
            0,
            ("NO_POLICY_ELIGIBLE_FOUR_LEG_STRUCTURE", *tuple(dict.fromkeys(rejected))),
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
    )


def _legal_put_pair(
    long_put: OptionQuote,
    short_put: OptionQuote,
    forward: Decimal,
    policy: BtcShortVolPolicy,
) -> bool:
    width = short_put.strike - long_put.strike
    return (
        long_put.instrument_name != short_put.instrument_name
        and long_put.strike < short_put.strike < forward
        and policy.structure.minimum_wing_width_usd
        <= width
        <= policy.structure.maximum_wing_width_usd
        and _short_delta_eligible(short_put, policy)
    )


def _short_call_eligible(
    short_call: OptionQuote,
    forward: Decimal,
    policy: BtcShortVolPolicy,
) -> bool:
    return short_call.strike > forward and _short_delta_eligible(short_call, policy)


def _legal_call_pair(
    short_call: OptionQuote,
    long_call: OptionQuote,
    policy: BtcShortVolPolicy,
) -> bool:
    width = long_call.strike - short_call.strike
    return (
        short_call.instrument_name != long_call.instrument_name
        and short_call.strike < long_call.strike
        and policy.structure.minimum_wing_width_usd
        <= width
        <= policy.structure.maximum_wing_width_usd
    )


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


def _policy_blockers(
    *,
    pricing: Btc0DteCondorPricing,
    net_delta: Decimal,
    minimum_body_distance: Decimal,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if minimum_body_distance < policy.structure.minimum_body_distance_sigma:
        blockers.append("BODY_DISTANCE_TOO_SMALL")
    if abs(net_delta) > policy.structure.maximum_abs_net_delta:
        blockers.append("NET_DELTA_TOO_DIRECTIONAL")
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
