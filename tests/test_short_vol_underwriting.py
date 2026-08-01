from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
import short_vol_underwriting.evidence as evidence_module
from short_vol_underwriting import (
    CANDIDATE_INVALIDATION_REASONS,
    COHORT_COUNT_KEYS,
    OUTCOME_OBJECT_KINDS,
    POSITION_CLOSE_REASONS,
    UNDERWRITING_OBJECT_KINDS,
    AdmissionAttempt,
    AdmissionTerminalOutcome,
    AlignedPair,
    CandidateState,
    CloseAtomicAvailability,
    CloseBookAvailability,
    CloseOpportunityEligibility,
    CloseOptionAvailability,
    CloseQuoteFacts,
    CloseQuoteState,
    DownstreamEvidenceError,
    DownstreamEvidenceWriter,
    FactBoundary,
    FixedContractShadowOwner,
    ManifestError,
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
    RefreshClassification,
    RejectedAnchor,
    RejectedAnchorSelector,
    RpcAdmissionRefreshWitness,
    RuntimeBindings,
    SourceFact,
    SubscriptionAdmissionRefreshWitness,
    TerminalSource,
    UnderwritingFacts,
    ValidatedManifest,
    canonical_identity,
    classify_close_quote,
    cohort_conservation_status,
    compute_close_economics,
    compute_cohort_rates,
    compute_entry_economics,
    evaluate_close_opportunity,
    load_manifest_bytes,
    load_policy_chain,
    manifest_identity_bytes,
    ordered_candidate_invalidation,
    read_current_evidence,
)
from short_vol_underwriting.evidence import (
    _read_complete_evidence_with_git_reader,
    validate_downstream_object,
)
from short_vol_underwriting.validation import validate_attempt_relationships

ROOT = Path(__file__).resolve().parents[1]
RADAR_POLICY_IDENTITY = "sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4"
UNDERWRITING_POLICY_IDENTITY = (
    "sha256:be056d7fad71668954103e1e383372c3b03db9b27b8d03ce0a030d39285629af"
)
POSITION_POLICY_IDENTITY = "sha256:498a298be50cb356f43886ae7ba02d1f6da065233ae9b2b52e9a230cf7f9c439"
UNDERWRITING_CONTRACT_DIGEST = (
    "sha256:9cbaecf57fb1db0dedf782a4ab002b655e43319a1ad7c5880db3d7b4682d4b03"
)
OUTCOME_CONTRACT_DIGEST = "sha256:61a032fe0fe265d66a38bcbb1a3c8498409664fedbda2c8bd0a245180581a695"


def _fake_manifest_git_reader(repository: Path, arguments: Sequence[str]) -> bytes:
    assert repository == ROOT
    command = tuple(arguments)
    if command == ("rev-parse", "--show-toplevel"):
        return f"{ROOT}\n".encode()
    if command == ("cat-file", "-e", f"{'a' * 40}^{{commit}}"):
        return b""
    if command == ("rev-parse", f"{'a' * 40}^{{tree}}"):
        return f"{'d' * 40}\n".encode()
    if command == ("cat-file", "-e", f"{'d' * 40}^{{tree}}"):
        return b""
    prefix = f"{'a' * 40}:"
    if len(command) == 3 and command[:2] == ("cat-file", "blob") and command[2].startswith(prefix):
        return (ROOT / command[2].removeprefix(prefix)).read_bytes()
    raise AssertionError(f"unexpected Git object command: {command}")


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


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
    )


def _owner(
    tmp_path: Path,
    *,
    close_enrollment: bool = True,
) -> tuple[FixedContractShadowOwner, RuntimeBindings]:
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
        underwriting_position_contract_digest=UNDERWRITING_CONTRACT_DIGEST,
        outcome_contract_digest=OUTCOME_CONTRACT_DIGEST,
    )
    owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        writer=DownstreamEvidenceWriter(tmp_path, bindings=bindings),
    )
    owner.open_enrollment(_boundary(0, 100))
    if close_enrollment:
        owner.close_enrollment(_boundary(100, 200))
    return owner, bindings


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

    assert replace(facts, active_episode_identity=None).active_episode_identity is None


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
    )

    with pytest.raises(ValueError, match="not bound"):
        owner.settle_underwriting((facts,), allocate_request_id=lambda: 41)
    assert owner.writer.objects == ()


def _manifest_for_owner(tmp_path: Path) -> tuple[ValidatedManifest, dict[str, object]]:
    runtime = "sha256:" + "b" * 64
    clock = "sha256:" + "c" * 64

    def trigger(kind: str, at: int) -> dict[str, object]:
        return {
            "runtime_identity": runtime,
            "supervisor_clock_identity": clock,
            "trigger_monotonic_ms": at,
            "trigger_kind": kind,
        }

    final_trigger = trigger("FINAL_STOP", 300)
    value: dict[str, object] = {
        "manifest_content_schema_identity": canonical_identity(
            "SHORT_VOL_SHADOW_FORWARD_COHORT_MANIFEST_SCHEMA",
            OUTCOME_CONTRACT_DIGEST,
        ),
        "candidate_commit": "a" * 40,
        "candidate_tree": "d" * 40,
        "intended_remote_ref": "refs/heads/codex/short-vol-fixed-contract-public-shadow-runtime",
        "verified_remote_ref": "a" * 40,
        "outcome_contract_identity": canonical_identity(
            "OUTCOME_CONTRACT",
            "SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT",
            OUTCOME_CONTRACT_DIGEST,
            "a" * 40,
            RADAR_POLICY_IDENTITY,
            UNDERWRITING_POLICY_IDENTITY,
            POSITION_POLICY_IDENTITY,
        ),
        "outcome_contract_path": "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md",
        "radar_policy_path": "policies/short-vol-fixed-public-shadow-radar.json",
        "radar_policy_identity": RADAR_POLICY_IDENTITY,
        "underwriting_policy_path": "policies/short-vol-fixed-public-shadow-underwriting.json",
        "underwriting_policy_identity": UNDERWRITING_POLICY_IDENTITY,
        "position_policy_path": "policies/short-vol-fixed-public-shadow-position.json",
        "position_policy_identity": POSITION_POLICY_IDENTITY,
        "evidence_directory": str(tmp_path),
        "process_argv": ["python", "-m", "radar_runtime", "observe-shadow"],
        "process_cwd": str(ROOT),
        "required_pre_run_checks": ["make check"],
        "runtime_start_trigger": trigger("RUNTIME_START", 100),
        "enrollment_cutoff_trigger": trigger("ENROLLMENT_CUTOFF", 200),
        "final_stop_trigger": final_trigger,
        "clean_stop_predicate": "final stop trigger accepted independent of results",
        "emergency_stop_authority": "sha256:" + "e" * 64,
        "forbidden_capabilities": [
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
        ],
        "non_claims": [
            "sha256:" + "3" * 64,
            "sha256:" + "4" * 64,
        ],
    }
    exact = (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()
    return load_manifest_bytes(exact), final_trigger


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
    return _object(read_current_evidence(tmp_path, bindings=bindings)[identity]["payload"])


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


def test_exact_policy_chain_loads_before_runtime_and_has_no_fourth_policy() -> None:
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
    assert chain.position.latest_exit_lead_ms == 1_800_000
    assert chain.position.underwriting_policy_identity == UNDERWRITING_POLICY_IDENTITY
    assert not hasattr(chain, "admission")
    assert not hasattr(chain, "outcome")


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
        "UNDERWRITING_POSITION_SUMMARY",
    )
    assert len(OUTCOME_OBJECT_KINDS) == 13
    assert not set(UNDERWRITING_OBJECT_KINDS) & set(OUTCOME_OBJECT_KINDS)


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


def test_outcome_terminal_order_is_exit_then_natural_then_stop_or_failure() -> None:
    reducer = OutcomeReducer(entry_boundary=_boundary(1))
    reducer.latch_close("sha256:" + "d" * 64, _boundary(2))
    result = reducer.settle(
        boundary=_boundary(3),
        eligible_exit_identity="sha256:" + "e" * 64,
        ordinary_attempt_terminal=True,
        lifecycle_ready=True,
        terminal_source=TerminalSource.FAILURE,
    )
    assert result is OutcomeState.MATURE_KNOWN
    assert reducer.settle(boundary=_boundary(4), terminal_source=TerminalSource.STOP) is result

    natural = OutcomeReducer(entry_boundary=_boundary(1))
    natural.latch_close("sha256:" + "f" * 64, _boundary(2))
    assert (
        natural.settle(
            boundary=_boundary(3),
            ordinary_attempt_terminal=True,
            lifecycle_ready=True,
            terminal_source=TerminalSource.FAILURE,
        )
        is OutcomeState.MATURE_UNKNOWN
    )

    censored = OutcomeReducer(entry_boundary=_boundary(1))
    censored.latch_close("sha256:" + "1" * 64, _boundary(2))
    assert (
        censored.settle(
            boundary=_boundary(3),
            ordinary_attempt_terminal=False,
            lifecycle_ready=True,
            terminal_source=TerminalSource.FAILURE,
        )
        is OutcomeState.CENSORED_AT_FAILURE
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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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

    assert owner.writer.objects == ()


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
    before = tuple(owner.writer.objects)
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

    assert tuple(owner.writer.objects) == before


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
    objects = read_current_evidence(tmp_path, bindings=bindings)
    payload = _object(next(iter(objects.values()))["payload"])
    assert payload["availability"] == "UNKNOWN"
    assert payload["unknown_reasons"] == ["INDEX_SOURCE_UNKNOWN"]


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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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


def test_owner_enrolls_anchor_after_start_before_cutoff_control_is_realized(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path, close_enrollment=False)

    _admit_owner(owner)

    objects = read_current_evidence(tmp_path, bindings=bindings)
    observation = next(
        value for value in objects.values() if value["object_kind"] == "SHADOW_OUTCOME_OBSERVATION"
    )
    assert _object(observation["payload"])["cohort_enrolled"] is True


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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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
        "ALIGNED_POLICY_NO_TRADE_PAIR",
    ]
    assert future.request_intents == ()
    objects = read_current_evidence(tmp_path, bindings=bindings)
    assert (
        sum(value["object_kind"] == "SHADOW_COUNTERFACTUAL_EXIT" for value in objects.values()) == 1
    )
    assert sum(value["object_kind"] == "SHADOW_OUTCOME" for value in objects.values()) == 1
    manifest, final_trigger = _manifest_for_owner(tmp_path)
    terminal_boundary = _boundary(101, 300)
    terminal_identity = canonical_identity(
        "PreboundSupervisorTriggerIdentity",
        final_trigger,
    )
    owner.terminate(
        boundary=terminal_boundary,
        terminal_source_identity=terminal_identity,
        terminal_source=TerminalSource.STOP,
    )
    owner.finalize_terminal(
        manifest=manifest,
        terminal_disposition="PLANNED_CLEAN_STOP",
        terminal_source=final_trigger,
    )
    complete = read_current_evidence(tmp_path, bindings=bindings)
    cohort_summary = next(
        value
        for value in complete.values()
        if value["object_kind"] == "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY"
    )
    summary_payload = _object(cohort_summary["payload"])
    counts = _object(summary_payload["counts"])
    assert counts["shadow_mature_known_count"] == 1
    assert counts["enrolled_admitted_mature_known_win_count"] == 1
    assert summary_payload["conservation_status"] == "MET"


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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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
    action = _object(read_current_evidence(tmp_path, bindings=bindings)[action_identity]["payload"])
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


def test_outcome_validator_enforces_exact_terminal_null_matrix(tmp_path: Path) -> None:
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
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_position_facts(
            boundary=_boundary(5, 150),
            change_id=13,
            previous_change_id=12,
        ),
        allocate_request_id=lambda: 43,
    )
    objects = read_current_evidence(tmp_path, bindings=bindings)
    outcome = next(value for value in objects.values() if value["object_kind"] == "SHADOW_OUTCOME")

    missing_attempt_owner = json.loads(json.dumps(outcome))
    missing_attempt_owner["payload"]["post_close_attempt_terminal_owner"] = None
    with pytest.raises(DownstreamEvidenceError, match=r"all required|terminal owner"):
        validate_downstream_object(missing_attempt_owner, bindings=bindings)

    mature_with_supervisor = json.loads(json.dumps(outcome))
    mature_with_supervisor["payload"]["terminal_supervisor_source_identity"] = "sha256:" + "f" * 64
    with pytest.raises(DownstreamEvidenceError, match="supervisor"):
        validate_downstream_object(mature_with_supervisor, bindings=bindings)

    partial_close_tuple = json.loads(json.dumps(outcome))
    partial_close_tuple["payload"]["post_close_attempt_terminal_identity"] = None
    with pytest.raises(DownstreamEvidenceError, match=r"all required|nullable"):
        validate_downstream_object(partial_close_tuple, bindings=bindings)


def test_downstream_validator_rejects_provenance_from_a_future_causal_boundary(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    _admit_owner(owner)
    objects = read_current_evidence(tmp_path, bindings=bindings)
    entry = next(value for value in objects.values() if value["object_kind"] == "SHADOW_ENTRY")
    tampered = json.loads(json.dumps(entry))
    provenance = tampered["source_provenance"]
    assert isinstance(provenance, list)
    receipt = _object(_object(provenance[0])["receipt_fact_boundary"])
    object_boundary = _object(tampered["fact_boundary"])
    receipt["causal_seq"] = int(cast(int, object_boundary["causal_seq"])) + 1

    with pytest.raises(DownstreamEvidenceError, match=r"future|causal"):
        validate_downstream_object(tampered, bindings=bindings)


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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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
    first_objects = read_current_evidence(tmp_path, bindings=bindings)
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
    second_objects = read_current_evidence(tmp_path, bindings=bindings)
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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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
    objects = read_current_evidence(tmp_path, bindings=bindings)
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

    objects = read_current_evidence(tmp_path, bindings=bindings)
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
        for value in read_current_evidence(tmp_path, bindings=bindings).values()
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
        for value in read_current_evidence(tmp_path, bindings=bindings).values()
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
        for value in read_current_evidence(tmp_path, bindings=bindings).values()
        if value["object_kind"] == "CLOSE_QUOTE_EVALUATION"
    ]
    assert len(quotes) == 1
    assert quotes[0]["close_quote_state"] == "ATOMIC_COMBO_CLOSE_QUOTE"
    assert quotes[0]["consumed_levels"] == [{"price_usdc_per_btc": "-1", "amount_btc": "0.1"}]
    assert quotes[0]["gross_close_cashflow_usdc"] == "0.1"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("price_usdc_per_btc", "NaN", "price"),
        ("price_usdc_per_btc", "Infinity", "price"),
        ("amount_btc", "0", "amount"),
        ("amount_btc", "-0.1", "amount"),
        ("amount_btc", "NaN", "amount"),
        ("amount_btc", "Infinity", "amount"),
    ),
)
def test_current_reader_rejects_malformed_persisted_close_level(
    tmp_path: Path,
    field: str,
    value: str,
    error: str,
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
    quote = next(
        value
        for value in read_current_evidence(tmp_path, bindings=bindings).values()
        if value["object_kind"] == "CLOSE_QUOTE_EVALUATION"
    )
    tampered = json.loads(json.dumps(quote))
    tampered["payload"]["consumed_levels"][0][field] = value

    with pytest.raises(DownstreamEvidenceError, match=error):
        validate_downstream_object(tampered, bindings=bindings)


def test_current_reader_rederives_signed_close_cashflow_from_levels(
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
    quote = next(
        value
        for value in read_current_evidence(tmp_path, bindings=bindings).values()
        if value["object_kind"] == "CLOSE_QUOTE_EVALUATION"
    )
    tampered = json.loads(json.dumps(quote))
    tampered["payload"]["consumed_levels"][0]["price_usdc_per_btc"] = "-1"

    with pytest.raises(DownstreamEvidenceError, match="gross close cashflow"):
        validate_downstream_object(tampered, bindings=bindings)


def test_current_reader_rederives_signed_entry_credit_from_levels(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    _admit_owner(owner)
    entry = next(
        value
        for value in read_current_evidence(tmp_path, bindings=bindings).values()
        if value["object_kind"] == "SHADOW_ENTRY"
    )
    tampered = json.loads(json.dumps(entry))
    tampered["payload"]["entry_consumed_levels"][0]["price_usdc_per_btc"] = "-200"

    with pytest.raises(DownstreamEvidenceError, match="gross entry credit"):
        validate_downstream_object(tampered, bindings=bindings)


def test_owner_rejected_counterfactual_closes_through_same_future_quote(
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
    rejected = owner.settle_underwriting(
        (watch_facts,),
        allocate_request_id=lambda: 41,
    )
    rejected_anchor = next(
        item.object_identity
        for item in rejected.emitted
        if item.object_kind == "REJECTED_COUNTERFACTUAL_ANCHOR"
    )

    first_close = owner.settle_position(
        anchor_identity=rejected_anchor,
        facts=replace(
            _position_facts(
                boundary=_boundary(2, 120),
                change_id=11,
                previous_change_id=10,
            ),
            current_short_delta=Decimal("0.6"),
        ),
        allocate_request_id=lambda: 42,
    )
    assert [item.object_kind for item in first_close.emitted] == [
        "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION",
        "REJECTED_COUNTERFACTUAL_POSITION_ACTION",
        "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION",
    ]
    assert [intent.request_id for intent in first_close.request_intents] == [42]

    future = owner.settle_position(
        anchor_identity=rejected_anchor,
        facts=replace(
            _position_facts(
                boundary=_boundary(3, 130),
                change_id=12,
                previous_change_id=11,
            ),
            current_short_delta=Decimal("0.6"),
        ),
        allocate_request_id=lambda: 43,
    )
    assert [item.object_kind for item in future.emitted] == [
        "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION",
        "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION",
        "REJECTED_COUNTERFACTUAL_EXIT",
        "REJECTED_COUNTERFACTUAL_OUTCOME",
        "ALIGNED_POLICY_NO_TRADE_PAIR",
    ]
    assert future.request_intents == ()
    objects = read_current_evidence(tmp_path, bindings=bindings)
    assert (
        sum(value["object_kind"] == "REJECTED_COUNTERFACTUAL_OUTCOME" for value in objects.values())
        == 1
    )
    assert (
        sum(value["object_kind"] == "ALIGNED_POLICY_NO_TRADE_PAIR" for value in objects.values())
        == 1
    )
    rejected_exit = next(
        _object(value["payload"])
        for value in objects.values()
        if value["object_kind"] == "REJECTED_COUNTERFACTUAL_EXIT"
    )
    rejected_quote = _object(
        objects[cast(str, rejected_exit["close_quote_evaluation_identity"])]["payload"]
    )
    assert (
        rejected_exit["consumed_rule_scoped_quote_fingerprint"]
        == (rejected_quote["consumed_rule_scoped_quote_fingerprint"])
    )


def test_owner_repeated_rejected_evaluation_keeps_first_anchor_without_crashing(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    first = replace(
        _underwriting_facts(
            boundary=_boundary(1, 110),
            change_id=10,
            previous_change_id=None,
            snapshot_kind="snapshot",
        ),
        entry_consumed_levels=((Decimal("150"), Decimal("0.1")),),
    )
    first_transition = owner.settle_underwriting((first,), allocate_request_id=lambda: 41)
    first_anchor = next(
        item.object_identity
        for item in first_transition.emitted
        if item.object_kind == "REJECTED_COUNTERFACTUAL_ANCHOR"
    )
    repeated = replace(
        _underwriting_facts(
            boundary=_boundary(2, 120),
            change_id=11,
            previous_change_id=10,
            snapshot_kind="change",
        ),
        entry_consumed_levels=((Decimal("150"), Decimal("0.1")),),
    )

    second_transition = owner.settle_underwriting(
        (repeated,),
        allocate_request_id=lambda: 42,
    )

    assert all(
        item.object_kind != "REJECTED_COUNTERFACTUAL_ANCHOR" for item in second_transition.emitted
    )
    objects = read_current_evidence(tmp_path, bindings=bindings)
    anchors = [
        value
        for value in objects.values()
        if value["object_kind"] == "REJECTED_COUNTERFACTUAL_ANCHOR"
    ]
    assert len(anchors) == 1
    assert anchors[0]["object_identity"] == first_anchor


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
    invalidation_path = next(
        (
            tmp_path
            / "objects"
            / "CANDIDATE_INVALIDATION"
            / f"{item.object_identity.removeprefix('sha256:')}.json"
        )
        for item in transition.emitted
        if item.object_kind == "CANDIDATE_INVALIDATION"
    )
    payload = json.loads(invalidation_path.read_text())["payload"]
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


def test_owner_terminalizes_zero_business_and_writes_both_conservation_summaries(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path)
    manifest, final_trigger = _manifest_for_owner(tmp_path)
    terminal_boundary = _boundary(101, 300)
    terminal_identity = canonical_identity(
        "PreboundSupervisorTriggerIdentity",
        final_trigger,
    )
    owner.terminate(
        boundary=terminal_boundary,
        terminal_source_identity=terminal_identity,
        terminal_source=TerminalSource.STOP,
    )
    transition = owner.finalize_terminal(
        manifest=manifest,
        terminal_disposition="PLANNED_CLEAN_STOP",
        terminal_source=final_trigger,
    )
    assert [item.object_kind for item in transition.emitted] == [
        "UNDERWRITING_POSITION_SUMMARY",
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
    ]
    objects = read_current_evidence(tmp_path, bindings=bindings)
    summaries = {
        str(value["object_kind"]): _object(value["payload"])
        for value in objects.values()
        if str(value["object_kind"]).endswith("SUMMARY")
    }
    assert summaries["UNDERWRITING_POSITION_SUMMARY"]["conservation_status"] == "MET"
    assert summaries["SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY"]["conservation_status"] == "MET"
    assert all(
        rate is None
        for rate in _object(summaries["SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY"]["rates"]).values()
    )


def test_owner_failure_before_cutoff_censors_pending_trade_and_closes_enrollment(
    tmp_path: Path,
) -> None:
    owner, bindings = _owner(tmp_path, close_enrollment=False)
    _admit_owner(owner)
    manifest, _final_trigger = _manifest_for_owner(tmp_path)
    failure_boundary = _boundary(6, 150)
    failure_control = {
        "runtime_identity": bindings.runtime_identity,
        "supervisor_clock_identity": manifest.supervisor_clock_identity,
        "failure_source_identity": "sha256:" + "f" * 64,
        "control_monotonic_ms": 150,
        "control_kind": "PROCESS_FAILURE",
        "failure_kind": "FATAL_RUNTIME",
    }
    failure_identity = canonical_identity(
        "FatalFailureControlIdentity",
        failure_control,
    )
    owner.terminate(
        boundary=failure_boundary,
        terminal_source_identity=failure_identity,
        terminal_source=TerminalSource.FAILURE,
    )
    owner.finalize_terminal(
        manifest=manifest,
        terminal_disposition="PROCESS_FAILURE",
        terminal_source=failure_control,
    )
    (tmp_path / "manifest.json").write_bytes(manifest.exact_bytes)
    objects = _read_complete_evidence_with_git_reader(
        tmp_path,
        bindings=bindings,
        git_object_reader=_fake_manifest_git_reader,
    )
    outcome = next(value for value in objects.values() if value["object_kind"] == "SHADOW_OUTCOME")
    outcome_payload = _object(outcome["payload"])
    assert outcome_payload["terminal_state"] == "CENSORED_AT_FAILURE"
    summary = next(
        value
        for value in objects.values()
        if value["object_kind"] == "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY"
    )
    summary_payload = _object(summary["payload"])
    assert summary_payload["enrollment_end_reason"] == "TERMINAL_BEFORE_CUTOFF"
    assert summary_payload["enrollment_end_fact_boundary"] == failure_boundary.as_object()
    assert _object(summary_payload["counts"])["shadow_censored_failure_count"] == 1
    assert summary_payload["conservation_status"] == "MET"

    wrong_source_identity = "sha256:" + "0" * 64
    outcome_path = (
        tmp_path
        / "objects"
        / "SHADOW_OUTCOME"
        / f"{str(outcome['object_identity']).removeprefix('sha256:')}.json"
    )
    tampered = _object(json.loads(outcome_path.read_text()))
    _object(tampered["payload"])["terminal_supervisor_source_identity"] = wrong_source_identity
    provenance = tampered["source_provenance"]
    assert isinstance(provenance, list)
    supervisor_root = next(
        _object(root) for root in provenance if _object(root)["source_role"] == "SUPERVISOR_CONTROL"
    )
    supervisor_root["source_identity"] = wrong_source_identity
    outcome_path.write_text(
        json.dumps(tampered, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    assert read_current_evidence(tmp_path, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="differs from cohort summary"):
        _read_complete_evidence_with_git_reader(
            tmp_path,
            bindings=bindings,
            git_object_reader=_fake_manifest_git_reader,
        )


def test_owner_rejects_non_identity_process_failure_source(tmp_path: Path) -> None:
    owner, bindings = _owner(tmp_path, close_enrollment=False)
    manifest, _final_trigger = _manifest_for_owner(tmp_path)
    failure_boundary = _boundary(6, 150)
    failure_control = {
        "runtime_identity": bindings.runtime_identity,
        "supervisor_clock_identity": manifest.supervisor_clock_identity,
        "failure_source_identity": "not-an-identity",
        "control_monotonic_ms": 150,
        "control_kind": "PROCESS_FAILURE",
        "failure_kind": "FATAL_RUNTIME",
    }
    owner.terminate(
        boundary=failure_boundary,
        terminal_source_identity=canonical_identity(
            "FatalFailureControlIdentity",
            failure_control,
        ),
        terminal_source=TerminalSource.FAILURE,
    )

    with pytest.raises(ValueError, match="failure_source_identity"):
        owner.finalize_terminal(
            manifest=manifest,
            terminal_disposition="PROCESS_FAILURE",
            terminal_source=failure_control,
        )


def test_downstream_writer_current_reader_and_duplicate_rules(tmp_path: Path) -> None:
    bindings = RuntimeBindings(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        radar_policy_identity=RADAR_POLICY_IDENTITY,
        underwriting_policy_identity=UNDERWRITING_POLICY_IDENTITY,
        position_policy_identity=POSITION_POLICY_IDENTITY,
        underwriting_position_contract_digest=UNDERWRITING_CONTRACT_DIGEST,
        outcome_contract_digest=OUTCOME_CONTRACT_DIGEST,
    )
    writer = DownstreamEvidenceWriter(tmp_path, bindings=bindings)
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
    path = writer.write(
        object_kind="CANDIDATE_INVALIDATION",
        object_identity=identity,
        fact_boundary=_boundary(2),
        payload=payload,
        source_provenance=(),
    )
    assert path is not None
    assert writer.revision == 1
    assert (
        writer.write(
            object_kind="CANDIDATE_INVALIDATION",
            object_identity=identity,
            fact_boundary=_boundary(2),
            payload=payload,
            source_provenance=(),
        )
        is None
    )
    assert writer.revision == 1

    objects = read_current_evidence(tmp_path, bindings=bindings)
    assert tuple(objects) == (identity,)
    assert objects[identity]["object_kind"] == "CANDIDATE_INVALIDATION"

    with pytest.raises(DownstreamEvidenceError, match="conflicting"):
        writer.write(
            object_kind="CANDIDATE_INVALIDATION",
            object_identity=identity,
            fact_boundary=_boundary(2),
            payload=payload,
            source_provenance=(
                {
                    "source_role": "SUPERVISOR_CONTROL",
                    "source_identity": "sha256:" + "9" * 64,
                    "receipt_fact_boundary": _boundary(2).as_object(),
                },
            ),
        )
    assert writer.revision == 1

    with pytest.raises(DownstreamEvidenceError, match="identity mismatch"):
        writer.write(
            object_kind="CANDIDATE_INVALIDATION",
            object_identity="sha256:" + "1" * 64,
            fact_boundary=_boundary(2),
            payload=payload,
            source_provenance=(),
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
    with pytest.raises(DownstreamEvidenceError, match="missing its atomic Candidate"):
        writer.write(
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
            source_provenance=(
                {
                    "source_role": "ANCHOR",
                    "source_identity": missing_candidate,
                    "receipt_fact_boundary": _boundary(3).as_object(),
                },
            ),
        )
    assert writer.revision == 1

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["unknown_member"] = True
    path.write_text(
        json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(DownstreamEvidenceError, match=r"unknown|exact"):
        read_current_evidence(tmp_path, bindings=bindings)


def test_availability_write_keeps_local_validation_and_skips_attempt_graph_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_calls = 0
    graph_calls = 0
    original_local = evidence_module.validate_downstream_object
    original_graph = validate_attempt_relationships

    def count_local(value: Mapping[str, object], *, bindings: RuntimeBindings) -> None:
        nonlocal local_calls
        local_calls += 1
        original_local(value, bindings=bindings)

    def count_graph(
        objects: Mapping[str, Mapping[str, object]],
        *,
        require_complete: bool,
    ) -> None:
        nonlocal graph_calls
        graph_calls += 1
        original_graph(objects, require_complete=require_complete)

    monkeypatch.setattr(evidence_module, "validate_downstream_object", count_local)
    monkeypatch.setattr(evidence_module, "validate_attempt_relationships", count_graph)

    owner, bindings = _owner(tmp_path)
    transition = owner.settle_underwriting(
        (
            replace(
                _underwriting_facts(
                    boundary=_boundary(1, 110),
                    change_id=10,
                    previous_change_id=None,
                    snapshot_kind="snapshot",
                ),
                active_episode_identity=None,
                atomic_state="NOT_EVALUATED",
                quote_refresh_witness=None,
            ),
        ),
        allocate_request_id=lambda: 41,
    )

    assert [value.object_kind for value in transition.emitted] == [
        "UNDERWRITING_AVAILABILITY_EVALUATION"
    ]
    assert local_calls == 1
    assert graph_calls == 0
    assert owner.writer.revision == 1
    assert read_current_evidence(tmp_path, bindings=bindings)
    local_calls_after_reader = local_calls

    boundary = _boundary(2, 120)
    candidate_identity = "sha256:" + "c" * 64
    identity = canonical_identity(
        "CANDIDATE_INVALIDATION",
        candidate_identity,
        "RUNTIME_OR_CODE_IDENTITY_CHANGED",
        ["RUNTIME_OR_CODE_IDENTITY_CHANGED"],
        boundary.as_object(),
    )
    owner.writer.write(
        object_kind="CANDIDATE_INVALIDATION",
        object_identity=identity,
        fact_boundary=boundary,
        payload={
            "candidate_invalidation_identity": identity,
            "candidate_identity": candidate_identity,
            "primary_reason": "RUNTIME_OR_CODE_IDENTITY_CHANGED",
            "ordered_applicable_reason_vector": ["RUNTIME_OR_CODE_IDENTITY_CHANGED"],
            "terminal_fact_boundary": boundary.as_object(),
        },
        source_provenance=(),
    )

    assert local_calls == local_calls_after_reader + 1
    assert graph_calls == 1
    assert owner.writer.revision == 2


def test_manifest_normative_serializer_vector_and_closed_identity_graph(tmp_path: Path) -> None:
    vector = '{"kind":"组合","values":["' + "\N{GREEK SMALL LETTER ALPHA}" + '",1,null]}\n'
    assert manifest_identity_bytes(vector.encode()) == (
        "sha256:8467e20e8dd44a9849ac4b63dd33d086f4fb7cedc027d663c16f70e3ed4b68f9"
    )
    candidate = "a" * 40
    runtime = "sha256:" + "b" * 64
    clock = "sha256:" + "c" * 64
    outcome_contract_identity = canonical_identity(
        "OUTCOME_CONTRACT",
        "SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT",
        OUTCOME_CONTRACT_DIGEST,
        candidate,
        RADAR_POLICY_IDENTITY,
        UNDERWRITING_POLICY_IDENTITY,
        POSITION_POLICY_IDENTITY,
    )

    def trigger(kind: str, at: int) -> dict[str, object]:
        return {
            "runtime_identity": runtime,
            "supervisor_clock_identity": clock,
            "trigger_monotonic_ms": at,
            "trigger_kind": kind,
        }

    manifest: dict[str, object] = {
        "manifest_content_schema_identity": canonical_identity(
            "SHORT_VOL_SHADOW_FORWARD_COHORT_MANIFEST_SCHEMA",
            OUTCOME_CONTRACT_DIGEST,
        ),
        "candidate_commit": candidate,
        "candidate_tree": "d" * 40,
        "intended_remote_ref": "refs/heads/codex/short-vol-fixed-contract-public-shadow-runtime",
        "verified_remote_ref": candidate,
        "outcome_contract_identity": outcome_contract_identity,
        "outcome_contract_path": "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md",
        "radar_policy_path": "policies/short-vol-fixed-public-shadow-radar.json",
        "radar_policy_identity": RADAR_POLICY_IDENTITY,
        "underwriting_policy_path": "policies/short-vol-fixed-public-shadow-underwriting.json",
        "underwriting_policy_identity": UNDERWRITING_POLICY_IDENTITY,
        "position_policy_path": "policies/short-vol-fixed-public-shadow-position.json",
        "position_policy_identity": POSITION_POLICY_IDENTITY,
        "evidence_directory": str(tmp_path / "evidence"),
        "process_argv": ["python", "-m", "radar_runtime", "observe-shadow"],
        "process_cwd": str(ROOT),
        "required_pre_run_checks": ["make check"],
        "runtime_start_trigger": trigger("RUNTIME_START", 1),
        "enrollment_cutoff_trigger": trigger("ENROLLMENT_CUTOFF", 2),
        "final_stop_trigger": trigger("FINAL_STOP", 3),
        "clean_stop_predicate": "final stop trigger accepted independent of results",
        "emergency_stop_authority": "sha256:" + "e" * 64,
        "forbidden_capabilities": [
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
        ],
        "non_claims": [
            "sha256:" + "3" * 64,
            "sha256:" + "4" * 64,
        ],
    }
    exact = (
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()
    loaded = load_manifest_bytes(exact)
    assert loaded.candidate_commit == candidate
    assert loaded.runtime_identity == runtime
    assert loaded.manifest_identity == manifest_identity_bytes(exact)

    manifest["unknown"] = True
    bad = (
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()
    with pytest.raises(ManifestError, match=r"exact keys|order"):
        load_manifest_bytes(bad)


def test_cohort_conservation_and_exact_rates_never_fabricate_zero() -> None:
    zero = {key: 0 for key in COHORT_COUNT_KEYS}
    assert cohort_conservation_status(zero, evidence_status="COMPLETE") == "MET"
    assert all(rate is None for rate in compute_cohort_rates(zero).values())

    counts = dict(zero)
    counts.update(
        {
            "shadow_entry_count": 1,
            "shadow_observation_count": 1,
            "shadow_mature_known_count": 1,
            "shadow_outcome_count": 1,
            "shadow_selected_exit_count": 1,
            "shadow_terminal_pair_count": 1,
            "logical_admitted_pair_count": 1,
            "logical_aligned_pair_count": 1,
            "enrolled_admitted_pair_count": 1,
            "enrolled_admitted_mature_known_count": 1,
            "enrolled_aligned_pair_count": 1,
            "enrolled_terminal_pair_count": 1,
            "enrolled_comparable_pair_count": 1,
            "logical_no_trade_arm_count": 1,
            "durable_terminal_pair_count": 1,
            "durable_no_trade_arm_count": 1,
            "enrolled_admitted_mature_known_win_count": 1,
        }
    )
    assert cohort_conservation_status(counts, evidence_status="COMPLETE") == "MET"
    assert compute_cohort_rates(counts)["admitted_win_rate"] == {
        "numerator": 1,
        "denominator": 1,
    }

    counts["shadow_selected_exit_count"] = 0
    assert cohort_conservation_status(counts, evidence_status="COMPLETE") == "NOT_MET"


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


def test_rejected_anchor_is_first_causal_action_with_lexical_same_boundary_tie_break() -> None:
    selector = RejectedAnchorSelector()
    slot = "sha256:" + "1" * 64
    late = RejectedAnchor(
        slot_identity=slot,
        underwriting_action_identity="sha256:" + "f" * 64,
        action="WATCH",
        boundary=_boundary(2),
    )
    early = RejectedAnchor(
        slot_identity=slot,
        underwriting_action_identity="sha256:" + "0" * 64,
        action="ABSTAIN",
        boundary=_boundary(2),
    )
    selected = selector.select_boundary((late, early))
    assert selected == early
    assert (
        selector.select_boundary(
            (
                RejectedAnchor(
                    slot_identity=slot,
                    underwriting_action_identity="sha256:" + "a" * 64,
                    action="WATCH",
                    boundary=_boundary(3),
                ),
            )
        )
        == early
    )


def test_observation_first_exit_and_aligned_pair_are_terminal_and_no_hindsight() -> None:
    observation = Observation.admitted(
        outcome_contract_identity="sha256:" + "1" * 64,
        shadow_entry_identity="sha256:" + "2" * 64,
        entry_boundary=_boundary(1),
        cohort_enrolled=True,
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

    pair = AlignedPair.for_admitted(
        outcome_contract_identity="sha256:" + "1" * 64,
        shadow_entry_identity="sha256:" + "2" * 64,
        cohort_enrolled=True,
    )
    pair.terminalize(
        state=OutcomeState.MATURE_KNOWN,
        terminal_boundary=_boundary(3),
        trade_outcome_identity="sha256:" + "6" * 64,
        trade_net_pnl_usdc=Decimal("-2"),
    )
    assert pair.policy_advantage_usdc == Decimal("-2")
    with pytest.raises(ValueError, match="terminal"):
        pair.terminalize(
            state=OutcomeState.MATURE_UNKNOWN,
            terminal_boundary=_boundary(4),
            trade_outcome_identity="sha256:" + "7" * 64,
            trade_net_pnl_usdc=None,
        )
