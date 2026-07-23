"""Bounded multi-decision Fixed-Policy public-Shadow composition and replay."""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import cast

from market_tape import (
    CAPTURE_FORMAT_ID,
    CanonicalEvent,
    CaptureManifest,
    EventKind,
    MarketTapeReducer,
    PublicShadowJournalReader,
    PublicShadowJournalWriter,
    canonical_digest,
    canonical_value,
    catalog_generation_identity,
    instrument_metadata_identity,
)
from market_tape.capture import _encoded_event
from shadow_engine import (
    NO_TRADE_COMPARATOR_ID,
    OPPORTUNITY_RECORD_TYPE,
    OUTCOME_CONTRACT_DIGEST,
    OUTCOME_CONTRACT_ID,
    RUN_CONTRACT_ID,
    RUN_RECEIPT_TYPE,
    AdmissionClass,
    MaturityClass,
    OpportunitySummary,
    OutcomeObservation,
    OutcomeReceipt,
    RunAccounting,
    ShadowEntryReceipt,
    TruthOutcomeStatus,
    admit_shadow,
    classify_admission,
    entry_receipt_payload,
    evaluate_outcome,
    outcome_receipt_payload,
)
from short_vol_radar import (
    DecisionFrame,
    DecisionInputContract,
    DecisionReceipt,
    RadarPolicy,
    RadarProjector,
    evaluate_radar_evidence,
)
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect
from websockets.sync.connection import Connection

from radar_runtime.deribit_public import (
    CATALOG_SCOPE,
    HEARTBEAT_SECONDS,
    REFERENCE,
    WEBSOCKET_URL,
    RadarProjection,
    _handle_message,
    _instrument_rows,
    _message,
    _object,
    _public_result,
    _refresh_catalog,
    _rpc,
    _wait_result,
    build_decision_receipt,
    decision_receipt_payload,
    select_btc_usdc_catalog,
)
from radar_runtime.fixture import build_fixture_events
from radar_runtime.outcome_identity import (
    OutcomeRuntimeSourceIdentity,
    outcome_runtime_source_identity,
)
from radar_runtime.outcome_runtime import (
    _compose,
    _OutcomeLiveSession,
    build_synthetic_outcome_events,
)
from radar_runtime.runtime_identity import RuntimeSourceIdentity, runtime_source_identity
from radar_runtime.shadow_identity import (
    RunRuntimeSourceIdentity,
    RuntimeEnvironmentIdentity,
    run_runtime_source_identity,
    runtime_environment_identity,
)

RUN_CONTRACT_PATH = "RUN_CONTRACT.json"
RUN_RESULT_PATH = "result.json"
RUN_RECEIPT_PATH = "run-receipt.json"
PROCESS_WITNESS_PATH = "invocation-witness.json"
RECEIPTS_DIRECTORY = "receipts"
REPLAY_RECEIPT_TYPE = "FIXED_POLICY_PUBLIC_SHADOW_REPLAY"
HISTORICAL_SEMANTIC_RECEIPT_TYPE = "NON_AUTHORITATIVE_HISTORICAL_SEMANTIC_REGRESSION"

INITIAL_SETUP_TIMEOUT_SECONDS = 60
NETWORK_OPEN_TIMEOUT_SECONDS = 10
NETWORK_RETRY_BACKOFF_SECONDS = 1
MAXIMUM_NETWORK_RETRY_DISPATCH_LATENCY_MS = 1_000
WARMUP_SECONDS = 3_600
CADENCE_SECONDS = 300
DUE_OPPORTUNITY_COUNT = 12
DECISION_PHASE_SECONDS = 7_200
MAXIMUM_POLICY_HORIZON_SECONDS = 14_400
OBSERVATION_TAIL_SECONDS = 300
SEALED_RUN_SECONDS = 21_900
SEGMENT_DURATION_MS = 300_000
MAXIMUM_OPPORTUNITY_COMMIT_LATENCY_MS = 5_000
PROBE_RETRY_INTERVAL_SECONDS = 60
PROBE_ATTEMPT_TIMEOUT_SECONDS = 60
MAXIMUM_PROBE_ATTEMPTS = 3
FUTURE_PLATFORM_PROBE_CONTRACT = "POST_ENTRY_AND_RECONNECT_PLATFORM_RESUBSCRIBE_THEN_STATUS"


class _HardCutoffReached(RuntimeError):
    pass


def _write_json_fsynced(path: Path, value: object) -> None:
    if path.exists():
        raise ValueError(f"public-Shadow artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            canonical_value(value),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _json_object(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return cast(dict[str, object], value)


def _typed_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _typed_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _typed_equal(one, two) for one, two in zip(left, right, strict=True)
        )
    return left == right


def _manifest(
    *,
    record_count: int,
    final_capture_seq: int,
    content_sha256: str,
    complete: bool,
) -> CaptureManifest:
    return CaptureManifest(
        format_id=CAPTURE_FORMAT_ID,
        record_count=record_count,
        first_capture_seq=1,
        last_capture_seq=final_capture_seq,
        content_sha256=content_sha256,
        complete=complete,
        incomplete_reasons=(() if complete else ("ONLINE_DECISION_PREFIX",)),
        data_path="segments",
    )


def build_run_contract(
    *,
    run_id: str,
    fact_provenance: str,
    created_at: str,
    decision_identity: RuntimeSourceIdentity,
    outcome_identity: OutcomeRuntimeSourceIdentity,
    run_identity: RunRuntimeSourceIdentity,
    environment: RuntimeEnvironmentIdentity,
) -> dict[str, object]:
    if fact_provenance not in {"synthetic", "production_public"}:
        raise ValueError("run fact provenance is invalid")
    if (
        environment.python_implementation != "CPython"
        or environment.python_version != "3.13.5"
        or environment.python_cache_tag != "cpython-313"
        or environment.websockets_version != "16.1.1"
    ):
        raise RuntimeError("runtime environment does not match the pre-registered contract")
    policy = RadarPolicy()
    input_contract = DecisionInputContract()
    return {
        "contract_id": RUN_CONTRACT_ID,
        "run_id": run_id,
        "fact_provenance": fact_provenance,
        "created_at": created_at,
        "environment": ("synthetic" if fact_provenance == "synthetic" else "production_public"),
        "transport_endpoint": None if fact_provenance == "synthetic" else WEBSOCKET_URL,
        "initial_setup_timeout_seconds": INITIAL_SETUP_TIMEOUT_SECONDS,
        "network_open_timeout_seconds": NETWORK_OPEN_TIMEOUT_SECONDS,
        "network_retry_backoff_seconds": NETWORK_RETRY_BACKOFF_SECONDS,
        "maximum_network_retry_dispatch_latency_ms": (MAXIMUM_NETWORK_RETRY_DISPATCH_LATENCY_MS),
        "warmup_seconds": WARMUP_SECONDS,
        "cadence_seconds": CADENCE_SECONDS,
        "due_opportunity_count": DUE_OPPORTUNITY_COUNT,
        "decision_phase_seconds": DECISION_PHASE_SECONDS,
        "maximum_policy_horizon_seconds": MAXIMUM_POLICY_HORIZON_SECONDS,
        "observation_tail_seconds": OBSERVATION_TAIL_SECONDS,
        "sealed_run_seconds": SEALED_RUN_SECONDS,
        "segment_duration_ms": SEGMENT_DURATION_MS,
        "maximum_opportunity_commit_latency_ms": MAXIMUM_OPPORTUNITY_COMMIT_LATENCY_MS,
        "admission_rule": "MAXIMUM_ONE_OPEN_ACTUAL_SHADOW_EXPOSURE",
        "initial_open_exposure_count": 0,
        "maturity_rule": "HORIZON_OBSERVATION_OR_EARLIER_EXECUTABLE_EXIT",
        "no_trade_comparator_id": NO_TRADE_COMPARATOR_ID,
        "future_platform_probe_contract": FUTURE_PLATFORM_PROBE_CONTRACT,
        "probe_retry_interval_seconds": PROBE_RETRY_INTERVAL_SECONDS,
        "probe_attempt_timeout_seconds": PROBE_ATTEMPT_TIMEOUT_SECONDS,
        "maximum_probe_attempts_per_entry_generation": MAXIMUM_PROBE_ATTEMPTS,
        "input_contract_id": input_contract.contract_id,
        "input_contract_digest": input_contract.digest,
        "policy_id": policy.policy_id,
        "policy_digest": policy.digest,
        "outcome_contract_id": OUTCOME_CONTRACT_ID,
        "outcome_contract_digest": OUTCOME_CONTRACT_DIGEST,
        "git_commit_sha": run_identity.git_commit_sha,
        "decision_runtime_source_id": decision_identity.runtime_source_id,
        "decision_runtime_source_digest": decision_identity.runtime_source_digest,
        "outcome_runtime_source_id": outcome_identity.runtime_source_id,
        "outcome_runtime_source_digest": outcome_identity.runtime_source_digest,
        "run_runtime_source_id": run_identity.runtime_source_id,
        "run_runtime_source_digest": run_identity.runtime_source_digest,
        "runtime_environment": canonical_value(environment),
        "runtime_environment_digest": environment.runtime_environment_digest,
        "external_source_attested": False,
        "attempt_selection_attested": False,
        "online_persistence_external_attested": False,
    }


@dataclass(slots=True)
class _EntryState:
    slot_index: int
    entry: ShadowEntryReceipt
    observations: list[OutcomeObservation]
    closed: bool = False


@dataclass(frozen=True, slots=True)
class RunComposition:
    origin_elapsed_ms: int
    seal_end_elapsed_ms: int
    opportunities: tuple[dict[str, object], ...]
    summaries: tuple[OpportunitySummary, ...]
    decision_receipts: tuple[DecisionReceipt | None, ...]
    entries: tuple[ShadowEntryReceipt, ...]
    outcomes: tuple[OutcomeReceipt, ...]
    accounting: RunAccounting
    full_capture_manifest: CaptureManifest
    run_receipt: dict[str, object]


class _OnlineRunController:
    """Make each due Decision durable before the collector can process another fact."""

    def __init__(
        self,
        *,
        root: Path,
        writer: PublicShadowJournalWriter,
        run_contract: dict[str, object],
        decision_identity: RuntimeSourceIdentity,
        outcome_identity: OutcomeRuntimeSourceIdentity,
        elapsed_ms: Callable[[], int],
    ) -> None:
        self.root = root
        self.writer = writer
        self.run_contract = run_contract
        self.decision_identity = decision_identity
        self.outcome_identity = outcome_identity
        self.elapsed_ms = elapsed_ms
        self.projector: RadarProjector | None = None
        self.origin_elapsed_ms: int | None = None
        self.origin_sources: tuple[int, ...] = ()
        self._initial_starts: dict[str, CanonicalEvent] = {}
        self._prefix_hasher = hashlib.sha256()
        self._records: list[dict[str, object] | None] = [None] * DUE_OPPORTUNITY_COUNT
        self._decision_receipts: list[DecisionReceipt | None] = [None] * DUE_OPPORTUNITY_COUNT
        self._entry_states: list[_EntryState] = []
        self._active: _EntryState | None = None
        self._ever_complete = False
        self.incomplete_reasons: list[str] = []
        self.opportunity_commit_latencies_ms: list[int] = []
        self._probe_obligations: list[dict[str, object]] = []
        self._platform_acquisition_ordinal = 0
        self.connection_generation = 0

    @property
    def records(self) -> tuple[dict[str, object], ...]:
        if any(item is None for item in self._records):
            raise RuntimeError("online opportunity denominator is incomplete")
        return tuple(cast(dict[str, object], item) for item in self._records)

    @property
    def seal_end_elapsed_ms(self) -> int | None:
        if self.origin_elapsed_ms is None:
            return None
        return self.origin_elapsed_ms + SEALED_RUN_SECONDS * 1_000

    @property
    def active_exposure(self) -> bool:
        return self._active is not None

    def incomplete_state(self) -> dict[str, object]:
        return {
            "recorded_slot_indices": [
                index for index, item in enumerate(self._records) if item is not None
            ],
            "missing_slot_indices": [
                index for index, item in enumerate(self._records) if item is None
            ],
            "entry_receipt_digests": [state.entry.digest for state in self._entry_states],
            "open_entry_receipt_digests": [
                state.entry.digest for state in self._entry_states if not state.closed
            ],
            "maturity_gap_entry_receipt_digests": [
                state.entry.digest for state in self._entry_states if not state.closed
            ],
            "probe_obligations": [
                {
                    "obligation_id": item["obligation_id"],
                    "entry_receipt_digest": item["entry_receipt_digest"],
                    "connection_generation": item["connection_generation"],
                    "attempt_zero_mode": item["attempt_zero_mode"],
                    "attempts": dict(cast(dict[int, str], item["attempts"])),
                    "satisfied": item["satisfied"],
                    "retired": item["retired"],
                }
                for item in self._probe_obligations
            ],
        }

    def attach_projector(self, projector: RadarProjector) -> None:
        self.projector = projector

    def _no_event_record(self, slot: int) -> dict[str, object]:
        if self.origin_elapsed_ms is None:
            raise RuntimeError("cannot close a slot before origin")
        target = self.origin_elapsed_ms + (WARMUP_SECONDS + slot * CADENCE_SECONDS) * 1_000
        return {
            "receipt_type": OPPORTUNITY_RECORD_TYPE,
            "run_id": self.run_contract["run_id"],
            "slot_index": slot,
            "target_elapsed_ms": target,
            "interval_start_elapsed_ms": target,
            "interval_end_elapsed_ms": target + CADENCE_SECONDS * 1_000,
            "event_backed": False,
            "cutoff_capture_seq": None,
            "cutoff_fact_digest": None,
            "decision_receipt_digest": None,
            "decision_action": None,
            "decision_complete": False,
            "admission_class": AdmissionClass.OPPORTUNITY_UNKNOWN.value,
            "admission_reason": "NO_CANONICAL_EVENT_IN_SLOT",
            "entry_receipt_digest": None,
            "fact_chain_head_through_cutoff": None,
        }

    def _commit_opportunity(self, record: dict[str, object], trigger_elapsed_ms: int) -> None:
        commit = self.writer.append_opportunity(record)
        commit_elapsed_ms = cast(int, commit["commit_elapsed_ms"])
        latency = commit_elapsed_ms - trigger_elapsed_ms
        self.opportunity_commit_latencies_ms.append(latency)
        if latency < 0 or latency > MAXIMUM_OPPORTUNITY_COMMIT_LATENCY_MS:
            self.incomplete_reasons.append("OPPORTUNITY_COMMIT_LATENCY_BREACH")

    def advance_time(self, now_elapsed_ms: int) -> None:
        if self.origin_elapsed_ms is None:
            if now_elapsed_ms >= INITIAL_SETUP_TIMEOUT_SECONDS * 1_000:
                self.incomplete_reasons.append("INITIAL_ORIGIN_DEADLINE_MISSED")
            return
        first_target = self.origin_elapsed_ms + WARMUP_SECONDS * 1_000
        for slot in range(DUE_OPPORTUNITY_COUNT):
            if self._records[slot] is not None:
                continue
            interval_end = first_target + (slot + 1) * CADENCE_SECONDS * 1_000
            if interval_end > now_elapsed_ms:
                break
            record = self._no_event_record(slot)
            self._commit_opportunity(record, interval_end)
            self._records[slot] = record

    def before_event(self, event: CanonicalEvent) -> None:
        hard_cutoff = (
            INITIAL_SETUP_TIMEOUT_SECONDS * 1_000
            if self.origin_elapsed_ms is None
            else self.seal_end_elapsed_ms
        )
        if hard_cutoff is not None and event.collector_elapsed_ms >= hard_cutoff:
            self.advance_time(hard_cutoff)
            self.writer.seal_fact_segments(hard_cutoff)
            if self.origin_elapsed_ms is None:
                self.incomplete_reasons.append("INITIAL_ORIGIN_DEADLINE_MISSED")
            raise _HardCutoffReached("canonical fact is at or after the hard cutoff")
        self.advance_time(event.collector_elapsed_ms)
        due_before_fact = self.due_probe(
            now_elapsed_ms=event.collector_elapsed_ms,
            active_connection=True,
        )
        if due_before_fact is not None:
            obligation, attempt = due_before_fact
            attempts = cast(dict[int, str], obligation["attempts"])
            attempts[attempt] = "OMITTED_BEFORE_LATER_FACT"
            self.incomplete_reasons.append("PLATFORM_PROBE_TIMER_ORDER_BREACH")
            self.writer.commit_control(
                "PLATFORM_PROBE_STATE_COMMIT",
                {
                    "obligation_id": obligation["obligation_id"],
                    "attempt": attempt,
                    "state": "OMITTED_BEFORE_LATER_FACT",
                    "later_fact_capture_seq": event.capture_seq,
                    "actual_elapsed_ms": event.collector_elapsed_ms,
                },
            )
        self.writer.advance_segments_before(event.collector_elapsed_ms)
        self.writer.append_fact(event)
        self._prefix_hasher.update(_encoded_event(event))

    def _establish_origin(self, event: CanonicalEvent) -> None:
        if self.origin_elapsed_ms is not None:
            return
        if event.event_kind is EventKind.RECONNECT:
            self.incomplete_reasons.append("INITIAL_CONNECTION_ENDED_BEFORE_ORIGIN")
            return
        if event.event_kind is not EventKind.SUBSCRIPTION_START:
            return
        stream = _event_payload(event).get("stream")
        if stream in {"reference_price", "reference_trade", "platform_state"}:
            self._initial_starts.setdefault(stream, event)
        if len(self._initial_starts) != 3:
            return
        origin = max(item.collector_elapsed_ms for item in self._initial_starts.values())
        if origin >= INITIAL_SETUP_TIMEOUT_SECONDS * 1_000:
            self.incomplete_reasons.append("INITIAL_ORIGIN_DEADLINE_MISSED")
            return
        self.origin_elapsed_ms = origin
        self.origin_sources = tuple(
            sorted(item.capture_seq for item in self._initial_starts.values())
        )
        self.writer.commit_control(
            "ORIGIN_COMMIT",
            {
                "origin_elapsed_ms": origin,
                "origin_subscription_capture_seqs": list(self.origin_sources),
                "slot_target_elapsed_ms": [
                    origin + (WARMUP_SECONDS + slot * CADENCE_SECONDS) * 1_000
                    for slot in range(DUE_OPPORTUNITY_COUNT)
                ],
            },
        )

    def _persist_online_receipt(
        self,
        *,
        artifact_type: str,
        relative: str,
        payload: dict[str, object],
        digest: str,
    ) -> None:
        _write_json_fsynced(self.root / relative, payload)
        self.writer.commit_artifact(
            artifact_type=artifact_type,
            relative_path=relative,
            artifact_digest=digest,
        )

    def _create_probe_obligation(
        self,
        state: _EntryState,
        event: CanonicalEvent,
        *,
        attempt_zero_mode: str = "PLATFORM_ONLY",
    ) -> None:
        if attempt_zero_mode not in {"PLATFORM_ONLY", "RECONNECT_BOOTSTRAP"}:
            raise ValueError("unsupported platform probe attempt-zero mode")
        obligation = {
            "obligation_id": canonical_digest(
                {
                    "entry_receipt_digest": state.entry.digest,
                    "connection_generation": self.connection_generation,
                    "trigger_capture_seq": event.capture_seq,
                    "attempt_zero_mode": attempt_zero_mode,
                }
            ),
            "entry_receipt_digest": state.entry.digest,
            "entry_capture_seq": state.entry.position.entry_capture_seq,
            "trigger_capture_seq": event.capture_seq,
            "connection_generation": self.connection_generation,
            "created_elapsed_ms": self.elapsed_ms(),
            "attempt_zero_mode": attempt_zero_mode,
            "attempts": {},
            "dispatches": {},
            "satisfied": False,
            "retired": False,
        }
        self._probe_obligations.append(obligation)
        self.writer.commit_control(
            "PLATFORM_PROBE_OBLIGATION_COMMIT",
            {
                key: value
                for key, value in obligation.items()
                if key not in {"attempts", "dispatches", "satisfied", "retired"}
            }
            | {
                "attempt_due_elapsed_ms": [
                    cast(int, obligation["created_elapsed_ms"])
                    + attempt * PROBE_RETRY_INTERVAL_SECONDS * 1_000
                    for attempt in range(MAXIMUM_PROBE_ATTEMPTS)
                ],
                "attempt_deadline_elapsed_ms": [
                    cast(int, obligation["created_elapsed_ms"])
                    + (attempt + 1) * PROBE_ATTEMPT_TIMEOUT_SECONDS * 1_000
                    for attempt in range(MAXIMUM_PROBE_ATTEMPTS)
                ],
            },
        )

    def _handle_reconnect_obligation(
        self,
        event: CanonicalEvent,
        state: _EntryState,
    ) -> None:
        for obligation in self._probe_obligations:
            if obligation["entry_receipt_digest"] == state.entry.digest and not cast(
                bool, obligation["retired"]
            ):
                obligation["retired"] = True
                self.writer.commit_control(
                    "PLATFORM_PROBE_STATE_COMMIT",
                    {
                        "obligation_id": obligation["obligation_id"],
                        "state": "INVALIDATED_BY_RECONNECT",
                        "reconnect_capture_seq": event.capture_seq,
                        "new_connection_generation": self.connection_generation,
                        "actual_elapsed_ms": self.elapsed_ms(),
                    },
                )
        self._create_probe_obligation(
            state,
            event,
            attempt_zero_mode="RECONNECT_BOOTSTRAP",
        )

    def after_event(
        self,
        event: CanonicalEvent,
        frame: DecisionFrame | None,
    ) -> None:
        if self.projector is None:
            raise RuntimeError("online run controller has no projector")
        self._establish_origin(event)
        current = frame or self.projector.finalize()
        self._ever_complete = self._ever_complete or _complete_60m(current)
        snapshot = self.projector.reducer.snapshot(event.collector_received_at_ms)
        for existing_state in self._entry_states:
            if event.capture_seq <= existing_state.entry.position.entry_capture_seq:
                continue
            existing_state.observations.append(
                OutcomeObservation(
                    frame=current,
                    platform_state=snapshot.platform_state,
                    reconnect_capture_seq=snapshot.reconnect_capture_seq,
                )
            )
        if self._active is not None and self._active.observations:
            provisional = evaluate_outcome(
                self._active.entry,
                tuple(self._active.observations),
                entry_receipt_digest=self._active.entry.digest,
                fact_seal_digest="ONLINE_PREFIX",
                full_capture_digest="ONLINE_PREFIX",
                full_capture_manifest_digest="ONLINE_PREFIX",
                final_capture_seq=event.capture_seq,
            )
            if provisional.outcome_status is TruthOutcomeStatus.CLOSED:
                self._active.closed = True
                self._active = None
        if event.event_kind is EventKind.RECONNECT and self._active is not None:
            self._handle_reconnect_obligation(event, self._active)
        if self.origin_elapsed_ms is None:
            return
        slot = _slot_for_elapsed(self.origin_elapsed_ms, event.collector_elapsed_ms)
        if slot is None or self._records[slot] is not None:
            return
        evaluation = evaluate_radar_evidence(current)
        projection = RadarProjection(
            final_event_capture_seq=event.capture_seq,
            frame=current,
            decision=evaluation.decision,
            evaluation=evaluation,
            current_complete_60m=_complete_60m(current),
            ever_observed_complete_60m=self._ever_complete,
        )
        prefix_manifest = _manifest(
            record_count=event.capture_seq,
            final_capture_seq=event.capture_seq,
            content_sha256=self._prefix_hasher.hexdigest(),
            complete=False,
        )
        decision_receipt = build_decision_receipt(
            prefix_manifest,
            projection,
            source_identity=self.decision_identity,
            receipt_git_commit_sha=cast(str, self.run_contract["git_commit_sha"]),
        )
        self._decision_receipts[slot] = decision_receipt
        decision_relative = f"{RECEIPTS_DIRECTORY}/decision-slot-{slot:02d}.json"
        self._persist_online_receipt(
            artifact_type="SHORT_VOL_DECISION_RECEIPT",
            relative=decision_relative,
            payload=decision_receipt_payload(decision_receipt),
            digest=decision_receipt.digest,
        )
        admission_class, admission_reason = classify_admission(
            decision_complete=current.complete,
            decision_action=evaluation.decision.action.value,
            capacity_available=self._active is None,
        )
        entry: ShadowEntryReceipt | None = None
        new_state: _EntryState | None = None
        if admission_class is AdmissionClass.ADMITTED:
            admitted = admit_shadow(
                decision_receipt,
                decision_receipt_digest=decision_receipt.digest,
                frame=current,
                entry_platform_state=snapshot.platform_state,
                fact_provenance=cast(str, self.run_contract["fact_provenance"]),
                outcome_runtime_git_commit_sha=cast(str, self.run_contract["git_commit_sha"]),
                outcome_runtime_source_id=self.outcome_identity.runtime_source_id,
                outcome_runtime_source_digest=self.outcome_identity.runtime_source_digest,
            )
            entry = admitted.entry_receipt
            if entry is None:
                raise RuntimeError("online ADMITTED opportunity produced no Entry")
            new_state = _EntryState(slot_index=slot, entry=entry, observations=[])
            self._entry_states.append(new_state)
            self._active = new_state
            entry_relative = f"{RECEIPTS_DIRECTORY}/entry-{len(self._entry_states) - 1:02d}.json"
            self._persist_online_receipt(
                artifact_type="SHORT_VOL_SHADOW_ENTRY_RECEIPT",
                relative=entry_relative,
                payload=entry_receipt_payload(entry),
                digest=entry.digest,
            )
        target = self.origin_elapsed_ms + (WARMUP_SECONDS + slot * CADENCE_SECONDS) * 1_000
        record = {
            "receipt_type": OPPORTUNITY_RECORD_TYPE,
            "run_id": self.run_contract["run_id"],
            "slot_index": slot,
            "target_elapsed_ms": target,
            "interval_start_elapsed_ms": target,
            "interval_end_elapsed_ms": target + CADENCE_SECONDS * 1_000,
            "event_backed": True,
            "cutoff_capture_seq": event.capture_seq,
            "cutoff_fact_digest": event.digest,
            "decision_receipt_digest": decision_receipt.digest,
            "decision_action": evaluation.decision.action.value,
            "decision_complete": current.complete,
            "decision_frame_digest": current.digest,
            "decision_readiness_digest": canonical_digest(decision_receipt.readiness),
            "input_contract_digest": decision_receipt.input_contract_digest,
            "policy_digest": decision_receipt.policy_digest,
            "runtime_source_digest": decision_receipt.runtime_source_digest,
            "admission_class": admission_class.value,
            "admission_reason": admission_reason,
            "entry_receipt_digest": entry.digest if entry is not None else None,
        }
        self._commit_opportunity(record, event.collector_elapsed_ms)
        self._records[slot] = record
        if new_state is not None:
            self._create_probe_obligation(new_state, event)

    def due_probe(
        self,
        *,
        now_elapsed_ms: int,
        active_connection: bool,
    ) -> tuple[dict[str, object], int] | None:
        for obligation in self._probe_obligations:
            if cast(bool, obligation["retired"]):
                continue
            attempts = cast(dict[int, str], obligation["attempts"])
            created = cast(int, obligation["created_elapsed_ms"])
            for attempt in range(MAXIMUM_PROBE_ATTEMPTS):
                if attempt in attempts:
                    continue
                due = created + attempt * PROBE_RETRY_INTERVAL_SECONDS * 1_000
                deadline = due + PROBE_ATTEMPT_TIMEOUT_SECONDS * 1_000
                if now_elapsed_ms < due:
                    break
                if cast(bool, obligation["satisfied"]):
                    attempts[attempt] = "SKIPPED_PAIR_ALREADY_VALID"
                    self.writer.commit_control(
                        "PLATFORM_PROBE_STATE_COMMIT",
                        {
                            "obligation_id": obligation["obligation_id"],
                            "attempt": attempt,
                            "state": "SKIPPED_PAIR_ALREADY_VALID",
                            "connection_generation": obligation["connection_generation"],
                            "due_elapsed_ms": due,
                            "deadline_elapsed_ms": deadline,
                            "actual_elapsed_ms": now_elapsed_ms,
                        },
                    )
                    continue
                if now_elapsed_ms >= deadline:
                    attempts[attempt] = "MISSED_DEADLINE"
                    self.incomplete_reasons.append("PLATFORM_PROBE_MISSED_DEADLINE")
                    self.writer.commit_control(
                        "PLATFORM_PROBE_STATE_COMMIT",
                        {
                            "obligation_id": obligation["obligation_id"],
                            "attempt": attempt,
                            "state": "MISSED_DEADLINE",
                            "connection_generation": obligation["connection_generation"],
                            "due_elapsed_ms": due,
                            "deadline_elapsed_ms": deadline,
                            "actual_elapsed_ms": now_elapsed_ms,
                        },
                    )
                    continue
                if not active_connection:
                    if attempt == 0 and obligation["attempt_zero_mode"] == "RECONNECT_BOOTSTRAP":
                        break
                    attempts[attempt] = "FAILED_NO_ACTIVE_CONNECTION"
                    self.writer.commit_control(
                        "PLATFORM_PROBE_STATE_COMMIT",
                        {
                            "obligation_id": obligation["obligation_id"],
                            "attempt": attempt,
                            "state": "FAILED_NO_ACTIVE_CONNECTION",
                            "connection_generation": obligation["connection_generation"],
                            "due_elapsed_ms": due,
                            "deadline_elapsed_ms": deadline,
                            "actual_elapsed_ms": now_elapsed_ms,
                        },
                    )
                    continue
                attempts[attempt] = "DISPATCHING"
                return obligation, attempt
        return None

    def begin_probe(
        self,
        obligation: dict[str, object],
        attempt: int,
        *,
        request_id: int,
        method: str = "public/subscribe",
        params: object | None = None,
    ) -> int:
        now = self.elapsed_ms()
        created = cast(int, obligation["created_elapsed_ms"])
        due = created + attempt * PROBE_RETRY_INTERVAL_SECONDS * 1_000
        deadline = due + PROBE_ATTEMPT_TIMEOUT_SECONDS * 1_000
        if not due <= now < deadline:
            raise RuntimeError("platform probe send intent is outside its timely interval")
        self._platform_acquisition_ordinal += 1
        acquisition_ordinal = self._platform_acquisition_ordinal
        actual_params = {"channels": ["platform_state"]} if params is None else params
        dispatches = cast(dict[int, dict[str, object]], obligation["dispatches"])
        dispatches[attempt] = {
            "platform_acquisition_ordinal": acquisition_ordinal,
            "request_id": request_id,
            "method": method,
        }
        self.writer.commit_control(
            "PLATFORM_PROBE_SEND_INTENT_COMMIT",
            {
                "obligation_id": obligation["obligation_id"],
                "attempt": attempt,
                "connection_generation": obligation["connection_generation"],
                "platform_acquisition_ordinal": acquisition_ordinal,
                "request_id": request_id,
                "method": method,
                "params": actual_params,
                "due_elapsed_ms": due,
                "deadline_elapsed_ms": deadline,
                "actual_elapsed_ms": now,
            },
        )
        return acquisition_ordinal

    def fail_dispatching_probes(self, error: str) -> None:
        for obligation in self._probe_obligations:
            attempts = cast(dict[int, str], obligation["attempts"])
            dispatches = cast(dict[int, dict[str, object]], obligation["dispatches"])
            for attempt, state in tuple(attempts.items()):
                if state != "DISPATCHING":
                    continue
                dispatch = dispatches[attempt]
                acquisition_ordinal = cast(
                    int,
                    dispatch["platform_acquisition_ordinal"],
                )
                request_id = cast(int, dispatch["request_id"])
                method = cast(str, dispatch["method"])
                self.commit_probe_rpc_result(
                    obligation,
                    attempt=attempt,
                    acquisition_ordinal=acquisition_ordinal,
                    request_id=request_id,
                    method=method,
                    result="FAILED",
                    error=error,
                    actual_elapsed_ms=self.elapsed_ms(),
                )
                self.finish_probe(
                    obligation,
                    attempt,
                    state="SEND_OR_RESPONSE_FAILED",
                    request_id=request_id,
                    error=error,
                    acquisition_ordinal=acquisition_ordinal,
                )

    def finish_probe(
        self,
        obligation: dict[str, object],
        attempt: int,
        *,
        state: str,
        request_id: int,
        error: str | None,
        acquisition_ordinal: int | None = None,
        subscription_capture_seq: int | None = None,
        status_capture_seq: int | None = None,
    ) -> None:
        attempts = cast(dict[int, str], obligation["attempts"])
        attempts[attempt] = state
        self.writer.commit_control(
            "PLATFORM_PROBE_ATTEMPT_STATE_COMMIT",
            {
                "obligation_id": obligation["obligation_id"],
                "attempt": attempt,
                "connection_generation": obligation["connection_generation"],
                "platform_acquisition_ordinal": acquisition_ordinal,
                "state": state,
                "request_id": request_id,
                "error": error,
                "subscription_capture_seq": subscription_capture_seq,
                "status_capture_seq": status_capture_seq,
                "actual_elapsed_ms": self.elapsed_ms(),
            },
        )

    def commit_probe_rpc_result(
        self,
        obligation: dict[str, object],
        *,
        attempt: int,
        acquisition_ordinal: int,
        request_id: int,
        method: str,
        result: str,
        error: str | None,
        actual_elapsed_ms: int,
    ) -> None:
        self.writer.commit_control(
            "PLATFORM_PROBE_RPC_RESULT_COMMIT",
            {
                "obligation_id": obligation["obligation_id"],
                "attempt": attempt,
                "connection_generation": obligation["connection_generation"],
                "platform_acquisition_ordinal": acquisition_ordinal,
                "request_id": request_id,
                "method": method,
                "result": result,
                "error": error,
                "actual_elapsed_ms": actual_elapsed_ms,
            },
        )

    def satisfy_probe(
        self,
        obligation: dict[str, object],
        *,
        attempt: int,
        acquisition_ordinal: int,
        subscription_event: CanonicalEvent,
        status_event: CanonicalEvent,
    ) -> None:
        if cast(bool, obligation["retired"]):
            raise RuntimeError("retired platform obligation cannot be satisfied")
        entry_seq = cast(int, obligation["entry_capture_seq"])
        if (
            subscription_event.event_kind is not EventKind.SUBSCRIPTION_START
            or status_event.event_kind is not EventKind.PLATFORM_STATE
            or subscription_event.capture_seq <= entry_seq
            or status_event.capture_seq <= subscription_event.capture_seq
        ):
            raise RuntimeError("platform acquisition pair is not strictly future")
        obligation["satisfied"] = True
        self.writer.commit_control(
            "PLATFORM_PROBE_STATE_COMMIT",
            {
                "obligation_id": obligation["obligation_id"],
                "attempt": attempt,
                "state": "SATISFIED",
                "connection_generation": obligation["connection_generation"],
                "platform_acquisition_ordinal": acquisition_ordinal,
                "subscription_capture_seq": subscription_event.capture_seq,
                "status_capture_seq": status_event.capture_seq,
                "actual_elapsed_ms": self.elapsed_ms(),
            },
        )


def _complete_60m(frame: DecisionFrame) -> bool:
    window = frame.window(3_600)
    return bool(
        window is not None and window.coverage.price_complete and window.coverage.trade_complete
    )


def _event_payload(event: CanonicalEvent) -> dict[str, object]:
    value: object = json.loads(event.raw_payload)
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _origin(
    events: tuple[CanonicalEvent, ...],
) -> tuple[int, tuple[int, ...]]:
    starts: dict[str, CanonicalEvent] = {}
    generation_started = False
    for event in events:
        if event.collector_elapsed_ms >= INITIAL_SETUP_TIMEOUT_SECONDS * 1_000:
            break
        if event.event_kind is EventKind.RECONNECT and generation_started:
            raise ValueError("initial connection ended before origin")
        if event.event_kind is not EventKind.SUBSCRIPTION_START:
            continue
        stream = _event_payload(event).get("stream")
        if stream in {"reference_price", "reference_trade", "platform_state"}:
            generation_started = True
            starts.setdefault(stream, event)
        if len(starts) == 3:
            return (
                max(item.collector_elapsed_ms for item in starts.values()),
                tuple(sorted(item.capture_seq for item in starts.values())),
            )
    raise ValueError("initial required subscriptions were not established before deadline")


def _slot_for_elapsed(origin_elapsed_ms: int, elapsed_ms: int) -> int | None:
    first_target = origin_elapsed_ms + WARMUP_SECONDS * 1_000
    relative = elapsed_ms - first_target
    if relative < 0:
        return None
    slot = relative // (CADENCE_SECONDS * 1_000)
    return int(slot) if 0 <= slot < DUE_OPPORTUNITY_COUNT else None


def _maturity(entry: ShadowEntryReceipt, outcome: OutcomeReceipt) -> MaturityClass:
    if outcome.outcome_status is TruthOutcomeStatus.CLOSED:
        return MaturityClass.MATURE_CLOSED
    horizon_elapsed_ms = entry.position.entry_elapsed_ms + entry.position.horizon_seconds * 1_000
    horizon_observed = any(
        point.observed_elapsed_ms >= horizon_elapsed_ms
        for point in (
            *outcome.actual_path.points,
            *(
                outcome.counterfactual_path.points
                if outcome.counterfactual_path is not None
                else ()
            ),
        )
    )
    if not horizon_observed:
        return MaturityClass.IMMATURE_UNKNOWN
    if outcome.outcome_status is TruthOutcomeStatus.UNEXITABLE:
        return MaturityClass.MATURE_UNEXITABLE
    return MaturityClass.MATURE_UNKNOWN


def compose_run(
    events: tuple[CanonicalEvent, ...],
    *,
    run_contract: dict[str, object],
    decision_identity: RuntimeSourceIdentity,
    outcome_identity: OutcomeRuntimeSourceIdentity,
    fact_seal_digest: str,
    require_complete: bool = True,
) -> RunComposition:
    if not events:
        raise ValueError("public-Shadow run has no canonical facts")
    if any(event.capture_seq != index for index, event in enumerate(events, start=1)):
        raise ValueError("public-Shadow run facts are not contiguous")
    if any(
        current.collector_elapsed_ms < previous.collector_elapsed_ms
        for previous, current in pairwise(events)
    ):
        raise ValueError("public-Shadow run elapsed time regressed")
    origin_elapsed_ms, origin_sources = _origin(events)
    seal_end_elapsed_ms = origin_elapsed_ms + SEALED_RUN_SECONDS * 1_000
    included = tuple(event for event in events if event.collector_elapsed_ms < seal_end_elapsed_ms)
    if not included:
        raise ValueError("public-Shadow run has no facts inside its sealed interval")
    projector = RadarProjector()
    prefix_hasher = hashlib.sha256()
    opportunities: list[dict[str, object] | None] = [None] * DUE_OPPORTUNITY_COUNT
    decisions: list[DecisionReceipt | None] = [None] * DUE_OPPORTUNITY_COUNT
    entry_by_slot: dict[int, _EntryState] = {}
    entry_states: list[_EntryState] = []
    active: _EntryState | None = None
    ever_complete = False
    no_event_closed_through = -1

    def no_event_record(slot: int) -> dict[str, object]:
        target = origin_elapsed_ms + (WARMUP_SECONDS + slot * CADENCE_SECONDS) * 1_000
        return {
            "receipt_type": OPPORTUNITY_RECORD_TYPE,
            "run_id": run_contract["run_id"],
            "slot_index": slot,
            "target_elapsed_ms": target,
            "interval_start_elapsed_ms": target,
            "interval_end_elapsed_ms": target + CADENCE_SECONDS * 1_000,
            "event_backed": False,
            "cutoff_capture_seq": None,
            "cutoff_fact_digest": None,
            "decision_receipt_digest": None,
            "decision_action": None,
            "decision_complete": False,
            "admission_class": AdmissionClass.OPPORTUNITY_UNKNOWN.value,
            "admission_reason": "NO_CANONICAL_EVENT_IN_SLOT",
            "entry_receipt_digest": None,
            "fact_chain_head_through_cutoff": None,
        }

    for event in included:
        slot = _slot_for_elapsed(origin_elapsed_ms, event.collector_elapsed_ms)
        if slot is not None:
            for missed in range(no_event_closed_through + 1, slot):
                if opportunities[missed] is None:
                    opportunities[missed] = no_event_record(missed)
                no_event_closed_through = missed
        prefix_hasher.update(_encoded_event(event))
        frame = projector.ingest(event)
        if frame is None:
            frame = projector.finalize()
        ever_complete = ever_complete or _complete_60m(frame)
        snapshot = projector.reducer.snapshot(event.collector_received_at_ms)
        for state in entry_states:
            if event.capture_seq <= state.entry.position.entry_capture_seq:
                continue
            state.observations.append(
                OutcomeObservation(
                    frame=frame,
                    platform_state=snapshot.platform_state,
                    reconnect_capture_seq=snapshot.reconnect_capture_seq,
                )
            )
        if active is not None and active.observations:
            provisional = evaluate_outcome(
                active.entry,
                tuple(active.observations),
                entry_receipt_digest=active.entry.digest,
                fact_seal_digest=fact_seal_digest,
                full_capture_digest="ONLINE_PREFIX",
                full_capture_manifest_digest="ONLINE_PREFIX",
                final_capture_seq=event.capture_seq,
            )
            if provisional.outcome_status is TruthOutcomeStatus.CLOSED:
                active.closed = True
                active = None
        if slot is None or opportunities[slot] is not None:
            continue
        evaluation = evaluate_radar_evidence(frame)
        projection = RadarProjection(
            final_event_capture_seq=event.capture_seq,
            frame=frame,
            decision=evaluation.decision,
            evaluation=evaluation,
            current_complete_60m=_complete_60m(frame),
            ever_observed_complete_60m=ever_complete,
        )
        prefix_manifest = _manifest(
            record_count=event.capture_seq,
            final_capture_seq=event.capture_seq,
            content_sha256=prefix_hasher.hexdigest(),
            complete=False,
        )
        decision_receipt = build_decision_receipt(
            prefix_manifest,
            projection,
            source_identity=decision_identity,
            receipt_git_commit_sha=cast(str, run_contract["git_commit_sha"]),
        )
        decisions[slot] = decision_receipt
        admission_class, admission_reason = classify_admission(
            decision_complete=frame.complete,
            decision_action=evaluation.decision.action.value,
            capacity_available=active is None,
        )
        entry: ShadowEntryReceipt | None = None
        if admission_class is AdmissionClass.ADMITTED:
            admitted = admit_shadow(
                decision_receipt,
                decision_receipt_digest=decision_receipt.digest,
                frame=frame,
                entry_platform_state=snapshot.platform_state,
                fact_provenance=cast(str, run_contract["fact_provenance"]),
                outcome_runtime_git_commit_sha=cast(str, run_contract["git_commit_sha"]),
                outcome_runtime_source_id=outcome_identity.runtime_source_id,
                outcome_runtime_source_digest=outcome_identity.runtime_source_digest,
            )
            if admitted.entry_receipt is None:
                raise RuntimeError("ADMITTED run opportunity produced no Entry receipt")
            entry = admitted.entry_receipt
            active = _EntryState(slot_index=slot, entry=entry, observations=[])
            entry_states.append(active)
            entry_by_slot[slot] = active
        target = origin_elapsed_ms + (WARMUP_SECONDS + slot * CADENCE_SECONDS) * 1_000
        opportunities[slot] = {
            "receipt_type": OPPORTUNITY_RECORD_TYPE,
            "run_id": run_contract["run_id"],
            "slot_index": slot,
            "target_elapsed_ms": target,
            "interval_start_elapsed_ms": target,
            "interval_end_elapsed_ms": target + CADENCE_SECONDS * 1_000,
            "event_backed": True,
            "cutoff_capture_seq": event.capture_seq,
            "cutoff_fact_digest": event.digest,
            "decision_receipt_digest": decision_receipt.digest,
            "decision_action": evaluation.decision.action.value,
            "decision_complete": frame.complete,
            "decision_frame_digest": frame.digest,
            "decision_readiness_digest": canonical_digest(decision_receipt.readiness),
            "input_contract_digest": decision_receipt.input_contract_digest,
            "policy_digest": decision_receipt.policy_digest,
            "runtime_source_digest": decision_receipt.runtime_source_digest,
            "admission_class": admission_class.value,
            "admission_reason": admission_reason,
            "entry_receipt_digest": entry.digest if entry is not None else None,
        }
        no_event_closed_through = max(no_event_closed_through, slot)

    for slot in range(DUE_OPPORTUNITY_COUNT):
        if opportunities[slot] is None:
            opportunities[slot] = no_event_record(slot)
    complete_opportunities = tuple(cast(dict[str, object], item) for item in opportunities)
    full_hasher = hashlib.sha256()
    for event in included:
        full_hasher.update(_encoded_event(event))
    full_manifest = _manifest(
        record_count=len(included),
        final_capture_seq=included[-1].capture_seq,
        content_sha256=full_hasher.hexdigest(),
        complete=True,
    )
    outcomes: list[OutcomeReceipt] = []
    outcome_by_slot: dict[int, OutcomeReceipt] = {}
    for state in entry_states:
        outcome = evaluate_outcome(
            state.entry,
            tuple(state.observations),
            entry_receipt_digest=state.entry.digest,
            fact_seal_digest=fact_seal_digest,
            full_capture_digest=full_manifest.content_sha256,
            full_capture_manifest_digest=full_manifest.digest,
            final_capture_seq=full_manifest.last_capture_seq,
        )
        outcomes.append(outcome)
        outcome_by_slot[state.slot_index] = outcome
    summaries: list[OpportunitySummary] = []
    for slot, record in enumerate(complete_opportunities):
        entry_state = entry_by_slot.get(slot)
        final_outcome = outcome_by_slot.get(slot)
        summaries.append(
            OpportunitySummary(
                slot_index=slot,
                event_backed=cast(bool, record["event_backed"]),
                decision_complete=cast(bool, record["decision_complete"]),
                decision_action=cast(str | None, record.get("decision_action")),
                admission_class=AdmissionClass(cast(str, record["admission_class"])),
                admission_reason=cast(str, record["admission_reason"]),
                entry_receipt_digest=(
                    entry_state.entry.digest if entry_state is not None else None
                ),
                outcome_receipt_digest=(
                    final_outcome.digest if final_outcome is not None else None
                ),
                outcome_status=(
                    final_outcome.outcome_status.value if final_outcome is not None else None
                ),
                maturity_class=(
                    _maturity(entry_state.entry, final_outcome)
                    if entry_state is not None and final_outcome is not None
                    else None
                ),
                observed_executable_pnl_usdc=(
                    final_outcome.observed_outcome.observed_executable_pnl_usdc
                    if final_outcome is not None
                    else None
                ),
            )
        )
    accounting = RunAccounting.from_opportunities(
        tuple(summaries),
        due_count=DUE_OPPORTUNITY_COUNT,
        require_complete=require_complete,
    )
    event_counts = Counter(item.event_kind.value for item in included)
    run_receipt: dict[str, object] = {
        "receipt_type": RUN_RECEIPT_TYPE,
        "run_id": run_contract["run_id"],
        "run_contract_digest": canonical_digest(run_contract),
        "complete": True,
        "origin_elapsed_ms": origin_elapsed_ms,
        "origin_subscription_capture_seqs": list(origin_sources),
        "slot_target_elapsed_ms": [
            origin_elapsed_ms + (WARMUP_SECONDS + slot * CADENCE_SECONDS) * 1_000
            for slot in range(DUE_OPPORTUNITY_COUNT)
        ],
        "seal_end_elapsed_ms": seal_end_elapsed_ms,
        "final_event_capture_seq": full_manifest.last_capture_seq,
        "final_decision_frame_capture_seq": projector.finalize().as_of_capture_seq,
        "full_capture_digest": full_manifest.content_sha256,
        "full_capture_manifest_digest": full_manifest.digest,
        "fact_seal_digest": fact_seal_digest,
        "opportunity_record_digests": [canonical_digest(item) for item in complete_opportunities],
        "decision_receipt_digests": [
            item.digest if item is not None else None for item in decisions
        ],
        "entry_receipt_digests": [item.entry.digest for item in entry_states],
        "outcome_receipt_digests": [item.digest for item in outcomes],
        "opportunity_summaries": canonical_value(tuple(summaries)),
        "accounting": canonical_value(accounting),
        "no_trade_comparators": [
            {
                "comparator_id": NO_TRADE_COMPARATOR_ID,
                "slot_index": slot,
                "exposure": 0,
                "fee_usdc": "0",
                "pnl_usdc": "0",
            }
            for slot in range(DUE_OPPORTUNITY_COUNT)
        ],
        "gap_records": event_counts[EventKind.TRADE_GAP.value]
        + event_counts[EventKind.BOOK_GAP.value],
        "reconnect_records": event_counts[EventKind.RECONNECT.value],
        "platform_state_records": event_counts[EventKind.PLATFORM_STATE.value],
        "fact_provenance": run_contract["fact_provenance"],
        "git_commit_sha": run_contract["git_commit_sha"],
        "decision_runtime_source_digest": run_contract["decision_runtime_source_digest"],
        "outcome_runtime_source_digest": run_contract["outcome_runtime_source_digest"],
        "run_runtime_source_digest": run_contract["run_runtime_source_digest"],
        "runtime_environment_digest": run_contract["runtime_environment_digest"],
        "external_source_attested": False,
        "attempt_selection_attested": False,
        "online_persistence_external_attested": False,
    }
    run_receipt["run_receipt_digest"] = canonical_digest(run_receipt)
    return RunComposition(
        origin_elapsed_ms=origin_elapsed_ms,
        seal_end_elapsed_ms=seal_end_elapsed_ms,
        opportunities=complete_opportunities,
        summaries=tuple(summaries),
        decision_receipts=tuple(decisions),
        entries=tuple(item.entry for item in entry_states),
        outcomes=tuple(outcomes),
        accounting=accounting,
        full_capture_manifest=full_manifest,
        run_receipt=run_receipt,
    )


def _synthetic_events() -> tuple[CanonicalEvent, ...]:
    """Extend the accepted candidate fixture across all twelve fixed slots."""

    accepted = build_synthetic_outcome_events()
    prefix = accepted[:144]
    elapsed_offset = min(item.collector_elapsed_ms for item in prefix)
    events = [
        replace(
            item,
            collector_elapsed_ms=item.collector_elapsed_ms - elapsed_offset,
        )
        for item in prefix
    ]
    origin_elapsed_ms, _ = _origin(tuple(events))
    first_target = origin_elapsed_ms + WARMUP_SECONDS * 1_000
    market_origin_ms = events[-1].exchange_timestamp_ms
    if market_origin_ms is None:
        raise RuntimeError("synthetic cutoff has no market-time reference")
    fixture = build_fixture_events()
    instrument_templates: dict[str, dict[str, object]] = {}
    option_ticker_templates: dict[str, dict[str, object]] = {}
    reference_ticker: dict[str, object] | None = None
    for event in fixture:
        payload = _event_payload(event)
        if event.event_kind is EventKind.INSTRUMENT and event.instrument_name is not None:
            instrument_templates[event.instrument_name] = payload
        elif event.event_kind is EventKind.TICKER and event.instrument_name == REFERENCE:
            reference_ticker = payload
        elif (
            event.event_kind is EventKind.TICKER
            and event.instrument_name is not None
            and event.instrument_name != REFERENCE
        ):
            option_ticker_templates[event.instrument_name] = payload
    if reference_ticker is None or len(option_ticker_templates) != 4:
        raise RuntimeError("synthetic market templates are incomplete")
    reducer = MarketTapeReducer()
    for event in events:
        reducer.ingest(event)
    sequence = events[-1].capture_seq
    received_origin_ms = events[-1].collector_received_at_ms

    def market_ms(elapsed_ms: int) -> int:
        return market_origin_ms + elapsed_ms - first_target

    def append(
        *,
        elapsed_ms: int,
        event_kind: EventKind,
        channel: str,
        payload: dict[str, object],
        instrument_name: str | None = None,
        exchange_timestamp_ms: int | None = None,
    ) -> CanonicalEvent:
        nonlocal sequence
        sequence += 1
        event = CanonicalEvent(
            capture_seq=sequence,
            collector_received_at_ms=(received_origin_ms + max(0, elapsed_ms - first_target)),
            collector_elapsed_ms=elapsed_ms,
            exchange_timestamp_ms=exchange_timestamp_ms,
            channel=channel,
            event_kind=event_kind,
            instrument_name=instrument_name,
            raw_payload=json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        reducer.ingest(event)
        events.append(event)
        return event

    def platform_pair(elapsed_ms: int) -> None:
        subscription = append(
            elapsed_ms=elapsed_ms,
            event_kind=EventKind.SUBSCRIPTION_START,
            channel="control",
            payload={"stream": "platform_state", "channel": "platform_state"},
        )
        status_seq = sequence + 1
        append(
            elapsed_ms=elapsed_ms + 1,
            event_kind=EventKind.PLATFORM_STATE,
            channel="public/status",
            payload={
                "state": "OPEN",
                "locked": False,
                "price_index": "btc_usdc",
                "status_capture_seq": status_seq,
                "source_capture_seqs": [subscription.capture_seq],
            },
        )

    def refresh(elapsed_ms: int) -> None:
        source_ms = market_ms(elapsed_ms)
        for name in sorted(option_ticker_templates):
            payload = dict(option_ticker_templates[name])
            payload["timestamp"] = source_ms
            append(
                elapsed_ms=elapsed_ms,
                event_kind=EventKind.TICKER,
                channel=f"ticker.{name}.agg2",
                instrument_name=name,
                exchange_timestamp_ms=source_ms,
                payload=payload,
            )
        for name in sorted(instrument_templates):
            append(
                elapsed_ms=elapsed_ms,
                event_kind=EventKind.INSTRUMENT,
                channel="public/get_instruments",
                instrument_name=name,
                exchange_timestamp_ms=source_ms,
                payload=instrument_templates[name],
            )
        instruments = tuple(
            sorted(reducer.snapshot().instruments, key=lambda item: item.instrument_name)
        )
        names = tuple(item.instrument_name for item in instruments)
        sources = tuple(item.source_capture_seq for item in instruments)
        metadata_digest = canonical_digest(
            tuple(instrument_metadata_identity(item) for item in instruments)
        )
        append(
            elapsed_ms=elapsed_ms,
            event_kind=EventKind.CATALOG_SNAPSHOT,
            channel="public/get_instruments",
            exchange_timestamp_ms=source_ms,
            payload={
                "timestamp": source_ms,
                "scope": CATALOG_SCOPE,
                "reference_instrument": REFERENCE,
                "instrument_names": names,
                "instrument_source_capture_seqs": sources,
                "metadata_set_digest": metadata_digest,
                "generation_id": catalog_generation_identity(
                    scope=CATALOG_SCOPE,
                    source_at_ms=source_ms,
                    reference_instrument=REFERENCE,
                    instrument_names=names,
                    instrument_source_capture_seqs=sources,
                    metadata_set_digest=metadata_digest,
                ),
            },
        )

    def reference(elapsed_ms: int) -> None:
        source_ms = market_ms(elapsed_ms)
        payload = dict(reference_ticker)
        payload["timestamp"] = source_ms
        payload["last_price"] = "100000"
        payload["index_price"] = "100000"
        payload["mark_price"] = "100002"
        append(
            elapsed_ms=elapsed_ms,
            event_kind=EventKind.TICKER,
            channel=f"ticker.{REFERENCE}.agg2",
            instrument_name=REFERENCE,
            exchange_timestamp_ms=source_ms,
            payload=payload,
        )

    def profitable_close(elapsed_ms: int) -> None:
        source_ms = market_ms(elapsed_ms)
        reference(elapsed_ms)
        prices = {
            "BTC_USDC-20JUL26-96000-P": ("95", "100"),
            "BTC_USDC-20JUL26-98000-P": ("240", "250"),
        }
        for name, (bid, ask) in prices.items():
            payload = dict(option_ticker_templates[name])
            payload.update(
                {
                    "timestamp": source_ms,
                    "best_bid_price": bid,
                    "best_ask_price": ask,
                }
            )
            append(
                elapsed_ms=elapsed_ms,
                event_kind=EventKind.TICKER,
                channel=f"ticker.{name}.agg2",
                instrument_name=name,
                exchange_timestamp_ms=source_ms,
                payload=payload,
            )

    platform_pair(first_target + 1)
    for slot in range(1, 5):
        target = first_target + slot * CADENCE_SECONDS * 1_000
        refresh(target - 1)
        reference(target)
    close_target = first_target + 6 * CADENCE_SECONDS * 1_000
    profitable_close(close_target)
    second_entry_target = first_target + 7 * CADENCE_SECONDS * 1_000
    refresh(second_entry_target - 1)
    reference(second_entry_target)
    platform_pair(second_entry_target + 1)
    for slot in range(8, DUE_OPPORTUNITY_COUNT):
        target = first_target + slot * CADENCE_SECONDS * 1_000
        refresh(target - 1)
        reference(target)
    profitable_close(second_entry_target + 30 * 60_000)
    return tuple(events)


def run_synthetic_shadow(output: Path) -> dict[str, object]:
    if output.exists():
        raise ValueError("synthetic public-Shadow output must not already exist")
    decision_identity = runtime_source_identity(require_clean=False)
    outcome_identity = outcome_runtime_source_identity(require_clean=False)
    run_identity = run_runtime_source_identity(require_clean=False)
    environment = runtime_environment_identity()
    contract = build_run_contract(
        run_id="fixed-policy-public-shadow-synthetic",
        fact_provenance="synthetic",
        created_at="2026-07-23T00:00:00+00:00",
        decision_identity=decision_identity,
        outcome_identity=outcome_identity,
        run_identity=run_identity,
        environment=environment,
    )
    events = _synthetic_events()
    mutable_clock = [0]
    writer = PublicShadowJournalWriter(
        output,
        run_contract=contract,
        elapsed_ms=lambda: mutable_clock[0],
    )
    writer.commit_network_open_intent(
        network_attempt_ordinal=1,
        purpose="INITIAL_SETUP",
        pending_connection_generation=1,
        due_elapsed_ms=0,
        actual_elapsed_ms=0,
        timeout_ms=NETWORK_OPEN_TIMEOUT_SECONDS * 1_000,
    )
    writer.commit_network_connect_result(
        network_attempt_ordinal=1,
        purpose="INITIAL_SETUP",
        pending_connection_generation=1,
        actual_elapsed_ms=0,
        result="CONNECTED",
        error=None,
    )
    controller = _OnlineRunController(
        root=output,
        writer=writer,
        run_contract=contract,
        decision_identity=decision_identity,
        outcome_identity=outcome_identity,
        elapsed_ms=lambda: mutable_clock[0],
    )
    projector = RadarProjector()
    controller.attach_projector(projector)
    pending_probe: tuple[dict[str, object], int, int] | None = None
    pending_subscription: CanonicalEvent | None = None
    next_request_id = 100
    for event in events:
        mutable_clock[0] = event.collector_elapsed_ms
        is_probe_subscription = (
            pending_probe is not None
            and event.event_kind is EventKind.SUBSCRIPTION_START
            and _event_payload(event).get("stream") == "platform_state"
        )
        is_probe_status = (
            pending_probe is not None
            and pending_subscription is not None
            and event.event_kind is EventKind.PLATFORM_STATE
            and event.channel == "public/status"
        )
        if is_probe_subscription:
            assert pending_probe is not None
            obligation, attempt, acquisition = pending_probe
            controller.commit_probe_rpc_result(
                obligation,
                attempt=attempt,
                acquisition_ordinal=acquisition,
                request_id=next_request_id,
                method="public/subscribe",
                result="ACKNOWLEDGED",
                error=None,
                actual_elapsed_ms=mutable_clock[0],
            )
        elif pending_probe is not None and pending_subscription is None:
            raise RuntimeError("synthetic probe response was not the next canonical fact")
        elif pending_probe is not None and not is_probe_status:
            raise RuntimeError("synthetic status response was not the next canonical fact")
        if is_probe_status:
            assert pending_probe is not None
            obligation, attempt, acquisition = pending_probe
            controller.commit_probe_rpc_result(
                obligation,
                attempt=attempt,
                acquisition_ordinal=acquisition,
                request_id=next_request_id + 1,
                method="public/status",
                result="RECEIVED",
                error=None,
                actual_elapsed_ms=mutable_clock[0],
            )
        controller.before_event(event)
        controller.after_event(event, projector.ingest(event))
        if is_probe_subscription:
            pending_subscription = event
            writer.commit_control(
                "PLATFORM_STATUS_SEND_INTENT_COMMIT",
                {
                    "obligation_id": obligation["obligation_id"],
                    "attempt": attempt,
                    "connection_generation": obligation["connection_generation"],
                    "platform_acquisition_ordinal": acquisition,
                    "subscription_capture_seq": event.capture_seq,
                    "request_id": next_request_id + 1,
                    "method": "public/status",
                    "params": {},
                    "actual_elapsed_ms": mutable_clock[0],
                },
            )
        elif is_probe_status:
            assert pending_subscription is not None
            controller.finish_probe(
                obligation,
                attempt,
                state="PAIR_RECEIVED",
                request_id=next_request_id + 1,
                error=None,
                acquisition_ordinal=acquisition,
                subscription_capture_seq=pending_subscription.capture_seq,
                status_capture_seq=event.capture_seq,
            )
            controller.satisfy_probe(
                obligation,
                attempt=attempt,
                acquisition_ordinal=acquisition,
                subscription_event=pending_subscription,
                status_event=event,
            )
            pending_probe = None
            pending_subscription = None
            next_request_id += 2
        if pending_probe is None:
            due = controller.due_probe(
                now_elapsed_ms=mutable_clock[0],
                active_connection=True,
            )
            if due is not None:
                acquisition = controller.begin_probe(
                    due[0],
                    due[1],
                    request_id=next_request_id,
                )
                pending_probe = (due[0], due[1], acquisition)
    if pending_probe is not None:
        raise RuntimeError("synthetic run ended with an unfinished platform probe")
    if controller.origin_elapsed_ms is None or controller.seal_end_elapsed_ms is None:
        raise RuntimeError("synthetic run did not establish its fixed origin")
    mutable_clock[0] = controller.seal_end_elapsed_ms
    controller.advance_time(controller.seal_end_elapsed_ms)
    controller.due_probe(
        now_elapsed_ms=controller.seal_end_elapsed_ms,
        active_connection=False,
    )
    if controller.incomplete_reasons:
        raise RuntimeError(
            "synthetic online run is incomplete: "
            + ",".join(dict.fromkeys(controller.incomplete_reasons))
        )
    segment_digests = writer.seal_fact_segments(controller.seal_end_elapsed_ms)
    durable_events = PublicShadowJournalReader(output).read_committed_events()
    full_capture_digest = hashlib.sha256(
        b"".join(_encoded_event(event) for event in durable_events)
    ).hexdigest()
    exact_fact_seal = canonical_digest(
        {
            "run_id": contract["run_id"],
            "segment_manifest_digests": segment_digests,
            "final_capture_seq": writer.last_capture_seq,
            "full_capture_digest": full_capture_digest,
        }
    )
    composition = compose_run(
        durable_events,
        run_contract=contract,
        decision_identity=decision_identity,
        outcome_identity=outcome_identity,
        fact_seal_digest=exact_fact_seal,
    )
    if not _typed_equal(list(controller.records), list(composition.opportunities)):
        raise ValueError("synthetic online opportunities differ from sealed reconstruction")
    _persist_live_receipts(output, composition, writer)
    result = {
        "receipt_type": "FIXED_POLICY_PUBLIC_SHADOW_RESULT",
        "environment": "synthetic",
        "complete": True,
        "run_id": contract["run_id"],
        "run_contract_digest": canonical_digest(contract),
        "run_receipt_digest": composition.run_receipt["run_receipt_digest"],
        "fact_seal_digest": exact_fact_seal,
        "records": composition.full_capture_manifest.record_count,
        "origin_elapsed_ms": composition.origin_elapsed_ms,
        "seal_end_elapsed_ms": composition.seal_end_elapsed_ms,
        "accounting": canonical_value(composition.accounting),
        "decision_runtime_source_digest": decision_identity.runtime_source_digest,
        "outcome_runtime_source_digest": outcome_identity.runtime_source_digest,
        "run_runtime_source_digest": run_identity.runtime_source_digest,
        "runtime_environment_digest": environment.runtime_environment_digest,
        "external_source_attested": False,
        "attempt_selection_attested": False,
        "online_persistence_external_attested": False,
    }
    result["result_digest"] = canonical_digest(result)
    _write_json_fsynced(output / RUN_RESULT_PATH, result)
    writer.commit_artifact(
        artifact_type="FIXED_POLICY_PUBLIC_SHADOW_RESULT",
        relative_path=RUN_RESULT_PATH,
        artifact_digest=cast(str, result["result_digest"]),
    )
    writer.seal(
        composition.seal_end_elapsed_ms,
        complete=True,
        incomplete_reasons=(),
        final_bindings={
            "run_receipt_digest": composition.run_receipt["run_receipt_digest"],
            "result_digest": result["result_digest"],
            "fact_seal_digest": exact_fact_seal,
        },
    )
    PublicShadowJournalReader(output).verify()
    return result


def _persist_live_receipts(
    root: Path,
    composition: RunComposition,
    writer: PublicShadowJournalWriter,
) -> None:
    expected_entries = list(composition.entries)
    entry_index = 0
    for slot, receipt in enumerate(composition.decision_receipts):
        if receipt is None:
            continue
        decision_path = root / RECEIPTS_DIRECTORY / f"decision-slot-{slot:02d}.json"
        if not _typed_equal(
            _json_object(decision_path),
            decision_receipt_payload(receipt),
        ):
            raise ValueError("online Decision receipt differs from sealed reconstruction")
        if composition.summaries[slot].admission_class is AdmissionClass.ADMITTED:
            entry = expected_entries[entry_index]
            entry_path = root / RECEIPTS_DIRECTORY / f"entry-{entry_index:02d}.json"
            if not _typed_equal(_json_object(entry_path), entry_receipt_payload(entry)):
                raise ValueError("online Entry receipt differs from sealed reconstruction")
            entry_index += 1
    if entry_index != len(expected_entries):
        raise ValueError("online Entry receipt denominator changed")
    for index, outcome in enumerate(composition.outcomes):
        relative = f"{RECEIPTS_DIRECTORY}/outcome-{index:02d}.json"
        _write_json_fsynced(root / relative, outcome_receipt_payload(outcome))
        writer.commit_artifact(
            artifact_type="SHORT_VOL_OUTCOME_RECEIPT",
            relative_path=relative,
            artifact_digest=outcome.digest,
        )
    _write_json_fsynced(root / RUN_RECEIPT_PATH, composition.run_receipt)
    writer.commit_artifact(
        artifact_type=RUN_RECEIPT_TYPE,
        relative_path=RUN_RECEIPT_PATH,
        artifact_digest=cast(str, composition.run_receipt["run_receipt_digest"]),
    )


@dataclass(frozen=True, slots=True)
class _BufferedNetworkMessage:
    value: dict[str, object]
    received_at_ms: int
    elapsed_ms: int


class _ProbeResponseWaitError(RuntimeError):
    def __init__(
        self,
        error: BaseException,
        buffered: tuple[_BufferedNetworkMessage, ...],
    ) -> None:
        super().__init__(str(error))
        self.error = error
        self.buffered = buffered


def _wait_probe_response(
    connection: Connection,
    session: _OutcomeLiveSession,
    request_id: int,
    *,
    test_request_id: int,
) -> tuple[object, int, int, int, tuple[_BufferedNetworkMessage, ...]]:
    buffered: list[_BufferedNetworkMessage] = []
    try:
        while True:
            received = _message(connection, session, 10)
            message = received.value
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"Deribit WebSocket error: {message['error']}")
                return (
                    message.get("result"),
                    received.clock.received_at_ms,
                    received.clock.elapsed_ms,
                    test_request_id,
                    tuple(buffered),
                )
            buffered.append(
                _BufferedNetworkMessage(
                    value=dict(message),
                    received_at_ms=received.clock.received_at_ms,
                    elapsed_ms=received.clock.elapsed_ms,
                )
            )
    except Exception as error:
        raise _ProbeResponseWaitError(error, tuple(buffered)) from error


def _process_buffered_messages(
    connection: Connection,
    session: _OutcomeLiveSession,
    buffered: tuple[_BufferedNetworkMessage, ...],
    *,
    test_request_id: int,
) -> int:
    for received in buffered:
        test_request_id = _handle_message(
            connection,
            session,
            received.value,
            received_at_ms=received.received_at_ms,
            elapsed_ms=received.elapsed_ms,
            test_request_id=test_request_id,
        )
    return test_request_id


def _run_platform_probe(
    *,
    connection: Connection,
    session: _OutcomeLiveSession,
    controller: _OnlineRunController,
    obligation: dict[str, object],
    attempt: int,
    request_id: int,
    test_request_id: int,
) -> tuple[int, int]:
    acquisition_ordinal = controller.begin_probe(
        obligation,
        attempt,
        request_id=request_id,
    )
    active_request_id = request_id
    active_method = "public/subscribe"
    result_committed = False
    buffered: tuple[_BufferedNetworkMessage, ...] = ()
    try:
        _rpc(
            connection,
            request_id,
            "public/subscribe",
            {"channels": ["platform_state"]},
        )
        (
            result,
            subscription_received_at_ms,
            subscription_elapsed_ms,
            test_request_id,
            buffered,
        ) = _wait_probe_response(
            connection,
            session,
            request_id,
            test_request_id=test_request_id,
        )
        if not isinstance(result, list) or result != ["platform_state"]:
            raise RuntimeError("platform-only subscription was not accepted")
        controller.commit_probe_rpc_result(
            obligation,
            attempt=attempt,
            acquisition_ordinal=acquisition_ordinal,
            request_id=request_id,
            method="public/subscribe",
            result="ACKNOWLEDGED",
            error=None,
            actual_elapsed_ms=subscription_elapsed_ms,
        )
        result_committed = True
        test_request_id = _process_buffered_messages(
            connection,
            session,
            buffered,
            test_request_id=test_request_id,
        )
        buffered = ()
        subscription_event = session.record_outcome_platform_subscription_start(
            received_at_ms=subscription_received_at_ms,
            elapsed_ms=subscription_elapsed_ms,
            request_id=request_id,
            platform_acquisition_ordinal=acquisition_ordinal,
            obligation_id=cast(str, obligation["obligation_id"]),
            connection_generation=cast(int, obligation["connection_generation"]),
        )
        request_id += 1
        active_request_id = request_id
        active_method = "public/status"
        result_committed = False
        controller.writer.commit_control(
            "PLATFORM_STATUS_SEND_INTENT_COMMIT",
            {
                "obligation_id": obligation["obligation_id"],
                "attempt": attempt,
                "connection_generation": obligation["connection_generation"],
                "platform_acquisition_ordinal": acquisition_ordinal,
                "subscription_capture_seq": subscription_event.capture_seq,
                "request_id": request_id,
                "method": "public/status",
                "params": {},
                "actual_elapsed_ms": controller.elapsed_ms(),
            },
        )
        _rpc(connection, request_id, "public/status", {})
        (
            status_result,
            status_received_at_ms,
            status_elapsed_ms,
            test_request_id,
            buffered,
        ) = _wait_probe_response(
            connection,
            session,
            request_id,
            test_request_id=test_request_id,
        )
        controller.commit_probe_rpc_result(
            obligation,
            attempt=attempt,
            acquisition_ordinal=acquisition_ordinal,
            request_id=request_id,
            method="public/status",
            result="RECEIVED",
            error=None,
            actual_elapsed_ms=status_elapsed_ms,
        )
        result_committed = True
        test_request_id = _process_buffered_messages(
            connection,
            session,
            buffered,
            test_request_id=test_request_id,
        )
        buffered = ()
        status_event = session.record_platform(
            _object(status_result, "Deribit public status"),
            channel="public/status",
            received_at_ms=status_received_at_ms,
            elapsed_ms=status_elapsed_ms,
            acquisition_lineage={
                "request_id": request_id,
                "platform_acquisition_ordinal": acquisition_ordinal,
                "obligation_id": obligation["obligation_id"],
                "connection_generation": obligation["connection_generation"],
            },
        )
        if status_event is None:
            raise RuntimeError("platform status did not produce a canonical fact")
        controller.finish_probe(
            obligation,
            attempt,
            state="PAIR_RECEIVED",
            request_id=request_id,
            error=None,
            acquisition_ordinal=acquisition_ordinal,
            subscription_capture_seq=subscription_event.capture_seq,
            status_capture_seq=status_event.capture_seq,
        )
        controller.satisfy_probe(
            obligation,
            attempt=attempt,
            acquisition_ordinal=acquisition_ordinal,
            subscription_event=subscription_event,
            status_event=status_event,
        )
    except Exception as error:
        wait_error = error if isinstance(error, _ProbeResponseWaitError) else None
        actual_error = wait_error.error if wait_error is not None else error
        if wait_error is not None:
            buffered = wait_error.buffered
        if not result_committed:
            controller.commit_probe_rpc_result(
                obligation,
                attempt=attempt,
                acquisition_ordinal=acquisition_ordinal,
                request_id=active_request_id,
                method=active_method,
                result="FAILED",
                error=type(actual_error).__name__,
                actual_elapsed_ms=controller.elapsed_ms(),
            )
        test_request_id = _process_buffered_messages(
            connection,
            session,
            buffered,
            test_request_id=test_request_id,
        )
        controller.finish_probe(
            obligation,
            attempt,
            state="SEND_OR_RESPONSE_FAILED",
            request_id=active_request_id,
            error=type(actual_error).__name__,
            acquisition_ordinal=acquisition_ordinal,
        )
        if isinstance(actual_error, (ConnectionClosed, OSError, TimeoutError)):
            raise actual_error from error
    return request_id + 1, test_request_id


def _run_connection_bootstrap(
    *,
    connection: Connection,
    session: _OutcomeLiveSession,
    controller: _OnlineRunController,
    channels: tuple[str, ...],
) -> int:
    _rpc(connection, 1, "public/set_heartbeat", {"interval": HEARTBEAT_SECONDS})
    heartbeat_result, test_request_id, _heartbeat_clock = _wait_result(
        connection,
        session,
        1,
        test_request_id=1_000,
    )
    if heartbeat_result != "ok":
        raise RuntimeError("Deribit public heartbeat was not accepted")
    probe = controller.due_probe(
        now_elapsed_ms=controller.elapsed_ms(),
        active_connection=True,
    )
    bootstrap_obligation: dict[str, object] | None = None
    bootstrap_attempt: int | None = None
    acquisition_ordinal: int | None = None
    if probe is not None:
        if probe[0]["attempt_zero_mode"] != "RECONNECT_BOOTSTRAP" or probe[1] != 0:
            raise RuntimeError("connection bootstrap encountered a non-bootstrap probe")
        bootstrap_obligation, bootstrap_attempt = probe
        acquisition_ordinal = controller.begin_probe(
            bootstrap_obligation,
            bootstrap_attempt,
            request_id=2,
            params={"channels": list(channels)},
        )
    _rpc(connection, 2, "public/subscribe", {"channels": list(channels)})
    if bootstrap_obligation is None:
        subscription_result, test_request_id, subscription_clock = _wait_result(
            connection,
            session,
            2,
            test_request_id=test_request_id,
        )
        subscription_received_at_ms = subscription_clock.received_at_ms
        subscription_elapsed_ms = subscription_clock.elapsed_ms
    else:
        assert bootstrap_attempt is not None and acquisition_ordinal is not None
        try:
            (
                subscription_result,
                subscription_received_at_ms,
                subscription_elapsed_ms,
                test_request_id,
                buffered,
            ) = _wait_probe_response(
                connection,
                session,
                2,
                test_request_id=test_request_id,
            )
        except _ProbeResponseWaitError as wait_error:
            controller.commit_probe_rpc_result(
                bootstrap_obligation,
                attempt=bootstrap_attempt,
                acquisition_ordinal=acquisition_ordinal,
                request_id=2,
                method="public/subscribe",
                result="FAILED",
                error=type(wait_error.error).__name__,
                actual_elapsed_ms=controller.elapsed_ms(),
            )
            _process_buffered_messages(
                connection,
                session,
                wait_error.buffered,
                test_request_id=test_request_id,
            )
            controller.finish_probe(
                bootstrap_obligation,
                bootstrap_attempt,
                state="SEND_OR_RESPONSE_FAILED",
                request_id=2,
                error=type(wait_error.error).__name__,
                acquisition_ordinal=acquisition_ordinal,
            )
            raise wait_error.error from wait_error
        controller.commit_probe_rpc_result(
            bootstrap_obligation,
            attempt=bootstrap_attempt,
            acquisition_ordinal=acquisition_ordinal,
            request_id=2,
            method="public/subscribe",
            result="ACKNOWLEDGED",
            error=None,
            actual_elapsed_ms=subscription_elapsed_ms,
        )
        test_request_id = _process_buffered_messages(
            connection,
            session,
            buffered,
            test_request_id=test_request_id,
        )
    if not isinstance(subscription_result, list) or set(
        str(item) for item in subscription_result
    ) != set(channels):
        raise RuntimeError("Deribit public subscriptions were not fully accepted")
    subscription_events = session.record_subscription_start(
        received_at_ms=subscription_received_at_ms,
        elapsed_ms=subscription_elapsed_ms,
        platform_acquisition_lineage=(
            {
                "request_id": 2,
                "platform_acquisition_ordinal": acquisition_ordinal,
                "obligation_id": bootstrap_obligation["obligation_id"],
                "connection_generation": bootstrap_obligation["connection_generation"],
            }
            if bootstrap_obligation is not None
            else None
        ),
    )
    platform_subscription = subscription_events[-1]
    if bootstrap_obligation is not None:
        controller.writer.commit_control(
            "PLATFORM_STATUS_SEND_INTENT_COMMIT",
            {
                "obligation_id": bootstrap_obligation["obligation_id"],
                "attempt": bootstrap_attempt,
                "connection_generation": bootstrap_obligation["connection_generation"],
                "platform_acquisition_ordinal": acquisition_ordinal,
                "subscription_capture_seq": platform_subscription.capture_seq,
                "request_id": 3,
                "method": "public/status",
                "params": {},
                "actual_elapsed_ms": controller.elapsed_ms(),
            },
        )
    _rpc(connection, 3, "public/status", {})
    if bootstrap_obligation is None:
        status_result, test_request_id, status_clock = _wait_result(
            connection,
            session,
            3,
            test_request_id=test_request_id,
        )
        status_received_at_ms = status_clock.received_at_ms
        status_elapsed_ms = status_clock.elapsed_ms
    else:
        assert bootstrap_attempt is not None and acquisition_ordinal is not None
        try:
            (
                status_result,
                status_received_at_ms,
                status_elapsed_ms,
                test_request_id,
                buffered,
            ) = _wait_probe_response(
                connection,
                session,
                3,
                test_request_id=test_request_id,
            )
        except _ProbeResponseWaitError as wait_error:
            controller.commit_probe_rpc_result(
                bootstrap_obligation,
                attempt=bootstrap_attempt,
                acquisition_ordinal=acquisition_ordinal,
                request_id=3,
                method="public/status",
                result="FAILED",
                error=type(wait_error.error).__name__,
                actual_elapsed_ms=controller.elapsed_ms(),
            )
            _process_buffered_messages(
                connection,
                session,
                wait_error.buffered,
                test_request_id=test_request_id,
            )
            controller.finish_probe(
                bootstrap_obligation,
                bootstrap_attempt,
                state="SEND_OR_RESPONSE_FAILED",
                request_id=3,
                error=type(wait_error.error).__name__,
                acquisition_ordinal=acquisition_ordinal,
            )
            raise wait_error.error from wait_error
        controller.commit_probe_rpc_result(
            bootstrap_obligation,
            attempt=bootstrap_attempt,
            acquisition_ordinal=acquisition_ordinal,
            request_id=3,
            method="public/status",
            result="RECEIVED",
            error=None,
            actual_elapsed_ms=status_elapsed_ms,
        )
        test_request_id = _process_buffered_messages(
            connection,
            session,
            buffered,
            test_request_id=test_request_id,
        )
    status_event = session.record_platform(
        _object(status_result, "Deribit public status"),
        channel="public/status",
        received_at_ms=status_received_at_ms,
        elapsed_ms=status_elapsed_ms,
        acquisition_lineage=(
            {
                "request_id": 3,
                "platform_acquisition_ordinal": acquisition_ordinal,
                "obligation_id": bootstrap_obligation["obligation_id"],
                "connection_generation": bootstrap_obligation["connection_generation"],
            }
            if bootstrap_obligation is not None
            else None
        ),
    )
    if status_event is None:
        raise RuntimeError("connection bootstrap status produced no canonical fact")
    if bootstrap_obligation is not None:
        assert bootstrap_attempt is not None and acquisition_ordinal is not None
        controller.finish_probe(
            bootstrap_obligation,
            bootstrap_attempt,
            state="RECONNECT_BOOTSTRAP_PAIR_RECEIVED",
            request_id=3,
            error=None,
            acquisition_ordinal=acquisition_ordinal,
            subscription_capture_seq=platform_subscription.capture_seq,
            status_capture_seq=status_event.capture_seq,
        )
        controller.satisfy_probe(
            bootstrap_obligation,
            attempt=bootstrap_attempt,
            acquisition_ordinal=acquisition_ordinal,
            subscription_event=platform_subscription,
            status_event=status_event,
        )
    return test_request_id


def _incomplete_public_run(
    *,
    output: Path,
    writer: PublicShadowJournalWriter,
    controller: _OnlineRunController,
    elapsed_ms: int,
    reasons: tuple[str, ...],
    contract: dict[str, object],
    invocation_started_at: datetime | None = None,
    network_attempts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    prefix_end_elapsed_ms = (
        controller.seal_end_elapsed_ms
        if controller.seal_end_elapsed_ms is not None
        and elapsed_ms >= controller.seal_end_elapsed_ms
        else min(elapsed_ms, INITIAL_SETUP_TIMEOUT_SECONDS * 1_000)
    )
    writer.seal_fact_segments(prefix_end_elapsed_ms)
    result: dict[str, object] = {
        "receipt_type": "FIXED_POLICY_PUBLIC_SHADOW_INCOMPLETE_RESULT",
        "environment": "production_public",
        "complete": False,
        "run_id": contract["run_id"],
        "run_contract_digest": canonical_digest(contract),
        "last_durable_capture_seq": writer.last_capture_seq,
        "recorded_opportunity_count": sum(item is not None for item in controller._records),
        "segment_manifest_digests": list(writer.segment_manifest_digests),
        "opportunity_journal_head": writer.opportunity_head,
        "incomplete_state": controller.incomplete_state(),
        "incomplete_reasons": list(dict.fromkeys(reasons)),
        "decision_runtime_source_digest": contract.get("decision_runtime_source_digest"),
        "outcome_runtime_source_digest": contract.get("outcome_runtime_source_digest"),
        "run_runtime_source_digest": contract.get("run_runtime_source_digest"),
        "runtime_environment_digest": contract.get("runtime_environment_digest"),
        "external_source_attested": False,
        "attempt_selection_attested": False,
        "online_persistence_external_attested": False,
    }
    result["result_digest"] = canonical_digest(result)
    _write_json_fsynced(output / RUN_RESULT_PATH, result)
    writer.commit_artifact(
        artifact_type="FIXED_POLICY_PUBLIC_SHADOW_INCOMPLETE_RESULT",
        relative_path=RUN_RESULT_PATH,
        artifact_digest=cast(str, result["result_digest"]),
    )
    started_at = invocation_started_at or datetime.fromisoformat(cast(str, contract["created_at"]))
    invocation: dict[str, object] = {
        "receipt_type": "FIXED_POLICY_PUBLIC_SHADOW_INCOMPLETE_INVOCATION_WITNESS",
        "run_id": contract["run_id"],
        "run_contract_digest": canonical_digest(contract),
        "invocation_started_at": started_at.isoformat(),
        "invocation_finished_at": datetime.now(UTC).isoformat(),
        "invocation_elapsed_ms": elapsed_ms,
        "requested_setup_deadline_elapsed_ms": INITIAL_SETUP_TIMEOUT_SECONDS * 1_000,
        "requested_hard_stop_elapsed_ms": controller.seal_end_elapsed_ms,
        "origin_elapsed_ms": controller.origin_elapsed_ms,
        "network_attempts": list(network_attempts or ()),
        "segment_manifest_digests": list(writer.segment_manifest_digests),
        "opportunity_journal_head": writer.opportunity_head,
        "terminal_causal_commit_digest_before_witness": writer.causal_head,
        "result_digest": result["result_digest"],
        "incomplete_reasons": result["incomplete_reasons"],
        "online_persistence_external_attested": False,
        "external_source_attested": False,
        "attempt_selection_attested": False,
    }
    invocation["invocation_digest"] = canonical_digest(invocation)
    _write_json_fsynced(output / PROCESS_WITNESS_PATH, invocation)
    writer.commit_artifact(
        artifact_type="FIXED_POLICY_PUBLIC_SHADOW_INCOMPLETE_INVOCATION_WITNESS",
        relative_path=PROCESS_WITNESS_PATH,
        artifact_digest=cast(str, invocation["invocation_digest"]),
    )
    writer.interrupt(
        tuple(cast(list[str], result["incomplete_reasons"])),
        final_bindings={
            "result_digest": result["result_digest"],
            "invocation_digest": invocation["invocation_digest"],
        },
    )
    PublicShadowJournalReader(output).verify(allow_incomplete=True)
    return result


def run_public_shadow_capture(output: Path) -> dict[str, object]:
    """Run the one authorized production-public schedule without retaining its full tape."""

    if output.exists():
        raise ValueError("production-public Shadow output must not already exist")
    decision_identity = runtime_source_identity(require_clean=True)
    outcome_identity = outcome_runtime_source_identity(require_clean=True)
    run_identity = run_runtime_source_identity(require_clean=True)
    environment = runtime_environment_identity()
    invocation_started_at = datetime.now(UTC)
    invocation_started_ns = time.monotonic_ns()

    def elapsed_ms() -> int:
        return (time.monotonic_ns() - invocation_started_ns) // 1_000_000

    run_id = (
        "fixed-policy-public-shadow-"
        + canonical_digest(
            {
                "created_at": invocation_started_at.isoformat(),
                "git_commit_sha": run_identity.git_commit_sha,
                "run_runtime_source_digest": run_identity.runtime_source_digest,
            }
        )[:20]
    )
    contract = build_run_contract(
        run_id=run_id,
        fact_provenance="production_public",
        created_at=invocation_started_at.isoformat(),
        decision_identity=decision_identity,
        outcome_identity=outcome_identity,
        run_identity=run_identity,
        environment=environment,
    )
    writer = PublicShadowJournalWriter(
        output,
        run_contract=contract,
        elapsed_ms=elapsed_ms,
    )
    controller = _OnlineRunController(
        root=output,
        writer=writer,
        run_contract=contract,
        decision_identity=decision_identity,
        outcome_identity=outcome_identity,
        elapsed_ms=elapsed_ms,
    )
    session = _OutcomeLiveSession(
        before_event=controller.before_event,
        after_event=controller.after_event,
        retain_events=False,
        started_monotonic_ns=invocation_started_ns,
    )
    controller.attach_projector(session.projector)
    network_attempts: list[dict[str, object]] = []
    try:
        input_contract = DecisionInputContract()
        option_catalog = _public_result(
            "get_instruments",
            {"currency": "USDC", "kind": "option", "expired": "false"},
            session,
        )
        future_catalog = _public_result(
            "get_instruments",
            {"currency": "USDC", "kind": "future", "expired": "false"},
            session,
        )
        catalog_market_at_ms = max(
            option_catalog.server_at_ms,
            future_catalog.server_at_ms,
        )
        selected = select_btc_usdc_catalog(
            _instrument_rows(option_catalog.result),
            _instrument_rows(future_catalog.result),
            as_of_ms=catalog_market_at_ms,
            validity_buffer_ms=input_contract.catalog_max_age_ms,
        )
        catalog_clock = session.clock_sample()
        session.record_catalog_generation(
            selected,
            source_at_ms=catalog_market_at_ms,
            received_at_ms=catalog_clock.received_at_ms,
            elapsed_ms=catalog_clock.elapsed_ms,
        )
    except Exception as error:
        return _incomplete_public_run(
            output=output,
            writer=writer,
            controller=controller,
            elapsed_ms=elapsed_ms(),
            reasons=(f"INITIAL_CATALOG_{type(error).__name__}",),
            contract=contract,
            invocation_started_at=invocation_started_at,
            network_attempts=network_attempts,
        )
    option_names = tuple(str(row["instrument_name"]) for row in selected[1:])
    channels = (
        f"ticker.{REFERENCE}.agg2",
        f"trades.{REFERENCE}.agg2",
        "platform_state",
        *(f"ticker.{name}.agg2" for name in option_names),
    )
    network_attempt_ordinal = 0
    pending_generation = 1
    established_generation = 0
    next_network_due_ms = elapsed_ms()
    next_catalog_refresh_ms = elapsed_ms() + input_contract.catalog_refresh_seconds * 1_000
    reconnect_reason_recorded = False
    while True:
        now = elapsed_ms()
        controller.advance_time(now)
        if controller.origin_elapsed_ms is None:
            deadline_ms = INITIAL_SETUP_TIMEOUT_SECONDS * 1_000
        else:
            assert controller.seal_end_elapsed_ms is not None
            deadline_ms = controller.seal_end_elapsed_ms
        if now >= deadline_ms:
            controller.due_probe(
                now_elapsed_ms=deadline_ms,
                active_connection=False,
            )
            writer.advance_segments_before(deadline_ms)
            break
        if now < next_network_due_ms:
            controller.due_probe(
                now_elapsed_ms=now,
                active_connection=False,
            )
            writer.advance_segments_before(now)
            time.sleep(min(0.2, (next_network_due_ms - now) / 1_000))
            continue
        network_attempt_ordinal += 1
        purpose = "INITIAL_SETUP" if established_generation == 0 else "RECONNECT"
        intent_elapsed = elapsed_ms()
        remaining_ms = deadline_ms - intent_elapsed
        if remaining_ms <= 0:
            break
        dispatch_latency_ms = intent_elapsed - next_network_due_ms
        if dispatch_latency_ms >= MAXIMUM_NETWORK_RETRY_DISPATCH_LATENCY_MS:
            controller.incomplete_reasons.append("NETWORK_RETRY_DISPATCH_LATE")
        effective_timeout_ms = min(
            NETWORK_OPEN_TIMEOUT_SECONDS * 1_000,
            remaining_ms,
        )
        writer.commit_network_open_intent(
            network_attempt_ordinal=network_attempt_ordinal,
            purpose=purpose,
            pending_connection_generation=pending_generation,
            due_elapsed_ms=next_network_due_ms,
            actual_elapsed_ms=intent_elapsed,
            timeout_ms=effective_timeout_ms,
        )
        attempt: dict[str, object] = {
            "network_attempt_ordinal": network_attempt_ordinal,
            "purpose": purpose,
            "pending_connection_generation": pending_generation,
            "due_elapsed_ms": next_network_due_ms,
            "actual_intent_elapsed_ms": intent_elapsed,
            "effective_timeout_ms": effective_timeout_ms,
            "dispatch_latency_ms": dispatch_latency_ms,
            "retry_dispatch_breach": (
                dispatch_latency_ms >= MAXIMUM_NETWORK_RETRY_DISPATCH_LATENCY_MS
            ),
        }
        attempt_connected = False
        try:
            with connect(
                WEBSOCKET_URL,
                open_timeout=effective_timeout_ms / 1_000,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=20,
                max_size=None,
                max_queue=1_024,
                proxy=None,
            ) as connection:
                result_elapsed = elapsed_ms()
                writer.commit_network_connect_result(
                    network_attempt_ordinal=network_attempt_ordinal,
                    purpose=purpose,
                    pending_connection_generation=pending_generation,
                    actual_elapsed_ms=result_elapsed,
                    result="CONNECTED",
                    error=None,
                )
                attempt.update(
                    {
                        "actual_result_elapsed_ms": result_elapsed,
                        "result": "CONNECTED",
                        "error": None,
                    }
                )
                network_attempts.append(attempt)
                attempt_connected = True
                established_generation = pending_generation
                controller.connection_generation = established_generation
                reconnect_reason_recorded = False
                test_request_id = _run_connection_bootstrap(
                    connection=connection,
                    session=session,
                    controller=controller,
                    channels=channels,
                )
                request_id = 10
                while True:
                    now = elapsed_ms()
                    controller.advance_time(now)
                    hard_end = controller.seal_end_elapsed_ms
                    active_deadline = (
                        hard_end if hard_end is not None else INITIAL_SETUP_TIMEOUT_SECONDS * 1_000
                    )
                    if now >= active_deadline:
                        break
                    probe = controller.due_probe(
                        now_elapsed_ms=now,
                        active_connection=True,
                    )
                    if probe is not None:
                        request_id, test_request_id = _run_platform_probe(
                            connection=connection,
                            session=session,
                            controller=controller,
                            obligation=probe[0],
                            attempt=probe[1],
                            request_id=request_id,
                            test_request_id=test_request_id,
                        )
                        continue
                    writer.advance_segments_before(now)
                    if now >= next_catalog_refresh_ms:
                        option_names, request_id, test_request_id = _refresh_catalog(
                            connection,
                            session,
                            current_option_names=option_names,
                            request_id=request_id,
                            test_request_id=test_request_id,
                            input_contract=input_contract,
                        )
                        channels = (
                            f"ticker.{REFERENCE}.agg2",
                            f"trades.{REFERENCE}.agg2",
                            "platform_state",
                            *(f"ticker.{name}.agg2" for name in option_names),
                        )
                        next_catalog_refresh_ms += input_contract.catalog_refresh_seconds * 1_000
                        continue
                    try:
                        received = _message(
                            connection,
                            session,
                            min(1.0, (active_deadline - now) / 1_000),
                        )
                    except TimeoutError:
                        continue
                    if received.clock.elapsed_ms >= active_deadline:
                        break
                    test_request_id = _handle_message(
                        connection,
                        session,
                        received.value,
                        received_at_ms=received.clock.received_at_ms,
                        elapsed_ms=received.clock.elapsed_ms,
                        test_request_id=test_request_id,
                    )
                if elapsed_ms() >= active_deadline:
                    break
        except _HardCutoffReached:
            break
        except (ConnectionClosed, InvalidStatus, OSError, TimeoutError) as error:
            result_elapsed = elapsed_ms()
            controller.fail_dispatching_probes(type(error).__name__)
            if not attempt_connected:
                writer.commit_network_connect_result(
                    network_attempt_ordinal=network_attempt_ordinal,
                    purpose=purpose,
                    pending_connection_generation=pending_generation,
                    actual_elapsed_ms=result_elapsed,
                    result="FAILED",
                    error=type(error).__name__,
                )
                attempt.update(
                    {
                        "actual_result_elapsed_ms": result_elapsed,
                        "result": "FAILED",
                        "error": type(error).__name__,
                    }
                )
                network_attempts.append(attempt)
            if established_generation > 0 and not reconnect_reason_recorded:
                reconnect_clock = session.clock_sample()
                pending_generation = established_generation + 1
                controller.connection_generation = pending_generation
                session.record_reconnect(
                    type(error).__name__,
                    received_at_ms=reconnect_clock.received_at_ms,
                    elapsed_ms=reconnect_clock.elapsed_ms,
                )
                reconnect_reason_recorded = True
                next_network_due_ms = reconnect_clock.elapsed_ms
            else:
                next_network_due_ms = result_elapsed + NETWORK_RETRY_BACKOFF_SECONDS * 1_000
            controller.due_probe(
                now_elapsed_ms=result_elapsed,
                active_connection=False,
            )
            writer.advance_segments_before(result_elapsed)
            if (
                controller.origin_elapsed_ms is None
                and "INITIAL_CONNECTION_ENDED_BEFORE_ORIGIN" in controller.incomplete_reasons
            ):
                break
            continue
        next_network_due_ms = elapsed_ms()
        if controller.origin_elapsed_ms is None and controller.incomplete_reasons:
            break
    if controller.origin_elapsed_ms is None:
        reasons = tuple(
            dict.fromkeys((*controller.incomplete_reasons, "INITIAL_ORIGIN_NOT_ESTABLISHED"))
        )
        return _incomplete_public_run(
            output=output,
            writer=writer,
            controller=controller,
            elapsed_ms=elapsed_ms(),
            reasons=reasons,
            contract=contract,
            invocation_started_at=invocation_started_at,
            network_attempts=network_attempts,
        )
    assert controller.seal_end_elapsed_ms is not None
    controller.advance_time(controller.seal_end_elapsed_ms)
    controller.due_probe(
        now_elapsed_ms=controller.seal_end_elapsed_ms,
        active_connection=False,
    )
    if any(item is None for item in controller._records):
        controller.incomplete_reasons.append("MISSING_DUE_OPPORTUNITY")
    writer.seal_fact_segments(controller.seal_end_elapsed_ms)
    durable_events = PublicShadowJournalReader(output).read_committed_events()
    exact_fact_seal = canonical_digest(
        {
            "run_id": contract["run_id"],
            "segment_manifest_digests": writer.segment_manifest_digests,
            "final_capture_seq": writer.last_capture_seq,
            "full_capture_digest": hashlib.sha256(
                b"".join(_encoded_event(event) for event in durable_events)
            ).hexdigest(),
        }
    )
    composition = compose_run(
        durable_events,
        run_contract=contract,
        decision_identity=decision_identity,
        outcome_identity=outcome_identity,
        fact_seal_digest=exact_fact_seal,
        require_complete=False,
    )
    if not _typed_equal(list(controller.records), list(composition.opportunities)):
        raise ValueError("online opportunity journal differs from sealed reconstruction")
    if composition.accounting.maturity_counts[MaturityClass.IMMATURE_UNKNOWN.value]:
        controller.incomplete_reasons.append("IMMATURE_OUTCOME_AT_SEAL")
    if controller.incomplete_reasons:
        return _incomplete_public_run(
            output=output,
            writer=writer,
            controller=controller,
            elapsed_ms=controller.seal_end_elapsed_ms,
            reasons=tuple(dict.fromkeys(controller.incomplete_reasons)),
            contract=contract,
            invocation_started_at=invocation_started_at,
            network_attempts=network_attempts,
        )
    _persist_live_receipts(output, composition, writer)
    invocation_finished_at = datetime.now(UTC)
    invocation: dict[str, object] = {
        "receipt_type": "FIXED_POLICY_PUBLIC_SHADOW_INVOCATION_WITNESS",
        "run_id": contract["run_id"],
        "run_contract_digest": canonical_digest(contract),
        "invocation_started_at": invocation_started_at.isoformat(),
        "invocation_finished_at": invocation_finished_at.isoformat(),
        "invocation_elapsed_ms": elapsed_ms(),
        "requested_setup_deadline_elapsed_ms": INITIAL_SETUP_TIMEOUT_SECONDS * 1_000,
        "requested_hard_stop_elapsed_ms": controller.seal_end_elapsed_ms,
        "origin_elapsed_ms": controller.origin_elapsed_ms,
        "seal_end_elapsed_ms": controller.seal_end_elapsed_ms,
        "network_attempts": network_attempts,
        "opportunity_commit_latencies_ms": (controller.opportunity_commit_latencies_ms),
        "segment_manifest_digests": list(writer.segment_manifest_digests),
        "opportunity_journal_head": writer.opportunity_head,
        "terminal_causal_commit_digest_before_witness": writer.causal_head,
        "run_receipt_digest": composition.run_receipt["run_receipt_digest"],
        "git_commit_sha": run_identity.git_commit_sha,
        "decision_runtime_source_digest": decision_identity.runtime_source_digest,
        "outcome_runtime_source_digest": outcome_identity.runtime_source_digest,
        "run_runtime_source_digest": run_identity.runtime_source_digest,
        "runtime_environment_digest": environment.runtime_environment_digest,
        "external_source_attested": False,
        "attempt_selection_attested": False,
        "online_persistence_external_attested": False,
    }
    invocation["invocation_digest"] = canonical_digest(invocation)
    _write_json_fsynced(output / PROCESS_WITNESS_PATH, invocation)
    writer.commit_artifact(
        artifact_type="FIXED_POLICY_PUBLIC_SHADOW_INVOCATION_WITNESS",
        relative_path=PROCESS_WITNESS_PATH,
        artifact_digest=cast(str, invocation["invocation_digest"]),
    )
    result: dict[str, object] = {
        "receipt_type": "FIXED_POLICY_PUBLIC_SHADOW_RESULT",
        "environment": "production_public",
        "complete": True,
        "run_id": contract["run_id"],
        "run_contract_digest": canonical_digest(contract),
        "run_receipt_digest": composition.run_receipt["run_receipt_digest"],
        "invocation_digest": invocation["invocation_digest"],
        "fact_seal_digest": exact_fact_seal,
        "records": composition.full_capture_manifest.record_count,
        "origin_elapsed_ms": composition.origin_elapsed_ms,
        "seal_end_elapsed_ms": composition.seal_end_elapsed_ms,
        "accounting": canonical_value(composition.accounting),
        "incomplete_reasons": [],
        "decision_runtime_source_digest": decision_identity.runtime_source_digest,
        "outcome_runtime_source_digest": outcome_identity.runtime_source_digest,
        "run_runtime_source_digest": run_identity.runtime_source_digest,
        "runtime_environment_digest": environment.runtime_environment_digest,
        "external_source_attested": False,
        "attempt_selection_attested": False,
        "online_persistence_external_attested": False,
    }
    result["result_digest"] = canonical_digest(result)
    _write_json_fsynced(output / RUN_RESULT_PATH, result)
    writer.commit_artifact(
        artifact_type="FIXED_POLICY_PUBLIC_SHADOW_RESULT",
        relative_path=RUN_RESULT_PATH,
        artifact_digest=cast(str, result["result_digest"]),
    )
    writer.seal(
        composition.seal_end_elapsed_ms,
        complete=True,
        incomplete_reasons=(),
        final_bindings={
            "run_receipt_digest": composition.run_receipt["run_receipt_digest"],
            "invocation_digest": invocation["invocation_digest"],
            "result_digest": result["result_digest"],
            "fact_seal_digest": exact_fact_seal,
        },
    )
    PublicShadowJournalReader(output).verify()
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _static_verify_accepted_outcome_bundle(
    bundle: Path,
    *,
    archive: Path,
) -> dict[str, object]:
    expected_archive_sha256 = "c3099dfa62575a66854f8d66f1c5a2d0c9701bb445b7ac91a27f7db56e56bcd3"
    if not bundle.is_dir() or not archive.is_file():
        raise ValueError("accepted Outcome Truth bundle or archive is missing")
    if _sha256_file(archive) != expected_archive_sha256:
        raise ValueError("accepted Outcome Truth archive identity changed")
    sidecar = Path(str(archive) + ".sha256")
    if (
        not sidecar.is_file()
        or sidecar.read_text(encoding="utf-8").strip()
        != f"{expected_archive_sha256}  {archive.name}"
    ):
        raise ValueError("accepted Outcome Truth archive sidecar changed")
    checksum_path = bundle / "SHA256SUMS"
    expected_paths = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    checksum_paths: set[str] = set()
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        target = bundle / relative
        if (
            not separator
            or relative in checksum_paths
            or relative not in expected_paths
            or not target.is_file()
            or _sha256_file(target) != digest
        ):
            raise ValueError("accepted Outcome Truth checksum coverage changed")
        checksum_paths.add(relative)
    if checksum_paths != expected_paths:
        raise ValueError("accepted Outcome Truth checksum coverage is incomplete")
    manifest = _json_object(bundle / "BUNDLE_MANIFEST.json")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("accepted Outcome Truth bundle manifest is invalid")
    manifest_paths: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, dict):
            raise ValueError("accepted Outcome Truth bundle artifact is invalid")
        artifact = cast(dict[str, object], raw)
        relative_path = artifact.get("path")
        if not isinstance(relative_path, str) or relative_path in manifest_paths:
            raise ValueError("accepted Outcome Truth artifact path changed")
        target = bundle / relative_path
        if (
            relative_path not in expected_paths - {"BUNDLE_MANIFEST.json"}
            or artifact.get("bytes") != target.stat().st_size
            or artifact.get("sha256") != _sha256_file(target)
        ):
            raise ValueError("accepted Outcome Truth artifact identity changed")
        manifest_paths.add(relative_path)
    if manifest_paths != expected_paths - {"BUNDLE_MANIFEST.json"}:
        raise ValueError("accepted Outcome Truth manifest coverage is incomplete")
    from radar_runtime.outcome_bundle import _report

    synthetic = _json_object(bundle / "synthetic/run/result.json")
    synthetic_replay = _json_object(bundle / "synthetic/replay/replay.json")
    public = _json_object(bundle / "production-public/run/result.json")
    public_replay = _json_object(bundle / "production-public/replay/replay.json")
    public_invocation = _json_object(bundle / "production-public/run/collector-invocation.json")
    generated_at = manifest.get("generated_at")
    if not isinstance(generated_at, str) or (bundle / "ACCEPTANCE.zh-CN.md").read_text(
        encoding="utf-8"
    ) != _report(
        synthetic,
        synthetic_replay,
        public,
        public_replay,
        public_invocation,
        generated_at=generated_at,
    ):
        raise ValueError("accepted Outcome Truth canonical report changed")
    archived: dict[str, tuple[int, str]] = {}
    with tarfile.open(archive, mode="r:gz") as source:
        for member in source.getmembers():
            member_path = PurePosixPath(member.name)
            if (
                not member.isfile()
                or member_path.is_absolute()
                or ".." in member_path.parts
                or member.name in archived
            ):
                raise ValueError("accepted Outcome Truth archive member is invalid")
            handle = source.extractfile(member)
            if handle is None:
                raise ValueError("accepted Outcome Truth archive member is unreadable")
            data = handle.read()
            archived[member.name] = (len(data), hashlib.sha256(data).hexdigest())
    expected_archive_members = {
        f"{bundle.name}/{path.relative_to(bundle).as_posix()}": (
            path.stat().st_size,
            _sha256_file(path),
        )
        for path in bundle.rglob("*")
        if path.is_file()
    }
    if archived != expected_archive_members:
        raise ValueError("accepted Outcome Truth archive contents changed")
    return {
        "archive_sha256": expected_archive_sha256,
        "checksum_entry_count": len(checksum_paths),
        "bundle_manifest_sha256": _sha256_file(bundle / "BUNDLE_MANIFEST.json"),
        "acceptance_report_sha256": _sha256_file(bundle / "ACCEPTANCE.zh-CN.md"),
        "synthetic": synthetic,
        "public": public,
    }


def _semantic_projection(value: object) -> object:
    excluded = {
        "git_commit_sha",
        "outcome_runtime_git_commit_sha",
        "replay_git_commit_sha",
        "runtime_source_id",
        "outcome_runtime_source_id",
        "decision_runtime_source_id",
        "runtime_source_dirty_paths",
        "collector_invocation_digest",
    }
    if isinstance(value, dict):
        return {
            key: _semantic_projection(item)
            for key, item in sorted(value.items())
            if key not in excluded and not key.endswith("_digest") and not key.endswith("_sha256")
        }
    if isinstance(value, list):
        return [_semantic_projection(item) for item in value]
    return value


def _semantic_drift_paths(
    expected: object,
    observed: object,
    *,
    prefix: str = "",
) -> list[str]:
    if type(expected) is not type(observed):
        return [prefix or "<root>"]
    if isinstance(expected, dict) and isinstance(observed, dict):
        paths: list[str] = []
        for key in sorted(set(expected) | set(observed)):
            child = f"{prefix}.{key}" if prefix else key
            if key not in expected or key not in observed:
                paths.append(child)
            else:
                paths.extend(
                    _semantic_drift_paths(
                        expected[key],
                        observed[key],
                        prefix=child,
                    )
                )
        return paths
    if isinstance(expected, list) and isinstance(observed, list):
        if len(expected) != len(observed):
            return [prefix or "<root>"]
        paths = []
        for index, (left, right) in enumerate(zip(expected, observed, strict=True)):
            paths.extend(
                _semantic_drift_paths(
                    left,
                    right,
                    prefix=f"{prefix}[{index}]",
                )
            )
        return paths
    return [] if expected == observed else [prefix or "<root>"]


def run_historical_semantic_regression(
    accepted_outcome_bundle: Path,
    output: Path,
) -> dict[str, object]:
    if output.exists():
        raise ValueError("semantic-regression output must not already exist")
    archive = accepted_outcome_bundle.with_suffix(".tar.gz")
    static = _static_verify_accepted_outcome_bundle(
        accepted_outcome_bundle,
        archive=archive,
    )
    decision_identity = runtime_source_identity(require_clean=True)
    outcome_identity = outcome_runtime_source_identity(require_clean=True)
    cases = (
        ("synthetic", "synthetic", "SYNTHETIC_LOGIC", 7_200),
        (
            "production-public",
            "production_public",
            "BOUNDED_PUBLIC_CAPTURE",
            3_665,
        ),
    )
    case_receipts: list[dict[str, object]] = []
    decision_drift_paths: list[str] = []
    outcome_drift_paths: list[str] = []
    for case_path, provenance, evidence_class, duration_seconds in cases:
        run_root = accepted_outcome_bundle / case_path / "run"
        old_result = _json_object(run_root / "result.json")
        old_decision = _json_object(run_root / "decision.json")
        old_entry = (
            _json_object(run_root / "shadow-entry.json")
            if (run_root / "shadow-entry.json").is_file()
            else None
        )
        old_outcome = (
            _json_object(run_root / "outcome.json")
            if (run_root / "outcome.json").is_file()
            else None
        )
        invocation_digest = old_result.get("collector_invocation_digest")
        composition = _compose(
            run_root / "facts",
            fact_provenance=provenance,
            evidence_class=evidence_class,
            duration_seconds=duration_seconds,
            decision_identity=decision_identity,
            outcome_identity=outcome_identity,
            evidence_git_commit_sha=outcome_identity.git_commit_sha,
            collector_invocation_digest=(
                cast(str, invocation_digest) if provenance == "production_public" else None
            ),
        )
        result_drift = _semantic_drift_paths(
            _semantic_projection(old_result),
            _semantic_projection(composition.result),
            prefix=f"{case_path}.result",
        )
        decision_drift = _semantic_drift_paths(
            _semantic_projection(old_decision),
            _semantic_projection(composition.decision_receipt),
            prefix=f"{case_path}.decision",
        )
        entry_drift = _semantic_drift_paths(
            _semantic_projection(old_entry),
            _semantic_projection(composition.entry_receipt),
            prefix=f"{case_path}.entry",
        )
        outcome_drift = _semantic_drift_paths(
            _semantic_projection(old_outcome),
            _semantic_projection(composition.outcome_receipt),
            prefix=f"{case_path}.outcome",
        )
        decision_drift_paths.extend((*result_drift, *decision_drift))
        outcome_drift_paths.extend((*entry_drift, *outcome_drift))
        case_receipts.append(
            {
                "case": case_path,
                "old_result_digest": old_result.get("result_digest"),
                "new_result_digest": composition.result.get("result_digest"),
                "semantic_projection_digest": canonical_digest(
                    {
                        "result": _semantic_projection(composition.result),
                        "decision": _semantic_projection(composition.decision_receipt),
                        "entry": _semantic_projection(composition.entry_receipt),
                        "outcome": _semantic_projection(composition.outcome_receipt),
                    }
                ),
            }
        )
    receipt: dict[str, object] = {
        "receipt_type": HISTORICAL_SEMANTIC_RECEIPT_TYPE,
        "authoritative_replay": False,
        "computation_reconstructed": False,
        "accepted_archive_sha256": static["archive_sha256"],
        "accepted_implementation_commit": ("62f9453503bf585a1c0aa891d40c69f90c02e83a"),
        "historical_decision_runtime_source_digest": (
            "eed711f1c924c73a0a61b562da5154873b40713f5b5e44c482882eecf7aee29c"
        ),
        "historical_outcome_runtime_source_digest": (
            "7fbb58658c1c86157e40d58b7315f015070f8c5fe1d70c6e002aa798fd955253"
        ),
        "new_decision_runtime_source_digest": (decision_identity.runtime_source_digest),
        "new_outcome_runtime_source_digest": outcome_identity.runtime_source_digest,
        "decision_semantic_drift_count": len(decision_drift_paths),
        "decision_semantic_drift_paths": decision_drift_paths,
        "outcome_semantic_drift_count": len(outcome_drift_paths),
        "outcome_semantic_drift_paths": outcome_drift_paths,
        "static_bundle_verification": {
            key: value for key, value in static.items() if key not in {"synthetic", "public"}
        },
        "cases": case_receipts,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    output.mkdir(parents=True)
    _write_json_fsynced(output / "semantic-regression.json", receipt)
    if decision_drift_paths or outcome_drift_paths:
        raise ValueError("historical semantic regression detected drift")
    return receipt


def replay_shadow(run_root: Path, output: Path) -> dict[str, object]:
    if output.exists():
        raise ValueError("public-Shadow replay output must not already exist")
    verified = PublicShadowJournalReader(run_root).verify()
    source_result = _json_object(run_root / RUN_RESULT_PATH)
    source_result_digest = source_result.get("result_digest")
    if (
        not isinstance(source_result_digest, str)
        or canonical_digest(
            {key: value for key, value in source_result.items() if key != "result_digest"}
        )
        != source_result_digest
        or source_result.get("complete") is not True
    ):
        raise ValueError("public-Shadow source result is not a complete bound result")
    contract = _json_object(run_root / RUN_CONTRACT_PATH)
    recorded_contract_digest = contract.pop("run_contract_digest", None)
    if canonical_digest(contract) != recorded_contract_digest:
        raise ValueError("public-Shadow run contract changed")
    decision_identity = runtime_source_identity(require_clean=False)
    outcome_identity = outcome_runtime_source_identity(require_clean=False)
    run_identity = run_runtime_source_identity(require_clean=False)
    environment = runtime_environment_identity()
    if (
        contract.get("decision_runtime_source_digest") != decision_identity.runtime_source_digest
        or contract.get("outcome_runtime_source_digest") != outcome_identity.runtime_source_digest
        or contract.get("run_runtime_source_digest") != run_identity.runtime_source_digest
        or contract.get("runtime_environment_digest") != environment.runtime_environment_digest
    ):
        raise ValueError("public-Shadow replay source or runtime environment mismatch")
    source_receipt = _json_object(run_root / RUN_RECEIPT_PATH)
    source_run_receipt_digest = source_receipt.get("run_receipt_digest")
    if (
        not isinstance(source_run_receipt_digest, str)
        or canonical_digest(
            {key: value for key, value in source_receipt.items() if key != "run_receipt_digest"}
        )
        != source_run_receipt_digest
        or source_result.get("run_receipt_digest") != source_run_receipt_digest
    ):
        raise ValueError("public-Shadow Run receipt digest changed")
    fact_seal_digest = source_receipt.get("fact_seal_digest")
    if not isinstance(fact_seal_digest, str):
        raise ValueError("public-Shadow Run receipt has no fact-seal identity")
    composition = compose_run(
        verified.events,
        run_contract=contract,
        decision_identity=replace(
            decision_identity,
            git_commit_sha=cast(str, contract["git_commit_sha"]),
            dirty_paths=(),
        ),
        outcome_identity=replace(
            outcome_identity,
            git_commit_sha=cast(str, contract["git_commit_sha"]),
            dirty_paths=(),
        ),
        fact_seal_digest=fact_seal_digest,
    )
    if not _typed_equal(source_receipt, composition.run_receipt):
        raise ValueError("public-Shadow Run receipt drift")
    reconstructed_opportunities = [
        {
            key: value
            for key, value in item.items()
            if key
            not in {
                "journal_id",
                "opportunity_ordinal",
                "previous_opportunity_digest",
                "opportunity_record_digest",
            }
        }
        for item in verified.opportunities
    ]
    if not _typed_equal(
        reconstructed_opportunities,
        list(composition.opportunities),
    ):
        raise ValueError("public-Shadow opportunity journal drift")
    expected_receipt_paths: set[str] = set()
    for slot, receipt in enumerate(composition.decision_receipts):
        if receipt is None:
            continue
        relative = f"decision-slot-{slot:02d}.json"
        expected_receipt_paths.add(relative)
        if not _typed_equal(
            _json_object(run_root / RECEIPTS_DIRECTORY / relative),
            decision_receipt_payload(receipt),
        ):
            raise ValueError("public-Shadow Decision receipt drift")
    for index, entry in enumerate(composition.entries):
        relative = f"entry-{index:02d}.json"
        expected_receipt_paths.add(relative)
        if not _typed_equal(
            _json_object(run_root / RECEIPTS_DIRECTORY / relative),
            entry_receipt_payload(entry),
        ):
            raise ValueError("public-Shadow Entry receipt drift")
    for index, outcome in enumerate(composition.outcomes):
        relative = f"outcome-{index:02d}.json"
        expected_receipt_paths.add(relative)
        if not _typed_equal(
            _json_object(run_root / RECEIPTS_DIRECTORY / relative),
            outcome_receipt_payload(outcome),
        ):
            raise ValueError("public-Shadow Outcome receipt drift")
    actual_receipt_paths = {
        path.name for path in (run_root / RECEIPTS_DIRECTORY).glob("*.json") if path.is_file()
    }
    if actual_receipt_paths != expected_receipt_paths:
        raise ValueError("public-Shadow receipt denominator drift")
    provenance = contract.get("fact_provenance")
    collector_witness_verified = False
    invocation_digest: str | None = None
    if provenance == "production_public":
        invocation = _json_object(run_root / PROCESS_WITNESS_PATH)
        raw_invocation_digest = invocation.get("invocation_digest")
        unsigned_invocation = {
            key: value for key, value in invocation.items() if key != "invocation_digest"
        }
        segment_digests = [item.manifest_digest for item in verified.segments]
        started = invocation.get("invocation_started_at")
        finished = invocation.get("invocation_finished_at")
        started_at: datetime | None
        finished_at: datetime | None
        try:
            started_at = datetime.fromisoformat(cast(str, started))
            finished_at = datetime.fromisoformat(cast(str, finished))
        except (TypeError, ValueError):
            started_at = finished_at = None
        causal_records = tuple(
            cast(dict[str, object], json.loads(line))
            for line in (run_root / "causal-commits.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        )
        witness_commit = next(
            (
                item
                for item in causal_records
                if item.get("commit_type") == "ARTIFACT_COMMIT"
                and item.get("artifact_path") == PROCESS_WITNESS_PATH
            ),
            None,
        )
        network_intents = {
            cast(int, item["network_attempt_ordinal"]): item
            for item in causal_records
            if item.get("commit_type") == "NETWORK_OPEN_INTENT_COMMIT"
        }
        reconstructed_network_attempts: list[dict[str, object]] = []
        for item in causal_records:
            if item.get("commit_type") != "NETWORK_CONNECT_RESULT_COMMIT":
                continue
            ordinal = cast(int, item["network_attempt_ordinal"])
            intent = network_intents[ordinal]
            reconstructed_network_attempts.append(
                {
                    "network_attempt_ordinal": ordinal,
                    "purpose": intent["purpose"],
                    "pending_connection_generation": intent["pending_connection_generation"],
                    "due_elapsed_ms": intent["due_elapsed_ms"],
                    "actual_intent_elapsed_ms": intent["actual_intent_elapsed_ms"],
                    "effective_timeout_ms": intent["effective_timeout_ms"],
                    "dispatch_latency_ms": intent["dispatch_latency_ms"],
                    "retry_dispatch_breach": intent["retry_dispatch_breach"],
                    "actual_result_elapsed_ms": item["actual_result_elapsed_ms"],
                    "result": item["result"],
                    "error": item["error"],
                }
            )
        elapsed = invocation.get("invocation_elapsed_ms")
        seal_end = invocation.get("seal_end_elapsed_ms")
        opportunity_latencies = invocation.get("opportunity_commit_latencies_ms")
        if (
            not isinstance(raw_invocation_digest, str)
            or canonical_digest(unsigned_invocation) != raw_invocation_digest
            or source_result.get("invocation_digest") != raw_invocation_digest
            or invocation.get("receipt_type") != "FIXED_POLICY_PUBLIC_SHADOW_INVOCATION_WITNESS"
            or invocation.get("run_id") != contract.get("run_id")
            or invocation.get("run_contract_digest") != canonical_digest(contract)
            or started_at is None
            or finished_at is None
            or started_at.tzinfo is None
            or finished_at.tzinfo is None
            or type(elapsed) is not int
            or type(seal_end) is not int
            or elapsed < seal_end
            or invocation.get("requested_setup_deadline_elapsed_ms")
            != INITIAL_SETUP_TIMEOUT_SECONDS * 1_000
            or invocation.get("requested_hard_stop_elapsed_ms") != seal_end
            or invocation.get("origin_elapsed_ms") != composition.origin_elapsed_ms
            or invocation.get("network_attempts") != reconstructed_network_attempts
            or invocation.get("segment_manifest_digests") != segment_digests
            or invocation.get("opportunity_journal_head") != verified.opportunity_journal_head
            or not isinstance(opportunity_latencies, list)
            or len(opportunity_latencies) != DUE_OPPORTUNITY_COUNT
            or any(
                type(value) is not int or value < 0 or value > MAXIMUM_OPPORTUNITY_COMMIT_LATENCY_MS
                for value in opportunity_latencies
            )
            or invocation.get("run_receipt_digest") != source_run_receipt_digest
            or invocation.get("decision_runtime_source_digest")
            != decision_identity.runtime_source_digest
            or invocation.get("outcome_runtime_source_digest")
            != outcome_identity.runtime_source_digest
            or invocation.get("run_runtime_source_digest") != run_identity.runtime_source_digest
            or invocation.get("runtime_environment_digest")
            != environment.runtime_environment_digest
            or witness_commit is None
            or witness_commit.get("previous_commit_digest")
            != invocation.get("terminal_causal_commit_digest_before_witness")
            or invocation.get("external_source_attested") is not False
            or invocation.get("attempt_selection_attested") is not False
            or invocation.get("online_persistence_external_attested") is not False
        ):
            raise ValueError("production-public invocation witness is invalid")
        collector_witness_verified = True
        invocation_digest = raw_invocation_digest
    elif provenance != "synthetic":
        raise ValueError("public-Shadow fact provenance changed")
    drift_names = (
        "schedule",
        "fact",
        "decision",
        "admission",
        "entry",
        "outcome",
        "maturity",
        "no_trade",
        "aggregate",
        "run_receipt",
    )
    replay: dict[str, object] = {
        "receipt_type": REPLAY_RECEIPT_TYPE,
        "run_id": contract["run_id"],
        "replay_verified": True,
        "computation_reconstructed": True,
        "prefix_causality_verified": verified.prefix_causality_verified,
        "collector_witness_verified": collector_witness_verified,
        "runtime_environment_match": True,
        "online_persistence_process_witness_verified": (
            verified.online_persistence_process_witness_verified
        ),
        "online_persistence_external_attested": False,
        "external_source_attested": False,
        "attempt_selection_attested": False,
        **{f"{name}_drift_count": 0 for name in drift_names},
        "run_receipt_digest": composition.run_receipt["run_receipt_digest"],
        "fact_seal_digest": fact_seal_digest,
        "invocation_digest": invocation_digest,
        "decision_runtime_source_digest": decision_identity.runtime_source_digest,
        "outcome_runtime_source_digest": outcome_identity.runtime_source_digest,
        "run_runtime_source_digest": run_identity.runtime_source_digest,
    }
    replay["replay_digest"] = canonical_digest(replay)
    output.mkdir(parents=True)
    _write_json_fsynced(output / "replay.json", replay)
    return replay
