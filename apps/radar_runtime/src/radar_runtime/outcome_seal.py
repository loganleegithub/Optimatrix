"""One-cutoff sealed Decision prefix and strictly future Outcome suffix."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from market_tape import (
    CanonicalEvent,
    EventKind,
    canonical_digest,
    canonical_value,
    read_capture,
    validate_capture,
    write_capture,
)
from market_tape.capture import CaptureManifest
from short_vol_radar import DecisionInputContract

OUTCOME_FACT_SEAL_TYPE = "SHORT_VOL_OUTCOME_FACT_SEAL"
DECISION_CUTOFF_CONTRACT_ID = "INITIAL_REQUIRED_SUBSCRIPTIONS_PLUS_MAX_WINDOW"
PREFIX_DIRECTORY = "decision-prefix"
SUFFIX_DATA_PATH = "future-suffix.jsonl"
SEAL_PATH = "seal.json"
REQUIRED_INITIAL_STREAMS = frozenset(
    {
        "reference_price",
        "reference_trade",
        "platform_state",
    }
)


@dataclass(frozen=True, slots=True)
class DecisionCutoff:
    contract_id: str
    required_subscription_capture_seqs: tuple[int, ...]
    origin_elapsed_ms: int
    required_warmup_ms: int
    target_elapsed_ms: int
    capture_seq: int
    observed_elapsed_ms: int

    def __post_init__(self) -> None:
        if self.contract_id != DECISION_CUTOFF_CONTRACT_ID:
            raise ValueError("unsupported Decision cutoff contract")
        if (
            len(self.required_subscription_capture_seqs) != len(REQUIRED_INITIAL_STREAMS)
            or tuple(sorted(set(self.required_subscription_capture_seqs)))
            != self.required_subscription_capture_seqs
            or any(
                item <= 0 or item >= self.capture_seq
                for item in self.required_subscription_capture_seqs
            )
        ):
            raise ValueError("Decision cutoff subscription lineage is invalid")
        if (
            self.origin_elapsed_ms < 0
            or self.required_warmup_ms <= 0
            or self.target_elapsed_ms != self.origin_elapsed_ms + self.required_warmup_ms
            or self.observed_elapsed_ms < self.target_elapsed_ms
        ):
            raise ValueError("Decision cutoff elapsed boundary is invalid")


@dataclass(frozen=True, slots=True)
class OutcomeFactSeal:
    seal_type: str
    cutoff: DecisionCutoff
    full_capture_manifest: CaptureManifest
    full_capture_manifest_digest: str
    prefix_capture_manifest_digest: str
    prefix_capture_digest: str
    suffix_data_path: str
    suffix_record_count: int
    suffix_first_capture_seq: int
    suffix_last_capture_seq: int
    suffix_sha256: str
    combined_capture_sha256: str

    def __post_init__(self) -> None:
        if self.seal_type != OUTCOME_FACT_SEAL_TYPE:
            raise ValueError("unsupported Outcome fact seal")
        if self.full_capture_manifest_digest != self.full_capture_manifest.digest:
            raise ValueError("full capture manifest digest disagrees")
        if (
            self.prefix_capture_digest == ""
            or self.prefix_capture_manifest_digest == ""
            or self.suffix_sha256 == ""
            or self.combined_capture_sha256 != self.full_capture_manifest.content_sha256
        ):
            raise ValueError("Outcome fact seal hashes are incomplete")
        if self.suffix_data_path != SUFFIX_DATA_PATH:
            raise ValueError("Outcome suffix path is invalid")
        if (
            self.suffix_record_count <= 0
            or self.suffix_first_capture_seq != self.cutoff.capture_seq + 1
            or self.suffix_last_capture_seq != self.full_capture_manifest.last_capture_seq
            or self.suffix_record_count
            != self.suffix_last_capture_seq - self.suffix_first_capture_seq + 1
        ):
            raise ValueError("Outcome suffix range is invalid")

    @property
    def digest(self) -> str:
        return canonical_digest(self)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _payload(event: CanonicalEvent) -> dict[str, object]:
    value: object = json.loads(event.raw_payload)
    if not isinstance(value, dict):
        raise ValueError("canonical payload must be an object")
    return cast(dict[str, object], value)


def decision_cutoff(events: tuple[CanonicalEvent, ...]) -> DecisionCutoff:
    subscriptions: dict[str, CanonicalEvent] = {}
    for event in events:
        if event.event_kind is EventKind.RECONNECT and len(subscriptions) < len(
            REQUIRED_INITIAL_STREAMS
        ):
            raise ValueError("initial connection ended before required subscriptions")
        if event.event_kind is not EventKind.SUBSCRIPTION_START:
            continue
        stream = _payload(event).get("stream")
        if isinstance(stream, str) and stream in REQUIRED_INITIAL_STREAMS:
            subscriptions.setdefault(stream, event)
        if subscriptions.keys() >= REQUIRED_INITIAL_STREAMS:
            break
    if subscriptions.keys() < REQUIRED_INITIAL_STREAMS:
        raise ValueError("capture has no complete initial required subscriptions")
    ordered = tuple(subscriptions[item] for item in sorted(REQUIRED_INITIAL_STREAMS))
    origin_elapsed_ms = max(item.collector_elapsed_ms for item in ordered)
    warmup_ms = max(DecisionInputContract().required_windows_seconds) * 1_000
    target_elapsed_ms = origin_elapsed_ms + warmup_ms
    selected = next(
        (item for item in events if item.collector_elapsed_ms >= target_elapsed_ms),
        None,
    )
    if selected is None:
        raise ValueError("capture does not reach the one-shot Decision cutoff")
    return DecisionCutoff(
        contract_id=DECISION_CUTOFF_CONTRACT_ID,
        required_subscription_capture_seqs=tuple(sorted(item.capture_seq for item in ordered)),
        origin_elapsed_ms=origin_elapsed_ms,
        required_warmup_ms=warmup_ms,
        target_elapsed_ms=target_elapsed_ms,
        capture_seq=selected.capture_seq,
        observed_elapsed_ms=selected.collector_elapsed_ms,
    )


def _capture_manifest(value: object) -> CaptureManifest:
    if not isinstance(value, dict):
        raise ValueError("full capture manifest must be an object")
    raw = cast(dict[str, object], value)
    complete = raw.get("complete")
    reasons = raw.get("incomplete_reasons")
    if not isinstance(complete, bool) or not isinstance(reasons, list):
        raise ValueError("full capture manifest completion evidence is invalid")
    return CaptureManifest(
        format_id=str(raw["format_id"]),
        record_count=int(str(raw["record_count"])),
        first_capture_seq=int(str(raw["first_capture_seq"])),
        last_capture_seq=int(str(raw["last_capture_seq"])),
        content_sha256=str(raw["content_sha256"]),
        complete=complete,
        incomplete_reasons=tuple(str(item) for item in reasons),
        data_path=str(raw["data_path"]),
    )


def _decision_cutoff(value: object) -> DecisionCutoff:
    if not isinstance(value, dict):
        raise ValueError("Decision cutoff must be an object")
    raw = cast(dict[str, object], value)
    sources = raw.get("required_subscription_capture_seqs")
    if not isinstance(sources, list):
        raise ValueError("Decision cutoff subscription lineage must be an array")
    return DecisionCutoff(
        contract_id=str(raw["contract_id"]),
        required_subscription_capture_seqs=tuple(int(str(item)) for item in sources),
        origin_elapsed_ms=int(str(raw["origin_elapsed_ms"])),
        required_warmup_ms=int(str(raw["required_warmup_ms"])),
        target_elapsed_ms=int(str(raw["target_elapsed_ms"])),
        capture_seq=int(str(raw["capture_seq"])),
        observed_elapsed_ms=int(str(raw["observed_elapsed_ms"])),
    )


def _event(value: object) -> CanonicalEvent:
    if not isinstance(value, dict):
        raise ValueError("suffix event must be an object")
    raw = cast(dict[str, object], value)
    exchange = raw.get("exchange_timestamp_ms")
    instrument = raw.get("instrument_name")
    return CanonicalEvent(
        capture_seq=int(str(raw["capture_seq"])),
        collector_received_at_ms=int(str(raw["collector_received_at_ms"])),
        collector_elapsed_ms=int(str(raw["collector_elapsed_ms"])),
        exchange_timestamp_ms=(int(str(exchange)) if exchange is not None else None),
        channel=str(raw["channel"]),
        event_kind=EventKind(str(raw["event_kind"])),
        instrument_name=(str(instrument) if instrument is not None else None),
        raw_payload=str(raw["raw_payload"]),
    )


def _events_from_bytes(data: bytes) -> tuple[CanonicalEvent, ...]:
    events: list[CanonicalEvent] = []
    for line in data.decode("utf-8").splitlines():
        if line:
            events.append(_event(json.loads(line)))
    return tuple(events)


def seal_payload(seal: OutcomeFactSeal) -> dict[str, object]:
    value = canonical_value(seal)
    if not isinstance(value, dict):
        raise RuntimeError("Outcome fact seal encoding is not an object")
    return {**value, "seal_digest": seal.digest}


def _seal_from_payload(value: object) -> OutcomeFactSeal:
    if not isinstance(value, dict):
        raise ValueError("Outcome fact seal must be an object")
    raw = cast(dict[str, object], value)
    seal = OutcomeFactSeal(
        seal_type=str(raw["seal_type"]),
        cutoff=_decision_cutoff(raw["cutoff"]),
        full_capture_manifest=_capture_manifest(raw["full_capture_manifest"]),
        full_capture_manifest_digest=str(raw["full_capture_manifest_digest"]),
        prefix_capture_manifest_digest=str(raw["prefix_capture_manifest_digest"]),
        prefix_capture_digest=str(raw["prefix_capture_digest"]),
        suffix_data_path=str(raw["suffix_data_path"]),
        suffix_record_count=int(str(raw["suffix_record_count"])),
        suffix_first_capture_seq=int(str(raw["suffix_first_capture_seq"])),
        suffix_last_capture_seq=int(str(raw["suffix_last_capture_seq"])),
        suffix_sha256=str(raw["suffix_sha256"]),
        combined_capture_sha256=str(raw["combined_capture_sha256"]),
    )
    if raw.get("seal_digest") != seal.digest:
        raise ValueError("Outcome fact seal digest changed")
    return seal


def seal_capture(full_capture: Path, output: Path) -> OutcomeFactSeal:
    """Split one verified full capture without retaining a second full-size copy."""

    if output.exists() and any(output.iterdir()):
        raise ValueError("Outcome fact output directory must be empty or absent")
    full_manifest, events = read_capture(full_capture)
    cutoff = decision_cutoff(events)
    prefix_events = events[: cutoff.capture_seq]
    suffix_events = events[cutoff.capture_seq :]
    if not suffix_events:
        raise ValueError("Outcome fact seal requires a strictly future suffix")
    prefix_root = output / PREFIX_DIRECTORY
    prefix_manifest = write_capture(
        prefix_root,
        prefix_events,
        complete=full_manifest.complete,
        incomplete_reasons=full_manifest.incomplete_reasons,
    )
    full_data = (full_capture / full_manifest.data_path).read_bytes()
    lines = full_data.splitlines(keepends=True)
    if len(lines) != full_manifest.record_count or any(not item.endswith(b"\n") for item in lines):
        raise ValueError("full capture bytes are not canonical newline-delimited records")
    prefix_data = b"".join(lines[: cutoff.capture_seq])
    suffix_data = b"".join(lines[cutoff.capture_seq :])
    if prefix_data != (prefix_root / prefix_manifest.data_path).read_bytes():
        raise ValueError("sealed Decision prefix bytes changed")
    (output / SUFFIX_DATA_PATH).write_bytes(suffix_data)
    seal = OutcomeFactSeal(
        seal_type=OUTCOME_FACT_SEAL_TYPE,
        cutoff=cutoff,
        full_capture_manifest=full_manifest,
        full_capture_manifest_digest=full_manifest.digest,
        prefix_capture_manifest_digest=prefix_manifest.digest,
        prefix_capture_digest=prefix_manifest.content_sha256,
        suffix_data_path=SUFFIX_DATA_PATH,
        suffix_record_count=len(suffix_events),
        suffix_first_capture_seq=suffix_events[0].capture_seq,
        suffix_last_capture_seq=suffix_events[-1].capture_seq,
        suffix_sha256=_sha256(suffix_data),
        combined_capture_sha256=_sha256(prefix_data + suffix_data),
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / SEAL_PATH).write_text(
        json.dumps(seal_payload(seal), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    reconstructed = read_sealed_capture(output)
    if reconstructed[0] != seal or reconstructed[2] != events:
        raise RuntimeError("Outcome fact seal did not reconstruct its source capture")
    return seal


def read_sealed_capture(
    root: Path,
) -> tuple[
    OutcomeFactSeal,
    CaptureManifest,
    tuple[CanonicalEvent, ...],
    CaptureManifest,
    tuple[CanonicalEvent, ...],
]:
    raw_seal: object = json.loads((root / SEAL_PATH).read_text(encoding="utf-8"))
    seal = _seal_from_payload(raw_seal)
    prefix_manifest, prefix_events = read_capture(root / PREFIX_DIRECTORY)
    if (
        prefix_manifest.digest != seal.prefix_capture_manifest_digest
        or prefix_manifest.content_sha256 != seal.prefix_capture_digest
        or prefix_manifest.last_capture_seq != seal.cutoff.capture_seq
    ):
        raise ValueError("Outcome Decision prefix binding disagrees")
    prefix_data = (root / PREFIX_DIRECTORY / prefix_manifest.data_path).read_bytes()
    suffix_data = (root / seal.suffix_data_path).read_bytes()
    if _sha256(suffix_data) != seal.suffix_sha256:
        raise ValueError("Outcome suffix digest changed")
    suffix_events = _events_from_bytes(suffix_data)
    if (
        len(suffix_events) != seal.suffix_record_count
        or not suffix_events
        or suffix_events[0].capture_seq != seal.suffix_first_capture_seq
        or suffix_events[-1].capture_seq != seal.suffix_last_capture_seq
        or any(item.capture_seq <= seal.cutoff.capture_seq for item in suffix_events)
    ):
        raise ValueError("Outcome suffix causal range changed")
    combined_data = prefix_data + suffix_data
    if _sha256(combined_data) != seal.combined_capture_sha256:
        raise ValueError("Outcome combined capture digest changed")
    events = _events_from_bytes(combined_data)
    validate_capture(seal.full_capture_manifest, events)
    if events[: seal.cutoff.capture_seq] != prefix_events:
        raise ValueError("Outcome prefix does not equal the full capture prefix")
    if decision_cutoff(events) != seal.cutoff:
        raise ValueError("Outcome Decision cutoff drifted")
    return seal, seal.full_capture_manifest, events, prefix_manifest, prefix_events
