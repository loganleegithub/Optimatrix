from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from market_tape import CanonicalEvent, EventKind, canonical_digest, write_capture
from radar_runtime.deribit_public import (
    CAPTURE_RECEIPT_TYPE,
    LIVE_CAPTURE_EVIDENCE,
    WEBSOCKET_URL,
    _event_summary,
    build_decision_receipt,
    decision_receipt_payload,
    inspect_payload,
    project_events,
    projection_payload,
)
from radar_runtime.outcome_bundle import (
    create_outcome_evidence_bundle,
    verify_outcome_evidence_bundle,
)
from radar_runtime.outcome_identity import outcome_runtime_source_identity
from radar_runtime.outcome_runtime import (
    PUBLIC_EVIDENCE_CLASS,
    PUBLIC_INVOCATION_RECEIPT_TYPE,
    _compose,
    _persist_composition,
    build_synthetic_outcome_events,
    reconstruct_outcome,
    replay_outcome,
    run_public_outcome_capture,
    run_synthetic_outcome,
)
from radar_runtime.outcome_seal import decision_cutoff, read_sealed_capture, seal_capture
from radar_runtime.runtime_identity import runtime_source_identity


def _object(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _payload(event: CanonicalEvent) -> dict[str, object]:
    value: object = json.loads(event.raw_payload)
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _without_candidate(
    events: tuple[CanonicalEvent, ...],
) -> tuple[CanonicalEvent, ...]:
    cutoff = decision_cutoff(events)
    changed: list[CanonicalEvent] = []
    for event in events:
        if (
            event.capture_seq <= cutoff.capture_seq
            and event.event_kind is EventKind.TICKER
            and event.instrument_name is not None
            and event.instrument_name != "BTC_USDC-PERPETUAL"
        ):
            payload = _payload(event)
            payload["best_bid_price"] = "1"
            payload["best_ask_price"] = "2"
            event = replace(
                event,
                raw_payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            )
        changed.append(event)
    return tuple(changed)


def _without_schedule(
    events: tuple[CanonicalEvent, ...],
) -> tuple[CanonicalEvent, ...]:
    return tuple(
        replace(
            event,
            event_kind=EventKind.HEARTBEAT,
            channel="heartbeat",
            raw_payload="{}",
        )
        if event.event_kind is EventKind.SCHEDULED_BLOCK_STATE
        else event
        for event in events
    )


def _write_composed_run(
    output: Path,
    events: tuple[CanonicalEvent, ...],
    *,
    provenance: str,
    duration_seconds: int,
) -> dict[str, object]:
    output.mkdir()
    full = output / "_full-capture" / "capture"
    write_capture(full, events, complete=True)
    seal_capture(full, output / "facts")
    decision_identity = runtime_source_identity(require_clean=False)
    outcome_identity = outcome_runtime_source_identity(require_clean=False)
    composition = _compose(
        output / "facts",
        fact_provenance=provenance,
        evidence_class=(
            PUBLIC_EVIDENCE_CLASS if provenance == "production_public" else "SYNTHETIC_LOGIC"
        ),
        duration_seconds=duration_seconds,
        decision_identity=decision_identity,
        outcome_identity=outcome_identity,
        evidence_git_commit_sha=outcome_identity.git_commit_sha,
    )
    _persist_composition(output, composition)
    shutil.rmtree(output / "_full-capture")
    return composition.result


def _rewrite_result(path: Path, updates: dict[str, object]) -> None:
    payload = _object(path)
    payload.update(updates)
    payload.pop("result_digest", None)
    payload["result_digest"] = canonical_digest(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _public_zero_events() -> tuple[CanonicalEvent, ...]:
    events = _without_candidate(build_synthetic_outcome_events())
    cutoff = decision_cutoff(events)
    suffix_elapsed = (
        cutoff.target_elapsed_ms + 1,
        cutoff.target_elapsed_ms + 2,
        cutoff.target_elapsed_ms + 30_000,
        cutoff.target_elapsed_ms + 30_001,
        cutoff.target_elapsed_ms + 30_002,
        cutoff.target_elapsed_ms + 65_000,
    )
    return tuple(
        replace(event, collector_elapsed_ms=suffix_elapsed[event.capture_seq - 145])
        if event.capture_seq > cutoff.capture_seq
        else event
        for event in events
    )


def _write_mock_public_collector_artifacts(
    run: Path,
    result: dict[str, object],
) -> None:
    _seal, manifest, events, _prefix_manifest, _prefix_events = read_sealed_capture(run / "facts")
    identity = runtime_source_identity(require_clean=False)
    projection = project_events(events)
    git_commit_sha = result["git_commit_sha"]
    assert isinstance(git_commit_sha, str)
    decision = build_decision_receipt(
        manifest,
        projection,
        source_identity=identity,
        receipt_git_commit_sha=git_commit_sha,
    )
    decision_payload = decision_receipt_payload(decision)
    live = {
        "receipt_type": CAPTURE_RECEIPT_TYPE,
        "environment": "production_public",
        "duration_seconds": 3_665,
        **_event_summary(manifest, events),
        **projection_payload(projection),
        "decision_receipt_digest": decision.digest,
        "git_commit_sha": git_commit_sha,
        "runtime_source_id": identity.runtime_source_id,
        "runtime_source_digest": identity.runtime_source_digest,
        "evidence_class": LIVE_CAPTURE_EVIDENCE,
    }
    inspected = inspect_payload(manifest, events, source_identity=identity)
    for name, payload in (
        ("collector-live.json", live),
        ("collector-decision.json", decision_payload),
        ("collector-inspect.json", inspected),
    ):
        (run / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    invocation = {
        "receipt_type": PUBLIC_INVOCATION_RECEIPT_TYPE,
        "environment": "production_public",
        "transport_endpoint": WEBSOCKET_URL,
        "requested_duration_seconds": 3_665,
        "invocation_started_at": "2026-07-20T00:00:00+00:00",
        "invocation_finished_at": "2026-07-20T01:01:05+00:00",
        "invocation_elapsed_ms": 3_665_000,
        "records": manifest.record_count,
        "capture_digest": manifest.content_sha256,
        "capture_manifest_digest": manifest.digest,
        "collector_live_sha256": hashlib.sha256(
            (run / "collector-live.json").read_bytes()
        ).hexdigest(),
        "collector_decision_sha256": hashlib.sha256(
            (run / "collector-decision.json").read_bytes()
        ).hexdigest(),
        "collector_inspect_sha256": hashlib.sha256(
            (run / "collector-inspect.json").read_bytes()
        ).hexdigest(),
        "git_commit_sha": git_commit_sha,
        "runtime_source_id": identity.runtime_source_id,
        "runtime_source_digest": identity.runtime_source_digest,
    }
    invocation["invocation_digest"] = canonical_digest(invocation)
    (run / "collector-invocation.json").write_text(
        json.dumps(invocation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_cutoff_is_fixed_to_initial_subscriptions_and_does_not_retry() -> None:
    events = build_synthetic_outcome_events()
    expected = decision_cutoff(events)
    assert expected.capture_seq == 144
    assert expected.required_subscription_capture_seqs == (1, 2, 4)

    reconnect = replace(events[20], event_kind=EventKind.RECONNECT, raw_payload="{}")
    reconnected = (*events[:20], reconnect, *events[21:])
    assert decision_cutoff(reconnected) == expected

    early_reconnect = replace(events[2], event_kind=EventKind.RECONNECT, raw_payload="{}")
    incomplete_initial = (*events[:2], early_reconnect, *events[3:])
    with pytest.raises(ValueError, match="initial connection ended"):
        decision_cutoff(incomplete_initial)


def test_seal_reconstructs_exact_bytes_and_rejects_suffix_tamper(tmp_path: Path) -> None:
    events = build_synthetic_outcome_events()
    full = tmp_path / "full"
    write_capture(full, events, complete=True)
    seal = seal_capture(full, tmp_path / "facts")

    reconstructed, manifest, replayed, prefix_manifest, prefix = read_sealed_capture(
        tmp_path / "facts"
    )
    assert reconstructed == seal
    assert replayed == events
    assert manifest.content_sha256 == seal.combined_capture_sha256
    assert prefix_manifest.record_count == seal.cutoff.capture_seq == len(prefix)

    suffix = tmp_path / "facts/future-suffix.jsonl"
    suffix.write_bytes(suffix.read_bytes() + b" ")
    with pytest.raises(ValueError, match="suffix digest changed"):
        read_sealed_capture(tmp_path / "facts")


def test_synthetic_run_and_fresh_process_replay_are_exact(tmp_path: Path) -> None:
    run = tmp_path / "synthetic"
    result = run_synthetic_outcome(run)

    assert result["decision_cutoff_capture_seq"] == 144
    assert result["decision_action"] == "RESEARCH_CANDIDATE"
    assert result["admission_status"] == "ADMITTED"
    assert result["entry_count"] == result["outcome_count"] == 1
    assert result["outcome_status"] == "CLOSED"
    assert result["counterfactual_point_count"] == 1
    assert result["decision_runtime_source_digest"] == (
        "eed711f1c924c73a0a61b562da5154873b40713f5b5e44c482882eecf7aee29c"
    )
    assert not (run / "_full-capture").exists()
    outcome = _object(run / "outcome.json")
    sources = outcome["outcome_source_capture_seqs"]
    assert isinstance(sources, list)
    assert all(isinstance(item, int) and item > 144 for item in sources)

    replay = tmp_path / "fresh-replay"
    completed = subprocess.run(
        (
            sys.executable,
            "-c",
            "from radar_runtime.outcome_cli import main; raise SystemExit(main())",
            "replay",
            str(run),
            "--output",
            str(replay),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    replayed: object = json.loads(completed.stdout)
    assert isinstance(replayed, dict)
    assert replayed["replay_verified"] is True
    assert replayed["decision_drift_count"] == 0
    assert replayed["entry_drift_count"] == 0
    assert replayed["outcome_drift_count"] == 0
    assert replayed["strict_future_violation_count"] == 0


def test_transient_executable_option_tick_is_the_first_causal_exit(tmp_path: Path) -> None:
    base = build_synthetic_outcome_events()
    prefix = base[:146]
    short_tick, long_tick, reference_tick, counterfactual = base[146:]
    reference_first = replace(reference_tick, capture_seq=147)
    short_after_reference = replace(short_tick, capture_seq=148)
    long_after_reference = replace(long_tick, capture_seq=149)
    deteriorated_payload = _payload(short_tick)
    deteriorated_at_ms = short_tick.collector_received_at_ms + 1
    deteriorated_payload["timestamp"] = deteriorated_at_ms
    deteriorated_payload["best_ask_price"] = "800"
    deteriorated = replace(
        short_tick,
        capture_seq=150,
        collector_received_at_ms=deteriorated_at_ms,
        collector_elapsed_ms=short_tick.collector_elapsed_ms + 1,
        exchange_timestamp_ms=deteriorated_at_ms,
        raw_payload=json.dumps(
            deteriorated_payload,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    later_counterfactual = replace(counterfactual, capture_seq=151)
    events = (
        *prefix,
        reference_first,
        short_after_reference,
        long_after_reference,
        deteriorated,
        later_counterfactual,
    )

    run = tmp_path / "transient"
    result = _write_composed_run(
        run,
        events,
        provenance="synthetic",
        duration_seconds=7_200,
    )
    outcome = _object(run / "outcome.json")
    observed = outcome["observed_outcome"]
    assert isinstance(observed, dict)

    assert result["outcome_status"] == "CLOSED"
    assert observed["exit_capture_seq"] == 149
    assert observed["exit_reason"] == "PROFIT_TARGET"
    assert result["counterfactual_point_count"] == 2


def test_replay_rejects_runtime_source_and_receipt_tamper(tmp_path: Path) -> None:
    original = tmp_path / "original"
    run_synthetic_outcome(original)

    source_tamper = tmp_path / "source-tamper"
    shutil.copytree(original, source_tamper)
    _rewrite_result(
        source_tamper / "result.json",
        {"outcome_runtime_source_digest": "0" * 64},
    )
    with pytest.raises(ValueError, match="runtime source identity mismatch"):
        reconstruct_outcome(source_tamper)

    receipt_tamper = tmp_path / "receipt-tamper"
    shutil.copytree(original, receipt_tamper)
    entry = _object(receipt_tamper / "shadow-entry.json")
    entry["frame_digest"] = "0" * 64
    (receipt_tamper / "shadow-entry.json").write_text(
        json.dumps(entry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"entry\.frame_digest"):
        reconstruct_outcome(receipt_tamper)

    decision_tamper = tmp_path / "decision-tamper"
    shutil.copytree(original, decision_tamper)
    decision = _object(decision_tamper / "decision.json")
    decision["frame_digest"] = "0" * 64
    (decision_tamper / "decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"decision\.frame_digest"):
        reconstruct_outcome(decision_tamper)

    outcome_tamper = tmp_path / "outcome-tamper"
    shutil.copytree(original, outcome_tamper)
    outcome = _object(outcome_tamper / "outcome.json")
    outcome["receipt_digest"] = "0" * 64
    (outcome_tamper / "outcome.json").write_text(
        json.dumps(outcome, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"outcome\.receipt_digest"):
        reconstruct_outcome(outcome_tamper)

    metadata_tamper = tmp_path / "metadata-tamper"
    shutil.copytree(original, metadata_tamper)
    _rewrite_result(
        metadata_tamper / "result.json",
        {"evidence_class": "UNBOUND", "duration_seconds": 1},
    )
    with pytest.raises(ValueError, match="replay metadata changed"):
        reconstruct_outcome(metadata_tamper)


def test_complete_zero_and_incomplete_unknown_emit_no_false_receipts(tmp_path: Path) -> None:
    base = build_synthetic_outcome_events()
    no_entry = _write_composed_run(
        tmp_path / "no-entry",
        _without_candidate(base),
        provenance="production_public",
        duration_seconds=3_665,
    )
    assert no_entry["decision_frame_complete"] is True
    assert no_entry["decision_action"] == "ABSTAIN"
    assert no_entry["admission_status"] == "NO_ENTRY"
    assert no_entry["entry_count"] == no_entry["outcome_count"] == 0
    assert no_entry["entry_receipt_digest"] is None
    assert no_entry["outcome_receipt_digest"] is None
    assert not (tmp_path / "no-entry/shadow-entry.json").exists()
    assert not (tmp_path / "no-entry/outcome.json").exists()

    unknown = _write_composed_run(
        tmp_path / "unknown",
        _without_schedule(base),
        provenance="production_public",
        duration_seconds=3_665,
    )
    assert unknown["decision_frame_complete"] is False
    assert unknown["admission_status"] == "UNKNOWN"
    assert unknown["entry_count"] == unknown["outcome_count"] == 0
    assert unknown["unknown_reasons"]
    assert not (tmp_path / "unknown/shadow-entry.json").exists()
    assert not (tmp_path / "unknown/outcome.json").exists()


def test_bundle_reconstructs_both_cases_and_rejects_tamper(tmp_path: Path) -> None:
    synthetic = tmp_path / "synthetic"
    synthetic_replay = tmp_path / "synthetic-replay"
    run_synthetic_outcome(synthetic)
    replay_outcome(synthetic, synthetic_replay)

    public = tmp_path / "public"
    public_replay = tmp_path / "public-replay"
    public_result = _write_composed_run(
        public,
        _public_zero_events(),
        provenance="production_public",
        duration_seconds=3_665,
    )
    assert public_result["admission_status"] == "NO_ENTRY"
    replay_outcome(public, public_replay)
    with pytest.raises(ValueError, match="missing bounded collector artifacts"):
        create_outcome_evidence_bundle(
            synthetic_run=synthetic,
            synthetic_replay=synthetic_replay,
            public_run=public,
            public_replay=public_replay,
            output=tmp_path / "unbound-bundle",
        )
    _write_mock_public_collector_artifacts(public, public_result)

    collector_tamper = tmp_path / "collector-tamper"
    shutil.copytree(public, collector_tamper)
    decision = _object(collector_tamper / "collector-decision.json")
    evaluation = decision["evaluation"]
    assert isinstance(evaluation, dict)
    decision_summary = evaluation["decision"]
    assert isinstance(decision_summary, dict)
    decision_summary["reason"] = "TAMPERED_BUT_REHASHED"
    decision.pop("receipt_digest")
    tampered_digest = canonical_digest(decision)
    decision["receipt_digest"] = tampered_digest
    live = _object(collector_tamper / "collector-live.json")
    live["decision_receipt_digest"] = tampered_digest
    inspected = _object(collector_tamper / "collector-inspect.json")
    inspected["decision_receipt_digest"] = tampered_digest
    for name, payload in (
        ("collector-decision.json", decision),
        ("collector-live.json", live),
        ("collector-inspect.json", inspected),
    ):
        (collector_tamper / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    invocation = _object(collector_tamper / "collector-invocation.json")
    invocation["collector_live_sha256"] = hashlib.sha256(
        (collector_tamper / "collector-live.json").read_bytes()
    ).hexdigest()
    invocation["collector_decision_sha256"] = hashlib.sha256(
        (collector_tamper / "collector-decision.json").read_bytes()
    ).hexdigest()
    invocation["collector_inspect_sha256"] = hashlib.sha256(
        (collector_tamper / "collector-inspect.json").read_bytes()
    ).hexdigest()
    invocation.pop("invocation_digest")
    invocation["invocation_digest"] = canonical_digest(invocation)
    (collector_tamper / "collector-invocation.json").write_text(
        json.dumps(invocation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Decision receipt is not reconstructed"):
        create_outcome_evidence_bundle(
            synthetic_run=synthetic,
            synthetic_replay=synthetic_replay,
            public_run=collector_tamper,
            public_replay=public_replay,
            output=tmp_path / "collector-tamper-bundle",
        )

    bundle = tmp_path / "bundle"
    created = create_outcome_evidence_bundle(
        synthetic_run=synthetic,
        synthetic_replay=synthetic_replay,
        public_run=public,
        public_replay=public_replay,
        output=bundle,
    )
    archive = Path(str(bundle.with_suffix(".tar.gz")))
    assert created["bundle_verified"] is True
    assert verify_outcome_evidence_bundle(bundle, archive=archive)["bundle_verified"] is True

    duplicate_archive = tmp_path / "duplicate.tar.gz"
    members: list[tuple[str, bytes]] = []
    with tarfile.open(archive, mode="r:gz") as source:
        for member in source.getmembers():
            handle = source.extractfile(member)
            assert handle is not None
            members.append((member.name, handle.read()))
    with tarfile.open(duplicate_archive, mode="w:gz") as target:
        for name, data in (*members, members[0]):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            target.addfile(info, io.BytesIO(data))
    with pytest.raises(ValueError, match="unsafe or duplicate"):
        verify_outcome_evidence_bundle(bundle, archive=duplicate_archive)
    report = (bundle / "ACCEPTANCE.zh-CN.md").read_text(encoding="utf-8")
    assert "records / actual public trades" in report
    assert "fresh-process drift" in report
    assert "不证明真实 fill" in report

    result = bundle / "production-public/run/result.json"
    result.write_bytes(result.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_outcome_evidence_bundle(bundle)


def test_public_capture_rejects_non_authorized_duration_before_writing(tmp_path: Path) -> None:
    output = tmp_path / "public"
    with pytest.raises(ValueError, match="exactly 3665"):
        run_public_outcome_capture(output, 60)
    assert not output.exists()
