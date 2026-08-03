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


def _seed_pre_shadow(state: ShadowStateStore) -> tuple[str, str, str]:
    action_identity = canonical_identity("UnderwritingActionIdentity", "test-action")
    candidate_identity = canonical_identity("CandidateActivationIdentity", "test-candidate")
    availability_identity = canonical_identity("AvailabilityIdentity", "test-availability")
    state.record(
        object_kind="UNDERWRITING_AVAILABILITY_EVALUATION",
        object_identity=availability_identity,
        fact_boundary=_boundary(1),
        payload={
            "underwriting_availability_evaluation_identity": availability_identity,
            "radar_scope_or_short_leg_identity": canonical_identity("RadarScope", "scope"),
            "consumed_availability_fact_fingerprint": canonical_identity(
                "AvailabilityFingerprint", "known"
            ),
            "availability": "EVALUABLE",
            "availability_evaluation_fact_boundary": _boundary(1).as_object(),
            "unknown_reasons": [],
        },
    )
    state.record(
        object_kind="UNDERWRITING_ACTION",
        object_identity=action_identity,
        fact_boundary=_boundary(2),
        payload={
            "underwriting_action_identity": action_identity,
            "underwriting_availability_evaluation_identity": availability_identity,
            "underwriting_opportunity_key_identity": canonical_identity("Opportunity", "one"),
            "consumed_economic_fact_fingerprint": canonical_identity("Economics", "one"),
            "economic_action": "CANDIDATE",
            "evaluation_fact_boundary": _boundary(2).as_object(),
        },
    )
    state.record(
        object_kind="CANDIDATE_ACTIVATION",
        object_identity=candidate_identity,
        fact_boundary=_boundary(3),
        payload={
            "candidate_identity": candidate_identity,
            "underwriting_action_identity": action_identity,
            "underwriting_position_slot_key_identity": canonical_identity("Slot", "one"),
            "candidate_activation_fact_boundary": _boundary(3).as_object(),
        },
    )
    return availability_identity, action_identity, candidate_identity


def _open_case(state: ShadowStateStore, candidate_identity: str) -> str:
    entry_identity = canonical_identity("ShadowEntryIdentity", "one")
    state.record(
        object_kind="SHADOW_ENTRY",
        object_identity=entry_identity,
        fact_boundary=_boundary(4),
        payload={
            "shadow_entry_identity": entry_identity,
            "candidate_identity": candidate_identity,
            "active_episode_identity": (f"{RUNTIME}:{RADAR_POLICY}:BTC_USDC-8AUG26-100000-C:1"),
            "radar_scope_identity": canonical_identity("RadarScope", "scope"),
            "atomic_state": "PUBLIC_ATOMIC_QUOTE_AVAILABLE",
            "radar_band_id": "six-to-twenty-four-hours",
            "radar_richness_interval": {"lower": "1.3", "upper": "1.31"},
            "canonical_combo_identity": canonical_identity("Combo", "one"),
            "canonical_leg_identities": [
                canonical_identity("Leg", "short"),
                canonical_identity("Leg", "long"),
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
