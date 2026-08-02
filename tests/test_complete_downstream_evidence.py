from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from short_vol_underwriting import (
    POSITION_CLOSE_REASONS,
    UNDERWRITING_COUNT_KEYS,
    CloseAtomicAvailability,
    CloseBookAvailability,
    CloseOptionAvailability,
    DownstreamEvidenceError,
    DownstreamEvidenceWriter,
    FactBoundary,
    FixedContractShadowOwner,
    PositionFacts,
    PredicateTruth,
    RuntimeBindings,
    SourceFact,
    TerminalSource,
    canonical_identity,
    compute_cohort_rates,
    compute_underwriting_rates,
    derive_cohort_counts,
    derive_underwriting_counts,
    load_manifest_bytes,
    load_policy_chain,
    read_current_evidence,
    underwriting_conservation_status,
)
from short_vol_underwriting import (
    read_complete_evidence as _public_read_complete_evidence,
)
from short_vol_underwriting.evidence import (
    _read_complete_evidence_with_git_reader,
)
from test_short_vol_underwriting import (
    _admit_owner as _admit_mature_known_owner,
)
from test_short_vol_underwriting import (
    _boundary as _mature_known_boundary,
)
from test_short_vol_underwriting import (
    _manifest_for_owner as _manifest_for_mature_known_owner,
)
from test_short_vol_underwriting import (
    _owner as _mature_known_owner,
)
from test_short_vol_underwriting import (
    _position_facts as _mature_known_position_facts,
)
from test_short_vol_underwriting import (
    _underwriting_facts as _mature_known_underwriting_facts,
)

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
CANDIDATE_COMMIT = subprocess.run(
    ("git", "-C", str(ROOT), "rev-parse", "HEAD"),
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
CANDIDATE_TREE = subprocess.run(
    ("git", "-C", str(ROOT), "rev-parse", "HEAD^{tree}"),
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()


def _boundary(causal_seq: int, monotonic_ms: int) -> FactBoundary:
    return FactBoundary(
        code_identity=CANDIDATE_COMMIT,
        runtime_identity="sha256:" + "b" * 64,
        session_epoch=1,
        ingress_seq=causal_seq,
        received_monotonic_ms=monotonic_ms,
        causal_seq=causal_seq,
    )


def _manifest_bytes(directory: Path, *, predicate: str = "result-independent stop") -> bytes:
    runtime = "sha256:" + "b" * 64
    clock = "sha256:" + "c" * 64

    def trigger(kind: str, at: int) -> dict[str, object]:
        return {
            "runtime_identity": runtime,
            "supervisor_clock_identity": clock,
            "trigger_monotonic_ms": at,
            "trigger_kind": kind,
        }

    value = {
        "manifest_content_schema_identity": canonical_identity(
            "SHORT_VOL_SHADOW_FORWARD_COHORT_MANIFEST_SCHEMA",
            OUTCOME_CONTRACT_DIGEST,
        ),
        "candidate_commit": CANDIDATE_COMMIT,
        "candidate_tree": CANDIDATE_TREE,
        "intended_remote_ref": "refs/heads/codex/short-vol-fixed-contract-public-shadow-runtime",
        "verified_remote_ref": CANDIDATE_COMMIT,
        "outcome_contract_identity": canonical_identity(
            "OUTCOME_CONTRACT",
            "SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT",
            OUTCOME_CONTRACT_DIGEST,
            CANDIDATE_COMMIT,
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
        "evidence_directory": str(directory),
        "process_argv": ["python", "-m", "radar_runtime", "observe-shadow"],
        "process_cwd": str(ROOT),
        "required_pre_run_checks": ["make check"],
        "runtime_start_trigger": trigger("RUNTIME_START", 100),
        "enrollment_cutoff_trigger": trigger("ENROLLMENT_CUTOFF", 200),
        "final_stop_trigger": trigger("FINAL_STOP", 300),
        "clean_stop_predicate": predicate,
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
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _fake_git_object_reader(repository: Path, arguments: Sequence[str]) -> bytes:
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


def read_complete_evidence(
    directory: Path,
    *,
    bindings: RuntimeBindings,
) -> dict[str, dict[str, object]]:
    reader = _fake_git_object_reader if bindings.code_identity == "a" * 40 else None
    return (
        _read_complete_evidence_with_git_reader(
            directory,
            bindings=bindings,
            git_object_reader=reader,
        )
        if reader is not None
        else _public_read_complete_evidence(directory, bindings=bindings)
    )


@pytest.fixture
def complete_directory(tmp_path: Path) -> tuple[Path, RuntimeBindings]:
    bindings = RuntimeBindings(
        code_identity=CANDIDATE_COMMIT,
        runtime_identity="sha256:" + "b" * 64,
        radar_policy_identity=RADAR_POLICY_IDENTITY,
        underwriting_policy_identity=UNDERWRITING_POLICY_IDENTITY,
        position_policy_identity=POSITION_POLICY_IDENTITY,
        underwriting_position_contract_digest=UNDERWRITING_CONTRACT_DIGEST,
        outcome_contract_digest=OUTCOME_CONTRACT_DIGEST,
    )
    manifest_bytes = _manifest_bytes(tmp_path)
    manifest = load_manifest_bytes(manifest_bytes)
    (tmp_path / "manifest.json").write_bytes(manifest_bytes)
    policies = load_policy_chain(
        radar_path=ROOT / "policies/short-vol-fixed-public-shadow-radar.json",
        underwriting_path=ROOT / "policies/short-vol-fixed-public-shadow-underwriting.json",
        position_path=ROOT / "policies/short-vol-fixed-public-shadow-position.json",
        radar_identity=RADAR_POLICY_IDENTITY,
        underwriting_identity=UNDERWRITING_POLICY_IDENTITY,
        position_identity=POSITION_POLICY_IDENTITY,
    )
    owner = FixedContractShadowOwner(
        policies=policies,
        bindings=bindings,
        writer=DownstreamEvidenceWriter(tmp_path, bindings=bindings),
    )
    # Supervisor controls are committed at the first reducer boundary at or after
    # each pre-bound trigger; they need not land on the same millisecond.
    owner.open_enrollment(_boundary(0, 101))
    owner.close_enrollment(_boundary(100, 201))
    final_trigger = manifest.value["final_stop_trigger"]
    assert isinstance(final_trigger, dict)
    terminal_identity = canonical_identity(
        "PreboundSupervisorTriggerIdentity",
        final_trigger,
    )
    owner.terminate(
        boundary=_boundary(101, 301),
        terminal_source_identity=terminal_identity,
        terminal_source=TerminalSource.STOP,
    )
    owner.finalize_terminal(
        manifest=manifest,
        terminal_disposition="PLANNED_CLEAN_STOP",
        terminal_source=final_trigger,
    )
    return tmp_path, bindings


@pytest.fixture
def mature_known_complete_directory(
    tmp_path: Path,
) -> tuple[Path, RuntimeBindings]:
    owner, bindings = _mature_known_owner(tmp_path)
    entry_identity = _admit_mature_known_owner(owner)
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_mature_known_position_facts(
            boundary=_mature_known_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_mature_known_position_facts(
            boundary=_mature_known_boundary(5, 150),
            change_id=13,
            previous_change_id=12,
        ),
        allocate_request_id=lambda: 43,
    )
    manifest, final_trigger = _manifest_for_mature_known_owner(tmp_path)
    terminal_boundary = _mature_known_boundary(101, 300)
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
    (tmp_path / "manifest.json").write_bytes(manifest.exact_bytes)
    complete = read_complete_evidence(tmp_path, bindings=bindings)
    assert len(complete) == 20
    assert any(
        value["object_kind"] == "SHADOW_OUTCOME"
        and cast(Mapping[str, object], value["payload"])["terminal_state"] == "MATURE_KNOWN"
        for value in complete.values()
    )
    return tmp_path, bindings


def _mature_unknown_position_facts(*, boundary: FactBoundary) -> PositionFacts:
    facts = _mature_known_position_facts(
        boundary=boundary,
        change_id=13,
        previous_change_id=12,
    )
    return replace(
        facts,
        platform_continuous=False,
        required_sources_continuous=False,
        short_leg_state="delivered",
        long_leg_state="archivized",
        short_leg_active=False,
        long_leg_active=False,
        close_quote_facts=replace(
            facts.close_quote_facts,
            option_availability=CloseOptionAvailability.UNKNOWN,
            atomic_availability=CloseAtomicAvailability.UNKNOWN,
            component_reference=PredicateTruth.UNKNOWN,
            book_availability=CloseBookAvailability.UNKNOWN,
            consumed_levels=(),
        ),
        quote_source=None,
        quote_refresh_witness=None,
        current_combo_subscription_witness=None,
        lifecycle_short_source=SourceFact(
            canonical_identity("TestLifecycleShortSource", boundary.as_object()),
            boundary,
        ),
        lifecycle_long_source=SourceFact(
            canonical_identity("TestLifecycleLongSource", boundary.as_object()),
            boundary,
        ),
    )


@pytest.fixture(params=("admitted", "rejected"))
def mature_unknown_complete_directory(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> tuple[Path, RuntimeBindings, str]:
    owner, bindings = _mature_known_owner(tmp_path)
    family = cast(str, request.param)
    if family == "admitted":
        anchor_identity = _admit_mature_known_owner(owner)
        close_boundary = _mature_known_boundary(4, 140)
        failure_boundary = _mature_known_boundary(5, 150)
        owner.settle_position(
            anchor_identity=anchor_identity,
            facts=_mature_known_position_facts(
                boundary=close_boundary,
                change_id=12,
                previous_change_id=11,
            ),
            allocate_request_id=lambda: 42,
        )
        outcome_kind = "SHADOW_OUTCOME"
    else:
        watch_facts = replace(
            _mature_known_underwriting_facts(
                boundary=_mature_known_boundary(1, 110),
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
        anchor_identity = next(
            emitted.object_identity
            for emitted in rejected.emitted
            if emitted.object_kind == "REJECTED_COUNTERFACTUAL_ANCHOR"
        )
        close_boundary = _mature_known_boundary(2, 120)
        failure_boundary = _mature_known_boundary(3, 130)
        owner.settle_position(
            anchor_identity=anchor_identity,
            facts=replace(
                _mature_known_position_facts(
                    boundary=close_boundary,
                    change_id=11,
                    previous_change_id=10,
                ),
                current_short_delta=Decimal("0.6"),
            ),
            allocate_request_id=lambda: 42,
        )
        outcome_kind = "REJECTED_COUNTERFACTUAL_OUTCOME"
    owner.note_request_failure(request_id=42, boundary=failure_boundary)
    owner.settle_position(
        anchor_identity=anchor_identity,
        facts=_mature_unknown_position_facts(boundary=failure_boundary),
        allocate_request_id=lambda: 43,
    )
    manifest, final_trigger = _manifest_for_mature_known_owner(tmp_path)
    terminal_boundary = _mature_known_boundary(101, 300)
    owner.terminate(
        boundary=terminal_boundary,
        terminal_source_identity=canonical_identity(
            "PreboundSupervisorTriggerIdentity",
            final_trigger,
        ),
        terminal_source=TerminalSource.STOP,
    )
    owner.finalize_terminal(
        manifest=manifest,
        terminal_disposition="PLANNED_CLEAN_STOP",
        terminal_source=final_trigger,
    )
    (tmp_path / "manifest.json").write_bytes(manifest.exact_bytes)
    return tmp_path, bindings, outcome_kind


def _object_file(
    directory: Path,
    objects: dict[str, dict[str, object]],
    object_kind: str,
) -> Path:
    value = next(value for value in objects.values() if value["object_kind"] == object_kind)
    identity = str(value["object_identity"]).removeprefix("sha256:")
    return directory / "objects" / object_kind / f"{identity}.json"


def _summary_parts(
    summary: Mapping[str, object],
) -> tuple[dict[str, object], Sequence[Mapping[str, object]]]:
    payload = cast(Mapping[str, object], summary["payload"])
    provenance = cast(Sequence[Mapping[str, object]], summary["source_provenance"])
    return dict(payload), provenance


def _underwriting_counts(payload: Mapping[str, object]) -> dict[str, int]:
    counts = cast(Mapping[str, int], payload["counts"])
    return {key: counts[key] for key in UNDERWRITING_COUNT_KEYS}


def _rewrite_object(path: Path, value: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _retarget_provenance(
    value: dict[str, Any],
    *,
    role: str,
    old_identity: str,
    new_identity: str | None = None,
    new_boundary: Mapping[str, object] | None = None,
) -> None:
    for root in value["source_provenance"]:
        if root["source_role"] == role and root["source_identity"] == old_identity:
            if new_identity is not None:
                root["source_identity"] = new_identity
            if new_boundary is not None:
                root["receipt_fact_boundary"] = new_boundary
    value["source_provenance"].sort(key=lambda root: (root["source_role"], root["source_identity"]))


def _rewrite_underwriting_summary_from_objects(
    directory: Path,
    *,
    bindings: RuntimeBindings,
) -> None:
    objects = read_current_evidence(directory, bindings=bindings)
    summary = next(
        value
        for value in objects.values()
        if value["object_kind"] == "UNDERWRITING_POSITION_SUMMARY"
    )
    payload, provenance = _summary_parts(summary)
    counts = derive_underwriting_counts(tuple(objects.values()))
    rates = compute_underwriting_rates(counts)
    status = underwriting_conservation_status(counts)
    boundary = FactBoundary.from_object(payload["terminal_fact_boundary"])
    identity = canonical_identity(
        "UNDERWRITING_POSITION_SUMMARY",
        bindings.underwriting_position_contract_digest,
        bindings.code_identity,
        bindings.runtime_identity,
        bindings.radar_policy_identity,
        bindings.underwriting_policy_identity,
        bindings.position_policy_identity,
        payload["terminal_source_identity"],
        boundary.as_object(),
        counts,
        rates,
        status,
    )
    _object_file(directory, objects, "UNDERWRITING_POSITION_SUMMARY").unlink()
    DownstreamEvidenceWriter(directory, bindings=bindings).write(
        object_kind="UNDERWRITING_POSITION_SUMMARY",
        object_identity=identity,
        fact_boundary=boundary,
        payload={
            **payload,
            "underwriting_position_summary_identity": identity,
            "counts": counts,
            "rates": rates,
            "conservation_status": status,
        },
        source_provenance=provenance,
    )


@pytest.mark.parametrize(
    ("request_id", "request_method"),
    (
        (0, "public/get_order_book"),
        (41, "private/get_positions"),
    ),
)
def test_writer_rejects_illegal_admission_schedule_semantics(
    complete_directory: tuple[Path, RuntimeBindings],
    request_id: int,
    request_method: str,
) -> None:
    directory, bindings = complete_directory
    boundary = _boundary(102, 302)
    candidate_identity = "sha256:" + "5" * 64
    params = {"instrument_name": "BTC-TEST-COMBO", "depth": 10000}
    identity = canonical_identity(
        "ScheduledAdmissionAttemptIdentity",
        candidate_identity,
        request_id,
        request_method,
        params,
        boundary.as_object(),
    )

    with pytest.raises(DownstreamEvidenceError, match=r"request|method|positive"):
        DownstreamEvidenceWriter(directory, bindings=bindings).write(
            object_kind="ADMISSION_ATTEMPT_SCHEDULED",
            object_identity=identity,
            fact_boundary=boundary,
            payload={
                "scheduled_admission_attempt_identity": identity,
                "candidate_identity": candidate_identity,
                "request_id": request_id,
                "request_method": request_method,
                "request_params": params,
                "schedule_fact_boundary": boundary.as_object(),
            },
            source_provenance=(
                {
                    "source_role": "ANCHOR",
                    "source_identity": candidate_identity,
                    "receipt_fact_boundary": boundary.as_object(),
                },
            ),
        )


@pytest.mark.parametrize(
    ("request_member", "request_method", "request_params"),
    (
        (41, "private/get_positions", {"instrument_name": "BTC-TEST-COMBO", "depth": 10000}),
        ("ARBITRARY_MARKER", "public/get_order_book", None),
        (
            "NOT_REQUESTABLE_UNKNOWN",
            "public/get_order_book",
            {"instrument_name": "BTC-TEST-COMBO", "depth": 10000},
        ),
        (41, "public/get_order_book", None),
    ),
)
def test_writer_rejects_illegal_post_close_schedule_semantics(
    complete_directory: tuple[Path, RuntimeBindings],
    request_member: object,
    request_method: str,
    request_params: object,
) -> None:
    directory, bindings = complete_directory
    boundary = _boundary(102, 302)
    entry_identity = "sha256:" + "6" * 64
    action_identity = "sha256:" + "7" * 64
    identity = canonical_identity(
        "ScheduledPostCloseQuoteAttemptIdentity",
        entry_identity,
        action_identity,
        request_member,
        request_method,
        request_params,
        boundary.as_object(),
    )

    with pytest.raises(DownstreamEvidenceError, match=r"request|method|marker|params"):
        DownstreamEvidenceWriter(directory, bindings=bindings).write(
            object_kind="POST_CLOSE_ATTEMPT_SCHEDULED",
            object_identity=identity,
            fact_boundary=boundary,
            payload={
                "scheduled_post_close_attempt_identity": identity,
                "shadow_entry_identity": entry_identity,
                "first_latched_close_action_identity": action_identity,
                "request_id_or_marker": request_member,
                "request_method": request_method,
                "request_params": request_params,
                "schedule_fact_boundary": boundary.as_object(),
            },
            source_provenance=(
                {
                    "source_role": "POSITION_ACTION",
                    "source_identity": action_identity,
                    "receipt_fact_boundary": boundary.as_object(),
                },
            ),
        )


@pytest.mark.parametrize(
    ("object_kind", "field", "invalid_value"),
    (
        ("ADMISSION_ATTEMPT_TERMINAL", "terminal_source_identity", None),
        ("ADMISSION_ATTEMPT_TERMINAL", "matched_response_identity", {"private": "get_positions"}),
        ("POST_CLOSE_ATTEMPT_TERMINAL", "matched_response_identity", {"private": "get_positions"}),
    ),
)
def test_current_and_complete_readers_reject_invalid_attempt_terminal_sources(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
    object_kind: str,
    field: str,
    invalid_value: object,
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    path = _object_file(directory, objects, object_kind)
    value = json.loads(path.read_text())
    value["payload"][field] = invalid_value
    _rewrite_object(path, value)

    for reader in (read_current_evidence, read_complete_evidence):
        with pytest.raises(DownstreamEvidenceError, match=r"source|matched|identity"):
            reader(directory, bindings=bindings)


def test_current_and_complete_readers_require_exact_admission_terminal_provenance(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    path = _object_file(directory, objects, "ADMISSION_ATTEMPT_TERMINAL")
    value = json.loads(path.read_text())
    value["source_provenance"][0]["source_identity"] = "sha256:" + "f" * 64
    _rewrite_object(path, value)

    for reader in (read_current_evidence, read_complete_evidence):
        with pytest.raises(DownstreamEvidenceError, match=r"provenance|source"):
            reader(directory, bindings=bindings)


def test_current_reader_rejects_request_id_reuse_across_admission_and_post_close(
    tmp_path: Path,
) -> None:
    owner, bindings = _mature_known_owner(tmp_path)
    entry_identity = _admit_mature_known_owner(owner)

    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_mature_known_position_facts(
            boundary=_mature_known_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 41,
    )
    with pytest.raises(DownstreamEvidenceError, match=r"request id.*reused"):
        read_current_evidence(tmp_path, bindings=bindings)


def test_current_reader_rejects_rekeyed_cross_attempt_request_id_reuse(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    admission = next(
        value for value in objects.values() if value["object_kind"] == "ADMISSION_ATTEMPT_SCHEDULED"
    )
    admission_payload = cast(Mapping[str, object], admission["payload"])
    reused_id = cast(int, admission_payload["request_id"])
    old_path = _object_file(directory, objects, "POST_CLOSE_ATTEMPT_SCHEDULED")
    scheduled = json.loads(old_path.read_text())
    scheduled["payload"]["request_id_or_marker"] = reused_id
    request_params = scheduled["payload"]["request_params"]
    assert isinstance(request_params, dict)
    new_identity = canonical_identity(
        "ScheduledPostCloseQuoteAttemptIdentity",
        scheduled["payload"]["shadow_entry_identity"],
        scheduled["payload"]["first_latched_close_action_identity"],
        reused_id,
        scheduled["payload"]["request_method"],
        {
            "instrument_name": request_params["instrument_name"],
            "depth": request_params["depth"],
        },
        FactBoundary.from_object(scheduled["fact_boundary"]),
    )
    scheduled["object_identity"] = new_identity
    scheduled["payload"]["scheduled_post_close_attempt_identity"] = new_identity
    old_path.unlink()
    new_path = old_path.with_name(f"{new_identity.removeprefix('sha256:')}.json")
    _rewrite_object(new_path, scheduled)

    with pytest.raises(DownstreamEvidenceError, match=r"request id.*reused"):
        read_current_evidence(directory, bindings=bindings)


def test_current_reader_rejects_second_admission_schedule_for_candidate(
    tmp_path: Path,
) -> None:
    owner, bindings = _mature_known_owner(tmp_path)
    _admit_mature_known_owner(owner)
    scheduled = next(
        value
        for value in owner.writer.objects
        if value["object_kind"] == "ADMISSION_ATTEMPT_SCHEDULED"
    )
    payload = dict(cast(Mapping[str, object], scheduled["payload"]))
    payload["request_id"] = 99
    boundary = FactBoundary.from_object(scheduled["fact_boundary"])
    identity = canonical_identity(
        "ScheduledAdmissionAttemptIdentity",
        payload["candidate_identity"],
        99,
        payload["request_method"],
        payload["request_params"],
        boundary.as_object(),
    )
    payload["scheduled_admission_attempt_identity"] = identity

    owner.writer.write(
        object_kind="ADMISSION_ATTEMPT_SCHEDULED",
        object_identity=identity,
        fact_boundary=boundary,
        payload=payload,
        source_provenance=cast(
            Sequence[Mapping[str, object]],
            scheduled["source_provenance"],
        ),
    )
    with pytest.raises(DownstreamEvidenceError, match=r"multiple Admission schedules"):
        read_current_evidence(tmp_path, bindings=bindings)


def test_current_reader_rejects_rekeyed_second_admission_schedule_for_candidate(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    scheduled = next(
        value for value in objects.values() if value["object_kind"] == "ADMISSION_ATTEMPT_SCHEDULED"
    )
    duplicate = json.loads(json.dumps(scheduled))
    duplicate["payload"]["request_id"] = 99
    boundary = FactBoundary.from_object(duplicate["fact_boundary"])
    request_params = duplicate["payload"]["request_params"]
    assert isinstance(request_params, dict)
    identity = canonical_identity(
        "ScheduledAdmissionAttemptIdentity",
        duplicate["payload"]["candidate_identity"],
        99,
        duplicate["payload"]["request_method"],
        {
            "instrument_name": request_params["instrument_name"],
            "depth": request_params["depth"],
        },
        boundary.as_object(),
    )
    duplicate["object_identity"] = identity
    duplicate["payload"]["scheduled_admission_attempt_identity"] = identity
    path = (
        directory
        / "objects"
        / "ADMISSION_ATTEMPT_SCHEDULED"
        / f"{identity.removeprefix('sha256:')}.json"
    )
    _rewrite_object(path, duplicate)

    with pytest.raises(DownstreamEvidenceError, match=r"multiple Admission schedules"):
        read_current_evidence(directory, bindings=bindings)


@pytest.mark.parametrize(
    "marker",
    (
        "NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE",
        "NOT_REQUESTABLE_UNKNOWN",
    ),
)
def test_current_reader_rejects_requestable_post_close_terminal_with_marker(
    tmp_path: Path,
    marker: str,
) -> None:
    owner, bindings = _mature_known_owner(tmp_path)
    entry_identity = _admit_mature_known_owner(owner)
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_mature_known_position_facts(
            boundary=_mature_known_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    scheduled = next(
        value
        for value in owner.writer.objects
        if value["object_kind"] == "POST_CLOSE_ATTEMPT_SCHEDULED"
    )
    boundary = _mature_known_boundary(5, 150)
    scheduled_identity = cast(str, scheduled["object_identity"])
    identity = canonical_identity(
        "PostCloseAttemptTerminalIdentity",
        scheduled_identity,
        marker,
        "ORDINARY",
        boundary.as_object(),
    )

    owner.writer.write(
        object_kind="POST_CLOSE_ATTEMPT_TERMINAL",
        object_identity=identity,
        fact_boundary=boundary,
        payload={
            "post_close_attempt_terminal_identity": identity,
            "scheduled_post_close_attempt_identity": scheduled_identity,
            "terminal_status": marker,
            "terminal_owner": "ORDINARY",
            "terminal_fact_boundary": boundary.as_object(),
            "matched_response_identity": None,
        },
        source_provenance=(
            {
                "source_role": "ATTEMPT_CONTROL",
                "source_identity": identity,
                "receipt_fact_boundary": boundary.as_object(),
            },
        ),
    )
    with pytest.raises(DownstreamEvidenceError, match=r"cannot use a not-requestable terminal"):
        read_current_evidence(tmp_path, bindings=bindings)


@pytest.mark.parametrize(
    "marker",
    (
        "NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE",
        "NOT_REQUESTABLE_UNKNOWN",
    ),
)
def test_current_and_complete_readers_reject_rekeyed_requestable_terminal_with_marker(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
    marker: str,
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    old_path = _object_file(directory, objects, "POST_CLOSE_ATTEMPT_TERMINAL")
    terminal = json.loads(old_path.read_text())
    boundary = FactBoundary.from_object(terminal["fact_boundary"])
    terminal["payload"]["terminal_status"] = marker
    terminal["payload"]["matched_response_identity"] = None
    identity = canonical_identity(
        "PostCloseAttemptTerminalIdentity",
        terminal["payload"]["scheduled_post_close_attempt_identity"],
        marker,
        terminal["payload"]["terminal_owner"],
        boundary.as_object(),
    )
    terminal["object_identity"] = identity
    terminal["payload"]["post_close_attempt_terminal_identity"] = identity
    terminal["source_provenance"][0]["source_identity"] = identity
    old_path.unlink()
    path = old_path.with_name(f"{identity.removeprefix('sha256:')}.json")
    _rewrite_object(path, terminal)

    for reader in (read_current_evidence, read_complete_evidence):
        with pytest.raises(
            DownstreamEvidenceError,
            match=r"cannot use a not-requestable terminal",
        ):
            reader(directory, bindings=bindings)


@pytest.mark.parametrize(
    "object_kind",
    ("ADMISSION_ATTEMPT_TERMINAL", "POST_CLOSE_ATTEMPT_TERMINAL"),
)
def test_current_reader_rejects_rekeyed_requestable_terminal_at_schedule_boundary(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
    object_kind: str,
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    if object_kind == "ADMISSION_ATTEMPT_TERMINAL":
        schedule_kind = "ADMISSION_ATTEMPT_SCHEDULED"
        identity_field = "admission_attempt_terminal_identity"
        identity_label = "ADMISSION_ATTEMPT_TERMINAL"
    else:
        schedule_kind = "POST_CLOSE_ATTEMPT_SCHEDULED"
        identity_field = "post_close_attempt_terminal_identity"
        identity_label = "PostCloseAttemptTerminalIdentity"
    schedule = next(value for value in objects.values() if value["object_kind"] == schedule_kind)
    schedule_boundary = json.loads(json.dumps(schedule["fact_boundary"]))
    old_path = _object_file(directory, objects, object_kind)
    terminal = json.loads(old_path.read_text())
    terminal["fact_boundary"] = schedule_boundary
    terminal["payload"]["terminal_fact_boundary"] = schedule_boundary
    if object_kind == "ADMISSION_ATTEMPT_TERMINAL":
        new_identity = canonical_identity(
            identity_label,
            terminal["payload"]["scheduled_admission_attempt_identity"],
            terminal["payload"]["terminal_outcome"],
            FactBoundary.from_object(schedule_boundary),
        )
    else:
        new_identity = canonical_identity(
            identity_label,
            terminal["payload"]["scheduled_post_close_attempt_identity"],
            terminal["payload"]["terminal_status"],
            terminal["payload"]["terminal_owner"],
            FactBoundary.from_object(schedule_boundary),
        )
        terminal["source_provenance"][0]["source_identity"] = new_identity
    terminal["object_identity"] = new_identity
    terminal["payload"][identity_field] = new_identity
    terminal["source_provenance"][0]["receipt_fact_boundary"] = schedule_boundary
    old_path.unlink()
    new_path = old_path.with_name(f"{new_identity.removeprefix('sha256:')}.json")
    _rewrite_object(new_path, terminal)

    with pytest.raises(DownstreamEvidenceError, match=r"strictly after"):
        read_current_evidence(directory, bindings=bindings)


def test_current_reader_rejects_internally_rekeyed_admission_source_not_used_by_entry(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    path = _object_file(directory, objects, "ADMISSION_ATTEMPT_TERMINAL")
    terminal = json.loads(path.read_text())
    forged_source = "sha256:" + "f" * 64
    terminal["payload"]["terminal_source_identity"] = forged_source
    terminal["payload"]["matched_response_identity"] = forged_source
    terminal["source_provenance"][0]["source_identity"] = forged_source
    _rewrite_object(path, terminal)

    with pytest.raises(DownstreamEvidenceError, match=r"Entry quote source"):
        read_current_evidence(directory, bindings=bindings)


def test_current_and_complete_readers_bind_successful_post_close_match_to_quote(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    path = _object_file(directory, objects, "POST_CLOSE_ATTEMPT_TERMINAL")
    terminal = json.loads(path.read_text())
    terminal["payload"]["matched_response_identity"] = "sha256:" + "f" * 64
    _rewrite_object(path, terminal)

    for reader in (read_current_evidence, read_complete_evidence):
        with pytest.raises(DownstreamEvidenceError, match=r"matched response.*close quote"):
            reader(directory, bindings=bindings)


def test_current_reader_rejects_success_quote_for_another_shadow_entry(
    tmp_path: Path,
) -> None:
    target_directory = tmp_path / "target"
    template_directory = tmp_path / "template"
    target_directory.mkdir()
    template_directory.mkdir()
    target, bindings = _mature_known_owner(target_directory)
    target_entry = _admit_mature_known_owner(target)
    target.settle_position(
        anchor_identity=target_entry,
        facts=_mature_known_position_facts(
            boundary=_mature_known_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )

    template, _template_bindings = _mature_known_owner(template_directory)
    template_entry = _admit_mature_known_owner(template)
    template.settle_position(
        anchor_identity=template_entry,
        facts=_mature_known_position_facts(
            boundary=_mature_known_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    template.settle_position(
        anchor_identity=template_entry,
        facts=_mature_known_position_facts(
            boundary=_mature_known_boundary(5, 150),
            change_id=13,
            previous_change_id=12,
        ),
        allocate_request_id=lambda: 43,
    )
    quote = next(
        value
        for value in template.writer.objects
        if value["object_kind"] == "CLOSE_QUOTE_EVALUATION"
        and cast(Mapping[str, object], value["payload"])["close_conditioning"] != "PRE_CLOSE"
    )
    terminal = next(
        value
        for value in template.writer.objects
        if value["object_kind"] == "POST_CLOSE_ATTEMPT_TERMINAL"
    )
    quote_payload = dict(cast(Mapping[str, object], quote["payload"]))
    quote_payload["shadow_entry_identity"] = "sha256:" + "f" * 64
    boundary = FactBoundary.from_object(quote["fact_boundary"])
    structure = canonical_identity(
        "OfficialComboAndCanonicalLegIdentity",
        quote_payload["canonical_combo_identity"],
        quote_payload["canonical_leg_identities"],
    )
    quote_identity = canonical_identity(
        "CloseQuoteEvaluationIdentity",
        quote_payload["shadow_entry_identity"],
        POSITION_POLICY_IDENTITY,
        structure,
        quote_payload["close_direction"],
        quote_payload["full_quantity_btc"],
        quote_payload["consumed_rule_scoped_quote_fingerprint"],
        quote_payload["close_quote_state"],
        quote_payload["close_conditioning"],
        boundary.as_object(),
    )
    quote_payload["close_quote_evaluation_identity"] = quote_identity
    target.writer.write(
        object_kind="CLOSE_QUOTE_EVALUATION",
        object_identity=quote_identity,
        fact_boundary=boundary,
        payload=quote_payload,
        source_provenance=cast(
            Sequence[Mapping[str, object]],
            quote["source_provenance"],
        ),
    )

    target.writer.write(
        object_kind="POST_CLOSE_ATTEMPT_TERMINAL",
        object_identity=cast(str, terminal["object_identity"]),
        fact_boundary=FactBoundary.from_object(terminal["fact_boundary"]),
        payload=cast(Mapping[str, object], terminal["payload"]),
        source_provenance=cast(
            Sequence[Mapping[str, object]],
            terminal["source_provenance"],
        ),
    )
    with pytest.raises(DownstreamEvidenceError, match=r"owner/first CLOSE"):
        read_current_evidence(target_directory, bindings=bindings)


@pytest.mark.parametrize("mutation", ("REQUEST_ID", "SHADOW_ENTRY"))
def test_current_reader_rejects_rekeyed_post_close_schedule_cross_bind(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
    mutation: str,
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    old_path = _object_file(directory, objects, "POST_CLOSE_ATTEMPT_SCHEDULED")
    scheduled = json.loads(old_path.read_text())
    if mutation == "REQUEST_ID":
        scheduled["payload"]["request_id_or_marker"] = 99
    else:
        scheduled["payload"]["shadow_entry_identity"] = "sha256:" + "f" * 64
    request_params = scheduled["payload"]["request_params"]
    assert isinstance(request_params, dict)
    new_identity = canonical_identity(
        "ScheduledPostCloseQuoteAttemptIdentity",
        scheduled["payload"]["shadow_entry_identity"],
        scheduled["payload"]["first_latched_close_action_identity"],
        scheduled["payload"]["request_id_or_marker"],
        scheduled["payload"]["request_method"],
        {
            "instrument_name": request_params["instrument_name"],
            "depth": request_params["depth"],
        },
        FactBoundary.from_object(scheduled["fact_boundary"]),
    )
    scheduled["object_identity"] = new_identity
    scheduled["payload"]["scheduled_post_close_attempt_identity"] = new_identity
    old_path.unlink()
    new_path = old_path.with_name(f"{new_identity.removeprefix('sha256:')}.json")
    _rewrite_object(new_path, scheduled)

    with pytest.raises(DownstreamEvidenceError, match=r"schedule cross-bind"):
        read_current_evidence(directory, bindings=bindings)


def test_complete_reader_requires_attempt_owned_opportunity_for_every_ordinary_failure(
    mature_unknown_complete_directory: tuple[Path, RuntimeBindings, str],
) -> None:
    directory, bindings, _outcome_kind = mature_unknown_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    opportunity_kind = next(
        value["object_kind"]
        for value in objects.values()
        if value["object_kind"]
        in {
            "CLOSE_OPPORTUNITY_EVALUATION",
            "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION",
        }
        and cast(Mapping[str, object], value["payload"])["attempt_terminal_identity"] is not None
    )
    _object_file(directory, objects, opportunity_kind).unlink()
    _rewrite_underwriting_summary_from_objects(directory, bindings=bindings)

    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match=r"attempt|opportunity|terminal"):
        read_complete_evidence(directory, bindings=bindings)


def test_current_reader_rejects_orphan_duplicate_attempt_owned_opportunity(
    tmp_path: Path,
) -> None:
    owner, bindings = _mature_known_owner(tmp_path)
    entry_identity = _admit_mature_known_owner(owner)
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_mature_known_position_facts(
            boundary=_mature_known_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    owner.note_request_failure(
        request_id=42,
        boundary=_mature_known_boundary(5, 150),
    )
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_mature_unknown_position_facts(
            boundary=_mature_known_boundary(5, 150),
        ),
        allocate_request_id=lambda: 43,
    )
    opportunity = next(
        value
        for value in owner.writer.objects
        if value["object_kind"] == "CLOSE_OPPORTUNITY_EVALUATION"
        and cast(Mapping[str, object], value["payload"])["attempt_terminal_identity"] is not None
    )
    payload = dict(cast(Mapping[str, object], opportunity["payload"]))
    forged_terminal = "sha256:" + "f" * 64
    payload["attempt_terminal_identity"] = forged_terminal
    boundary = FactBoundary.from_object(opportunity["fact_boundary"])
    identity = canonical_identity(
        "CloseOpportunityEvaluationIdentity",
        payload["shadow_entry_identity"],
        payload["first_latched_close_action_identity"],
        forged_terminal,
        payload["opportunity_economics_business_fingerprint"],
        payload["eligibility"],
        boundary.as_object(),
    )
    payload["close_opportunity_evaluation_identity"] = identity
    provenance = json.loads(json.dumps(opportunity["source_provenance"]))
    for root in provenance:
        if root["source_role"] == "ATTEMPT_CONTROL":
            root["source_identity"] = forged_terminal

    owner.writer.write(
        object_kind="CLOSE_OPPORTUNITY_EVALUATION",
        object_identity=identity,
        fact_boundary=boundary,
        payload=payload,
        source_provenance=cast(Sequence[Mapping[str, object]], provenance),
    )
    with pytest.raises(
        DownstreamEvidenceError,
        match=r"missing its local terminal|duplicate.*owner boundary",
    ):
        read_current_evidence(tmp_path, bindings=bindings)


def test_current_reader_rejects_quote_and_attempt_opportunities_at_one_boundary(
    tmp_path: Path,
) -> None:
    target_directory = tmp_path / "target"
    template_directory = tmp_path / "template"
    target_directory.mkdir()
    template_directory.mkdir()
    target, bindings = _mature_known_owner(target_directory)
    target_entry = _admit_mature_known_owner(target)
    target.settle_position(
        anchor_identity=target_entry,
        facts=_mature_known_position_facts(
            boundary=_mature_known_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    target.note_request_failure(
        request_id=42,
        boundary=_mature_known_boundary(5, 150),
    )
    target.settle_position(
        anchor_identity=target_entry,
        facts=_mature_unknown_position_facts(
            boundary=_mature_known_boundary(5, 150),
        ),
        allocate_request_id=lambda: 43,
    )

    template, _template_bindings = _mature_known_owner(template_directory)
    template_entry = _admit_mature_known_owner(template)
    template.settle_position(
        anchor_identity=template_entry,
        facts=_mature_known_position_facts(
            boundary=_mature_known_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    template.settle_position(
        anchor_identity=template_entry,
        facts=_mature_known_position_facts(
            boundary=_mature_known_boundary(5, 150),
            change_id=13,
            previous_change_id=12,
        ),
        allocate_request_id=lambda: 43,
    )
    quote = next(
        value
        for value in template.writer.objects
        if value["object_kind"] == "CLOSE_QUOTE_EVALUATION"
        and cast(Mapping[str, object], value["payload"])["close_conditioning"] != "PRE_CLOSE"
    )
    opportunity = next(
        value
        for value in template.writer.objects
        if value["object_kind"] == "CLOSE_OPPORTUNITY_EVALUATION"
        and cast(Mapping[str, object], value["payload"])["close_quote_evaluation_identity"]
        is not None
    )
    target.writer.write(
        object_kind="CLOSE_QUOTE_EVALUATION",
        object_identity=cast(str, quote["object_identity"]),
        fact_boundary=FactBoundary.from_object(quote["fact_boundary"]),
        payload=cast(Mapping[str, object], quote["payload"]),
        source_provenance=cast(
            Sequence[Mapping[str, object]],
            quote["source_provenance"],
        ),
    )
    target.writer.write(
        object_kind="CLOSE_OPPORTUNITY_EVALUATION",
        object_identity=cast(str, opportunity["object_identity"]),
        fact_boundary=FactBoundary.from_object(opportunity["fact_boundary"]),
        payload=cast(Mapping[str, object], opportunity["payload"]),
        source_provenance=cast(
            Sequence[Mapping[str, object]],
            opportunity["source_provenance"],
        ),
    )
    with pytest.raises(DownstreamEvidenceError, match=r"duplicate close opportunities"):
        read_current_evidence(target_directory, bindings=bindings)


def test_current_and_complete_readers_reject_rekeyed_duplicate_attempt_opportunity(
    mature_unknown_complete_directory: tuple[Path, RuntimeBindings, str],
) -> None:
    directory, bindings, outcome_kind = mature_unknown_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    rejected = outcome_kind.startswith("REJECTED_")
    opportunity_kind = (
        "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION"
        if rejected
        else "CLOSE_OPPORTUNITY_EVALUATION"
    )
    opportunity = next(
        value
        for value in objects.values()
        if value["object_kind"] == opportunity_kind
        and cast(Mapping[str, object], value["payload"])["attempt_terminal_identity"] is not None
    )
    duplicate = json.loads(json.dumps(opportunity))
    payload = duplicate["payload"]
    forged_terminal = "sha256:" + "f" * 64
    payload["attempt_terminal_identity"] = forged_terminal
    boundary = FactBoundary.from_object(duplicate["fact_boundary"])
    label = (
        "RejectedCounterfactualCloseOpportunityEvaluationIdentity"
        if rejected
        else "CloseOpportunityEvaluationIdentity"
    )
    owner_field = "rejected_observation_identity" if rejected else "shadow_entry_identity"
    identity_field = (
        "rejected_close_opportunity_evaluation_identity"
        if rejected
        else "close_opportunity_evaluation_identity"
    )
    identity = canonical_identity(
        label,
        payload[owner_field],
        payload["first_latched_close_action_identity"],
        forged_terminal,
        payload["opportunity_economics_business_fingerprint"],
        payload["eligibility"],
        boundary.as_object(),
    )
    duplicate["object_identity"] = identity
    payload[identity_field] = identity
    for root in duplicate["source_provenance"]:
        if root["source_role"] == "ATTEMPT_CONTROL":
            root["source_identity"] = forged_terminal
    path = directory / "objects" / opportunity_kind / f"{identity.removeprefix('sha256:')}.json"
    _rewrite_object(path, duplicate)

    for reader in (read_current_evidence, read_complete_evidence):
        with pytest.raises(
            DownstreamEvidenceError,
            match=r"missing its local terminal|duplicate.*owner boundary|differs from its owning Outcome",
        ):
            reader(directory, bindings=bindings)


@pytest.mark.parametrize(
    "mature_unknown_complete_directory",
    ("rejected",),
    indirect=True,
)
def test_current_reader_binds_only_rejected_attempt_opportunity_to_outcome(
    mature_unknown_complete_directory: tuple[Path, RuntimeBindings, str],
) -> None:
    directory, bindings, outcome_kind = mature_unknown_complete_directory
    assert outcome_kind == "REJECTED_COUNTERFACTUAL_OUTCOME"
    objects = read_current_evidence(directory, bindings=bindings)
    opportunity_kind = "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION"
    opportunity = next(
        value
        for value in objects.values()
        if value["object_kind"] == opportunity_kind
        and cast(Mapping[str, object], value["payload"])["attempt_terminal_identity"] is not None
    )
    old_path = _object_file(directory, objects, opportunity_kind)
    rekeyed = json.loads(json.dumps(opportunity))
    payload = rekeyed["payload"]
    forged_terminal = "sha256:" + "f" * 64
    payload["attempt_terminal_identity"] = forged_terminal
    boundary = FactBoundary.from_object(rekeyed["fact_boundary"])
    identity = canonical_identity(
        "RejectedCounterfactualCloseOpportunityEvaluationIdentity",
        payload["rejected_observation_identity"],
        payload["first_latched_close_action_identity"],
        forged_terminal,
        payload["opportunity_economics_business_fingerprint"],
        payload["eligibility"],
        boundary.as_object(),
    )
    rekeyed["object_identity"] = identity
    payload["rejected_close_opportunity_evaluation_identity"] = identity
    for root in rekeyed["source_provenance"]:
        if root["source_role"] == "ATTEMPT_CONTROL":
            root["source_identity"] = forged_terminal
    old_path.unlink()
    path = old_path.with_name(f"{identity.removeprefix('sha256:')}.json")
    _rewrite_object(path, rekeyed)

    with pytest.raises(DownstreamEvidenceError, match=r"differs from its owning Outcome"):
        read_current_evidence(directory, bindings=bindings)


@pytest.mark.parametrize(
    "atomic_availability",
    (
        CloseAtomicAvailability.KNOWN_UNAVAILABLE,
        CloseAtomicAvailability.UNKNOWN,
    ),
)
def test_owner_and_complete_reader_accept_not_requestable_first_close_atomically(
    tmp_path: Path,
    atomic_availability: CloseAtomicAvailability,
) -> None:
    owner, bindings = _mature_known_owner(tmp_path)
    entry_identity = _admit_mature_known_owner(owner)
    first_close = _mature_known_position_facts(
        boundary=_mature_known_boundary(4, 140),
        change_id=12,
        previous_change_id=11,
    )
    first_close = replace(
        first_close,
        current_short_delta=Decimal("0.6"),
        close_quote_facts=replace(
            first_close.close_quote_facts,
            option_availability=(
                CloseOptionAvailability.TRADEABLE
                if atomic_availability is CloseAtomicAvailability.KNOWN_UNAVAILABLE
                else CloseOptionAvailability.UNKNOWN
            ),
            atomic_availability=atomic_availability,
            component_reference=PredicateTruth.UNKNOWN,
            book_availability=CloseBookAvailability.UNKNOWN,
            consumed_levels=(),
        ),
        quote_source=None,
        quote_refresh_witness=None,
        current_combo_subscription_witness=None,
    )
    transition = owner.settle_position(
        anchor_identity=entry_identity,
        facts=first_close,
        allocate_request_id=lambda: 42,
    )
    assert [item.object_kind for item in transition.emitted] == [
        "POSITION_EVALUATION",
        "POSITION_ACTION",
        "POST_CLOSE_ATTEMPT_SCHEDULED",
        "POST_CLOSE_ATTEMPT_TERMINAL",
        "CLOSE_OPPORTUNITY_EVALUATION",
    ]
    manifest, final_trigger = _manifest_for_mature_known_owner(tmp_path)
    terminal_boundary = _mature_known_boundary(101, 300)
    owner.terminate(
        boundary=terminal_boundary,
        terminal_source_identity=canonical_identity(
            "PreboundSupervisorTriggerIdentity",
            final_trigger,
        ),
        terminal_source=TerminalSource.STOP,
    )
    owner.finalize_terminal(
        manifest=manifest,
        terminal_disposition="PLANNED_CLEAN_STOP",
        terminal_source=final_trigger,
    )
    (tmp_path / "manifest.json").write_bytes(manifest.exact_bytes)

    complete = read_complete_evidence(tmp_path, bindings=bindings)
    scheduled = next(
        value
        for value in complete.values()
        if value["object_kind"] == "POST_CLOSE_ATTEMPT_SCHEDULED"
    )
    terminal = next(
        value
        for value in complete.values()
        if value["object_kind"] == "POST_CLOSE_ATTEMPT_TERMINAL"
    )
    opportunity = next(
        value
        for value in complete.values()
        if value["object_kind"] == "CLOSE_OPPORTUNITY_EVALUATION"
    )
    assert scheduled["fact_boundary"] == terminal["fact_boundary"] == opportunity["fact_boundary"]


def test_complete_reader_closes_manifest_summaries_and_rederived_counts(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory

    complete = read_complete_evidence(directory, bindings=bindings)

    assert {value["object_kind"] for value in complete.values()} == {
        "UNDERWRITING_POSITION_SUMMARY",
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
    }
    (directory / "diagnostics.txt").write_text("non-authoritative\n")
    assert read_complete_evidence(directory, bindings=bindings) == complete


def test_owner_writer_and_complete_reader_preserve_mature_unknown_for_both_families(
    mature_unknown_complete_directory: tuple[Path, RuntimeBindings, str],
) -> None:
    directory, bindings, outcome_kind = mature_unknown_complete_directory

    complete = read_complete_evidence(directory, bindings=bindings)

    outcome = next(value for value in complete.values() if value["object_kind"] == outcome_kind)
    payload = cast(Mapping[str, object], outcome["payload"])
    assert payload["terminal_state"] == "MATURE_UNKNOWN"
    assert payload["selected_exit_identity"] is None
    assert payload["post_close_attempt_terminal_owner"] == "ORDINARY"
    pair = next(
        value
        for value in complete.values()
        if value["object_kind"] == "ALIGNED_POLICY_NO_TRADE_PAIR"
    )
    pair_payload = cast(Mapping[str, object], pair["payload"])
    assert pair_payload["terminal_state"] == "MATURE_UNKNOWN"
    assert pair_payload["comparison_availability"] == "UNKNOWN"


def test_complete_reader_accepts_rejected_mature_known_graph_and_rejects_quote_tampering(
    tmp_path: Path,
) -> None:
    owner, bindings = _mature_known_owner(tmp_path)
    watch_facts = replace(
        _mature_known_underwriting_facts(
            boundary=_mature_known_boundary(1, 110),
            change_id=10,
            previous_change_id=None,
            snapshot_kind="snapshot",
        ),
        entry_consumed_levels=((Decimal("150"), Decimal("0.1")),),
    )
    rejected = owner.settle_underwriting((watch_facts,), allocate_request_id=lambda: 41)
    anchor_identity = next(
        emitted.object_identity
        for emitted in rejected.emitted
        if emitted.object_kind == "REJECTED_COUNTERFACTUAL_ANCHOR"
    )
    owner.settle_position(
        anchor_identity=anchor_identity,
        facts=replace(
            _mature_known_position_facts(
                boundary=_mature_known_boundary(2, 120),
                change_id=11,
                previous_change_id=10,
            ),
            current_short_delta=Decimal("0.6"),
        ),
        allocate_request_id=lambda: 42,
    )
    owner.settle_position(
        anchor_identity=anchor_identity,
        facts=replace(
            _mature_known_position_facts(
                boundary=_mature_known_boundary(3, 130),
                change_id=12,
                previous_change_id=11,
            ),
            current_short_delta=Decimal("0.6"),
        ),
        allocate_request_id=lambda: 43,
    )
    manifest, final_trigger = _manifest_for_mature_known_owner(tmp_path)
    terminal_boundary = _mature_known_boundary(101, 300)
    owner.terminate(
        boundary=terminal_boundary,
        terminal_source_identity=canonical_identity(
            "PreboundSupervisorTriggerIdentity",
            final_trigger,
        ),
        terminal_source=TerminalSource.STOP,
    )
    owner.finalize_terminal(
        manifest=manifest,
        terminal_disposition="PLANNED_CLEAN_STOP",
        terminal_source=final_trigger,
    )
    (tmp_path / "manifest.json").write_bytes(manifest.exact_bytes)

    complete = read_complete_evidence(tmp_path, bindings=bindings)

    outcome = next(
        value
        for value in complete.values()
        if value["object_kind"] == "REJECTED_COUNTERFACTUAL_OUTCOME"
    )
    assert cast(Mapping[str, object], outcome["payload"])["terminal_state"] == "MATURE_KNOWN"
    exit_path = _object_file(
        tmp_path,
        complete,
        "REJECTED_COUNTERFACTUAL_EXIT",
    )
    selected_exit = json.loads(exit_path.read_text())
    tampered_fingerprint = "sha256:" + "f" * 64
    selected_exit["payload"]["consumed_rule_scoped_quote_fingerprint"] = tampered_fingerprint
    for root in selected_exit["source_provenance"]:
        if root["source_role"] == "COMBO_QUOTE":
            root["source_identity"] = tampered_fingerprint
    _rewrite_object(exit_path, selected_exit)

    with pytest.raises(
        DownstreamEvidenceError,
        match=r"rejected exit quote fingerprint.*owning close quote",
    ):
        read_current_evidence(tmp_path, bindings=bindings)
    with pytest.raises(
        DownstreamEvidenceError,
        match=r"rejected exit quote fingerprint.*owning close quote",
    ):
        read_complete_evidence(tmp_path, bindings=bindings)


def test_complete_reader_reproves_local_named_git_graph_without_remote_access(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory
    commands: list[tuple[str, ...]] = []

    def local_reader(repository: Path, arguments: Sequence[str]) -> bytes:
        commands.append(tuple(arguments))
        return subprocess.run(
            ("git", "-C", str(repository), *arguments),
            check=True,
            capture_output=True,
        ).stdout

    _read_complete_evidence_with_git_reader(
        directory,
        bindings=bindings,
        git_object_reader=local_reader,
    )

    assert ("cat-file", "-e", f"{CANDIDATE_COMMIT}^{{commit}}") in commands
    assert ("rev-parse", f"{CANDIDATE_COMMIT}^{{tree}}") in commands
    assert all("ls-remote" not in command for command in commands)
    assert all("HEAD" not in command for command in commands)


def test_public_complete_reader_cannot_replace_local_git_proof(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = mature_known_complete_directory

    private_result = _read_complete_evidence_with_git_reader(
        directory,
        bindings=bindings,
        git_object_reader=_fake_git_object_reader,
    )
    assert len(private_result) == 20
    with pytest.raises(DownstreamEvidenceError, match="local Git"):
        _public_read_complete_evidence(directory, bindings=bindings)
    with pytest.raises(TypeError, match="git_object_reader"):
        cast(Any, _public_read_complete_evidence)(
            directory,
            bindings=bindings,
            git_object_reader=_fake_git_object_reader,
        )


def test_complete_reader_rejects_missing_named_commit(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory

    def missing_commit(_repository: Path, arguments: Sequence[str]) -> bytes:
        if tuple(arguments) == ("rev-parse", "--show-toplevel"):
            return f"{ROOT}\n".encode()
        raise OSError("missing named commit")

    with pytest.raises(DownstreamEvidenceError, match="local Git"):
        _read_complete_evidence_with_git_reader(
            directory,
            bindings=bindings,
            git_object_reader=missing_commit,
        )


def test_complete_reader_rejects_wrong_named_tree(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory

    def wrong_tree(repository: Path, arguments: Sequence[str]) -> bytes:
        if tuple(arguments) == ("rev-parse", f"{CANDIDATE_COMMIT}^{{tree}}"):
            return f"{'f' * 40}\n".encode()
        return subprocess.run(
            ("git", "-C", str(repository), *arguments),
            check=True,
            capture_output=True,
        ).stdout

    with pytest.raises(DownstreamEvidenceError, match="tree"):
        _read_complete_evidence_with_git_reader(
            directory,
            bindings=bindings,
            git_object_reader=wrong_tree,
        )


@pytest.mark.parametrize(
    ("path", "label"),
    (
        (
            "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md",
            "Outcome contract",
        ),
        ("policies/short-vol-fixed-public-shadow-radar.json", "Radar Policy"),
        (
            "policies/short-vol-fixed-public-shadow-underwriting.json",
            "Underwriting Policy",
        ),
        ("policies/short-vol-fixed-public-shadow-position.json", "Position Policy"),
    ),
)
def test_complete_reader_rejects_wrong_named_contract_or_policy_blob(
    complete_directory: tuple[Path, RuntimeBindings],
    path: str,
    label: str,
) -> None:
    directory, bindings = complete_directory
    spec = f"{CANDIDATE_COMMIT}:{path}"

    def wrong_blob(repository: Path, arguments: Sequence[str]) -> bytes:
        if tuple(arguments) == ("cat-file", "blob", spec):
            return b"{}\n"
        return subprocess.run(
            ("git", "-C", str(repository), *arguments),
            check=True,
            capture_output=True,
        ).stdout

    with pytest.raises(DownstreamEvidenceError, match=label):
        _read_complete_evidence_with_git_reader(
            directory,
            bindings=bindings,
            git_object_reader=wrong_blob,
        )


@pytest.mark.parametrize(
    "object_kind",
    (
        "ADMISSION_ATTEMPT_SCHEDULED",
        "ADMISSION_ATTEMPT_TERMINAL",
        "POST_CLOSE_ATTEMPT_SCHEDULED",
        "POST_CLOSE_ATTEMPT_TERMINAL",
    ),
)
def test_complete_reader_requires_each_local_attempt_relationship_object(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
    object_kind: str,
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    _object_file(directory, objects, object_kind).unlink()

    with pytest.raises(DownstreamEvidenceError, match="attempt"):
        read_complete_evidence(directory, bindings=bindings)


@pytest.mark.parametrize(
    "object_kinds",
    (
        (
            "ADMISSION_ATTEMPT_SCHEDULED",
            "ADMISSION_ATTEMPT_TERMINAL",
        ),
        (
            "POST_CLOSE_ATTEMPT_SCHEDULED",
            "POST_CLOSE_ATTEMPT_TERMINAL",
        ),
    ),
)
def test_complete_reader_cannot_lose_an_entire_local_attempt_relationship(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
    object_kinds: tuple[str, str],
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    for object_kind in object_kinds:
        _object_file(directory, objects, object_kind).unlink()

    with pytest.raises(DownstreamEvidenceError, match="attempt"):
        read_complete_evidence(directory, bindings=bindings)


def test_partial_reader_stays_partial_when_manifest_or_summary_is_absent(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory
    read_current_evidence(directory, bindings=bindings)
    (directory / "manifest.json").unlink()

    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match=r"manifest\.json"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_rejects_missing_terminal_summary(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    _object_file(directory, objects, "UNDERWRITING_POSITION_SUMMARY").unlink()

    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="exactly one"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_rejects_changed_manifest_identity(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory
    (directory / "manifest.json").write_bytes(
        _manifest_bytes(directory, predicate="different result-independent stop")
    )

    with pytest.raises(DownstreamEvidenceError, match="manifest identity"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_rejects_unknown_and_authoritative_namespace_pollution(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    cohort_path = _object_file(
        directory,
        objects,
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
    )
    cohort = json.loads(cohort_path.read_text())
    cohort["payload"]["evidence_status"] = "INCOMPLETE"
    cohort["payload"]["conservation_status"] = "UNKNOWN"
    cohort_path.write_text(
        json.dumps(cohort, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DownstreamEvidenceError, match=r"COMPLETE|UNKNOWN"):
        read_complete_evidence(directory, bindings=bindings)

    cohort_path.write_bytes(
        json.dumps(
            objects[
                next(
                    key
                    for key, value in objects.items()
                    if value["object_kind"] == "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY"
                )
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    (directory / "objects" / "pollution.txt").write_text("invalid\n")
    with pytest.raises(DownstreamEvidenceError, match="unknown entry inside objects"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_rejects_self_consistent_summary_not_derived_from_objects(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    summary = next(
        value
        for value in objects.values()
        if value["object_kind"] == "UNDERWRITING_POSITION_SUMMARY"
    )
    payload, provenance = _summary_parts(summary)
    counts = _underwriting_counts(payload)
    counts["underwriting_availability_not_evaluated_count"] = 1
    rates = compute_underwriting_rates(counts)
    boundary = FactBoundary.from_object(payload["terminal_fact_boundary"])
    identity = canonical_identity(
        "UNDERWRITING_POSITION_SUMMARY",
        bindings.underwriting_position_contract_digest,
        bindings.code_identity,
        bindings.runtime_identity,
        bindings.radar_policy_identity,
        bindings.underwriting_policy_identity,
        bindings.position_policy_identity,
        payload["terminal_source_identity"],
        boundary.as_object(),
        counts,
        rates,
        "MET",
    )
    _object_file(directory, objects, "UNDERWRITING_POSITION_SUMMARY").unlink()
    DownstreamEvidenceWriter(directory, bindings=bindings).write(
        object_kind="UNDERWRITING_POSITION_SUMMARY",
        object_identity=identity,
        fact_boundary=boundary,
        payload={
            **payload,
            "underwriting_position_summary_identity": identity,
            "counts": counts,
            "rates": rates,
        },
        source_provenance=provenance,
    )

    with pytest.raises(DownstreamEvidenceError, match="derived Underwriting counts"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_requires_summary_terminal_cross_bind(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    summary = next(
        value
        for value in objects.values()
        if value["object_kind"] == "UNDERWRITING_POSITION_SUMMARY"
    )
    payload, provenance = _summary_parts(summary)
    counts = _underwriting_counts(payload)
    rates = compute_underwriting_rates(counts)
    boundary = _boundary(102, 300)
    identity = canonical_identity(
        "UNDERWRITING_POSITION_SUMMARY",
        bindings.underwriting_position_contract_digest,
        bindings.code_identity,
        bindings.runtime_identity,
        bindings.radar_policy_identity,
        bindings.underwriting_policy_identity,
        bindings.position_policy_identity,
        payload["terminal_source_identity"],
        boundary.as_object(),
        counts,
        rates,
        "MET",
    )
    _object_file(directory, objects, "UNDERWRITING_POSITION_SUMMARY").unlink()
    DownstreamEvidenceWriter(directory, bindings=bindings).write(
        object_kind="UNDERWRITING_POSITION_SUMMARY",
        object_identity=identity,
        fact_boundary=boundary,
        payload={
            **payload,
            "underwriting_position_summary_identity": identity,
            "terminal_fact_boundary": boundary.as_object(),
            "counts": counts,
            "rates": rates,
        },
        source_provenance=[
            {
                **item,
                "receipt_fact_boundary": boundary.as_object(),
            }
            for item in provenance
        ],
    )

    with pytest.raises(DownstreamEvidenceError, match="terminal"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_rejects_two_individually_valid_underwriting_summaries(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    summary = next(
        value
        for value in objects.values()
        if value["object_kind"] == "UNDERWRITING_POSITION_SUMMARY"
    )
    payload, provenance = _summary_parts(summary)
    counts = _underwriting_counts(payload)
    rates = compute_underwriting_rates(counts)
    boundary = _boundary(102, 300)
    identity = canonical_identity(
        "UNDERWRITING_POSITION_SUMMARY",
        bindings.underwriting_position_contract_digest,
        bindings.code_identity,
        bindings.runtime_identity,
        bindings.radar_policy_identity,
        bindings.underwriting_policy_identity,
        bindings.position_policy_identity,
        payload["terminal_source_identity"],
        boundary.as_object(),
        counts,
        rates,
        "MET",
    )
    DownstreamEvidenceWriter(directory, bindings=bindings).write(
        object_kind="UNDERWRITING_POSITION_SUMMARY",
        object_identity=identity,
        fact_boundary=boundary,
        payload={
            **payload,
            "underwriting_position_summary_identity": identity,
            "terminal_fact_boundary": boundary.as_object(),
            "counts": counts,
            "rates": rates,
        },
        source_provenance=[
            {
                **item,
                "receipt_fact_boundary": boundary.as_object(),
            }
            for item in provenance
        ],
    )

    with pytest.raises(DownstreamEvidenceError, match="exactly one"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_reconstructs_exact_summary_manifest_provenance(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    cohort_path = _object_file(
        directory,
        objects,
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
    )
    cohort = json.loads(cohort_path.read_text())
    cohort["source_provenance"].pop()
    cohort_path.write_text(
        json.dumps(cohort, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="exact one-hop provenance"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_rejects_pair_pnl_that_differs_from_outcome(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    pair_path = _object_file(directory, objects, "ALIGNED_POLICY_NO_TRADE_PAIR")
    pair = json.loads(pair_path.read_text())
    pair["payload"]["trade_net_pnl_after_public_standard_fee_reserve_usdc"] = "123"
    pair["payload"]["policy_advantage_usdc"] = "123"
    _rewrite_object(pair_path, pair)

    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match=r"pair.*Outcome|Outcome.*pair"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_rejects_exit_structure_that_differs_from_owning_quote(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    exit_path = _object_file(directory, objects, "SHADOW_COUNTERFACTUAL_EXIT")
    selected_exit = json.loads(exit_path.read_text())
    selected_exit["payload"]["canonical_combo_identity"] = "sha256:" + "f" * 64
    _rewrite_object(exit_path, selected_exit)

    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match=r"exit.*quote|quote.*exit"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_rejects_two_actions_for_one_position_evaluation(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    action = next(value for value in objects.values() if value["object_kind"] == "POSITION_ACTION")
    action_payload = dict(cast(Mapping[str, object], action["payload"]))
    truth_vector = cast(list[str], action_payload["ordered_predicate_truth_vector"])
    evaluation_identity = cast(str, action_payload["position_evaluation_identity"])
    duplicate_identity = canonical_identity(
        "PositionActionIdentity",
        evaluation_identity,
        "HOLD",
        truth_vector,
        [],
    )
    duplicate_payload = {
        **action_payload,
        "position_action_identity": duplicate_identity,
        "serialized_action": "HOLD",
        "ordered_latched_close_reason_vector": [],
        "primary_close_reason": None,
        "secondary_close_reasons": [],
        "first_latched_close_action_identity": None,
        "scheduled_post_close_attempt_identity": None,
    }
    DownstreamEvidenceWriter(directory, bindings=bindings).write(
        object_kind="POSITION_ACTION",
        object_identity=duplicate_identity,
        fact_boundary=FactBoundary.from_object(action["fact_boundary"]),
        payload=duplicate_payload,
        source_provenance=cast(Sequence[Mapping[str, object]], action["source_provenance"]),
    )

    with pytest.raises(DownstreamEvidenceError, match=r"duplicate.*action|action.*duplicate"):
        read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match=r"duplicate.*action|action.*duplicate"):
        read_complete_evidence(directory, bindings=bindings)


@pytest.mark.parametrize(
    "field",
    (
        "entry_index_usdc_per_btc",
        "entry_index_source_identity",
        "entry_index_fact_boundary",
        "entry_short_leg_mark_iv_fraction",
        "entry_short_leg_mark_iv_source_identity",
        "entry_short_leg_mark_iv_fact_boundary",
    ),
)
def test_current_and_complete_readers_bind_position_entry_sources(
    mature_unknown_complete_directory: tuple[Path, RuntimeBindings, str],
    field: str,
) -> None:
    directory, bindings, outcome_kind = mature_unknown_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    evaluation_kind = (
        "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION"
        if outcome_kind.startswith("REJECTED_")
        else "POSITION_EVALUATION"
    )
    evaluation_value = min(
        (value for value in objects.values() if value["object_kind"] == evaluation_kind),
        key=lambda value: cast(Mapping[str, int], value["fact_boundary"])["causal_seq"],
    )
    evaluation_path = (
        directory
        / "objects"
        / evaluation_kind
        / f"{cast(str, evaluation_value['object_identity']).removeprefix('sha256:')}.json"
    )
    evaluation = json.loads(evaluation_path.read_text())
    rejected = outcome_kind.startswith("REJECTED_")
    if field.endswith("_fact_boundary"):
        old_identity = evaluation["payload"][field.replace("_fact_boundary", "_source_identity")]
        new_boundary = _mature_known_boundary(2, 120).as_object()
        evaluation["payload"][field] = new_boundary
        if rejected and field == "entry_index_fact_boundary":
            evaluation["payload"]["prior_evaluation_index_fact_boundary"] = new_boundary
        if rejected:
            _retarget_provenance(
                evaluation,
                role=("POSITION_FACT" if "mark_iv" in field else "INDEX"),
                old_identity=old_identity,
                new_boundary=new_boundary,
            )
    elif field.endswith("_source_identity"):
        old_identity = evaluation["payload"][field]
        evaluation["payload"][field] = "sha256:" + "f" * 64
        if rejected and field == "entry_index_source_identity":
            evaluation["payload"]["prior_evaluation_index_source_identity"] = "sha256:" + "f" * 64
        if rejected:
            _retarget_provenance(
                evaluation,
                role=("POSITION_FACT" if "mark_iv" in field else "INDEX"),
                old_identity=old_identity,
                new_identity="sha256:" + "f" * 64,
            )
    elif field == "entry_index_usdc_per_btc":
        evaluation["payload"][field] = "99999"
    else:
        evaluation["payload"][field] = "0.4"
    _rewrite_object(evaluation_path, evaluation)

    with pytest.raises(DownstreamEvidenceError, match="entry source graph"):
        read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="entry source graph"):
        read_complete_evidence(directory, bindings=bindings)


@pytest.mark.parametrize(
    "field",
    (
        "prior_evaluation_index_usdc_per_btc",
        "prior_evaluation_index_source_identity",
        "prior_evaluation_index_fact_boundary",
    ),
)
def test_current_and_complete_readers_bind_position_prior_index_chain(
    mature_unknown_complete_directory: tuple[Path, RuntimeBindings, str],
    field: str,
) -> None:
    directory, bindings, outcome_kind = mature_unknown_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    evaluation_kind = (
        "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION"
        if outcome_kind.startswith("REJECTED_")
        else "POSITION_EVALUATION"
    )
    evaluations = sorted(
        (value for value in objects.values() if value["object_kind"] == evaluation_kind),
        key=lambda value: cast(Mapping[str, int], value["fact_boundary"])["causal_seq"],
    )
    assert len(evaluations) == 2
    later = evaluations[1]
    later_path = (
        directory
        / "objects"
        / evaluation_kind
        / f"{cast(str, later['object_identity']).removeprefix('sha256:')}.json"
    )
    tampered = json.loads(later_path.read_text())
    if field.endswith("_fact_boundary"):
        old_identity = tampered["payload"]["prior_evaluation_index_source_identity"]
        new_boundary = _mature_known_boundary(3, 130).as_object()
        tampered["payload"][field] = new_boundary
        if outcome_kind.startswith("REJECTED_"):
            _retarget_provenance(
                tampered,
                role="INDEX",
                old_identity=old_identity,
                new_boundary=new_boundary,
            )
    elif field.endswith("_source_identity"):
        old_identity = tampered["payload"][field]
        tampered["payload"][field] = "sha256:" + "f" * 64
        if outcome_kind.startswith("REJECTED_"):
            _retarget_provenance(
                tampered,
                role="INDEX",
                old_identity=old_identity,
                new_identity="sha256:" + "f" * 64,
            )
    else:
        tampered["payload"][field] = "99999"
    _rewrite_object(later_path, tampered)

    with pytest.raises(DownstreamEvidenceError, match="prior index anchor"):
        read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="prior index anchor"):
        read_complete_evidence(directory, bindings=bindings)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("primary_close_reason", "PLATFORM_OR_SOURCE_DISCONTINUITY"),
        ("secondary_close_reasons", ["PLATFORM_OR_SOURCE_DISCONTINUITY"]),
    ),
)
def test_current_and_complete_readers_rederive_position_close_reasons(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
    field: str,
    value: object,
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    action_path = _object_file(directory, objects, "POSITION_ACTION")
    action = json.loads(action_path.read_text())
    action["payload"][field] = value
    _rewrite_object(action_path, action)

    with pytest.raises(DownstreamEvidenceError, match="latched close reasons"):
        read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="latched close reasons"):
        read_complete_evidence(directory, bindings=bindings)


def test_current_and_complete_readers_bind_both_position_action_latches(
    mature_unknown_complete_directory: tuple[Path, RuntimeBindings, str],
) -> None:
    directory, bindings, outcome_kind = mature_unknown_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    action_kind = (
        "REJECTED_COUNTERFACTUAL_POSITION_ACTION"
        if outcome_kind.startswith("REJECTED_")
        else "POSITION_ACTION"
    )
    action_value = next(
        value
        for value in objects.values()
        if value["object_kind"] == action_kind
        and cast(Mapping[str, object], value["payload"])["ordered_latched_close_reason_vector"]
    )
    action_path = (
        directory
        / "objects"
        / action_kind
        / f"{cast(str, action_value['object_identity']).removeprefix('sha256:')}.json"
    )
    action = json.loads(action_path.read_text())
    action["payload"]["first_latched_close_action_identity"] = None
    _rewrite_object(action_path, action)

    with pytest.raises(DownstreamEvidenceError, match="latched close reasons"):
        read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="latched close reasons"):
        read_complete_evidence(directory, bindings=bindings)


def test_current_and_complete_readers_bind_earliest_position_action_latch(
    mature_unknown_complete_directory: tuple[Path, RuntimeBindings, str],
) -> None:
    directory, bindings, outcome_kind = mature_unknown_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    action_kind = (
        "REJECTED_COUNTERFACTUAL_POSITION_ACTION"
        if outcome_kind.startswith("REJECTED_")
        else "POSITION_ACTION"
    )
    actions = sorted(
        (value for value in objects.values() if value["object_kind"] == action_kind),
        key=lambda value: cast(Mapping[str, int], value["fact_boundary"])["causal_seq"],
    )
    assert len(actions) == 2
    first_identity = cast(str, actions[0]["object_identity"])
    later_identity = cast(str, actions[1]["object_identity"])
    later_path = (
        directory / "objects" / action_kind / f"{later_identity.removeprefix('sha256:')}.json"
    )
    later = json.loads(later_path.read_text())
    assert later["payload"]["first_latched_close_action_identity"] == first_identity
    later["payload"]["first_latched_close_action_identity"] = later_identity
    _rewrite_object(later_path, later)

    with pytest.raises(DownstreamEvidenceError, match="causal latch history"):
        read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="causal latch history"):
        read_complete_evidence(directory, bindings=bindings)


def test_current_and_complete_readers_rederive_permanent_position_latch_history(
    mature_unknown_complete_directory: tuple[Path, RuntimeBindings, str],
) -> None:
    directory, bindings, outcome_kind = mature_unknown_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    rejected = outcome_kind.startswith("REJECTED_")
    action_kind = "REJECTED_COUNTERFACTUAL_POSITION_ACTION" if rejected else "POSITION_ACTION"
    actions = sorted(
        (value for value in objects.values() if value["object_kind"] == action_kind),
        key=lambda value: cast(Mapping[str, int], value["fact_boundary"])["causal_seq"],
    )
    assert len(actions) == 2
    payloads = [cast(Mapping[str, object], value["payload"]) for value in actions]
    invented_reason = next(
        reason
        for index, reason in enumerate(POSITION_CLOSE_REASONS)
        if all(
            cast(list[str], payload["ordered_predicate_truth_vector"])[index] != "TRUE"
            for payload in payloads
        )
        and reason not in cast(list[str], payloads[-1]["ordered_latched_close_reason_vector"])
    )
    later_identity = cast(str, actions[-1]["object_identity"])
    later_path = (
        directory / "objects" / action_kind / f"{later_identity.removeprefix('sha256:')}.json"
    )
    later = json.loads(later_path.read_text())
    latched = set(later["payload"]["ordered_latched_close_reason_vector"])
    latched.add(invented_reason)
    ordered_latched = [reason for reason in POSITION_CLOSE_REASONS if reason in latched]
    later["payload"]["ordered_latched_close_reason_vector"] = ordered_latched
    if not rejected:
        later["payload"]["primary_close_reason"] = ordered_latched[0]
        later["payload"]["secondary_close_reasons"] = ordered_latched[1:]
    evaluation_field = (
        "rejected_position_evaluation_identity" if rejected else "position_evaluation_identity"
    )
    identity_field = "rejected_position_action_identity" if rejected else "position_action_identity"
    new_identity = canonical_identity(
        "RejectedCounterfactualPositionActionIdentity" if rejected else "PositionActionIdentity",
        later["payload"][evaluation_field],
        later["payload"]["serialized_action"],
        later["payload"]["ordered_predicate_truth_vector"],
        ordered_latched,
    )
    later["object_identity"] = new_identity
    later["payload"][identity_field] = new_identity
    new_path = later_path.with_name(f"{new_identity.removeprefix('sha256:')}.json")
    later_path.unlink()
    _rewrite_object(new_path, later)

    with pytest.raises(DownstreamEvidenceError, match="causal latch history"):
        read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="causal latch history"):
        read_complete_evidence(directory, bindings=bindings)


def test_admitted_position_current_index_source_is_bound_to_exact_provenance(
    tmp_path: Path,
) -> None:
    directory = tmp_path
    owner, bindings = _mature_known_owner(directory)
    anchor_identity = _admit_mature_known_owner(owner)
    close_boundary = _mature_known_boundary(4, 140)
    failure_boundary = _mature_known_boundary(5, 150)
    owner.settle_position(
        anchor_identity=anchor_identity,
        facts=_mature_known_position_facts(
            boundary=close_boundary,
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    owner.note_request_failure(request_id=42, boundary=failure_boundary)
    owner.settle_position(
        anchor_identity=anchor_identity,
        facts=_mature_unknown_position_facts(boundary=failure_boundary),
        allocate_request_id=lambda: 43,
    )
    manifest, final_trigger = _manifest_for_mature_known_owner(directory)
    terminal_boundary = _mature_known_boundary(101, 300)
    owner.terminate(
        boundary=terminal_boundary,
        terminal_source_identity=canonical_identity(
            "PreboundSupervisorTriggerIdentity",
            final_trigger,
        ),
        terminal_source=TerminalSource.STOP,
    )
    owner.finalize_terminal(
        manifest=manifest,
        terminal_disposition="PLANNED_CLEAN_STOP",
        terminal_source=final_trigger,
    )
    (directory / "manifest.json").write_bytes(manifest.exact_bytes)
    objects = read_current_evidence(directory, bindings=bindings)
    evaluations = sorted(
        (value for value in objects.values() if value["object_kind"] == "POSITION_EVALUATION"),
        key=lambda value: cast(Mapping[str, int], value["fact_boundary"])["causal_seq"],
    )
    assert len(evaluations) == 2
    first_path = (
        directory
        / "objects"
        / "POSITION_EVALUATION"
        / f"{cast(str, evaluations[0]['object_identity']).removeprefix('sha256:')}.json"
    )
    later_path = (
        directory
        / "objects"
        / "POSITION_EVALUATION"
        / f"{cast(str, evaluations[1]['object_identity']).removeprefix('sha256:')}.json"
    )
    first = json.loads(first_path.read_text())
    later = json.loads(later_path.read_text())
    forged_identity = "sha256:" + "f" * 64
    first["payload"]["current_index_source_identity"] = forged_identity
    later["payload"]["prior_evaluation_index_source_identity"] = forged_identity
    _rewrite_object(first_path, first)
    _rewrite_object(later_path, later)

    with pytest.raises(DownstreamEvidenceError, match="exact one-hop provenance"):
        read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="exact one-hop provenance"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_requires_atomic_opportunity_exit_outcome_boundary(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    selected_exit_path = _object_file(
        directory,
        objects,
        "SHADOW_COUNTERFACTUAL_EXIT",
    )
    selected_exit = json.loads(selected_exit_path.read_text())
    old_boundary = FactBoundary.from_object(selected_exit["fact_boundary"])
    moved_boundary = FactBoundary(
        code_identity=old_boundary.code_identity,
        runtime_identity=old_boundary.runtime_identity,
        session_epoch=old_boundary.session_epoch,
        ingress_seq=old_boundary.ingress_seq + 1,
        received_monotonic_ms=old_boundary.received_monotonic_ms + 1,
        causal_seq=old_boundary.causal_seq + 1,
    )
    selected_exit["fact_boundary"] = moved_boundary.as_object()
    selected_exit["payload"]["selection_fact_boundary"] = moved_boundary.as_object()
    _rewrite_object(selected_exit_path, selected_exit)

    outcome = next(value for value in objects.values() if value["object_kind"] == "SHADOW_OUTCOME")
    old_outcome_path = _object_file(directory, objects, "SHADOW_OUTCOME")
    moved_outcome = json.loads(old_outcome_path.read_text())
    moved_outcome_identity = canonical_identity(
        "ShadowOutcomeIdentity",
        moved_outcome["payload"]["shadow_observation_identity"],
        "MATURE_KNOWN",
        moved_boundary.as_object(),
    )
    moved_outcome["object_identity"] = moved_outcome_identity
    moved_outcome["fact_boundary"] = moved_boundary.as_object()
    moved_outcome["payload"]["shadow_outcome_identity"] = moved_outcome_identity
    moved_outcome["payload"]["terminal_fact_boundary"] = moved_boundary.as_object()
    for root in moved_outcome["source_provenance"]:
        if root["source_role"] == "SELECTED_EXIT":
            root["receipt_fact_boundary"] = moved_boundary.as_object()
    old_outcome_path.unlink()
    new_outcome_path = (
        directory
        / "objects"
        / "SHADOW_OUTCOME"
        / f"{moved_outcome_identity.removeprefix('sha256:')}.json"
    )
    _rewrite_object(new_outcome_path, moved_outcome)

    pair_path = _object_file(directory, objects, "ALIGNED_POLICY_NO_TRADE_PAIR")
    pair = json.loads(pair_path.read_text())
    pair["fact_boundary"] = moved_boundary.as_object()
    pair["payload"]["trade_outcome_identity"] = moved_outcome_identity
    pair["payload"]["terminal_fact_boundary"] = moved_boundary.as_object()
    for root in pair["source_provenance"]:
        if root["source_role"] == "TERMINAL_OUTCOME":
            root["source_identity"] = moved_outcome_identity
            root["receipt_fact_boundary"] = moved_boundary.as_object()
    _rewrite_object(pair_path, pair)

    assert outcome["object_identity"] != moved_outcome_identity
    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match=r"boundary|atomic"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_binds_mature_unknown_witnesses_to_anchor_legs(
    mature_unknown_complete_directory: tuple[Path, RuntimeBindings, str],
) -> None:
    directory, bindings, outcome_kind = mature_unknown_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    outcome_path = _object_file(directory, objects, outcome_kind)
    outcome = json.loads(outcome_path.read_text())
    outcome["payload"]["natural_terminal_lifecycle_witnesses"][0]["instrument_identity"] = (
        "sha256:" + "f" * 64
    )
    _rewrite_object(outcome_path, outcome)

    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match=r"lifecycle.*leg|leg.*lifecycle"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_rejects_mature_unknown_lifecycle_witness_at_entry(
    mature_unknown_complete_directory: tuple[Path, RuntimeBindings, str],
) -> None:
    directory, bindings, outcome_kind = mature_unknown_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    outcome_path = _object_file(directory, objects, outcome_kind)
    outcome = json.loads(outcome_path.read_text())
    rejected = outcome_kind.startswith("REJECTED_")
    anchor_kind = "REJECTED_COUNTERFACTUAL_ANCHOR" if rejected else "SHADOW_ENTRY"
    anchor_field = "rejected_anchor_identity" if rejected else "shadow_entry_identity"
    anchor_identity = outcome["payload"][anchor_field]
    anchor = next(
        value
        for value in objects.values()
        if value["object_kind"] == anchor_kind and value["object_identity"] == anchor_identity
    )
    entry_boundary = json.loads(json.dumps(anchor["fact_boundary"]))
    witness = outcome["payload"]["natural_terminal_lifecycle_witnesses"][0]
    witness["witness_fact_boundary"] = entry_boundary
    matching_roots = [
        root
        for root in outcome["source_provenance"]
        if root["source_role"] == "INSTRUMENT_LIFECYCLE"
        and root["source_identity"] == witness["source_identity"]
    ]
    assert len(matching_roots) == 1
    matching_roots[0]["receipt_fact_boundary"] = json.loads(json.dumps(entry_boundary))
    _rewrite_object(outcome_path, outcome)

    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="lifecycle witness must be strictly after"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_recomputes_enrollment_from_realized_causal_boundaries(
    mature_known_complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = mature_known_complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    for object_kind in (
        "SHADOW_OUTCOME_OBSERVATION",
        "ALIGNED_POLICY_NO_TRADE_PAIR",
    ):
        path = _object_file(directory, objects, object_kind)
        value = json.loads(path.read_text())
        value["payload"]["cohort_enrolled"] = False
        _rewrite_object(path, value)

    changed = read_current_evidence(directory, bindings=bindings)
    cohort_path = _object_file(
        directory,
        changed,
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
    )
    cohort = json.loads(cohort_path.read_text())
    counts = derive_cohort_counts(tuple(changed.values()))
    cohort["payload"]["counts"] = counts
    cohort["payload"]["rates"] = compute_cohort_rates(counts, evidence_status="COMPLETE")
    _rewrite_object(cohort_path, cohort)

    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match="enrollment"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_rejects_cutoff_not_causally_before_terminal(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    cohort_path = _object_file(
        directory,
        objects,
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
    )
    cohort = json.loads(cohort_path.read_text())
    terminal_boundary = cohort["payload"]["terminal_fact_boundary"]
    cohort["payload"]["enrollment_end_fact_boundary"] = terminal_boundary
    manifest = load_manifest_bytes((directory / "manifest.json").read_bytes())
    cutoff = cast(Mapping[str, object], manifest.value["enrollment_cutoff_trigger"])
    cutoff_identity = canonical_identity("PreboundSupervisorTriggerIdentity", cutoff)
    for root in cohort["source_provenance"]:
        if root["source_identity"] == cutoff_identity:
            root["receipt_fact_boundary"] = terminal_boundary
    _rewrite_object(cohort_path, cohort)

    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match=r"cutoff|enrollment end"):
        read_complete_evidence(directory, bindings=bindings)


def test_complete_reader_rejects_runtime_start_not_causally_before_cutoff(
    complete_directory: tuple[Path, RuntimeBindings],
) -> None:
    directory, bindings = complete_directory
    objects = read_current_evidence(directory, bindings=bindings)
    cohort_path = _object_file(
        directory,
        objects,
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
    )
    cohort = json.loads(cohort_path.read_text())
    cutoff_boundary = cohort["payload"]["enrollment_end_fact_boundary"]
    cohort["payload"]["runtime_start_fact_boundary"] = cutoff_boundary
    manifest = load_manifest_bytes((directory / "manifest.json").read_bytes())
    runtime_start = cast(Mapping[str, object], manifest.value["runtime_start_trigger"])
    runtime_start_identity = canonical_identity(
        "PreboundSupervisorTriggerIdentity",
        runtime_start,
    )
    for root in cohort["source_provenance"]:
        if root["source_identity"] in {
            manifest.manifest_identity,
            runtime_start_identity,
        }:
            root["receipt_fact_boundary"] = cutoff_boundary
    _rewrite_object(cohort_path, cohort)

    assert read_current_evidence(directory, bindings=bindings)
    with pytest.raises(DownstreamEvidenceError, match=r"cutoff|runtime start"):
        read_complete_evidence(directory, bindings=bindings)
