"""One-shot Decision-to-Outcome composition over a sealed canonical tape."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from market_tape import (
    CanonicalEvent,
    CaptureManifest,
    EventKind,
    MarketTapeReducer,
    PlatformState,
    canonical_digest,
    canonical_value,
    read_capture,
    write_capture,
)
from shadow_engine import (
    OUTCOME_CONTRACT_DIGEST,
    OUTCOME_CONTRACT_ID,
    OutcomeObservation,
    OutcomeReceipt,
    ShadowAdmission,
    ShadowEntryReceipt,
    admit_shadow,
    entry_receipt_payload,
    evaluate_outcome,
    outcome_receipt_payload,
)
from short_vol_radar import RadarProjector

from radar_runtime.deribit_public import (
    WEBSOCKET_URL,
    RadarProjection,
    build_decision_receipt,
    decision_receipt_payload,
    inspect_payload,
    project_events,
    projection_payload,
    run_public_capture,
)
from radar_runtime.fixture import REFERENCE, build_fixture_events
from radar_runtime.outcome_identity import (
    OutcomeRuntimeSourceIdentity,
    outcome_runtime_source_identity,
)
from radar_runtime.outcome_seal import read_sealed_capture, seal_capture
from radar_runtime.runtime_identity import RuntimeSourceIdentity, runtime_source_identity

FACTS_DIRECTORY = "facts"
RESULT_PATH = "result.json"
DECISION_RECEIPT_PATH = "decision.json"
ENTRY_RECEIPT_PATH = "shadow-entry.json"
OUTCOME_RECEIPT_PATH = "outcome.json"
TEMP_CAPTURE_DIRECTORY = "_full-capture"
SYNTHETIC_EVIDENCE_CLASS = "SYNTHETIC_LOGIC"
PUBLIC_EVIDENCE_CLASS = "BOUNDED_PUBLIC_CAPTURE"
REPLAY_EVIDENCE_CLASS = "LIVE_REPLAY"
PUBLIC_CAPTURE_SECONDS = 3_665
PUBLIC_INVOCATION_PATH = "collector-invocation.json"
PUBLIC_INVOCATION_RECEIPT_TYPE = "DERIBIT_PUBLIC_OUTCOME_CAPTURE_INVOCATION"


@dataclass(frozen=True, slots=True)
class _Composition:
    result: dict[str, object]
    decision_receipt: dict[str, object]
    entry_receipt: dict[str, object] | None
    outcome_receipt: dict[str, object] | None


def _json_payload(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(path: Path, label: str) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _write_json(path: Path, payload: object) -> None:
    if path.exists():
        raise ValueError(f"Outcome artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(canonical_value(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _event(
    *,
    capture_seq: int,
    collector_received_at_ms: int,
    collector_elapsed_ms: int,
    exchange_timestamp_ms: int | None,
    event_kind: EventKind,
    channel: str,
    instrument_name: str | None,
    payload: dict[str, object],
) -> CanonicalEvent:
    return CanonicalEvent(
        capture_seq=capture_seq,
        collector_received_at_ms=collector_received_at_ms,
        collector_elapsed_ms=collector_elapsed_ms,
        exchange_timestamp_ms=exchange_timestamp_ms,
        event_kind=event_kind,
        channel=channel,
        instrument_name=instrument_name,
        raw_payload=_json_payload(payload),
    )


def build_synthetic_outcome_events() -> tuple[CanonicalEvent, ...]:
    """Build one Candidate cutoff, executable close, and post-exit counterfactual."""

    fixture = build_fixture_events()
    first_elapsed_ms = fixture[0].collector_elapsed_ms
    subscription_origin_ms = first_elapsed_ms + 60_000
    cutoff_target_ms = subscription_origin_ms + 3_600_000
    prefix: list[CanonicalEvent] = []
    for index, item in enumerate(fixture):
        elapsed_ms = max(item.collector_elapsed_ms, subscription_origin_ms)
        if index == len(fixture) - 1:
            elapsed_ms = cutoff_target_ms
        elif elapsed_ms >= cutoff_target_ms:
            elapsed_ms = cutoff_target_ms - 1
        prefix.append(replace(item, collector_elapsed_ms=elapsed_ms))

    final_wall_ms = prefix[-1].collector_received_at_ms
    future: list[CanonicalEvent] = []
    sequence = prefix[-1].capture_seq

    sequence += 1
    future.append(
        _event(
            capture_seq=sequence,
            collector_received_at_ms=final_wall_ms + 1,
            collector_elapsed_ms=cutoff_target_ms + 1,
            exchange_timestamp_ms=None,
            event_kind=EventKind.SUBSCRIPTION_START,
            channel="control",
            instrument_name=None,
            payload={"stream": "platform_state", "channel": "platform_state"},
        )
    )
    sequence += 1
    future.append(
        _event(
            capture_seq=sequence,
            collector_received_at_ms=final_wall_ms + 2,
            collector_elapsed_ms=cutoff_target_ms + 2,
            exchange_timestamp_ms=None,
            event_kind=EventKind.PLATFORM_STATE,
            channel="public/status",
            instrument_name=None,
            payload={
                "state": "OPEN",
                "locked": False,
                "price_index": "btc_usdc",
                "status_capture_seq": sequence,
            },
        )
    )

    close_wall_ms = final_wall_ms + 30 * 60_000
    close_elapsed_ms = cutoff_target_ms + 30 * 60_000
    option_rows = (
        (
            "BTC_USDC-20JUL26-98000-P",
            {
                "timestamp": close_wall_ms,
                "state": "open",
                "best_bid_price": "240",
                "best_ask_price": "250",
                "best_bid_amount": "1",
                "best_ask_amount": "1",
                "bid_iv": "65",
                "ask_iv": "66",
                "mark_iv": "65.5",
                "open_interest": "100",
                "greeks": {"delta": "-0.18", "gamma": "0.00002"},
            },
        ),
        (
            "BTC_USDC-20JUL26-96000-P",
            {
                "timestamp": close_wall_ms,
                "state": "open",
                "best_bid_price": "100",
                "best_ask_price": "110",
                "best_bid_amount": "1",
                "best_ask_amount": "1",
                "bid_iv": "67",
                "ask_iv": "68",
                "mark_iv": "67.5",
                "open_interest": "80",
                "greeks": {"delta": "-0.08", "gamma": "0.00001"},
            },
        ),
    )
    for instrument_name, payload in option_rows:
        sequence += 1
        future.append(
            _event(
                capture_seq=sequence,
                collector_received_at_ms=close_wall_ms,
                collector_elapsed_ms=close_elapsed_ms,
                exchange_timestamp_ms=close_wall_ms,
                event_kind=EventKind.TICKER,
                channel=f"ticker.{instrument_name}.agg2",
                instrument_name=instrument_name,
                payload=payload,
            )
        )
    sequence += 1
    future.append(
        _event(
            capture_seq=sequence,
            collector_received_at_ms=close_wall_ms,
            collector_elapsed_ms=close_elapsed_ms,
            exchange_timestamp_ms=close_wall_ms,
            event_kind=EventKind.TICKER,
            channel=f"ticker.{REFERENCE}.agg2",
            instrument_name=REFERENCE,
            payload={
                "timestamp": close_wall_ms,
                "state": "open",
                "last_price": "100010",
                "index_price": "100010",
                "mark_price": "100012",
                "best_bid_price": "100009",
                "best_ask_price": "100011",
                "funding_8h": "0.00002",
                "open_interest": "1500",
            },
        )
    )

    counterfactual_wall_ms = final_wall_ms + 60 * 60_000
    counterfactual_elapsed_ms = cutoff_target_ms + 60 * 60_000
    sequence += 1
    future.append(
        _event(
            capture_seq=sequence,
            collector_received_at_ms=counterfactual_wall_ms,
            collector_elapsed_ms=counterfactual_elapsed_ms,
            exchange_timestamp_ms=counterfactual_wall_ms,
            event_kind=EventKind.TICKER,
            channel=f"ticker.{REFERENCE}.agg2",
            instrument_name=REFERENCE,
            payload={
                "timestamp": counterfactual_wall_ms,
                "state": "open",
                "last_price": "97000",
                "index_price": "97000",
                "mark_price": "97002",
                "best_bid_price": "96999",
                "best_ask_price": "97001",
                "funding_8h": "0.00002",
                "open_interest": "1500",
            },
        )
    )
    return (*prefix, *future)


def _entry_platform_state(events: tuple[CanonicalEvent, ...]) -> PlatformState | None:
    reducer = MarketTapeReducer()
    for event in events:
        reducer.ingest(event)
    return reducer.snapshot().platform_state


def _outcome_observations(
    events: tuple[CanonicalEvent, ...],
    *,
    entry: ShadowEntryReceipt,
) -> tuple[OutcomeObservation, ...]:
    projector = RadarProjector()
    observations: list[OutcomeObservation] = []
    position = entry.position
    trigger_instruments = {
        REFERENCE,
        position.structure.short_leg.instrument_name,
        position.structure.long_leg.instrument_name,
        *((position.structure.combo_id,) if position.structure.combo_id is not None else ()),
    }
    horizon_elapsed_ms = position.entry_elapsed_ms + position.horizon_seconds * 1_000
    horizon_observed = False
    for event in events:
        frame = projector.ingest(event)
        if event.capture_seq <= position.entry_capture_seq:
            continue
        first_horizon_fact = bool(
            not horizon_observed and event.collector_elapsed_ms >= horizon_elapsed_ms
        )
        relevant_change = bool(
            (event.event_kind is EventKind.TICKER and event.instrument_name in trigger_instruments)
            or event.event_kind
            in {
                EventKind.PLATFORM_STATE,
                EventKind.RECONNECT,
                EventKind.SUBSCRIPTION_START,
            }
        )
        if not relevant_change and not first_horizon_fact:
            continue
        if frame is None:
            frame = projector.finalize()
        snapshot = projector.reducer.snapshot(event.collector_received_at_ms)
        observations.append(
            OutcomeObservation(
                frame=frame,
                platform_state=snapshot.platform_state,
                reconnect_capture_seq=snapshot.reconnect_capture_seq,
            )
        )
        horizon_observed = horizon_observed or first_horizon_fact
    return tuple(observations)


def _bound_identity(
    identity: OutcomeRuntimeSourceIdentity,
    git_commit_sha: str,
) -> OutcomeRuntimeSourceIdentity:
    return replace(identity, git_commit_sha=git_commit_sha)


def _summary_fields(
    manifest: CaptureManifest,
    events: tuple[CanonicalEvent, ...],
    identity: RuntimeSourceIdentity,
) -> dict[str, object]:
    inspected = inspect_payload(manifest, events, source_identity=identity)
    fields = (
        "actual_trades",
        "book_gap_records",
        "collector_elapsed_order",
        "collector_elapsed_regressions",
        "collector_elapsed_span_ms",
        "reconnect_records",
        "ticker_source_regressions",
        "trade_gap_records",
        "trade_source_regressions",
        "platform_locked",
        "platform_source_capture_seqs",
        "platform_state",
    )
    return {field: inspected.get(field) for field in fields}


def _compose(
    facts: Path,
    *,
    fact_provenance: str,
    evidence_class: str,
    duration_seconds: int,
    decision_identity: RuntimeSourceIdentity,
    outcome_identity: OutcomeRuntimeSourceIdentity,
    evidence_git_commit_sha: str,
) -> _Composition:
    seal, full_manifest, events, prefix_manifest, prefix_events = read_sealed_capture(facts)
    projection: RadarProjection = project_events(prefix_events)
    decision_receipt = build_decision_receipt(
        prefix_manifest,
        projection,
        source_identity=decision_identity,
        receipt_git_commit_sha=evidence_git_commit_sha,
    )
    encoded_decision = decision_receipt_payload(decision_receipt)
    entry_platform_state = _entry_platform_state(prefix_events)
    admission = admit_shadow(
        decision_receipt,
        decision_receipt_digest=decision_receipt.digest,
        frame=projection.frame,
        entry_platform_state=entry_platform_state,
        fact_provenance=fact_provenance,
        outcome_runtime_git_commit_sha=evidence_git_commit_sha,
        outcome_runtime_source_id=outcome_identity.runtime_source_id,
        outcome_runtime_source_digest=outcome_identity.runtime_source_digest,
    )
    entry: ShadowEntryReceipt | None = admission.entry_receipt
    outcome: OutcomeReceipt | None = None
    observations: tuple[OutcomeObservation, ...] = ()
    if entry is not None:
        observations = _outcome_observations(
            events,
            entry=entry,
        )
        outcome = evaluate_outcome(
            entry,
            observations,
            entry_receipt_digest=entry.digest,
            fact_seal_digest=seal.digest,
            full_capture_digest=full_manifest.content_sha256,
            full_capture_manifest_digest=full_manifest.digest,
            final_capture_seq=full_manifest.last_capture_seq,
        )
    encoded_entry = entry_receipt_payload(entry) if entry is not None else None
    encoded_outcome = outcome_receipt_payload(outcome) if outcome is not None else None
    projection_summary = projection_payload(projection)
    outcome_status = outcome.outcome_status.value if outcome is not None else None
    unknown_reasons = (
        list(outcome.unknown_reasons)
        if outcome is not None
        else list(admission.reasons)
        if admission.status is ShadowAdmission.UNKNOWN
        else []
    )
    result: dict[str, object] = {
        "fact_provenance": fact_provenance,
        "evidence_class": evidence_class,
        "duration_seconds": duration_seconds,
        "capture_complete": full_manifest.complete,
        "records": full_manifest.record_count,
        "full_capture_digest": full_manifest.content_sha256,
        "full_capture_manifest_digest": full_manifest.digest,
        "fact_seal_digest": seal.digest,
        "combined_capture_sha256": seal.combined_capture_sha256,
        "decision_cutoff_contract_id": seal.cutoff.contract_id,
        "decision_cutoff_capture_seq": seal.cutoff.capture_seq,
        "decision_cutoff_target_elapsed_ms": seal.cutoff.target_elapsed_ms,
        "prefix_record_count": prefix_manifest.record_count,
        "prefix_capture_digest": prefix_manifest.content_sha256,
        "prefix_capture_manifest_digest": prefix_manifest.digest,
        "suffix_record_count": seal.suffix_record_count,
        "suffix_first_capture_seq": seal.suffix_first_capture_seq,
        "suffix_last_capture_seq": seal.suffix_last_capture_seq,
        "suffix_sha256": seal.suffix_sha256,
        "decision_action": projection.decision.action.value,
        "decision_reason": projection.decision.reason,
        "decision_frame_complete": projection.frame.complete,
        "decision_readiness": projection_summary["decision_readiness"],
        "required_window_coverage": projection_summary["required_window_coverage"],
        "admission_status": admission.status.value,
        "admission_reasons": list(admission.reasons),
        "entry_count": int(entry is not None),
        "outcome_count": int(outcome is not None),
        "outcome_observation_count": len(observations),
        "outcome_status": outcome_status,
        "outcome_exit_reason": (
            outcome.observed_outcome.exit_reason.value if outcome is not None else None
        ),
        "unknown_reasons": unknown_reasons,
        "counterfactual_point_count": (
            len(outcome.counterfactual_path.points)
            if outcome is not None and outcome.counterfactual_path is not None
            else 0
        ),
        "decision_receipt_digest": decision_receipt.digest,
        "entry_receipt_digest": entry.digest if entry is not None else None,
        "outcome_receipt_digest": outcome.digest if outcome is not None else None,
        "input_contract_id": decision_receipt.input_contract_id,
        "input_contract_digest": decision_receipt.input_contract_digest,
        "policy_id": decision_receipt.policy_id,
        "policy_digest": decision_receipt.policy_digest,
        "outcome_contract_id": OUTCOME_CONTRACT_ID,
        "outcome_contract_digest": OUTCOME_CONTRACT_DIGEST,
        "git_commit_sha": evidence_git_commit_sha,
        "decision_runtime_source_id": decision_identity.runtime_source_id,
        "decision_runtime_source_digest": decision_identity.runtime_source_digest,
        "outcome_runtime_source_id": outcome_identity.runtime_source_id,
        "outcome_runtime_source_digest": outcome_identity.runtime_source_digest,
        "outcome_runtime_source_dirty_paths": list(outcome_identity.dirty_paths),
        "outcome_source_capture_seqs": (
            list(outcome.outcome_source_capture_seqs) if outcome is not None else []
        ),
        **_summary_fields(full_manifest, events, decision_identity),
    }
    result["result_digest"] = canonical_digest(result)
    return _Composition(
        result=result,
        decision_receipt=encoded_decision,
        entry_receipt=encoded_entry,
        outcome_receipt=encoded_outcome,
    )


def _persist_composition(output: Path, composition: _Composition) -> None:
    _write_json(output / DECISION_RECEIPT_PATH, composition.decision_receipt)
    if composition.entry_receipt is not None:
        _write_json(output / ENTRY_RECEIPT_PATH, composition.entry_receipt)
    if composition.outcome_receipt is not None:
        _write_json(output / OUTCOME_RECEIPT_PATH, composition.outcome_receipt)
    _write_json(output / RESULT_PATH, composition.result)


def _validate_output_root(output: Path) -> None:
    if output.exists():
        raise ValueError("Outcome output directory must not already exist")
    output.mkdir(parents=True)


def run_synthetic_outcome(output: Path) -> dict[str, object]:
    _validate_output_root(output)
    temp = output / TEMP_CAPTURE_DIRECTORY
    events = build_synthetic_outcome_events()
    write_capture(temp / "capture", events, complete=True)
    decision_identity = runtime_source_identity(require_clean=False)
    outcome_identity = outcome_runtime_source_identity(require_clean=False)
    try:
        seal_capture(temp / "capture", output / FACTS_DIRECTORY)
        composition = _compose(
            output / FACTS_DIRECTORY,
            fact_provenance="synthetic",
            evidence_class=SYNTHETIC_EVIDENCE_CLASS,
            duration_seconds=(events[-1].collector_elapsed_ms - events[0].collector_elapsed_ms)
            // 1_000,
            decision_identity=decision_identity,
            outcome_identity=outcome_identity,
            evidence_git_commit_sha=outcome_identity.git_commit_sha,
        )
        _persist_composition(output, composition)
        read_sealed_capture(output / FACTS_DIRECTORY)
    except Exception:
        raise
    else:
        shutil.rmtree(temp)
    return composition.result


def run_public_outcome_capture(output: Path, duration_seconds: int) -> dict[str, object]:
    if duration_seconds != PUBLIC_CAPTURE_SECONDS:
        raise ValueError("Outcome public capture duration must be exactly 3665 seconds")
    decision_identity = runtime_source_identity(require_clean=True)
    outcome_identity = outcome_runtime_source_identity(require_clean=True)
    _validate_output_root(output)
    temp = output / TEMP_CAPTURE_DIRECTORY
    try:
        invocation_started_at = datetime.now(UTC)
        invocation_started_ns = time.monotonic_ns()
        live = run_public_capture(temp, duration_seconds)
        invocation_finished_ns = time.monotonic_ns()
        invocation_finished_at = datetime.now(UTC)
        if live.get("duration_seconds") != duration_seconds:
            raise RuntimeError("collector duration binding changed")
        full_manifest, full_events = read_capture(temp / "capture")
        _write_json(
            output / "collector-inspect.json",
            inspect_payload(full_manifest, full_events, source_identity=decision_identity),
        )
        shutil.copy2(temp / "live.json", output / "collector-live.json")
        shutil.copy2(temp / "decision.json", output / "collector-decision.json")
        invocation = {
            "receipt_type": PUBLIC_INVOCATION_RECEIPT_TYPE,
            "environment": "production_public",
            "transport_endpoint": WEBSOCKET_URL,
            "requested_duration_seconds": duration_seconds,
            "invocation_started_at": invocation_started_at.isoformat(),
            "invocation_finished_at": invocation_finished_at.isoformat(),
            "invocation_elapsed_ms": (invocation_finished_ns - invocation_started_ns) // 1_000_000,
            "records": full_manifest.record_count,
            "capture_digest": full_manifest.content_sha256,
            "capture_manifest_digest": full_manifest.digest,
            "collector_live_sha256": _sha256_file(output / "collector-live.json"),
            "collector_decision_sha256": _sha256_file(output / "collector-decision.json"),
            "collector_inspect_sha256": _sha256_file(output / "collector-inspect.json"),
            "git_commit_sha": outcome_identity.git_commit_sha,
            "runtime_source_id": decision_identity.runtime_source_id,
            "runtime_source_digest": decision_identity.runtime_source_digest,
        }
        invocation["invocation_digest"] = canonical_digest(invocation)
        _write_json(output / PUBLIC_INVOCATION_PATH, invocation)
        seal_capture(temp / "capture", output / FACTS_DIRECTORY)
        composition = _compose(
            output / FACTS_DIRECTORY,
            fact_provenance="production_public",
            evidence_class=PUBLIC_EVIDENCE_CLASS,
            duration_seconds=duration_seconds,
            decision_identity=decision_identity,
            outcome_identity=outcome_identity,
            evidence_git_commit_sha=outcome_identity.git_commit_sha,
        )
        _persist_composition(output, composition)
        read_sealed_capture(output / FACTS_DIRECTORY)
    except Exception:
        raise
    else:
        shutil.rmtree(temp)
    return composition.result


def _drift_fields(
    expected: dict[str, object] | None,
    observed: dict[str, object] | None,
) -> list[str]:
    if expected is None or observed is None:
        return [] if expected is observed else ["<presence>"]
    return [
        key
        for key in sorted(set(expected) | set(observed))
        if key not in expected
        or key not in observed
        or type(expected[key]) is not type(observed[key])
        or expected[key] != observed[key]
    ]


def _optional_receipt(root: Path, name: str) -> dict[str, object] | None:
    path = root / name
    return _json_object(path, name) if path.is_file() else None


def reconstruct_outcome(run_root: Path) -> dict[str, object]:
    """Rebuild one persisted run without live state or output-side effects."""

    source_result = _json_object(run_root / RESULT_PATH, "Outcome result")
    source_digest = source_result.get("result_digest")
    unsigned_source = {key: value for key, value in source_result.items() if key != "result_digest"}
    if not isinstance(source_digest, str) or canonical_digest(unsigned_source) != source_digest:
        raise ValueError("Outcome result digest changed")
    provenance = source_result.get("fact_provenance")
    evidence_git_commit_sha = source_result.get("git_commit_sha")
    if (
        provenance not in {"synthetic", "production_public"}
        or not isinstance(evidence_git_commit_sha, str)
        or not evidence_git_commit_sha
    ):
        raise ValueError("Outcome result replay metadata is invalid")
    _seal, full_manifest, full_events, _prefix_manifest, _prefix_events = read_sealed_capture(
        run_root / FACTS_DIRECTORY
    )
    if not full_manifest.complete or not full_events:
        raise ValueError("Outcome replay requires one complete sealed capture")
    if provenance == "synthetic":
        evidence_class = SYNTHETIC_EVIDENCE_CLASS
        duration_seconds = (
            full_events[-1].collector_elapsed_ms - full_events[0].collector_elapsed_ms
        ) // 1_000
    else:
        evidence_class = PUBLIC_EVIDENCE_CLASS
        duration_seconds = PUBLIC_CAPTURE_SECONDS
    if (
        source_result.get("evidence_class") != evidence_class
        or source_result.get("duration_seconds") != duration_seconds
    ):
        raise ValueError("Outcome result replay metadata changed")
    decision_identity = runtime_source_identity(require_clean=False)
    outcome_identity = outcome_runtime_source_identity(require_clean=False)
    if (
        source_result.get("decision_runtime_source_id") != decision_identity.runtime_source_id
        or source_result.get("decision_runtime_source_digest")
        != decision_identity.runtime_source_digest
        or source_result.get("outcome_runtime_source_id") != outcome_identity.runtime_source_id
        or source_result.get("outcome_runtime_source_digest")
        != outcome_identity.runtime_source_digest
    ):
        raise ValueError("Outcome replay runtime source identity mismatch")
    bound_identity = _bound_identity(outcome_identity, evidence_git_commit_sha)
    reconstructed = _compose(
        run_root / FACTS_DIRECTORY,
        fact_provenance=provenance,
        evidence_class=evidence_class,
        duration_seconds=duration_seconds,
        decision_identity=decision_identity,
        outcome_identity=bound_identity,
        evidence_git_commit_sha=evidence_git_commit_sha,
    )
    source_decision = _json_object(run_root / DECISION_RECEIPT_PATH, "Decision receipt")
    source_entry = _optional_receipt(run_root, ENTRY_RECEIPT_PATH)
    source_outcome = _optional_receipt(run_root, OUTCOME_RECEIPT_PATH)
    decision_drift = _drift_fields(source_decision, reconstructed.decision_receipt)
    entry_drift = _drift_fields(source_entry, reconstructed.entry_receipt)
    outcome_drift = _drift_fields(source_outcome, reconstructed.outcome_receipt)
    result_drift = _drift_fields(source_result, reconstructed.result)
    if decision_drift or entry_drift or outcome_drift or result_drift:
        fields = sorted(
            {
                *(f"decision.{item}" for item in decision_drift),
                *(f"entry.{item}" for item in entry_drift),
                *(f"outcome.{item}" for item in outcome_drift),
                *(f"result.{item}" for item in result_drift),
            }
        )
        raise ValueError("Outcome replay drift: " + ",".join(fields))
    replay = {
        "evidence_class": REPLAY_EVIDENCE_CLASS,
        "fact_provenance": provenance,
        "replay_verified": True,
        "source_result_digest": source_digest,
        "reconstructed_result_digest": reconstructed.result["result_digest"],
        "decision_drift_count": 0,
        "decision_drift_fields": [],
        "entry_drift_count": 0,
        "entry_drift_fields": [],
        "outcome_drift_count": 0,
        "outcome_drift_fields": [],
        "result_drift_count": 0,
        "result_drift_fields": [],
        "strict_future_violation_count": 0,
        "replay_git_commit_sha": outcome_identity.git_commit_sha,
        **{
            field: reconstructed.result.get(field)
            for field in (
                "full_capture_digest",
                "full_capture_manifest_digest",
                "fact_seal_digest",
                "decision_receipt_digest",
                "entry_receipt_digest",
                "outcome_receipt_digest",
                "decision_runtime_source_digest",
                "outcome_runtime_source_digest",
                "input_contract_digest",
                "policy_digest",
                "outcome_contract_digest",
            )
        },
    }
    return replay


def replay_outcome(run_root: Path, output: Path) -> dict[str, object]:
    if output.exists():
        raise ValueError("Outcome replay output directory must not already exist")
    replay = reconstruct_outcome(run_root)
    output.mkdir(parents=True)
    _write_json(output / "replay.json", replay)
    return replay
