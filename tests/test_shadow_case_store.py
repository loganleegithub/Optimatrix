from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

import pytest
import short_vol_underwriting.case_store as case_store_module
from options_domain import INVERSE_BTC, OptionType
from short_vol_radar import RadarScorePacket, ScoreBand, radar_bucket_episode_identity
from short_vol_radar.black import DecimalInterval
from short_vol_radar.policy import digest_policy_bytes, load_policy_bytes
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
from short_vol_underwriting import (
    UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY,
    ExitAcquisitionProfile,
    FixedContractShadowOwner,
    RuntimeBindings,
    ShadowCaseReadStatus,
    ShadowCaseSegmentStatus,
    ShadowCaseStore,
    ShadowCaseStoreError,
    ShadowStateError,
    ShadowStateStore,
    canonical_identity,
    load_policy_chain,
)
from short_vol_underwriting.constants import (
    INVERSE_BTC_POSITION_POLICY_IDENTITY as POSITION_POLICY,
)
from short_vol_underwriting.constants import (
    INVERSE_BTC_RADAR_POLICY_IDENTITY as RADAR_POLICY,
)
from short_vol_underwriting.constants import (
    INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY as UNDERWRITING_POLICY,
)
from short_vol_underwriting.control import selected_decision_batch_identity
from short_vol_underwriting.model import FactBoundary

ROOT = Path(__file__).resolve().parents[1]
CODE = "a" * 40
RUNTIME = "sha256:" + "b" * 64
COMPONENT_NON_CLAIMS = [
    "NOT_AN_ORDER",
    "NOT_A_FILL",
    "NOT_AN_ATOMIC_QUOTE",
    "NO_LIQUIDITY_RESERVATION",
    "ATOMIC_EXECUTABILITY_UNPROVEN",
]


def _exit_acquisition_profile() -> dict[str, object]:
    return ExitAcquisitionProfile.create(
        response_budget_ms=30_000,
        maximum_source_skew_ms=6_000,
        maximum_receive_skew_ms=4_000,
    ).as_object()


def _boundary(causal_seq: int) -> FactBoundary:
    return FactBoundary(
        code_identity=CODE,
        runtime_identity=RUNTIME,
        session_epoch=1,
        ingress_seq=causal_seq,
        received_monotonic_ms=100 + causal_seq,
        causal_seq=causal_seq,
    )


def _runtime_boundary(
    bindings: RuntimeBindings,
    causal_seq: int,
) -> FactBoundary:
    return FactBoundary(
        code_identity=bindings.code_identity,
        runtime_identity=bindings.runtime_identity,
        session_epoch=1,
        ingress_seq=causal_seq,
        received_monotonic_ms=1_000 + causal_seq,
        causal_seq=causal_seq,
    )


def _high_score_packet(
    *,
    boundary: FactBoundary,
    candidate_identity: str,
    activation_causal_seq: int,
) -> RadarScorePacket:
    bindings = RuntimeBindings(
        code_identity=CODE,
        runtime_identity=RUNTIME,
        radar_policy_identity=RADAR_POLICY,
        underwriting_policy_identity=UNDERWRITING_POLICY,
        position_policy_identity=POSITION_POLICY,
    )
    exact_policy = (ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json").read_bytes()
    policy = load_policy_bytes(exact_policy, digest_policy_bytes(exact_policy))

    def point(value: str) -> DecimalInterval:
        return DecimalInterval(Decimal(value), Decimal(value))

    score_inputs = RadarScoreInputs(
        stressed_richness=point("1.3"),
        stressed_executable_bid_iv=point("0.3"),
        local_same_type_mark_iv=Decimal("0.3"),
        surface_source_skew_ms=0,
        current_expiry_atm_mark_iv=Decimal("0.3"),
        adjacent_expiry_atm_mark_iv=Decimal("0.3"),
        term_source_skew_ms=0,
        adverse_semivariance_share=point("0"),
        jump_share=point("0"),
        target_spread_ticks=point("1"),
        bid_consumed_level_count=1,
        ask_consumed_level_count=1,
    )
    return build_radar_score_packet(
        policy_identity=policy.identity,
        fact_boundary=boundary.as_object(),
        bucket_key=RadarBucketKey(
            tte_band_id="six-to-twenty-four-hours",
            expiry_ms=1_786_150_800_000,
            option_type=OptionType.CALL,
            delta_bucket="0.15-0.25",
        ),
        leader_instrument_name="BTC-8AUG26-100000-C",
        result=compute_radar_score(policy.score_model, score_inputs),
        oi_diagnostic=compute_unsigned_oi_concentration(
            open_interest=None,
            option_gamma=None,
            bucket_total_unsigned_gamma_weight=None,
        ),
        stressed_richness=score_inputs.stressed_richness,
        leader_coverage=LeaderCoverage.COMPLETE,
        sampling_metadata=RadarSamplingMetadata(
            kind=SamplingKind.CANONICAL_HIGH,
            causal_batch_identity=selected_decision_batch_identity(
                bindings=bindings,
                activation_causal_seq=activation_causal_seq,
            ),
            designation_identity=candidate_identity,
        ),
    )


def _system(tmp_path: Path) -> tuple[ShadowStateStore, ShadowCaseStore, RuntimeBindings]:
    policies = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json",
        underwriting_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-underwriting.json",
        position_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-position.json",
        radar_identity=RADAR_POLICY,
        underwriting_identity=UNDERWRITING_POLICY,
        position_identity=POSITION_POLICY,
    )
    bindings = RuntimeBindings(
        code_identity=CODE,
        runtime_identity=RUNTIME,
        radar_policy_identity=RADAR_POLICY,
        underwriting_policy_identity=UNDERWRITING_POLICY,
        position_policy_identity=POSITION_POLICY,
    )
    cases = tmp_path / "cases"
    cases.mkdir()
    case_store = ShadowCaseStore(cases, bindings=bindings, policies=policies)
    state = ShadowStateStore(bindings=bindings, observer=case_store)
    return state, case_store, bindings


def _scope_identity(suffix: str) -> str:
    return canonical_identity("RadarScope", suffix)


def _component_source_refs(
    *,
    suffix: str,
    causal_seq: int,
    include_pair_timing_inputs: bool = False,
    leg_identities: tuple[str, str] | None = None,
    instrument_names: tuple[str, str] | None = None,
) -> list[dict[str, object]]:
    if not include_pair_timing_inputs:
        return [
            {
                "canonical_leg_role": role,
                "source_identity": canonical_identity("ComponentSource", suffix, role, causal_seq),
                "receipt_fact_boundary": _boundary(causal_seq).as_object(),
            }
            for role in ("SHORT", "LONG")
        ]
    if leg_identities is None or instrument_names is None:
        raise ValueError("entry component source refs require leg identities and names")
    origin = _boundary(causal_seq - 2)
    sent = _boundary(causal_seq - 1)
    response = _boundary(causal_seq)
    refs: list[dict[str, object]] = []
    for index, role in enumerate(("SHORT", "LONG")):
        request_id = 101 + index
        params = {"instrument_name": instrument_names[index], "depth": 10000}
        source_identity = canonical_identity(
            "RpcComponentLegRefreshSourceIdentity",
            response.runtime_identity,
            request_id,
            role,
            "public/get_order_book",
            leg_identities[index],
            params,
            origin.as_object(),
            sent.as_object(),
            1,
            11,
            1_000,
            response.as_object(),
        )
        refs.append(
            {
                "canonical_leg_role": role,
                "source_identity": source_identity,
                "receipt_fact_boundary": response.as_object(),
                "source_timestamp_ms": 1_000,
                "global_continuity_epoch": 1,
                "request_id": request_id,
                "owner_origin_boundary": origin.as_object(),
                "sent_boundary": sent.as_object(),
                "change_id": 11,
            }
        )
    return refs


def _component_legs(*, close: bool = False) -> list[dict[str, object]]:
    specifications = (
        (
            "SHORT",
            "BTC-8AUG26-100000-C",
            "BUY" if close else "SELL",
            "50" if close else "400",
            "51" if close else "399",
            "0.6375" if close else "3",
        ),
        (
            "LONG",
            "BTC-8AUG26-102000-C",
            "SELL" if close else "BUY",
            "20" if close else "100",
            "19" if close else "101",
            "0.2375" if close else "1.2625",
        ),
    )
    index = Decimal("100000")
    legs: list[dict[str, object]] = []
    for role, instrument_name, action, raw_price, stressed_price, fee in specifications:
        raw_native = Decimal(raw_price) / index
        stressed_native = Decimal(stressed_price) / index
        native_fee = Decimal(fee) / index
        legs.append(
            {
                "canonical_leg_role": role,
                "instrument_name": instrument_name,
                "action": action,
                "native_premium_currency": "BTC",
                "valuation_index_price": str(index),
                "raw_consumed_levels_native": [
                    {"price_native": str(raw_native), "amount_btc": "0.1"}
                ],
                "raw_vwap_native": str(raw_native),
                "stressed_consumed_levels_native": [
                    {"price_native": str(stressed_native), "amount_btc": "0.1"}
                ],
                "stressed_vwap_native": str(stressed_native),
                "native_fee_reserve": str(native_fee),
                "raw_consumed_levels": [{"price_usdc_per_btc": raw_price, "amount_btc": "0.1"}],
                "raw_vwap_usdc_per_btc": raw_price,
                "stressed_consumed_levels": [
                    {"price_usdc_per_btc": stressed_price, "amount_btc": "0.1"}
                ],
                "stressed_vwap_usdc_per_btc": stressed_price,
                "fee_reserve_usdc": fee,
            }
        )
    return legs


def _predicate_margin_vector() -> list[dict[str, object]]:
    return [
        {
            "predicate": predicate,
            "signed_margin": margin,
            "unit": unit,
            "passes": True,
        }
        for predicate, margin, unit in (
            ("POSITIVE_NET_ENTRY_CREDIT", "25.5375", "USD_EQUIVALENT"),
            ("CREDIT_ABOVE_FUTURE_COST_RESERVE", "13.5375", "USD_EQUIVALENT"),
            ("UNDERWRITING_RESERVED_LOSS_WITHIN_LIMIT", "63.5375", "USD_EQUIVALENT"),
            ("MINIMUM_NET_ENTRY_CREDIT", "10.5375", "USD_EQUIVALENT"),
            ("MINIMUM_NET_CREDIT_TO_PAYOFF_CAP", "0.0276875", "FRACTION"),
            ("ENTRY_CONSUMED_LEVEL_LIMIT", 9998, "LEVEL_COUNT"),
        )
    ]


def _seed_pre_shadow(
    state: ShadowStateStore,
    *,
    suffix: str = "test",
    start_seq: int = 1,
) -> tuple[str, str, str]:
    action_identity = canonical_identity("UnderwritingActionIdentity", f"{suffix}-action")
    candidate_identity = canonical_identity("CandidateActivationIdentity", f"{suffix}-candidate")
    availability_identity = canonical_identity("AvailabilityIdentity", f"{suffix}-availability")
    state.record(
        object_kind="UNDERWRITING_AVAILABILITY_EVALUATION",
        object_identity=availability_identity,
        fact_boundary=_boundary(start_seq),
        payload={
            "underwriting_availability_evaluation_identity": availability_identity,
            "radar_scope_or_short_leg_identity": _scope_identity(suffix),
            "consumed_availability_fact_fingerprint": canonical_identity(
                "AvailabilityFingerprint", suffix
            ),
            "availability": "EVALUABLE",
            "availability_evaluation_fact_boundary": _boundary(start_seq).as_object(),
            "unknown_reasons": [],
        },
    )
    state.record(
        object_kind="UNDERWRITING_ACTION",
        object_identity=action_identity,
        fact_boundary=_boundary(start_seq + 1),
        payload={
            "underwriting_action_identity": action_identity,
            "underwriting_availability_evaluation_identity": availability_identity,
            "underwriting_opportunity_key_identity": canonical_identity("Opportunity", suffix),
            "consumed_economic_fact_fingerprint": canonical_identity("Economics", suffix),
            "economic_action": "CANDIDATE",
            "failed_predicates": [],
            "predicate_margin_vector": _predicate_margin_vector(),
            "evaluation_fact_boundary": _boundary(start_seq + 1).as_object(),
        },
    )
    state.record(
        object_kind="CANDIDATE_ACTIVATION",
        object_identity=candidate_identity,
        fact_boundary=_boundary(start_seq + 2),
        payload={
            "candidate_identity": candidate_identity,
            "underwriting_action_identity": action_identity,
            "underwriting_position_slot_key_identity": canonical_identity("Slot", suffix),
            "candidate_activation_fact_boundary": _boundary(start_seq + 2).as_object(),
        },
    )
    return availability_identity, action_identity, candidate_identity


def _open_case(
    state: ShadowStateStore,
    candidate_identity: str,
    *,
    suffix: str = "one",
    causal_seq: int = 4,
) -> str:
    entry_identity = canonical_identity("ShadowEntryIdentity", suffix)
    entry_economic_fingerprint = canonical_identity("EntryEconomicFingerprint", suffix)
    entry_action_identity = canonical_identity(
        "CaseOpenRefreshedUnderwritingActionIdentity",
        candidate_identity,
        entry_economic_fingerprint,
        "CANDIDATE",
        UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY,
        1,
        _boundary(causal_seq).as_object(),
    )
    leg_identities = (
        canonical_identity("Leg", f"{suffix}-short"),
        canonical_identity("Leg", f"{suffix}-long"),
    )
    instrument_names = (
        "BTC-8AUG26-100000-C",
        "BTC-8AUG26-102000-C",
    )
    entry_source_refs = _component_source_refs(
        suffix=f"{suffix}-entry",
        causal_seq=causal_seq,
        include_pair_timing_inputs=True,
        leg_identities=leg_identities,
        instrument_names=instrument_names,
    )
    entry_pair_identity = canonical_identity(
        "ComponentBookPairWitnessIdentity",
        entry_source_refs[0]["source_identity"],
        entry_source_refs[1]["source_identity"],
        _boundary(causal_seq).as_object(),
    )
    activation_causal_seq = causal_seq - 1
    selection_packet = _high_score_packet(
        boundary=_boundary(activation_causal_seq),
        candidate_identity=candidate_identity,
        activation_causal_seq=activation_causal_seq,
    )
    refresh_packet = _high_score_packet(
        boundary=_boundary(causal_seq),
        candidate_identity=candidate_identity,
        activation_causal_seq=activation_causal_seq,
    )
    active_episode_identity = radar_bucket_episode_identity(
        runtime_identity=RUNTIME,
        policy_identity=RADAR_POLICY,
        bucket_key=selection_packet.bucket_key,
        leader_instrument_name=selection_packet.leader_instrument_name,
        score_band=ScoreBand.HIGH,
        activation_causal_seq=activation_causal_seq,
    )
    state.record(
        object_kind="SHADOW_ENTRY",
        object_identity=entry_identity,
        fact_boundary=_boundary(causal_seq),
        payload={
            "shadow_entry_identity": entry_identity,
            "enrollment_kind": "ADMITTED_SHADOW_TRADE",
            "candidate_identity": candidate_identity,
            "entry_underwriting_action_identity": entry_action_identity,
            "entry_underwriting_economic_action": "CANDIDATE",
            "entry_underwriting_consumed_economic_fact_fingerprint": (entry_economic_fingerprint),
            "entry_underwriting_failed_predicates": [],
            "entry_underwriting_predicate_margin_vector": _predicate_margin_vector(),
            "entry_underwriting_protective_leg_selection_rule_identity": (
                UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY
            ),
            "entry_underwriting_candidate_protective_leg_count": 1,
            "entry_underwriting_decision_fact_boundary": _boundary(causal_seq).as_object(),
            "selection_score_packet": selection_packet.as_object(),
            "entry_refresh_score_packet": refresh_packet.as_object(),
            "active_episode_identity": active_episode_identity,
            "radar_research_review_identity": None,
            "radar_activation_causal_seq": activation_causal_seq,
            "radar_scope_identity": _scope_identity(suffix),
            "execution_model": "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL",
            "product_spec_identity": INVERSE_BTC.identity,
            "product_name": INVERSE_BTC.name.value,
            "native_premium_currency": INVERSE_BTC.native_premium_currency,
            "settlement_currency": INVERSE_BTC.settlement_currency,
            "valuation_currency": INVERSE_BTC.valuation_currency,
            "price_index": INVERSE_BTC.price_index,
            "component_state": "COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE",
            "atomic_state_diagnostic": "NO_ACTIVE_COMBO",
            "canonical_leg_identities": [
                *leg_identities,
            ],
            "short_leg_instrument_name": instrument_names[0],
            "long_leg_instrument_name": instrument_names[1],
            "expiry_ms": 1_786_150_800_000,
            "option_type": "call",
            "short_strike_usdc_per_btc": "100000",
            "long_strike_usdc_per_btc": "102000",
            "entry_direction": "SELL",
            "full_quantity_btc": "0.1",
            "entry_component_pair_identity": entry_pair_identity,
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
            "entry_component_quote_source_refs": entry_source_refs,
            "entry_component_legs": _component_legs(),
            "native_gross_entry_credit": "0.000298",
            "native_entry_fee_reserve": "0.000042625",
            "native_net_entry_credit": "0.000255375",
            "entry_index_usdc_per_btc": "100000",
            "entry_index_source_ref": {
                "source_identity": canonical_identity("IndexSource", suffix),
                "receipt_fact_boundary": _boundary(causal_seq).as_object(),
            },
            "entry_short_leg_mark_iv_fraction": "0.5",
            "entry_short_leg_mark_iv_source_ref": {
                "source_identity": canonical_identity("TickerSource", suffix),
                "receipt_fact_boundary": _boundary(causal_seq).as_object(),
            },
            "entry_valuation_index_price": "100000",
            "gross_entry_credit_usdc": "29.8",
            "entry_fee_reserve_usdc": "4.2625",
            "net_entry_credit_usdc": "25.5375",
            "width_usdc_per_btc": "2000",
            "payoff_cap_usdc": "200",
            "contractual_payoff_max_loss_ex_fees_usdc": "170.2",
            "entry_fee_reserved_payoff_loss_usdc": "174.4625",
            "future_cost_reserve_usdc": "12",
            "underwriting_reserved_loss_usdc": "186.4625",
            "non_claims": COMPONENT_NON_CLAIMS,
        },
    )
    return entry_identity


def _record_first_close_and_schedule(
    state: ShadowStateStore,
    entry_identity: str,
    *,
    suffix: str,
    causal_seq: int,
) -> str:
    close_identity = canonical_identity("PositionActionIdentity", suffix)
    state.record(
        object_kind="POSITION_ACTION",
        object_identity=close_identity,
        fact_boundary=_boundary(causal_seq),
        payload={
            "position_action_identity": close_identity,
            "shadow_entry_identity": entry_identity,
            "serialized_action": "CLOSE",
            "ordered_predicate_truth_vector": ["FALSE"] * 8 + ["TRUE"],
            "ordered_latched_close_reason_vector": ["ECONOMIC_EXIT_BOUNDARY_REACHED"],
            "primary_close_reason": "ECONOMIC_EXIT_BOUNDARY_REACHED",
            "secondary_close_reasons": [],
            "first_latched_close_action_identity": close_identity,
            "exit_acquisition_profile": _exit_acquisition_profile(),
            "action_fact_boundary": _boundary(causal_seq).as_object(),
        },
    )
    request_ids = [41, 42]
    request_params = [
        {"instrument_name": "BTC-8AUG26-100000-C", "depth": 10000},
        {"instrument_name": "BTC-8AUG26-102000-C", "depth": 10000},
    ]
    schedule_identity = canonical_identity(
        "ScheduledComponentPostCloseAttemptIdentity",
        entry_identity,
        close_identity,
        request_ids,
        "public/get_order_book",
        request_params,
        _boundary(causal_seq).as_object(),
    )
    state.record(
        object_kind="POST_CLOSE_ATTEMPT_SCHEDULED",
        object_identity=schedule_identity,
        fact_boundary=_boundary(causal_seq),
        payload={
            "scheduled_post_close_attempt_identity": schedule_identity,
            "shadow_entry_identity": entry_identity,
            "first_latched_close_action_identity": close_identity,
            "request_id_or_marker": request_ids,
            "execution_model": "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL",
            "request_method": "public/get_order_book",
            "request_params": request_params,
            "schedule_fact_boundary": _boundary(causal_seq).as_object(),
        },
    )
    return close_identity


def _mature_unknown_case(
    state: ShadowStateStore,
    entry_identity: str,
    *,
    suffix: str,
    causal_seq: int,
) -> None:
    outcome_identity = canonical_identity("ShadowOutcomeIdentity", suffix)
    state.record(
        object_kind="SHADOW_OUTCOME",
        object_identity=outcome_identity,
        fact_boundary=_boundary(causal_seq),
        payload={
            "shadow_outcome_identity": outcome_identity,
            "shadow_entry_identity": entry_identity,
            "terminal_state": "MATURE_UNKNOWN",
            "selected_exit_identity": None,
            "first_latched_close_action_identity": None,
            "gross_close_cashflow_usdc": None,
            "close_fee_reserve_usdc": None,
            "net_close_cashflow_usdc": None,
            "gross_pnl_usdc": None,
            "total_public_fee_reserve_usdc": None,
            "net_pnl_after_public_standard_fee_reserve_usdc": None,
            "net_loss_usdc": None,
            "native_gross_close_cashflow": None,
            "native_close_fee_reserve": None,
            "native_net_close_cashflow": None,
            "native_gross_pnl": None,
            "native_total_fee_reserve": None,
            "native_net_pnl": None,
            "close_valuation_index_price": None,
            "boundary_valued_net_pnl_usd": None,
            "exit_valued_native_net_pnl_usd": None,
            "economic_availability": "UNKNOWN",
            "close_component_pair_identity": None,
            "close_component_quote_source_refs": [],
            "close_component_legs": [],
            "censor_mask": [],
            "non_claims": COMPONENT_NON_CLAIMS,
        },
    )


def _legacy_unknown_outcome(
    opened: Mapping[str, object],
    *,
    suffix: str,
    causal_seq: int,
    terminal_state: str,
    first_close_identity: str | None = None,
) -> dict[str, object]:
    return {
        "record_kind": "SHADOW_CASE_OUTCOME",
        "schema_version": opened["schema_version"],
        "case_id": opened["case_id"],
        "code_identity": opened["code_identity"],
        "runtime_identity": opened["runtime_identity"],
        "radar_policy_identity": opened["radar_policy_identity"],
        "underwriting_policy_identity": opened["underwriting_policy_identity"],
        "position_policy_identity": opened["position_policy_identity"],
        "outcome_fact_boundary": _boundary(causal_seq).as_object(),
        "shadow_outcome_identity": canonical_identity("ShadowOutcomeIdentity", suffix),
        "terminal_state": terminal_state,
        "selected_exit_identity": None,
        "first_latched_close_action_identity": first_close_identity,
        "gross_close_cashflow_usd": None,
        "close_fee_reserve_usd": None,
        "net_close_cashflow_usd": None,
        "gross_pnl_usd": None,
        "total_public_fee_reserve_usd": None,
        "net_pnl_after_public_standard_fee_reserve_usd": None,
        "net_loss_usd": None,
        "native_outcome_economics": {
            "native_gross_close_cashflow": None,
            "native_close_fee_reserve": None,
            "native_net_close_cashflow": None,
            "native_gross_pnl": None,
            "native_total_fee_reserve": None,
            "native_net_pnl": None,
            "close_valuation_index_price": None,
            "boundary_valued_net_pnl_usd": None,
            "exit_valued_native_net_pnl_usd": None,
        },
        "economic_availability": "UNKNOWN",
        "close_component_pair_identity": None,
        "close_component_quote_source_refs": [],
        "close_component_legs": [],
        "censor_mask": (
            ["STOP"]
            if terminal_state == "CENSORED_AT_STOP"
            else ["FAILURE"]
            if terminal_state == "CENSORED_AT_FAILURE"
            else []
        ),
        "non_claims": COMPONENT_NON_CLAIMS,
    }


def _censor_case(
    state: ShadowStateStore,
    entry_identity: str,
    *,
    suffix: str,
    causal_seq: int,
) -> None:
    outcome_identity = canonical_identity("ShadowOutcomeIdentity", suffix)
    state.record(
        object_kind="SHADOW_OUTCOME",
        object_identity=outcome_identity,
        fact_boundary=_boundary(causal_seq),
        payload={
            "shadow_outcome_identity": outcome_identity,
            "shadow_entry_identity": entry_identity,
            "terminal_state": "CENSORED_AT_STOP",
            "selected_exit_identity": None,
            "first_latched_close_action_identity": None,
            "gross_close_cashflow_usdc": None,
            "close_fee_reserve_usdc": None,
            "net_close_cashflow_usdc": None,
            "gross_pnl_usdc": None,
            "total_public_fee_reserve_usdc": None,
            "net_pnl_after_public_standard_fee_reserve_usdc": None,
            "net_loss_usdc": None,
            "native_gross_close_cashflow": None,
            "native_close_fee_reserve": None,
            "native_net_close_cashflow": None,
            "native_gross_pnl": None,
            "native_total_fee_reserve": None,
            "native_net_pnl": None,
            "close_valuation_index_price": None,
            "boundary_valued_net_pnl_usd": None,
            "exit_valued_native_net_pnl_usd": None,
            "economic_availability": "UNKNOWN",
            "close_component_pair_identity": None,
            "close_component_quote_source_refs": [],
            "close_component_legs": [],
            "censor_mask": ["STOP"],
            "non_claims": COMPONENT_NON_CLAIMS,
        },
    )


def test_pre_shadow_state_is_in_memory_only_even_under_repeated_updates(tmp_path: Path) -> None:
    state, case_store, _bindings = _system(tmp_path)
    _availability, action_identity, candidate_identity = _seed_pre_shadow(state)
    action = state.get_object("UNDERWRITING_ACTION", action_identity)
    candidate = state.get_object("CANDIDATE_ACTIVATION", candidate_identity)
    assert action is not None and candidate is not None
    action_payload = action["payload"]
    candidate_payload = candidate["payload"]
    assert isinstance(action_payload, Mapping)
    assert isinstance(candidate_payload, Mapping)

    for _ in range(100_000):
        state.record(
            object_kind="UNDERWRITING_ACTION",
            object_identity=action_identity,
            fact_boundary=_boundary(2),
            payload=action_payload,
        )
        state.record(
            object_kind="CANDIDATE_ACTIVATION",
            object_identity=candidate_identity,
            fact_boundary=_boundary(3),
            payload=candidate_payload,
        )

    assert case_store.case_count == 0
    assert list((tmp_path / "cases").iterdir()) == []


def test_shadow_state_exposes_each_new_record_once_without_a_history_journal(
    tmp_path: Path,
) -> None:
    state, _case_store, _bindings = _system(tmp_path)
    assert state.take_pending_records() == ()

    _seed_pre_shadow(state)
    first_revision = state.revision
    first = state.take_pending_records()
    assert len(first) == first_revision == 3
    assert state.take_pending_records() == ()

    candidate = first[-1]
    candidate_payload = candidate["payload"]
    assert isinstance(candidate_payload, Mapping)
    state.record(
        object_kind=str(candidate["object_kind"]),
        object_identity=str(candidate["object_identity"]),
        fact_boundary=_boundary(3),
        payload=candidate_payload,
    )
    assert state.revision == first_revision
    assert state.take_pending_records() == ()


def test_shadow_entry_opens_exactly_one_minimal_case(tmp_path: Path) -> None:
    state, case_store, _bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)

    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)

    assert case_id is not None
    case_directory = tmp_path / "cases" / case_id.removeprefix("sha256:")
    assert sorted(path.name for path in case_directory.iterdir()) == ["opened.json", "segments"]
    assert sorted(path.name for path in (case_directory / "segments" / "0").iterdir()) == [
        "opened.json"
    ]
    read = case_store.read_case(case_id, runtime_active=True)
    assert read.status is ShadowCaseReadStatus.OPEN
    inactive_read = case_store.read_case(case_id)
    assert inactive_read.segments[-1].status is ShadowCaseSegmentStatus.INCOMPLETE_UNCLEAN_EXIT
    offline_bindings = RuntimeBindings(
        code_identity=_bindings.code_identity,
        runtime_identity="sha256:" + "d" * 64,
        radar_policy_identity=_bindings.radar_policy_identity,
        underwriting_policy_identity=_bindings.underwriting_policy_identity,
        position_policy_identity=_bindings.position_policy_identity,
    )
    offline_reader = ShadowCaseStore(
        tmp_path / "cases",
        bindings=offline_bindings,
        policies=case_store.policies,
    )
    asserted_active = offline_reader.read_case(case_id, runtime_active=True)
    assert asserted_active.segments[-1].status is ShadowCaseSegmentStatus.OPEN
    assert read.opened["shadow_entry_identity"] == entry_identity
    underwriting = read.opened["underwriting"]
    assert isinstance(underwriting, Mapping)
    assert underwriting["action"] == "CANDIDATE"
    assert (
        underwriting["protective_leg_selection_rule_identity"]
        == UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY
    )
    assert underwriting["candidate_protective_leg_count"] == 1
    current_entry = state.get_object("SHADOW_ENTRY", entry_identity)
    assert current_entry is not None
    current_payload = current_entry["payload"]
    assert isinstance(current_payload, Mapping)
    assert current_payload["origin_runtime_identity"] == _bindings.runtime_identity
    assert (
        current_payload["current_segment_identity"] == read.segments[0].opened["segment_identity"]
    )
    assert current_payload["current_segment_sequence"] == 0
    assert current_payload["observation_quality"] == "CONTINUOUS"
    assert current_payload["gap_count"] == 0
    assert current_payload["qualification_eligible"] is True
    assert current_payload["tracking_state"] == "ACTIVE"
    assert current_payload["post_close_attempt_state"] == "NOT_SCHEDULED"


def test_active_admitted_entry_scans_and_opens_a_gapped_recovery_segment(
    tmp_path: Path,
) -> None:
    state, case_store, bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None

    restarted_bindings = RuntimeBindings(
        code_identity=bindings.code_identity,
        runtime_identity="sha256:" + "c" * 64,
        radar_policy_identity=bindings.radar_policy_identity,
        underwriting_policy_identity=bindings.underwriting_policy_identity,
        position_policy_identity=bindings.position_policy_identity,
    )
    restarted = ShadowCaseStore(
        tmp_path / "cases",
        bindings=restarted_bindings,
        policies=case_store.policies,
    )

    (recoverable,) = restarted.scan_active_admitted()
    assert recoverable.case_id == case_id
    assert recoverable.shadow_entry_identity == entry_identity
    assert recoverable.latest_segment_sequence == 0
    assert recoverable.predecessor_segment_state.value == "INCOMPLETE_UNCLEAN_EXIT"
    assert recoverable.entry_terms.index_usdc_per_btc == Decimal("100000")
    assert recoverable.entry_terms.index_source is not None
    assert recoverable.entry_terms.index_source.as_ref() == {
        "source_identity": canonical_identity("IndexSource", "one"),
        "receipt_fact_boundary": _boundary(4).as_object(),
    }
    assert recoverable.entry_terms.short_mark_iv_fraction == Decimal("0.5")
    assert recoverable.entry_terms.ticker_source is not None
    assert recoverable.entry_terms.ticker_source.as_ref() == {
        "source_identity": canonical_identity("TickerSource", "one"),
        "receipt_fact_boundary": _boundary(4).as_object(),
    }
    assert not hasattr(recoverable, "segments")
    with pytest.raises(TypeError):
        recoverable.entry_payload["origin_case_id"] = "tampered"  # type: ignore[index]
    expected_baseline = {
        "entry_index_usd_per_btc": "100000",
        "entry_index_source_ref": {
            "source_identity": canonical_identity("IndexSource", "one"),
            "receipt_fact_boundary": _boundary(4).as_object(),
        },
        "entry_short_leg_mark_iv_fraction": "0.5",
        "entry_short_leg_mark_iv_source_ref": {
            "source_identity": canonical_identity("TickerSource", "one"),
            "receipt_fact_boundary": _boundary(4).as_object(),
        },
    }
    assert (
        case_store.read_case(case_id).segments[0].opened["entry_position_baseline"]
        == expected_baseline
    )

    current = restarted.open_recovery_segment(
        case_id,
        adoption_fact_boundary=_runtime_boundary(restarted_bindings, 1),
    )
    assert current.latest_segment_sequence == 1
    assert current.observation_quality.value == "GAPPED"
    assert current.gap_count == 1
    assert current.qualification_eligible is False
    assert current.predecessor_segment_state.value == "INCOMPLETE_UNCLEAN_EXIT"
    assert current.first_close_state == "NOT_LATCHED"
    assert current.attempt_state == "NOT_SCHEDULED"
    assert current.adoption_case_boundary.segment_sequence == 1
    assert restarted.read_case(case_id).segments[-1].opened["entry_position_baseline"] is None

    with pytest.raises(ShadowCaseStoreError, match="already owns"):
        restarted.open_recovery_segment(
            case_id,
            adoption_fact_boundary=_runtime_boundary(restarted_bindings, 2),
        )


def test_admitted_stop_closes_only_current_segment_and_bulk_close_is_idempotent(
    tmp_path: Path,
) -> None:
    state, case_store, bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None

    boundary = _boundary(5)
    first = case_store.close_active_admitted_segments(
        boundary=boundary,
        terminal_state="CENSORED_AT_STOP",
    )
    second = case_store.close_active_admitted_segments(
        boundary=boundary,
        terminal_state="CENSORED_AT_STOP",
    )
    assert len(first) == len(second) == 1
    case_directory = tmp_path / "cases" / case_id.removeprefix("sha256:")
    assert not (case_directory / "outcome.json").exists()
    assert (
        json.loads((case_directory / "segments" / "0" / "closed.json").read_text(encoding="utf-8"))[
            "terminal_state"
        ]
        == "CENSORED_AT_STOP"
    )
    assert case_store.case_id_for_entry(entry_identity) == case_id
    assert case_store.active_case_count == 1

    with pytest.raises(ShadowCaseStoreError, match="conflicting"):
        case_store.close_active_admitted_segments(
            boundary=_boundary(6),
            terminal_state="CENSORED_AT_FAILURE",
        )

    restarted_bindings = RuntimeBindings(
        code_identity=bindings.code_identity,
        runtime_identity="sha256:" + "f" * 64,
        radar_policy_identity=bindings.radar_policy_identity,
        underwriting_policy_identity=bindings.underwriting_policy_identity,
        position_policy_identity=bindings.position_policy_identity,
    )
    restarted = ShadowCaseStore(
        tmp_path / "cases",
        bindings=restarted_bindings,
        policies=case_store.policies,
    )
    (recoverable,) = restarted.scan_active_admitted()
    assert recoverable.predecessor_segment_state.value == "CENSORED_AT_STOP"
    recovered = restarted.open_recovery_segment(
        case_id,
        adoption_fact_boundary=_runtime_boundary(restarted_bindings, 1),
    )
    assert recovered.predecessor_segment_state.value == "CENSORED_AT_STOP"
    assert recovered.gap_count == 1


def test_stable_admitted_censored_outcome_is_rejected_instead_of_mapped(
    tmp_path: Path,
) -> None:
    state, case_store, _bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None

    with pytest.raises(ShadowCaseStoreError, match="cannot emit a censored aggregate Outcome"):
        _censor_case(state, entry_identity, suffix="stop", causal_seq=5)

    case_directory = tmp_path / "cases" / case_id.removeprefix("sha256:")
    assert not (case_directory / "outcome.json").exists()
    assert not (case_directory / "segments" / "0" / "closed.json").exists()
    read = case_store.read_case(case_id)
    assert read.status is ShadowCaseReadStatus.OPEN
    assert read.segments[-1].status.value == "INCOMPLETE_UNCLEAN_EXIT"


def test_new_case_directory_is_never_visible_with_only_opened_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _case_store, _bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    original_rename = Path.rename

    def fail_case_publish(path: Path, target: Path) -> Path:
        if path.name.startswith(".case-"):
            raise OSError("simulated crash before directory publication")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_case_publish)
    with pytest.raises(ShadowCaseStoreError, match="atomically publish"):
        _open_case(state, candidate_identity)

    assert list((tmp_path / "cases").iterdir()) == []


def test_recovery_segment_crash_before_publication_leaves_no_numeric_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, case_store, bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None
    restarted_bindings = RuntimeBindings(
        code_identity=bindings.code_identity,
        runtime_identity="sha256:" + "7" * 64,
        radar_policy_identity=bindings.radar_policy_identity,
        underwriting_policy_identity=bindings.underwriting_policy_identity,
        position_policy_identity=bindings.position_policy_identity,
    )
    restarted = ShadowCaseStore(
        tmp_path / "cases",
        bindings=restarted_bindings,
        policies=case_store.policies,
    )
    restarted.scan_active_admitted()
    original_rename = Path.rename

    def fail_segment_publish(path: Path, target: Path) -> Path:
        if path.name.startswith(".segment-"):
            raise OSError("simulated crash before Segment publication")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_segment_publish)
    with pytest.raises(ShadowCaseStoreError, match="atomically publish Observation Segment"):
        restarted.open_recovery_segment(
            case_id,
            adoption_fact_boundary=_runtime_boundary(restarted_bindings, 1),
        )

    segments = tmp_path / "cases" / case_id.removeprefix("sha256:") / "segments"
    assert sorted(path.name for path in segments.iterdir()) == ["0"]
    assert restarted.read_case(case_id).segments[-1].sequence == 0


def test_recovery_segment_is_complete_if_parent_fsync_fails_after_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, case_store, bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None
    restarted_bindings = RuntimeBindings(
        code_identity=bindings.code_identity,
        runtime_identity="sha256:" + "8" * 64,
        radar_policy_identity=bindings.radar_policy_identity,
        underwriting_policy_identity=bindings.underwriting_policy_identity,
        position_policy_identity=bindings.position_policy_identity,
    )
    restarted = ShadowCaseStore(
        tmp_path / "cases",
        bindings=restarted_bindings,
        policies=case_store.policies,
    )
    restarted.scan_active_admitted()
    segments = tmp_path / "cases" / case_id.removeprefix("sha256:") / "segments"
    original_fsync = case_store_module._fsync_directory

    def fail_after_segment_rename(path: Path) -> None:
        if path == segments and (segments / "1" / "opened.json").is_file():
            raise OSError("simulated crash after Segment publication")
        original_fsync(path)

    monkeypatch.setattr(case_store_module, "_fsync_directory", fail_after_segment_rename)
    with pytest.raises(ShadowCaseStoreError, match="atomically publish Observation Segment"):
        restarted.open_recovery_segment(
            case_id,
            adoption_fact_boundary=_runtime_boundary(restarted_bindings, 1),
        )

    assert sorted(path.name for path in segments.iterdir()) == ["0", "1"]
    assert (segments / "1" / "opened.json").is_file()
    assert restarted.read_case(case_id).segments[-1].sequence == 1


def test_segment_scanner_ignores_only_plain_exact_staging_directories(tmp_path: Path) -> None:
    state, case_store, _bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None
    segments = tmp_path / "cases" / case_id.removeprefix("sha256:") / "segments"
    residue = segments / f".segment-{'3' * 32}.tmp"
    residue.mkdir()
    (residue / "opened.json").write_text("interrupted Segment", encoding="utf-8")

    assert case_store.read_case(case_id).segments[-1].sequence == 0

    invalid = segments / f".segment-{'4' * 32}.tmp"
    invalid.symlink_to(residue, target_is_directory=True)
    with pytest.raises(ShadowCaseStoreError, match="staging path"):
        case_store.read_case(case_id)


def test_case_reader_rejects_unexpected_nested_opened_fields(tmp_path: Path) -> None:
    state, case_store, _bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None
    opened_path = tmp_path / "cases" / case_id.removeprefix("sha256:") / "opened.json"
    opened = json.loads(opened_path.read_text(encoding="utf-8"))
    opened["structure"]["unexpected_history"] = []
    opened_path.write_text(json.dumps(opened), encoding="utf-8")

    with pytest.raises(ShadowCaseStoreError, match="key set"):
        case_store.read_case(case_id)


@pytest.mark.parametrize(
    ("tamper", "expected_error"),
    (
        ("pair_receive_skew", "receive skew"),
        ("pair_source_skew", "source skew"),
        ("pair_continuity", "continuity evidence"),
        ("pair_limit", "Policy"),
        ("pair_identity", "pair identity mismatch"),
        ("source_identity", "source identity mismatch"),
        ("predicate_name", "predicate order/unit"),
        ("predicate_passes", "contradicts signed_margin"),
        ("failed_predicates", "failed predicates"),
        ("signed_margin", "do not match entry economics"),
        ("selector_rule", "selection rule identity mismatch"),
        ("candidate_leg_count", "action identity mismatch"),
        ("selection_packet_extra_key", "exact keys"),
        ("selection_packet_boundary", "boundary/order"),
        ("selection_packet_score", "disagrees"),
        ("selection_packet_band", "disagrees"),
        ("selection_packet_aggregates", "disagrees"),
        ("selection_packet_contribution", "disagrees"),
        ("sampling_metadata_drift", "identical sampling metadata"),
    ),
)
def test_case_reader_rejects_tampered_entry_pair_and_underwriting_truth(
    tmp_path: Path,
    tamper: str,
    expected_error: str,
) -> None:
    state, case_store, _bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None
    opened_path = tmp_path / "cases" / case_id.removeprefix("sha256:") / "opened.json"
    opened = json.loads(opened_path.read_text(encoding="utf-8"))
    if tamper == "pair_receive_skew":
        opened["structure"]["entry_component_pair_timing"]["receive_skew_ms"] = 1
    elif tamper == "pair_source_skew":
        opened["structure"]["entry_component_pair_timing"]["source_timestamp_skew_ms"] = 1
    elif tamper == "pair_continuity":
        opened["structure"]["entry_component_pair_timing"]["global_continuity_epochs"] = [2, 2]
    elif tamper == "pair_limit":
        opened["structure"]["entry_component_pair_limits"]["maximum_receive_skew_ms"] = 4_001
    elif tamper == "pair_identity":
        opened["structure"]["entry_component_pair_identity"] = "sha256:" + "c" * 64
    elif tamper == "source_identity":
        opened["structure"]["entry_component_quote_source_refs"][0]["source_identity"] = (
            "sha256:" + "d" * 64
        )
    elif tamper == "predicate_name":
        opened["underwriting"]["predicate_margin_vector"][0]["predicate"] = "NOT_CANONICAL"
    elif tamper == "predicate_passes":
        opened["underwriting"]["predicate_margin_vector"][0]["passes"] = False
    elif tamper == "failed_predicates":
        opened["underwriting"]["failed_predicates"] = ["NON_POSITIVE_NET_ENTRY_CREDIT"]
    elif tamper == "signed_margin":
        opened["underwriting"]["predicate_margin_vector"][0]["signed_margin"] = "999"
    elif tamper == "selector_rule":
        opened["underwriting"]["protective_leg_selection_rule_identity"] = "sha256:" + "e" * 64
    elif tamper == "candidate_leg_count":
        opened["underwriting"]["candidate_protective_leg_count"] = 2
    elif tamper == "selection_packet_extra_key":
        opened["selection_score_packet"]["unexpected"] = True
    elif tamper == "selection_packet_boundary":
        opened["selection_score_packet"]["fact_boundary"] = opened["opened_fact_boundary"]
    elif tamper == "selection_packet_score":
        opened["selection_score_packet"]["result"]["score"] = {
            "lower": "1",
            "upper": "1",
        }
    elif tamper == "selection_packet_band":
        opened["selection_score_packet"]["result"]["band"] = "LOW"
    elif tamper == "selection_packet_aggregates":
        opened["selection_score_packet"]["result"]["premium_evidence"] = {
            "lower": "0.1",
            "upper": "0.1",
        }
        opened["selection_score_packet"]["result"]["risk_quality"] = {
            "lower": "0.1",
            "upper": "0.1",
        }
    elif tamper == "selection_packet_contribution":
        opened["selection_score_packet"]["result"]["factors"][0]["weighted_contribution"] = {
            "lower": "0.1",
            "upper": "0.1",
        }
    elif tamper == "sampling_metadata_drift":
        opened["entry_refresh_score_packet"]["sampling_metadata"]["designation_identity"] = (
            canonical_identity("SamplingDesignation", "tampered")
        )
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(tamper)
    opened_path.write_text(json.dumps(opened), encoding="utf-8")

    with pytest.raises(ShadowCaseStoreError, match=expected_error):
        case_store.read_case(case_id)


def test_first_close_and_known_outcome_complete_case_with_recomputable_economics(
    tmp_path: Path,
) -> None:
    state, case_store, _bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None

    close_identity = _record_first_close_and_schedule(
        state,
        entry_identity,
        suffix="first-close",
        causal_seq=5,
    )
    outcome_identity = canonical_identity("ShadowOutcomeIdentity", "known")
    state.record(
        object_kind="SHADOW_OUTCOME",
        object_identity=outcome_identity,
        fact_boundary=_boundary(6),
        payload={
            "shadow_outcome_identity": outcome_identity,
            "shadow_entry_identity": entry_identity,
            "terminal_state": "MATURE_KNOWN",
            "selected_exit_identity": canonical_identity("ShadowExit", "one"),
            "first_latched_close_action_identity": close_identity,
            "gross_close_cashflow_usdc": "-3.2",
            "close_fee_reserve_usdc": "0.875",
            "net_close_cashflow_usdc": "-4.075",
            "gross_pnl_usdc": "26.6",
            "total_public_fee_reserve_usdc": "5.1375",
            "net_pnl_after_public_standard_fee_reserve_usdc": "21.4625",
            "net_loss_usdc": "0",
            "native_gross_close_cashflow": "-0.000032",
            "native_close_fee_reserve": "0.00000875",
            "native_net_close_cashflow": "-0.00004075",
            "native_gross_pnl": "0.000266",
            "native_total_fee_reserve": "0.000051375",
            "native_net_pnl": "0.000214625",
            "close_valuation_index_price": "100000",
            "boundary_valued_net_pnl_usd": "21.4625",
            "exit_valued_native_net_pnl_usd": "21.4625",
            "economic_availability": "KNOWN",
            "close_component_pair_identity": canonical_identity("ComponentPair", "one", "close"),
            "close_component_quote_source_refs": _component_source_refs(
                suffix="one-close",
                causal_seq=6,
            ),
            "close_component_legs": _component_legs(close=True),
            "censor_mask": [],
            "non_claims": COMPONENT_NON_CLAIMS,
        },
    )

    case_directory = tmp_path / "cases" / case_id.removeprefix("sha256:")
    assert sorted(path.name for path in case_directory.iterdir()) == [
        "first-close.json",
        "opened.json",
        "outcome.json",
        "segments",
    ]
    read = case_store.read_case(case_id)
    assert read.status is ShadowCaseReadStatus.COMPLETE
    assert read.first_close is not None
    assert read.outcome is not None
    assert read.outcome["net_pnl_after_public_standard_fee_reserve_usd"] == "21.4625"

    for filename in ("first-close.json", "outcome.json"):
        path = case_directory / filename
        record = json.loads(path.read_text(encoding="utf-8"))
        record["unexpected_history"] = []
        path.write_text(json.dumps(record), encoding="utf-8")
        with pytest.raises(ShadowCaseStoreError, match="key set"):
            case_store.read_case(case_id)
        del record["unexpected_history"]
        path.write_text(json.dumps(record), encoding="utf-8")


def test_first_close_intent_is_durable_before_transient_exit_attempts_and_remains_recoverable(
    tmp_path: Path,
) -> None:
    state, case_store, bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None

    close_identity = canonical_identity("PositionActionIdentity", "atomic-first-close")
    state.record(
        object_kind="POSITION_ACTION",
        object_identity=close_identity,
        fact_boundary=_boundary(5),
        payload={
            "position_action_identity": close_identity,
            "shadow_entry_identity": entry_identity,
            "serialized_action": "CLOSE",
            "ordered_predicate_truth_vector": ["FALSE"] * 8 + ["TRUE"],
            "ordered_latched_close_reason_vector": ["ECONOMIC_EXIT_BOUNDARY_REACHED"],
            "primary_close_reason": "ECONOMIC_EXIT_BOUNDARY_REACHED",
            "secondary_close_reasons": [],
            "first_latched_close_action_identity": close_identity,
            "exit_acquisition_profile": _exit_acquisition_profile(),
            "action_fact_boundary": _boundary(5).as_object(),
        },
    )
    first_close_path = tmp_path / "cases" / case_id.removeprefix("sha256:") / "first-close.json"
    durable_intent = json.loads(first_close_path.read_text(encoding="utf-8"))
    assert durable_intent["transition"] == "FIRST_CLOSE_INTENT_LATCHED"
    assert durable_intent["position_action_identity"] == close_identity
    assert "scheduled_post_close_attempt_identity" not in durable_intent

    request_ids = [51, 52]
    request_params = [
        {"instrument_name": "BTC-8AUG26-100000-C", "depth": 10000},
        {"instrument_name": "BTC-8AUG26-102000-C", "depth": 10000},
    ]
    schedule_identity = canonical_identity(
        "ScheduledComponentPostCloseAttemptIdentity",
        entry_identity,
        close_identity,
        request_ids,
        "public/get_order_book",
        request_params,
        _boundary(5).as_object(),
    )
    state.record(
        object_kind="POST_CLOSE_ATTEMPT_SCHEDULED",
        object_identity=schedule_identity,
        fact_boundary=_boundary(5),
        payload={
            "scheduled_post_close_attempt_identity": schedule_identity,
            "shadow_entry_identity": entry_identity,
            "first_latched_close_action_identity": close_identity,
            "request_id_or_marker": request_ids,
            "execution_model": "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL",
            "request_method": "public/get_order_book",
            "request_params": request_params,
            "schedule_fact_boundary": _boundary(5).as_object(),
        },
    )
    durable = json.loads(first_close_path.read_text(encoding="utf-8"))
    assert durable == durable_intent

    closed = case_store.close_active_admitted_segments(
        boundary=_boundary(6),
        terminal_state="CENSORED_AT_STOP",
    )
    assert len(closed) == 1
    assert case_store.read_case(case_id).first_close == durable
    case_directory = tmp_path / "cases" / case_id.removeprefix("sha256:")
    case_residue = case_directory / f".case-{'1' * 32}.tmp"
    segment_residue = case_directory / "segments" / "0" / f".case-{'2' * 32}.tmp"
    case_residue.write_text("interrupted first CLOSE write", encoding="utf-8")
    segment_residue.write_text("interrupted Segment close write", encoding="utf-8")
    linked_case_residue = case_directory / f".case-{'3' * 32}.tmp"
    linked_segment_residue = case_directory / "segments" / "0" / f".case-{'4' * 32}.tmp"
    linked_case_residue.hardlink_to(first_close_path)
    linked_segment_residue.hardlink_to(case_directory / "segments" / "0" / "closed.json")
    assert linked_case_residue.samefile(first_close_path)
    assert linked_segment_residue.samefile(case_directory / "segments" / "0" / "closed.json")

    restarted_bindings = RuntimeBindings(
        code_identity=bindings.code_identity,
        runtime_identity="sha256:" + "d" * 64,
        radar_policy_identity=bindings.radar_policy_identity,
        underwriting_policy_identity=bindings.underwriting_policy_identity,
        position_policy_identity=bindings.position_policy_identity,
    )
    restarted = ShadowCaseStore(
        tmp_path / "cases",
        bindings=restarted_bindings,
        policies=case_store.policies,
    )
    (recoverable,) = restarted.scan_active_admitted()
    assert recoverable.predecessor_segment_state.value == "CENSORED_AT_STOP"
    assert recoverable.first_close_state == "LATCHED"
    assert recoverable.attempt_state == "NOT_SCHEDULED"
    assert recoverable.first_close_decision is not None
    assert recoverable.exit_acquisition_profile is not None
    assert recoverable.exit_acquisition_profile.as_object() == _exit_acquisition_profile()
    assert case_residue.exists()
    assert segment_residue.exists()
    assert linked_case_residue.exists()
    assert linked_segment_residue.exists()

    adopted = restarted.open_recovery_segment(
        case_id,
        adoption_fact_boundary=_runtime_boundary(restarted_bindings, 1),
    )
    assert adopted.first_close_state == "LATCHED"
    assert adopted.attempt_state == "NOT_SCHEDULED"
    assert adopted.exit_acquisition_profile == recoverable.exit_acquisition_profile
    recovery_owner = FixedContractShadowOwner(
        policies=case_store.policies,
        bindings=restarted_bindings,
        state_store=ShadowStateStore(bindings=restarted_bindings),
    )
    recovery_owner.activate_recovered_entries((adopted,))
    assert recovery_owner.active_trade_identities == frozenset({entry_identity})


def test_stable_scanner_rejects_symlink_and_tampered_segment_chain(tmp_path: Path) -> None:
    state, case_store, bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None
    case_directory = tmp_path / "cases" / case_id.removeprefix("sha256:")

    symlink_name = "e" * 64
    (tmp_path / "cases" / symlink_name).symlink_to(case_directory, target_is_directory=True)
    restarted = ShadowCaseStore(
        tmp_path / "cases",
        bindings=bindings,
        policies=case_store.policies,
    )
    with pytest.raises(ShadowCaseStoreError, match="non-Case"):
        restarted.scan_active_admitted()
    (tmp_path / "cases" / symlink_name).unlink()

    segment_path = case_directory / "segments" / "0" / "opened.json"
    segment = json.loads(segment_path.read_text(encoding="utf-8"))
    segment["gap_count"] = 1
    segment_path.write_text(json.dumps(segment), encoding="utf-8")
    with pytest.raises(ShadowCaseStoreError, match="origin Segment continuity"):
        restarted.scan_active_admitted()


def test_open_segment_is_explicitly_incomplete_after_unclean_exit(tmp_path: Path) -> None:
    state, case_store, bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None

    restarted_reader = ShadowCaseStore(
        tmp_path / "cases",
        bindings=bindings,
        policies=case_store.policies,
    )
    read = restarted_reader.read_case(case_id)
    assert read.status is ShadowCaseReadStatus.OPEN
    assert read.segments[-1].status.value == "INCOMPLETE_UNCLEAN_EXIT"


def test_case_reader_rejects_tampered_known_outcome_arithmetic(tmp_path: Path) -> None:
    state, case_store, bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None
    case_directory = tmp_path / "cases" / case_id.removeprefix("sha256:")
    close_identity = _record_first_close_and_schedule(
        state,
        entry_identity,
        suffix="tampered",
        causal_seq=5,
    )
    outcome_identity = canonical_identity("ShadowOutcomeIdentity", "tampered")
    state.record(
        object_kind="SHADOW_OUTCOME",
        object_identity=outcome_identity,
        fact_boundary=_boundary(6),
        payload={
            "shadow_outcome_identity": outcome_identity,
            "shadow_entry_identity": entry_identity,
            "terminal_state": "MATURE_KNOWN",
            "selected_exit_identity": canonical_identity("ShadowExit", "tampered"),
            "first_latched_close_action_identity": close_identity,
            "gross_close_cashflow_usdc": "-3.2",
            "close_fee_reserve_usdc": "0.875",
            "net_close_cashflow_usdc": "-4.075",
            "gross_pnl_usdc": "26.6",
            "total_public_fee_reserve_usdc": "5.1375",
            "net_pnl_after_public_standard_fee_reserve_usdc": "21.4625",
            "net_loss_usdc": "0",
            "native_gross_close_cashflow": "-0.000032",
            "native_close_fee_reserve": "0.00000875",
            "native_net_close_cashflow": "-0.00004075",
            "native_gross_pnl": "0.000266",
            "native_total_fee_reserve": "0.000051375",
            "native_net_pnl": "0.000214625",
            "close_valuation_index_price": "100000",
            "boundary_valued_net_pnl_usd": "21.4625",
            "exit_valued_native_net_pnl_usd": "21.4625",
            "economic_availability": "KNOWN",
            "close_component_pair_identity": canonical_identity(
                "ComponentPair", "tampered", "close"
            ),
            "close_component_quote_source_refs": _component_source_refs(
                suffix="tampered-close",
                causal_seq=6,
            ),
            "close_component_legs": _component_legs(close=True),
            "censor_mask": [],
            "non_claims": COMPONENT_NON_CLAIMS,
        },
    )
    outcome_path = case_directory / "outcome.json"
    tampered = json.loads(outcome_path.read_text(encoding="utf-8"))
    tampered["gross_pnl_usd"] = "999"
    outcome_path.write_text(json.dumps(tampered), encoding="utf-8")

    restarted_reader = ShadowCaseStore(
        tmp_path / "cases",
        bindings=bindings,
        policies=case_store.policies,
    )
    with pytest.raises(ShadowCaseStoreError, match="arithmetic mismatch"):
        restarted_reader.read_case(case_id)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("code_identity", "c" * 40),
        ("runtime_identity", "sha256:" + "d" * 64),
        ("radar_policy_identity", "sha256:" + "e" * 64),
        ("shadow_entry_identity", canonical_identity("ShadowEntryIdentity", "tampered")),
    ),
)
def test_case_reader_rejects_tampered_opened_identity_binding(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    state, case_store, bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None
    opened_path = tmp_path / "cases" / case_id.removeprefix("sha256:") / "opened.json"
    opened = json.loads(opened_path.read_text(encoding="utf-8"))
    opened[field] = replacement
    opened_path.write_text(json.dumps(opened), encoding="utf-8")

    restarted_reader = ShadowCaseStore(
        tmp_path / "cases",
        bindings=bindings,
        policies=case_store.policies,
    )
    with pytest.raises(ShadowCaseStoreError, match=r"binding|identity"):
        restarted_reader.read_case(case_id)


def test_in_memory_store_rejects_conflicting_duplicate_before_case_persistence(
    tmp_path: Path,
) -> None:
    state, case_store, _bindings = _system(tmp_path)
    _availability, action_identity, _candidate_identity = _seed_pre_shadow(state)
    action = state.get_object("UNDERWRITING_ACTION", action_identity)
    assert action is not None
    action_payload = action["payload"]
    assert isinstance(action_payload, Mapping)

    with pytest.raises(ShadowStateError, match="conflicting"):
        state.record(
            object_kind="UNDERWRITING_ACTION",
            object_identity=action_identity,
            fact_boundary=_boundary(2),
            payload={**action_payload, "economic_action": "WATCH"},
        )

    assert case_store.case_count == 0
    assert list((tmp_path / "cases").iterdir()) == []


def test_completed_cases_evict_active_memory_but_remain_durably_readable(tmp_path: Path) -> None:
    state, case_store, _bindings = _system(tmp_path)
    case_ids: list[str] = []
    case_count = 32

    for index in range(case_count):
        suffix = f"case-{index}"
        start = index * 10 + 1
        _availability, _action, candidate = _seed_pre_shadow(
            state,
            suffix=suffix,
            start_seq=start,
        )
        entry = _open_case(
            state,
            candidate,
            suffix=suffix,
            causal_seq=start + 3,
        )
        case_id = case_store.case_id_for_entry(entry)
        assert case_id is not None
        case_ids.append(case_id)
        _mature_unknown_case(
            state,
            entry,
            suffix=suffix,
            causal_seq=start + 4,
        )
        state.retire_candidate(candidate)
        state.retire_scope(_scope_identity(suffix))
        state.retain_latest_terminal_case(entry)
        state.take_pending_records()

        assert case_store.active_case_count == 0
        assert state.retained_state_counts["active_scopes"] == 0
        assert state.retained_state_counts["active_candidates"] == 0
        assert state.retained_state_counts["active_or_latest_terminal_cases"] == 1
        assert state.retained_state_counts["latest_terminal_cases"] == 1
        assert state.retained_state_counts["pending_records"] == 0

    assert case_store.case_count == case_count
    assert case_store.active_case_count == 0
    assert state.retained_state_counts == {
        "objects": 2,
        "pending_records": 0,
        "active_scopes": 0,
        "active_candidates": 0,
        "active_or_latest_terminal_control_batches": 0,
        "active_or_latest_terminal_cases": 1,
        "availability_bindings": 0,
        "admission_attempt_bindings": 0,
        "observation_bindings": 0,
        "post_close_attempt_bindings": 0,
        "latest_terminal_cases": 1,
        "latest_terminal_control_batches": 0,
    }
    assert case_store.read_case(case_ids[0]).status is ShadowCaseReadStatus.COMPLETE
    assert case_store.read_case(case_ids[-1]).status is ShadowCaseReadStatus.COMPLETE


def test_current_scope_replacements_do_not_accumulate_hidden_availability_bindings(
    tmp_path: Path,
) -> None:
    state, case_store, _bindings = _system(tmp_path)
    scope = _scope_identity("replacement")

    for index in range(1_000):
        availability = canonical_identity("AvailabilityIdentity", f"replacement-{index}")
        action = canonical_identity("UnderwritingActionIdentity", f"replacement-{index}")
        state.record(
            object_kind="UNDERWRITING_AVAILABILITY_EVALUATION",
            object_identity=availability,
            fact_boundary=_boundary(index * 2 + 1),
            payload={
                "underwriting_availability_evaluation_identity": availability,
                "radar_scope_or_short_leg_identity": scope,
                "consumed_availability_fact_fingerprint": canonical_identity(
                    "AvailabilityFingerprint",
                    index,
                ),
                "availability": "EVALUABLE",
                "availability_evaluation_fact_boundary": _boundary(index * 2 + 1).as_object(),
                "unknown_reasons": [],
            },
        )
        state.record(
            object_kind="UNDERWRITING_ACTION",
            object_identity=action,
            fact_boundary=_boundary(index * 2 + 2),
            payload={
                "underwriting_action_identity": action,
                "underwriting_availability_evaluation_identity": availability,
                "underwriting_opportunity_key_identity": canonical_identity(
                    "Opportunity",
                    index,
                ),
                "consumed_economic_fact_fingerprint": canonical_identity("Economics", index),
                "economic_action": "WATCH",
                "evaluation_fact_boundary": _boundary(index * 2 + 2).as_object(),
            },
        )
        state.take_pending_records()

    assert state.retained_state_counts == {
        "objects": 2,
        "pending_records": 0,
        "active_scopes": 1,
        "active_candidates": 0,
        "active_or_latest_terminal_control_batches": 0,
        "active_or_latest_terminal_cases": 0,
        "availability_bindings": 1,
        "admission_attempt_bindings": 0,
        "observation_bindings": 0,
        "post_close_attempt_bindings": 0,
        "latest_terminal_cases": 0,
        "latest_terminal_control_batches": 0,
    }
    state.retire_scope(scope)
    assert state.retained_object_count == 0
    assert case_store.case_count == 0
