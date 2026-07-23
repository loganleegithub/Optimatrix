"""Closure-owned append-only durability for one bounded public-Shadow run."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from market_tape.capture import _encoded_event, _event_from_dict
from market_tape.contracts import CanonicalEvent, EventKind, canonical_digest, canonical_value

FACT_SEGMENT_ID = "SHORT_VOL_PUBLIC_SHADOW_FACT_SEGMENT"
CAUSAL_COMMIT_ID = "SHORT_VOL_PUBLIC_SHADOW_CAUSAL_COMMIT"
OPPORTUNITY_JOURNAL_ID = "SHORT_VOL_PUBLIC_SHADOW_OPPORTUNITY_JOURNAL"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _encoded_json_line(value: object) -> bytes:
    return (
        json.dumps(
            canonical_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_fsynced(path: Path, value: object) -> None:
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


def _append_fsynced(path: Path, encoded: bytes) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        offset = handle.tell()
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return offset, len(encoded)


def _json_object(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return cast(dict[str, object], value)


def _strict_int(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    assert isinstance(value, int)
    return value


@dataclass(frozen=True, slots=True)
class VerifiedSegment:
    segment_index: int
    planned_start_elapsed_ms: int
    planned_end_elapsed_ms: int
    record_count: int
    first_capture_seq: int | None
    last_capture_seq: int | None
    byte_size: int
    content_sha256: str
    manifest_digest: str


@dataclass(frozen=True, slots=True)
class VerifiedJournal:
    complete: bool
    events: tuple[CanonicalEvent, ...]
    segments: tuple[VerifiedSegment, ...]
    opportunities: tuple[dict[str, object], ...]
    opportunity_count: int
    opportunity_journal_head: str
    causal_commit_count: int
    terminal_causal_commit_digest: str
    prefix_causality_verified: bool
    orphan_tail: bool
    incomplete_reasons: tuple[str, ...]
    online_persistence_process_witness_verified: bool
    online_persistence_external_attested: bool = False


class PublicShadowJournalWriter:
    """Write facts and closure receipts before exposing them to later processing."""

    def __init__(
        self,
        root: Path,
        *,
        run_contract: Mapping[str, object],
        elapsed_ms: Callable[[], int],
    ) -> None:
        if root.exists() and any(root.iterdir()):
            raise ValueError("public-Shadow run output must be empty or absent")
        if run_contract.get("contract_id") != "FIXED_POLICY_PUBLIC_SHADOW_RUN":
            raise ValueError("unsupported public-Shadow run contract")
        segment_duration = run_contract.get("segment_duration_ms")
        self.segment_duration_ms = _strict_int(
            segment_duration,
            "segment_duration_ms",
            minimum=1,
        )
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.segments_root = root / "segments"
        self.segments_root.mkdir()
        self.causal_path = root / "causal-commits.jsonl"
        self.opportunity_path = root / "opportunities.jsonl"
        self._clock = elapsed_ms
        self._run_contract = dict(run_contract)
        self._ordinal = 0
        self._last_commit_elapsed_ms = -1
        self._causal_head = ""
        self._opportunity_head = ""
        self._platform_control_head = ""
        self._network_intents: dict[int, dict[str, object]] = {}
        self._segment_index = 0
        self._segment_start_ms = 0
        self._previous_segment_digest = ""
        self._sealed_segments: list[dict[str, object]] = []
        self._last_capture_seq = 0
        self._last_fact_elapsed_ms = -1
        self._fact_count = 0
        self._opportunity_count = 0
        self._closed = False
        contract = dict(run_contract)
        contract_digest = canonical_digest(contract)
        self.run_contract_digest = contract_digest
        _write_fsynced(
            root / "RUN_CONTRACT.json",
            {**contract, "run_contract_digest": contract_digest},
        )
        self._commit(
            "RUN_CONTRACT_COMMIT",
            {
                "run_contract_digest": contract_digest,
                "run_contract_path": "RUN_CONTRACT.json",
            },
            elapsed_ms=0,
        )

    @property
    def causal_head(self) -> str:
        return self._causal_head

    @property
    def opportunity_head(self) -> str:
        return self._opportunity_head

    @property
    def fact_count(self) -> int:
        return self._fact_count

    @property
    def segment_manifest_digests(self) -> tuple[str, ...]:
        return tuple(cast(str, item["segment_manifest_digest"]) for item in self._sealed_segments)

    @property
    def last_capture_seq(self) -> int | None:
        return self._last_capture_seq or None

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("public-Shadow journal is closed")

    def _commit(
        self,
        commit_type: str,
        payload: Mapping[str, object],
        *,
        elapsed_ms: int | None = None,
    ) -> dict[str, object]:
        self._ensure_open()
        observed_elapsed_ms = self._clock() if elapsed_ms is None else elapsed_ms
        _strict_int(observed_elapsed_ms, "commit elapsed_ms")
        if observed_elapsed_ms < self._last_commit_elapsed_ms:
            raise ValueError("causal commit elapsed time regressed")
        unsigned: dict[str, object] = {
            "receipt_type": CAUSAL_COMMIT_ID,
            "commit_ordinal": self._ordinal + 1,
            "commit_type": commit_type,
            "commit_elapsed_ms": observed_elapsed_ms,
            "previous_commit_digest": self._causal_head,
            "latest_opportunity_journal_head": self._opportunity_head,
            "latest_platform_control_head": self._platform_control_head,
            **dict(payload),
        }
        digest = canonical_digest(unsigned)
        record = {**unsigned, "commit_digest": digest}
        _append_fsynced(self.causal_path, _encoded_json_line(record))
        self._ordinal += 1
        self._last_commit_elapsed_ms = observed_elapsed_ms
        self._causal_head = digest
        if commit_type.startswith("PLATFORM_"):
            self._platform_control_head = digest
        return record

    def commit_control(
        self,
        commit_type: str,
        payload: Mapping[str, object],
        *,
        elapsed_ms: int | None = None,
    ) -> dict[str, object]:
        if not commit_type.startswith("PLATFORM_") and commit_type not in {
            "ORIGIN_COMMIT",
            "INTERRUPTION_COMMIT",
        }:
            raise ValueError("unsupported public-Shadow control commit")
        return self._commit(commit_type, payload, elapsed_ms=elapsed_ms)

    def commit_network_open_intent(
        self,
        *,
        network_attempt_ordinal: int,
        purpose: str,
        pending_connection_generation: int,
        due_elapsed_ms: int,
        actual_elapsed_ms: int,
        timeout_ms: int,
    ) -> None:
        if network_attempt_ordinal in self._network_intents:
            raise ValueError("network attempt ordinal is duplicated")
        if actual_elapsed_ms < due_elapsed_ms:
            raise ValueError("network open intent precedes its due time")
        if not 0 < timeout_ms <= 10_000:
            raise ValueError("network open timeout is outside the frozen bound")
        intent = {
            "network_attempt_ordinal": network_attempt_ordinal,
            "purpose": purpose,
            "pending_connection_generation": pending_connection_generation,
            "due_elapsed_ms": due_elapsed_ms,
            "actual_intent_elapsed_ms": actual_elapsed_ms,
            "effective_timeout_ms": timeout_ms,
            "dispatch_latency_ms": actual_elapsed_ms - due_elapsed_ms,
            "retry_dispatch_breach": actual_elapsed_ms - due_elapsed_ms >= 1_000,
        }
        self._network_intents[network_attempt_ordinal] = intent
        self._commit("NETWORK_OPEN_INTENT_COMMIT", intent, elapsed_ms=actual_elapsed_ms)

    def commit_network_connect_result(
        self,
        *,
        network_attempt_ordinal: int,
        purpose: str,
        pending_connection_generation: int,
        actual_elapsed_ms: int,
        result: str,
        error: str | None,
    ) -> None:
        intent = self._network_intents.pop(network_attempt_ordinal, None)
        if (
            intent is None
            or intent["purpose"] != purpose
            or intent["pending_connection_generation"] != pending_connection_generation
        ):
            raise ValueError("network result has no exact pending intent")
        self._commit(
            "NETWORK_CONNECT_RESULT_COMMIT",
            {
                "network_attempt_ordinal": network_attempt_ordinal,
                "purpose": purpose,
                "pending_connection_generation": pending_connection_generation,
                "actual_result_elapsed_ms": actual_elapsed_ms,
                "result": result,
                "error": error,
            },
            elapsed_ms=actual_elapsed_ms,
        )

    def _segment_data_path(self, index: int | None = None) -> Path:
        active = self._segment_index if index is None else index
        return self.segments_root / f"segment-{active:05d}.jsonl"

    def _segment_manifest_path(self, index: int | None = None) -> Path:
        active = self._segment_index if index is None else index
        return self.segments_root / f"segment-{active:05d}.manifest.json"

    def append_fact(self, event: CanonicalEvent) -> dict[str, object]:
        self._ensure_open()
        if event.capture_seq != self._last_capture_seq + 1:
            raise ValueError("public-Shadow facts must be contiguous and start at one")
        if event.collector_elapsed_ms < self._last_fact_elapsed_ms:
            raise ValueError("public-Shadow fact elapsed time must be nondecreasing")
        self.advance_segments_before(event.collector_elapsed_ms)
        segment_end = self._segment_start_ms + self.segment_duration_ms
        if not self._segment_start_ms <= event.collector_elapsed_ms < segment_end:
            raise ValueError("fact does not belong to the active segment")
        encoded = _encoded_event(event)
        path = self._segment_data_path()
        offset, length = _append_fsynced(path, encoded)
        commit = self._commit(
            "FACT_COMMIT",
            {
                "capture_seq": event.capture_seq,
                "collector_elapsed_ms": event.collector_elapsed_ms,
                "fact_digest": event.digest,
                "segment_index": self._segment_index,
                "segment_data_path": path.relative_to(self.root).as_posix(),
                "segment_byte_offset": offset,
                "segment_byte_length": length,
                "encoded_fact_sha256": hashlib.sha256(encoded).hexdigest(),
            },
        )
        self._last_capture_seq = event.capture_seq
        self._last_fact_elapsed_ms = event.collector_elapsed_ms
        self._fact_count += 1
        return commit

    def write_uncommitted_fact_for_test(self, event: CanonicalEvent) -> None:
        """Inject the crash boundary after payload fsync and before its FACT_COMMIT."""

        self._ensure_open()
        self.advance_segments_before(event.collector_elapsed_ms)
        _append_fsynced(self._segment_data_path(), _encoded_event(event))

    def append_opportunity(
        self,
        record: Mapping[str, object],
        *,
        elapsed_ms: int | None = None,
    ) -> dict[str, object]:
        self._ensure_open()
        if record.get("receipt_type") != "SHORT_VOL_PUBLIC_SHADOW_OPPORTUNITY_RECORD":
            raise ValueError("unsupported opportunity record")
        unsigned = {
            "journal_id": OPPORTUNITY_JOURNAL_ID,
            "opportunity_ordinal": self._opportunity_count + 1,
            "previous_opportunity_digest": self._opportunity_head,
            **dict(record),
        }
        digest = canonical_digest(unsigned)
        envelope = {**unsigned, "opportunity_record_digest": digest}
        offset, length = _append_fsynced(self.opportunity_path, _encoded_json_line(envelope))
        self._opportunity_head = digest
        self._opportunity_count += 1
        return self._commit(
            "OPPORTUNITY_COMMIT",
            {
                "opportunity_ordinal": self._opportunity_count,
                "opportunity_record_digest": digest,
                "opportunity_journal_path": self.opportunity_path.name,
                "opportunity_byte_offset": offset,
                "opportunity_byte_length": length,
                "fact_chain_head_through_cutoff": self._causal_head,
            },
            elapsed_ms=elapsed_ms,
        )

    def advance_segments_before(self, elapsed_ms: int) -> None:
        self._ensure_open()
        _strict_int(elapsed_ms, "segment advance elapsed_ms")
        while self._segment_start_ms + self.segment_duration_ms <= elapsed_ms:
            self._seal_active_segment(self._segment_start_ms + self.segment_duration_ms)

    def _seal_active_segment(self, planned_end_ms: int) -> None:
        if not (
            self._segment_start_ms
            < planned_end_ms
            <= self._segment_start_ms + self.segment_duration_ms
        ):
            raise ValueError("segment endpoint is outside its bounded window")
        data_path = self._segment_data_path()
        if not data_path.exists():
            with data_path.open("xb") as handle:
                handle.flush()
                os.fsync(handle.fileno())
        content = data_path.read_bytes()
        fact_commits = self._fact_commits_for_segment(self._segment_index)
        sequences = tuple(cast(int, item["capture_seq"]) for item in fact_commits)
        manifest: dict[str, object] = {
            "segment_type": FACT_SEGMENT_ID,
            "segment_index": self._segment_index,
            "data_path": data_path.relative_to(self.root).as_posix(),
            "planned_start_elapsed_ms": self._segment_start_ms,
            "planned_end_elapsed_ms": planned_end_ms,
            "timer_seal_elapsed_ms": max(planned_end_ms, self._clock()),
            "record_count": len(sequences),
            "first_capture_seq": sequences[0] if sequences else None,
            "last_capture_seq": sequences[-1] if sequences else None,
            "byte_size": len(content),
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "previous_segment_digest": self._previous_segment_digest,
            "run_contract_digest": self.run_contract_digest,
            "runtime_identity_digests": {
                key: self._run_contract.get(key)
                for key in (
                    "decision_runtime_source_digest",
                    "outcome_runtime_source_digest",
                    "run_runtime_source_digest",
                    "runtime_environment_digest",
                )
            },
            "terminal_preseal_commit_ordinal": self._ordinal,
            "terminal_preseal_commit_digest": self._causal_head,
            "opportunity_journal_head": self._opportunity_head,
            "platform_control_head": self._platform_control_head,
        }
        manifest_digest = canonical_digest(manifest)
        persisted = {**manifest, "segment_manifest_digest": manifest_digest}
        manifest_path = self._segment_manifest_path()
        _write_fsynced(manifest_path, persisted)
        self._commit(
            "SEGMENT_SEAL_COMMIT",
            {
                "segment_index": self._segment_index,
                "segment_manifest_path": manifest_path.relative_to(self.root).as_posix(),
                "segment_manifest_digest": manifest_digest,
            },
            elapsed_ms=max(planned_end_ms, self._clock()),
        )
        self._sealed_segments.append(persisted)
        self._previous_segment_digest = manifest_digest
        self._segment_index += 1
        self._segment_start_ms = planned_end_ms

    def seal_fact_segments(self, end_elapsed_ms: int) -> tuple[str, ...]:
        """Seal the half-open fact interval while leaving receipt commits open."""

        self._ensure_open()
        _strict_int(end_elapsed_ms, "fact seal end_elapsed_ms")
        self.advance_segments_before(end_elapsed_ms)
        if end_elapsed_ms > self._segment_start_ms:
            self._seal_active_segment(end_elapsed_ms)
        return self.segment_manifest_digests

    def commit_artifact(
        self,
        *,
        artifact_type: str,
        relative_path: str,
        artifact_digest: str,
        elapsed_ms: int | None = None,
    ) -> None:
        path = self.root / relative_path
        if not path.is_file() or not artifact_digest:
            raise ValueError("committed artifact is missing or unidentified")
        self._commit(
            "ARTIFACT_COMMIT",
            {
                "artifact_type": artifact_type,
                "artifact_path": relative_path,
                "artifact_digest": artifact_digest,
                "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            },
            elapsed_ms=elapsed_ms,
        )

    def _fact_commits_for_segment(self, segment_index: int) -> list[dict[str, object]]:
        if not self.causal_path.exists():
            return []
        commits: list[dict[str, object]] = []
        for line in self.causal_path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            value: object = json.loads(line)
            if (
                isinstance(value, dict)
                and value.get("commit_type") == "FACT_COMMIT"
                and value.get("segment_index") == segment_index
            ):
                commits.append(cast(dict[str, object], value))
        return commits

    def seal(
        self,
        end_elapsed_ms: int,
        *,
        complete: bool,
        incomplete_reasons: tuple[str, ...],
        final_bindings: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self._ensure_open()
        _strict_int(end_elapsed_ms, "seal end_elapsed_ms")
        self.seal_fact_segments(end_elapsed_ms)
        if self._network_intents:
            raise ValueError("cannot seal with a network call lacking its result commit")
        if complete and incomplete_reasons:
            raise ValueError("complete journal cannot carry incomplete reasons")
        if not complete and not incomplete_reasons:
            raise ValueError("incomplete journal requires exact reasons")
        manifest: dict[str, object] = {
            "receipt_type": "SHORT_VOL_PUBLIC_SHADOW_SEGMENT_MANIFEST",
            "run_contract_digest": self.run_contract_digest,
            "complete": complete,
            "incomplete_reasons": list(incomplete_reasons),
            "seal_end_elapsed_ms": end_elapsed_ms,
            "segment_manifest_digests": [
                item["segment_manifest_digest"] for item in self._sealed_segments
            ],
            "fact_count": self._fact_count,
            "final_capture_seq": self.last_capture_seq,
            "opportunity_count": self._opportunity_count,
            "opportunity_journal_head": self._opportunity_head,
            "terminal_preseal_commit_ordinal": self._ordinal,
            "terminal_preseal_commit_digest": self._causal_head,
            "online_persistence_external_attested": False,
            "final_bindings": dict(final_bindings or {}),
        }
        digest = canonical_digest(manifest)
        _write_fsynced(
            self.root / "SEGMENT_MANIFEST.json",
            {**manifest, "segment_manifest_digest": digest},
        )
        self._commit(
            "FINALIZE_COMMIT",
            {
                "segment_manifest_digest": digest,
                "complete": complete,
            },
            elapsed_ms=max(end_elapsed_ms, self._clock()),
        )
        self._closed = True
        return {**manifest, "segment_manifest_digest": digest}

    def interrupt(
        self,
        reasons: tuple[str, ...],
        *,
        final_bindings: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self._ensure_open()
        if not reasons:
            raise ValueError("interruption requires exact reasons")
        self._commit(
            "INTERRUPTION_COMMIT",
            {"incomplete_reasons": list(reasons)},
        )
        payload = {
            "receipt_type": "SHORT_VOL_PUBLIC_SHADOW_INCOMPLETE_PREFIX",
            "run_contract_digest": self.run_contract_digest,
            "incomplete_reasons": list(reasons),
            "last_durable_capture_seq": self.last_capture_seq,
            "terminal_commit_ordinal": self._ordinal,
            "terminal_commit_digest": self._causal_head,
            "opportunity_count": self._opportunity_count,
            "segment_manifest_digests": list(self.segment_manifest_digests),
            "final_bindings": dict(final_bindings or {}),
        }
        persisted: dict[str, object] = {
            **payload,
            "prefix_digest": canonical_digest(payload),
        }
        _write_fsynced(
            self.root / "INCOMPLETE_PREFIX.json",
            persisted,
        )
        self._closed = True
        return persisted


class PublicShadowJournalReader:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _contract(self) -> tuple[dict[str, object], str]:
        persisted = _json_object(self.root / "RUN_CONTRACT.json")
        digest = persisted.pop("run_contract_digest", None)
        if not isinstance(digest, str) or canonical_digest(persisted) != digest:
            raise ValueError("run contract digest changed")
        if persisted.get("contract_id") != "FIXED_POLICY_PUBLIC_SHADOW_RUN":
            raise ValueError("run contract identity changed")
        return persisted, digest

    def _commits(self, contract_digest: str) -> tuple[dict[str, object], ...]:
        path = self.root / "causal-commits.jsonl"
        if not path.is_file():
            raise ValueError("causal commit journal is missing")
        commits: list[dict[str, object]] = []
        head = ""
        previous_elapsed_ms = -1
        for ordinal, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line:
                raise ValueError("causal commit journal contains an empty record")
            value: object = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("causal commit must be an object")
            record = cast(dict[str, object], value)
            digest = record.get("commit_digest")
            commit_elapsed_ms = _strict_int(
                record.get("commit_elapsed_ms"),
                "commit_elapsed_ms",
            )
            unsigned = {key: item for key, item in record.items() if key != "commit_digest"}
            if (
                record.get("receipt_type") != CAUSAL_COMMIT_ID
                or record.get("commit_ordinal") != ordinal
                or record.get("previous_commit_digest") != head
                or not isinstance(digest, str)
                or canonical_digest(unsigned) != digest
                or commit_elapsed_ms < previous_elapsed_ms
            ):
                raise ValueError("causal commit chain changed")
            commits.append(record)
            head = digest
            previous_elapsed_ms = commit_elapsed_ms
        if (
            not commits
            or commits[0].get("commit_type") != "RUN_CONTRACT_COMMIT"
            or commits[0].get("run_contract_digest") != contract_digest
        ):
            raise ValueError("causal journal does not bind the run contract")
        pending_network: dict[int, dict[str, object]] = {}
        expected_network_ordinal = 1
        for commit in commits:
            commit_type = commit.get("commit_type")
            raw_attempt = commit.get("network_attempt_ordinal")
            if commit_type == "NETWORK_OPEN_INTENT_COMMIT":
                attempt = _strict_int(raw_attempt, "network_attempt_ordinal", minimum=1)
                due = _strict_int(commit.get("due_elapsed_ms"), "network due elapsed")
                actual = _strict_int(
                    commit.get("actual_intent_elapsed_ms"),
                    "network intent elapsed",
                )
                timeout = _strict_int(
                    commit.get("effective_timeout_ms"),
                    "network timeout",
                    minimum=1,
                )
                latency = actual - due
                if (
                    attempt != expected_network_ordinal
                    or attempt in pending_network
                    or actual < due
                    or timeout > 10_000
                    or commit.get("dispatch_latency_ms") != latency
                    or commit.get("retry_dispatch_breach") != (latency >= 1_000)
                    or commit.get("purpose") not in {"INITIAL_SETUP", "RECONNECT"}
                ):
                    raise ValueError("network intent ordinal was reused")
                pending_network[attempt] = commit
                expected_network_ordinal += 1
            elif commit_type == "NETWORK_CONNECT_RESULT_COMMIT":
                attempt = _strict_int(raw_attempt, "network_attempt_ordinal", minimum=1)
                intent = pending_network.pop(attempt, None)
                actual = _strict_int(
                    commit.get("actual_result_elapsed_ms"),
                    "network result elapsed",
                )
                if (
                    intent is None
                    or any(
                        intent.get(field) != commit.get(field)
                        for field in ("purpose", "pending_connection_generation")
                    )
                    or (
                        actual < cast(int, intent["actual_intent_elapsed_ms"])
                        or commit.get("result") not in {"CONNECTED", "FAILED"}
                        or (commit.get("result") == "CONNECTED" and commit.get("error") is not None)
                        or (
                            commit.get("result") == "FAILED"
                            and not isinstance(commit.get("error"), str)
                        )
                    )
                ):
                    raise ValueError("network result is not paired with its intent")
        finalized = commits[-1].get("commit_type") == "FINALIZE_COMMIT"
        if finalized and pending_network:
            raise ValueError("final journal has an unresolved network intent")
        return tuple(commits)

    def _opportunities(
        self,
        commits: tuple[dict[str, object], ...],
    ) -> tuple[dict[str, object], ...]:
        path = self.root / "opportunities.jsonl"
        opportunity_commits = tuple(
            item for item in commits if item.get("commit_type") == "OPPORTUNITY_COMMIT"
        )
        if not opportunity_commits:
            if path.exists() and path.read_bytes():
                raise ValueError("opportunity journal has no causal commit")
            return ()
        content = path.read_bytes()
        records: list[dict[str, object]] = []
        head = ""
        committed_end = 0
        for ordinal, commit in enumerate(opportunity_commits, start=1):
            offset = _strict_int(commit.get("opportunity_byte_offset"), "opportunity offset")
            length = _strict_int(
                commit.get("opportunity_byte_length"),
                "opportunity length",
                minimum=1,
            )
            if offset != committed_end or offset + length > len(content):
                raise ValueError("opportunity journal byte range changed")
            value: object = json.loads(content[offset : offset + length])
            if not isinstance(value, dict):
                raise ValueError("opportunity record must be an object")
            record = cast(dict[str, object], value)
            digest = record.get("opportunity_record_digest")
            unsigned = {
                key: item for key, item in record.items() if key != "opportunity_record_digest"
            }
            if (
                record.get("journal_id") != OPPORTUNITY_JOURNAL_ID
                or record.get("opportunity_ordinal") != ordinal
                or record.get("previous_opportunity_digest") != head
                or digest != commit.get("opportunity_record_digest")
                or not isinstance(digest, str)
                or canonical_digest(unsigned) != digest
            ):
                raise ValueError("opportunity journal chain changed")
            if (
                commit.get("fact_chain_head_through_cutoff") != commit.get("previous_commit_digest")
                or commit.get("latest_opportunity_journal_head") != digest
            ):
                raise ValueError("opportunity causal cutoff binding changed")
            records.append(record)
            head = digest
            committed_end = offset + length
        if committed_end != len(content):
            raise ValueError("opportunity journal has an orphan tail")
        return tuple(records)

    def _events(
        self,
        commits: tuple[dict[str, object], ...],
    ) -> tuple[tuple[CanonicalEvent, ...], bool, dict[int, int]]:
        fact_commits = tuple(item for item in commits if item.get("commit_type") == "FACT_COMMIT")
        events: list[CanonicalEvent] = []
        segment_committed_ends: dict[int, int] = {}
        orphan_tail = False
        for expected_seq, commit in enumerate(fact_commits, start=1):
            sequence = _strict_int(commit.get("capture_seq"), "capture_seq", minimum=1)
            if sequence != expected_seq:
                raise ValueError("committed facts are not contiguous")
            segment_index = _strict_int(commit.get("segment_index"), "segment_index")
            relative = commit.get("segment_data_path")
            if not isinstance(relative, str):
                raise ValueError("fact commit has no segment path")
            path = self.root / relative
            data = path.read_bytes()
            offset = _strict_int(commit.get("segment_byte_offset"), "fact byte offset")
            length = _strict_int(commit.get("segment_byte_length"), "fact byte length", minimum=1)
            expected_offset = segment_committed_ends.get(segment_index, 0)
            if offset != expected_offset or offset + length > len(data):
                raise ValueError("fact byte range changed")
            encoded = data[offset : offset + length]
            if hashlib.sha256(encoded).hexdigest() != commit.get("encoded_fact_sha256"):
                raise ValueError("encoded fact bytes changed")
            raw: object = json.loads(encoded)
            if not isinstance(raw, dict):
                raise ValueError("canonical fact must be an object")
            event = _event_from_dict(cast(dict[str, object], raw))
            if event.digest != commit.get("fact_digest") or event.capture_seq != sequence:
                raise ValueError("canonical fact digest changed")
            if events and event.collector_elapsed_ms < events[-1].collector_elapsed_ms:
                raise ValueError("canonical fact elapsed time regressed")
            events.append(event)
            segment_committed_ends[segment_index] = offset + length
        for path in (self.root / "segments").glob("segment-*.jsonl"):
            index = int(path.stem.split("-")[1])
            if len(path.read_bytes()) > segment_committed_ends.get(index, 0):
                orphan_tail = True
        return tuple(events), orphan_tail, segment_committed_ends

    def _segments(
        self,
        commits: tuple[dict[str, object], ...],
        segment_duration_ms: int,
        committed_ends: dict[int, int],
        events: tuple[CanonicalEvent, ...],
        contract: dict[str, object],
        contract_digest: str,
    ) -> tuple[VerifiedSegment, ...]:
        seals = tuple(item for item in commits if item.get("commit_type") == "SEGMENT_SEAL_COMMIT")
        segments: list[VerifiedSegment] = []
        previous_digest = ""
        expected_start = 0
        for index, commit in enumerate(seals):
            if commit.get("segment_index") != index:
                raise ValueError("segment seal order changed")
            relative = commit.get("segment_manifest_path")
            if not isinstance(relative, str):
                raise ValueError("segment seal has no manifest path")
            path = self.root / relative
            if not path.is_file():
                raise ValueError("sealed segment manifest is missing")
            persisted = _json_object(path)
            digest = persisted.pop("segment_manifest_digest", None)
            if (
                not isinstance(digest, str)
                or digest != commit.get("segment_manifest_digest")
                or canonical_digest(persisted) != digest
                or persisted.get("segment_type") != FACT_SEGMENT_ID
                or persisted.get("segment_index") != index
                or persisted.get("previous_segment_digest") != previous_digest
                or persisted.get("planned_start_elapsed_ms") != expected_start
                or persisted.get("run_contract_digest") != contract_digest
                or persisted.get("runtime_identity_digests")
                != {
                    key: contract.get(key)
                    for key in (
                        "decision_runtime_source_digest",
                        "outcome_runtime_source_digest",
                        "run_runtime_source_digest",
                        "runtime_environment_digest",
                    )
                }
                or relative != f"segments/segment-{index:05d}.manifest.json"
                or persisted.get("terminal_preseal_commit_ordinal")
                != cast(int, commit["commit_ordinal"]) - 1
                or persisted.get("terminal_preseal_commit_digest")
                != commit.get("previous_commit_digest")
                or persisted.get("opportunity_journal_head")
                != commit.get("latest_opportunity_journal_head")
                or persisted.get("platform_control_head")
                != commit.get("latest_platform_control_head")
            ):
                raise ValueError("segment manifest chain changed")
            end = _strict_int(
                persisted.get("planned_end_elapsed_ms"),
                "segment planned end",
                minimum=1,
            )
            if end <= expected_start or end - expected_start > segment_duration_ms:
                raise ValueError("segment window changed")
            data_relative = persisted.get("data_path")
            if (
                not isinstance(data_relative, str)
                or data_relative != f"segments/segment-{index:05d}.jsonl"
            ):
                raise ValueError("segment data path is missing")
            data = (self.root / data_relative).read_bytes()
            if (
                persisted.get("byte_size") != len(data)
                or persisted.get("content_sha256") != hashlib.sha256(data).hexdigest()
                or committed_ends.get(index, 0) != len(data)
            ):
                raise ValueError("sealed segment bytes changed")
            record_count = _strict_int(persisted.get("record_count"), "segment record count")
            segment_events = tuple(
                event for event in events if expected_start <= event.collector_elapsed_ms < end
            )
            first = persisted.get("first_capture_seq")
            last = persisted.get("last_capture_seq")
            if (
                record_count != len(segment_events)
                or first != (segment_events[0].capture_seq if segment_events else None)
                or last != (segment_events[-1].capture_seq if segment_events else None)
                or _strict_int(
                    persisted.get("timer_seal_elapsed_ms"),
                    "segment timer seal elapsed",
                )
                < end
                or cast(int, commit["commit_elapsed_ms"])
                < cast(int, persisted["timer_seal_elapsed_ms"])
            ):
                raise ValueError("segment fact/time witness changed")
            if record_count == 0:
                if (
                    first is not None
                    or last is not None
                    or data
                    or persisted.get("content_sha256") != EMPTY_SHA256
                ):
                    raise ValueError("empty segment evidence changed")
            else:
                _strict_int(first, "segment first capture_seq", minimum=1)
                _strict_int(last, "segment last capture_seq", minimum=1)
            segments.append(
                VerifiedSegment(
                    segment_index=index,
                    planned_start_elapsed_ms=expected_start,
                    planned_end_elapsed_ms=end,
                    record_count=record_count,
                    first_capture_seq=first,
                    last_capture_seq=last,
                    byte_size=len(data),
                    content_sha256=cast(str, persisted["content_sha256"]),
                    manifest_digest=digest,
                )
            )
            expected_start = end
            previous_digest = digest
        return tuple(segments)

    def _artifacts(self, commits: tuple[dict[str, object], ...]) -> None:
        for commit in commits:
            if commit.get("commit_type") != "ARTIFACT_COMMIT":
                continue
            relative = commit.get("artifact_path")
            expected_sha = commit.get("artifact_sha256")
            expected_digest = commit.get("artifact_digest")
            if not all(
                isinstance(item, str) and item
                for item in (
                    relative,
                    expected_sha,
                    expected_digest,
                )
            ):
                raise ValueError("artifact commit identity is incomplete")
            assert isinstance(relative, str)
            path = self.root / relative
            try:
                path.relative_to(self.root)
            except ValueError as error:
                raise ValueError("artifact path escapes the run root") from error
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
                raise ValueError("committed artifact bytes changed")
            payload = _json_object(path)
            bound_digests = {
                value
                for key, value in payload.items()
                if key.endswith("_digest") and isinstance(value, str)
            }
            if expected_digest not in bound_digests:
                raise ValueError("committed artifact semantic digest changed")

    def _probe_controls(
        self,
        commits: tuple[dict[str, object], ...],
        events: tuple[CanonicalEvent, ...],
        *,
        complete: bool,
    ) -> None:
        obligations: set[str] = set()
        retired_obligations: set[str] = set()
        accounted_attempts: dict[str, set[int]] = {}
        rpc_intents: dict[tuple[int, int], dict[str, object]] = {}
        rpc_results: dict[tuple[int, int], dict[str, object]] = {}
        expected_acquisition_ordinal = 1
        for commit in commits:
            commit_type = commit.get("commit_type")
            if commit_type == "PLATFORM_PROBE_OBLIGATION_COMMIT":
                obligation_id = commit.get("obligation_id")
                if not isinstance(obligation_id, str) or obligation_id in obligations:
                    raise ValueError("platform probe obligation identity changed")
                obligations.add(obligation_id)
                accounted_attempts[obligation_id] = set()
            elif commit_type == "PLATFORM_PROBE_SEND_INTENT_COMMIT":
                obligation_id = commit.get("obligation_id")
                acquisition = _strict_int(
                    commit.get("platform_acquisition_ordinal"),
                    "platform acquisition ordinal",
                    minimum=1,
                )
                request_id = _strict_int(
                    commit.get("request_id"),
                    "platform request id",
                    minimum=1,
                )
                due = _strict_int(commit.get("due_elapsed_ms"), "probe due elapsed")
                deadline = _strict_int(
                    commit.get("deadline_elapsed_ms"),
                    "probe deadline elapsed",
                    minimum=1,
                )
                actual = _strict_int(
                    commit.get("actual_elapsed_ms"),
                    "probe send elapsed",
                )
                if (
                    obligation_id not in obligations
                    or acquisition != expected_acquisition_ordinal
                    or not due <= actual < deadline
                    or commit.get("method") != "public/subscribe"
                ):
                    raise ValueError("platform probe send lineage changed")
                rpc_intents[(acquisition, request_id)] = commit
                expected_acquisition_ordinal += 1
            elif commit_type == "PLATFORM_STATUS_SEND_INTENT_COMMIT":
                acquisition = _strict_int(
                    commit.get("platform_acquisition_ordinal"),
                    "platform acquisition ordinal",
                    minimum=1,
                )
                request_id = _strict_int(
                    commit.get("request_id"),
                    "platform status request id",
                    minimum=1,
                )
                if (
                    commit.get("obligation_id") not in obligations
                    or commit.get("method") != "public/status"
                    or (acquisition, request_id) in rpc_intents
                ):
                    raise ValueError("platform status send lineage changed")
                rpc_intents[(acquisition, request_id)] = commit
            elif commit_type == "PLATFORM_PROBE_RPC_RESULT_COMMIT":
                acquisition = _strict_int(
                    commit.get("platform_acquisition_ordinal"),
                    "platform result acquisition ordinal",
                    minimum=1,
                )
                request_id = _strict_int(
                    commit.get("request_id"),
                    "platform result request id",
                    minimum=1,
                )
                key = (acquisition, request_id)
                intent = rpc_intents.get(key)
                if (
                    intent is None
                    or key in rpc_results
                    or intent.get("obligation_id") != commit.get("obligation_id")
                    or intent.get("method") != commit.get("method")
                    or cast(int, commit["commit_ordinal"]) <= cast(int, intent["commit_ordinal"])
                ):
                    raise ValueError("platform probe result lineage changed")
                rpc_results[key] = commit
            elif commit_type in {
                "PLATFORM_PROBE_ATTEMPT_STATE_COMMIT",
                "PLATFORM_PROBE_STATE_COMMIT",
            }:
                obligation_id = commit.get("obligation_id")
                if obligation_id not in obligations:
                    raise ValueError("platform probe state has no obligation")
                assert isinstance(obligation_id, str)
                if commit.get("state") == "INVALIDATED_BY_RECONNECT":
                    retired_obligations.add(obligation_id)
                raw_attempt = commit.get("attempt")
                if type(raw_attempt) is int:
                    accounted_attempts[obligation_id].add(raw_attempt)
        if complete and rpc_results.keys() != rpc_intents.keys():
            raise ValueError("complete run has a platform RPC without an exact result")
        if complete and any(
            obligation_id not in retired_obligations
            and accounted_attempts[obligation_id] != set(range(3))
            for obligation_id in obligations
        ):
            raise ValueError("complete run has an unaccounted platform probe attempt")
        fact_ordinals = {
            cast(int, item["capture_seq"]): cast(int, item["commit_ordinal"])
            for item in commits
            if item.get("commit_type") == "FACT_COMMIT"
        }
        for event in events:
            payload: object = json.loads(event.raw_payload)
            if not isinstance(payload, dict):
                continue
            raw_acquisition = payload.get("platform_acquisition_ordinal")
            raw_request_id = payload.get("request_id")
            if type(raw_acquisition) is not int or type(raw_request_id) is not int:
                continue
            acquisition = raw_acquisition
            request_id = raw_request_id
            result = rpc_results.get((acquisition, request_id))
            expected_method = (
                "public/subscribe"
                if event.event_kind is EventKind.SUBSCRIPTION_START
                else "public/status"
                if event.event_kind is EventKind.PLATFORM_STATE
                else None
            )
            if (
                result is None
                or result.get("method") != expected_method
                or cast(int, result["commit_ordinal"]) >= fact_ordinals[event.capture_seq]
            ):
                raise ValueError("canonical platform fact precedes its RPC result commit")

    def read_committed_events(self) -> tuple[CanonicalEvent, ...]:
        """Read the validated durable fact prefix before final receipt materialization."""

        _contract, contract_digest = self._contract()
        commits = self._commits(contract_digest)
        events, orphan_tail, _committed_ends = self._events(commits)
        if orphan_tail:
            raise ValueError("durable fact prefix has an orphan tail")
        return events

    def verify(self, *, allow_incomplete: bool = False) -> VerifiedJournal:
        contract, contract_digest = self._contract()
        segment_duration = _strict_int(
            contract.get("segment_duration_ms"),
            "segment_duration_ms",
            minimum=1,
        )
        commits = self._commits(contract_digest)
        opportunities = self._opportunities(commits)
        self._artifacts(commits)
        events, orphan_tail, committed_ends = self._events(commits)
        segments = self._segments(
            commits,
            segment_duration,
            committed_ends,
            events,
            contract,
            contract_digest,
        )
        final_path = self.root / "SEGMENT_MANIFEST.json"
        prefix_path = self.root / "INCOMPLETE_PREFIX.json"
        artifact_digests = {
            cast(str, item["artifact_digest"])
            for item in commits
            if item.get("commit_type") == "ARTIFACT_COMMIT"
        }
        complete = False
        reasons: list[str] = []
        if final_path.is_file():
            persisted = _json_object(final_path)
            digest = persisted.pop("segment_manifest_digest", None)
            final_commit = commits[-1]
            if (
                final_commit.get("commit_type") != "FINALIZE_COMMIT"
                or final_commit.get("segment_manifest_digest") != digest
                or not isinstance(digest, str)
                or canonical_digest(persisted) != digest
                or persisted.get("run_contract_digest") != contract_digest
                or persisted.get("segment_manifest_digests")
                != [item.manifest_digest for item in segments]
                or persisted.get("fact_count") != len(events)
                or persisted.get("opportunity_count") != len(opportunities)
                or persisted.get("terminal_preseal_commit_ordinal")
                != cast(int, final_commit["commit_ordinal"]) - 1
                or persisted.get("terminal_preseal_commit_digest")
                != final_commit.get("previous_commit_digest")
                or (
                    segments
                    and persisted.get("seal_end_elapsed_ms") != segments[-1].planned_end_elapsed_ms
                )
            ):
                raise ValueError("final segment manifest changed")
            raw_complete = persisted.get("complete")
            raw_reasons = persisted.get("incomplete_reasons")
            final_bindings = persisted.get("final_bindings")
            if (
                not isinstance(raw_complete, bool)
                or not isinstance(raw_reasons, list)
                or not isinstance(final_bindings, dict)
                or any(
                    value not in artifact_digests
                    for key, value in final_bindings.items()
                    if key
                    in {
                        "run_receipt_digest",
                        "invocation_digest",
                        "result_digest",
                    }
                )
            ):
                raise ValueError("final completion evidence is invalid")
            complete = raw_complete
            reasons.extend(str(item) for item in raw_reasons)
            if complete and (reasons or orphan_tail):
                raise ValueError("complete journal contains incomplete evidence")
            if (
                complete
                and {
                    "due_opportunity_count",
                    "sealed_run_seconds",
                }
                <= contract.keys()
            ):
                origin_commits = tuple(
                    item for item in commits if item.get("commit_type") == "ORIGIN_COMMIT"
                )
                if (
                    len(origin_commits) != 1
                    or len(opportunities) != contract.get("due_opportunity_count")
                    or not segments
                    or persisted.get("seal_end_elapsed_ms")
                    != cast(int, origin_commits[0]["origin_elapsed_ms"])
                    + cast(int, contract["sealed_run_seconds"]) * 1_000
                ):
                    raise ValueError("complete run schedule binding changed")
        elif prefix_path.is_file():
            persisted = _json_object(prefix_path)
            digest = persisted.pop("prefix_digest", None)
            if (
                not isinstance(digest, str)
                or canonical_digest(persisted) != digest
                or persisted.get("run_contract_digest") != contract_digest
                or persisted.get("terminal_commit_digest") != commits[-1].get("commit_digest")
                or persisted.get("terminal_commit_ordinal") != len(commits)
            ):
                raise ValueError("incomplete prefix witness changed")
            raw_reasons = persisted.get("incomplete_reasons")
            final_bindings = persisted.get("final_bindings")
            if (
                not isinstance(raw_reasons, list)
                or not raw_reasons
                or not isinstance(final_bindings, dict)
                or any(value not in artifact_digests for value in final_bindings.values())
            ):
                raise ValueError("incomplete prefix has no exact reason")
            reasons.extend(str(item) for item in raw_reasons)
        else:
            raise ValueError("journal has neither final nor interrupted prefix evidence")
        if orphan_tail:
            reasons.append("ORPHAN_FACT_TAIL")
        if not complete and not allow_incomplete:
            raise ValueError("public-Shadow journal is incomplete")
        self._probe_controls(commits, events, complete=complete)
        return VerifiedJournal(
            complete=complete,
            events=events,
            segments=segments,
            opportunities=opportunities,
            opportunity_count=len(opportunities),
            opportunity_journal_head=(
                cast(str, opportunities[-1]["opportunity_record_digest"]) if opportunities else ""
            ),
            causal_commit_count=len(commits),
            terminal_causal_commit_digest=cast(str, commits[-1]["commit_digest"]),
            prefix_causality_verified=True,
            orphan_tail=orphan_tail,
            incomplete_reasons=tuple(dict.fromkeys(reasons)),
            online_persistence_process_witness_verified=True,
        )
