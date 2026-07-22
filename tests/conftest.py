from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from market_tape import CanonicalEvent, EventKind

EventFactory = Callable[..., CanonicalEvent]


@pytest.fixture
def event_factory() -> EventFactory:
    def build(
        capture_seq: int,
        event_kind: EventKind,
        *,
        at_ms: int | None = None,
        elapsed_ms: int | None = None,
        instrument_name: str | None = None,
        payload: dict[str, object] | None = None,
        channel: str = "test",
    ) -> CanonicalEvent:
        timestamp = at_ms or int(datetime(2026, 7, 20, tzinfo=UTC).timestamp() * 1_000)
        return CanonicalEvent(
            capture_seq=capture_seq,
            collector_received_at_ms=timestamp,
            collector_elapsed_ms=(timestamp if elapsed_ms is None else elapsed_ms),
            exchange_timestamp_ms=timestamp,
            channel=channel,
            event_kind=event_kind,
            instrument_name=instrument_name,
            raw_payload=json.dumps(
                payload or {},
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    return build
