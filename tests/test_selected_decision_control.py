from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from itertools import count
from pathlib import Path

import pytest
from market_monitor import PriceLevel
from options_domain import (
    INVERSE_BTC,
    AmountMetadata,
    ComponentBookQuoteKind,
    ComponentBookVerticalQuote,
    OptionInstrument,
    OptionType,
    PriceTickMetadata,
    evaluate_component_book_vertical,
)
from short_vol_radar.black import DecimalInterval
from short_vol_radar.bucket import radar_bucket_episode_identity
from short_vol_radar.policy import digest_policy_bytes, load_policy_bytes
from short_vol_radar.score import (
    LeaderCoverage,
    RadarBucketKey,
    RadarScoreInputs,
    RadarScorePacket,
    ScoreBand,
    build_radar_score_packet,
    compute_radar_score,
    compute_unsigned_oi_concentration,
)
from short_vol_underwriting import (
    UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY,
    ComponentBookPairWitness,
    ComponentLegRole,
    DecisionControlAttempt,
    DecisionControlAttemptOutcome,
    DecisionControlKnownNoControlReason,
    DecisionControlRefreshClassification,
    FactBoundary,
    FixedContractShadowOwner,
    RpcComponentLegRefreshWitness,
    RuntimeBindings,
    ShadowCaseReadStatus,
    ShadowCaseStore,
    ShadowStateStore,
    SourceFact,
    TerminalSource,
    UnderwritingFacts,
    canonical_identity,
    component_pair_witness,
    designate_radar_score_control_review,
    designate_selected_decision_episode,
    load_policy_chain,
    radar_score_control_batch_identity,
    radar_score_control_designation_key,
    radar_score_control_rule_identity,
    selected_decision_batch_identity,
    selected_decision_designation_key,
    selected_decision_rule_identity,
)
from short_vol_underwriting.constants import (
    INVERSE_BTC_POSITION_POLICY_IDENTITY,
    INVERSE_BTC_RADAR_POLICY_IDENTITY,
    INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
)

ROOT = Path(__file__).resolve().parents[1]


def _boundary(causal_seq: int, monotonic_ms: int) -> FactBoundary:
    return FactBoundary(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        session_epoch=1,
        ingress_seq=causal_seq,
        received_monotonic_ms=monotonic_ms,
        causal_seq=causal_seq,
    )


def _bindings() -> RuntimeBindings:
    return RuntimeBindings(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        radar_policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_policy_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_policy_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )


def _score_packet(
    *,
    boundary: FactBoundary,
    band: ScoreBand,
    bucket_key: RadarBucketKey,
    leader_instrument_name: str,
) -> RadarScorePacket:
    exact_policy = (ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json").read_bytes()
    policy = load_policy_bytes(exact_policy, digest_policy_bytes(exact_policy))
    richness = {
        ScoreBand.LOW: DecimalInterval(Decimal("1"), Decimal("1")),
        ScoreBand.MID: DecimalInterval(Decimal("1.1375"), Decimal("1.1375")),
        ScoreBand.HIGH: DecimalInterval(Decimal("1.3"), Decimal("1.3")),
        ScoreBand.REVIEW: DecimalInterval(Decimal("1.1"), Decimal("1.2")),
    }[band]
    point_zero = DecimalInterval(Decimal(0), Decimal(0))
    point_one = DecimalInterval(Decimal(1), Decimal(1))
    score_inputs = RadarScoreInputs(
        stressed_richness=richness,
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
    result = compute_radar_score(policy.score_model, score_inputs)
    assert result.band is band
    return build_radar_score_packet(
        policy_identity=policy.identity,
        fact_boundary=boundary.as_object(),
        bucket_key=bucket_key,
        leader_instrument_name=leader_instrument_name,
        result=result,
        oi_diagnostic=compute_unsigned_oi_concentration(
            open_interest=None,
            option_gamma=None,
            bucket_total_unsigned_gamma_weight=None,
        ),
        stressed_richness=richness,
        leader_coverage=LeaderCoverage.COMPLETE,
    )


def _component_quote(
    *,
    short_name: str = "BTC-8AUG26-100000-C",
    long_name: str = "BTC-8AUG26-102000-C",
    short_strike: str = "100000",
    long_strike: str = "102000",
) -> tuple[
    OptionInstrument,
    OptionInstrument,
    ComponentBookVerticalQuote,
]:
    amount = AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1"))
    tick = PriceTickMetadata(Decimal("0.0001"))
    short = OptionInstrument(
        short_name,
        1_786_150_800_000,
        Decimal(short_strike),
        OptionType.CALL,
        amount,
        tick,
        product=INVERSE_BTC,
    )
    long = OptionInstrument(
        long_name,
        1_786_150_800_000,
        Decimal(long_strike),
        OptionType.CALL,
        amount,
        tick,
        product=INVERSE_BTC,
    )
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
    assert quote is not None and reasons == ()
    return short, long, quote


def _review_facts(
    *,
    boundary: FactBoundary,
    activation_causal_seq: int,
    review_identity: str,
    packet: RadarScorePacket,
    short: OptionInstrument,
    long: OptionInstrument,
    quote: ComponentBookVerticalQuote,
    short_source: SourceFact,
    long_source: SourceFact,
    pair: ComponentBookPairWitness | None = None,
) -> UnderwritingFacts:
    return UnderwritingFacts(
        boundary=boundary,
        radar_scope_identity=canonical_identity("RadarScope", review_identity),
        active_episode_identity=None,
        anomaly_activation_seq=None,
        short_leg_identity=canonical_identity("OptionIdentity", short.instrument_name),
        long_leg_identity=canonical_identity("OptionIdentity", long.instrument_name),
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
        short_instrument_source=SourceFact(
            canonical_identity("InstrumentSource", short.instrument_name, boundary.as_object()),
            boundary,
        ),
        long_instrument_source=SourceFact(
            canonical_identity("InstrumentSource", long.instrument_name, boundary.as_object()),
            boundary,
        ),
        index_source=SourceFact(
            canonical_identity("IndexSource", boundary.as_object()),
            boundary,
        ),
        ticker_source=SourceFact(
            canonical_identity("TickerSource", boundary.as_object()),
            boundary,
        ),
        short_leg_instrument_name=short.instrument_name,
        long_leg_instrument_name=long.instrument_name,
        component_state="COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE",
        component_quote=quote,
        component_short_quote_source=short_source,
        component_long_quote_source=long_source,
        component_pair_witness=pair,
        protective_leg_selection_rule_identity=(UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY),
        candidate_protective_leg_count=1,
        radar_score_packet=packet,
        radar_research_review_identity=review_identity,
        radar_research_activation_seq=activation_causal_seq,
    )


def _witness(
    *,
    role: ComponentLegRole,
    request_id: int,
    option_identity: str,
    instrument_name: str,
    origin: FactBoundary,
    sent: FactBoundary,
    response: FactBoundary,
    source_timestamp_ms: int,
    response_covers_full_quantity: bool = True,
    payload_matches_request: bool = True,
    payload_well_formed: bool = True,
) -> RpcComponentLegRefreshWitness:
    params = {"instrument_name": instrument_name, "depth": 10000}
    source_identity = canonical_identity(
        "RpcComponentLegRefreshSourceIdentity",
        response.runtime_identity,
        request_id,
        role.value,
        "public/get_order_book",
        option_identity,
        params,
        origin.as_object(),
        sent.as_object(),
        1,
        11,
        source_timestamp_ms,
        response.as_object(),
    )
    return RpcComponentLegRefreshWitness(
        source_identity=source_identity,
        boundary=response,
        role=role,
        canonical_option_identity=option_identity,
        instrument_name=instrument_name,
        request_params=params,
        change_id=11,
        source_timestamp_ms=source_timestamp_ms,
        request_id=request_id,
        owner_origin_boundary=origin,
        sent_boundary=sent,
        global_continuity_epoch=1,
        response_covers_full_quantity=response_covers_full_quantity,
        payload_matches_request=payload_matches_request,
        payload_well_formed=payload_well_formed,
    )


def test_selected_decision_rule_batch_and_designation_are_pre_outcome_policy_bound() -> None:
    bindings = _bindings()

    rule = selected_decision_rule_identity(bindings=bindings)
    first = selected_decision_batch_identity(
        bindings=bindings,
        activation_causal_seq=7,
    )
    same = selected_decision_batch_identity(
        bindings=bindings,
        activation_causal_seq=7,
    )
    next_batch = selected_decision_batch_identity(
        bindings=bindings,
        activation_causal_seq=8,
    )
    first_episode = f"{bindings.runtime_identity}:{bindings.radar_policy_identity}:BTC-FIRST:7"
    second_episode = f"{bindings.runtime_identity}:{bindings.radar_policy_identity}:BTC-SECOND:7"
    designation_keys = {
        episode: selected_decision_designation_key(
            bindings=bindings,
            batch_identity=first,
            episode_identity=episode,
        )
        for episode in (first_episode, second_episode)
    }
    designated = designate_selected_decision_episode(
        bindings=bindings,
        batch_identity=first,
        episode_identities=(second_episode, first_episode),
    )
    reordered = designate_selected_decision_episode(
        bindings=bindings,
        batch_identity=first,
        episode_identities=(first_episode, second_episode),
    )

    assert rule.startswith("sha256:")
    assert first == same
    assert next_batch != first
    assert designated == reordered
    assert designated == min(designation_keys, key=designation_keys.__getitem__)


def test_radar_score_control_designation_is_stratified_bounded_and_order_independent() -> None:
    bindings = _bindings()
    batch = radar_score_control_batch_identity(
        bindings=bindings,
        activation_causal_seq=7,
    )
    reviews = (
        ("sha256:" + "1" * 64, "LOW"),
        ("sha256:" + "2" * 64, "LOW"),
        ("sha256:" + "3" * 64, "MID"),
        ("sha256:" + "4" * 64, "MID"),
        ("sha256:" + "5" * 64, "MID"),
    )

    first = designate_radar_score_control_review(
        bindings=bindings,
        batch_identity=batch,
        eligible_reviews=reviews,
    )
    reordered = designate_radar_score_control_review(
        bindings=bindings,
        batch_identity=batch,
        eligible_reviews=tuple(reversed(reviews)),
    )

    assert first == reordered
    assert first.rule_identity == radar_score_control_rule_identity(bindings=bindings)
    assert (first.low_eligible_count, first.mid_eligible_count) == (2, 3)
    assert first.present_stratum_count == 2
    selected_members = tuple(
        review_identity for review_identity, band in reviews if band == first.selected_band
    )
    assert first.selected_review_identity == min(
        selected_members,
        key=lambda review_identity: radar_score_control_designation_key(
            bindings=bindings,
            batch_identity=batch,
            review_identity=review_identity,
            band=first.selected_band,
        ),
    )
    assert first.inclusion_numerator == 1
    assert first.inclusion_denominator == 2 * len(selected_members)


def test_radar_score_control_single_stratum_probability_and_no_fallback_membership() -> None:
    bindings = _bindings()
    batch = radar_score_control_batch_identity(
        bindings=bindings,
        activation_causal_seq=8,
    )
    reviews = (
        ("sha256:" + "6" * 64, "MID"),
        ("sha256:" + "7" * 64, "MID"),
    )

    selected = designate_radar_score_control_review(
        bindings=bindings,
        batch_identity=batch,
        eligible_reviews=reviews,
    )

    assert selected.selected_band == "MID"
    assert selected.low_eligible_count == 0
    assert selected.mid_eligible_count == 2
    assert selected.present_stratum_count == 1
    assert selected.inclusion_denominator == 2
    with pytest.raises(ValueError, match="LOW or MID"):
        designate_radar_score_control_review(
            bindings=bindings,
            batch_identity=batch,
            eligible_reviews=(("sha256:" + "8" * 64, "HIGH"),),
        )


@pytest.mark.parametrize(
    "refresh_known_no_control",
    (False, True),
    ids=("control-opened", "known-no-control"),
)
def test_low_band_candidate_refresh_opens_control_or_attributes_known_no_control(
    tmp_path: Path,
    refresh_known_no_control: bool,
) -> None:
    bindings = _bindings()
    policies = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json",
        underwriting_path=(ROOT / "policies/short-vol-inverse-btc-public-shadow-underwriting.json"),
        position_path=(ROOT / "policies/short-vol-inverse-btc-public-shadow-position.json"),
        radar_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )
    cases = tmp_path / "cases"
    cases.mkdir()
    case_store = ShadowCaseStore(cases, bindings=bindings, policies=policies)
    state = ShadowStateStore(bindings=bindings, observer=case_store)
    owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        state_store=state,
    )
    short, long, quote = _component_quote()
    activation = _boundary(1, 100)
    bucket_key = RadarBucketKey(
        tte_band_id="six-to-twenty-four-hours",
        expiry_ms=short.expiration_timestamp_ms,
        option_type=OptionType.CALL,
        delta_bucket="0.15-0.25",
    )
    selection_packet = _score_packet(
        boundary=activation,
        band=ScoreBand.LOW,
        bucket_key=bucket_key,
        leader_instrument_name=short.instrument_name,
    )
    review_identity = radar_bucket_episode_identity(
        runtime_identity=bindings.runtime_identity,
        policy_identity=bindings.radar_policy_identity,
        bucket_key=bucket_key,
        leader_instrument_name=short.instrument_name,
        score_band=ScoreBand.LOW,
        activation_causal_seq=activation.causal_seq,
    )
    initial_source = SourceFact(
        canonical_identity("SelectionComponentSource", review_identity),
        activation,
    )
    selection_facts = _review_facts(
        boundary=activation,
        activation_causal_seq=activation.causal_seq,
        review_identity=review_identity,
        packet=selection_packet,
        short=short,
        long=long,
        quote=quote,
        short_source=initial_source,
        long_source=initial_source,
    )
    request_ids = count(41)

    selected = owner.settle_underwriting(
        (selection_facts,),
        allocate_request_id=lambda: next(request_ids),
    )

    assert len(selected.request_intents) == 2
    assert list(cases.iterdir()) == []
    assert owner.active_candidate_identities == frozenset()
    assert not any(value["object_kind"] == "CANDIDATE_ACTIVATION" for value in state.objects)
    selected_record = next(
        value for value in state.objects if value["object_kind"] == "SELECTED_UNDERWRITING_DECISION"
    )
    selection_identity = selected_record["object_identity"]
    assert isinstance(selection_identity, str)

    sent_boundaries = (_boundary(2, 110), _boundary(3, 111))
    for intent, sent_boundary in zip(selected.request_intents, sent_boundaries, strict=True):
        owner.note_request_sent(request_id=intent.request_id, boundary=sent_boundary)
    short_identity = canonical_identity("OptionIdentity", short.instrument_name)
    long_identity = canonical_identity("OptionIdentity", long.instrument_name)
    pair = component_pair_witness(
        short=_witness(
            role=ComponentLegRole.SHORT,
            request_id=selected.request_intents[0].request_id,
            option_identity=short_identity,
            instrument_name=short.instrument_name,
            origin=activation,
            sent=sent_boundaries[0],
            response=_boundary(4, 120),
            source_timestamp_ms=1_000,
        ),
        long=_witness(
            role=ComponentLegRole.LONG,
            request_id=selected.request_intents[1].request_id,
            option_identity=long_identity,
            instrument_name=long.instrument_name,
            origin=activation,
            sent=sent_boundaries[1],
            response=_boundary(5, 121),
            source_timestamp_ms=1_001,
        ),
    )
    refresh_packet = _score_packet(
        boundary=pair.boundary,
        band=ScoreBand.HIGH,
        bucket_key=bucket_key,
        leader_instrument_name=short.instrument_name,
    )
    refreshed_facts = _review_facts(
        boundary=pair.boundary,
        activation_causal_seq=activation.causal_seq,
        review_identity=review_identity,
        packet=refresh_packet,
        short=short,
        long=long,
        quote=quote,
        short_source=SourceFact(pair.short.source_identity, pair.short.boundary),
        long_source=SourceFact(pair.long.source_identity, pair.long.boundary),
        pair=pair,
    )
    if refresh_known_no_control:
        refreshed_facts = replace(
            refreshed_facts,
            component_state="NO_PROTECTIVE_COMPONENT",
            component_quote=None,
            component_blockers=("NO_PROTECTIVE_COMPONENT",),
        )

    opened_transition = owner.settle_component_decision_control(
        selection_identity=selection_identity,
        refreshed_facts=refreshed_facts,
        pair_witness=pair,
    )

    if refresh_known_no_control:
        assert not any(
            emitted.object_kind == "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OPEN"
            for emitted in opened_transition.emitted
        )
        terminal = next(
            value
            for value in state.objects
            if value["object_kind"] == "UNDERWRITING_DECISION_CONTROL_ATTEMPT_TERMINAL"
        )
        payload = terminal["payload"]
        assert isinstance(payload, Mapping)
        assert payload["terminal_outcome"] == "KNOWN_NO_CONTROL"
        assert payload["known_no_control_reason"] == "NO_PROTECTIVE_COMPONENT"
        assert list(cases.iterdir()) == []
        return

    assert any(
        emitted.object_kind == "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OPEN"
        for emitted in opened_transition.emitted
    )
    assert owner.active_candidate_identities == frozenset()
    assert owner.retained_state_counts["active_consumed_slots"] == 0
    assert not any(value["object_kind"] == "SHADOW_ENTRY" for value in state.objects)
    control_open = next(
        value
        for value in state.objects
        if value["object_kind"] == "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OPEN"
    )
    control_identity = control_open["object_identity"]
    assert isinstance(control_identity, str)
    case_id = case_store.case_id_for_enrollment(control_identity)
    assert case_id is not None
    read = case_store.read_case(case_id, runtime_active=True)
    assert read.status is ShadowCaseReadStatus.OPEN
    assert read.opened["schema_version"] == 5
    assert read.opened["enrollment_kind"] == "RADAR_SCORE_BAND_NO_TRADE_CONTROL"
    selection_object = read.opened["selection_score_packet"]
    refresh_object = read.opened["entry_refresh_score_packet"]
    assert isinstance(selection_object, Mapping)
    assert isinstance(refresh_object, Mapping)
    assert selection_object["result"]["band"] == "LOW"
    assert refresh_object["result"]["band"] == "HIGH"
    assert selection_object["sampling_metadata"] == refresh_object["sampling_metadata"]
    metadata = selection_object["sampling_metadata"]
    assert metadata["eligible_count"] == 1
    assert metadata["stratum_count"] == 1
    assert metadata["inclusion_numerator"] == 1
    assert metadata["inclusion_denominator"] == 1

    owner.terminate(
        boundary=_boundary(6, 130),
        terminal_source_identity=canonical_identity("RuntimeStop", control_identity),
        terminal_source=TerminalSource.STOP,
    )
    assert any(
        value["object_kind"] == "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OUTCOME"
        for value in state.objects
    )
    completed = case_store.read_case(case_id)
    assert completed.status is ShadowCaseReadStatus.COMPLETE
    assert completed.outcome is not None
    assert completed.outcome["terminal_state"] == "CENSORED_AT_STOP"


def test_delayed_low_control_selection_freezes_activation_packet_across_band_drift(
    tmp_path: Path,
) -> None:
    bindings = _bindings()
    policies = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json",
        underwriting_path=(ROOT / "policies/short-vol-inverse-btc-public-shadow-underwriting.json"),
        position_path=(ROOT / "policies/short-vol-inverse-btc-public-shadow-position.json"),
        radar_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )
    cases = tmp_path / "cases"
    cases.mkdir()
    case_store = ShadowCaseStore(cases, bindings=bindings, policies=policies)
    state = ShadowStateStore(bindings=bindings, observer=case_store)
    owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        state_store=state,
    )
    short, long, quote = _component_quote()
    activation = _boundary(1, 100)
    bucket_key = RadarBucketKey(
        tte_band_id="six-to-twenty-four-hours",
        expiry_ms=short.expiration_timestamp_ms,
        option_type=OptionType.CALL,
        delta_bucket="0.15-0.25",
    )
    activation_packet = _score_packet(
        boundary=activation,
        band=ScoreBand.LOW,
        bucket_key=bucket_key,
        leader_instrument_name=short.instrument_name,
    )
    review_identity = radar_bucket_episode_identity(
        runtime_identity=bindings.runtime_identity,
        policy_identity=bindings.radar_policy_identity,
        bucket_key=bucket_key,
        leader_instrument_name=short.instrument_name,
        score_band=ScoreBand.LOW,
        activation_causal_seq=activation.causal_seq,
    )
    activation_source = SourceFact(
        canonical_identity("DelayedSelectionSource", activation.as_object()),
        activation,
    )
    unavailable = replace(
        _review_facts(
            boundary=activation,
            activation_causal_seq=activation.causal_seq,
            review_identity=review_identity,
            packet=activation_packet,
            short=short,
            long=long,
            quote=quote,
            short_source=activation_source,
            long_source=activation_source,
        ),
        component_state="COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN",
        component_blockers=("COMPONENT_BOOK_UNKNOWN",),
        component_quote=None,
        component_short_quote_source=None,
        component_long_quote_source=None,
        unknown_reasons=("COMPONENT_BOOK_UNKNOWN",),
    )
    request_ids = count(201)

    first = owner.settle_underwriting(
        (unavailable,),
        allocate_request_id=lambda: next(request_ids),
    )

    assert first.request_intents == ()
    assert list(cases.iterdir()) == []

    selection_boundary = _boundary(2, 110)
    current_packet = _score_packet(
        boundary=selection_boundary,
        band=ScoreBand.MID,
        bucket_key=bucket_key,
        leader_instrument_name=short.instrument_name,
    )
    selection_source = SourceFact(
        canonical_identity("DelayedSelectionSource", selection_boundary.as_object()),
        selection_boundary,
    )
    current = _review_facts(
        boundary=selection_boundary,
        activation_causal_seq=activation.causal_seq,
        review_identity=review_identity,
        packet=current_packet,
        short=short,
        long=long,
        quote=quote,
        short_source=selection_source,
        long_source=selection_source,
    )

    selected = owner.settle_underwriting(
        (current,),
        allocate_request_id=lambda: next(request_ids),
    )

    assert len(selected.request_intents) == 2
    selected_record = next(
        value for value in state.objects if value["object_kind"] == "SELECTED_UNDERWRITING_DECISION"
    )
    selection_identity = selected_record["object_identity"]
    assert isinstance(selection_identity, str)
    frozen = owner._decision_controls[selection_identity].selection.selection_score_packet
    assert frozen.result.band is ScoreBand.LOW
    assert frozen.fact_boundary == activation.as_object()
    assert frozen.sampling_metadata is not None
    assert frozen.sampling_metadata.control_band is ScoreBand.LOW

    sent_boundaries = (_boundary(3, 120), _boundary(4, 121))
    for intent, sent_boundary in zip(selected.request_intents, sent_boundaries, strict=True):
        owner.note_request_sent(request_id=intent.request_id, boundary=sent_boundary)
    short_identity = canonical_identity("OptionIdentity", short.instrument_name)
    long_identity = canonical_identity("OptionIdentity", long.instrument_name)
    pair = component_pair_witness(
        short=_witness(
            role=ComponentLegRole.SHORT,
            request_id=selected.request_intents[0].request_id,
            option_identity=short_identity,
            instrument_name=short.instrument_name,
            origin=selection_boundary,
            sent=sent_boundaries[0],
            response=_boundary(5, 130),
            source_timestamp_ms=1_000,
        ),
        long=_witness(
            role=ComponentLegRole.LONG,
            request_id=selected.request_intents[1].request_id,
            option_identity=long_identity,
            instrument_name=long.instrument_name,
            origin=selection_boundary,
            sent=sent_boundaries[1],
            response=_boundary(6, 131),
            source_timestamp_ms=1_001,
        ),
    )
    refresh_packet = _score_packet(
        boundary=pair.boundary,
        band=ScoreBand.HIGH,
        bucket_key=bucket_key,
        leader_instrument_name=short.instrument_name,
    )
    refreshed = _review_facts(
        boundary=pair.boundary,
        activation_causal_seq=activation.causal_seq,
        review_identity=review_identity,
        packet=refresh_packet,
        short=short,
        long=long,
        quote=quote,
        short_source=SourceFact(pair.short.source_identity, pair.short.boundary),
        long_source=SourceFact(pair.long.source_identity, pair.long.boundary),
        pair=pair,
    )

    owner.settle_component_decision_control(
        selection_identity=selection_identity,
        refreshed_facts=refreshed,
        pair_witness=pair,
    )

    control_open = next(
        value
        for value in state.objects
        if value["object_kind"] == "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OPEN"
    )
    control_identity = control_open["object_identity"]
    assert isinstance(control_identity, str)
    case_id = case_store.case_id_for_enrollment(control_identity)
    assert case_id is not None
    opened = case_store.read_case(case_id, runtime_active=True).opened
    selection_object = opened["selection_score_packet"]
    refresh_object = opened["entry_refresh_score_packet"]
    assert isinstance(selection_object, Mapping)
    assert isinstance(refresh_object, Mapping)
    selection_result = selection_object["result"]
    refresh_result = refresh_object["result"]
    assert isinstance(selection_result, Mapping)
    assert isinstance(refresh_result, Mapping)
    assert selection_result["band"] == "LOW"
    assert selection_object["fact_boundary"] == activation.as_object()
    assert refresh_result["band"] == "HIGH"
    assert refresh_object["fact_boundary"] == pair.boundary.as_object()


def test_high_with_combo_owns_batch_before_low_mid_control_designation() -> None:
    bindings = _bindings()
    policies = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json",
        underwriting_path=(ROOT / "policies/short-vol-inverse-btc-public-shadow-underwriting.json"),
        position_path=(ROOT / "policies/short-vol-inverse-btc-public-shadow-position.json"),
        radar_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )
    state = ShadowStateStore(bindings=bindings)
    owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        state_store=state,
    )
    short, long, quote = _component_quote()
    activation = _boundary(7, 170)
    bucket_key = RadarBucketKey(
        tte_band_id="six-to-twenty-four-hours",
        expiry_ms=short.expiration_timestamp_ms,
        option_type=OptionType.CALL,
        delta_bucket="0.15-0.25",
    )
    low_packet = _score_packet(
        boundary=activation,
        band=ScoreBand.LOW,
        bucket_key=bucket_key,
        leader_instrument_name=short.instrument_name,
    )
    low_identity = radar_bucket_episode_identity(
        runtime_identity=bindings.runtime_identity,
        policy_identity=bindings.radar_policy_identity,
        bucket_key=bucket_key,
        leader_instrument_name=short.instrument_name,
        score_band=ScoreBand.LOW,
        activation_causal_seq=activation.causal_seq,
    )
    source = SourceFact(canonical_identity("BatchSource", activation.as_object()), activation)
    low_facts = _review_facts(
        boundary=activation,
        activation_causal_seq=activation.causal_seq,
        review_identity=low_identity,
        packet=low_packet,
        short=short,
        long=long,
        quote=quote,
        short_source=source,
        long_source=source,
    )
    high_packet = _score_packet(
        boundary=activation,
        band=ScoreBand.HIGH,
        bucket_key=bucket_key,
        leader_instrument_name=short.instrument_name,
    )
    high_identity = radar_bucket_episode_identity(
        runtime_identity=bindings.runtime_identity,
        policy_identity=bindings.radar_policy_identity,
        bucket_key=bucket_key,
        leader_instrument_name=short.instrument_name,
        score_band=ScoreBand.HIGH,
        activation_causal_seq=activation.causal_seq,
    )
    high_facts = replace(
        low_facts,
        radar_scope_identity=canonical_identity("RadarScope", high_identity),
        active_episode_identity=high_identity,
        anomaly_activation_seq=activation.causal_seq,
        canonical_combo_identity=canonical_identity("OfficialCombo", high_identity),
        combo_instrument_name="BTC-OFFICIAL-COMBO",
        radar_score_packet=high_packet,
        radar_research_review_identity=None,
        radar_research_activation_seq=None,
    )
    request_ids = count(101)

    owner.settle_underwriting(
        (low_facts, high_facts),
        allocate_request_id=lambda: next(request_ids),
    )

    designation = next(
        value
        for value in state.objects
        if value["object_kind"] == "UNDERWRITING_DECISION_BATCH_DESIGNATION"
    )
    designation_payload = designation["payload"]
    assert isinstance(designation_payload, Mapping)
    assert designation_payload["designated_episode_identity"] == high_identity
    assert designation_payload["score_band_eligible_counts"] is None
    selected_decision = next(
        value for value in state.objects if value["object_kind"] == "SELECTED_UNDERWRITING_DECISION"
    )
    selected_payload = selected_decision["payload"]
    assert isinstance(selected_payload, Mapping)
    assert selected_payload["selection_kind"] == "HIGH_ACTION_BLIND"
    assert selected_payload["active_episode_identity"] == high_identity
    assert selected_payload["radar_research_review_identity"] is None
    assert owner.active_candidate_identities
    assert owner.active_decision_control_identities == frozenset()


def test_first_late_high_candidate_uses_episode_activation_packet_for_case(
    tmp_path: Path,
) -> None:
    bindings = _bindings()
    policies = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json",
        underwriting_path=(ROOT / "policies/short-vol-inverse-btc-public-shadow-underwriting.json"),
        position_path=(ROOT / "policies/short-vol-inverse-btc-public-shadow-position.json"),
        radar_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )
    cases = tmp_path / "cases"
    cases.mkdir()
    case_store = ShadowCaseStore(cases, bindings=bindings, policies=policies)
    state = ShadowStateStore(bindings=bindings, observer=case_store)
    owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        state_store=state,
    )
    component_pairs = (
        _component_quote(),
        _component_quote(
            short_name="BTC-8AUG26-104000-C",
            long_name="BTC-8AUG26-106000-C",
            short_strike="104000",
            long_strike="106000",
        ),
    )
    first_short = component_pairs[0][0]
    activation = _boundary(1, 100)
    bucket_keys = (
        RadarBucketKey(
            tte_band_id="six-to-twenty-four-hours",
            expiry_ms=first_short.expiration_timestamp_ms,
            option_type=OptionType.CALL,
            delta_bucket="0.05-0.15",
        ),
        RadarBucketKey(
            tte_band_id="six-to-twenty-four-hours",
            expiry_ms=first_short.expiration_timestamp_ms,
            option_type=OptionType.CALL,
            delta_bucket="0.15-0.25",
        ),
    )
    packets = tuple(
        _score_packet(
            boundary=activation,
            band=ScoreBand.HIGH,
            bucket_key=bucket_key,
            leader_instrument_name=component_pairs[index][0].instrument_name,
        )
        for index, bucket_key in enumerate(bucket_keys)
    )
    episode_identities = tuple(
        radar_bucket_episode_identity(
            runtime_identity=bindings.runtime_identity,
            policy_identity=bindings.radar_policy_identity,
            bucket_key=bucket_key,
            leader_instrument_name=component_pairs[index][0].instrument_name,
            score_band=ScoreBand.HIGH,
            activation_causal_seq=activation.causal_seq,
        )
        for index, bucket_key in enumerate(bucket_keys)
    )
    target_index = 1
    target_episode = episode_identities[target_index]
    short, long, quote = component_pairs[target_index]
    activation_source = SourceFact(
        canonical_identity("DelayedHighActivationSource", activation.as_object()),
        activation,
    )
    activation_facts = []
    for index, (packet, episode_identity, (member_short, member_long, member_quote)) in enumerate(
        zip(
            packets,
            episode_identities,
            component_pairs,
            strict=True,
        )
    ):
        if index == target_index:
            continue
        member = replace(
            _review_facts(
                boundary=activation,
                activation_causal_seq=activation.causal_seq,
                review_identity=episode_identity,
                packet=packet,
                short=member_short,
                long=member_long,
                quote=member_quote,
                short_source=activation_source,
                long_source=activation_source,
            ),
            radar_scope_identity=canonical_identity("RadarScope", episode_identity),
            active_episode_identity=episode_identity,
            anomaly_activation_seq=activation.causal_seq,
            radar_research_review_identity=None,
            radar_research_activation_seq=None,
            component_state="COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN",
            component_blockers=("COMPONENT_BOOK_UNKNOWN",),
            component_quote=None,
            component_short_quote_source=None,
            component_long_quote_source=None,
            unknown_reasons=("COMPONENT_BOOK_UNKNOWN",),
            short_delta=Decimal("0.10") if index == 0 else Decimal("0.20"),
        )
        activation_facts.append(member)
    request_ids = count(301)

    first = owner.settle_underwriting(
        tuple(activation_facts),
        allocate_request_id=lambda: next(request_ids),
    )

    assert first.request_intents == ()
    assert owner.active_candidate_identities == frozenset()
    selection_boundary = _boundary(2, 110)
    current_packet = _score_packet(
        boundary=selection_boundary,
        band=ScoreBand.MID,
        bucket_key=bucket_keys[target_index],
        leader_instrument_name=short.instrument_name,
    )
    selection_source = SourceFact(
        canonical_identity("DelayedHighSelectionSource", selection_boundary.as_object()),
        selection_boundary,
    )
    current = replace(
        _review_facts(
            boundary=selection_boundary,
            activation_causal_seq=activation.causal_seq,
            review_identity=target_episode,
            packet=current_packet,
            short=short,
            long=long,
            quote=quote,
            short_source=selection_source,
            long_source=selection_source,
        ),
        radar_scope_identity=canonical_identity("RadarScope", target_episode),
        active_episode_identity=target_episode,
        anomaly_activation_seq=activation.causal_seq,
        radar_research_review_identity=None,
        radar_research_activation_seq=None,
        radar_activation_score_packet=packets[target_index],
        short_delta=Decimal("0.10") if target_index == 0 else Decimal("0.20"),
    )

    selected = owner.settle_underwriting(
        (current,),
        allocate_request_id=lambda: next(request_ids),
    )

    assert len(selected.request_intents) == 2
    assert len(owner.active_candidate_identities) == 1
    candidate_identity = next(iter(owner.active_candidate_identities))
    sent_boundaries = (_boundary(3, 120), _boundary(4, 121))
    for intent, sent_boundary in zip(selected.request_intents, sent_boundaries, strict=True):
        owner.note_request_sent(request_id=intent.request_id, boundary=sent_boundary)
    pair = component_pair_witness(
        short=_witness(
            role=ComponentLegRole.SHORT,
            request_id=selected.request_intents[0].request_id,
            option_identity=canonical_identity("OptionIdentity", short.instrument_name),
            instrument_name=short.instrument_name,
            origin=selection_boundary,
            sent=sent_boundaries[0],
            response=_boundary(5, 130),
            source_timestamp_ms=1_000,
        ),
        long=_witness(
            role=ComponentLegRole.LONG,
            request_id=selected.request_intents[1].request_id,
            option_identity=canonical_identity("OptionIdentity", long.instrument_name),
            instrument_name=long.instrument_name,
            origin=selection_boundary,
            sent=sent_boundaries[1],
            response=_boundary(6, 131),
            source_timestamp_ms=1_001,
        ),
    )
    refresh_packet = _score_packet(
        boundary=pair.boundary,
        band=ScoreBand.MID,
        bucket_key=bucket_keys[target_index],
        leader_instrument_name=short.instrument_name,
    )
    refreshed = replace(
        current,
        boundary=pair.boundary,
        radar_score_packet=refresh_packet,
        component_short_quote_source=SourceFact(pair.short.source_identity, pair.short.boundary),
        component_long_quote_source=SourceFact(pair.long.source_identity, pair.long.boundary),
        component_pair_witness=pair,
    )

    owner.settle_component_admission(
        candidate_identity=candidate_identity,
        refreshed_facts=refreshed,
        pair_witness=pair,
    )

    entry = next(value for value in state.objects if value["object_kind"] == "SHADOW_ENTRY")
    entry_identity = entry["object_identity"]
    assert isinstance(entry_identity, str)
    case_id = case_store.case_id_for_enrollment(entry_identity)
    assert case_id is not None
    opened = case_store.read_case(case_id, runtime_active=True).opened
    selection_object = opened["selection_score_packet"]
    refresh_object = opened["entry_refresh_score_packet"]
    assert isinstance(selection_object, Mapping)
    assert isinstance(refresh_object, Mapping)
    assert selection_object["result"]["band"] == "HIGH"
    assert selection_object["fact_boundary"] == activation.as_object()
    assert refresh_object["result"]["band"] == "MID"
    assert refresh_object["fact_boundary"] == pair.boundary.as_object()


def test_decision_control_attempt_opens_only_from_one_strictly_later_valid_pair() -> None:
    origin = _boundary(1, 100)
    short_identity = "sha256:" + "6" * 64
    long_identity = "sha256:" + "7" * 64
    attempt = DecisionControlAttempt.schedule(
        selection_identity="sha256:" + "5" * 64,
        short_option_identity=short_identity,
        long_option_identity=long_identity,
        short_request_id=41,
        long_request_id=42,
        boundary=origin,
        short_instrument_name="BTC-SHORT",
        long_instrument_name="BTC-LONG",
    )

    intents = attempt.take_request_intents()
    assert [intent.purpose for intent in intents] == [
        "COMPONENT_DECISION_CONTROL_SHORT_REFRESH",
        "COMPONENT_DECISION_CONTROL_LONG_REFRESH",
    ]
    short_sent = _boundary(2, 110)
    long_sent = _boundary(3, 111)
    assert attempt.mark_sent(request_id=41, boundary=short_sent, send_budget_ms=30_000)
    assert attempt.mark_sent(request_id=42, boundary=long_sent, send_budget_ms=30_000)
    pair = component_pair_witness(
        short=_witness(
            role=ComponentLegRole.SHORT,
            request_id=41,
            option_identity=short_identity,
            instrument_name="BTC-SHORT",
            origin=origin,
            sent=short_sent,
            response=_boundary(4, 120),
            source_timestamp_ms=1_000,
        ),
        long=_witness(
            role=ComponentLegRole.LONG,
            request_id=42,
            option_identity=long_identity,
            instrument_name="BTC-LONG",
            origin=origin,
            sent=long_sent,
            response=_boundary(5, 121),
            source_timestamp_ms=1_001,
        ),
    )

    assert attempt.accept_pair(
        witness=pair,
        response_budget_ms=30_000,
        maximum_source_skew_ms=6_000,
        maximum_receive_skew_ms=4_000,
        classification=DecisionControlRefreshClassification.REFRESHED_WATCH_OR_ABSTAIN,
    )
    assert attempt.terminal_outcome is DecisionControlAttemptOutcome.CONTROL_OPENED
    assert attempt.terminal_boundary == pair.boundary
    assert attempt.take_request_intents() == ()


def test_decision_control_attempt_requires_one_fixed_reason_for_known_no_control() -> None:
    origin = _boundary(1, 100)
    short_identity = "sha256:" + "6" * 64
    long_identity = "sha256:" + "7" * 64
    attempt = DecisionControlAttempt.schedule(
        selection_identity="sha256:" + "5" * 64,
        short_option_identity=short_identity,
        long_option_identity=long_identity,
        short_request_id=41,
        long_request_id=42,
        boundary=origin,
        short_instrument_name="BTC-SHORT",
        long_instrument_name="BTC-LONG",
    )
    attempt.take_request_intents()
    short_sent = _boundary(2, 110)
    long_sent = _boundary(3, 111)
    attempt.mark_sent(request_id=41, boundary=short_sent, send_budget_ms=30_000)
    attempt.mark_sent(request_id=42, boundary=long_sent, send_budget_ms=30_000)
    pair = component_pair_witness(
        short=_witness(
            role=ComponentLegRole.SHORT,
            request_id=41,
            option_identity=short_identity,
            instrument_name="BTC-SHORT",
            origin=origin,
            sent=short_sent,
            response=_boundary(4, 120),
            source_timestamp_ms=1_000,
        ),
        long=_witness(
            role=ComponentLegRole.LONG,
            request_id=42,
            option_identity=long_identity,
            instrument_name="BTC-LONG",
            origin=origin,
            sent=long_sent,
            response=_boundary(5, 121),
            source_timestamp_ms=1_001,
        ),
    )

    with pytest.raises(ValueError, match="requires exactly one"):
        attempt.accept_pair(
            witness=pair,
            response_budget_ms=30_000,
            maximum_source_skew_ms=6_000,
            maximum_receive_skew_ms=4_000,
            classification=DecisionControlRefreshClassification.NOT_EVALUATED,
        )

    assert attempt.accept_pair(
        witness=pair,
        response_budget_ms=30_000,
        maximum_source_skew_ms=6_000,
        maximum_receive_skew_ms=4_000,
        classification=DecisionControlRefreshClassification.NOT_EVALUATED,
        known_no_control_reason=(DecisionControlKnownNoControlReason.NO_PROTECTIVE_COMPONENT),
    )
    assert attempt.terminal_outcome is DecisionControlAttemptOutcome.KNOWN_NO_CONTROL
    assert attempt.terminal_known_no_control_reason is (
        DecisionControlKnownNoControlReason.NO_PROTECTIVE_COMPONENT
    )


def test_decision_control_attempt_fails_closed_on_pair_skew() -> None:
    origin = _boundary(1, 100)
    short_identity = "sha256:" + "6" * 64
    long_identity = "sha256:" + "7" * 64
    attempt = DecisionControlAttempt.schedule(
        selection_identity="sha256:" + "5" * 64,
        short_option_identity=short_identity,
        long_option_identity=long_identity,
        short_request_id=41,
        long_request_id=42,
        boundary=origin,
        short_instrument_name="BTC-SHORT",
        long_instrument_name="BTC-LONG",
    )
    attempt.take_request_intents()
    short_sent = _boundary(2, 110)
    long_sent = _boundary(3, 111)
    attempt.mark_sent(request_id=41, boundary=short_sent, send_budget_ms=30_000)
    attempt.mark_sent(request_id=42, boundary=long_sent, send_budget_ms=30_000)
    pair = component_pair_witness(
        short=_witness(
            role=ComponentLegRole.SHORT,
            request_id=41,
            option_identity=short_identity,
            instrument_name="BTC-SHORT",
            origin=origin,
            sent=short_sent,
            response=_boundary(4, 120),
            source_timestamp_ms=1_000,
        ),
        long=_witness(
            role=ComponentLegRole.LONG,
            request_id=42,
            option_identity=long_identity,
            instrument_name="BTC-LONG",
            origin=origin,
            sent=long_sent,
            response=_boundary(5, 5_000),
            source_timestamp_ms=8_000,
        ),
    )

    attempt.accept_pair(
        witness=pair,
        response_budget_ms=30_000,
        maximum_source_skew_ms=6_000,
        maximum_receive_skew_ms=4_000,
        classification=DecisionControlRefreshClassification.REFRESHED_WATCH_OR_ABSTAIN,
    )

    assert attempt.terminal_outcome is DecisionControlAttemptOutcome.UNKNOWN_CONSUMED
    assert attempt.terminal_unknown_reasons == (
        "COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED",
        "COMPONENT_PAIR_RECEIVE_SKEW_EXCEEDED",
    )


def test_decision_control_attempt_reports_every_non_timing_pair_blocker() -> None:
    origin = _boundary(1, 100)
    short_identity = "sha256:" + "6" * 64
    long_identity = "sha256:" + "7" * 64
    attempt = DecisionControlAttempt.schedule(
        selection_identity="sha256:" + "5" * 64,
        short_option_identity=short_identity,
        long_option_identity=long_identity,
        short_request_id=41,
        long_request_id=42,
        boundary=origin,
        short_instrument_name="BTC-SHORT",
        long_instrument_name="BTC-LONG",
    )
    attempt.take_request_intents()
    short_sent = _boundary(2, 110)
    long_sent = _boundary(3, 111)
    attempt.mark_sent(request_id=41, boundary=short_sent, send_budget_ms=30_000)
    attempt.mark_sent(request_id=42, boundary=long_sent, send_budget_ms=30_000)
    pair = component_pair_witness(
        short=_witness(
            role=ComponentLegRole.SHORT,
            request_id=41,
            option_identity=short_identity,
            instrument_name="BTC-SHORT",
            origin=origin,
            sent=short_sent,
            response=_boundary(4, 40_120),
            source_timestamp_ms=1_000,
            response_covers_full_quantity=False,
            payload_matches_request=False,
        ),
        long=_witness(
            role=ComponentLegRole.LONG,
            request_id=42,
            option_identity=long_identity,
            instrument_name="BTC-LONG",
            origin=origin,
            sent=long_sent,
            response=_boundary(5, 40_121),
            source_timestamp_ms=1_001,
        ),
    )

    attempt.accept_pair(
        witness=pair,
        response_budget_ms=30_000,
        maximum_source_skew_ms=6_000,
        maximum_receive_skew_ms=4_000,
        classification=DecisionControlRefreshClassification.REFRESHED_WATCH_OR_ABSTAIN,
    )

    assert attempt.terminal_outcome is DecisionControlAttemptOutcome.UNKNOWN_CONSUMED
    assert attempt.terminal_unknown_reasons == (
        "COMPONENT_PAIR_SHORT_PAYLOAD_REQUEST_MISMATCH",
        "COMPONENT_PAIR_SHORT_FULL_QUANTITY_NOT_COVERED",
        "COMPONENT_PAIR_SHORT_RESPONSE_BUDGET_EXCEEDED",
        "COMPONENT_PAIR_LONG_RESPONSE_BUDGET_EXCEEDED",
    )


@pytest.mark.parametrize(
    ("terminal_path", "expected_reason"),
    (
        ("send_budget", "COMPONENT_DECISION_CONTROL_SEND_BUDGET_EXCEEDED"),
        ("request_error", "COMPONENT_DECISION_CONTROL_REQUEST_ERROR"),
    ),
)
def test_decision_control_attempt_unknown_terminal_always_has_exact_reason(
    terminal_path: str,
    expected_reason: str,
) -> None:
    origin = _boundary(1, 100)
    attempt = DecisionControlAttempt.schedule(
        selection_identity="sha256:" + "5" * 64,
        short_option_identity="sha256:" + "6" * 64,
        long_option_identity="sha256:" + "7" * 64,
        short_request_id=41,
        long_request_id=42,
        boundary=origin,
        short_instrument_name="BTC-SHORT",
        long_instrument_name="BTC-LONG",
    )
    attempt.take_request_intents()
    if terminal_path == "send_budget":
        attempt.mark_sent(
            request_id=41,
            boundary=_boundary(2, 30_101),
            send_budget_ms=30_000,
        )
    else:
        attempt.fail_request(
            request_id=41,
            source_identity="sha256:" + "8" * 64,
            boundary=_boundary(2, 101),
            unknown_reason=expected_reason,
        )

    assert attempt.terminal_outcome is DecisionControlAttemptOutcome.UNKNOWN_CONSUMED
    assert attempt.terminal_unknown_reasons == (expected_reason,)
