from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from short_vol_underwriting import (
    RuntimeBindings,
    ShadowCaseReadStatus,
    ShadowCaseStore,
    ShadowCaseStoreError,
    ShadowStateError,
    ShadowStateStore,
    canonical_identity,
    load_policy_chain,
)
from short_vol_underwriting.model import FactBoundary

ROOT = Path(__file__).resolve().parents[1]
CODE = "a" * 40
RUNTIME = "sha256:" + "b" * 64
RADAR_POLICY = "sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4"
UNDERWRITING_POLICY = "sha256:be056d7fad71668954103e1e383372c3b03db9b27b8d03ce0a030d39285629af"
POSITION_POLICY = "sha256:498a298be50cb356f43886ae7ba02d1f6da065233ae9b2b52e9a230cf7f9c439"


def _boundary(causal_seq: int) -> FactBoundary:
    return FactBoundary(
        code_identity=CODE,
        runtime_identity=RUNTIME,
        session_epoch=1,
        ingress_seq=causal_seq,
        received_monotonic_ms=100 + causal_seq,
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
    state.record(
        object_kind="SHADOW_ENTRY",
        object_identity=entry_identity,
        fact_boundary=_boundary(causal_seq),
        payload={
            "shadow_entry_identity": entry_identity,
            "candidate_identity": candidate_identity,
            "active_episode_identity": (
                f"{RUNTIME}:{RADAR_POLICY}:BTC_USDC-8AUG26-100000-C:{causal_seq}"
            ),
            "radar_scope_identity": _scope_identity(suffix),
            "atomic_state": "PUBLIC_ATOMIC_QUOTE_AVAILABLE",
            "radar_band_id": "six-to-twenty-four-hours",
            "radar_richness_interval": {"lower": "1.3", "upper": "1.31"},
            "canonical_combo_identity": canonical_identity("Combo", suffix),
            "canonical_leg_identities": [
                canonical_identity("Leg", f"{suffix}-short"),
                canonical_identity("Leg", f"{suffix}-long"),
            ],
            "combo_instrument_name": "BTC_USDC-CS-8AUG26-100000_105000",
            "short_leg_instrument_name": "BTC_USDC-8AUG26-100000-C",
            "long_leg_instrument_name": "BTC_USDC-8AUG26-105000-C",
            "expiry_ms": 1_786_150_800_000,
            "option_type": "call",
            "short_strike_usdc_per_btc": "100000",
            "long_strike_usdc_per_btc": "105000",
            "entry_direction": "SELL",
            "full_quantity_btc": "0.1",
            "entry_consumed_levels": [{"price_usdc_per_btc": "300", "amount_btc": "0.1"}],
            "gross_entry_credit_usdc": "30",
            "entry_fee_reserve_usdc": "3",
            "net_entry_credit_usdc": "27",
            "payoff_cap_usdc": "500",
            "future_cost_reserve_usdc": "12",
            "underwriting_reserved_loss_usdc": "485",
        },
    )
    return entry_identity


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
            "censor_mask": ["STOP"],
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
    assert sorted(path.name for path in case_directory.iterdir()) == ["opened.json"]
    read = case_store.read_case(case_id, runtime_active=True)
    assert read.status is ShadowCaseReadStatus.OPEN
    assert read.opened["shadow_entry_identity"] == entry_identity
    underwriting = read.opened["underwriting"]
    assert isinstance(underwriting, Mapping)
    assert underwriting["action"] == "CANDIDATE"


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


def test_first_close_and_known_outcome_complete_case_with_recomputable_economics(
    tmp_path: Path,
) -> None:
    state, case_store, _bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None

    close_identity = canonical_identity("PositionActionIdentity", "first-close")
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
            "gross_close_cashflow_usdc": "-5",
            "close_fee_reserve_usdc": "3",
            "net_close_cashflow_usdc": "-8",
            "gross_pnl_usdc": "25",
            "total_public_fee_reserve_usdc": "6",
            "net_pnl_after_public_standard_fee_reserve_usdc": "19",
            "net_loss_usdc": "0",
            "economic_availability": "KNOWN",
            "censor_mask": [],
        },
    )

    case_directory = tmp_path / "cases" / case_id.removeprefix("sha256:")
    assert sorted(path.name for path in case_directory.iterdir()) == [
        "first-close.json",
        "opened.json",
        "outcome.json",
    ]
    read = case_store.read_case(case_id)
    assert read.status is ShadowCaseReadStatus.COMPLETE
    assert read.first_close is not None
    assert read.outcome is not None
    assert read.outcome["net_pnl_after_public_standard_fee_reserve_usdc"] == "19"

    for filename in ("first-close.json", "outcome.json"):
        path = case_directory / filename
        record = json.loads(path.read_text(encoding="utf-8"))
        record["unexpected_history"] = []
        path.write_text(json.dumps(record), encoding="utf-8")
        with pytest.raises(ShadowCaseStoreError, match="key set"):
            case_store.read_case(case_id)
        del record["unexpected_history"]
        path.write_text(json.dumps(record), encoding="utf-8")


def test_opened_only_case_is_explicitly_incomplete_after_unclean_exit(tmp_path: Path) -> None:
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
    assert (
        restarted_reader.read_case(case_id).status is ShadowCaseReadStatus.INCOMPLETE_UNCLEAN_EXIT
    )


def test_case_reader_rejects_tampered_known_outcome_arithmetic(tmp_path: Path) -> None:
    state, case_store, bindings = _system(tmp_path)
    _availability, _action, candidate_identity = _seed_pre_shadow(state)
    entry_identity = _open_case(state, candidate_identity)
    case_id = case_store.case_id_for_entry(entry_identity)
    assert case_id is not None
    case_directory = tmp_path / "cases" / case_id.removeprefix("sha256:")
    opened_boundary = _boundary(4)
    tampered = {
        "record_kind": "SHADOW_CASE_OUTCOME",
        "schema_version": 1,
        "case_id": case_id,
        "code_identity": CODE,
        "runtime_identity": RUNTIME,
        "radar_policy_identity": RADAR_POLICY,
        "underwriting_policy_identity": UNDERWRITING_POLICY,
        "position_policy_identity": POSITION_POLICY,
        "outcome_fact_boundary": _boundary(6).as_object(),
        "shadow_outcome_identity": canonical_identity("ShadowOutcomeIdentity", "tampered"),
        "terminal_state": "MATURE_KNOWN",
        "selected_exit_identity": canonical_identity("ShadowExit", "tampered"),
        "first_latched_close_action_identity": canonical_identity("PositionAction", "tampered"),
        "gross_close_cashflow_usdc": "-5",
        "close_fee_reserve_usdc": "3",
        "net_close_cashflow_usdc": "-8",
        "gross_pnl_usdc": "999",
        "total_public_fee_reserve_usdc": "6",
        "net_pnl_after_public_standard_fee_reserve_usdc": "19",
        "net_loss_usdc": "0",
        "economic_availability": "KNOWN",
        "censor_mask": [],
        "non_claims": ["NOT_ACTUAL_PNL"],
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
        _censor_case(
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
        "active_or_latest_terminal_cases": 1,
        "availability_bindings": 0,
        "admission_attempt_bindings": 0,
        "observation_bindings": 0,
        "post_close_attempt_bindings": 0,
        "latest_terminal_cases": 1,
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
        "active_or_latest_terminal_cases": 0,
        "availability_bindings": 1,
        "admission_attempt_bindings": 0,
        "observation_bindings": 0,
        "post_close_attempt_bindings": 0,
        "latest_terminal_cases": 0,
    }
    state.retire_scope(scope)
    assert state.retained_object_count == 0
    assert case_store.case_count == 0
