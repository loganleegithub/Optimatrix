"""Small deterministic JSONL capture format for bounded market-tape runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from market_tape.contracts import (
    CanonicalEvent,
    EventKind,
    canonical_digest,
    canonical_value,
)

CAPTURE_FORMAT_ID = "CANONICAL_MARKET_TAPE_WITH_PERSISTED_ELAPSED"


@dataclass(frozen=True, slots=True)
class CaptureManifest:
    format_id: str
    record_count: int
    first_capture_seq: int
    last_capture_seq: int
    content_sha256: str
    complete: bool
    incomplete_reasons: tuple[str, ...]
    data_path: str

    @property
    def digest(self) -> str:
        return canonical_digest(self)


def _event_from_dict(value: dict[str, object]) -> CanonicalEvent:
    raw_exchange = value.get("exchange_timestamp_ms")
    raw_instrument = value.get("instrument_name")
    raw_elapsed = value.get("collector_elapsed_ms")
    if raw_elapsed is None:
        raise ValueError("capture event has no collector elapsed time")
    return CanonicalEvent(
        capture_seq=int(str(value["capture_seq"])),
        collector_received_at_ms=int(str(value["collector_received_at_ms"])),
        collector_elapsed_ms=int(str(raw_elapsed)),
        exchange_timestamp_ms=(int(str(raw_exchange)) if raw_exchange is not None else None),
        channel=str(value["channel"]),
        event_kind=EventKind(str(value["event_kind"])),
        instrument_name=(str(raw_instrument) if raw_instrument is not None else None),
        raw_payload=str(value["raw_payload"]),
    )


def _encoded_event(event: CanonicalEvent) -> bytes:
    return (
        json.dumps(
            canonical_value(event),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def _event_content(
    events: tuple[CanonicalEvent, ...],
) -> tuple[int, int, int, str]:
    if not events:
        raise ValueError("capture cannot be empty")
    hasher = hashlib.sha256()
    previous_elapsed_ms: int | None = None
    for expected_capture_seq, event in enumerate(events, start=1):
        if event.capture_seq != expected_capture_seq:
            raise ValueError("capture events must be contiguous and start at one")
        if previous_elapsed_ms is not None and event.collector_elapsed_ms < previous_elapsed_ms:
            raise ValueError("capture collector elapsed time must be nondecreasing")
        previous_elapsed_ms = event.collector_elapsed_ms
        hasher.update(_encoded_event(event))
    return len(events), events[0].capture_seq, events[-1].capture_seq, hasher.hexdigest()


def validate_capture(
    manifest: CaptureManifest,
    events: tuple[CanonicalEvent, ...],
) -> None:
    """Bind one manifest to the exact canonical facts supplied by its caller."""

    if manifest.format_id != CAPTURE_FORMAT_ID:
        raise ValueError(f"unsupported capture format: {manifest.format_id}")
    count, first_capture_seq, last_capture_seq, content_sha256 = _event_content(events)
    if (
        manifest.record_count != count
        or manifest.first_capture_seq != first_capture_seq
        or manifest.last_capture_seq != last_capture_seq
    ):
        raise ValueError("capture manifest and event sequence disagree")
    if manifest.content_sha256 != content_sha256:
        raise ValueError("capture manifest and canonical events digest disagree")


def write_capture(
    root: Path,
    events: Iterable[CanonicalEvent],
    *,
    complete: bool,
    incomplete_reasons: tuple[str, ...] = (),
) -> CaptureManifest:
    captured_events = tuple(events)
    count, first_capture_seq, last_capture_seq, content_sha256 = _event_content(captured_events)
    manifest = CaptureManifest(
        format_id=CAPTURE_FORMAT_ID,
        record_count=count,
        first_capture_seq=first_capture_seq,
        last_capture_seq=last_capture_seq,
        content_sha256=content_sha256,
        complete=complete,
        incomplete_reasons=incomplete_reasons,
        data_path="capture.jsonl",
    )
    validate_capture(manifest, captured_events)
    if root.exists() and any(root.iterdir()):
        raise ValueError("capture output directory must be empty or absent")
    root.mkdir(parents=True, exist_ok=True)
    data_path = root / manifest.data_path
    with data_path.open("wb") as handle:
        for event in captured_events:
            handle.write(_encoded_event(event))
    (root / "manifest.json").write_text(
        json.dumps(canonical_value(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def read_capture(root: Path) -> tuple[CaptureManifest, tuple[CanonicalEvent, ...]]:
    raw_manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(raw_manifest, dict):
        raise ValueError("capture manifest root must be an object")
    value = cast(dict[str, object], raw_manifest)
    raw_format_id = value.get("format_id")
    if raw_format_id != CAPTURE_FORMAT_ID:
        raise ValueError(f"unsupported capture format: {raw_format_id}")
    raw_reasons = value.get("incomplete_reasons", [])
    if not isinstance(raw_reasons, list):
        raise ValueError("capture incomplete reasons must be an array")
    raw_complete = value.get("complete")
    if not isinstance(raw_complete, bool):
        raise ValueError("capture manifest complete must be boolean")
    manifest = CaptureManifest(
        format_id=CAPTURE_FORMAT_ID,
        record_count=int(str(value["record_count"])),
        first_capture_seq=int(str(value["first_capture_seq"])),
        last_capture_seq=int(str(value["last_capture_seq"])),
        content_sha256=str(value["content_sha256"]),
        complete=raw_complete,
        incomplete_reasons=tuple(str(item) for item in raw_reasons),
        data_path=str(value["data_path"]),
    )
    data = (root / manifest.data_path).read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest.content_sha256:
        raise ValueError("capture content digest changed")
    events: list[CanonicalEvent] = []
    for raw_line in data.decode("utf-8").splitlines():
        if not raw_line:
            continue
        raw_event = json.loads(raw_line)
        if not isinstance(raw_event, dict):
            raise ValueError("capture event root must be an object")
        events.append(_event_from_dict(cast(dict[str, object], raw_event)))
    captured_events = tuple(events)
    validate_capture(manifest, captured_events)
    return manifest, captured_events
