from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

import pytest
import short_vol_underwriting.case_store as case_store_module
from short_vol_underwriting import (
    UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY,
    FixedContractShadowOwner,
    RuntimeBindings,
    ShadowCaseReadStatus,
    ShadowCaseStore,
    ShadowCaseStoreError,
    ShadowStateError,
    ShadowStateStore,
    canonical_identity,
    load_policy_chain,
    migrate_legacy_admitted_cases,
)
from short_vol_underwriting.constants import (
    POSITION_POLICY_IDENTITY as POSITION_POLICY,
)
from short_vol_underwriting.constants import (
    RADAR_POLICY_IDENTITY as RADAR_POLICY,
)
from short_vol_underwriting.constants import (
    UNDERWRITING_POLICY_IDENTITY as UNDERWRITING_POLICY,
)
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


def _system(tmp_path: Path) -> tuple[ShadowStateStore, ShadowCaseStore, RuntimeBindings]:
    policies = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-fixed-public-shadow-radar.json",
        underwriting_path=ROOT / "policies/short-vol-fixed-public-shadow-underwriting.json",
        position_path=ROOT / "policies/short-vol-fixed-public-shadow-position.json",
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
            "BTC_USDC-8AUG26-100000-C",
            "BUY" if close else "SELL",
            "50" if close else "400",
            "51" if close else "399",
            "0.6375" if close else "3",
        ),
        (
            "LONG",
            "BTC_USDC-8AUG26-102000-C",
            "SELL" if close else "BUY",
            "20" if close else "100",
            "19" if close else "101",
            "0.2375" if close else "1.2625",
        ),
    )
    return [
        {
            "canonical_leg_role": role,
            "instrument_name": instrument_name,
            "action": action,
            "raw_consumed_levels": [{"price_usdc_per_btc": raw_price, "amount_btc": "0.1"}],
            "raw_vwap_usdc_per_btc": raw_price,
            "stressed_consumed_levels": [
                {"price_usdc_per_btc": stressed_price, "amount_btc": "0.1"}
            ],
            "stressed_vwap_usdc_per_btc": stressed_price,
            "fee_reserve_usdc": fee,
        }
        for role, instrument_name, action, raw_price, stressed_price, fee in specifications
    ]


def _predicate_margin_vector() -> list[dict[str, object]]:
    return [
        {
            "predicate": predicate,
            "signed_margin": margin,
            "unit": unit,
            "passes": True,
        }
        for predicate, margin, unit in (
            ("POSITIVE_NET_ENTRY_CREDIT", "25.5375", "USDC"),
            ("CREDIT_ABOVE_FUTURE_COST_RESERVE", "13.5375", "USDC"),
            ("UNDERWRITING_RESERVED_LOSS_WITHIN_LIMIT", "63.5375", "USDC"),
            ("MINIMUM_NET_ENTRY_CREDIT", "10.5375", "USDC"),
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
        "BTC_USDC-8AUG26-100000-C",
        "BTC_USDC-8AUG26-102000-C",
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
            "active_episode_identity": (
                f"{RUNTIME}:{RADAR_POLICY}:BTC_USDC-8AUG26-100000-C:{causal_seq}"
            ),
            "radar_scope_identity": _scope_identity(suffix),
            "execution_model": "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL",
            "component_state": "COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE",
            "atomic_state_diagnostic": "NO_ACTIVE_COMBO",
            "radar_band_id": "six-to-twenty-four-hours",
            "radar_richness_interval": {"lower": "1.3", "upper": "1.31"},
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
            "action_fact_boundary": _boundary(causal_seq).as_object(),
        },
    )
    request_ids = [41, 42]
    request_params = [
        {"instrument_name": "BTC_USDC-8AUG26-100000-C", "depth": 10000},
        {"instrument_name": "BTC_USDC-8AUG26-102000-C", "depth": 10000},
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
        "gross_close_cashflow_usdc": None,
        "close_fee_reserve_usdc": None,
        "net_close_cashflow_usdc": None,
        "gross_pnl_usdc": None,
        "total_public_fee_reserve_usdc": None,
        "net_pnl_after_public_standard_fee_reserve_usdc": None,
        "net_loss_usdc": None,
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
        "entry_index_usdc_per_btc": "100000",
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
    assert read.outcome["net_pnl_after_public_standard_fee_reserve_usdc"] == "21.4625"

    for filename in ("first-close.json", "outcome.json"):
        path = case_directory / filename
        record = json.loads(path.read_text(encoding="utf-8"))
        record["unexpected_history"] = []
        path.write_text(json.dumps(record), encoding="utf-8")
        with pytest.raises(ShadowCaseStoreError, match="key set"):
            case_store.read_case(case_id)
        del record["unexpected_history"]
        path.write_text(json.dumps(record), encoding="utf-8")


def test_first_close_is_durable_only_with_its_attempt_and_is_never_retried(
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
            "action_fact_boundary": _boundary(5).as_object(),
        },
    )
    first_close_path = tmp_path / "cases" / case_id.removeprefix("sha256:") / "first-close.json"
    assert not first_close_path.exists()

    request_ids = [51, 52]
    request_params = [
        {"instrument_name": "BTC_USDC-8AUG26-100000-C", "depth": 10000},
        {"instrument_name": "BTC_USDC-8AUG26-102000-C", "depth": 10000},
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
    assert durable["transition"] == "FIRST_CLOSE_AND_ATTEMPT_SCHEDULED"
    assert durable["scheduled_post_close_attempt_identity"] == schedule_identity

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
    assert recoverable.attempt_state == "ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS"
    assert recoverable.first_close_decision is not None
    assert case_residue.exists()
    assert segment_residue.exists()
    assert linked_case_residue.exists()
    assert linked_segment_residue.exists()

    adopted = restarted.open_recovery_segment(
        case_id,
        adoption_fact_boundary=_runtime_boundary(restarted_bindings, 1),
    )
    assert adopted.first_close_state == "LATCHED"
    assert adopted.attempt_state == "ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS"
    recovery_owner = FixedContractShadowOwner(
        policies=case_store.policies,
        bindings=restarted_bindings,
        state_store=ShadowStateStore(bindings=restarted_bindings),
    )
    recovery_owner.activate_recovered_entries((adopted,))
    assert recovery_owner.active_trade_identities == frozenset({entry_identity})


def test_legacy_reader_validates_without_writing_or_treating_run_case_as_stable(
    tmp_path: Path,
) -> None:
    state, case_store, bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None
    source_opened = (
        tmp_path / "cases" / case_id.removeprefix("sha256:") / "opened.json"
    ).read_bytes()

    legacy_cases = tmp_path / "legacy-cases"
    legacy_case = legacy_cases / case_id.removeprefix("sha256:")
    legacy_case.mkdir(parents=True)
    (legacy_case / "opened.json").write_bytes(source_opened)
    legacy_reader = ShadowCaseStore(
        legacy_cases,
        bindings=bindings,
        policies=case_store.policies,
    )

    read = legacy_reader.read_legacy_case(case_id)
    assert read.status is ShadowCaseReadStatus.INCOMPLETE_UNCLEAN_EXIT
    assert read.opened["shadow_entry_identity"] == entry_identity
    assert (legacy_case / "opened.json").read_bytes() == source_opened
    assert sorted(path.name for path in legacy_case.iterdir()) == ["opened.json"]
    with pytest.raises(ShadowCaseStoreError, match="origin Observation Segment"):
        legacy_reader.read_case(case_id)


def test_offline_legacy_migration_is_atomic_read_only_idempotent_and_recoverable(
    tmp_path: Path,
) -> None:
    state, case_store, bindings = _system(tmp_path)

    _availability, _action, candidate = _seed_pre_shadow(
        state,
        suffix="legacy-close",
        start_seq=1,
    )
    closed_entry = _open_case(
        state,
        candidate,
        suffix="legacy-close",
        causal_seq=4,
    )
    first_close_identity = _record_first_close_and_schedule(
        state,
        closed_entry,
        suffix="legacy-close",
        causal_seq=5,
    )
    closed_case_id = case_store.case_id_for_entry(closed_entry)
    assert closed_case_id is not None

    _availability, _action, candidate = _seed_pre_shadow(
        state,
        suffix="legacy-open",
        start_seq=6,
    )
    open_entry = _open_case(
        state,
        candidate,
        suffix="legacy-open",
        causal_seq=9,
    )
    open_case_id = case_store.case_id_for_entry(open_entry)
    assert open_case_id is not None

    _availability, _action, candidate = _seed_pre_shadow(
        state,
        suffix="legacy-terminal",
        start_seq=10,
    )
    terminal_entry = _open_case(
        state,
        candidate,
        suffix="legacy-terminal",
        causal_seq=13,
    )
    terminal_case_id = case_store.case_id_for_entry(terminal_entry)
    assert terminal_case_id is not None

    source = tmp_path / "legacy-cases"
    source.mkdir()
    opened_by_case: dict[str, dict[str, object]] = {}
    for case_id in (closed_case_id, open_case_id, terminal_case_id):
        source_case = source / case_id.removeprefix("sha256:")
        source_case.mkdir()
        stable_opened = tmp_path / "cases" / case_id.removeprefix("sha256:") / "opened.json"
        (source_case / "opened.json").write_bytes(stable_opened.read_bytes())
        opened_by_case[case_id] = json.loads(stable_opened.read_text(encoding="utf-8"))

    stable_first_close = json.loads(
        (
            tmp_path / "cases" / closed_case_id.removeprefix("sha256:") / "first-close.json"
        ).read_text(encoding="utf-8")
    )
    stable_first_close_extension = {
        "product_spec_identity",
        "segment_sequence",
        "segment_identity",
        "transition",
        "scheduled_post_close_attempt_identity",
        "request_id_or_marker",
        "execution_model",
        "request_method",
        "request_params",
        "canonical_leg_identities",
        "full_quantity_btc",
        "schedule_fact_boundary",
    }
    legacy_first_close = {
        key: value
        for key, value in stable_first_close.items()
        if key not in stable_first_close_extension
    }
    closed_source_case = source / closed_case_id.removeprefix("sha256:")
    (closed_source_case / "first-close.json").write_text(
        json.dumps(legacy_first_close),
        encoding="utf-8",
    )
    (closed_source_case / "outcome.json").write_text(
        json.dumps(
            _legacy_unknown_outcome(
                opened_by_case[closed_case_id],
                suffix="legacy-close",
                causal_seq=6,
                terminal_state="CENSORED_AT_STOP",
                first_close_identity=first_close_identity,
            )
        ),
        encoding="utf-8",
    )
    terminal_source_case = source / terminal_case_id.removeprefix("sha256:")
    (terminal_source_case / "outcome.json").write_text(
        json.dumps(
            _legacy_unknown_outcome(
                opened_by_case[terminal_case_id],
                suffix="legacy-terminal",
                causal_seq=14,
                terminal_state="MATURE_UNKNOWN",
            )
        ),
        encoding="utf-8",
    )
    source_snapshot = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }

    destination = tmp_path / "stable-cases"
    first = migrate_legacy_admitted_cases(
        source,
        destination,
        policies=case_store.policies,
    )
    destination_snapshot = {
        path.relative_to(destination).as_posix(): path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file()
    }
    second = migrate_legacy_admitted_cases(
        source,
        destination,
        policies=case_store.policies,
    )

    assert {entry.case_id for entry in first} == {closed_case_id, open_case_id}
    assert {entry.case_id for entry in second} == {closed_case_id, open_case_id}
    assert not (destination / terminal_case_id.removeprefix("sha256:")).exists()
    assert source_snapshot == {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert destination_snapshot == {
        path.relative_to(destination).as_posix(): path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file()
    }

    closed_destination = destination / closed_case_id.removeprefix("sha256:")
    assert not (closed_destination / "first-close.json").exists()
    assert not (closed_destination / "outcome.json").exists()
    migration_record = json.loads(
        (closed_destination / "legacy-migration.json").read_text(encoding="utf-8")
    )
    assert set(migration_record) == {
        "record_kind",
        "migration_schema_version",
        "case_id",
        "shadow_entry_identity",
        "source_opened_record_identity",
        "source_first_close_record_identity",
        "source_outcome_record_identity",
        "source_outcome_terminal_state",
        "legacy_first_close",
        "mapped_segment_state",
    }
    assert migration_record["legacy_first_close"] == legacy_first_close
    assert (
        json.loads(
            (closed_destination / "segments" / "0" / "closed.json").read_text(encoding="utf-8")
        )["terminal_state"]
        == "CENSORED_AT_STOP"
    )
    migrated_closed = next(entry for entry in first if entry.case_id == closed_case_id)
    assert migrated_closed.first_close_state == "LATCHED"
    assert migrated_closed.attempt_state == "ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS"
    assert migrated_closed.first_close_decision is not None
    assert migrated_closed.first_close_decision.action_case_boundary.segment_sequence == 0
    assert migrated_closed.first_close_decision.position_action_identity == first_close_identity
    assert migrated_closed.entry_terms.index_usdc_per_btc is None
    assert migrated_closed.entry_terms.index_source is None
    assert migrated_closed.entry_terms.short_mark_iv_fraction is None
    assert migrated_closed.entry_terms.ticker_source is None

    restarted_bindings = RuntimeBindings(
        code_identity=bindings.code_identity,
        runtime_identity="sha256:" + "e" * 64,
        radar_policy_identity=bindings.radar_policy_identity,
        underwriting_policy_identity=bindings.underwriting_policy_identity,
        position_policy_identity=bindings.position_policy_identity,
    )
    recovery_state = ShadowStateStore(bindings=restarted_bindings)
    recovery_owner = FixedContractShadowOwner(
        policies=case_store.policies,
        bindings=restarted_bindings,
        state_store=recovery_state,
    )
    staged = recovery_owner.stage_recovered_entries(
        first,
        recovery_projection_boundary=_runtime_boundary(restarted_bindings, 0),
    )
    staged_closed = next(seed for seed in staged if seed.case_id == closed_case_id)
    assert staged_closed.first_close_decision is not None
    assert staged_closed.first_close_decision.position_action_identity == first_close_identity
    assert staged_closed.first_close_decision.action_case_boundary.segment_sequence == 0

    restarted = ShadowCaseStore(
        destination,
        bindings=restarted_bindings,
        policies=case_store.policies,
    )
    restarted.scan_active_admitted()
    adopted = restarted.open_recovery_segment(
        closed_case_id,
        adoption_fact_boundary=_runtime_boundary(restarted_bindings, 1),
    )
    assert adopted.latest_segment_sequence == 1
    assert adopted.observation_quality.value == "GAPPED"
    assert adopted.first_close_state == "LATCHED"
    assert adopted.attempt_state == "ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS"


@pytest.mark.parametrize(
    ("tamper_field", "expected_error"),
    (
        ("quantity", "quantity"),
        ("runtime", "one origin runtime binding"),
    ),
)
def test_offline_legacy_migration_validates_the_full_set_before_publication(
    tmp_path: Path,
    tamper_field: str,
    expected_error: str,
) -> None:
    state, case_store, _bindings = _system(tmp_path)
    source = tmp_path / "legacy-cases"
    source.mkdir()
    for index, suffix in enumerate(("valid", "tampered")):
        start_seq = 1 + index * 4
        _availability, _action, candidate = _seed_pre_shadow(
            state,
            suffix=suffix,
            start_seq=start_seq,
        )
        entry = _open_case(
            state,
            candidate,
            suffix=suffix,
            causal_seq=start_seq + 3,
        )
        case_id = case_store.case_id_for_entry(entry)
        assert case_id is not None
        source_case = source / case_id.removeprefix("sha256:")
        source_case.mkdir()
        opened_path = tmp_path / "cases" / source_case.name / "opened.json"
        (source_case / "opened.json").write_bytes(opened_path.read_bytes())
        if suffix == "tampered":
            opened = json.loads((source_case / "opened.json").read_text(encoding="utf-8"))
            if tamper_field == "runtime":
                opened["runtime_identity"] = "sha256:" + "9" * 64
            else:
                opened["structure"]["full_quantity_btc"] = "0"
            (source_case / "opened.json").write_text(json.dumps(opened), encoding="utf-8")

    destination = tmp_path / "stable-cases"
    with pytest.raises(ShadowCaseStoreError, match=expected_error):
        migrate_legacy_admitted_cases(
            source,
            destination,
            policies=case_store.policies,
        )
    assert not destination.exists()


def test_offline_legacy_migration_rejects_zero_active_cases_without_destination(
    tmp_path: Path,
) -> None:
    _state, case_store, _bindings = _system(tmp_path)
    source = tmp_path / "empty-legacy-cases"
    source.mkdir()
    destination = tmp_path / "stable-cases"

    with pytest.raises(ShadowCaseStoreError, match="no active compatible"):
        migrate_legacy_admitted_cases(
            source,
            destination,
            policies=case_store.policies,
        )

    assert not destination.exists()


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
    segment_opened = json.loads(
        (case_directory / "segments" / "0" / "opened.json").read_text(encoding="utf-8")
    )
    opened_boundary = _boundary(4)
    tampered = {
        "record_kind": "SHADOW_CASE_OUTCOME",
        "schema_version": 3,
        "case_id": case_id,
        "code_identity": CODE,
        "runtime_identity": RUNTIME,
        "radar_policy_identity": RADAR_POLICY,
        "underwriting_policy_identity": UNDERWRITING_POLICY,
        "position_policy_identity": POSITION_POLICY,
        "product_spec_identity": case_store.product.identity,
        "segment_sequence": 0,
        "segment_identity": segment_opened["segment_identity"],
        "observation_quality": "CONTINUOUS",
        "gap_count": 0,
        "qualification_eligible": True,
        "outcome_fact_boundary": _boundary(6).as_object(),
        "shadow_outcome_identity": canonical_identity("ShadowOutcomeIdentity", "tampered"),
        "terminal_state": "MATURE_KNOWN",
        "selected_exit_identity": canonical_identity("ShadowExit", "tampered"),
        "first_latched_close_action_identity": canonical_identity("PositionAction", "tampered"),
        "gross_close_cashflow_usdc": "-3.2",
        "close_fee_reserve_usdc": "0.875",
        "net_close_cashflow_usdc": "-4.075",
        "gross_pnl_usdc": "999",
        "total_public_fee_reserve_usdc": "5.1375",
        "net_pnl_after_public_standard_fee_reserve_usdc": "21.4625",
        "net_loss_usdc": "0",
        "economic_availability": "KNOWN",
        "close_component_pair_identity": canonical_identity("ComponentPair", "tampered", "close"),
        "close_component_quote_source_refs": _component_source_refs(
            suffix="tampered-close",
            causal_seq=6,
        ),
        "close_component_legs": _component_legs(close=True),
        "censor_mask": [],
        "non_claims": COMPONENT_NON_CLAIMS,
    }
    assert _boundary(6).is_strictly_after(opened_boundary)
    (case_directory / "outcome.json").write_text(json.dumps(tampered), encoding="utf-8")

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
