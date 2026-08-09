from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from options_domain import LINEAR_BTC_USDC
from short_vol_underwriting import (
    CANDIDATE_INVALIDATION_REASONS,
    DECISION_CONTROL_OBJECT_KINDS,
    OUTCOME_OBJECT_KINDS,
    POSITION_CLOSE_REASONS,
    UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY,
    UNDERWRITING_OBJECT_KINDS,
    AdmissionAttempt,
    AdmissionTerminalOutcome,
    CandidateState,
    CloseAtomicAvailability,
    CloseBookAvailability,
    CloseOpportunityEligibility,
    CloseOptionAvailability,
    CloseQuoteFacts,
    CloseQuoteState,
    ComponentLegRole,
    EntryEconomics,
    FactBoundary,
    FixedContractShadowOwner,
    Observation,
    OutcomeReducer,
    OutcomeState,
    OwnerTransition,
    PolicyChainError,
    PositionDecisionState,
    PositionFacts,
    PostCloseAttempt,
    PostCloseAttemptOwner,
    PostCloseAttemptStatus,
    PredicateTruth,
    RecoverableShadowEntry,
    RefreshClassification,
    RpcAdmissionRefreshWitness,
    RpcComponentLegRefreshWitness,
    RuntimeBindings,
    ShadowCaseStore,
    ShadowCaseStoreError,
    ShadowStateError,
    ShadowStateStore,
    SourceFact,
    SubscriptionAdmissionRefreshWitness,
    TerminalSource,
    UnderwritingComponentCandidate,
    UnderwritingFacts,
    canonical_identity,
    classify_close_quote,
    component_pair_witness,
    compute_close_economics,
    compute_entry_economics,
    evaluate_close_opportunity,
    load_policy_chain,
    ordered_candidate_invalidation,
    select_underwriting_component,
    underwriting_threshold_margins,
)
from short_vol_underwriting.case_store import ShadowCaseSegmentStatus
from short_vol_underwriting.constants import (
    POSITION_POLICY_IDENTITY,
    RADAR_POLICY_IDENTITY,
    UNDERWRITING_POLICY_IDENTITY,
)
from short_vol_underwriting.domain import EntryTerms, PositionDecision
from short_vol_underwriting.model import (
    CaseFactBoundary,
    ObservationQuality,
    PositionDecisionRecoverySeed,
)

ROOT = Path(__file__).resolve().parents[1]


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


class _HistoryObserver:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def on_record(
        self,
        value: Mapping[str, object],
        state: ShadowStateStore,
    ) -> None:
        del state
        self.records.append(dict(value))


_STATE_BY_DIRECTORY: dict[Path, ShadowStateStore] = {}
_HISTORY_BY_DIRECTORY: dict[Path, _HistoryObserver] = {}


def _written_objects(
    directory: Path,
    *,
    bindings: RuntimeBindings,
) -> dict[str, dict[str, object]]:
    del bindings
    result: dict[str, dict[str, object]] = {}
    resolved = directory.resolve()
    history = _HISTORY_BY_DIRECTORY.get(resolved)
    values = history.records if history is not None else _STATE_BY_DIRECTORY[resolved].objects
    for value in values:
        identity = value["object_identity"]
        assert isinstance(identity, str)
        result[identity] = dict(value)
    return result


def _boundary(causal_seq: int, monotonic_ms: int | None = None) -> FactBoundary:
    return FactBoundary(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        session_epoch=1,
        ingress_seq=causal_seq,
        received_monotonic_ms=(100 + causal_seq if monotonic_ms is None else monotonic_ms),
        causal_seq=causal_seq,
    )


def _radar_episode_identity(
    *,
    runtime_identity: str = "sha256:" + "b" * 64,
    policy_identity: str = RADAR_POLICY_IDENTITY,
    instrument_name: str = "BTC-SHORT",
    activation_causal_seq: int = 1,
) -> str:
    return f"{runtime_identity}:{policy_identity}:{instrument_name}:{activation_causal_seq}"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("session_epoch", True),
        ("session_epoch", 1.5),
        ("ingress_seq", 1.5),
        ("received_monotonic_ms", 1.5),
        ("causal_seq", 1.5),
    ),
)
def test_fact_boundary_rejects_non_integer_members(field: str, value: object) -> None:
    members: dict[str, object] = {
        "code_identity": "a" * 40,
        "runtime_identity": "sha256:" + "b" * 64,
        "session_epoch": 1,
        "ingress_seq": 1,
        "received_monotonic_ms": 1,
        "causal_seq": 1,
    }
    members[field] = value

    with pytest.raises(ValueError, match="non-negative integer"):
        FactBoundary(
            code_identity=cast(str, members["code_identity"]),
            runtime_identity=cast(str, members["runtime_identity"]),
            session_epoch=cast(int, members["session_epoch"]),
            ingress_seq=cast(int, members["ingress_seq"]),
            received_monotonic_ms=cast(int, members["received_monotonic_ms"]),
            causal_seq=cast(int, members["causal_seq"]),
        )


def _underwriting_facts(
    *,
    boundary: FactBoundary,
    change_id: int,
    previous_change_id: int | None,
    snapshot_kind: str,
) -> UnderwritingFacts:
    combo_identity = "sha256:" + "3" * 64
    instrument_name = "BTC-TEST-COMBO"
    quote_identity = canonical_identity(
        "SubscriptionAdmissionRefreshSourceIdentity",
        boundary.runtime_identity,
        boundary.session_epoch,
        1,
        combo_identity,
        snapshot_kind,
        previous_change_id,
        change_id,
        1_000 + change_id,
        boundary.as_object(),
    )
    quote_witness = SubscriptionAdmissionRefreshWitness(
        source_identity=quote_identity,
        boundary=boundary,
        canonical_combo_identity=combo_identity,
        instrument_name=instrument_name,
        change_id=change_id,
        source_timestamp_ms=1_000 + change_id,
        snapshot_kind=snapshot_kind,
        session_epoch=boundary.session_epoch,
        subscription_generation=1,
        prev_change_id=previous_change_id,
    )
    return UnderwritingFacts(
        boundary=boundary,
        radar_scope_identity="sha256:" + "4" * 64,
        active_episode_identity=_radar_episode_identity(runtime_identity=boundary.runtime_identity),
        anomaly_activation_seq=1,
        short_leg_identity="sha256:" + "6" * 64,
        long_leg_identity="sha256:" + "7" * 64,
        canonical_combo_identity=combo_identity,
        combo_instrument_name=instrument_name,
        option_type="call",
        short_strike_usdc_per_btc=Decimal("101000"),
        long_strike_usdc_per_btc=Decimal("102000"),
        expiry_ms=10_000_000,
        target_quantity_btc=Decimal("0.1"),
        entry_direction="SELL",
        entry_consumed_levels=((Decimal("300"), Decimal("0.1")),),
        atomic_state="PUBLIC_ATOMIC_QUOTE_AVAILABLE",
        option_catalog_complete=True,
        combo_catalog_complete=True,
        short_leg_state="open",
        long_leg_state="open",
        short_leg_active=True,
        long_leg_active=True,
        option_amounts_aligned=True,
        combo_state="open",
        combo_active=True,
        combo_amount_aligned=True,
        platform_usable=True,
        trusted_time_lower_ms=1_000_000,
        trusted_time_upper_ms=1_000_001,
        short_leg_taker_commission_fraction=Decimal("0.0003"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        index_usdc_per_btc=Decimal("100000"),
        short_delta=Decimal("0.2"),
        short_mark_iv_fraction=Decimal("0.5"),
        quote_source=SourceFact(quote_identity, boundary),
        quote_refresh_witness=quote_witness,
        short_instrument_source=SourceFact("sha256:" + "8" * 64, boundary),
        long_instrument_source=SourceFact("sha256:" + "9" * 64, boundary),
        index_source=SourceFact("sha256:" + "a" * 64, boundary),
        ticker_source=SourceFact("sha256:" + "b" * 64, boundary),
        short_leg_instrument_name="BTC-SHORT",
        long_leg_instrument_name="BTC-LONG",
        radar_band_id="six-to-twenty-four-hours",
        radar_richness_lower=Decimal("1.3"),
        radar_richness_upper=Decimal("1.31"),
    )


def _owner(
    tmp_path: Path,
    *,
    close_enrollment: bool = True,
) -> tuple[FixedContractShadowOwner, RuntimeBindings]:
    del close_enrollment
    policies = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-fixed-public-shadow-radar.json",
        underwriting_path=ROOT / "policies/short-vol-fixed-public-shadow-underwriting.json",
        position_path=ROOT / "policies/short-vol-fixed-public-shadow-position.json",
        radar_identity=RADAR_POLICY_IDENTITY,
        underwriting_identity=UNDERWRITING_POLICY_IDENTITY,
        position_identity=POSITION_POLICY_IDENTITY,
    )
    bindings = RuntimeBindings(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        radar_policy_identity=RADAR_POLICY_IDENTITY,
        underwriting_policy_identity=UNDERWRITING_POLICY_IDENTITY,
        position_policy_identity=POSITION_POLICY_IDENTITY,
    )
    history = _HistoryObserver()
    state_store = ShadowStateStore(bindings=bindings, observer=history)
    owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        state_store=state_store,
    )
    _STATE_BY_DIRECTORY[tmp_path.resolve()] = state_store
    _HISTORY_BY_DIRECTORY[tmp_path.resolve()] = history
    return owner, bindings


def _recovery_projection(
    bindings: RuntimeBindings,
    *,
    first_close: bool = False,
    known_entry_baseline: bool = True,
) -> dict[str, object]:
    origin_bindings = replace(
        bindings,
        code_identity="c" * 40,
        runtime_identity="sha256:" + "d" * 64,
    )
    origin_boundary = replace(
        _boundary(3, 130),
        code_identity=origin_bindings.code_identity,
        runtime_identity=origin_bindings.runtime_identity,
    )
    adoption_boundary = _boundary(1, 110)
    entry_identity = canonical_identity("ShadowEntryIdentity", "recovery")
    case_id = canonical_identity("ShadowCaseIdentity", "recovery")
    segment_identity = canonical_identity("ShadowCaseSegmentIdentity", case_id, 1)
    opened: dict[str, object] = {
        "schema_version": 3,
        "case_id": case_id,
        "code_identity": origin_bindings.code_identity,
        "runtime_identity": origin_bindings.runtime_identity,
        "radar_policy_identity": bindings.radar_policy_identity,
        "underwriting_policy_identity": bindings.underwriting_policy_identity,
        "position_policy_identity": bindings.position_policy_identity,
        "shadow_case_contract_identity": origin_bindings.shadow_case_contract_identity,
        "opened_fact_boundary": origin_boundary.as_object(),
        "enrollment_kind": "ADMITTED_SHADOW_TRADE",
        "shadow_entry_identity": entry_identity,
        "candidate_identity": canonical_identity("CandidateIdentity", "recovery"),
        "structure": {
            "execution_model": "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL",
            "canonical_leg_identities": [
                canonical_identity("LegIdentity", "recovery-short"),
                canonical_identity("LegIdentity", "recovery-long"),
            ],
            "short_leg_instrument_name": "BTC_USDC-8AUG26-101000-C",
            "long_leg_instrument_name": "BTC_USDC-8AUG26-102000-C",
            "expiry_ms": 10_000_000,
            "option_type": "call",
            "short_strike_usdc_per_btc": "101000",
            "long_strike_usdc_per_btc": "102000",
            "entry_direction": "SELL",
            "full_quantity_btc": "0.1",
            "entry_component_pair_identity": canonical_identity(
                "ComponentPairIdentity", "recovery-entry"
            ),
            "entry_component_pair_timing": {},
            "entry_component_pair_limits": {},
            "entry_component_legs": [
                {"canonical_leg_role": "SHORT"},
                {"canonical_leg_role": "LONG"},
            ],
        },
        "radar": {
            "active_episode_identity": "origin-episode",
            "radar_scope_identity": canonical_identity("RadarScopeIdentity", "recovery"),
        },
        "entry_economics": {
            "gross_entry_credit_usdc": "29.8",
            "entry_fee_reserve_usdc": "4.2625",
            "net_entry_credit_usdc": "25.5375",
            "width_usdc_per_btc": "1000",
            "payoff_cap_usdc": "100",
            "contractual_payoff_max_loss_ex_fees_usdc": "70.2",
            "entry_fee_reserved_payoff_loss_usdc": "74.4625",
            "future_cost_reserve_usdc": "12",
            "underwriting_reserved_loss_usdc": "86.4625",
        },
        "non_claims": ["NOT_AN_ORDER", "NOT_A_FILL"],
    }
    index_source = {
        "source_identity": canonical_identity("IndexSourceIdentity", "recovery-entry"),
        "receipt_fact_boundary": origin_boundary.as_object(),
    }
    ticker_source = {
        "source_identity": canonical_identity("TickerSourceIdentity", "recovery-entry"),
        "receipt_fact_boundary": origin_boundary.as_object(),
    }
    baseline = {
        "entry_index_usdc_per_btc": "100000" if known_entry_baseline else None,
        "entry_index_source_ref": index_source if known_entry_baseline else None,
        "entry_short_leg_mark_iv_fraction": "0.5" if known_entry_baseline else None,
        "entry_short_leg_mark_iv_source_ref": ticker_source if known_entry_baseline else None,
    }
    close_boundary = replace(origin_boundary, causal_seq=4, ingress_seq=4)
    first_close_record = (
        {
            "segment_sequence": 0,
            "first_close_fact_boundary": close_boundary.as_object(),
            "position_action_identity": canonical_identity(
                "PositionActionIdentity", "recovery-close"
            ),
            "primary_close_reason": "ECONOMIC_EXIT_BOUNDARY_REACHED",
            "ordered_latched_close_reasons": ["ECONOMIC_EXIT_BOUNDARY_REACHED"],
            "predicate_truth_vector": ["FALSE"] * 8 + ["TRUE"],
        }
        if first_close
        else None
    )
    return {
        "case_id": case_id,
        "shadow_entry_identity": entry_identity,
        "opened": opened,
        "entry_position_baseline": baseline,
        "latest_segment_sequence": 1,
        "current_segment_identity": segment_identity,
        "predecessor_segment_state": "CENSORED_AT_STOP",
        "observation_quality": "GAPPED",
        "gap_count": 1,
        "qualification_eligible": False,
        "first_close": first_close_record,
        "first_close_state": "LATCHED" if first_close else "NOT_LATCHED",
        "attempt_state": (
            "ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS" if first_close else "NOT_SCHEDULED"
        ),
        "segments": (
            {
                "segment_sequence": 1,
                "segment_identity": segment_identity,
                "adoption_fact_boundary": adoption_boundary.as_object(),
            },
        ),
    }


def _typed_recovery_entry(
    bindings: RuntimeBindings,
    *,
    first_close: bool = False,
    known_entry_baseline: bool = True,
) -> RecoverableShadowEntry:
    projection = _recovery_projection(
        bindings,
        first_close=first_close,
        known_entry_baseline=known_entry_baseline,
    )
    opened = cast(Mapping[str, object], projection["opened"])
    structure = cast(Mapping[str, object], opened["structure"])
    economics = cast(Mapping[str, object], opened["entry_economics"])
    baseline = cast(Mapping[str, object], projection["entry_position_baseline"])
    index_source_value = baseline["entry_index_source_ref"]
    ticker_source_value = baseline["entry_short_leg_mark_iv_source_ref"]
    index_source = (
        SourceFact(
            cast(str, cast(Mapping[str, object], index_source_value)["source_identity"]),
            FactBoundary.from_object(
                cast(
                    Mapping[str, object],
                    cast(Mapping[str, object], index_source_value)["receipt_fact_boundary"],
                )
            ),
        )
        if index_source_value is not None
        else None
    )
    ticker_source = (
        SourceFact(
            cast(str, cast(Mapping[str, object], ticker_source_value)["source_identity"]),
            FactBoundary.from_object(
                cast(
                    Mapping[str, object],
                    cast(Mapping[str, object], ticker_source_value)["receipt_fact_boundary"],
                )
            ),
        )
        if ticker_source_value is not None
        else None
    )
    leg_identities = cast(list[str], structure["canonical_leg_identities"])
    terms = EntryTerms(
        short_leg_identity=leg_identities[0],
        long_leg_identity=leg_identities[1],
        short_leg_instrument_name=cast(str, structure["short_leg_instrument_name"]),
        long_leg_instrument_name=cast(str, structure["long_leg_instrument_name"]),
        canonical_combo_identity=None,
        combo_instrument_name=None,
        option_type=cast(str, structure["option_type"]),
        short_strike_usdc_per_btc=Decimal(str(structure["short_strike_usdc_per_btc"])),
        long_strike_usdc_per_btc=Decimal(str(structure["long_strike_usdc_per_btc"])),
        expiry_ms=cast(int, structure["expiry_ms"]),
        target_quantity_btc=Decimal(str(structure["full_quantity_btc"])),
        entry_direction=cast(str, structure["entry_direction"]),
        index_usdc_per_btc=(
            Decimal(str(baseline["entry_index_usdc_per_btc"])) if index_source is not None else None
        ),
        index_source=index_source,
        short_mark_iv_fraction=(
            Decimal(str(baseline["entry_short_leg_mark_iv_fraction"]))
            if ticker_source is not None
            else None
        ),
        ticker_source=ticker_source,
        short_leg_taker_commission_fraction=Decimal("0.0003"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        execution_model=cast(str, structure["execution_model"]),
        product_spec_identity=LINEAR_BTC_USDC.identity,
        product_name=LINEAR_BTC_USDC.name.value,
        native_premium_currency=LINEAR_BTC_USDC.native_premium_currency,
        settlement_currency=LINEAR_BTC_USDC.settlement_currency,
        valuation_currency=LINEAR_BTC_USDC.valuation_currency,
        price_index=LINEAR_BTC_USDC.price_index,
        native_gross_entry_credit=Decimal(str(economics["gross_entry_credit_usdc"])),
        native_entry_fee_reserve=Decimal(str(economics["entry_fee_reserve_usdc"])),
        native_net_entry_credit=Decimal(str(economics["net_entry_credit_usdc"])),
        entry_valuation_index_price=Decimal(1),
        width_usdc_per_btc=Decimal(str(economics["width_usdc_per_btc"])),
        entry_component_legs=tuple(
            cast(Mapping[str, object], member)
            for member in cast(list[object], structure["entry_component_legs"])
        ),
    )
    entry_economics = EntryEconomics(
        full_quantity_btc=terms.target_quantity_btc,
        required_side_total_quote_usdc=Decimal(0),
        gross_entry_credit_usdc=Decimal(str(economics["gross_entry_credit_usdc"])),
        entry_fee_reserve_usdc=Decimal(str(economics["entry_fee_reserve_usdc"])),
        net_entry_credit_usdc=Decimal(str(economics["net_entry_credit_usdc"])),
        width_usdc_per_btc=Decimal(str(economics["width_usdc_per_btc"])),
        payoff_cap_usdc=Decimal(str(economics["payoff_cap_usdc"])),
        contractual_payoff_max_loss_ex_fees_usdc=Decimal(
            str(economics["contractual_payoff_max_loss_ex_fees_usdc"])
        ),
        entry_fee_reserved_payoff_loss_usdc=Decimal(
            str(economics["entry_fee_reserved_payoff_loss_usdc"])
        ),
        future_cost_reserve_usdc=Decimal(str(economics["future_cost_reserve_usdc"])),
        underwriting_reserved_loss_usdc=Decimal(str(economics["underwriting_reserved_loss_usdc"])),
    )
    first_close_value = projection["first_close"]
    first_close_decision = None
    if first_close_value is not None:
        first_close_mapping = cast(Mapping[str, object], first_close_value)
        action_identity = cast(str, first_close_mapping["position_action_identity"])
        reasons = tuple(cast(list[str], first_close_mapping["ordered_latched_close_reasons"]))
        first_close_decision = PositionDecision(
            position_evaluation_identity=action_identity,
            position_action_identity=action_identity,
            serialized_action="CLOSE",
            ordered_predicate_truth_vector=tuple(
                cast(list[str], first_close_mapping["predicate_truth_vector"])
            ),
            ordered_latched_close_reason_vector=reasons,
            primary_close_reason=reasons[0],
            secondary_close_reasons=reasons[1:],
            first_latched_close_action_identity=action_identity,
            action_case_boundary=CaseFactBoundary(
                0,
                FactBoundary.from_object(
                    cast(
                        Mapping[str, object],
                        first_close_mapping["first_close_fact_boundary"],
                    )
                ),
            ),
        )
    entry_boundary = FactBoundary.from_object(
        cast(Mapping[str, object], opened["opened_fact_boundary"])
    )
    adoption_boundary = FactBoundary.from_object(
        cast(
            Mapping[str, object],
            cast(tuple[Mapping[str, object], ...], projection["segments"])[0][
                "adoption_fact_boundary"
            ],
        )
    )
    entry_payload = {
        "shadow_entry_identity": projection["shadow_entry_identity"],
        "candidate_identity": opened["candidate_identity"],
        "enrollment_kind": "ADMITTED_SHADOW_TRADE",
        "entry_fact_boundary": entry_boundary.as_object(),
        "short_leg_instrument_name": terms.short_leg_instrument_name,
        "long_leg_instrument_name": terms.long_leg_instrument_name,
        "expiry_ms": terms.expiry_ms,
        "option_type": terms.option_type,
        "full_quantity_btc": terms.target_quantity_btc,
        "entry_component_legs": list(terms.entry_component_legs),
        "product_spec_identity": terms.product_spec_identity,
        "product_name": terms.product_name,
        "native_premium_currency": terms.native_premium_currency,
        "settlement_currency": terms.settlement_currency,
        "valuation_currency": terms.valuation_currency,
        "price_index": terms.price_index,
        "gross_entry_credit_usdc": entry_economics.gross_entry_credit_usdc,
        "entry_fee_reserve_usdc": entry_economics.entry_fee_reserve_usdc,
        "net_entry_credit_usdc": entry_economics.net_entry_credit_usdc,
        "origin_case_id": projection["case_id"],
        "origin_runtime_identity": opened["runtime_identity"],
        "current_segment_identity": projection["current_segment_identity"],
        "current_segment_sequence": 1,
        "observation_quality": "GAPPED",
        "gap_count": 1,
        "qualification_eligible": False,
        "tracking_state": "ACTIVE",
        "post_close_attempt_state": projection["attempt_state"],
    }
    return RecoverableShadowEntry(
        case_id=cast(str, projection["case_id"]),
        shadow_entry_identity=cast(str, projection["shadow_entry_identity"]),
        origin_outcome_contract_identity=cast(str, opened["shadow_case_contract_identity"]),
        origin_runtime_identity=cast(str, opened["runtime_identity"]),
        product_spec_identity=LINEAR_BTC_USDC.identity,
        policy_identities=(
            bindings.radar_policy_identity,
            bindings.underwriting_policy_identity,
            bindings.position_policy_identity,
        ),
        entry_case_boundary=CaseFactBoundary(0, entry_boundary),
        adoption_case_boundary=CaseFactBoundary(1, adoption_boundary),
        latest_segment_sequence=1,
        current_segment_identity=cast(str, projection["current_segment_identity"]),
        predecessor_segment_state=ShadowCaseSegmentStatus.CENSORED_AT_STOP,
        observation_quality=ObservationQuality.GAPPED,
        gap_count=1,
        qualification_eligible=False,
        entry_terms=terms,
        entry_economics=entry_economics,
        first_close_decision=first_close_decision,
        first_close_state="LATCHED" if first_close else "NOT_LATCHED",
        attempt_state=cast(str, projection["attempt_state"]),
        entry_payload=entry_payload,
    )


@pytest.mark.parametrize(
    "episode_identity",
    (
        "",
        "sha256:" + "5" * 64,
        _radar_episode_identity()[:-1],
        _radar_episode_identity(runtime_identity="SHA256:" + "b" * 64),
        _radar_episode_identity(instrument_name=""),
        _radar_episode_identity()[:-1] + "x",
        _radar_episode_identity()[:-1] + "-1",
        _radar_episode_identity()[:-1] + "01",
    ),
)
def test_underwriting_facts_reject_malformed_radar_episode_identity(
    episode_identity: str,
) -> None:
    facts = _underwriting_facts(
        boundary=_boundary(2, 120),
        change_id=10,
        previous_change_id=None,
        snapshot_kind="snapshot",
    )

    with pytest.raises(ValueError):
        replace(facts, active_episode_identity=episode_identity)

    assert (
        replace(
            facts, active_episode_identity=None, anomaly_activation_seq=None
        ).active_episode_identity
        is None
    )


@pytest.mark.parametrize(
    "field",
    ("short_leg_identity", "long_leg_identity", "canonical_combo_identity"),
)
def test_radar_episode_identity_does_not_weaken_downstream_owned_identities(
    field: str,
) -> None:
    facts = _underwriting_facts(
        boundary=_boundary(2, 120),
        change_id=10,
        previous_change_id=None,
        snapshot_kind="snapshot",
    )

    with pytest.raises(ValueError, match="must be sha256"):
        if field == "short_leg_identity":
            replace(facts, short_leg_identity=_radar_episode_identity())
        elif field == "long_leg_identity":
            replace(facts, long_leg_identity=_radar_episode_identity())
        else:
            replace(facts, canonical_combo_identity=_radar_episode_identity())


@pytest.mark.parametrize(
    "episode_identity",
    (
        _radar_episode_identity(runtime_identity="sha256:" + "c" * 64),
        _radar_episode_identity(policy_identity="sha256:" + "d" * 64),
        _radar_episode_identity(instrument_name="BTC-OTHER"),
        _radar_episode_identity(activation_causal_seq=3),
    ),
)
def test_owner_rejects_unbound_radar_episode_before_emission(
    tmp_path: Path,
    episode_identity: str,
) -> None:
    owner, _bindings = _owner(tmp_path)
    facts = replace(
        _underwriting_facts(
            boundary=_boundary(2, 120),
            change_id=10,
            previous_change_id=None,
            snapshot_kind="snapshot",
        ),
        active_episode_identity=episode_identity,
        anomaly_activation_seq=int(episode_identity.rsplit(":", 1)[1]),
    )

    with pytest.raises(ValueError, match="not bound"):
        owner.settle_underwriting((facts,), allocate_request_id=lambda: 41)
    assert owner.state_store.objects == ()


def _admit_owner(owner: FixedContractShadowOwner) -> str:
    origin = _underwriting_facts(
        boundary=_boundary(1, 110),
        change_id=10,
        previous_change_id=None,
        snapshot_kind="snapshot",
    )
    activated = owner.settle_underwriting((origin,), allocate_request_id=lambda: 41)
    candidate_identity = next(
        item.object_identity
        for item in activated.emitted
        if item.object_kind == "CANDIDATE_ACTIVATION"
    )
    owner.note_request_sent(request_id=41, boundary=_boundary(2, 120))
    refreshed = _underwriting_facts(
        boundary=_boundary(3, 130),
        change_id=11,
        previous_change_id=10,
        snapshot_kind="change",
    )
    admitted = owner.settle_underwriting((refreshed,), allocate_request_id=lambda: 42)
    assert any(item.object_kind == "SHADOW_ENTRY" for item in admitted.emitted)
    assert candidate_identity.startswith("sha256:")
    return next(
        item.object_identity for item in admitted.emitted if item.object_kind == "SHADOW_ENTRY"
    )


def _position_subscription_witness(
    *,
    boundary: FactBoundary,
    change_id: int,
    previous_change_id: int | None,
    snapshot_kind: str = "change",
    subscription_generation: int = 1,
    canonical_combo_identity: str = "sha256:" + "3" * 64,
    instrument_name: str = "BTC-TEST-COMBO",
) -> SubscriptionAdmissionRefreshWitness:
    quote_identity = canonical_identity(
        "SubscriptionAdmissionRefreshSourceIdentity",
        boundary.runtime_identity,
        boundary.session_epoch,
        subscription_generation,
        canonical_combo_identity,
        snapshot_kind,
        previous_change_id,
        change_id,
        2_000 + change_id,
        boundary.as_object(),
    )
    return SubscriptionAdmissionRefreshWitness(
        source_identity=quote_identity,
        boundary=boundary,
        canonical_combo_identity=canonical_combo_identity,
        instrument_name=instrument_name,
        change_id=change_id,
        source_timestamp_ms=2_000 + change_id,
        snapshot_kind=snapshot_kind,
        session_epoch=boundary.session_epoch,
        subscription_generation=subscription_generation,
        prev_change_id=previous_change_id,
    )


def _position_facts(
    *,
    boundary: FactBoundary,
    change_id: int,
    previous_change_id: int,
) -> PositionFacts:
    witness = _position_subscription_witness(
        boundary=boundary,
        change_id=change_id,
        previous_change_id=previous_change_id,
    )
    quote_identity = witness.source_identity
    source = SourceFact(quote_identity, boundary)
    return PositionFacts(
        boundary=boundary,
        trusted_time_lower_ms=1_000_100,
        trusted_time_upper_ms=1_000_101,
        platform_continuous=True,
        required_sources_continuous=True,
        canonical_structure_intact=True,
        short_leg_state="open",
        long_leg_state="open",
        short_leg_active=True,
        long_leg_active=True,
        current_index_usdc_per_btc=Decimal("100000"),
        current_short_delta=Decimal("0.2"),
        current_short_mark_iv_fraction=Decimal("0.5"),
        close_quote_facts=CloseQuoteFacts(
            option_availability=CloseOptionAvailability.TRADEABLE,
            atomic_availability=CloseAtomicAvailability.ACTIVE,
            component_reference=PredicateTruth.FALSE,
            book_availability=CloseBookAvailability.FULL_QUANTITY,
            consumed_levels=((Decimal("50"), Decimal("0.1")),),
        ),
        close_direction="BUY",
        quote_source=source,
        quote_refresh_witness=witness,
        short_leg_taker_commission_fraction=Decimal("0.0003"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        short_commission_source=SourceFact(
            canonical_identity("TestShortCommissionSourceIdentity", boundary.as_object()),
            boundary,
        ),
        long_commission_source=SourceFact(
            canonical_identity("TestLongCommissionSourceIdentity", boundary.as_object()),
            boundary,
        ),
        index_source=SourceFact(
            canonical_identity("TestIndexSourceIdentity", boundary.as_object()),
            boundary,
        ),
        ticker_source=SourceFact(
            canonical_identity("TestTickerSourceIdentity", boundary.as_object()),
            boundary,
        ),
        current_combo_subscription_witness=witness,
    )


def _quiet_position_facts(
    *,
    boundary: FactBoundary,
    change_id: int = 12,
    previous_change_id: int = 11,
) -> PositionFacts:
    facts = _position_facts(
        boundary=boundary,
        change_id=change_id,
        previous_change_id=previous_change_id,
    )
    return replace(
        facts,
        close_quote_facts=replace(
            facts.close_quote_facts,
            consumed_levels=((Decimal("300"), Decimal("0.1")),),
        ),
    )


def _position_evaluation_payload(
    tmp_path: Path,
    bindings: RuntimeBindings,
    transition: OwnerTransition,
) -> dict[str, object]:
    identity = next(
        item.object_identity
        for item in transition.emitted
        if item.object_kind == "POSITION_EVALUATION"
    )
    return _object(_written_objects(tmp_path, bindings=bindings)[identity]["payload"])


def test_canonical_identity_matches_all_normative_vectors() -> None:
    assert canonical_identity("FooIdentity", "member_1", "member_2") == (
        "sha256:961665d18281a3f4d46b0e72f1d05c494d73d11a9f829def2f4509e09e76bf3a"
    )
    assert (
        canonical_identity(
            "CompositeIdentity",
            {
                "code_identity": "code",
                "runtime_identity": "runtime",
                "session_epoch": 1,
                "ingress_seq": 2,
                "received_monotonic_ms": 3,
                "causal_seq": 4,
            },
            ["TRUE", "UNKNOWN"],
            {"instrument_name": "combo", "depth": 10000},
            7,
            None,
        )
        == "sha256:2a6013410106bda9c407cb910982744c77f406384beb93f17b917464639e05ff"
    )
    assert (
        canonical_identity(
            "UnderwritingPositionSlotKeyIdentity",
            "runtime",
            "radar-policy",
            "episode",
            "short-leg",
            Decimal("0.10"),
        )
        == "sha256:3d9a604d72459c3f0353f0a623c7f1f014ec0a24ff38a79975dd272f73e0a8dc"
    )


def test_exact_policy_chain_loads_before_runtime() -> None:
    chain = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-fixed-public-shadow-radar.json",
        underwriting_path=ROOT / "policies/short-vol-fixed-public-shadow-underwriting.json",
        position_path=ROOT / "policies/short-vol-fixed-public-shadow-position.json",
        radar_identity=RADAR_POLICY_IDENTITY,
        underwriting_identity=UNDERWRITING_POLICY_IDENTITY,
        position_identity=POSITION_POLICY_IDENTITY,
    )

    assert chain.identities == (
        RADAR_POLICY_IDENTITY,
        UNDERWRITING_POLICY_IDENTITY,
        POSITION_POLICY_IDENTITY,
    )
    assert chain.underwriting.target_base_quantity_btc == Decimal("0.1")
    assert chain.underwriting.future_cost_reserve_usdc == Decimal("12")
    assert chain.underwriting.maximum_component_pair_source_skew_ms == 6_000
    assert chain.underwriting.maximum_component_pair_receive_skew_ms == 4_000
    assert chain.position.maximum_component_pair_source_skew_ms == 6_000
    assert chain.position.maximum_component_pair_receive_skew_ms == 4_000
    assert chain.position.latest_exit_lead_ms == 1_800_000
    assert chain.position.underwriting_policy_identity == UNDERWRITING_POLICY_IDENTITY


def test_policy_loader_rejects_unknown_member_and_cross_identity(tmp_path: Path) -> None:
    underwriting = json.loads(
        (ROOT / "policies/short-vol-fixed-public-shadow-underwriting.json").read_text()
    )
    underwriting["admission_policy_identity"] = "sha256:" + "0" * 64
    changed = tmp_path / "underwriting.json"
    changed.write_text(json.dumps(underwriting), encoding="utf-8")

    with pytest.raises(PolicyChainError, match=r"exact keys|digest"):
        load_policy_chain(
            radar_path=ROOT / "policies/short-vol-fixed-public-shadow-radar.json",
            underwriting_path=changed,
            position_path=ROOT / "policies/short-vol-fixed-public-shadow-position.json",
            radar_identity=RADAR_POLICY_IDENTITY,
            underwriting_identity="sha256:" + "0" * 64,
            position_identity=POSITION_POLICY_IDENTITY,
        )


def _selection_economics(
    *,
    net_credit: str,
    payoff_cap: str,
    reserved_loss: str,
) -> EntryEconomics:
    net = Decimal(net_credit)
    payoff = Decimal(payoff_cap)
    return EntryEconomics(
        full_quantity_btc=Decimal("0.1"),
        required_side_total_quote_usdc=Decimal("1"),
        gross_entry_credit_usdc=net + Decimal("1"),
        entry_fee_reserve_usdc=Decimal("1"),
        net_entry_credit_usdc=net,
        width_usdc_per_btc=payoff / Decimal("0.1"),
        payoff_cap_usdc=payoff,
        contractual_payoff_max_loss_ex_fees_usdc=max(Decimal(0), payoff - net - 1),
        entry_fee_reserved_payoff_loss_usdc=max(Decimal(0), payoff - net),
        future_cost_reserve_usdc=Decimal("12"),
        underwriting_reserved_loss_usdc=Decimal(reserved_loss),
    )


def test_underwriting_margin_vector_reports_every_signed_predicate_distance() -> None:
    margins = underwriting_threshold_margins(
        economics=_selection_economics(
            net_credit="11",
            payoff_cap="100",
            reserved_loss="260",
        ),
        consumed_level_count=10_001,
        maximum_underwriting_reserved_loss_usdc=Decimal("250"),
        minimum_net_entry_credit_usdc=Decimal("15"),
        minimum_net_credit_to_payoff_cap_fraction=Decimal("0.1"),
        maximum_entry_consumed_level_count=10_000,
    )

    assert margins.failed_predicates == (
        "CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE",
        "UNDERWRITING_RESERVED_LOSS_LIMIT",
        "MINIMUM_NET_ENTRY_CREDIT",
        "ENTRY_CONSUMED_LEVEL_LIMIT",
    )
    assert margins.as_vector() == (
        {
            "predicate": "POSITIVE_NET_ENTRY_CREDIT",
            "signed_margin": "11",
            "unit": "USDC",
            "passes": True,
        },
        {
            "predicate": "CREDIT_ABOVE_FUTURE_COST_RESERVE",
            "signed_margin": "-1",
            "unit": "USDC",
            "passes": False,
        },
        {
            "predicate": "UNDERWRITING_RESERVED_LOSS_WITHIN_LIMIT",
            "signed_margin": "-10",
            "unit": "USDC",
            "passes": False,
        },
        {
            "predicate": "MINIMUM_NET_ENTRY_CREDIT",
            "signed_margin": "-4",
            "unit": "USDC",
            "passes": False,
        },
        {
            "predicate": "MINIMUM_NET_CREDIT_TO_PAYOFF_CAP",
            "signed_margin": "0.01",
            "unit": "FRACTION",
            "passes": True,
        },
        {
            "predicate": "ENTRY_CONSUMED_LEVEL_LIMIT",
            "signed_margin": -1,
            "unit": "LEVEL_COUNT",
            "passes": False,
        },
    )


def test_underwriting_selector_prefers_action_class_then_full_margin_vector() -> None:
    abstain_with_more_credit = UnderwritingComponentCandidate(
        long_instrument_name="BTC-LONG-ABSTAIN",
        economics=_selection_economics(
            net_credit="100",
            payoff_cap="1000",
            reserved_loss="912",
        ),
        consumed_level_count=2,
    )
    candidate = UnderwritingComponentCandidate(
        long_instrument_name="BTC-LONG-CANDIDATE",
        economics=_selection_economics(
            net_credit="20",
            payoff_cap="100",
            reserved_loss="92",
        ),
        consumed_level_count=2,
    )
    watch_b = UnderwritingComponentCandidate(
        long_instrument_name="BTC-LONG-WATCH-B",
        economics=_selection_economics(
            net_credit="14",
            payoff_cap="80",
            reserved_loss="78",
        ),
        consumed_level_count=2,
    )
    watch_a = replace(watch_b, long_instrument_name="BTC-LONG-WATCH-A")

    selection = select_underwriting_component(
        (abstain_with_more_credit, watch_b, candidate, watch_a),
        maximum_underwriting_reserved_loss_usdc=Decimal("250"),
        minimum_net_entry_credit_usdc=Decimal("15"),
        minimum_net_credit_to_payoff_cap_fraction=Decimal("0.1"),
        maximum_entry_consumed_level_count=10_000,
    )
    reordered = select_underwriting_component(
        (watch_a, candidate, watch_b, abstain_with_more_credit),
        maximum_underwriting_reserved_loss_usdc=Decimal("250"),
        minimum_net_entry_credit_usdc=Decimal("15"),
        minimum_net_credit_to_payoff_cap_fraction=Decimal("0.1"),
        maximum_entry_consumed_level_count=10_000,
    )
    watches = select_underwriting_component(
        (watch_b, watch_a),
        maximum_underwriting_reserved_loss_usdc=Decimal("250"),
        minimum_net_entry_credit_usdc=Decimal("15"),
        minimum_net_credit_to_payoff_cap_fraction=Decimal("0.1"),
        maximum_entry_consumed_level_count=10_000,
    )

    assert selection is not None
    assert selection.candidate.long_instrument_name == "BTC-LONG-CANDIDATE"
    assert selection.action.value == "CANDIDATE"
    assert selection.selection_rule_identity == UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY
    assert selection.candidate_protective_leg_count == 1
    assert reordered == selection
    assert watches is not None
    assert watches.candidate.long_instrument_name == "BTC-LONG-WATCH-A"
    assert watches.candidate_protective_leg_count == 0


def _component_leg_witness(
    *,
    role: ComponentLegRole,
    request_id: int,
    boundary: FactBoundary,
    sent_boundary: FactBoundary,
    source_timestamp_ms: int,
    global_continuity_epoch: int,
) -> RpcComponentLegRefreshWitness:
    origin = _boundary(1, 100)
    option_identity = "sha256:" + ("6" if role is ComponentLegRole.SHORT else "7") * 64
    instrument_name = "BTC-SHORT" if role is ComponentLegRole.SHORT else "BTC-LONG"
    params = {"instrument_name": instrument_name, "depth": 10000}
    source_identity = canonical_identity(
        "RpcComponentLegRefreshSourceIdentity",
        boundary.runtime_identity,
        request_id,
        role.value,
        "public/get_order_book",
        option_identity,
        params,
        origin.as_object(),
        sent_boundary.as_object(),
        global_continuity_epoch,
        11,
        source_timestamp_ms,
        boundary.as_object(),
    )
    return RpcComponentLegRefreshWitness(
        source_identity=source_identity,
        boundary=boundary,
        role=role,
        canonical_option_identity=option_identity,
        instrument_name=instrument_name,
        request_params=params,
        change_id=11,
        source_timestamp_ms=source_timestamp_ms,
        request_id=request_id,
        owner_origin_boundary=origin,
        sent_boundary=sent_boundary,
        global_continuity_epoch=global_continuity_epoch,
        response_covers_full_quantity=True,
    )


def test_component_pair_exposes_session_continuity_and_skew_unknown_reasons() -> None:
    short_sent = _boundary(2, 110)
    long_sent = replace(_boundary(3, 120), session_epoch=2)
    short = _component_leg_witness(
        role=ComponentLegRole.SHORT,
        request_id=41,
        boundary=_boundary(4, 130),
        sent_boundary=short_sent,
        source_timestamp_ms=1_000,
        global_continuity_epoch=7,
    )
    long = _component_leg_witness(
        role=ComponentLegRole.LONG,
        request_id=42,
        boundary=replace(_boundary(5, 5_500), session_epoch=2),
        sent_boundary=long_sent,
        source_timestamp_ms=8_000,
        global_continuity_epoch=8,
    )

    pair = component_pair_witness(short=short, long=long)

    assert pair.source_timestamp_skew_ms == 7_000
    assert pair.receive_skew_ms == 5_370
    assert pair.timing_unknown_reasons(
        maximum_source_skew_ms=6_000,
        maximum_receive_skew_ms=4_000,
    ) == (
        "COMPONENT_PAIR_SESSION_EPOCH_MISMATCH",
        "COMPONENT_PAIR_CONTINUITY_EPOCH_MISMATCH",
        "COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED",
        "COMPONENT_PAIR_RECEIVE_SKEW_EXCEEDED",
    )


def test_kind_registries_are_exact_and_disjoint() -> None:
    assert UNDERWRITING_OBJECT_KINDS == (
        "UNDERWRITING_AVAILABILITY_EVALUATION",
        "UNDERWRITING_ACTION",
        "CANDIDATE_ACTIVATION",
        "CANDIDATE_INVALIDATION",
        "ADMISSION_ATTEMPT_SCHEDULED",
        "ADMISSION_ATTEMPT_TERMINAL",
        "SHADOW_ENTRY",
        "POSITION_EVALUATION",
        "POSITION_ACTION",
        "CLOSE_QUOTE_EVALUATION",
        "POST_CLOSE_ATTEMPT_SCHEDULED",
        "POST_CLOSE_ATTEMPT_TERMINAL",
        "CLOSE_OPPORTUNITY_EVALUATION",
        "SHADOW_CLOSE_OPPORTUNITY",
    )
    assert OUTCOME_OBJECT_KINDS == (
        "SHADOW_OUTCOME_OBSERVATION",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
    )
    assert DECISION_CONTROL_OBJECT_KINDS == (
        "UNDERWRITING_DECISION_BATCH_DESIGNATION",
        "SELECTED_UNDERWRITING_DECISION",
        "UNDERWRITING_DECISION_CONTROL_ATTEMPT_SCHEDULED",
        "UNDERWRITING_DECISION_CONTROL_ATTEMPT_TERMINAL",
        "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN",
        "SELECTED_UNDERWRITING_DECISION_CONTROL_OUTCOME",
    )
    assert not set(UNDERWRITING_OBJECT_KINDS) & set(OUTCOME_OBJECT_KINDS)
    assert not set(UNDERWRITING_OBJECT_KINDS) & set(DECISION_CONTROL_OBJECT_KINDS)
    assert not set(OUTCOME_OBJECT_KINDS) & set(DECISION_CONTROL_OBJECT_KINDS)


def test_candidate_invalidation_uses_complete_total_order_and_is_terminal() -> None:
    assert len(CANDIDATE_INVALIDATION_REASONS) == 10
    primary, ordered = ordered_candidate_invalidation(
        {
            "FAILED_ADMISSION_EVALUATION_CONSUMED",
            "POSITION_SLOT_CONSUMED_BY_SHADOW_ENTRY",
            "RUNTIME_OR_CODE_IDENTITY_CHANGED",
        }
    )
    assert primary == "RUNTIME_OR_CODE_IDENTITY_CHANGED"
    assert ordered == (
        "RUNTIME_OR_CODE_IDENTITY_CHANGED",
        "POSITION_SLOT_CONSUMED_BY_SHADOW_ENTRY",
        "FAILED_ADMISSION_EVALUATION_CONSUMED",
    )
    state = CandidateState("sha256:" + "c" * 64)
    state.invalidate(ordered, _boundary(2))
    with pytest.raises(ValueError, match="terminal"):
        state.admit(_boundary(3))


@pytest.mark.parametrize("reason", CANDIDATE_INVALIDATION_REASONS)
def test_each_candidate_invalidation_reason_is_independently_terminal(reason: str) -> None:
    state = CandidateState("sha256:" + "c" * 64)
    boundary = _boundary(2)

    identity = state.invalidate((reason,), boundary)

    assert identity == canonical_identity(
        "CANDIDATE_INVALIDATION",
        state.candidate_identity,
        reason,
        (reason,),
        boundary.as_object(),
    )
    with pytest.raises(ValueError, match="terminal"):
        state.admit(_boundary(3))


def test_position_action_unknown_is_not_hold_and_close_latches_once() -> None:
    assert len(POSITION_CLOSE_REASONS) == 9
    state = PositionDecisionState(
        shadow_entry_identity="sha256:" + "2" * 64,
        position_policy_identity=POSITION_POLICY_IDENTITY,
        entry_boundary=_boundary(1),
    )
    unknown = state.evaluate(
        {reason: PredicateTruth.UNKNOWN for reason in POSITION_CLOSE_REASONS},
        _boundary(2),
        consumed_position_fact_fingerprint="sha256:" + "3" * 64,
    )
    assert unknown.serialized_action == "UNKNOWN"
    assert unknown.action_case_boundary == CaseFactBoundary(0, _boundary(2))
    assert unknown.action_fact_boundary == _boundary(2)

    close = state.evaluate(
        {
            reason: (
                PredicateTruth.TRUE
                if reason
                in {
                    "PATH_OR_JUMP_RISK_BOUNDARY_REACHED",
                    "ECONOMIC_EXIT_BOUNDARY_REACHED",
                }
                else PredicateTruth.FALSE
            )
            for reason in POSITION_CLOSE_REASONS
        },
        _boundary(3),
        consumed_position_fact_fingerprint="sha256:" + "4" * 64,
    )
    assert close.serialized_action == "CLOSE"
    assert close.primary_close_reason == "PATH_OR_JUMP_RISK_BOUNDARY_REACHED"
    first_identity = close.first_latched_close_action_identity

    later = state.evaluate(
        {
            reason: (
                PredicateTruth.TRUE
                if reason == "SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED"
                else PredicateTruth.FALSE
            )
            for reason in POSITION_CLOSE_REASONS
        },
        _boundary(4),
        consumed_position_fact_fingerprint="sha256:" + "5" * 64,
    )
    assert later.serialized_action == "CLOSE"
    assert later.first_latched_close_action_identity == first_identity
    assert later.primary_close_reason == "SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED"
    assert state.recovery_seed() == PositionDecisionRecoverySeed(
        first_latched_close_action_identity=first_identity,
        ordered_latched_close_reason_vector=(
            "PATH_OR_JUMP_RISK_BOUNDARY_REACHED",
            "ECONOMIC_EXIT_BOUNDARY_REACHED",
        ),
    )


def test_recovered_position_policy_restores_first_close_in_a_new_segment() -> None:
    entry = CaseFactBoundary(0, _boundary(1))
    baseline_fact = FactBoundary(
        code_identity="c" * 40,
        runtime_identity="sha256:" + "d" * 64,
        session_epoch=1,
        ingress_seq=10,
        received_monotonic_ms=10,
        causal_seq=10,
    )
    baseline = CaseFactBoundary(1, baseline_fact)
    seed = PositionDecisionRecoverySeed(
        first_latched_close_action_identity="sha256:" + "4" * 64,
        ordered_latched_close_reason_vector=(
            "PATH_OR_JUMP_RISK_BOUNDARY_REACHED",
            "ECONOMIC_EXIT_BOUNDARY_REACHED",
        ),
    )
    state = PositionDecisionState.recovered(
        shadow_entry_identity="sha256:" + "2" * 64,
        position_policy_identity=POSITION_POLICY_IDENTITY,
        entry_boundary=entry,
        segment_baseline_boundary=baseline,
        recovery_seed=seed,
    )
    all_false = {reason: PredicateTruth.FALSE for reason in POSITION_CLOSE_REASONS}

    with pytest.raises(ValueError, match="strictly after the recovery segment baseline"):
        state.evaluate(
            all_false,
            baseline_fact,
            consumed_position_fact_fingerprint="sha256:" + "5" * 64,
        )

    current_fact = replace(
        baseline_fact,
        ingress_seq=11,
        received_monotonic_ms=11,
        causal_seq=11,
    )
    decision = state.evaluate(
        all_false,
        current_fact,
        consumed_position_fact_fingerprint="sha256:" + "6" * 64,
    )

    assert decision.serialized_action == "CLOSE"
    assert decision.first_latched_close_action_identity == (
        seed.first_latched_close_action_identity
    )
    assert decision.ordered_latched_close_reason_vector == (
        seed.ordered_latched_close_reason_vector
    )
    assert decision.action_case_boundary == CaseFactBoundary(1, current_fact)
    assert decision.action_fact_boundary == current_fact
    assert state.recovery_seed() == seed


def test_gapped_segment_baseline_cannot_latch_close_or_synthesize_hold() -> None:
    entry = CaseFactBoundary(0, _boundary(1))
    baseline_fact = FactBoundary(
        code_identity="c" * 40,
        runtime_identity="sha256:" + "d" * 64,
        session_epoch=1,
        ingress_seq=1,
        received_monotonic_ms=1,
        causal_seq=1,
    )
    baseline = CaseFactBoundary(1, baseline_fact)
    with pytest.raises(ValueError, match="later Case segment"):
        PositionDecisionState.recovered(
            shadow_entry_identity="sha256:" + "2" * 64,
            position_policy_identity=POSITION_POLICY_IDENTITY,
            entry_boundary=entry,
            segment_baseline_boundary=CaseFactBoundary(0, _boundary(2)),
            recovery_seed=PositionDecisionRecoverySeed(),
        )
    state = PositionDecisionState.recovered(
        shadow_entry_identity="sha256:" + "2" * 64,
        position_policy_identity=POSITION_POLICY_IDENTITY,
        entry_boundary=entry,
        segment_baseline_boundary=baseline,
        recovery_seed=PositionDecisionRecoverySeed(),
    )
    baseline_truth = {
        reason: (
            PredicateTruth.TRUE
            if reason == "SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED"
            else PredicateTruth.FALSE
        )
        for reason in POSITION_CLOSE_REASONS
    }

    with pytest.raises(ValueError, match="strictly after the recovery segment baseline"):
        state.evaluate(
            baseline_truth,
            baseline,
            consumed_position_fact_fingerprint="sha256:" + "3" * 64,
        )
    assert state.recovery_seed() == PositionDecisionRecoverySeed()

    current_fact = replace(
        baseline_fact,
        ingress_seq=2,
        received_monotonic_ms=2,
        causal_seq=2,
    )
    decision = state.evaluate(
        {reason: PredicateTruth.FALSE for reason in POSITION_CLOSE_REASONS},
        CaseFactBoundary(1, current_fact),
        consumed_position_fact_fingerprint="sha256:" + "4" * 64,
    )

    assert decision.serialized_action == "HOLD"
    assert decision.first_latched_close_action_identity is None


def test_position_recovery_seed_rejects_incomplete_or_noncanonical_close_state() -> None:
    reason = "PATH_OR_JUMP_RISK_BOUNDARY_REACHED"
    with pytest.raises(ValueError, match="require the first CLOSE identity"):
        PositionDecisionRecoverySeed(
            ordered_latched_close_reason_vector=(reason,),
        )
    with pytest.raises(ValueError, match="requires at least one latched reason"):
        PositionDecisionRecoverySeed(
            first_latched_close_action_identity="sha256:" + "2" * 64,
        )
    with pytest.raises(ValueError, match="canonically ordered"):
        PositionDecisionRecoverySeed(
            first_latched_close_action_identity="sha256:" + "2" * 64,
            ordered_latched_close_reason_vector=(
                "ECONOMIC_EXIT_BOUNDARY_REACHED",
                reason,
            ),
        )


@pytest.mark.parametrize("reason", POSITION_CLOSE_REASONS)
def test_each_position_close_reason_independently_latches_close(reason: str) -> None:
    state = PositionDecisionState(
        shadow_entry_identity="sha256:" + "2" * 64,
        position_policy_identity=POSITION_POLICY_IDENTITY,
        entry_boundary=_boundary(1),
    )

    decision = state.evaluate(
        {
            candidate: PredicateTruth.TRUE if candidate == reason else PredicateTruth.FALSE
            for candidate in POSITION_CLOSE_REASONS
        },
        _boundary(2),
        consumed_position_fact_fingerprint="sha256:" + "3" * 64,
    )

    assert decision.serialized_action == "CLOSE"
    assert decision.primary_close_reason == reason
    assert decision.ordered_latched_close_reason_vector == (reason,)


def test_entry_and_close_economics_preserve_signs_and_public_fee_reserve() -> None:
    entry = compute_entry_economics(
        direction="SELL",
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=((Decimal("200"), Decimal("0.04")), (Decimal("190"), Decimal("0.06"))),
        index_usdc_per_btc=Decimal("100000"),
        short_strike_usdc_per_btc=Decimal("110000"),
        long_strike_usdc_per_btc=Decimal("120000"),
        fee_rate_index_fraction=Decimal("0.0003"),
        future_cost_reserve_usdc=Decimal("12"),
    )
    assert entry.gross_entry_credit_usdc == Decimal("19.4")
    assert entry.entry_fee_reserve_usdc == Decimal("3")
    assert entry.net_entry_credit_usdc == Decimal("16.4")
    assert entry.payoff_cap_usdc == Decimal("1000")
    assert entry.actual_all_in_max_loss_usdc is None

    close = compute_close_economics(
        direction="BUY",
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=((Decimal("50"), Decimal("0.1")),),
        index_usdc_per_btc=Decimal("100000"),
        fee_rate_index_fraction=Decimal("0.0003"),
        net_entry_credit_usdc=entry.net_entry_credit_usdc,
    )
    assert close.gross_close_cashflow_usdc == Decimal("-5")
    assert close.close_fee_reserve_usdc == Decimal("3")
    assert close.net_close_cashflow_usdc == Decimal("-8")
    assert close.projected_shadow_net_pnl_usdc == Decimal("8.4")

    closing_credit = compute_close_economics(
        direction="BUY",
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=((Decimal("-50"), Decimal("0.1")),),
        index_usdc_per_btc=Decimal("100000"),
        fee_rate_index_fraction=Decimal("0.0003"),
        net_entry_credit_usdc=entry.net_entry_credit_usdc,
    )
    assert closing_credit.required_close_side_total_quote_usdc == Decimal("-5")
    assert closing_credit.gross_close_cashflow_usdc == Decimal("5")
    assert closing_credit.close_fee_reserve_usdc == Decimal("3")
    assert closing_credit.net_close_cashflow_usdc == Decimal("2")
    assert closing_credit.net_close_debit_usdc == Decimal("0")
    assert closing_credit.projected_shadow_net_pnl_usdc == Decimal("18.4")
    assert closing_credit.projected_net_loss_usdc == Decimal("0")


@pytest.mark.parametrize(
    (
        "direction",
        "price",
        "required_total",
        "gross",
        "net",
        "debit",
        "projected",
        "loss",
    ),
    (
        ("BUY", "-50", "-5", "5", "2", "0", "3", "0"),
        ("BUY", "50", "5", "-5", "-8", "8", "-7", "7"),
        ("SELL", "-50", "-5", "-5", "-8", "8", "-7", "7"),
        ("SELL", "50", "5", "5", "2", "0", "3", "0"),
    ),
)
def test_close_economics_preserves_all_signed_combo_orientations(
    direction: str,
    price: str,
    required_total: str,
    gross: str,
    net: str,
    debit: str,
    projected: str,
    loss: str,
) -> None:
    close = compute_close_economics(
        direction=direction,
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=((Decimal(price), Decimal("0.1")),),
        index_usdc_per_btc=Decimal("100000"),
        fee_rate_index_fraction=Decimal("0.0003"),
        net_entry_credit_usdc=Decimal("1"),
    )

    assert close.required_close_side_total_quote_usdc == Decimal(required_total)
    assert close.gross_close_cashflow_usdc == Decimal(gross)
    assert close.net_close_cashflow_usdc == Decimal(net)
    assert close.net_close_debit_usdc == Decimal(debit)
    assert close.projected_shadow_net_pnl_usdc == Decimal(projected)
    assert close.projected_net_loss_usdc == Decimal(loss)


def test_entry_economics_accepts_only_signed_orientation_with_positive_credit() -> None:
    entry = compute_entry_economics(
        direction="BUY",
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=((Decimal("-200"), Decimal("0.1")),),
        index_usdc_per_btc=Decimal("100000"),
        short_strike_usdc_per_btc=Decimal("110000"),
        long_strike_usdc_per_btc=Decimal("120000"),
        fee_rate_index_fraction=Decimal("0.0003"),
        future_cost_reserve_usdc=Decimal("12"),
    )
    assert entry.required_side_total_quote_usdc == Decimal("-20")
    assert entry.gross_entry_credit_usdc == Decimal("20")

    with pytest.raises(ValueError, match="positive gross credit"):
        compute_entry_economics(
            direction="BUY",
            full_quantity_btc=Decimal("0.1"),
            consumed_levels=((Decimal("200"), Decimal("0.1")),),
            index_usdc_per_btc=Decimal("100000"),
            short_strike_usdc_per_btc=Decimal("110000"),
            long_strike_usdc_per_btc=Decimal("120000"),
            fee_rate_index_fraction=Decimal("0.0003"),
            future_cost_reserve_usdc=Decimal("12"),
        )


def test_case_fact_boundary_orders_within_and_across_observation_segments() -> None:
    entry = CaseFactBoundary(0, _boundary(10))
    same_segment_later = CaseFactBoundary(0, _boundary(11))
    next_segment = CaseFactBoundary(
        1,
        FactBoundary(
            code_identity="c" * 40,
            runtime_identity="sha256:" + "d" * 64,
            session_epoch=1,
            ingress_seq=0,
            received_monotonic_ms=1,
            causal_seq=0,
        ),
    )

    assert same_segment_later.is_strictly_after(entry)
    assert next_segment.is_strictly_after(same_segment_later)
    assert not entry.is_strictly_after(next_segment)
    with pytest.raises(ValueError, match="runtime/code identity mismatch"):
        CaseFactBoundary(0, next_segment.fact_boundary).is_strictly_after(entry)
    with pytest.raises(ValueError, match="segment_sequence"):
        CaseFactBoundary(True, _boundary(1))


def test_outcome_terminal_order_is_exit_then_natural_without_process_censoring() -> None:
    reducer = OutcomeReducer(entry_boundary=CaseFactBoundary(0, _boundary(1)))
    reducer.latch_close("sha256:" + "d" * 64, CaseFactBoundary(0, _boundary(2)))
    result = reducer.settle(
        boundary=CaseFactBoundary(0, _boundary(3)),
        eligible_exit_identity="sha256:" + "e" * 64,
        ordinary_attempt_terminal=True,
        lifecycle_ready=True,
    )
    assert result is OutcomeState.MATURE_KNOWN
    assert reducer.settle(boundary=CaseFactBoundary(1, _boundary(1))) is result

    natural = OutcomeReducer(entry_boundary=CaseFactBoundary(0, _boundary(1)))
    natural.latch_close("sha256:" + "f" * 64, CaseFactBoundary(0, _boundary(2)))
    assert (
        natural.settle(
            boundary=CaseFactBoundary(1, _boundary(1)),
            ordinary_attempt_terminal=True,
            lifecycle_ready=True,
        )
        is OutcomeState.MATURE_UNKNOWN
    )


def test_admission_schedules_one_rpc_and_consumes_every_terminal_race() -> None:
    combo_identity = "sha256:" + "7" * 64
    instrument_name = "BTC-TEST-COMBO"
    params = {"instrument_name": instrument_name, "depth": 10000}
    attempt = AdmissionAttempt.schedule(
        candidate_identity="sha256:" + "6" * 64,
        canonical_combo_identity=combo_identity,
        request_id=7,
        boundary=_boundary(2),
        request_instrument_name=instrument_name,
    )
    intent = attempt.take_request_intent()
    assert intent is not None
    assert intent.method == "public/get_order_book"
    assert intent.params == {
        "instrument_name": instrument_name,
        "depth": 10000,
    }
    assert attempt.take_request_intent() is None
    assert attempt.mark_sent(request_id=7, boundary=_boundary(3), send_budget_ms=30)
    response_boundary = _boundary(4)
    rpc_witness = RpcAdmissionRefreshWitness(
        source_identity=canonical_identity(
            "RpcAdmissionRefreshSourceIdentity",
            response_boundary.runtime_identity,
            7,
            "public/get_order_book",
            combo_identity,
            params,
            _boundary(2).as_object(),
            _boundary(3).as_object(),
            11,
            400,
            response_boundary.as_object(),
        ),
        boundary=response_boundary,
        canonical_combo_identity=combo_identity,
        instrument_name=instrument_name,
        request_params=params,
        change_id=11,
        source_timestamp_ms=400,
        request_id=7,
        candidate_origin_boundary=_boundary(2),
        sent_boundary=_boundary(3),
        market_frontier_change_id=11,
        market_frontier_session_epoch=1,
        response_matches_frontier=True,
        response_covers_full_quantity=True,
    )
    assert attempt.accept_response(
        witness=rpc_witness,
        response_budget_ms=30,
        classification=RefreshClassification.COMPLETE_CANDIDATE,
    )
    assert attempt.terminal_outcome is AdmissionTerminalOutcome.ENTRY_EMITTED
    terminal_identity = attempt.terminal_identity

    candidate_boundary = _boundary(1)
    candidate_witness = SubscriptionAdmissionRefreshWitness(
        source_identity=canonical_identity(
            "SubscriptionAdmissionRefreshSourceIdentity",
            candidate_boundary.runtime_identity,
            1,
            1,
            combo_identity,
            "snapshot",
            None,
            10,
            100,
            candidate_boundary.as_object(),
        ),
        boundary=candidate_boundary,
        canonical_combo_identity=combo_identity,
        instrument_name=instrument_name,
        change_id=10,
        source_timestamp_ms=100,
        snapshot_kind="snapshot",
        session_epoch=1,
        subscription_generation=1,
    )
    later_boundary = _boundary(5)
    later_witness = SubscriptionAdmissionRefreshWitness(
        source_identity=canonical_identity(
            "SubscriptionAdmissionRefreshSourceIdentity",
            later_boundary.runtime_identity,
            1,
            1,
            combo_identity,
            "change",
            10,
            11,
            500,
            later_boundary.as_object(),
        ),
        boundary=later_boundary,
        canonical_combo_identity=combo_identity,
        instrument_name=instrument_name,
        change_id=11,
        source_timestamp_ms=500,
        snapshot_kind="change",
        session_epoch=1,
        subscription_generation=1,
        prev_change_id=10,
    )
    assert not attempt.accept_subscription_refresh(
        witness=later_witness,
        candidate_quote_witness=candidate_witness,
        classification=RefreshClassification.COMPLETE_CANDIDATE,
    )
    assert attempt.terminal_identity == terminal_identity

    failed = AdmissionAttempt.schedule(
        candidate_identity="sha256:" + "a" * 64,
        canonical_combo_identity="sha256:" + "b" * 64,
        request_id=8,
        boundary=_boundary(2),
        request_instrument_name="BTC-FAILED-COMBO",
    )
    failed.take_request_intent()
    failed.mark_sent(request_id=8, boundary=_boundary(3), send_budget_ms=30)
    failed.fail_request(
        request_id=8,
        source_identity="sha256:" + "c" * 64,
        boundary=_boundary(4),
    )
    assert failed.terminal_outcome is AdmissionTerminalOutcome.UNKNOWN_CONSUMED


def test_admission_late_or_truncated_rpc_consumes_attempt_without_entry() -> None:
    candidate_identity = "sha256:" + "1" * 64
    combo_identity = "sha256:" + "2" * 64
    instrument_name = "BTC-LATE-COMBO"
    late_send = AdmissionAttempt.schedule(
        candidate_identity=candidate_identity,
        canonical_combo_identity=combo_identity,
        request_id=20,
        boundary=_boundary(1, 100),
        request_instrument_name=instrument_name,
    )
    late_send.take_request_intent()
    assert late_send.mark_sent(
        request_id=20,
        boundary=_boundary(2, 131),
        send_budget_ms=30,
    )
    assert late_send.sent_boundary is None
    assert late_send.terminal_outcome is AdmissionTerminalOutcome.UNKNOWN_CONSUMED

    origin = _boundary(1, 100)
    sent = _boundary(2, 110)
    response = _boundary(3, 120)
    params = {"instrument_name": instrument_name, "depth": 10000}
    truncated = AdmissionAttempt.schedule(
        candidate_identity=candidate_identity,
        canonical_combo_identity=combo_identity,
        request_id=21,
        boundary=origin,
        request_instrument_name=instrument_name,
    )
    truncated.take_request_intent()
    assert truncated.mark_sent(
        request_id=21,
        boundary=sent,
        send_budget_ms=30,
    )
    witness = RpcAdmissionRefreshWitness(
        source_identity=canonical_identity(
            "RpcAdmissionRefreshSourceIdentity",
            response.runtime_identity,
            21,
            "public/get_order_book",
            combo_identity,
            params,
            origin.as_object(),
            sent.as_object(),
            12,
            500,
            response.as_object(),
        ),
        boundary=response,
        canonical_combo_identity=combo_identity,
        instrument_name=instrument_name,
        request_params=params,
        change_id=12,
        source_timestamp_ms=500,
        request_id=21,
        candidate_origin_boundary=origin,
        sent_boundary=sent,
        market_frontier_change_id=12,
        market_frontier_session_epoch=response.session_epoch,
        response_matches_frontier=True,
        response_covers_full_quantity=False,
    )
    assert truncated.accept_response(
        witness=witness,
        response_budget_ms=30,
        classification=RefreshClassification.COMPLETE_CANDIDATE,
    )
    assert truncated.terminal_outcome is AdmissionTerminalOutcome.UNKNOWN_CONSUMED


def test_owner_candidate_to_subscription_admission_round_trip(tmp_path: Path) -> None:
    owner, bindings = _owner(tmp_path)
    origin_facts = _underwriting_facts(
        boundary=_boundary(1, 110),
        change_id=10,
        previous_change_id=None,
        snapshot_kind="snapshot",
    )
    transition = owner.settle_underwriting(
        (origin_facts,),
        allocate_request_id=lambda: 41,
    )
    assert [intent.request_id for intent in transition.request_intents] == [41]
    assert [item.object_kind for item in transition.emitted] == [
        "UNDERWRITING_AVAILABILITY_EVALUATION",
        "UNDERWRITING_ACTION",
        "CANDIDATE_ACTIVATION",
        "ADMISSION_ATTEMPT_SCHEDULED",
    ]
    candidate_identity = next(
        item.object_identity
        for item in transition.emitted
        if item.object_kind == "CANDIDATE_ACTIVATION"
    )
    assert candidate_identity.startswith("sha256:")
    owner.note_request_sent(
        request_id=41,
        boundary=_boundary(2, 120),
    )
    refreshed = _underwriting_facts(
        boundary=_boundary(3, 130),
        change_id=11,
        previous_change_id=10,
        snapshot_kind="change",
    )
    admitted = owner.settle_underwriting(
        (refreshed,),
        allocate_request_id=lambda: 42,
    )
    assert [item.object_kind for item in admitted.emitted] == [
        "ADMISSION_ATTEMPT_TERMINAL",
        "SHADOW_ENTRY",
        "SHADOW_OUTCOME_OBSERVATION",
    ]
    assert owner.required_combo_instrument_names == ("BTC-TEST-COMBO",)
    objects = _written_objects(tmp_path, bindings=bindings)
    assert {value["object_kind"] for value in objects.values()} == {
        "UNDERWRITING_AVAILABILITY_EVALUATION",
        "UNDERWRITING_ACTION",
        "CANDIDATE_ACTIVATION",
        "ADMISSION_ATTEMPT_SCHEDULED",
        "ADMISSION_ATTEMPT_TERMINAL",
        "SHADOW_ENTRY",
        "SHADOW_OUTCOME_OBSERVATION",
    }


def test_owner_treats_negative_public_commission_as_unknown(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    facts = replace(
        _underwriting_facts(
            boundary=_boundary(1, 110),
            change_id=10,
            previous_change_id=None,
            snapshot_kind="snapshot",
        ),
        short_leg_taker_commission_fraction=Decimal("-0.0001"),
    )

    transition = owner.settle_underwriting((facts,), allocate_request_id=lambda: 41)

    assert [item.object_kind for item in transition.emitted] == [
        "UNDERWRITING_AVAILABILITY_EVALUATION"
    ]
    objects = _written_objects(tmp_path, bindings=bindings)
    availability = next(iter(objects.values()))
    assert _object(availability["payload"])["availability"] == "UNKNOWN"


def test_owner_rejects_initial_target_quantity_mismatch_before_any_write(
    tmp_path: Path,
) -> None:
    owner, _bindings = _owner(tmp_path)
    facts = replace(
        _underwriting_facts(
            boundary=_boundary(1, 110),
            change_id=10,
            previous_change_id=None,
            snapshot_kind="snapshot",
        ),
        target_quantity_btc=Decimal("0.2"),
        entry_consumed_levels=((Decimal("300"), Decimal("0.2")),),
    )

    with pytest.raises(RuntimeError, match="target quantity"):
        owner.settle_underwriting((facts,), allocate_request_id=lambda: 41)

    assert owner.state_store.objects == ()


def test_owner_rejects_refresh_target_quantity_mismatch_without_consuming_candidate(
    tmp_path: Path,
) -> None:
    owner, _bindings = _owner(tmp_path)
    origin = _underwriting_facts(
        boundary=_boundary(1, 110),
        change_id=10,
        previous_change_id=None,
        snapshot_kind="snapshot",
    )
    activated = owner.settle_underwriting((origin,), allocate_request_id=lambda: 41)
    candidate_identity = next(
        item.object_identity
        for item in activated.emitted
        if item.object_kind == "CANDIDATE_ACTIVATION"
    )
    before = tuple(owner.state_store.objects)
    refreshed = replace(
        _underwriting_facts(
            boundary=_boundary(2, 120),
            change_id=11,
            previous_change_id=10,
            snapshot_kind="change",
        ),
        target_quantity_btc=Decimal("0.2"),
        entry_consumed_levels=((Decimal("300"), Decimal("0.2")),),
    )
    witness = refreshed.quote_refresh_witness
    assert witness is not None

    with pytest.raises(RuntimeError, match="target quantity"):
        owner.settle_admission(
            candidate_identity=candidate_identity,
            refreshed_facts=refreshed,
            refresh_witness=witness,
        )

    assert tuple(owner.state_store.objects) == before


def test_owner_explicit_unknown_reasons_prevent_economic_action(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    facts = replace(
        _underwriting_facts(
            boundary=_boundary(1, 110),
            change_id=10,
            previous_change_id=None,
            snapshot_kind="snapshot",
        ),
        unknown_reasons=("INDEX_SOURCE_UNKNOWN",),
    )

    transition = owner.settle_underwriting((facts,), allocate_request_id=lambda: 41)

    assert [item.object_kind for item in transition.emitted] == [
        "UNDERWRITING_AVAILABILITY_EVALUATION"
    ]
    assert transition.request_intents == ()
    objects = _written_objects(tmp_path, bindings=bindings)
    payload = _object(next(iter(objects.values()))["payload"])
    assert payload["availability"] == "UNKNOWN"
    assert payload["unknown_reasons"] == ["INDEX_SOURCE_UNKNOWN"]


def test_owner_action_carries_complete_margin_truth_beyond_primary_blocker(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    facts = replace(
        _underwriting_facts(
            boundary=_boundary(1, 110),
            change_id=10,
            previous_change_id=None,
            snapshot_kind="snapshot",
        ),
        entry_consumed_levels=((Decimal("150"), Decimal("0.1")),),
    )

    owner.settle_underwriting((facts,), allocate_request_id=lambda: 41)

    action = next(
        value
        for value in _written_objects(tmp_path, bindings=bindings).values()
        if value["object_kind"] == "UNDERWRITING_ACTION"
    )
    payload = _object(action["payload"])
    assert payload["economic_action"] == "ABSTAIN"
    assert payload["decision_blockers"] == ["CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE"]
    assert payload["failed_predicates"] == [
        "CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE",
        "MINIMUM_NET_ENTRY_CREDIT",
    ]
    vector = payload["predicate_margin_vector"]
    assert isinstance(vector, list)
    assert len(vector) == 6
    assert payload["selected_long_leg_instrument_name"] == "BTC-LONG"


def test_owner_unknown_refresh_invalidates_candidate_before_admission(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    origin = _underwriting_facts(
        boundary=_boundary(1, 110),
        change_id=10,
        previous_change_id=None,
        snapshot_kind="snapshot",
    )
    owner.settle_underwriting((origin,), allocate_request_id=lambda: 41)
    refreshed = replace(
        _underwriting_facts(
            boundary=_boundary(2, 120),
            change_id=11,
            previous_change_id=10,
            snapshot_kind="change",
        ),
        unknown_reasons=("COMBO_BOOK_SOURCE_UNKNOWN",),
    )

    transition = owner.settle_underwriting((refreshed,), allocate_request_id=lambda: 42)

    assert [item.object_kind for item in transition.emitted] == [
        "ADMISSION_ATTEMPT_TERMINAL",
        "CANDIDATE_INVALIDATION",
    ]
    objects = _written_objects(tmp_path, bindings=bindings)
    kinds = {value["object_kind"] for value in objects.values()}
    assert "SHADOW_ENTRY" not in kinds
    terminal = next(
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "ADMISSION_ATTEMPT_TERMINAL"
    )
    invalidation = next(
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "CANDIDATE_INVALIDATION"
    )
    assert terminal["terminal_outcome"] == "KNOWN_INVALIDATED_BEFORE_REFRESH"
    assert invalidation["primary_reason"] == (
        "SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN"
    )


def test_owner_opens_admitted_observation_without_online_cohort_membership(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)

    _admit_owner(owner)

    objects = _written_objects(tmp_path, bindings=bindings)
    observation = next(
        value for value in objects.values() if value["object_kind"] == "SHADOW_OUTCOME_OBSERVATION"
    )
    assert "cohort_enrolled" not in _object(observation["payload"])
    assert not any(
        value["object_kind"] == "ALIGNED_POLICY_NO_TRADE_PAIR" for value in objects.values()
    )


def test_owner_emits_slot_consumed_availability_after_entry(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    _admit_owner(owner)
    after_entry = _underwriting_facts(
        boundary=_boundary(4, 140),
        change_id=12,
        previous_change_id=11,
        snapshot_kind="change",
    )

    transition = owner.settle_underwriting(
        (after_entry,),
        allocate_request_id=lambda: 42,
    )

    assert [item.object_kind for item in transition.emitted] == [
        "UNDERWRITING_AVAILABILITY_EVALUATION"
    ]
    emitted_identity = transition.emitted[0].object_identity
    objects = _written_objects(tmp_path, bindings=bindings)
    payload = _object(objects[emitted_identity]["payload"])
    assert payload["availability"] == "NOT_EVALUATED"


def test_owner_first_close_then_strictly_future_subscription_exit_round_trip(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)

    first_close = owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    assert [item.object_kind for item in first_close.emitted] == [
        "POSITION_EVALUATION",
        "POSITION_ACTION",
        "POST_CLOSE_ATTEMPT_SCHEDULED",
        "CLOSE_QUOTE_EVALUATION",
    ]
    assert [intent.request_id for intent in first_close.request_intents] == [42]

    future = owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=_boundary(5, 150),
            change_id=13,
            previous_change_id=12,
        ),
        allocate_request_id=lambda: 43,
    )
    assert [item.object_kind for item in future.emitted] == [
        "CLOSE_QUOTE_EVALUATION",
        "POST_CLOSE_ATTEMPT_TERMINAL",
        "CLOSE_OPPORTUNITY_EVALUATION",
        "SHADOW_CLOSE_OPPORTUNITY",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
    ]
    assert future.request_intents == ()
    objects = _written_objects(tmp_path, bindings=bindings)
    assert (
        sum(value["object_kind"] == "SHADOW_COUNTERFACTUAL_EXIT" for value in objects.values()) == 1
    )
    assert sum(value["object_kind"] == "SHADOW_OUTCOME" for value in objects.values()) == 1


def test_owner_matches_equal_distinct_first_close_subscription_witnesses(
    tmp_path: Path,
) -> None:
    owner, _bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    first_close_facts = _position_facts(
        boundary=_boundary(4, 140),
        change_id=12,
        previous_change_id=11,
    )
    quote_witness = cast(
        SubscriptionAdmissionRefreshWitness,
        first_close_facts.quote_refresh_witness,
    )
    distinct_origin_witness = replace(quote_witness)
    assert distinct_origin_witness == quote_witness
    assert distinct_origin_witness is not quote_witness
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            first_close_facts,
            current_combo_subscription_witness=distinct_origin_witness,
        ),
        allocate_request_id=lambda: 42,
    )

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=_boundary(5, 150),
            change_id=13,
            previous_change_id=12,
        ),
        allocate_request_id=lambda: 43,
    )

    assert {
        "POST_CLOSE_ATTEMPT_TERMINAL",
        "CLOSE_QUOTE_EVALUATION",
        "SHADOW_CLOSE_OPPORTUNITY",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
    }.issubset(item.object_kind for item in transition.emitted)


def test_owner_does_not_promote_retained_first_close_quote_on_a_later_tick(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    first_close_facts = _position_facts(
        boundary=_boundary(4, 140),
        change_id=12,
        previous_change_id=11,
    )
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=first_close_facts,
        allocate_request_id=lambda: 42,
    )

    later = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            first_close_facts,
            boundary=_boundary(5, 150),
            trusted_time_lower_ms=1_000_102,
            trusted_time_upper_ms=1_000_103,
            quote_refresh_witness=None,
        ),
        allocate_request_id=lambda: 43,
    )

    forbidden = {
        "CLOSE_QUOTE_EVALUATION",
        "POST_CLOSE_ATTEMPT_TERMINAL",
        "CLOSE_OPPORTUNITY_EVALUATION",
        "SHADOW_CLOSE_OPPORTUNITY",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
    }
    assert not forbidden.intersection(item.object_kind for item in later.emitted)
    objects = _written_objects(tmp_path, bindings=bindings)
    kinds = [value["object_kind"] for value in objects.values()]
    assert kinds.count("CLOSE_QUOTE_EVALUATION") == 1
    assert "POST_CLOSE_ATTEMPT_TERMINAL" not in kinds
    assert "CLOSE_OPPORTUNITY_EVALUATION" not in kinds
    assert "SHADOW_CLOSE_OPPORTUNITY" not in kinds
    assert "SHADOW_COUNTERFACTUAL_EXIT" not in kinds
    assert "SHADOW_OUTCOME" not in kinds


def test_owner_does_not_promote_a_malformed_post_close_rpc_payload(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    first_close_boundary = _boundary(4, 140)
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=first_close_boundary,
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    sent_boundary = _boundary(5, 145)
    owner.note_request_sent(request_id=42, boundary=sent_boundary)
    response_boundary = _boundary(6, 150)
    combo_identity = "sha256:" + "3" * 64
    instrument_name = "BTC-TEST-COMBO"
    params = {"instrument_name": instrument_name, "depth": 10000}
    response_identity = canonical_identity(
        "RpcAdmissionRefreshSourceIdentity",
        response_boundary.runtime_identity,
        42,
        "public/get_order_book",
        combo_identity,
        params,
        first_close_boundary.as_object(),
        sent_boundary.as_object(),
        13,
        2_013,
        response_boundary.as_object(),
    )
    witness = RpcAdmissionRefreshWitness(
        source_identity=response_identity,
        boundary=response_boundary,
        canonical_combo_identity=combo_identity,
        instrument_name=instrument_name,
        request_params=params,
        change_id=13,
        source_timestamp_ms=2_013,
        request_id=42,
        candidate_origin_boundary=first_close_boundary,
        sent_boundary=sent_boundary,
        market_frontier_change_id=13,
        market_frontier_session_epoch=response_boundary.session_epoch,
        response_matches_frontier=True,
        response_covers_full_quantity=True,
        payload_matches_request=False,
        payload_well_formed=True,
    )
    facts = _position_facts(
        boundary=response_boundary,
        change_id=13,
        previous_change_id=12,
    )

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            facts,
            quote_source=SourceFact(response_identity, response_boundary),
            quote_refresh_witness=witness,
        ),
        allocate_request_id=lambda: 43,
    )

    forbidden = {
        "CLOSE_QUOTE_EVALUATION",
        "SHADOW_CLOSE_OPPORTUNITY",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
    }
    assert not forbidden.intersection(item.object_kind for item in transition.emitted)
    objects = _written_objects(tmp_path, bindings=bindings)
    terminal = next(
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "POST_CLOSE_ATTEMPT_TERMINAL"
    )
    assert terminal["terminal_status"] == "ERROR"
    assert terminal["matched_response_identity"] is None
    opportunities = [
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "CLOSE_OPPORTUNITY_EVALUATION"
    ]
    assert len(opportunities) == 1
    assert opportunities[0]["close_quote_evaluation_identity"] is None
    assert (
        opportunities[0]["attempt_terminal_identity"]
        == terminal["post_close_attempt_terminal_identity"]
    )
    assert opportunities[0]["eligibility"] == "UNKNOWN"


@pytest.mark.parametrize(
    (
        "snapshot_kind",
        "change_id",
        "previous_change_id",
        "subscription_generation",
        "session_epoch",
    ),
    (
        ("snapshot", 12, None, 1, 1),
        ("snapshot", 11, None, 1, 1),
        ("change", 13, 12, 2, 1),
        ("change", 13, 12, 1, 2),
        ("change", 13, 11, 1, 1),
    ),
)
def test_owner_rejects_unqualified_subscription_after_post_close_rpc_error(
    tmp_path: Path,
    snapshot_kind: str,
    change_id: int,
    previous_change_id: int | None,
    subscription_generation: int,
    session_epoch: int,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    owner.note_request_failure(
        request_id=42,
        boundary=_boundary(5, 145),
    )
    boundary = replace(_boundary(6, 150), session_epoch=session_epoch)
    witness = _position_subscription_witness(
        boundary=boundary,
        change_id=change_id,
        previous_change_id=previous_change_id,
        snapshot_kind=snapshot_kind,
        subscription_generation=subscription_generation,
    )
    facts = _position_facts(
        boundary=boundary,
        change_id=13,
        previous_change_id=12,
    )

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            facts,
            quote_source=SourceFact(witness.source_identity, boundary),
            quote_refresh_witness=witness,
            current_combo_subscription_witness=witness,
        ),
        allocate_request_id=lambda: 43,
    )

    forbidden = {
        "CLOSE_QUOTE_EVALUATION",
        "CLOSE_OPPORTUNITY_EVALUATION",
        "SHADOW_CLOSE_OPPORTUNITY",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
    }
    assert not forbidden.intersection(item.object_kind for item in transition.emitted)
    objects = _written_objects(tmp_path, bindings=bindings)
    kinds = [value["object_kind"] for value in objects.values()]
    assert kinds.count("CLOSE_QUOTE_EVALUATION") == 1
    assert kinds.count("CLOSE_OPPORTUNITY_EVALUATION") == 1
    assert "SHADOW_CLOSE_OPPORTUNITY" not in kinds
    assert "SHADOW_COUNTERFACTUAL_EXIT" not in kinds
    assert "SHADOW_OUTCOME" not in kinds


@pytest.mark.parametrize(
    (
        "snapshot_kind",
        "change_id",
        "previous_change_id",
        "subscription_generation",
        "session_epoch",
    ),
    (
        ("change", 13, 12, 1, 1),
        ("snapshot", 1, None, 2, 1),
        ("snapshot", 1, None, 1, 2),
    ),
)
def test_owner_accepts_valid_subscription_after_post_close_rpc_error(
    tmp_path: Path,
    snapshot_kind: str,
    change_id: int,
    previous_change_id: int | None,
    subscription_generation: int,
    session_epoch: int,
) -> None:
    owner, _bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    owner.note_request_failure(
        request_id=42,
        boundary=_boundary(5, 145),
    )
    boundary = replace(_boundary(6, 150), session_epoch=session_epoch)
    witness = _position_subscription_witness(
        boundary=boundary,
        change_id=change_id,
        previous_change_id=previous_change_id,
        snapshot_kind=snapshot_kind,
        subscription_generation=subscription_generation,
    )
    facts = _position_facts(
        boundary=boundary,
        change_id=13,
        previous_change_id=12,
    )

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            facts,
            quote_source=SourceFact(witness.source_identity, boundary),
            quote_refresh_witness=witness,
            current_combo_subscription_witness=witness,
        ),
        allocate_request_id=lambda: 43,
    )

    assert {
        "CLOSE_QUOTE_EVALUATION",
        "SHADOW_CLOSE_OPPORTUNITY",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
    }.issubset(item.object_kind for item in transition.emitted)


def test_owner_accepts_snapshot_after_not_requestable_first_close(
    tmp_path: Path,
) -> None:
    owner, _bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    first_close = _quiet_position_facts(boundary=_boundary(4, 140))
    first_close = replace(
        first_close,
        current_short_delta=Decimal("0.6"),
        close_quote_facts=CloseQuoteFacts(
            option_availability=CloseOptionAvailability.UNKNOWN,
            atomic_availability=CloseAtomicAvailability.UNKNOWN,
            component_reference=PredicateTruth.UNKNOWN,
            book_availability=CloseBookAvailability.UNKNOWN,
            consumed_levels=(),
        ),
        quote_source=None,
        quote_refresh_witness=None,
        current_combo_subscription_witness=None,
    )
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=first_close,
        allocate_request_id=lambda: 42,
    )
    boundary = _boundary(5, 150)
    witness = _position_subscription_witness(
        boundary=boundary,
        change_id=1,
        previous_change_id=None,
        snapshot_kind="snapshot",
        subscription_generation=2,
    )
    facts = _position_facts(
        boundary=boundary,
        change_id=13,
        previous_change_id=12,
    )

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            facts,
            quote_source=SourceFact(witness.source_identity, boundary),
            quote_refresh_witness=witness,
            current_combo_subscription_witness=witness,
        ),
        allocate_request_id=lambda: 43,
    )

    assert {
        "CLOSE_QUOTE_EVALUATION",
        "SHADOW_CLOSE_OPPORTUNITY",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
    }.issubset(item.object_kind for item in transition.emitted)


def test_owner_accepts_later_unbroken_subscription_after_unknown_opportunity(
    tmp_path: Path,
) -> None:
    owner, _bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    owner.note_request_failure(
        request_id=42,
        boundary=_boundary(5, 145),
    )
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _position_facts(
                boundary=_boundary(6, 150),
                change_id=13,
                previous_change_id=12,
            ),
            short_leg_taker_commission_fraction=None,
        ),
        allocate_request_id=lambda: 43,
    )

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=_boundary(7, 160),
            change_id=14,
            previous_change_id=13,
        ),
        allocate_request_id=lambda: 44,
    )

    assert {
        "SHADOW_CLOSE_OPPORTUNITY",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
    }.issubset(item.object_kind for item in transition.emitted)


def test_owner_advances_lineage_after_equal_business_new_generation_snapshot(
    tmp_path: Path,
) -> None:
    owner, _bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    owner.note_request_failure(
        request_id=42,
        boundary=_boundary(5, 145),
    )
    snapshot_boundary = _boundary(6, 150)
    snapshot = _position_subscription_witness(
        boundary=snapshot_boundary,
        change_id=1,
        previous_change_id=None,
        snapshot_kind="snapshot",
        subscription_generation=2,
    )
    snapshot_facts = _position_facts(
        boundary=snapshot_boundary,
        change_id=13,
        previous_change_id=12,
    )
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            snapshot_facts,
            quote_source=SourceFact(snapshot.source_identity, snapshot_boundary),
            quote_refresh_witness=snapshot,
            current_combo_subscription_witness=snapshot,
            short_leg_taker_commission_fraction=None,
        ),
        allocate_request_id=lambda: 43,
    )
    change_boundary = _boundary(7, 160)
    change = _position_subscription_witness(
        boundary=change_boundary,
        change_id=2,
        previous_change_id=1,
        subscription_generation=2,
    )
    change_facts = _position_facts(
        boundary=change_boundary,
        change_id=14,
        previous_change_id=13,
    )

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            change_facts,
            quote_source=SourceFact(change.source_identity, change_boundary),
            quote_refresh_witness=change,
            current_combo_subscription_witness=change,
        ),
        allocate_request_id=lambda: 44,
    )

    assert {
        "SHADOW_CLOSE_OPPORTUNITY",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "SHADOW_OUTCOME",
    }.issubset(item.object_kind for item in transition.emitted)


@pytest.mark.parametrize("state", ("inactive", "locked", "halted"))
def test_position_option_discontinuity_states_are_hard_close(
    tmp_path: Path,
    state: str,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _quiet_position_facts(boundary=_boundary(4, 140)),
            short_leg_state=state,
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("PLATFORM_OR_SOURCE_DISCONTINUITY")] == "TRUE"
    action_identity = next(
        item.object_identity for item in transition.emitted if item.object_kind == "POSITION_ACTION"
    )
    action = _object(_written_objects(tmp_path, bindings=bindings)[action_identity]["payload"])
    assert action["serialized_action"] == "CLOSE"
    assert action["primary_close_reason"] == "PLATFORM_OR_SOURCE_DISCONTINUITY"


def test_position_open_inactive_option_is_a_hard_discontinuity(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    facts = _quiet_position_facts(boundary=_boundary(4, 140))

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(facts, short_leg_active=False),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("PLATFORM_OR_SOURCE_DISCONTINUITY")] == "TRUE"


def test_position_unrecognized_option_state_keeps_discontinuity_unknown(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _quiet_position_facts(boundary=_boundary(4, 140)),
            short_leg_state="unexpected",
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("PLATFORM_OR_SOURCE_DISCONTINUITY")] == "UNKNOWN"


@pytest.mark.parametrize(
    "delta",
    (
        Decimal("2"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ),
)
def test_position_invalid_delta_is_unknown_not_a_close_trigger(
    tmp_path: Path,
    delta: Decimal,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _quiet_position_facts(boundary=_boundary(4, 140)),
            current_short_delta=delta,
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("SHORT_LEG_RISK_BOUNDARY_REACHED")] == "UNKNOWN"


@pytest.mark.parametrize(
    "index",
    (
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ),
)
def test_position_invalid_index_is_unknown_for_risk_and_path(
    tmp_path: Path,
    index: Decimal,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _quiet_position_facts(boundary=_boundary(4, 140)),
            current_index_usdc_per_btc=index,
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("SHORT_LEG_RISK_BOUNDARY_REACHED")] == "UNKNOWN"
    assert truths[POSITION_CLOSE_REASONS.index("PATH_OR_JUMP_RISK_BOUNDARY_REACHED")] == "UNKNOWN"


@pytest.mark.parametrize(
    "mark_iv",
    (
        Decimal("-0.1"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ),
)
def test_position_invalid_mark_iv_is_unknown(
    tmp_path: Path,
    mark_iv: Decimal,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _quiet_position_facts(boundary=_boundary(4, 140)),
            current_short_mark_iv_fraction=mark_iv,
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("VOLATILITY_STATE_BOUNDARY_REACHED")] == "UNKNOWN"


def test_owner_quiet_current_combo_schedules_post_close_rpc_when_time_latches_close(
    tmp_path: Path,
) -> None:
    owner, _bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    retained = _position_facts(
        boundary=_boundary(4, 140),
        change_id=12,
        previous_change_id=11,
    )
    retained = replace(
        retained,
        close_quote_facts=replace(
            retained.close_quote_facts,
            consumed_levels=((Decimal("300"), Decimal("0.1")),),
        ),
    )
    held = owner.settle_position(
        anchor_identity=entry_identity,
        facts=retained,
        allocate_request_id=lambda: 42,
    )
    assert held.request_intents == ()

    time_boundary = replace(
        retained,
        boundary=_boundary(5, 150),
        trusted_time_lower_ms=8_200_000,
        trusted_time_upper_ms=8_200_000,
        quote_refresh_witness=None,
    )
    closed = owner.settle_position(
        anchor_identity=entry_identity,
        facts=time_boundary,
        allocate_request_id=lambda: 42,
    )

    assert [item.object_kind for item in closed.emitted] == [
        "POSITION_EVALUATION",
        "POSITION_ACTION",
        "POST_CLOSE_ATTEMPT_SCHEDULED",
    ]
    assert [intent.request_id for intent in closed.request_intents] == [42]


def test_owner_post_close_request_failure_emits_attempt_owned_unknown_opportunity(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    owner.note_request_sent(request_id=42, boundary=_boundary(5, 145))

    failed = owner.note_request_failure(
        request_id=42,
        boundary=_boundary(6, 150),
    )

    assert [item.object_kind for item in failed.emitted] == [
        "POST_CLOSE_ATTEMPT_TERMINAL",
        "CLOSE_OPPORTUNITY_EVALUATION",
    ]
    objects = _written_objects(tmp_path, bindings=bindings)
    opportunity = next(
        value
        for value in objects.values()
        if value["object_kind"] == "CLOSE_OPPORTUNITY_EVALUATION"
    )
    payload = _object(opportunity["payload"])
    assert payload["close_quote_evaluation_identity"] is None
    assert payload["attempt_terminal_identity"] is not None
    assert payload["attempt_terminal_fact_boundary"] == _boundary(6, 150).as_object()
    assert payload["eligibility"] == "UNKNOWN"
    assert payload["eligibility_reason"] == "QUOTE_OR_ATTEMPT_UNKNOWN"
    assert payload["gross_cashflow_availability"] == "UNKNOWN"
    assert payload["derived_economics_availability"] == "UNKNOWN"
    assert payload["commission_source_refs"] == []
    assert payload["index_source_ref"] is None


def test_owner_reconnect_retirement_invalidates_pending_admission_as_source_gap(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    origin = _underwriting_facts(
        boundary=_boundary(1, 110),
        change_id=10,
        previous_change_id=None,
        snapshot_kind="snapshot",
    )
    activated = owner.settle_underwriting((origin,), allocate_request_id=lambda: 41)
    assert any(item.object_kind == "CANDIDATE_ACTIVATION" for item in activated.emitted)
    owner.note_request_sent(request_id=41, boundary=_boundary(2, 120))

    retired = owner.note_request_failure(
        request_id=41,
        boundary=_boundary(3, 130),
        terminal_status=PostCloseAttemptStatus.RETIRED,
    )

    assert [item.object_kind for item in retired.emitted] == [
        "ADMISSION_ATTEMPT_TERMINAL",
        "CANDIDATE_INVALIDATION",
    ]
    objects = _written_objects(tmp_path, bindings=bindings)
    terminal = next(
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "ADMISSION_ATTEMPT_TERMINAL"
    )
    invalidation = next(
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "CANDIDATE_INVALIDATION"
    )
    assert terminal["terminal_outcome"] == "KNOWN_INVALIDATED_BEFORE_REFRESH"
    assert invalidation["primary_reason"] == (
        "SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN"
    )


def test_owner_episode_retirement_terminalizes_its_active_candidate(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    origin = _underwriting_facts(
        boundary=_boundary(1, 110),
        change_id=10,
        previous_change_id=None,
        snapshot_kind="snapshot",
    )
    activated = owner.settle_underwriting((origin,), allocate_request_id=lambda: 41)
    assert any(item.object_kind == "CANDIDATE_ACTIVATION" for item in activated.emitted)
    episode_identity = origin.active_episode_identity
    assert episode_identity is not None

    retired = owner.retire_radar_episode(
        episode_identity,
        boundary=_boundary(2, 120),
    )

    assert [item.object_kind for item in retired.emitted] == [
        "ADMISSION_ATTEMPT_TERMINAL",
        "CANDIDATE_INVALIDATION",
    ]
    assert owner.retained_state_counts["active_candidates"] == 0
    objects = _written_objects(tmp_path, bindings=bindings)
    terminal = next(
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "ADMISSION_ATTEMPT_TERMINAL"
    )
    invalidation = next(
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "CANDIDATE_INVALIDATION"
    )
    assert terminal["terminal_outcome"] == "KNOWN_INVALIDATED_BEFORE_REFRESH"
    assert invalidation["primary_reason"] == ("RADAR_POLICY_OR_EPISODE_PAUSED_ENDED_OR_CHANGED")


def test_owner_close_opportunity_deduplicates_receipts_but_reacts_to_consumed_facts(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )

    commission_unknown = replace(
        _position_facts(
            boundary=_boundary(5, 150),
            change_id=13,
            previous_change_id=12,
        ),
        short_leg_taker_commission_fraction=None,
    )
    first = owner.settle_position(
        anchor_identity=entry_identity,
        facts=commission_unknown,
        allocate_request_id=lambda: 43,
    )
    assert [item.object_kind for item in first.emitted] == [
        "POSITION_EVALUATION",
        "POSITION_ACTION",
        "CLOSE_QUOTE_EVALUATION",
        "POST_CLOSE_ATTEMPT_TERMINAL",
        "CLOSE_OPPORTUNITY_EVALUATION",
    ]

    repeated = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _position_facts(
                boundary=_boundary(6, 160),
                change_id=14,
                previous_change_id=13,
            ),
            short_leg_taker_commission_fraction=None,
        ),
        allocate_request_id=lambda: 44,
    )
    assert repeated.emitted == ()

    above_policy = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _position_facts(
                boundary=_boundary(7, 170),
                change_id=15,
                previous_change_id=14,
            ),
            short_leg_taker_commission_fraction=Decimal("0.0004"),
        ),
        allocate_request_id=lambda: 45,
    )
    assert [item.object_kind for item in above_policy.emitted] == [
        "POSITION_EVALUATION",
        "POSITION_ACTION",
        "CLOSE_OPPORTUNITY_EVALUATION",
    ]
    objects = _written_objects(tmp_path, bindings=bindings)
    opportunities = [
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "CLOSE_OPPORTUNITY_EVALUATION"
    ]
    assert {payload["eligibility_reason"] for payload in opportunities} == {
        "COMMISSION_UNKNOWN",
        "COMMISSION_ABOVE_POLICY",
    }


def test_owner_position_fingerprint_reacts_when_fee_economics_become_known(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    unknown_fee = replace(
        _position_facts(
            boundary=_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        short_leg_taker_commission_fraction=None,
        long_leg_taker_commission_fraction=None,
        short_commission_source=None,
        long_commission_source=None,
    )
    first = owner.settle_position(
        anchor_identity=entry_identity,
        facts=unknown_fee,
        allocate_request_id=lambda: 42,
    )
    first_action_identity = next(
        item.object_identity for item in first.emitted if item.object_kind == "POSITION_ACTION"
    )
    first_objects = _written_objects(tmp_path, bindings=bindings)
    assert (
        _object(first_objects[first_action_identity]["payload"])["serialized_action"] == "UNKNOWN"
    )

    known_fee = _position_facts(
        boundary=_boundary(5, 150),
        change_id=13,
        previous_change_id=12,
    )
    second = owner.settle_position(
        anchor_identity=entry_identity,
        facts=known_fee,
        allocate_request_id=lambda: 42,
    )

    assert [item.object_kind for item in second.emitted[:3]] == [
        "POSITION_EVALUATION",
        "POSITION_ACTION",
        "POST_CLOSE_ATTEMPT_SCHEDULED",
    ]
    second_action_identity = next(
        item.object_identity for item in second.emitted if item.object_kind == "POSITION_ACTION"
    )
    second_objects = _written_objects(tmp_path, bindings=bindings)
    assert (
        _object(second_objects[second_action_identity]["payload"])["serialized_action"] == "CLOSE"
    )


def test_position_source_less_index_is_unknown_and_does_not_advance_anchor(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    first = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _quiet_position_facts(boundary=_boundary(4, 140)),
            current_index_usdc_per_btc=Decimal("100500"),
            index_source=None,
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, first)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("SHORT_LEG_RISK_BOUNDARY_REACHED")] == "UNKNOWN"
    assert truths[POSITION_CLOSE_REASONS.index("PATH_OR_JUMP_RISK_BOUNDARY_REACHED")] == "UNKNOWN"
    assert payload["current_index_usdc_per_btc"] is None
    assert payload["current_index_source_identity"] is None
    assert payload["current_index_fact_boundary"] is None
    assert payload["current_index_availability"] == "UNKNOWN"
    assert payload["next_evaluation_index_usdc_per_btc"] == "100000"

    second = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _quiet_position_facts(
                boundary=_boundary(5, 150),
                change_id=13,
                previous_change_id=12,
            ),
            current_index_usdc_per_btc=Decimal("101000"),
        ),
        allocate_request_id=lambda: 43,
    )
    second_payload = _position_evaluation_payload(tmp_path, bindings, second)
    second_truths = cast(list[str], second_payload["ordered_predicate_truth_vector"])
    assert second_payload["prior_evaluation_index_usdc_per_btc"] == "100000"
    assert (
        second_truths[POSITION_CLOSE_REASONS.index("PATH_OR_JUMP_RISK_BOUNDARY_REACHED")] == "TRUE"
    )


def test_position_source_less_ticker_cannot_trigger_risk_or_volatility_close(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _quiet_position_facts(boundary=_boundary(4, 140)),
            current_short_delta=Decimal("0.9"),
            current_short_mark_iv_fraction=Decimal("0.9"),
            ticker_source=None,
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("SHORT_LEG_RISK_BOUNDARY_REACHED")] == "UNKNOWN"
    assert truths[POSITION_CLOSE_REASONS.index("VOLATILITY_STATE_BOUNDARY_REACHED")] == "UNKNOWN"


def test_position_source_less_atomic_quote_has_no_quote_economics(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _position_facts(
                boundary=_boundary(4, 140),
                change_id=12,
                previous_change_id=11,
            ),
            quote_source=None,
            quote_refresh_witness=None,
            current_combo_subscription_witness=None,
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("LIQUIDITY_EXIT_BOUNDARY_REACHED")] == "UNKNOWN"
    assert truths[POSITION_CLOSE_REASONS.index("ECONOMIC_EXIT_BOUNDARY_REACHED")] == "UNKNOWN"
    objects = _written_objects(tmp_path, bindings=bindings)
    assert all(value["object_kind"] != "CLOSE_QUOTE_EVALUATION" for value in objects.values())


@pytest.mark.parametrize(
    "fault",
    (
        "SOURCE_IDENTITY",
        "SOURCE_BOUNDARY",
        "CANONICAL_COMBO",
        "INSTRUMENT",
        "LINEAGE",
    ),
)
def test_preclose_atomic_quote_requires_exact_source_witness_and_lineage(
    tmp_path: Path,
    fault: str,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    facts = _position_facts(
        boundary=_boundary(4, 140),
        change_id=12,
        previous_change_id=11,
    )
    witness = facts.current_combo_subscription_witness
    assert witness is not None
    quote_source = facts.quote_source
    refresh_witness = facts.quote_refresh_witness
    if fault == "SOURCE_IDENTITY":
        quote_source = SourceFact(canonical_identity("WrongQuoteSource"), witness.boundary)
        refresh_witness = None
    elif fault == "SOURCE_BOUNDARY":
        quote_source = SourceFact(witness.source_identity, _boundary(3, 130))
        refresh_witness = None
    elif fault == "CANONICAL_COMBO":
        witness = _position_subscription_witness(
            boundary=facts.boundary,
            change_id=12,
            previous_change_id=11,
            canonical_combo_identity=canonical_identity("WrongCombo"),
        )
        quote_source = SourceFact(witness.source_identity, witness.boundary)
        refresh_witness = witness
    elif fault == "INSTRUMENT":
        witness = _position_subscription_witness(
            boundary=facts.boundary,
            change_id=12,
            previous_change_id=11,
            instrument_name="WRONG-COMBO",
        )
        quote_source = SourceFact(witness.source_identity, witness.boundary)
        refresh_witness = witness
    elif fault == "LINEAGE":
        witness = _position_subscription_witness(
            boundary=facts.boundary,
            change_id=12,
            previous_change_id=999,
        )
        quote_source = SourceFact(witness.source_identity, witness.boundary)
        refresh_witness = witness
    else:
        raise AssertionError(f"unhandled fault: {fault}")

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            facts,
            quote_source=quote_source,
            quote_refresh_witness=refresh_witness,
            current_combo_subscription_witness=witness,
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("LIQUIDITY_EXIT_BOUNDARY_REACHED")] == "UNKNOWN"
    assert truths[POSITION_CLOSE_REASONS.index("ECONOMIC_EXIT_BOUNDARY_REACHED")] == "UNKNOWN"
    objects = _written_objects(tmp_path, bindings=bindings)
    assert all(value["object_kind"] != "CLOSE_QUOTE_EVALUATION" for value in objects.values())


@pytest.mark.parametrize(
    ("hard_close_kind", "expected_reason"),
    (
        (
            "SETTLEMENT",
            "SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED",
        ),
        (
            "LATEST_EXIT",
            "LATEST_EXIT_BOUNDARY_REACHED",
        ),
    ),
)
def test_invalid_quote_lineage_does_not_mask_hard_close(
    tmp_path: Path,
    hard_close_kind: str,
    expected_reason: str,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    facts = _position_facts(
        boundary=_boundary(4, 140),
        change_id=12,
        previous_change_id=11,
    )
    invalid_witness = _position_subscription_witness(
        boundary=facts.boundary,
        change_id=12,
        previous_change_id=999,
    )
    facts = replace(
        facts,
        quote_source=SourceFact(
            invalid_witness.source_identity,
            invalid_witness.boundary,
        ),
        quote_refresh_witness=invalid_witness,
        current_combo_subscription_witness=invalid_witness,
    )
    if hard_close_kind == "SETTLEMENT":
        facts = replace(facts, short_leg_state="settlement")
    elif hard_close_kind == "LATEST_EXIT":
        facts = replace(
            facts,
            trusted_time_lower_ms=8_200_000,
            trusted_time_upper_ms=8_200_001,
        )
    else:
        raise AssertionError(f"unhandled hard close kind: {hard_close_kind}")

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=facts,
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("LIQUIDITY_EXIT_BOUNDARY_REACHED")] == "UNKNOWN"
    objects = _written_objects(tmp_path, bindings=bindings)
    action = next(
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "POSITION_ACTION"
    )
    assert action["serialized_action"] == "CLOSE"
    assert action["primary_close_reason"] == expected_reason
    assert transition.request_intents == ()
    assert all(value["object_kind"] != "CLOSE_QUOTE_EVALUATION" for value in objects.values())


def test_known_position_source_loss_closes_and_still_schedules_quote_rpc(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    facts = _position_facts(
        boundary=_boundary(4, 140),
        change_id=12,
        previous_change_id=11,
    )

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            facts,
            required_sources_continuous=False,
            current_index_usdc_per_btc=None,
            current_short_delta=None,
            current_short_mark_iv_fraction=None,
            index_source=None,
            ticker_source=None,
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("PLATFORM_OR_SOURCE_DISCONTINUITY")] == "TRUE"
    objects = _written_objects(tmp_path, bindings=bindings)
    action = next(
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "POSITION_ACTION"
    )
    assert action["serialized_action"] == "CLOSE"
    assert action["primary_close_reason"] == "PLATFORM_OR_SOURCE_DISCONTINUITY"
    assert len(transition.request_intents) == 1


def test_exact_expiry_has_only_settlement_primary_and_latest_exit_secondary(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    facts = _position_facts(
        boundary=_boundary(4, 140),
        change_id=12,
        previous_change_id=11,
    )

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            facts,
            trusted_time_lower_ms=10_000_000,
            trusted_time_upper_ms=10_000_001,
            required_sources_continuous=True,
            close_quote_facts=replace(
                facts.close_quote_facts,
                atomic_availability=CloseAtomicAvailability.UNKNOWN,
                book_availability=CloseBookAvailability.UNKNOWN,
                consumed_levels=(),
            ),
            quote_source=None,
            quote_refresh_witness=None,
            current_combo_subscription_witness=None,
        ),
        allocate_request_id=lambda: 42,
    )

    objects = _written_objects(tmp_path, bindings=bindings)
    action = next(
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "POSITION_ACTION"
    )
    assert action["primary_close_reason"] == "SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED"
    assert action["secondary_close_reasons"] == ["LATEST_EXIT_BOUNDARY_REACHED"]
    assert transition.request_intents == ()


def test_admitted_position_evaluation_persists_complete_index_source_graph(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    facts = _quiet_position_facts(boundary=_boundary(4, 140))
    assert facts.index_source is not None

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=facts,
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    assert payload["entry_index_usdc_per_btc"] == "100000"
    assert payload["entry_index_source_identity"] == "sha256:" + "a" * 64
    assert payload["entry_index_fact_boundary"] == _boundary(3, 130).as_object()
    assert payload["entry_short_leg_mark_iv_fraction"] == "0.5"
    assert payload["entry_short_leg_mark_iv_source_identity"] == "sha256:" + "b" * 64
    assert payload["entry_short_leg_mark_iv_fact_boundary"] == _boundary(3, 130).as_object()
    assert payload["prior_evaluation_index_usdc_per_btc"] == "100000"
    assert payload["prior_evaluation_index_source_identity"] == "sha256:" + "a" * 64
    assert payload["prior_evaluation_index_fact_boundary"] == _boundary(3, 130).as_object()
    assert payload["current_index_usdc_per_btc"] == "100000"
    assert payload["current_index_source_identity"] == facts.index_source.source_identity
    assert payload["current_index_fact_boundary"] == facts.index_source.boundary.as_object()
    assert payload["current_index_availability"] == "KNOWN"
    assert payload["next_evaluation_index_usdc_per_btc"] == "100000"


def test_known_above_policy_position_fee_is_hard_discontinuity(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _quiet_position_facts(boundary=_boundary(4, 140)),
            short_leg_taker_commission_fraction=Decimal("0.0004"),
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    discontinuity_index = POSITION_CLOSE_REASONS.index("PLATFORM_OR_SOURCE_DISCONTINUITY")
    assert truths[discontinuity_index] == "TRUE"
    action = next(
        _object(value["payload"])
        for value in _written_objects(tmp_path, bindings=bindings).values()
        if value["object_kind"] == "POSITION_ACTION"
    )
    assert action["serialized_action"] == "CLOSE"
    assert action["primary_close_reason"] == "PLATFORM_OR_SOURCE_DISCONTINUITY"


def test_initial_missing_position_fee_remains_unknown_not_hard_discontinuity(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=replace(
            _quiet_position_facts(boundary=_boundary(4, 140)),
            short_leg_taker_commission_fraction=None,
            short_commission_source=None,
        ),
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("PLATFORM_OR_SOURCE_DISCONTINUITY")] == "UNKNOWN"
    action = next(
        _object(value["payload"])
        for value in _written_objects(tmp_path, bindings=bindings).values()
        if value["object_kind"] == "POSITION_ACTION"
    )
    assert action["serialized_action"] == "UNKNOWN"


def test_first_match_quote_fields_do_not_manufacture_new_business_objects(
    tmp_path: Path,
) -> None:
    owner, _bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    first = _position_facts(
        boundary=_boundary(4, 140),
        change_id=12,
        previous_change_id=11,
    )
    first = replace(
        first,
        close_quote_facts=replace(
            first.close_quote_facts,
            option_availability=CloseOptionAvailability.UNKNOWN,
        ),
    )
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=first,
        allocate_request_id=lambda: 42,
    )
    second = _position_facts(
        boundary=_boundary(5, 150),
        change_id=13,
        previous_change_id=12,
    )
    second = replace(
        second,
        close_quote_facts=replace(
            second.close_quote_facts,
            option_availability=CloseOptionAvailability.UNKNOWN,
            component_reference=PredicateTruth.TRUE,
            consumed_levels=((Decimal("75"), Decimal("0.1")),),
        ),
    )

    repeated = owner.settle_position(
        anchor_identity=entry_identity,
        facts=second,
        allocate_request_id=lambda: 43,
    )

    assert repeated.emitted == ()
    assert repeated.request_intents == ()


def test_negative_signed_close_level_preserves_atomic_quote_and_credit(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    facts = _position_facts(
        boundary=_boundary(4, 140),
        change_id=12,
        previous_change_id=11,
    )
    facts = replace(
        facts,
        close_quote_facts=replace(
            facts.close_quote_facts,
            consumed_levels=((Decimal("-1"), Decimal("0.1")),),
        ),
    )

    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=facts,
        allocate_request_id=lambda: 42,
    )

    payload = _position_evaluation_payload(tmp_path, bindings, transition)
    truths = cast(list[str], payload["ordered_predicate_truth_vector"])
    assert truths[POSITION_CLOSE_REASONS.index("LIQUIDITY_EXIT_BOUNDARY_REACHED")] == "FALSE"
    quotes = [
        _object(value["payload"])
        for value in _written_objects(tmp_path, bindings=bindings).values()
        if value["object_kind"] == "CLOSE_QUOTE_EVALUATION"
    ]
    assert len(quotes) == 1
    assert quotes[0]["close_quote_state"] == "ATOMIC_COMBO_CLOSE_QUOTE"
    assert quotes[0]["consumed_levels"] == [{"price_usdc_per_btc": "-1", "amount_btc": "0.1"}]
    assert quotes[0]["gross_close_cashflow_usdc"] == "0.1"


def test_watch_and_abstain_remain_current_state_without_automatic_counterfactual_cases(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    watch_facts = replace(
        _underwriting_facts(
            boundary=_boundary(1, 110),
            change_id=10,
            previous_change_id=None,
            snapshot_kind="snapshot",
        ),
        entry_consumed_levels=((Decimal("150"), Decimal("0.1")),),
    )

    first = owner.settle_underwriting((watch_facts,), allocate_request_id=lambda: 41)
    repeated = owner.settle_underwriting(
        (
            replace(
                watch_facts,
                boundary=_boundary(2, 120),
                quote_source=SourceFact(
                    cast(
                        SubscriptionAdmissionRefreshWitness, watch_facts.quote_refresh_witness
                    ).source_identity,
                    _boundary(2, 120),
                ),
            ),
        ),
        allocate_request_id=lambda: 42,
    )

    emitted_kinds = {item.object_kind for item in (*first.emitted, *repeated.emitted)}
    assert "UNDERWRITING_ACTION" in emitted_kinds
    assert not any(kind.startswith("REJECTED_COUNTERFACTUAL") for kind in emitted_kinds)
    assert "ALIGNED_POLICY_NO_TRADE_PAIR" not in emitted_kinds
    objects = _written_objects(tmp_path, bindings=bindings)
    assert not any(
        str(value["object_kind"]).startswith("REJECTED_COUNTERFACTUAL")
        for value in objects.values()
    )


def test_owner_invalidates_broken_subscription_chain_without_replacement_candidate(
    tmp_path: Path,
) -> None:
    owner, _bindings = _owner(tmp_path)
    origin = _underwriting_facts(
        boundary=_boundary(1, 110),
        change_id=10,
        previous_change_id=None,
        snapshot_kind="snapshot",
    )
    owner.settle_underwriting((origin,), allocate_request_id=lambda: 41)
    broken = _underwriting_facts(
        boundary=_boundary(2, 120),
        change_id=12,
        previous_change_id=9,
        snapshot_kind="change",
    )
    transition = owner.settle_underwriting((broken,), allocate_request_id=lambda: 42)
    assert [item.object_kind for item in transition.emitted] == [
        "ADMISSION_ATTEMPT_TERMINAL",
        "CANDIDATE_INVALIDATION",
    ]
    invalidation_identity = next(
        item.object_identity
        for item in transition.emitted
        if item.object_kind == "CANDIDATE_INVALIDATION"
    )
    payload = _object(
        _written_objects(tmp_path, bindings=_bindings)[invalidation_identity]["payload"]
    )
    assert payload["primary_reason"] == ("SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN")
    assert not any(item.object_kind == "CANDIDATE_ACTIVATION" for item in transition.emitted)


def test_owner_replaces_candidate_only_after_ordinary_economic_fingerprint_change(
    tmp_path: Path,
) -> None:
    owner, _bindings = _owner(tmp_path)
    origin = _underwriting_facts(
        boundary=_boundary(1, 110),
        change_id=10,
        previous_change_id=None,
        snapshot_kind="snapshot",
    )
    activated = owner.settle_underwriting((origin,), allocate_request_id=lambda: 41)
    first_candidate = next(
        item.object_identity
        for item in activated.emitted
        if item.object_kind == "CANDIDATE_ACTIVATION"
    )
    later_boundary = _boundary(2, 120)
    changed = replace(
        origin,
        boundary=later_boundary,
        index_usdc_per_btc=Decimal("101000"),
        index_source=SourceFact("sha256:" + "c" * 64, later_boundary),
    )
    replacement = owner.settle_underwriting((changed,), allocate_request_id=lambda: 42)
    assert [item.object_kind for item in replacement.emitted] == [
        "ADMISSION_ATTEMPT_TERMINAL",
        "CANDIDATE_INVALIDATION",
        "UNDERWRITING_ACTION",
        "CANDIDATE_ACTIVATION",
        "ADMISSION_ATTEMPT_SCHEDULED",
    ]
    second_candidate = next(
        item.object_identity
        for item in replacement.emitted
        if item.object_kind == "CANDIDATE_ACTIVATION"
    )
    assert second_candidate != first_candidate


def test_owner_failure_does_not_settle_pending_admitted_observation(tmp_path: Path) -> None:
    owner, bindings = _owner(tmp_path, close_enrollment=False)
    _admit_owner(owner)
    failure_boundary = _boundary(6, 150)
    failure_identity = canonical_identity(
        "PublicShadowRuntimeTerminalSourceIdentity",
        bindings.runtime_identity,
        "PROCESS_FAILURE",
        failure_boundary.as_object(),
    )

    transition = owner.terminate(
        boundary=failure_boundary,
        terminal_source_identity=failure_identity,
        terminal_source=TerminalSource.FAILURE,
    )

    objects = _written_objects(tmp_path, bindings=bindings)
    assert not any(value["object_kind"] == "SHADOW_OUTCOME" for value in objects.values())
    assert not any(item.object_kind == "SHADOW_OUTCOME" for item in transition.emitted)
    assert len(owner.active_trade_identities) == 1


@pytest.mark.parametrize(
    ("terminal_source", "expected_state"),
    (
        (TerminalSource.STOP, "CENSORED_AT_STOP"),
        (TerminalSource.FAILURE, "CENSORED_AT_FAILURE"),
    ),
)
def test_owner_process_end_preserves_control_censor_outcome(
    tmp_path: Path,
    terminal_source: TerminalSource,
    expected_state: str,
) -> None:
    owner, bindings = _owner(tmp_path)
    entry_identity = _admit_owner(owner)
    owner._trades[entry_identity].enrollment_kind = "SELECTED_UNDERWRITING_DECISION_CONTROL"
    boundary = _boundary(6, 160)
    source_identity = canonical_identity(
        "PublicShadowRuntimeTerminalSourceIdentity",
        bindings.runtime_identity,
        terminal_source.value,
        boundary.as_object(),
    )

    transition = owner.terminate(
        boundary=boundary,
        terminal_source_identity=source_identity,
        terminal_source=terminal_source,
    )

    outcome = next(
        item
        for item in transition.emitted
        if item.object_kind == "SELECTED_UNDERWRITING_DECISION_CONTROL_OUTCOME"
    )
    record = owner.state_store.get_object(outcome.object_kind, outcome.object_identity)
    assert record is not None
    payload = cast(Mapping[str, object], record["payload"])
    assert payload["terminal_state"] == expected_state
    assert payload["economic_availability"] == "UNKNOWN"


def test_owner_restores_entry_without_replaying_admission_and_skips_adoption_baseline(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    projection = _typed_recovery_entry(bindings, known_entry_baseline=False)
    raw_projection = _recovery_projection(bindings, known_entry_baseline=False)
    with pytest.raises(TypeError, match="official CaseStore values"):
        owner.stage_recovered_entries(
            (raw_projection,),  # type: ignore[arg-type]
            recovery_projection_boundary=_boundary(0, 100),
        )

    staged = owner.stage_recovered_entries(
        (projection,),
        recovery_projection_boundary=_boundary(0, 100),
    )

    assert staged[0].required_option_instrument_names == (
        "BTC_USDC-8AUG26-101000-C",
        "BTC_USDC-8AUG26-102000-C",
    )
    assert staged[0].expiry_ms == 10_000_000
    assert owner.active_trade_identities == frozenset()
    recovering = owner.state_store.get_object(
        "SHADOW_ENTRY",
        projection.shadow_entry_identity,
    )
    assert recovering is not None
    recovering_payload = cast(Mapping[str, object], recovering["payload"])
    assert recovering_payload["tracking_state"] == "RECOVERING"
    assert recovering_payload["current_segment_identity"] is None
    owner.activate_recovered_entries(staged)
    entry_identity = projection.shadow_entry_identity
    assert owner.active_trade_identities == frozenset({entry_identity})
    assert owner.state_store.take_pending_records() == ()
    assert owner.retained_state_counts["active_consumed_slots"] == 0
    assert owner.retained_state_counts["active_candidates"] == 0
    restored = owner.state_store.get_object("SHADOW_ENTRY", entry_identity)
    assert restored is not None
    assert restored["fact_boundary"] == _boundary(1, 110).as_object()
    restored_payload = cast(Mapping[str, object], restored["payload"])
    assert restored_payload["observation_quality"] == "GAPPED"
    assert restored_payload["qualification_eligible"] is False

    baseline = owner.settle_position(
        anchor_identity=entry_identity,
        facts=_quiet_position_facts(boundary=_boundary(1, 110)),
        allocate_request_id=lambda: pytest.fail("adoption baseline scheduled a request"),
    )
    assert baseline.emitted == ()
    continued = owner.settle_position(
        anchor_identity=entry_identity,
        facts=_quiet_position_facts(boundary=_boundary(2, 120)),
        allocate_request_id=lambda: pytest.fail("UNKNOWN recovery scheduled a request"),
    )
    assert continued.request_intents == ()
    action = next(item for item in continued.emitted if item.object_kind == "POSITION_ACTION")
    action_record = owner.state_store.get_object(action.object_kind, action.object_identity)
    assert action_record is not None
    action_payload = cast(Mapping[str, object], action_record["payload"])
    assert action_payload["serialized_action"] == "UNKNOWN"
    evaluation = next(
        item for item in continued.emitted if item.object_kind == "POSITION_EVALUATION"
    )
    evaluation_record = owner.state_store.get_object(
        evaluation.object_kind,
        evaluation.object_identity,
    )
    assert evaluation_record is not None
    evaluation_payload = cast(Mapping[str, object], evaluation_record["payload"])
    assert evaluation_payload["entry_index_usdc_per_btc"] is None
    assert evaluation_payload["entry_short_leg_mark_iv_fraction"] is None
    with pytest.raises(ValueError, match="duplicate recovered shadow_entry_identity"):
        owner.activate_recovered_entries(staged)


def test_recovered_first_close_is_not_retried_and_can_mature_gapped_unknown(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    projection = _typed_recovery_entry(bindings, first_close=True)
    assert projection.first_close_decision is not None
    first_close_identity = projection.first_close_decision.position_action_identity
    entry_identity = projection.shadow_entry_identity
    owner.activate_recovered_entries((projection,))

    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_quiet_position_facts(boundary=_boundary(1, 110)),
        allocate_request_id=lambda: pytest.fail("adoption baseline retried CLOSE"),
    )
    terminal_boundary = _boundary(2, 120)
    ordinary = _quiet_position_facts(boundary=terminal_boundary)
    natural = replace(
        ordinary,
        short_leg_state="delivered",
        long_leg_state="delivered",
        short_leg_active=False,
        long_leg_active=False,
        lifecycle_short_source=SourceFact(
            canonical_identity("LifecycleSourceIdentity", "recovery-short"),
            terminal_boundary,
        ),
        lifecycle_long_source=SourceFact(
            canonical_identity("LifecycleSourceIdentity", "recovery-long"),
            terminal_boundary,
        ),
    )
    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=natural,
        allocate_request_id=lambda: pytest.fail("recovered CLOSE attempt was retried"),
    )

    assert transition.request_intents == ()
    assert not any(
        item.object_kind == "POST_CLOSE_ATTEMPT_SCHEDULED" for item in transition.emitted
    )
    action = next(item for item in transition.emitted if item.object_kind == "POSITION_ACTION")
    action_record = owner.state_store.get_object(action.object_kind, action.object_identity)
    assert action_record is not None
    action_payload = cast(Mapping[str, object], action_record["payload"])
    assert action_payload["first_latched_close_action_identity"] == first_close_identity
    outcome = next(item for item in transition.emitted if item.object_kind == "SHADOW_OUTCOME")
    outcome_record = owner.state_store.get_object(outcome.object_kind, outcome.object_identity)
    assert outcome_record is not None
    outcome_payload = cast(Mapping[str, object], outcome_record["payload"])
    assert outcome_payload["terminal_state"] == "MATURE_UNKNOWN"
    assert outcome_payload["observation_quality"] == "GAPPED"
    assert outcome_payload["qualification_eligible"] is False
    assert outcome_payload["economic_availability"] == "UNKNOWN"


def test_downstream_writer_publishes_once_and_rejects_conflicting_identity(tmp_path: Path) -> None:
    bindings = RuntimeBindings(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        radar_policy_identity=RADAR_POLICY_IDENTITY,
        underwriting_policy_identity=UNDERWRITING_POLICY_IDENTITY,
        position_policy_identity=POSITION_POLICY_IDENTITY,
    )
    writer = ShadowStateStore(bindings=bindings)
    _STATE_BY_DIRECTORY[tmp_path.resolve()] = writer
    assert writer.revision == 0
    identity = canonical_identity(
        "CANDIDATE_INVALIDATION",
        "sha256:" + "c" * 64,
        "RUNTIME_OR_CODE_IDENTITY_CHANGED",
        ["RUNTIME_OR_CODE_IDENTITY_CHANGED"],
        _boundary(2).as_object(),
    )
    payload = {
        "candidate_invalidation_identity": identity,
        "candidate_identity": "sha256:" + "c" * 64,
        "primary_reason": "RUNTIME_OR_CODE_IDENTITY_CHANGED",
        "ordered_applicable_reason_vector": ["RUNTIME_OR_CODE_IDENTITY_CHANGED"],
        "terminal_fact_boundary": _boundary(2).as_object(),
    }
    writer.record(
        object_kind="CANDIDATE_INVALIDATION",
        object_identity=identity,
        fact_boundary=_boundary(2),
        payload=payload,
    )
    assert writer.revision == 1
    first_snapshot = writer.objects
    assert writer.objects is first_snapshot
    assert writer.get_object("CANDIDATE_INVALIDATION", identity) is first_snapshot[0]
    writer.record(
        object_kind="CANDIDATE_INVALIDATION",
        object_identity=identity,
        fact_boundary=_boundary(2),
        payload=payload,
    )
    assert writer.revision == 1
    assert writer.objects is first_snapshot

    objects = _written_objects(tmp_path, bindings=bindings)
    assert tuple(objects) == (identity,)
    assert objects[identity]["object_kind"] == "CANDIDATE_INVALIDATION"

    with pytest.raises(ShadowStateError, match="conflicting"):
        writer.record(
            object_kind="CANDIDATE_INVALIDATION",
            object_identity=identity,
            fact_boundary=_boundary(2),
            payload={**payload, "primary_reason": "DIFFERENT"},
        )
    assert writer.revision == 1

    missing_candidate = "sha256:" + "2" * 64
    attempt = AdmissionAttempt.schedule(
        candidate_identity=missing_candidate,
        canonical_combo_identity="sha256:" + "3" * 64,
        request_id=41,
        boundary=_boundary(3),
        request_instrument_name="BTC-TEST-COMBO",
    )
    writer.record(
        object_kind="ADMISSION_ATTEMPT_SCHEDULED",
        object_identity=attempt.scheduled_identity,
        fact_boundary=_boundary(3),
        payload={
            "scheduled_admission_attempt_identity": attempt.scheduled_identity,
            "candidate_identity": missing_candidate,
            "request_id": 41,
            "request_method": "public/get_order_book",
            "request_params": {"instrument_name": "BTC-TEST-COMBO", "depth": 10000},
            "schedule_fact_boundary": _boundary(3).as_object(),
        },
    )
    assert writer.revision == 2
    assert writer.objects is not first_snapshot
    assert attempt.scheduled_identity in _written_objects(tmp_path, bindings=bindings)


def test_legacy_atomic_shadow_entry_cannot_open_a_component_book_case(tmp_path: Path) -> None:
    policies = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-fixed-public-shadow-radar.json",
        underwriting_path=ROOT / "policies/short-vol-fixed-public-shadow-underwriting.json",
        position_path=ROOT / "policies/short-vol-fixed-public-shadow-position.json",
        radar_identity=RADAR_POLICY_IDENTITY,
        underwriting_identity=UNDERWRITING_POLICY_IDENTITY,
        position_identity=POSITION_POLICY_IDENTITY,
    )
    bindings = RuntimeBindings(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        radar_policy_identity=RADAR_POLICY_IDENTITY,
        underwriting_policy_identity=UNDERWRITING_POLICY_IDENTITY,
        position_policy_identity=POSITION_POLICY_IDENTITY,
    )
    cases = tmp_path / "cases"
    cases.mkdir()
    case_store = ShadowCaseStore(cases, bindings=bindings, policies=policies)
    state_store = ShadowStateStore(bindings=bindings, observer=case_store)
    owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        state_store=state_store,
    )

    with pytest.raises(ShadowCaseStoreError, match="execution_model"):
        _admit_owner(owner)

    assert case_store.case_count == 0
    assert list(cases.iterdir()) == []


def test_close_quote_classifier_follows_the_frozen_first_match_order() -> None:
    levels = ((Decimal("50"), Decimal("0.1")),)
    base = CloseQuoteFacts(
        option_availability=CloseOptionAvailability.TRADEABLE,
        atomic_availability=CloseAtomicAvailability.ACTIVE,
        component_reference=PredicateTruth.FALSE,
        book_availability=CloseBookAvailability.FULL_QUANTITY,
        consumed_levels=levels,
    )
    assert classify_close_quote(base) is CloseQuoteState.ATOMIC_COMBO_CLOSE_QUOTE
    assert (
        classify_close_quote(
            CloseQuoteFacts(
                option_availability=CloseOptionAvailability.UNEXECUTABLE,
                atomic_availability=CloseAtomicAvailability.ACTIVE,
                component_reference=PredicateTruth.TRUE,
                book_availability=CloseBookAvailability.FULL_QUANTITY,
                consumed_levels=levels,
            )
        )
        is CloseQuoteState.UNEXECUTABLE
    )
    assert (
        classify_close_quote(
            CloseQuoteFacts(
                option_availability=CloseOptionAvailability.TRADEABLE,
                atomic_availability=CloseAtomicAvailability.KNOWN_UNAVAILABLE,
                component_reference=PredicateTruth.TRUE,
                book_availability=CloseBookAvailability.INSUFFICIENT,
                consumed_levels=(),
            )
        )
        is CloseQuoteState.LEGGED_CLOSE_REFERENCE
    )
    assert (
        classify_close_quote(
            CloseQuoteFacts(
                option_availability=CloseOptionAvailability.TRADEABLE,
                atomic_availability=CloseAtomicAvailability.UNKNOWN,
                component_reference=PredicateTruth.UNKNOWN,
                book_availability=CloseBookAvailability.UNKNOWN,
                consumed_levels=(),
            )
        )
        is CloseQuoteState.UNKNOWN
    )
    assert (
        classify_close_quote(
            CloseQuoteFacts(
                option_availability=CloseOptionAvailability.TRADEABLE,
                atomic_availability=CloseAtomicAvailability.ACTIVE,
                component_reference=PredicateTruth.FALSE,
                book_availability=CloseBookAvailability.FULL_QUANTITY,
                consumed_levels=((Decimal("-1"), Decimal("0.1")),),
            )
        )
        is CloseQuoteState.ATOMIC_COMBO_CLOSE_QUOTE
    )


@pytest.mark.parametrize(
    ("price", "amount"),
    (
        (Decimal("NaN"), Decimal("0.1")),
        (Decimal("Infinity"), Decimal("0.1")),
        (Decimal("50"), Decimal("0")),
        (Decimal("50"), Decimal("-0.1")),
        (Decimal("50"), Decimal("NaN")),
        (Decimal("50"), Decimal("Infinity")),
    ),
)
def test_malformed_atomic_close_level_normalizes_to_unknown(
    price: Decimal,
    amount: Decimal,
) -> None:
    facts = CloseQuoteFacts(
        option_availability=CloseOptionAvailability.TRADEABLE,
        atomic_availability=CloseAtomicAvailability.ACTIVE,
        component_reference=PredicateTruth.FALSE,
        book_availability=CloseBookAvailability.FULL_QUANTITY,
        consumed_levels=((price, amount),),
    )

    assert classify_close_quote(facts) is CloseQuoteState.UNKNOWN


def test_first_match_ignores_malformed_levels_after_unexecutable_option() -> None:
    facts = CloseQuoteFacts(
        option_availability=CloseOptionAvailability.UNEXECUTABLE,
        atomic_availability=CloseAtomicAvailability.ACTIVE,
        component_reference=PredicateTruth.TRUE,
        book_availability=CloseBookAvailability.FULL_QUANTITY,
        consumed_levels=((Decimal("NaN"), Decimal("0")),),
    )

    assert classify_close_quote(facts) is CloseQuoteState.UNEXECUTABLE


def test_close_opportunity_preserves_unknown_and_only_full_quote_is_eligible() -> None:
    unknown = evaluate_close_opportunity(
        quote_state=CloseQuoteState.UNKNOWN,
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=(),
        close_direction="BUY",
        short_leg_taker_commission_fraction=None,
        long_leg_taker_commission_fraction=None,
        fee_rate_index_fraction=Decimal("0.0003"),
        close_index_usdc_per_btc=None,
        net_entry_credit_usdc=Decimal("16.4"),
        expected_product=LINEAR_BTC_USDC,
        entry_product_spec_identity=None,
        expected_short_leg_instrument_name=None,
        expected_long_leg_instrument_name=None,
        expected_width_usdc_per_btc=None,
    )
    assert unknown.eligibility is CloseOpportunityEligibility.UNKNOWN
    assert unknown.economics is None

    incompatible_fee = evaluate_close_opportunity(
        quote_state=CloseQuoteState.ATOMIC_COMBO_CLOSE_QUOTE,
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=((Decimal("50"), Decimal("0.1")),),
        close_direction="BUY",
        short_leg_taker_commission_fraction=Decimal("0.0004"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        fee_rate_index_fraction=Decimal("0.0003"),
        close_index_usdc_per_btc=Decimal("100000"),
        net_entry_credit_usdc=Decimal("16.4"),
        expected_product=LINEAR_BTC_USDC,
        entry_product_spec_identity=None,
        expected_short_leg_instrument_name=None,
        expected_long_leg_instrument_name=None,
        expected_width_usdc_per_btc=None,
    )
    assert incompatible_fee.eligibility is CloseOpportunityEligibility.INELIGIBLE
    assert incompatible_fee.economics is None

    eligible = evaluate_close_opportunity(
        quote_state=CloseQuoteState.ATOMIC_COMBO_CLOSE_QUOTE,
        full_quantity_btc=Decimal("0.1"),
        consumed_levels=((Decimal("50"), Decimal("0.1")),),
        close_direction="BUY",
        short_leg_taker_commission_fraction=Decimal("0.0003"),
        long_leg_taker_commission_fraction=Decimal("0.0003"),
        fee_rate_index_fraction=Decimal("0.0003"),
        close_index_usdc_per_btc=Decimal("100000"),
        net_entry_credit_usdc=Decimal("16.4"),
        expected_product=LINEAR_BTC_USDC,
        entry_product_spec_identity=None,
        expected_short_leg_instrument_name=None,
        expected_long_leg_instrument_name=None,
        expected_width_usdc_per_btc=None,
    )
    assert eligible.eligibility is CloseOpportunityEligibility.ELIGIBLE
    assert eligible.economics is not None
    assert eligible.economics.projected_shadow_net_pnl_usdc == Decimal("8.4")


def test_post_close_attempt_is_one_shot_and_barrier_owner_is_explicit() -> None:
    attempt = PostCloseAttempt.schedule(
        anchor_identity="sha256:" + "1" * 64,
        first_close_action_identity="sha256:" + "2" * 64,
        canonical_combo_identity="sha256:" + "3" * 64,
        request_id=17,
        boundary=_boundary(2),
        request_instrument_name="BTC-CLOSE-COMBO",
        origin_quote_witness=SubscriptionAdmissionRefreshWitness(
            source_identity=canonical_identity(
                "SubscriptionAdmissionRefreshSourceIdentity",
                _boundary(2).runtime_identity,
                1,
                1,
                "sha256:" + "3" * 64,
                "snapshot",
                None,
                10,
                100,
                _boundary(2).as_object(),
            ),
            boundary=_boundary(2),
            canonical_combo_identity="sha256:" + "3" * 64,
            instrument_name="BTC-CLOSE-COMBO",
            change_id=10,
            source_timestamp_ms=100,
            snapshot_kind="snapshot",
            session_epoch=1,
            subscription_generation=1,
        ),
    )
    intent = attempt.take_request_intent()
    assert intent is not None and intent.request_id == 17
    assert attempt.take_request_intent() is None
    attempt.mark_sent(request_id=17, boundary=_boundary(3), send_budget_ms=30)
    response_boundary = _boundary(4)
    response = RpcAdmissionRefreshWitness(
        source_identity=canonical_identity(
            "RpcAdmissionRefreshSourceIdentity",
            response_boundary.runtime_identity,
            17,
            "public/get_order_book",
            "sha256:" + "3" * 64,
            {"instrument_name": "BTC-CLOSE-COMBO", "depth": 10000},
            _boundary(2).as_object(),
            _boundary(3).as_object(),
            11,
            200,
            response_boundary.as_object(),
        ),
        boundary=response_boundary,
        canonical_combo_identity="sha256:" + "3" * 64,
        instrument_name="BTC-CLOSE-COMBO",
        request_params={"instrument_name": "BTC-CLOSE-COMBO", "depth": 10000},
        change_id=11,
        source_timestamp_ms=200,
        request_id=17,
        candidate_origin_boundary=_boundary(2),
        sent_boundary=_boundary(3),
        market_frontier_change_id=11,
        market_frontier_session_epoch=1,
        response_matches_frontier=True,
        response_covers_full_quantity=True,
    )
    wrong_response = RpcAdmissionRefreshWitness(
        **{
            **response.__dict__,
            "request_id": 99,
            "source_identity": canonical_identity(
                "RpcAdmissionRefreshSourceIdentity",
                response_boundary.runtime_identity,
                99,
                "public/get_order_book",
                "sha256:" + "3" * 64,
                {"instrument_name": "BTC-CLOSE-COMBO", "depth": 10000},
                _boundary(2).as_object(),
                _boundary(3).as_object(),
                11,
                200,
                response_boundary.as_object(),
            ),
        }
    )
    assert not attempt.accept_response(witness=wrong_response, response_budget_ms=30)
    assert attempt.accept_response(witness=response, response_budget_ms=30)
    assert attempt.terminal_status is PostCloseAttemptStatus.SUCCESS
    assert attempt.terminal_owner is PostCloseAttemptOwner.ORDINARY
    terminal = attempt.terminal_identity
    assert not attempt.censor(boundary=_boundary(5), owner=PostCloseAttemptOwner.STOP)
    assert attempt.terminal_identity == terminal

    pending = PostCloseAttempt.schedule(
        anchor_identity="sha256:" + "5" * 64,
        first_close_action_identity="sha256:" + "6" * 64,
        canonical_combo_identity="sha256:" + "7" * 64,
        request_id=18,
        boundary=_boundary(2),
        request_instrument_name="BTC-CLOSE-COMBO",
        origin_quote_witness=SubscriptionAdmissionRefreshWitness(
            source_identity=canonical_identity(
                "SubscriptionAdmissionRefreshSourceIdentity",
                _boundary(2).runtime_identity,
                1,
                1,
                "sha256:" + "7" * 64,
                "snapshot",
                None,
                10,
                100,
                _boundary(2).as_object(),
            ),
            boundary=_boundary(2),
            canonical_combo_identity="sha256:" + "7" * 64,
            instrument_name="BTC-CLOSE-COMBO",
            change_id=10,
            source_timestamp_ms=100,
            snapshot_kind="snapshot",
            session_epoch=1,
            subscription_generation=1,
        ),
    )
    assert pending.censor(boundary=_boundary(3), owner=PostCloseAttemptOwner.FAILURE)
    assert pending.terminal_status is PostCloseAttemptStatus.CENSORED
    assert pending.terminal_owner is PostCloseAttemptOwner.FAILURE


def test_admitted_observation_selects_the_first_exit_without_online_cohort_state() -> None:
    observation = Observation.admitted(
        outcome_contract_identity="sha256:" + "1" * 64,
        shadow_entry_identity="sha256:" + "2" * 64,
        entry_boundary=_boundary(1),
    )
    observation.latch_close("sha256:" + "3" * 64, _boundary(2))
    first = observation.accept_eligible_exit(
        close_opportunity_evaluation_identity="sha256:" + "4" * 64,
        boundary=_boundary(3),
    )
    assert first is not None
    assert (
        observation.accept_eligible_exit(
            close_opportunity_evaluation_identity="sha256:" + "5" * 64,
            boundary=_boundary(4),
        )
        is None
    )
    assert observation.state is OutcomeState.MATURE_KNOWN
    assert observation.observation_quality is ObservationQuality.CONTINUOUS
    assert observation.qualification_eligible
    assert not hasattr(observation, "cohort_enrolled")
    assert not hasattr(observation, "rejected")


def test_gapped_observation_can_mature_known_but_is_not_qualification_eligible() -> None:
    entry = CaseFactBoundary(0, _boundary(1))
    close = CaseFactBoundary(
        1,
        FactBoundary(
            code_identity="c" * 40,
            runtime_identity="sha256:" + "d" * 64,
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=10,
            causal_seq=1,
        ),
    )
    exit_boundary = CaseFactBoundary(
        2,
        FactBoundary(
            code_identity="e" * 40,
            runtime_identity="sha256:" + "f" * 64,
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=10,
            causal_seq=1,
        ),
    )
    observation = Observation.admitted(
        outcome_contract_identity="sha256:" + "1" * 64,
        shadow_entry_identity="sha256:" + "2" * 64,
        entry_boundary=entry,
        observation_quality=ObservationQuality.GAPPED,
    )

    observation.latch_close("sha256:" + "3" * 64, close)
    selected = observation.accept_eligible_exit(
        close_opportunity_evaluation_identity="sha256:" + "4" * 64,
        boundary=exit_boundary,
    )

    assert selected is not None
    assert observation.state is OutcomeState.MATURE_KNOWN
    assert observation.observation_quality is ObservationQuality.GAPPED
    assert not observation.qualification_eligible
    assert observation.reducer.terminal_case_boundary == exit_boundary
    assert observation.reducer.terminal_boundary == exit_boundary.fact_boundary


@pytest.mark.parametrize("terminal_source", (TerminalSource.STOP, TerminalSource.FAILURE))
def test_process_end_does_not_settle_an_admitted_observation(
    terminal_source: TerminalSource,
) -> None:
    observation = Observation.admitted(
        outcome_contract_identity="sha256:" + "1" * 64,
        shadow_entry_identity="sha256:" + "2" * 64,
        entry_boundary=_boundary(1),
    )
    observation.latch_close("sha256:" + "3" * 64, _boundary(2))

    state = observation.settle_without_exit(
        boundary=_boundary(3),
        ordinary_attempt_terminal=False,
        lifecycle_ready=False,
        terminal_source=terminal_source,
    )

    assert state is OutcomeState.PENDING
    assert observation.terminal_outcome_identity is None
    assert observation.reducer.terminal_case_boundary is None
