from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from options_domain import (
    INVERSE_BTC,
    OptionProductName,
    product_for_name,
)


def test_product_profile_is_inverse_only() -> None:
    assert product_for_name(OptionProductName.INVERSE_BTC) is INVERSE_BTC
    assert product_for_name("inverse-btc") is INVERSE_BTC
    with pytest.raises(ValueError, match="unsupported option product: linear-btc-usdc"):
        product_for_name("linear-btc-usdc")
    assert INVERSE_BTC.public_currency == "BTC"
    assert INVERSE_BTC.price_index == "btc_usd"
    assert INVERSE_BTC.instrument_type == "reversed"
    assert INVERSE_BTC.option_lifecycle_channel == "instrument.state.option.BTC"
    assert INVERSE_BTC.index_channel == "deribit_price_index.btc_usd"
    assert INVERSE_BTC.economic_semantics_version == "INVERSE_BTC_V1"
    assert INVERSE_BTC.case_schema_version == 5
    assert INVERSE_BTC.native_settlement_liability_profile == (
        "SETTLEMENT_PRICE_DEPENDENT_RECIPROCAL_BTC_LIABILITY"
    )


def test_inverse_native_premium_has_separate_model_and_boundary_values() -> None:
    native = Decimal("0.0200")
    forward = Decimal("100000")
    index = Decimal("99500")
    assert INVERSE_BTC.model_premium(native, forward_price=forward) == Decimal("2000.0000")
    assert INVERSE_BTC.valuation(native, index_price=index) == Decimal("1990.0000")


def test_inverse_native_fee_preserves_native_and_valuation_currency() -> None:
    q = Decimal("0.1")
    rate = Decimal("0.0003")
    index = Decimal("100000")
    inverse_fee = INVERSE_BTC.native_option_fee(
        native_option_price=Decimal("0.0200"),
        index_price=index,
        quantity_btc=q,
        fee_rate=rate,
    )
    assert inverse_fee == Decimal("0.000030")
    assert INVERSE_BTC.valuation(inverse_fee, index_price=index) == Decimal("3.000000")


def test_inverse_native_payoff_liability_depends_on_expiry_delivery_price() -> None:
    contractual_usd_payoff = Decimal("100")

    high_delivery_liability = INVERSE_BTC.native_payoff_from_strike_value(
        contractual_usd_payoff,
        settlement_price=Decimal("100000"),
    )
    low_delivery_liability = INVERSE_BTC.native_payoff_from_strike_value(
        contractual_usd_payoff,
        settlement_price=Decimal("50000"),
    )

    assert high_delivery_liability == Decimal("0.001")
    assert low_delivery_liability == Decimal("0.002")
    assert low_delivery_liability > high_delivery_liability


def test_inverse_underwriting_margins_use_declared_valuation_unit() -> None:
    from short_vol_underwriting import UnderwritingThresholdMargins

    margins = UnderwritingThresholdMargins(
        positive_net_credit_usdc=Decimal("20"),
        credit_above_future_cost_reserve_usdc=Decimal("8"),
        reserved_loss_limit_headroom_usdc=Decimal("100"),
        minimum_net_credit_headroom_usdc=Decimal("5"),
        minimum_credit_ratio_headroom=Decimal("0.1"),
        entry_consumed_level_headroom=10,
    )
    vector = margins.as_vector(INVERSE_BTC.valuation_currency)
    assert [member["unit"] for member in vector] == [
        "USD_EQUIVALENT",
        "USD_EQUIVALENT",
        "USD_EQUIVALENT",
        "USD_EQUIVALENT",
        "FRACTION",
        "LEVEL_COUNT",
    ]


def _inverse_option_payload(*, name: str = "BTC-8AUG26-100000-C") -> dict[str, object]:
    return {
        "instrument_name": name,
        "kind": "option",
        "base_currency": "BTC",
        "quote_currency": "BTC",
        "settlement_currency": "BTC",
        "counter_currency": "USD",
        "price_index": "btc_usd",
        "instrument_type": "reversed",
        "is_active": True,
        "state": "open",
        "option_type": "call",
        "expiration_timestamp": 1_800_000_000_000,
        "strike": 100000,
        "contract_size": 1,
        "min_trade_amount": 0.1,
        "qty_tick_size": 0.1,
        "tick_size": 0.0001,
        "tick_size_steps": [{"above_price": 0.005, "tick_size": 0.0005}],
        "taker_commission": 0.0003,
    }


def test_inverse_instrument_parser_uses_exact_profile() -> None:
    from options_domain import parse_option_instrument

    instrument = parse_option_instrument(_inverse_option_payload(), product=INVERSE_BTC)
    assert instrument is not None
    assert instrument.product is INVERSE_BTC
    assert instrument.amount is not None
    assert instrument.amount.min_trade_amount == Decimal("0.1")
    assert instrument.price_tick is not None
    assert instrument.price_tick.previous_legal_price(Decimal("0.005")) == Decimal("0.0049")
    assert (
        parse_option_instrument(
            {**_inverse_option_payload(), "quote_currency": "USDC"},
            product=INVERSE_BTC,
        )
        is None
    )
    assert (
        parse_option_instrument(
            {**_inverse_option_payload(), "instrument_name": "BTC_USDC-8AUG26-100000-C"},
            product=INVERSE_BTC,
        )
        is None
    )


def test_inverse_combo_parser_rejects_cross_product_leg_names() -> None:
    from options_domain import parse_combo_instrument

    summary = {
        "id": "BTC-COMBO",
        "state": "active",
        "legs": [
            {"instrument_name": "BTC-8AUG26-100000-C", "amount": -1},
            {"instrument_name": "BTC-8AUG26-110000-C", "amount": 1},
        ],
    }
    metadata = {
        "instrument_name": "BTC-COMBO",
        "kind": "option_combo",
        "base_currency": "BTC",
        "quote_currency": "BTC",
        "settlement_currency": "BTC",
        "counter_currency": "USD",
        "instrument_type": "reversed",
        "state": "open",
        "is_active": True,
        "contract_size": 1,
        "min_trade_amount": 0.1,
        "qty_tick_size": 0.1,
    }

    combo = parse_combo_instrument(summary, metadata, product=INVERSE_BTC)
    assert combo is not None
    assert combo.product is INVERSE_BTC
    contaminated = {
        **summary,
        "legs": [
            summary["legs"][0],
            {"instrument_name": "BTC_USDC-8AUG26-110000-C", "amount": 1},
        ],
    }
    assert parse_combo_instrument(contaminated, metadata, product=INVERSE_BTC) is None


def test_inverse_component_quote_stresses_native_ticks_then_values_at_index() -> None:
    from market_monitor import ContinuousOrderBook, PriceLevel
    from options_domain import (
        ComponentBookQuoteKind,
        evaluate_component_book_vertical,
        parse_option_instrument,
    )

    short_payload = _inverse_option_payload(name="BTC-8AUG26-100000-C")
    long_payload = {**_inverse_option_payload(name="BTC-8AUG26-110000-C"), "strike": 110000}
    short = parse_option_instrument(short_payload, product=INVERSE_BTC)
    long = parse_option_instrument(long_payload, product=INVERSE_BTC)
    assert short is not None and long is not None
    quote, reasons = evaluate_component_book_vertical(
        kind=ComponentBookQuoteKind.ENTRY,
        short_instrument=short,
        long_instrument=long,
        short_side_levels=(PriceLevel(Decimal("0.0060"), Decimal("0.1")),),
        long_side_levels=(PriceLevel(Decimal("0.0020"), Decimal("0.1")),),
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=Decimal("0.1"),
        fee_rate_index_fraction=Decimal("0.0003"),
    )
    assert reasons == ()
    assert quote is not None
    assert quote.product_spec_identity == INVERSE_BTC.identity
    assert quote.short_leg.stressed.vwap == Decimal("0.0055")
    assert quote.long_leg.stressed.vwap == Decimal("0.0021")
    assert quote.native_gross_cashflow == Decimal("0.00034")
    assert quote.gross_cashflow_usdc == Decimal("34.00000")
    assert quote.native_total_fee_reserve == Decimal("0.00005625")
    assert quote.total_fee_reserve_usdc == Decimal("5.62500000")
    assert quote.native_net_cashflow == Decimal("0.00028375")
    assert quote.net_cashflow_usdc == Decimal("28.37500000")
    assert quote.payoff_cap_usdc == Decimal("1000.0")

    from short_vol_radar.review import _legged_reference

    short_book = ContinuousOrderBook(short.instrument_name)
    short_book.apply(
        {
            "type": "snapshot",
            "timestamp": 1,
            "instrument_name": short.instrument_name,
            "change_id": 1,
            "bids": [["new", "0.0060", "0.1"]],
            "asks": [["new", "0.0062", "0.1"]],
        },
        1,
    )
    long_book = ContinuousOrderBook(long.instrument_name)
    long_book.apply(
        {
            "type": "snapshot",
            "timestamp": 1,
            "instrument_name": long.instrument_name,
            "change_id": 1,
            "bids": [["new", "0.0018", "0.1"]],
            "asks": [["new", "0.0020", "0.1"]],
        },
        1,
    )
    reference, reference_reasons = _legged_reference(
        short_instrument=short,
        long_instrument=long,
        short_book=short_book,
        long_book=long_book,
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=Decimal("0.1"),
        fee_rate_index_fraction=Decimal("0.0003"),
    )
    assert reference_reasons == ()
    assert reference is not None
    reference_object = reference.as_object()
    assert "_usdc" not in json.dumps(reference_object, sort_keys=True).lower()
    assert reference_object["native_premium_currency"] == "BTC"
    assert reference_object["stressed_gross_credit_native"] == "0.00034"
    assert reference_object["stressed_gross_credit_valuation"] == "34.00000"


def test_inverse_owner_fails_closed_on_tampered_component_quote(repository_root: Path) -> None:
    from dataclasses import replace

    from market_monitor import PriceLevel
    from options_domain import (
        AmountMetadata,
        ComponentBookQuoteKind,
        OptionInstrument,
        OptionType,
        PriceTickMetadata,
        evaluate_component_book_vertical,
    )
    from short_vol_underwriting import (
        FactBoundary,
        FixedContractShadowOwner,
        RuntimeBindings,
        ShadowStateStore,
        SourceFact,
        UnderwritingFacts,
        load_policy_chain,
    )
    from short_vol_underwriting.constants import (
        INVERSE_BTC_POSITION_POLICY_IDENTITY,
        INVERSE_BTC_RADAR_POLICY_IDENTITY,
        INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
    )

    code = "a" * 40
    runtime = "sha256:" + "b" * 64
    boundary = FactBoundary(code, runtime, 1, 2, 102, 2)
    amount = AmountMetadata(Decimal("1"), Decimal("0.1"), Decimal("0.1"))
    tick = PriceTickMetadata(Decimal("0.0001"))
    short = OptionInstrument(
        "BTC-8AUG26-100000-C",
        1_800_000_000_000,
        Decimal("100000"),
        OptionType.CALL,
        amount,
        tick,
        product=INVERSE_BTC,
    )
    long = OptionInstrument(
        "BTC-8AUG26-101000-C",
        1_800_000_000_000,
        Decimal("101000"),
        OptionType.CALL,
        amount,
        tick,
        product=INVERSE_BTC,
    )
    valid_quote, reasons = evaluate_component_book_vertical(
        kind=ComponentBookQuoteKind.ENTRY,
        short_instrument=short,
        long_instrument=long,
        short_side_levels=(PriceLevel(Decimal("0.0060"), Decimal("0.1")),),
        long_side_levels=(PriceLevel(Decimal("0.0020"), Decimal("0.1")),),
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=Decimal("0.1"),
        fee_rate_index_fraction=Decimal("0.0003"),
    )
    assert valid_quote is not None and reasons == ()
    quote = replace(valid_quote, product_spec_identity="sha256:" + "0" * 64)

    policies = load_policy_chain(
        radar_path=repository_root / "policies/short-vol-inverse-btc-public-shadow-radar.json",
        underwriting_path=(
            repository_root / "policies/short-vol-inverse-btc-public-shadow-underwriting.json"
        ),
        position_path=(
            repository_root / "policies/short-vol-inverse-btc-public-shadow-position.json"
        ),
        radar_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )
    bindings = RuntimeBindings(
        code,
        runtime,
        INVERSE_BTC_RADAR_POLICY_IDENTITY,
        INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )
    state_store = ShadowStateStore(bindings=bindings)
    owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        state_store=state_store,
    )
    source = SourceFact("sha256:" + "c" * 64, boundary)
    from short_vol_radar import RadarScorePacket, ScoreBand
    from short_vol_radar.bucket import radar_bucket_episode_identity

    score_packet = RadarScorePacket.from_object(
        {
            "packet_schema_version": 1,
            "policy_identity": INVERSE_BTC_RADAR_POLICY_IDENTITY,
            "fact_boundary": boundary.as_object(),
            "bucket_key": {
                "tte_band_id": "six-to-twenty-four-hours",
                "expiry_ms": short.expiration_timestamp_ms,
                "option_type": "call",
                "delta_bucket": "0.15-0.25",
            },
            "leader_instrument_name": short.instrument_name,
            "leader_coverage": "COMPLETE",
            "result": {
                "premium_evidence": {"lower": "0.8", "upper": "0.8"},
                "risk_quality": {"lower": "0.8", "upper": "0.8"},
                "score": {"lower": "70", "upper": "70"},
                "band": "HIGH",
                "coverage": "COMPLETE",
                "missing_factors": [],
                "factors": [
                    {
                        "name": name,
                        "raw_inputs": [
                            {
                                "name": f"test_{name.lower()}",
                                "interval": {"lower": "0.8", "upper": "0.8"},
                            }
                        ],
                        "normalized": {"lower": "0.8", "upper": "0.8"},
                        "weighted_contribution": {
                            "lower": "0.1",
                            "upper": "0.1",
                        },
                        "unknown_reason": None,
                    }
                    for name in ("A", "S", "T", "D", "E")
                ],
            },
            "oi_diagnostic": {
                "state": "UNKNOWN",
                "open_interest": None,
                "option_gamma": None,
                "unsigned_gamma_weight": None,
                "bucket_total_unsigned_gamma_weight": None,
                "concentration_share": None,
                "missing_reason": "TEST_UNKNOWN",
                "dealer_gamma_sign": "UNKNOWN",
            },
            "sampling_metadata": None,
            "legacy_v1_threshold_pass": True,
        }
    )
    facts = UnderwritingFacts(
        boundary=boundary,
        radar_scope_identity="sha256:" + "d" * 64,
        active_episode_identity=radar_bucket_episode_identity(
            runtime_identity=runtime,
            policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
            bucket_key=score_packet.bucket_key,
            leader_instrument_name=score_packet.leader_instrument_name,
            score_band=ScoreBand.HIGH,
            activation_causal_seq=1,
        ),
        anomaly_activation_seq=1,
        short_leg_identity="sha256:" + "e" * 64,
        long_leg_identity="sha256:" + "f" * 64,
        canonical_combo_identity=None,
        combo_instrument_name=None,
        option_type="call",
        short_strike_usdc_per_btc=short.strike,
        long_strike_usdc_per_btc=long.strike,
        expiry_ms=short.expiration_timestamp_ms,
        target_quantity_btc=Decimal("0.1"),
        entry_direction="SELL",
        entry_consumed_levels=(),
        atomic_state="NO_ACTIVE_COMBO",
        option_catalog_complete=True,
        combo_catalog_complete=False,
        short_leg_state="open",
        long_leg_state="open",
        short_leg_active=True,
        long_leg_active=True,
        option_amounts_aligned=True,
        combo_state=None,
        combo_active=None,
        combo_amount_aligned=None,
        platform_usable=True,
        trusted_time_lower_ms=1_000,
        trusted_time_upper_ms=1_001,
        short_leg_taker_commission_fraction=Decimal("0.0003"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        index_usdc_per_btc=Decimal("100000"),
        short_delta=Decimal("0.2"),
        short_mark_iv_fraction=Decimal("0.5"),
        quote_source=None,
        quote_refresh_witness=None,
        short_instrument_source=source,
        long_instrument_source=source,
        index_source=source,
        ticker_source=source,
        short_leg_instrument_name=short.instrument_name,
        long_leg_instrument_name=long.instrument_name,
        component_state="COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE",
        component_quote=quote,
        component_short_quote_source=source,
        component_long_quote_source=source,
        radar_score_packet=score_packet,
    )

    owner.settle_underwriting((facts,), allocate_request_id=lambda: 1)
    availability = next(
        value
        for value in state_store.objects
        if value["object_kind"] == "UNDERWRITING_AVAILABILITY_EVALUATION"
    )
    availability_payload = cast(Mapping[str, object], availability["payload"])
    assert availability_payload["availability"] == "UNKNOWN"
    assert availability_payload["unknown_reasons"] == ["COMPONENT_PRODUCT_MISMATCH"]
    assert not any(
        value["object_kind"] in {"UNDERWRITING_ACTION", "CANDIDATE_ACTIVATION"}
        for value in state_store.objects
    )

    valid_close_quote, close_reasons = evaluate_component_book_vertical(
        kind=ComponentBookQuoteKind.CLOSE,
        short_instrument=short,
        long_instrument=long,
        short_side_levels=(PriceLevel(Decimal("0.0030"), Decimal("0.1")),),
        long_side_levels=(PriceLevel(Decimal("0.0010"), Decimal("0.1")),),
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=Decimal("0.1"),
        fee_rate_index_fraction=Decimal("0.0003"),
    )
    assert valid_close_quote is not None and close_reasons == ()
    mismatched_close_quote = replace(
        valid_close_quote,
        product_spec_identity="sha256:" + "0" * 64,
    )
    from short_vol_underwriting import (
        CloseOpportunityEligibility,
        CloseQuoteState,
        evaluate_close_opportunity,
    )

    close_opportunity = evaluate_close_opportunity(
        quote_state=CloseQuoteState.COMPONENT_BOOK_CLOSE_QUOTE,
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=(),
        close_direction="BUY",
        short_leg_taker_commission_fraction=Decimal("0.0003"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        fee_rate_index_fraction=Decimal("0.0003"),
        close_index_usdc_per_btc=Decimal("100000"),
        net_entry_credit_usdc=Decimal("20"),
        expected_product=INVERSE_BTC,
        entry_product_spec_identity=INVERSE_BTC.identity,
        expected_short_leg_instrument_name=short.instrument_name,
        expected_long_leg_instrument_name=long.instrument_name,
        expected_width_usdc_per_btc=Decimal("1000"),
        component_quote=mismatched_close_quote,
    )
    assert close_opportunity.eligibility is CloseOpportunityEligibility.UNKNOWN
    assert close_opportunity.eligibility_reason == "COMPONENT_PRODUCT_MISMATCH"
    assert close_opportunity.economics is None

    forged_inverse_economics_quote = replace(
        valid_quote,
        native_gross_cashflow=valid_quote.native_gross_cashflow + Decimal("0.000001"),
    )
    forged_boundary = FactBoundary(code, runtime, 1, 3, 103, 3)
    forged_packet = replace(
        score_packet,
        fact_boundary=forged_boundary.as_object(),
    )
    forged_facts = replace(
        facts,
        boundary=forged_boundary,
        radar_scope_identity="sha256:" + "8" * 64,
        active_episode_identity=radar_bucket_episode_identity(
            runtime_identity=runtime,
            policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
            bucket_key=forged_packet.bucket_key,
            leader_instrument_name=forged_packet.leader_instrument_name,
            score_band=ScoreBand.HIGH,
            activation_causal_seq=2,
        ),
        anomaly_activation_seq=2,
        component_quote=forged_inverse_economics_quote,
        radar_score_packet=forged_packet,
    )
    owner.settle_underwriting((forged_facts,), allocate_request_id=lambda: 2)
    forged_availability = [
        value
        for value in state_store.objects
        if value["object_kind"] == "UNDERWRITING_AVAILABILITY_EVALUATION"
    ][-1]
    forged_payload = cast(Mapping[str, object], forged_availability["payload"])
    assert forged_payload["availability"] == "UNKNOWN"
    assert forged_payload["unknown_reasons"] == ["COMPONENT_PRODUCT_MISMATCH"]

    forged_inverse_close = replace(
        valid_close_quote,
        native_total_fee_reserve=(valid_close_quote.native_total_fee_reserve + Decimal("0.000001")),
    )
    forged_close_opportunity = evaluate_close_opportunity(
        quote_state=CloseQuoteState.COMPONENT_BOOK_CLOSE_QUOTE,
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=(),
        close_direction="BUY",
        short_leg_taker_commission_fraction=Decimal("0.0003"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        fee_rate_index_fraction=Decimal("0.0003"),
        close_index_usdc_per_btc=Decimal("100000"),
        net_entry_credit_usdc=Decimal("20"),
        expected_product=INVERSE_BTC,
        entry_product_spec_identity=INVERSE_BTC.identity,
        expected_short_leg_instrument_name="BTC-8AUG26-100000-C",
        expected_long_leg_instrument_name="BTC-8AUG26-101000-C",
        expected_width_usdc_per_btc=Decimal("1000"),
        component_quote=forged_inverse_close,
    )
    assert forged_close_opportunity.eligibility is CloseOpportunityEligibility.UNKNOWN
    assert forged_close_opportunity.eligibility_reason == "COMPONENT_PRODUCT_MISMATCH"

    inverse_short = short
    inverse_long = long
    inverse_close_quote, inverse_close_reasons = evaluate_component_book_vertical(
        kind=ComponentBookQuoteKind.CLOSE,
        short_instrument=inverse_short,
        long_instrument=inverse_long,
        short_side_levels=(PriceLevel(Decimal("0.0030"), Decimal("0.2")),),
        long_side_levels=(PriceLevel(Decimal("0.0010"), Decimal("0.2")),),
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=Decimal("0.1"),
        fee_rate_index_fraction=Decimal("0.0003"),
    )
    assert inverse_close_quote is not None and inverse_close_reasons == ()
    valid_inverse_close = evaluate_close_opportunity(
        quote_state=CloseQuoteState.COMPONENT_BOOK_CLOSE_QUOTE,
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=(),
        close_direction="BUY",
        short_leg_taker_commission_fraction=Decimal("0.0003"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        fee_rate_index_fraction=Decimal("0.0003"),
        close_index_usdc_per_btc=Decimal("100000"),
        net_entry_credit_usdc=Decimal("20"),
        expected_product=INVERSE_BTC,
        entry_product_spec_identity=INVERSE_BTC.identity,
        expected_short_leg_instrument_name=inverse_short.instrument_name,
        expected_long_leg_instrument_name=inverse_long.instrument_name,
        expected_width_usdc_per_btc=Decimal("1000"),
        component_quote=inverse_close_quote,
    )
    assert valid_inverse_close.eligibility is CloseOpportunityEligibility.ELIGIBLE

    wrong_quantity_quote, wrong_quantity_reasons = evaluate_component_book_vertical(
        kind=ComponentBookQuoteKind.CLOSE,
        short_instrument=inverse_short,
        long_instrument=inverse_long,
        short_side_levels=(PriceLevel(Decimal("0.0030"), Decimal("0.2")),),
        long_side_levels=(PriceLevel(Decimal("0.0010"), Decimal("0.2")),),
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=Decimal("0.2"),
        fee_rate_index_fraction=Decimal("0.0003"),
    )
    assert wrong_quantity_quote is not None and wrong_quantity_reasons == ()
    wrong_quantity_close = evaluate_close_opportunity(
        quote_state=CloseQuoteState.COMPONENT_BOOK_CLOSE_QUOTE,
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=(),
        close_direction="BUY",
        short_leg_taker_commission_fraction=Decimal("0.0003"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        fee_rate_index_fraction=Decimal("0.0003"),
        close_index_usdc_per_btc=Decimal("100000"),
        net_entry_credit_usdc=Decimal("20"),
        expected_product=INVERSE_BTC,
        entry_product_spec_identity=INVERSE_BTC.identity,
        expected_short_leg_instrument_name=inverse_short.instrument_name,
        expected_long_leg_instrument_name=inverse_long.instrument_name,
        expected_width_usdc_per_btc=Decimal("1000"),
        component_quote=wrong_quantity_quote,
    )
    assert wrong_quantity_close.eligibility is CloseOpportunityEligibility.UNKNOWN
    assert wrong_quantity_close.eligibility_reason == "COMPONENT_POSITION_MISMATCH"

    other_short = replace(
        inverse_short,
        instrument_name="BTC-8AUG26-110000-C",
        strike=Decimal("110000"),
    )
    other_long = replace(
        inverse_long,
        instrument_name="BTC-8AUG26-112000-C",
        strike=Decimal("112000"),
    )
    other_position_quote, other_position_reasons = evaluate_component_book_vertical(
        kind=ComponentBookQuoteKind.CLOSE,
        short_instrument=other_short,
        long_instrument=other_long,
        short_side_levels=(PriceLevel(Decimal("0.0030"), Decimal("0.1")),),
        long_side_levels=(PriceLevel(Decimal("0.0010"), Decimal("0.1")),),
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=Decimal("0.1"),
        fee_rate_index_fraction=Decimal("0.0003"),
    )
    assert other_position_quote is not None and other_position_reasons == ()
    other_position_close = evaluate_close_opportunity(
        quote_state=CloseQuoteState.COMPONENT_BOOK_CLOSE_QUOTE,
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=(),
        close_direction="BUY",
        short_leg_taker_commission_fraction=Decimal("0.0003"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        fee_rate_index_fraction=Decimal("0.0003"),
        close_index_usdc_per_btc=Decimal("100000"),
        net_entry_credit_usdc=Decimal("20"),
        expected_product=INVERSE_BTC,
        entry_product_spec_identity=INVERSE_BTC.identity,
        expected_short_leg_instrument_name=inverse_short.instrument_name,
        expected_long_leg_instrument_name=inverse_long.instrument_name,
        expected_width_usdc_per_btc=Decimal("1000"),
        component_quote=other_position_quote,
    )
    assert other_position_close.eligibility is CloseOpportunityEligibility.UNKNOWN
    assert other_position_close.eligibility_reason == "COMPONENT_POSITION_MISMATCH"

    inverse_quote, inverse_reasons = evaluate_component_book_vertical(
        kind=ComponentBookQuoteKind.ENTRY,
        short_instrument=inverse_short,
        long_instrument=inverse_long,
        short_side_levels=(PriceLevel(Decimal("0.0060"), Decimal("0.1")),),
        long_side_levels=(PriceLevel(Decimal("0.0020"), Decimal("0.1")),),
        index_usdc_per_btc=Decimal("100000"),
        target_quantity_btc=Decimal("0.1"),
        fee_rate_index_fraction=Decimal("0.0003"),
    )
    assert inverse_quote is not None and inverse_reasons == ()
    valid_inverse_boundary = FactBoundary(code, runtime, 1, 5, 105, 5)
    valid_inverse_packet = replace(
        score_packet,
        fact_boundary=valid_inverse_boundary.as_object(),
    )
    valid_inverse_facts = replace(
        facts,
        boundary=valid_inverse_boundary,
        radar_scope_identity="sha256:" + "1" * 64,
        active_episode_identity=radar_bucket_episode_identity(
            runtime_identity=runtime,
            policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
            bucket_key=valid_inverse_packet.bucket_key,
            leader_instrument_name=valid_inverse_packet.leader_instrument_name,
            score_band=ScoreBand.HIGH,
            activation_causal_seq=1,
        ),
        short_leg_instrument_name=inverse_short.instrument_name,
        long_leg_instrument_name=inverse_long.instrument_name,
        component_quote=inverse_quote,
        radar_score_packet=valid_inverse_packet,
    )
    assert owner._evaluate_component_underwriting(valid_inverse_facts).availability.value == (
        "EVALUABLE"
    )

    projection_mismatches = (
        replace(valid_inverse_facts, index_usdc_per_btc=Decimal("90000")),
        replace(
            valid_inverse_facts,
            component_quote=replace(
                inverse_quote,
                width_usdc_per_btc=Decimal("2000"),
                payoff_cap_usdc=Decimal("200"),
            ),
        ),
    )
    for offset, mismatched_facts in enumerate(projection_mismatches, start=6):
        mismatched_boundary = FactBoundary(
            code,
            runtime,
            1,
            offset,
            100 + offset,
            offset,
        )
        mismatched_packet = replace(
            score_packet,
            fact_boundary=mismatched_boundary.as_object(),
        )
        mismatched_facts = replace(
            mismatched_facts,
            boundary=mismatched_boundary,
            radar_scope_identity="sha256:" + str(offset) * 64,
            active_episode_identity=radar_bucket_episode_identity(
                runtime_identity=runtime,
                policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
                bucket_key=mismatched_packet.bucket_key,
                leader_instrument_name=mismatched_packet.leader_instrument_name,
                score_band=ScoreBand.HIGH,
                activation_causal_seq=offset,
            ),
            anomaly_activation_seq=offset,
            radar_score_packet=mismatched_packet,
        )
        mismatch_store = ShadowStateStore(bindings=bindings)
        mismatch_owner = FixedContractShadowOwner(
            policies=policies,
            bindings=bindings,
            state_store=mismatch_store,
        )
        mismatch_owner.settle_underwriting(
            (mismatched_facts,),
            allocate_request_id=lambda: 42,
        )
        mismatch_availability = [
            value
            for value in mismatch_store.objects
            if value["object_kind"] == "UNDERWRITING_AVAILABILITY_EVALUATION"
        ][-1]
        mismatch_payload = cast(Mapping[str, object], mismatch_availability["payload"])
        assert mismatch_payload["availability"] == "UNKNOWN"
        assert mismatch_payload["unknown_reasons"] == ["COMPONENT_FACT_PROJECTION_MISMATCH"]
        assert not any(
            value["object_kind"] in {"UNDERWRITING_ACTION", "CANDIDATE_ACTIVATION"}
            for value in mismatch_store.objects
        )

    inverse_atomic_boundary = FactBoundary(code, runtime, 1, 4, 104, 4)
    inverse_atomic_packet = replace(
        score_packet,
        fact_boundary=inverse_atomic_boundary.as_object(),
    )
    inverse_atomic_facts = replace(
        facts,
        boundary=inverse_atomic_boundary,
        radar_scope_identity="sha256:" + "9" * 64,
        active_episode_identity=radar_bucket_episode_identity(
            runtime_identity=runtime,
            policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
            bucket_key=inverse_atomic_packet.bucket_key,
            leader_instrument_name=inverse_atomic_packet.leader_instrument_name,
            score_band=ScoreBand.HIGH,
            activation_causal_seq=1,
        ),
        component_state="NOT_EVALUATED",
        component_quote=None,
        component_short_quote_source=None,
        component_long_quote_source=None,
        atomic_state="PUBLIC_ATOMIC_QUOTE_AVAILABLE",
        radar_score_packet=inverse_atomic_packet,
    )
    atomic_store = ShadowStateStore(bindings=bindings)
    atomic_owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        state_store=atomic_store,
    )
    atomic_owner.settle_underwriting((inverse_atomic_facts,), allocate_request_id=lambda: 3)
    inverse_atomic_availability = [
        value
        for value in atomic_store.objects
        if value["object_kind"] == "UNDERWRITING_AVAILABILITY_EVALUATION"
    ][-1]
    inverse_atomic_payload = cast(Mapping[str, object], inverse_atomic_availability["payload"])
    assert inverse_atomic_payload["availability"] == "UNKNOWN"
    assert inverse_atomic_payload["unknown_reasons"] == ["INVERSE_ATOMIC_ECONOMICS_UNSUPPORTED"]

    inverse_atomic_close = evaluate_close_opportunity(
        quote_state=CloseQuoteState.ATOMIC_COMBO_CLOSE_QUOTE,
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=((Decimal("0.001"), Decimal("0.1")),),
        close_direction="BUY",
        short_leg_taker_commission_fraction=Decimal("0.0003"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        fee_rate_index_fraction=Decimal("0.0003"),
        close_index_usdc_per_btc=Decimal("100000"),
        net_entry_credit_usdc=Decimal("20"),
        expected_product=INVERSE_BTC,
        entry_product_spec_identity=INVERSE_BTC.identity,
        expected_short_leg_instrument_name=None,
        expected_long_leg_instrument_name=None,
        expected_width_usdc_per_btc=None,
    )
    assert inverse_atomic_close.eligibility is CloseOpportunityEligibility.UNKNOWN
    assert inverse_atomic_close.eligibility_reason == "INVERSE_ATOMIC_ECONOMICS_UNSUPPORTED"
    assert inverse_atomic_close.economics is None


def test_inverse_radar_converts_native_btc_premium_to_black_model_price() -> None:
    import math
    from dataclasses import replace
    from types import SimpleNamespace

    from conftest import encode_policy, policy_document
    from market_monitor import ContinuousOrderBook, TimeInterval
    from options_domain import AmountMetadata, OptionInstrument, OptionType, PriceTickMetadata
    from short_vol_radar.black import black_price
    from short_vol_radar.detector import DetectorState
    from short_vol_radar.policy import load_policy_bytes
    from short_vol_radar.radar import TickerState, calculate_current_evaluation
    from short_vol_radar.review import build_review_contexts

    document = policy_document(activation_count=1, clear_count=1, separation_ms=0)
    exact, digest = encode_policy(document)
    policy = load_policy_bytes(exact, digest)
    forward = Decimal("100000")
    strike = Decimal("100010")
    expiry = 60 * 60 * 1000
    total_volatility = 0.5 * math.sqrt(60 / (365 * 24 * 60))
    model_price = Decimal(
        str(black_price(float(forward), float(strike), total_volatility, OptionType.CALL))
    )
    native_price = model_price / forward
    instrument = OptionInstrument(
        instrument_name="BTC-8AUG26-100010-C",
        expiration_timestamp_ms=expiry,
        strike=strike,
        option_type=OptionType.CALL,
        amount=AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
        price_tick=PriceTickMetadata(Decimal("0.0000000001")),
        product=INVERSE_BTC,
    )
    book = ContinuousOrderBook(instrument.instrument_name)
    book.apply(
        {
            "type": "snapshot",
            "timestamp": 1,
            "instrument_name": instrument.instrument_name,
            "change_id": 1,
            "bids": [["new", native_price, "0.1"]],
            "asks": [["new", native_price + Decimal("0.0000000002"), "0.1"]],
        },
        1,
    )
    current = calculate_current_evaluation(
        policy=policy,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=book,
        ticker=TickerState(forward, "BTC-8AUG26", 1),
        causal_closes=(forward,) * 6,
    )
    assert current.calculation is not None
    calculation = current.calculation
    assert calculation.product_spec_identity == INVERSE_BTC.identity
    assert calculation.native_executable_sell_price == native_price
    assert calculation.executable_sell_price_usdc == native_price * forward
    assert calculation.model_conversion_forward == forward
    midpoint = (calculation.total_volatility.lower + calculation.total_volatility.upper) / 2
    assert abs(midpoint - Decimal(str(total_volatility))) < Decimal("1e-15")

    mismatched_policy = replace(
        policy,
        product_spec_identity="sha256:" + "0" * 64,
    )
    mismatch = calculate_current_evaluation(
        policy=mismatched_policy,
        instrument=instrument,
        trusted_time=TimeInterval(0, 0),
        causal_seq=1,
        option_book=book,
        ticker=TickerState(forward, "BTC-8AUG26", 1),
        causal_closes=(forward,) * 6,
    )
    assert mismatch.reason == "PRODUCT_POLICY_MISMATCH"
    assert mismatch.known_evaluation is False
    assert mismatch.calculation is None

    long_instrument = OptionInstrument(
        instrument_name="BTC-8AUG26-100020-C",
        expiration_timestamp_ms=expiry,
        strike=Decimal("100020"),
        option_type=OptionType.CALL,
        amount=AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
        price_tick=PriceTickMetadata(Decimal("0.0000000001")),
        product=INVERSE_BTC,
    )
    long_book = ContinuousOrderBook(long_instrument.instrument_name)
    long_book.apply(
        {
            "type": "snapshot",
            "timestamp": 1,
            "instrument_name": long_instrument.instrument_name,
            "change_id": 1,
            "bids": [["new", native_price / 3, "0.1"]],
            "asks": [["new", native_price / 2, "0.1"]],
        },
        1,
    )
    review_contexts = build_review_contexts(
        options={
            instrument.instrument_name: instrument,
            long_instrument.instrument_name: long_instrument,
        },
        calculations={instrument.instrument_name: calculation},
        detector_states={instrument.instrument_name: DetectorState.ANOMALY_ACTIVE},
        detector_reasons={instrument.instrument_name: "RICHNESS_ACTIVATED"},
        tickers={
            instrument.instrument_name: TickerState(
                forward,
                "BTC-8AUG26",
                1,
                signed_delta=Decimal("0.2"),
                mark_iv_fraction=Decimal("0.5"),
            ),
            long_instrument.instrument_name: TickerState(
                forward,
                "BTC-8AUG26",
                1,
                signed_delta=Decimal("0.1"),
                mark_iv_fraction=Decimal("0.4"),
            ),
        },
        option_books={
            instrument.instrument_name: book,
            long_instrument.instrument_name: long_book,
        },
        option_catalog_complete=True,
        index_usdc_per_btc=forward,
        target_quantity_btc=Decimal("0.1"),
        fee_rate_index_fraction=Decimal("0.0003"),
        score_model=policy.score_model,
    )
    from radar_runtime.runtime import CausalCommit, RadarReducer
    from radar_runtime.workbench import _radar_rows

    reducer = SimpleNamespace(
        options={
            instrument.instrument_name: instrument,
            long_instrument.instrument_name: long_instrument,
        },
        results={
            instrument.instrument_name: SimpleNamespace(
                calculation=calculation,
                detector_state=DetectorState.ANOMALY_ACTIVE,
                reason="RICHNESS_ACTIVATED",
                known_evaluation=True,
                band_id=calculation.band.band_id,
            )
        },
        trackers={},
        score_bucket_keys={},
        bucket_leader_by_key={},
        bucket_trackers={},
        bucket_leader_coverage={},
        option_books={
            instrument.instrument_name: book,
            long_instrument.instrument_name: long_book,
        },
    )
    radar_rows = _radar_rows(
        cast(RadarReducer, reducer),
        cast(CausalCommit, SimpleNamespace(boundary=SimpleNamespace(received_monotonic_ms=1))),
        TimeInterval(0, 0),
        review_contexts,
    )
    serialized_radar = json.dumps(radar_rows, sort_keys=True).lower()
    assert "_usdc" not in serialized_radar
    inverse_row = next(
        row for row in radar_rows if row["instrument_name"] == instrument.instrument_name
    )
    legged_context = cast(Mapping[str, object], inverse_row["legged_structure_context"])
    legged_references = cast(list[object], legged_context["references"])
    legged_reference = cast(Mapping[str, object], legged_references[0])
    assert legged_reference["native_premium_currency"] == "BTC"
    assert legged_reference["stressed_gross_credit_native"] is not None
    assert legged_reference["stressed_gross_credit_valuation"] is not None
    rank_inputs = cast(Mapping[str, object], inverse_row["rank_inputs"])
    assert rank_inputs["strike_price"] == str(strike)


def test_inverse_platform_readiness_tracks_only_btc_usd_lock() -> None:
    from market_monitor.deribit import PlatformReadiness

    readiness = PlatformReadiness(price_index="btc_usd")
    readiness.apply_status({"locked": "partial", "locked_indices": ["eth_usd"]})
    assert readiness.lock_snapshot is False
    readiness = PlatformReadiness(price_index="btc_usd")
    readiness.apply_status({"locked": "partial", "locked_indices": ["btc_usd"]})
    assert readiness.lock_snapshot is True


def test_radar_policy_v9_binds_inverse_product_identity() -> None:
    from conftest import encode_policy, policy_document
    from short_vol_radar.policy import load_policy_bytes

    document = policy_document()
    exact, digest = encode_policy(document)

    policy = load_policy_bytes(exact, digest)

    assert policy.schema_version == 9
    assert policy.product_spec_identity == INVERSE_BTC.identity


def test_radar_policy_rejects_removed_schema_v6() -> None:
    from conftest import encode_policy, policy_document
    from short_vol_radar.policy import PolicyError, load_policy_bytes

    document = policy_document()
    document["policy_schema_version"] = 6
    document.pop("product_spec_identity")
    exact, digest = encode_policy(document)

    with pytest.raises(PolicyError, match="policy_schema_version must be exactly 9"):
        load_policy_bytes(exact, digest)


def test_inverse_policy_chain_is_exact_and_product_bound(repository_root: Path) -> None:
    from radar_runtime.product_config import INVERSE_BTC_PROFILE
    from short_vol_underwriting.policy import load_policy_chain

    profile = INVERSE_BTC_PROFILE
    chain = load_policy_chain(
        radar_path=repository_root / "policies" / profile.radar_policy_filename,
        underwriting_path=repository_root / "policies" / profile.underwriting_policy_filename,
        position_path=repository_root / "policies" / profile.position_policy_filename,
        radar_identity=profile.radar_policy_identity,
        underwriting_identity=profile.underwriting_policy_identity,
        position_identity=profile.position_policy_identity,
    )

    assert chain.radar.product_spec_identity == INVERSE_BTC.identity
    assert chain.identities == (
        profile.radar_policy_identity,
        profile.underwriting_policy_identity,
        profile.position_policy_identity,
    )


def test_inverse_persistent_startup_builds_one_product_graph(
    tmp_path: Path,
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import radar_runtime.service as service_module
    from radar_runtime.service import (
        build_persistent_service_composition,
        prepare_persistent_service_startup,
    )

    monkeypatch.setattr(service_module, "_temporary_state_roots", lambda: ())
    startup = prepare_persistent_service_startup(
        state_root=(tmp_path / "inverse-state").resolve(),
        process_cwd=repository_root,
        workbench_host="127.0.0.1",
        workbench_port=0,
        product=OptionProductName.INVERSE_BTC,
        code_identity="a" * 40,
        startup_monotonic_ms=100,
        process_id=123,
        nonce_factory=lambda: "inverse",
    )
    composition = build_persistent_service_composition(startup)
    try:
        assert startup.product is INVERSE_BTC
        assert startup.policies.radar.product_spec_identity == INVERSE_BTC.identity
        assert composition.runtime.reducer.product is INVERSE_BTC
        assert composition.runtime.reducer.platform.price_index == "btc_usd"
    finally:
        composition.workbench.close()


def test_inverse_reducer_keeps_selected_index_across_session_bootstrap() -> None:
    from conftest import encode_policy, policy_document
    from radar_runtime.runtime import RadarReducer
    from short_vol_radar.evidence import RadarEventSink
    from short_vol_radar.policy import load_policy_bytes

    document = policy_document()
    exact, digest = encode_policy(document)
    policy = load_policy_bytes(exact, digest)
    reducer = RadarReducer(
        policy=policy,
        code_identity="a" * 40,
        event_sink=RadarEventSink(
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=policy.identity,
        ),
        runtime_identity="runtime",
        product=INVERSE_BTC,
    )

    reducer.begin_session(session_epoch=1, monotonic_ms=100)

    assert reducer.platform.price_index == "btc_usd"
    assert reducer.option_lifecycle_channel == "instrument.state.option.BTC"
    assert reducer.combo_lifecycle_channel == "instrument.state.option_combo.BTC"
    assert reducer.index_channel == "deribit_price_index.btc_usd"


def test_inverse_workbench_identifies_native_and_valuation_units(
    tmp_path: Path,
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import radar_runtime.service as service_module
    from radar_runtime.service import (
        build_persistent_service_composition,
        prepare_persistent_service_startup,
    )
    from radar_runtime.workbench import (
        _outcome_rows,
        _position_rows,
        _shadow_rows,
        _underwriting_rows,
    )

    monkeypatch.setattr(service_module, "_temporary_state_roots", lambda: ())
    startup = prepare_persistent_service_startup(
        state_root=(tmp_path / "inverse-workbench-state").resolve(),
        process_cwd=repository_root,
        workbench_host="127.0.0.1",
        workbench_port=0,
        product="inverse-btc",
        code_identity="a" * 40,
        startup_monotonic_ms=100,
        process_id=123,
        nonce_factory=lambda: "inverse-workbench",
    )
    composition = build_persistent_service_composition(startup)
    try:
        document = json.loads(composition.snapshot_store.read().workbench_body)
        assert document["schema_version"] == 7
        assert document["channel_id"] == "INVERSE_BTC_SHORT_VOL_V2"
        assert document["product"] == {
            "product_spec_identity": INVERSE_BTC.identity,
            "name": "inverse-btc",
            "market_family": "DERIBIT_BTC_OPTIONS",
            "economic_semantics_version": "INVERSE_BTC_V1",
            "case_schema_version": 5,
            "public_currency": "BTC",
            "base_currency": "BTC",
            "quote_currency": "BTC",
            "settlement_currency": "BTC",
            "counter_currency": "USD",
            "price_index": "btc_usd",
            "instrument_type": "reversed",
            "native_premium_currency": "BTC",
            "valuation_currency": "USD_EQUIVALENT",
            "strike_currency": "USD",
            "model_premium_rule": "NATIVE_BTC_PREMIUM_TIMES_FORWARD",
            "valuation_rule": "NATIVE_BTC_AMOUNT_TIMES_CAUSAL_BTC_USD_INDEX",
            "fee_rule": "MIN_BASE_RATE_OR_12_5_PERCENT_NATIVE_PREMIUM_IN_BTC",
            "native_settlement_payoff_rule": ("USD_STRIKE_PAYOFF_DIVIDED_BY_EXPIRY_DELIVERY_PRICE"),
            "native_settlement_liability_profile": (
                "SETTLEMENT_PRICE_DEPENDENT_RECIPROCAL_BTC_LIABILITY"
            ),
            "actual_account_margin_requirement": None,
            "actual_account_margin_availability": "UNKNOWN",
            "actual_account_margin_reason": "ACCOUNT_MARGIN_UNKNOWN",
        }
        assert document["system"]["index_history"]["source"].endswith("BTC_USD_2D")
        assert "_usdc" not in json.dumps(document, sort_keys=True).lower()

        availability_identity = "sha256:" + "1" * 64
        candidate_identity = "sha256:" + "2" * 64
        entry_identity = "sha256:" + "3" * 64
        observation_identity = "sha256:" + "4" * 64
        fact_boundary = {
            "code_identity": "a" * 40,
            "runtime_identity": "sha256:" + "b" * 64,
            "session_epoch": 1,
            "ingress_seq": 1,
            "received_monotonic_ms": 100,
            "causal_seq": 1,
        }
        kinds: dict[str, list[dict[str, object]]] = {
            "UNDERWRITING_AVAILABILITY_EVALUATION": [
                {
                    "object_identity": availability_identity,
                    "fact_boundary": fact_boundary,
                    "payload": {
                        "radar_scope_or_short_leg_identity": "inverse-scope",
                        "availability": "EVALUABLE",
                        "unknown_reasons": [],
                        "component_state": "COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE",
                    },
                }
            ],
            "UNDERWRITING_ACTION": [
                {
                    "object_identity": "sha256:" + "5" * 64,
                    "fact_boundary": fact_boundary,
                    "payload": {
                        "underwriting_availability_evaluation_identity": (availability_identity),
                        "economic_action": "CANDIDATE",
                        "product_spec_identity": INVERSE_BTC.identity,
                        "product_name": INVERSE_BTC.name.value,
                        "native_premium_currency": "BTC",
                        "valuation_currency": "USD_EQUIVALENT",
                        "gross_entry_credit_usdc": "34",
                        "entry_fee_reserve_usdc": "5.625",
                        "net_entry_credit_usdc": "28.375",
                        "contractual_payoff_max_loss_ex_fees_usdc": "66",
                        "future_cost_reserve_usdc": "12",
                        "underwriting_reserved_loss_usdc": "83.625",
                    },
                }
            ],
            "CANDIDATE_ACTIVATION": [
                {
                    "object_identity": candidate_identity,
                    "payload": {
                        "underwriting_action_identity": "sha256:" + "5" * 64,
                    },
                }
            ],
            "SHADOW_ENTRY": [
                {
                    "object_identity": entry_identity,
                    "runtime_identity": "sha256:" + "b" * 64,
                    "payload": {
                        "candidate_identity": candidate_identity,
                        "radar_scope_identity": "inverse-scope",
                        "full_quantity_btc": "0.1",
                        "gross_entry_credit_usdc": "34",
                        "native_premium_currency": "BTC",
                        "native_gross_entry_credit": "0.00034",
                        "native_entry_fee_reserve": "0.00005625",
                        "native_net_entry_credit": "0.00028375",
                        "entry_valuation_index_price": "100000",
                        "entry_component_legs": [
                            {
                                "canonical_leg_role": "SHORT",
                                "instrument_name": "BTC-8AUG26-100000-C",
                                "action": "SELL",
                                "native_premium_currency": "BTC",
                                "stressed_vwap_usdc_per_btc": "550",
                                "stressed_vwap_native": "0.0055",
                                "fee_reserve_usdc": "3",
                            },
                            {
                                "canonical_leg_role": "LONG",
                                "instrument_name": "BTC-8AUG26-101000-C",
                                "action": "BUY",
                                "native_premium_currency": "BTC",
                                "stressed_vwap_usdc_per_btc": "210",
                                "stressed_vwap_native": "0.0021",
                                "fee_reserve_usdc": "2.625",
                            },
                        ],
                        "canonical_leg_identities": [],
                        "origin_runtime_identity": "sha256:" + "b" * 64,
                        "current_segment_identity": "sha256:" + "8" * 64,
                        "current_segment_sequence": 0,
                        "observation_quality": "CONTINUOUS",
                        "gap_count": 0,
                        "qualification_eligible": True,
                        "tracking_state": "ACTIVE",
                        "post_close_attempt_state": "NOT_SCHEDULED",
                    },
                }
            ],
            "CLOSE_OPPORTUNITY_EVALUATION": [
                {
                    "object_identity": "sha256:" + "6" * 64,
                    "fact_boundary": fact_boundary,
                    "payload": {
                        "shadow_entry_identity": entry_identity,
                        "gross_close_cashflow_usdc": "-10",
                        "net_close_debit_usdc": "12",
                        "projected_shadow_net_pnl_usdc": "16.375",
                        "native_premium_currency": "BTC",
                        "native_net_close_cashflow": "-0.00012",
                        "native_projected_shadow_net_pnl": "0.00016375",
                    },
                }
            ],
            "SHADOW_OUTCOME_OBSERVATION": [
                {
                    "object_identity": observation_identity,
                    "payload": {"shadow_entry_identity": entry_identity},
                }
            ],
            "SHADOW_OUTCOME": [
                {
                    "object_identity": "sha256:" + "7" * 64,
                    "payload": {
                        "shadow_observation_identity": observation_identity,
                        "terminal_state": "MATURE_KNOWN",
                        "net_pnl_after_public_standard_fee_reserve_usdc": "16.375",
                        "native_premium_currency": "BTC",
                        "native_net_pnl": "0.00016375",
                        "actual_pnl_usdc": None,
                    },
                }
            ],
        }
        populated_projection = {
            "underwriting": _underwriting_rows(kinds, startup.policies),
            "shadow": _shadow_rows(kinds, startup.policies),
            "positions": _position_rows(
                kinds,
                startup.policies,
                trusted_time=None,
                option_metadata=(),
            ),
            "outcomes": _outcome_rows(kinds),
        }
        serialized_projection = json.dumps(populated_projection, sort_keys=True).lower()
        assert "_usdc" not in serialized_projection
        assert populated_projection["underwriting"][0]["net_entry_credit_valuation"] == "28.375"
        assert populated_projection["shadow"][0]["simulated_entry_price_valuation_per_btc"] == "340"
        assert populated_projection["positions"][0]["projected_shadow_pnl_valuation"] == "16.375"
        assert populated_projection["outcomes"][0]["public_quote_net_pnl_valuation"] == "16.375"
    finally:
        composition.workbench.close()


def test_inverse_shadow_case_v5_conserves_native_and_boundary_valued_outcome(
    tmp_path: Path,
    repository_root: Path,
) -> None:

    from short_vol_underwriting import (
        UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY,
        FixedContractShadowOwner,
        RuntimeBindings,
        ShadowCaseReadStatus,
        ShadowCaseStore,
        ShadowCaseStoreError,
        ShadowStateStore,
        canonical_identity,
        load_policy_chain,
    )
    from short_vol_underwriting.constants import (
        INVERSE_BTC_POSITION_POLICY_IDENTITY,
        INVERSE_BTC_RADAR_POLICY_IDENTITY,
        INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
    )
    from short_vol_underwriting.model import FactBoundary

    code = "a" * 40
    runtime = "sha256:" + "b" * 64

    def boundary(causal_seq: int) -> FactBoundary:
        return FactBoundary(
            code_identity=code,
            runtime_identity=runtime,
            session_epoch=1,
            ingress_seq=causal_seq,
            received_monotonic_ms=100 + causal_seq,
            causal_seq=causal_seq,
        )

    policies = load_policy_chain(
        radar_path=repository_root / "policies/short-vol-inverse-btc-public-shadow-radar.json",
        underwriting_path=(
            repository_root / "policies/short-vol-inverse-btc-public-shadow-underwriting.json"
        ),
        position_path=(
            repository_root / "policies/short-vol-inverse-btc-public-shadow-position.json"
        ),
        radar_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )
    bindings = RuntimeBindings(
        code_identity=code,
        runtime_identity=runtime,
        radar_policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_policy_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_policy_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )
    cases = Path(tmp_path) / "cases"
    cases.mkdir()
    case_store = ShadowCaseStore(cases, bindings=bindings, policies=policies)
    state = ShadowStateStore(bindings=bindings, observer=case_store)

    margin_vector = [
        {
            "predicate": predicate,
            "signed_margin": margin,
            "unit": unit,
            "passes": True,
        }
        for predicate, margin, unit in (
            ("POSITIVE_NET_ENTRY_CREDIT", "28.375", "USD_EQUIVALENT"),
            ("CREDIT_ABOVE_FUTURE_COST_RESERVE", "16.375", "USD_EQUIVALENT"),
            ("UNDERWRITING_RESERVED_LOSS_WITHIN_LIMIT", "166.375", "USD_EQUIVALENT"),
            ("MINIMUM_NET_ENTRY_CREDIT", "13.375", "USD_EQUIVALENT"),
            ("MINIMUM_NET_CREDIT_TO_PAYOFF_CAP", "0.18375", "FRACTION"),
            ("ENTRY_CONSUMED_LEVEL_LIMIT", 9998, "LEVEL_COUNT"),
        )
    ]
    availability_identity = canonical_identity("Availability", "inverse")
    action_identity = canonical_identity("UnderwritingActionIdentity", "inverse")
    candidate_identity = canonical_identity("CandidateActivationIdentity", "inverse")
    state.record(
        object_kind="UNDERWRITING_AVAILABILITY_EVALUATION",
        object_identity=availability_identity,
        fact_boundary=boundary(1),
        payload={
            "underwriting_availability_evaluation_identity": availability_identity,
            "radar_scope_or_short_leg_identity": canonical_identity("RadarScope", "inverse"),
            "consumed_availability_fact_fingerprint": canonical_identity(
                "AvailabilityFingerprint", "inverse"
            ),
            "availability": "EVALUABLE",
            "availability_evaluation_fact_boundary": boundary(1).as_object(),
            "unknown_reasons": [],
        },
    )
    state.record(
        object_kind="UNDERWRITING_ACTION",
        object_identity=action_identity,
        fact_boundary=boundary(2),
        payload={
            "underwriting_action_identity": action_identity,
            "underwriting_availability_evaluation_identity": availability_identity,
            "underwriting_opportunity_key_identity": canonical_identity("Opportunity", "inverse"),
            "consumed_economic_fact_fingerprint": canonical_identity("Economics", "inverse"),
            "economic_action": "CANDIDATE",
            "failed_predicates": [],
            "predicate_margin_vector": margin_vector,
            "evaluation_fact_boundary": boundary(2).as_object(),
        },
    )
    state.record(
        object_kind="CANDIDATE_ACTIVATION",
        object_identity=candidate_identity,
        fact_boundary=boundary(3),
        payload={
            "candidate_identity": candidate_identity,
            "underwriting_action_identity": action_identity,
            "underwriting_position_slot_key_identity": canonical_identity("Slot", "inverse"),
            "candidate_activation_fact_boundary": boundary(3).as_object(),
        },
    )

    short_name = "BTC-8AUG26-100000-C"
    long_name = "BTC-8AUG26-101000-C"
    leg_identities = (
        canonical_identity("Leg", "inverse-short"),
        canonical_identity("Leg", "inverse-long"),
    )
    origin = boundary(2)
    sent = boundary(3)
    opened_boundary = boundary(4)
    source_refs: list[dict[str, object]] = []
    for index, role in enumerate(("SHORT", "LONG")):
        request_id = 201 + index
        name = (short_name, long_name)[index]
        source_identity = canonical_identity(
            "RpcComponentLegRefreshSourceIdentity",
            runtime,
            request_id,
            role,
            "public/get_order_book",
            leg_identities[index],
            {"instrument_name": name, "depth": 10000},
            origin.as_object(),
            sent.as_object(),
            1,
            11,
            1_000,
            opened_boundary.as_object(),
        )
        source_refs.append(
            {
                "canonical_leg_role": role,
                "source_identity": source_identity,
                "receipt_fact_boundary": opened_boundary.as_object(),
                "source_timestamp_ms": 1_000,
                "global_continuity_epoch": 1,
                "request_id": request_id,
                "owner_origin_boundary": origin.as_object(),
                "sent_boundary": sent.as_object(),
                "change_id": 11,
            }
        )
    pair_identity = canonical_identity(
        "ComponentBookPairWitnessIdentity",
        source_refs[0]["source_identity"],
        source_refs[1]["source_identity"],
        opened_boundary.as_object(),
    )

    def component_leg(
        *,
        role: str,
        name: str,
        action: str,
        raw_native: str,
        stressed_native: str,
        index_price: str,
        native_fee: str,
    ) -> dict[str, object]:
        raw_valuation = Decimal(raw_native) * Decimal(index_price)
        stressed_valuation = Decimal(stressed_native) * Decimal(index_price)
        valuation_fee = Decimal(native_fee) * Decimal(index_price)
        return {
            "canonical_leg_role": role,
            "instrument_name": name,
            "action": action,
            "native_premium_currency": "BTC",
            "valuation_index_price": index_price,
            "raw_consumed_levels_native": [{"price_native": raw_native, "amount_btc": "0.1"}],
            "raw_vwap_native": raw_native,
            "stressed_consumed_levels_native": [
                {"price_native": stressed_native, "amount_btc": "0.1"}
            ],
            "stressed_vwap_native": stressed_native,
            "native_fee_reserve": native_fee,
            "raw_consumed_levels": [
                {"price_usdc_per_btc": str(raw_valuation), "amount_btc": "0.1"}
            ],
            "raw_vwap_usdc_per_btc": str(raw_valuation),
            "stressed_consumed_levels": [
                {
                    "price_usdc_per_btc": str(stressed_valuation),
                    "amount_btc": "0.1",
                }
            ],
            "stressed_vwap_usdc_per_btc": str(stressed_valuation),
            "fee_reserve_usdc": str(valuation_fee),
        }

    entry_identity = canonical_identity("ShadowEntryIdentity", "inverse")
    entry_fingerprint = canonical_identity("EntryEconomicFingerprint", "inverse")
    entry_action_identity = canonical_identity(
        "CaseOpenRefreshedUnderwritingActionIdentity",
        candidate_identity,
        entry_fingerprint,
        "CANDIDATE",
        UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY,
        1,
        opened_boundary.as_object(),
    )
    from options_domain import OptionType
    from short_vol_radar import RadarScorePacket, ScoreBand, radar_bucket_episode_identity
    from short_vol_radar.black import DecimalInterval
    from short_vol_radar.score import (
        LeaderCoverage,
        RadarBucketKey,
        RadarSamplingMetadata,
        RadarScoreInputs,
        SamplingKind,
        build_radar_score_packet,
        compute_radar_score,
        compute_unsigned_oi_concentration,
    )
    from short_vol_underwriting.control import selected_decision_batch_identity

    activation_causal_seq = 3
    sampling_metadata = RadarSamplingMetadata(
        kind=SamplingKind.CANONICAL_HIGH,
        causal_batch_identity=selected_decision_batch_identity(
            bindings=bindings,
            activation_causal_seq=activation_causal_seq,
        ),
        designation_identity=candidate_identity,
    )

    def score_packet(packet_boundary: FactBoundary) -> RadarScorePacket:
        point_zero = DecimalInterval(Decimal(0), Decimal(0))
        point_one = DecimalInterval(Decimal(1), Decimal(1))
        stressed_richness = DecimalInterval(Decimal("1.3"), Decimal("1.3"))
        inputs = RadarScoreInputs(
            stressed_richness=stressed_richness,
            stressed_executable_bid_iv=DecimalInterval(Decimal("0.3"), Decimal("0.3")),
            local_same_type_mark_iv=Decimal("0.3"),
            surface_source_skew_ms=0,
            current_expiry_atm_mark_iv=Decimal("0.3"),
            adjacent_expiry_atm_mark_iv=Decimal("0.3"),
            term_source_skew_ms=0,
            adverse_semivariance_share=point_zero,
            jump_share=point_zero,
            target_spread_ticks=point_one,
            bid_consumed_level_count=1,
            ask_consumed_level_count=1,
        )
        return build_radar_score_packet(
            policy_identity=policies.radar.identity,
            fact_boundary=packet_boundary.as_object(),
            bucket_key=RadarBucketKey(
                tte_band_id="six-to-twenty-four-hours",
                expiry_ms=1_786_150_800_000,
                option_type=OptionType.CALL,
                delta_bucket="0.15-0.25",
            ),
            leader_instrument_name=short_name,
            result=compute_radar_score(policies.radar.score_model, inputs),
            oi_diagnostic=compute_unsigned_oi_concentration(
                open_interest=None,
                option_gamma=None,
                bucket_total_unsigned_gamma_weight=None,
            ),
            stressed_richness=stressed_richness,
            leader_coverage=LeaderCoverage.COMPLETE,
            sampling_metadata=sampling_metadata,
        )

    selection_packet = score_packet(boundary(activation_causal_seq))
    refresh_packet = score_packet(opened_boundary)
    active_episode_identity = radar_bucket_episode_identity(
        runtime_identity=runtime,
        policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        bucket_key=selection_packet.bucket_key,
        leader_instrument_name=selection_packet.leader_instrument_name,
        score_band=ScoreBand.HIGH,
        activation_causal_seq=activation_causal_seq,
    )
    state.record(
        object_kind="SHADOW_ENTRY",
        object_identity=entry_identity,
        fact_boundary=opened_boundary,
        payload={
            "shadow_entry_identity": entry_identity,
            "enrollment_kind": "ADMITTED_SHADOW_TRADE",
            "candidate_identity": candidate_identity,
            "entry_underwriting_action_identity": entry_action_identity,
            "entry_underwriting_economic_action": "CANDIDATE",
            "entry_underwriting_consumed_economic_fact_fingerprint": entry_fingerprint,
            "entry_underwriting_failed_predicates": [],
            "entry_underwriting_predicate_margin_vector": margin_vector,
            "entry_underwriting_protective_leg_selection_rule_identity": (
                UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY
            ),
            "entry_underwriting_candidate_protective_leg_count": 1,
            "entry_underwriting_decision_fact_boundary": opened_boundary.as_object(),
            "selection_score_packet": selection_packet.as_object(),
            "entry_refresh_score_packet": refresh_packet.as_object(),
            "active_episode_identity": active_episode_identity,
            "radar_research_review_identity": None,
            "radar_activation_causal_seq": activation_causal_seq,
            "radar_scope_identity": canonical_identity("RadarScope", "inverse"),
            "execution_model": "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL",
            "product_spec_identity": INVERSE_BTC.identity,
            "product_name": INVERSE_BTC.name.value,
            "native_premium_currency": "BTC",
            "settlement_currency": "BTC",
            "valuation_currency": "USD_EQUIVALENT",
            "price_index": "btc_usd",
            "component_state": "COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE",
            "atomic_state_diagnostic": "NO_ACTIVE_COMBO",
            "canonical_leg_identities": list(leg_identities),
            "short_leg_instrument_name": short_name,
            "long_leg_instrument_name": long_name,
            "expiry_ms": 1_786_150_800_000,
            "option_type": "call",
            "short_strike_usdc_per_btc": "100000",
            "long_strike_usdc_per_btc": "101000",
            "entry_direction": "SELL",
            "full_quantity_btc": "0.1",
            "entry_component_pair_identity": pair_identity,
            "entry_component_pair_timing": {
                "session_epochs": [1, 1],
                "global_continuity_epochs": [1, 1],
                "source_timestamp_skew_ms": 0,
                "receive_skew_ms": 0,
            },
            "entry_component_pair_limits": {
                "maximum_source_skew_ms": 6000,
                "maximum_receive_skew_ms": 4000,
            },
            "entry_component_quote_source_refs": source_refs,
            "entry_component_legs": [
                component_leg(
                    role="SHORT",
                    name=short_name,
                    action="SELL",
                    raw_native="0.0060",
                    stressed_native="0.0055",
                    index_price="100000",
                    native_fee="0.000030",
                ),
                component_leg(
                    role="LONG",
                    name=long_name,
                    action="BUY",
                    raw_native="0.0020",
                    stressed_native="0.0021",
                    index_price="100000",
                    native_fee="0.00002625",
                ),
            ],
            "native_gross_entry_credit": "0.00034",
            "native_entry_fee_reserve": "0.00005625",
            "native_net_entry_credit": "0.00028375",
            "entry_index_usdc_per_btc": "100000",
            "entry_index_source_ref": {
                "source_identity": canonical_identity("IndexSource", "inverse-entry"),
                "receipt_fact_boundary": opened_boundary.as_object(),
            },
            "entry_short_leg_mark_iv_fraction": "0.5",
            "entry_short_leg_mark_iv_source_ref": {
                "source_identity": canonical_identity("TickerSource", "inverse-entry"),
                "receipt_fact_boundary": opened_boundary.as_object(),
            },
            "entry_valuation_index_price": "100000",
            "gross_entry_credit_usdc": "34",
            "entry_fee_reserve_usdc": "5.625",
            "net_entry_credit_usdc": "28.375",
            "width_usdc_per_btc": "1000",
            "payoff_cap_usdc": "100",
            "contractual_payoff_max_loss_ex_fees_usdc": "66",
            "entry_fee_reserved_payoff_loss_usdc": "71.625",
            "future_cost_reserve_usdc": "12",
            "underwriting_reserved_loss_usdc": "83.625",
            "non_claims": [
                "NOT_AN_ORDER",
                "NOT_A_FILL",
                "NOT_AN_ATOMIC_QUOTE",
                "NO_LIQUIDITY_RESERVATION",
                "ATOMIC_EXECUTABILITY_UNPROVEN",
            ],
        },
    )
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None

    recovery_cases = tmp_path / "recovery-cases"
    shutil.copytree(cases, recovery_cases)
    recovery_bindings = RuntimeBindings(
        code_identity=code,
        runtime_identity="sha256:" + "c" * 64,
        radar_policy_identity=bindings.radar_policy_identity,
        underwriting_policy_identity=bindings.underwriting_policy_identity,
        position_policy_identity=bindings.position_policy_identity,
    )
    recovery_store = ShadowCaseStore(
        recovery_cases,
        bindings=recovery_bindings,
        policies=policies,
    )
    (scanned_entry,) = recovery_store.scan_active_admitted()
    assert scanned_entry.required_option_instrument_names == (short_name, long_name)
    assert scanned_entry.entry_terms.target_quantity_btc == Decimal("0.1")
    assert scanned_entry.entry_payload["entry_fact_boundary"] == opened_boundary.as_object()
    scanned_sources = cast(
        tuple[Mapping[str, object], ...],
        scanned_entry.entry_payload["entry_component_quote_source_refs"],
    )
    assert [source["source_timestamp_ms"] for source in scanned_sources] == [1_000, 1_000]

    recovery_state = ShadowStateStore(bindings=recovery_bindings)
    recovery_owner = FixedContractShadowOwner(
        policies=policies,
        bindings=recovery_bindings,
        state_store=recovery_state,
    )
    startup_boundary = FactBoundary(
        code_identity=code,
        runtime_identity=recovery_bindings.runtime_identity,
        session_epoch=0,
        ingress_seq=0,
        received_monotonic_ms=90,
        causal_seq=0,
    )
    staged = recovery_owner.stage_recovered_entries(
        (scanned_entry,),
        recovery_projection_boundary=startup_boundary,
    )
    adoption_boundary = FactBoundary(
        code_identity=code,
        runtime_identity=recovery_bindings.runtime_identity,
        session_epoch=1,
        ingress_seq=1,
        received_monotonic_ms=100,
        causal_seq=1,
    )
    adopted = recovery_store.open_recovery_segment(
        case_id,
        adoption_fact_boundary=adoption_boundary,
    )
    assert staged[0].shadow_entry_identity == adopted.shadow_entry_identity
    recovery_owner.activate_recovered_entries((adopted,))
    restored = recovery_state.get_object("SHADOW_ENTRY", entry_identity)
    assert restored is not None
    restored_payload = cast(Mapping[str, object], restored["payload"])
    restored_legs = cast(list[Mapping[str, object]], restored_payload["entry_component_legs"])
    assert [Decimal(cast(str, leg["stressed_vwap_usdc_per_btc"])) for leg in restored_legs] == [
        Decimal("550"),
        Decimal("210"),
    ]
    assert [Decimal(cast(str, leg["fee_reserve_usdc"])) for leg in restored_legs] == [
        Decimal("3"),
        Decimal("2.625"),
    ]
    assert restored_payload["full_quantity_btc"] == "0.1"
    assert restored_payload["entry_fact_boundary"] == opened_boundary.as_object()
    restored_sources = cast(
        list[Mapping[str, object]],
        restored_payload["entry_component_quote_source_refs"],
    )
    assert [source["source_timestamp_ms"] for source in restored_sources] == [1_000, 1_000]
    from radar_runtime.workbench import _shadow_rows

    recovered_rows = _shadow_rows(
        {"SHADOW_ENTRY": [restored]},
        policies,
    )
    assert recovered_rows[0]["simulated_entry_price_valuation_per_btc"] == "340"
    assert recovered_rows[0]["target_quantity_btc"] == "0.1"
    assert recovered_rows[0]["entry_fact_boundary"] == opened_boundary.as_object()
    assert [
        source["source_timestamp_ms"]
        for source in cast(
            list[Mapping[str, object]],
            recovered_rows[0]["entry_component_quote_source_refs"],
        )
    ] == [1_000, 1_000]

    close_identity = canonical_identity("PositionActionIdentity", "inverse-close")
    state.record(
        object_kind="POSITION_ACTION",
        object_identity=close_identity,
        fact_boundary=boundary(5),
        payload={
            "position_action_identity": close_identity,
            "shadow_entry_identity": entry_identity,
            "serialized_action": "CLOSE",
            "ordered_predicate_truth_vector": ["FALSE"] * 8 + ["TRUE"],
            "ordered_latched_close_reason_vector": ["ECONOMIC_EXIT_BOUNDARY_REACHED"],
            "primary_close_reason": "ECONOMIC_EXIT_BOUNDARY_REACHED",
            "secondary_close_reasons": [],
            "first_latched_close_action_identity": close_identity,
            "action_fact_boundary": boundary(5).as_object(),
        },
    )
    close_request_ids = [301, 302]
    close_request_params = [
        {"instrument_name": short_name, "depth": 10000},
        {"instrument_name": long_name, "depth": 10000},
    ]
    close_schedule_identity = canonical_identity(
        "ScheduledComponentPostCloseAttemptIdentity",
        entry_identity,
        close_identity,
        close_request_ids,
        "public/get_order_book",
        close_request_params,
        boundary(5).as_object(),
    )
    state.record(
        object_kind="POST_CLOSE_ATTEMPT_SCHEDULED",
        object_identity=close_schedule_identity,
        fact_boundary=boundary(5),
        payload={
            "scheduled_post_close_attempt_identity": close_schedule_identity,
            "shadow_entry_identity": entry_identity,
            "first_latched_close_action_identity": close_identity,
            "request_id_or_marker": close_request_ids,
            "execution_model": "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL",
            "request_method": "public/get_order_book",
            "request_params": close_request_params,
            "schedule_fact_boundary": boundary(5).as_object(),
        },
    )
    outcome_identity = canonical_identity("ShadowOutcomeIdentity", "inverse-known")
    state.record(
        object_kind="SHADOW_OUTCOME",
        object_identity=outcome_identity,
        fact_boundary=boundary(6),
        payload={
            "shadow_outcome_identity": outcome_identity,
            "shadow_entry_identity": entry_identity,
            "terminal_state": "MATURE_KNOWN",
            "selected_exit_identity": canonical_identity("ShadowExit", "inverse"),
            "first_latched_close_action_identity": close_identity,
            "native_gross_close_cashflow": "-0.00012",
            "native_close_fee_reserve": "0.000025",
            "native_net_close_cashflow": "-0.000145",
            "native_gross_pnl": "0.00022",
            "native_total_fee_reserve": "0.00008125",
            "native_net_pnl": "0.00013875",
            "close_valuation_index_price": "110000",
            "boundary_valued_net_pnl_usd": "12.425",
            "exit_valued_native_net_pnl_usd": "15.2625",
            "gross_close_cashflow_usdc": "-13.2",
            "close_fee_reserve_usdc": "2.75",
            "net_close_cashflow_usdc": "-15.95",
            "gross_pnl_usdc": "20.8",
            "total_public_fee_reserve_usdc": "8.375",
            "net_pnl_after_public_standard_fee_reserve_usdc": "12.425",
            "net_loss_usdc": "0",
            "economic_availability": "KNOWN",
            "close_component_pair_identity": canonical_identity("ComponentPair", "inverse-close"),
            "close_component_quote_source_refs": [
                {
                    "canonical_leg_role": role,
                    "source_identity": canonical_identity("ComponentCloseSource", "inverse", role),
                    "receipt_fact_boundary": boundary(6).as_object(),
                }
                for role in ("SHORT", "LONG")
            ],
            "close_component_legs": [
                component_leg(
                    role="SHORT",
                    name=short_name,
                    action="BUY",
                    raw_native="0.0015",
                    stressed_native="0.0016",
                    index_price="110000",
                    native_fee="0.000020",
                ),
                component_leg(
                    role="LONG",
                    name=long_name,
                    action="SELL",
                    raw_native="0.0005",
                    stressed_native="0.0004",
                    index_price="110000",
                    native_fee="0.000005",
                ),
            ],
            "censor_mask": [],
            "non_claims": [
                "NOT_AN_ORDER",
                "NOT_A_FILL",
                "NOT_AN_ATOMIC_QUOTE",
                "NO_LIQUIDITY_RESERVATION",
                "ATOMIC_EXECUTABILITY_UNPROVEN",
            ],
        },
    )

    read = case_store.read_case(case_id)
    assert read.status is ShadowCaseReadStatus.COMPLETE
    assert read.opened["schema_version"] == 5
    assert "_usdc" not in json.dumps(read.opened, sort_keys=True).lower()
    assert read.opened["product"] == {
        "product_spec_identity": INVERSE_BTC.identity,
        "product_name": "inverse-btc",
        "market_family": "DERIBIT_BTC_OPTIONS",
        "economic_semantics_version": "INVERSE_BTC_V1",
        "case_schema_version": 5,
        "native_premium_currency": "BTC",
        "settlement_currency": "BTC",
        "valuation_currency": "USD_EQUIVALENT",
        "price_index": "btc_usd",
        "strike_currency": "USD",
        "valuation_basis": "EACH_CASHFLOW_AT_ITS_CAUSAL_INDEX_BOUNDARY",
        "model_premium_rule": "NATIVE_BTC_PREMIUM_TIMES_FORWARD",
        "valuation_rule": "NATIVE_BTC_AMOUNT_TIMES_CAUSAL_BTC_USD_INDEX",
        "fee_rule": "MIN_BASE_RATE_OR_12_5_PERCENT_NATIVE_PREMIUM_IN_BTC",
        "native_settlement_payoff_rule": ("USD_STRIKE_PAYOFF_DIVIDED_BY_EXPIRY_DELIVERY_PRICE"),
        "native_settlement_liability_profile": (
            "SETTLEMENT_PRICE_DEPENDENT_RECIPROCAL_BTC_LIABILITY"
        ),
        "actual_account_margin_requirement": None,
        "actual_account_margin_availability": "UNKNOWN",
        "actual_account_margin_reason": "ACCOUNT_MARGIN_UNKNOWN",
    }
    native_entry = cast(
        Mapping[str, object],
        read.opened["native_entry_economics"],
    )
    assert native_entry["contractual_payoff_cap_strike_currency"] == "100"
    assert native_entry["native_contractual_payoff_cap_at_entry_index"] == "0.001"
    assert native_entry["native_contractual_payoff_cap_basis"] == (
        "ENTRY_INDEX_COUNTERFACTUAL_NOT_EXPIRY_SETTLEMENT"
    )
    assert native_entry["expiry_delivery_price"] is None
    assert native_entry["native_contractual_payoff_at_expiry"] is None
    assert read.outcome is not None
    assert "_usdc" not in json.dumps(read.outcome, sort_keys=True).lower()
    native_outcome = cast(
        Mapping[str, object],
        read.outcome["native_outcome_economics"],
    )
    assert native_outcome["native_net_pnl"] == "0.00013875"
    assert native_outcome["boundary_valued_net_pnl_usd"] == "12.425"
    assert native_outcome["exit_valued_native_net_pnl_usd"] == "15.2625"

    opened_path = cases / case_id.removeprefix("sha256:") / "opened.json"
    original_opened = opened_path.read_text(encoding="utf-8")
    wrong_product = json.loads(original_opened)
    wrong_product["structure"]["short_leg_instrument_name"] = "BTC_USDC-8AUG26-100000-C"
    wrong_product["structure"]["long_leg_instrument_name"] = "BTC_USDC-8AUG26-101000-C"
    wrong_product["structure"]["entry_component_legs"][0]["instrument_name"] = (
        "BTC_USDC-8AUG26-100000-C"
    )
    wrong_product["structure"]["entry_component_legs"][1]["instrument_name"] = (
        "BTC_USDC-8AUG26-101000-C"
    )
    opened_path.write_text(
        json.dumps(wrong_product, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ShadowCaseStoreError, match="does not match its option product"):
        case_store.read_case(case_id)

    wrong_orientation = json.loads(original_opened)
    wrong_orientation["structure"]["long_strike_usd_per_btc"] = "99000"
    opened_path.write_text(
        json.dumps(wrong_orientation, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ShadowCaseStoreError, match="not a protective vertical"):
        case_store.read_case(case_id)

    wrong_name_strike = json.loads(original_opened)
    wrong_name_strike["structure"]["short_leg_instrument_name"] = "BTC-8AUG26-99999-C"
    wrong_name_strike["structure"]["entry_component_legs"][0]["instrument_name"] = (
        "BTC-8AUG26-99999-C"
    )
    opened_path.write_text(
        json.dumps(wrong_name_strike, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ShadowCaseStoreError, match="instrument strike mismatch"):
        case_store.read_case(case_id)

    wrong_leg_expiry = json.loads(original_opened)
    wrong_leg_expiry["structure"]["long_leg_instrument_name"] = "BTC-9AUG26-101000-C"
    wrong_leg_expiry["structure"]["entry_component_legs"][1]["instrument_name"] = (
        "BTC-9AUG26-101000-C"
    )
    opened_path.write_text(
        json.dumps(wrong_leg_expiry, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ShadowCaseStoreError, match="instrument expiry date mismatch"):
        case_store.read_case(case_id)

    wrong_record_expiry = json.loads(original_opened)
    wrong_record_expiry["structure"]["expiry_ms"] = 1
    opened_path.write_text(
        json.dumps(wrong_record_expiry, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ShadowCaseStoreError, match="instrument expiry date mismatch"):
        case_store.read_case(case_id)

    tampered = json.loads(original_opened)
    entry_legs = tampered["structure"]["entry_component_legs"]
    entry_legs[0]["native_fee_reserve"] = "0.000031"
    entry_legs[0]["fee_reserve_usd"] = "3.100000"
    entry_legs[1]["native_fee_reserve"] = "0.00002525"
    entry_legs[1]["fee_reserve_usd"] = "2.52500000"
    opened_path.write_text(
        json.dumps(tampered, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ShadowCaseStoreError, match="native fee does not match"):
        case_store.read_case(case_id)


def test_workbench_browser_uses_product_owned_units() -> None:
    from radar_runtime.workbench import JS

    assert "documentValue.product" in JS
    assert "const valuationUnit = documentValue.product.valuation_currency" in JS
    assert "const nativeUnit = documentValue.product.native_premium_currency" in JS
    assert "Public-quote PnL (USDC)" not in JS
    assert "模拟权利金 (USDC)" not in JS
    assert "Close debit (USDC)" not in JS
    assert "Shadow PnL (USDC)" not in JS
    assert "净信用\uff08${nativeUnit}\uff09" in JS
    assert "净信用\uff08${valuationUnit}\uff09" in JS
    assert "_usdc" not in JS.lower()
