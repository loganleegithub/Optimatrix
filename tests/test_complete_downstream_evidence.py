from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest
from short_vol_underwriting import (
    UNDERWRITING_COUNT_KEYS,
    DownstreamEvidenceError,
    DownstreamEvidenceWriter,
    FactBoundary,
    FixedContractShadowOwner,
    RuntimeBindings,
    TerminalSource,
    canonical_identity,
    compute_underwriting_rates,
    load_manifest_bytes,
    load_policy_chain,
    read_complete_evidence,
    read_current_evidence,
)
from test_short_vol_underwriting import (
    _admit_owner as _admit_mature_known_owner,
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


def _boundary(causal_seq: int, monotonic_ms: int) -> FactBoundary:
    return FactBoundary(
        code_identity="a" * 40,
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


@pytest.fixture
def complete_directory(tmp_path: Path) -> tuple[Path, RuntimeBindings]:
    bindings = RuntimeBindings(
        code_identity="a" * 40,
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
            boundary=_boundary(4, 140),
            change_id=12,
            previous_change_id=11,
        ),
        allocate_request_id=lambda: 42,
    )
    owner.settle_position(
        anchor_identity=entry_identity,
        facts=_mature_known_position_facts(
            boundary=_boundary(5, 150),
            change_id=13,
            previous_change_id=12,
        ),
        allocate_request_id=lambda: 43,
    )
    manifest, final_trigger = _manifest_for_mature_known_owner(tmp_path)
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
    (tmp_path / "manifest.json").write_bytes(manifest.exact_bytes)
    complete = read_complete_evidence(tmp_path, bindings=bindings)
    assert len(complete) == 20
    assert any(
        value["object_kind"] == "SHADOW_OUTCOME"
        and cast(Mapping[str, object], value["payload"])["terminal_state"] == "MATURE_KNOWN"
        for value in complete.values()
    )
    return tmp_path, bindings


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
