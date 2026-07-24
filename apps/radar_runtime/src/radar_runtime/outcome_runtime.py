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
    CAPTURE_FORMAT_ID,
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
from short_vol_radar import DecisionInputContract, RadarProjector
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect
from websockets.sync.connection import Connection

from radar_runtime.deribit_public import (
    CAPTURE_RECEIPT_TYPE,
    LIVE_CAPTURE_EVIDENCE,
    WEBSOCKET_URL,
    RadarProjection,
    _event_summary,
    _handle_message,
    _instrument_rows,
    _LiveSession,
    _message,
    _object,
    _public_result,
    _refresh_catalog,
    _rpc,
    _subscribe,
    _wait_result,
    build_decision_receipt,
    decision_receipt_payload,
    inspect_payload,
    project_events,
    projection_payload,
    select_btc_usdc_catalog,
)
from radar_runtime.fixture import REFERENCE, build_fixture_events
from radar_runtime.outcome_identity import (
    OutcomeRuntimeSourceIdentity,
    outcome_runtime_source_identity,
)
from radar_runtime.outcome_seal import (
    REQUIRED_INITIAL_STREAMS,
    decision_cutoff,
    read_sealed_capture,
    seal_capture,
)
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
PUBLIC_COLLECTOR_ENTRYPOINT_ID = "OUTCOME_BOUND_DERIBIT_PUBLIC_COLLECTOR"
FUTURE_PLATFORM_PROBE_ID = "POST_CUTOFF_PLATFORM_RESUBSCRIBE_THEN_STATUS"
PUBLIC_INITIAL_CONNECTION_TIMEOUT_SECONDS = 60
PUBLIC_INVOCATION_FIELDS = frozenset(
    {
        "receipt_type",
        "environment",
        "transport_endpoint",
        "collector_entrypoint_id",
        "future_platform_probe_id",
        "requested_duration_seconds",
        "invocation_started_at",
        "invocation_finished_at",
        "invocation_elapsed_ms",
        "records",
        "capture_digest",
        "capture_manifest_digest",
        "future_platform_subscription_capture_seq",
        "future_platform_status_capture_seq",
        "collector_live_sha256",
        "collector_decision_sha256",
        "collector_inspect_sha256",
        "git_commit_sha",
        "runtime_source_id",
        "runtime_source_digest",
        "outcome_runtime_source_id",
        "outcome_runtime_source_digest",
        "invocation_digest",
    }
)


@dataclass(frozen=True, slots=True)
class _Composition:
    result: dict[str, object]
    decision_receipt: dict[str, object]
    entry_receipt: dict[str, object] | None
    outcome_receipt: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class _PublicCollectorRun:
    live: dict[str, object]
    platform_subscription_capture_seq: int
    platform_status_capture_seq: int


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


def _is_git_commit_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


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


class _OutcomeLiveSession(_LiveSession):
    """Decision-compatible session with one Outcome-only platform subscription fact."""

    def record_outcome_platform_subscription_start(
        self,
        *,
        received_at_ms: int,
        elapsed_ms: int,
        request_id: int | None = None,
        platform_acquisition_ordinal: int | None = None,
        obligation_id: str | None = None,
        connection_generation: int | None = None,
    ) -> CanonicalEvent:
        payload: dict[str, object] = {
            "stream": "platform_state",
            "channel": "platform_state",
        }
        if request_id is not None:
            payload.update(
                {
                    "request_id": request_id,
                    "platform_acquisition_ordinal": platform_acquisition_ordinal,
                    "obligation_id": obligation_id,
                    "connection_generation": connection_generation,
                }
            )
        event = self._record(
            EventKind.SUBSCRIPTION_START,
            "control",
            payload,
            received_at_ms=received_at_ms,
            elapsed_ms=elapsed_ms,
        )
        self._platform_maintenance = None
        self._platform_maintenance_capture_seq = None
        self._platform_index_locked = None
        self._platform_index_capture_seq = None
        self._platform_status_capture_seq = None
        self._platform_subscription_capture_seq = event.capture_seq
        return event


class _DeadlineConnection:
    """Clamp every collector receive to one absolute process deadline."""

    def __init__(self, connection: Connection, deadline: float) -> None:
        self._connection = connection
        self.deadline = deadline

    def send(self, value: str) -> None:
        self._connection.send(value)

    def recv(self, *, timeout: float) -> str | bytes:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Outcome public collector deadline elapsed")
        value = self._connection.recv(timeout=min(timeout, remaining))
        if not isinstance(value, (str, bytes)):
            raise RuntimeError("Deribit WebSocket message must be text or bytes")
        return value


def _initial_decision_cutoff_target_elapsed_ms(
    events: list[CanonicalEvent],
    input_contract: DecisionInputContract,
) -> int:
    subscriptions: dict[str, CanonicalEvent] = {}
    for event in events:
        if event.event_kind is not EventKind.SUBSCRIPTION_START:
            continue
        payload: object = json.loads(event.raw_payload)
        if not isinstance(payload, dict):
            continue
        stream = payload.get("stream")
        if isinstance(stream, str) and stream in REQUIRED_INITIAL_STREAMS:
            subscriptions.setdefault(stream, event)
    if subscriptions.keys() < REQUIRED_INITIAL_STREAMS:
        raise RuntimeError("Outcome collector has no complete initial required subscriptions")
    origin_elapsed_ms = max(event.collector_elapsed_ms for event in subscriptions.values())
    return origin_elapsed_ms + max(input_contract.required_windows_seconds) * 1_000


def _future_platform_barrier_capture_seqs(
    events: tuple[CanonicalEvent, ...],
) -> tuple[int, int]:
    cutoff_capture_seq = decision_cutoff(events).capture_seq
    subscription_capture_seq: int | None = None
    for event in events:
        if event.capture_seq <= cutoff_capture_seq:
            continue
        if event.event_kind is EventKind.RECONNECT:
            subscription_capture_seq = None
            continue
        payload: object = json.loads(event.raw_payload)
        if (
            event.event_kind is EventKind.SUBSCRIPTION_START
            and isinstance(payload, dict)
            and payload.get("stream") == "platform_state"
        ):
            subscription_capture_seq = event.capture_seq
            continue
        if (
            subscription_capture_seq is not None
            and event.event_kind is EventKind.PLATFORM_STATE
            and event.channel == "public/status"
            and event.capture_seq > subscription_capture_seq
            and isinstance(payload, dict)
            and payload.get("status_capture_seq") == event.capture_seq
        ):
            return subscription_capture_seq, event.capture_seq
    raise ValueError("production-public capture has no strict-future platform barrier")


def _validate_future_platform_barrier_capture_seqs(
    events: tuple[CanonicalEvent, ...],
    *,
    subscription_capture_seq: int,
    status_capture_seq: int,
) -> None:
    cutoff_capture_seq = decision_cutoff(events).capture_seq
    if not (
        cutoff_capture_seq < subscription_capture_seq < status_capture_seq <= events[-1].capture_seq
    ):
        raise ValueError("production-public future platform barrier sequence is invalid")
    subscription = events[subscription_capture_seq - 1]
    status = events[status_capture_seq - 1]
    subscription_payload: object = json.loads(subscription.raw_payload)
    status_payload: object = json.loads(status.raw_payload)
    status_sources = (
        status_payload.get("source_capture_seqs") if isinstance(status_payload, dict) else None
    )
    if (
        subscription.capture_seq != subscription_capture_seq
        or subscription.event_kind is not EventKind.SUBSCRIPTION_START
        or subscription.channel != "control"
        or not isinstance(subscription_payload, dict)
        or subscription_payload.get("stream") != "platform_state"
        or subscription_payload.get("channel") != "platform_state"
        or status.capture_seq != status_capture_seq
        or status.event_kind is not EventKind.PLATFORM_STATE
        or status.channel != "public/status"
        or not isinstance(status_payload, dict)
        or status_payload.get("status_capture_seq") != status_capture_seq
        or not (
            (status_payload.get("state") == "OPEN" and status_payload.get("locked") is False)
            or (status_payload.get("state") == "LOCKED" and status_payload.get("locked") is True)
        )
        or not isinstance(status_sources, list)
        or not all(type(item) is int for item in status_sources)
        or status_sources != sorted(set(status_sources))
        or subscription_capture_seq not in status_sources
        or any(
            source <= cutoff_capture_seq or source >= status_capture_seq
            for source in status_sources
        )
        or any(
            event.event_kind is EventKind.RECONNECT
            for event in events[subscription_capture_seq:status_capture_seq]
        )
    ):
        raise ValueError("production-public future platform barrier generation is invalid")


def _refresh_outcome_platform_barrier(
    connection: Connection,
    session: _OutcomeLiveSession,
    *,
    cutoff_capture_seq: int,
    request_id: int,
    test_request_id: int,
) -> tuple[int, int, int, int]:
    channels = ("platform_state",)
    _rpc(connection, request_id, "public/subscribe", {"channels": list(channels)})
    result, test_request_id, subscription_clock = _wait_result(
        connection,
        session,
        request_id,
        test_request_id=test_request_id,
    )
    if not isinstance(result, list) or set(str(item) for item in result) != set(channels):
        raise RuntimeError("Outcome platform subscription refresh was not accepted")
    subscription = session.record_outcome_platform_subscription_start(
        received_at_ms=subscription_clock.received_at_ms,
        elapsed_ms=subscription_clock.elapsed_ms,
    )
    if subscription.capture_seq <= cutoff_capture_seq:
        raise RuntimeError("Outcome platform subscription is not strictly after Decision cutoff")
    request_id += 1
    _rpc(connection, request_id, "public/status", {})
    status_result, test_request_id, status_clock = _wait_result(
        connection,
        session,
        request_id,
        test_request_id=test_request_id,
    )
    status = _object(status_result, "Deribit public status")
    session.record_platform(
        status,
        channel="public/status",
        received_at_ms=status_clock.received_at_ms,
        elapsed_ms=status_clock.elapsed_ms,
    )
    if session.events[-1].capture_seq <= subscription.capture_seq:
        raise RuntimeError("Outcome platform status did not follow its subscription")
    return (
        request_id + 1,
        test_request_id,
        subscription.capture_seq,
        session.events[-1].capture_seq,
    )


def _record_connection_attempt_failure(
    session: _OutcomeLiveSession,
    *,
    attempt_start_event_count: int,
    active_connection: bool,
    error: BaseException,
) -> bool:
    if not active_connection and len(session.events) == attempt_start_event_count:
        return False
    reconnect_clock = session.clock_sample()
    session.record_reconnect(
        type(error).__name__,
        received_at_ms=reconnect_clock.received_at_ms,
        elapsed_ms=reconnect_clock.elapsed_ms,
    )
    return True


def _run_public_outcome_collector(
    output: Path,
    duration_seconds: int,
    *,
    source_identity: RuntimeSourceIdentity,
) -> _PublicCollectorRun:
    """Run the unchanged Decision canonicalizer plus one post-cutoff platform proof."""

    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if output.exists() and any(output.iterdir()):
        raise ValueError("capture output directory must be empty or absent")
    input_contract = DecisionInputContract()
    session = _OutcomeLiveSession()
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
    catalog_market_at_ms = max(option_catalog.server_at_ms, future_catalog.server_at_ms)
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
    option_names = tuple(str(row["instrument_name"]) for row in selected[1:])
    channels = (
        f"ticker.{REFERENCE}.agg2",
        f"trades.{REFERENCE}.agg2",
        "platform_state",
        *(f"ticker.{name}.agg2" for name in option_names),
    )
    deadline: float | None = None
    next_catalog_refresh: float | None = None
    active_connection = False
    future_platform_probe_complete = False
    probe_subscription_capture_seq: int | None = None
    probe_status_capture_seq: int | None = None
    cutoff_target_elapsed_ms: int | None = None
    while deadline is None or time.monotonic() < deadline:
        attempt_start_event_count = len(session.events)
        try:
            with connect(
                WEBSOCKET_URL,
                open_timeout=10,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=20,
                max_size=None,
                max_queue=1_024,
                proxy=None,
            ) as raw_connection:
                receive_deadline = (
                    deadline
                    if deadline is not None
                    else time.monotonic() + PUBLIC_INITIAL_CONNECTION_TIMEOUT_SECONDS
                )
                guarded_connection = _DeadlineConnection(raw_connection, receive_deadline)
                connection = cast(Connection, guarded_connection)
                test_request_id = _subscribe(connection, session, channels)
                _rpc(connection, 3, "public/status", {})
                status_result, test_request_id, status_clock = _wait_result(
                    connection,
                    session,
                    3,
                    test_request_id=test_request_id,
                )
                session.record_platform(
                    _object(status_result, "Deribit public status"),
                    channel="public/status",
                    received_at_ms=status_clock.received_at_ms,
                    elapsed_ms=status_clock.elapsed_ms,
                )
                active_connection = True
                if deadline is None:
                    deadline = time.monotonic() + duration_seconds
                    guarded_connection.deadline = deadline
                    next_catalog_refresh = time.monotonic() + input_contract.catalog_refresh_seconds
                    cutoff_target_elapsed_ms = _initial_decision_cutoff_target_elapsed_ms(
                        session.events,
                        input_contract,
                    )
                request_id = 10
                while time.monotonic() < deadline:
                    if (
                        not future_platform_probe_complete
                        and cutoff_target_elapsed_ms is not None
                        and session.events[-1].collector_elapsed_ms >= cutoff_target_elapsed_ms
                    ):
                        cutoff_capture_seq = decision_cutoff(tuple(session.events)).capture_seq
                        (
                            request_id,
                            test_request_id,
                            probe_subscription_capture_seq,
                            probe_status_capture_seq,
                        ) = _refresh_outcome_platform_barrier(
                            connection,
                            session,
                            cutoff_capture_seq=cutoff_capture_seq,
                            request_id=request_id,
                            test_request_id=test_request_id,
                        )
                        future_platform_probe_complete = True
                        continue
                    if (
                        next_catalog_refresh is not None
                        and time.monotonic() >= next_catalog_refresh
                    ):
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
                        next_catalog_refresh = (
                            time.monotonic() + input_contract.catalog_refresh_seconds
                        )
                        continue
                    remaining = deadline - time.monotonic()
                    try:
                        received = _message(connection, session, min(1.0, remaining))
                    except TimeoutError:
                        continue
                    test_request_id = _handle_message(
                        connection,
                        session,
                        received.value,
                        received_at_ms=received.clock.received_at_ms,
                        elapsed_ms=received.clock.elapsed_ms,
                        test_request_id=test_request_id,
                    )
        except (ConnectionClosed, InvalidStatus, OSError, TimeoutError) as error:
            if deadline is None:
                raise RuntimeError("initial Deribit public connection failed") from error
            _record_connection_attempt_failure(
                session,
                attempt_start_event_count=attempt_start_event_count,
                active_connection=active_connection,
                error=error,
            )
            active_connection = False
            if time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))
    if not future_platform_probe_complete:
        raise RuntimeError("capture ended before the post-cutoff platform proof was observed")
    if probe_subscription_capture_seq is None or probe_status_capture_seq is None:
        raise RuntimeError("Outcome platform proof sequence was not retained")
    projection = session.live_projection()
    output.mkdir(parents=True, exist_ok=True)
    manifest = write_capture(output / "capture", session.events, complete=True)
    events = tuple(session.events)
    decision_receipt = build_decision_receipt(
        manifest,
        projection,
        source_identity=source_identity,
    )
    result = {
        "receipt_type": CAPTURE_RECEIPT_TYPE,
        "environment": "production_public",
        "duration_seconds": duration_seconds,
        **_event_summary(manifest, events),
        **projection_payload(projection),
        "decision_receipt_digest": decision_receipt.digest,
        "git_commit_sha": source_identity.git_commit_sha,
        "runtime_source_id": source_identity.runtime_source_id,
        "runtime_source_digest": source_identity.runtime_source_digest,
        "evidence_class": LIVE_CAPTURE_EVIDENCE,
    }
    _write_json(output / "decision.json", decision_receipt_payload(decision_receipt))
    _write_json(output / "live.json", result)
    return _PublicCollectorRun(
        live=result,
        platform_subscription_capture_seq=probe_subscription_capture_seq,
        platform_status_capture_seq=probe_status_capture_seq,
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
                "source_capture_seqs": [sequence - 1],
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
    if (
        events
        and events[-1].capture_seq > position.entry_capture_seq
        and events[-1].collector_elapsed_ms >= horizon_elapsed_ms
        and (not observations or observations[-1].frame.as_of_capture_seq != events[-1].capture_seq)
    ):
        final_frame = projector.finalize()
        snapshot = projector.reducer.snapshot(events[-1].collector_received_at_ms)
        observations.append(
            OutcomeObservation(
                frame=final_frame,
                platform_state=snapshot.platform_state,
                reconnect_capture_seq=snapshot.reconnect_capture_seq,
            )
        )
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
    collector_invocation_digest: str | None = None,
) -> _Composition:
    if (fact_provenance == "production_public") != (
        isinstance(collector_invocation_digest, str) and bool(collector_invocation_digest)
    ):
        raise ValueError("production-public facts require one collector invocation binding")
    if fact_provenance not in {"synthetic", "production_public"}:
        raise ValueError("Outcome fact provenance is invalid")
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
        "environment": (
            "production_public" if fact_provenance == "production_public" else "synthetic"
        ),
        "fact_provenance": fact_provenance,
        "evidence_class": evidence_class,
        "duration_seconds": duration_seconds,
        "capture_format_id": CAPTURE_FORMAT_ID,
        "capture_complete": full_manifest.complete,
        "records": full_manifest.record_count,
        "final_event_capture_seq": full_manifest.last_capture_seq,
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
        "decision_digest": projection.decision.digest,
        "decision_frame_capture_seq": projection.frame.as_of_capture_seq,
        "decision_frame_digest": projection.frame.digest,
        "decision_frame_complete": projection.frame.complete,
        "decision_readiness": projection_summary["decision_readiness"],
        "required_window_coverage": projection_summary["required_window_coverage"],
        "candidate_count": projection_summary["research_candidate_count"],
        "assessment_count": projection_summary["assessment_count"],
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
        "collector_invocation_digest": collector_invocation_digest,
        "git_commit_sha": evidence_git_commit_sha,
        "decision_runtime_source_id": decision_identity.runtime_source_id,
        "decision_runtime_source_digest": decision_identity.runtime_source_digest,
        "outcome_runtime_source_id": outcome_identity.runtime_source_id,
        "outcome_runtime_source_digest": outcome_identity.runtime_source_digest,
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
        collector_run = _run_public_outcome_collector(
            temp,
            duration_seconds,
            source_identity=decision_identity,
        )
        live = collector_run.live
        invocation_finished_ns = time.monotonic_ns()
        invocation_finished_at = datetime.now(UTC)
        if live.get("duration_seconds") != duration_seconds:
            raise RuntimeError("collector duration binding changed")
        full_manifest, full_events = read_capture(temp / "capture")
        platform_subscription_seq = collector_run.platform_subscription_capture_seq
        platform_status_seq = collector_run.platform_status_capture_seq
        _validate_future_platform_barrier_capture_seqs(
            full_events,
            subscription_capture_seq=platform_subscription_seq,
            status_capture_seq=platform_status_seq,
        )
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
            "collector_entrypoint_id": PUBLIC_COLLECTOR_ENTRYPOINT_ID,
            "future_platform_probe_id": FUTURE_PLATFORM_PROBE_ID,
            "requested_duration_seconds": duration_seconds,
            "invocation_started_at": invocation_started_at.isoformat(),
            "invocation_finished_at": invocation_finished_at.isoformat(),
            "invocation_elapsed_ms": (invocation_finished_ns - invocation_started_ns) // 1_000_000,
            "records": full_manifest.record_count,
            "capture_digest": full_manifest.content_sha256,
            "capture_manifest_digest": full_manifest.digest,
            "future_platform_subscription_capture_seq": platform_subscription_seq,
            "future_platform_status_capture_seq": platform_status_seq,
            "collector_live_sha256": _sha256_file(output / "collector-live.json"),
            "collector_decision_sha256": _sha256_file(output / "collector-decision.json"),
            "collector_inspect_sha256": _sha256_file(output / "collector-inspect.json"),
            "git_commit_sha": outcome_identity.git_commit_sha,
            "runtime_source_id": decision_identity.runtime_source_id,
            "runtime_source_digest": decision_identity.runtime_source_digest,
            "outcome_runtime_source_id": outcome_identity.runtime_source_id,
            "outcome_runtime_source_digest": outcome_identity.runtime_source_digest,
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
            collector_invocation_digest=cast(str, invocation["invocation_digest"]),
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
        or not _typed_equal(expected[key], observed[key])
    ]


def _typed_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _typed_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _typed_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _optional_receipt(root: Path, name: str) -> dict[str, object] | None:
    path = root / name
    return _json_object(path, name) if path.is_file() else None


def _aware_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def validate_public_collector_artifacts(
    run_root: Path,
    result: dict[str, object],
) -> dict[str, object]:
    """Verify the bounded collector process witness and reconstruct its artifacts."""

    paths = {
        "live": run_root / "collector-live.json",
        "decision": run_root / "collector-decision.json",
        "inspect": run_root / "collector-inspect.json",
        "invocation": run_root / PUBLIC_INVOCATION_PATH,
    }
    if any(not path.is_file() for path in paths.values()):
        raise ValueError("production-public run is missing bounded collector artifacts")
    live = _json_object(paths["live"], "production-public collector live receipt")
    decision = _json_object(paths["decision"], "production-public collector Decision receipt")
    inspected = _json_object(paths["inspect"], "production-public collector inspect")
    invocation = _json_object(paths["invocation"], "production-public collector invocation")
    _seal, manifest, events, _prefix_manifest, _prefix_events = read_sealed_capture(
        run_root / FACTS_DIRECTORY
    )
    evidence_git_commit_sha = result.get("git_commit_sha")
    if not _is_git_commit_sha(evidence_git_commit_sha):
        raise ValueError("production-public evidence Git identity is invalid")
    assert isinstance(evidence_git_commit_sha, str)
    invocation_digest = invocation.get("invocation_digest")
    unsigned_invocation = {
        key: value for key, value in invocation.items() if key != "invocation_digest"
    }
    invocation_elapsed_ms = invocation.get("invocation_elapsed_ms")
    invocation_started_at = _aware_iso_datetime(invocation.get("invocation_started_at"))
    invocation_finished_at = _aware_iso_datetime(invocation.get("invocation_finished_at"))
    platform_subscription_seq = invocation.get("future_platform_subscription_capture_seq")
    platform_status_seq = invocation.get("future_platform_status_capture_seq")
    if (
        not isinstance(platform_subscription_seq, int)
        or isinstance(platform_subscription_seq, bool)
        or not isinstance(platform_status_seq, int)
        or isinstance(platform_status_seq, bool)
    ):
        raise ValueError("production-public collector platform witness is invalid")
    _validate_future_platform_barrier_capture_seqs(
        events,
        subscription_capture_seq=platform_subscription_seq,
        status_capture_seq=platform_status_seq,
    )
    if (
        invocation.keys() != PUBLIC_INVOCATION_FIELDS
        or not isinstance(invocation_digest, str)
        or canonical_digest(unsigned_invocation) != invocation_digest
        or result.get("collector_invocation_digest") != invocation_digest
        or invocation.get("receipt_type") != PUBLIC_INVOCATION_RECEIPT_TYPE
        or invocation.get("environment") != "production_public"
        or invocation.get("transport_endpoint") != WEBSOCKET_URL
        or invocation.get("collector_entrypoint_id") != PUBLIC_COLLECTOR_ENTRYPOINT_ID
        or invocation.get("future_platform_probe_id") != FUTURE_PLATFORM_PROBE_ID
        or type(invocation.get("requested_duration_seconds")) is not int
        or invocation.get("requested_duration_seconds") != PUBLIC_CAPTURE_SECONDS
        or not isinstance(invocation_elapsed_ms, int)
        or isinstance(invocation_elapsed_ms, bool)
        or invocation_elapsed_ms < PUBLIC_CAPTURE_SECONDS * 1_000
        or events[-1].collector_elapsed_ms > invocation_elapsed_ms
        or invocation_started_at is None
        or invocation_finished_at is None
        or type(invocation.get("records")) is not int
        or invocation.get("records") != manifest.record_count
        or invocation.get("capture_digest") != manifest.content_sha256
        or invocation.get("capture_manifest_digest") != manifest.digest
        or invocation.get("collector_live_sha256") != _sha256_file(paths["live"])
        or invocation.get("collector_decision_sha256") != _sha256_file(paths["decision"])
        or invocation.get("collector_inspect_sha256") != _sha256_file(paths["inspect"])
        or invocation.get("git_commit_sha") != evidence_git_commit_sha
        or invocation.get("runtime_source_id") != result.get("decision_runtime_source_id")
        or invocation.get("runtime_source_digest") != result.get("decision_runtime_source_digest")
        or invocation.get("outcome_runtime_source_id") != result.get("outcome_runtime_source_id")
        or invocation.get("outcome_runtime_source_digest")
        != result.get("outcome_runtime_source_digest")
    ):
        raise ValueError("production-public collector invocation witness is invalid")
    current_decision_identity = runtime_source_identity(require_clean=False)
    bound_decision_identity = replace(
        current_decision_identity,
        git_commit_sha=evidence_git_commit_sha,
        dirty_paths=(),
    )
    if bound_decision_identity.runtime_source_id != result.get(
        "decision_runtime_source_id"
    ) or bound_decision_identity.runtime_source_digest != result.get(
        "decision_runtime_source_digest"
    ):
        raise ValueError("production-public Decision runtime identity changed")
    current_outcome_identity = outcome_runtime_source_identity(require_clean=False)
    if current_outcome_identity.runtime_source_id != result.get(
        "outcome_runtime_source_id"
    ) or current_outcome_identity.runtime_source_digest != result.get(
        "outcome_runtime_source_digest"
    ):
        raise ValueError("production-public Outcome runtime identity changed")
    projection = project_events(events)
    expected_decision_receipt = build_decision_receipt(
        manifest,
        projection,
        source_identity=bound_decision_identity,
        receipt_git_commit_sha=evidence_git_commit_sha,
    )
    if not _typed_equal(decision, decision_receipt_payload(expected_decision_receipt)):
        raise ValueError("production-public collector Decision receipt is not reconstructed")
    expected_inspect = inspect_payload(
        manifest,
        events,
        source_identity=bound_decision_identity,
    )
    if not _typed_equal(inspected, expected_inspect):
        raise ValueError("production-public collector inspect is not reconstructed")
    expected_live = {
        "receipt_type": CAPTURE_RECEIPT_TYPE,
        "environment": "production_public",
        "duration_seconds": PUBLIC_CAPTURE_SECONDS,
        **_event_summary(manifest, events),
        **projection_payload(projection),
        "decision_receipt_digest": expected_decision_receipt.digest,
        "git_commit_sha": evidence_git_commit_sha,
        "runtime_source_id": bound_decision_identity.runtime_source_id,
        "runtime_source_digest": bound_decision_identity.runtime_source_digest,
        "evidence_class": LIVE_CAPTURE_EVIDENCE,
    }
    if not _typed_equal(live, expected_live):
        raise ValueError("production-public collector live receipt is not reconstructed")
    return invocation


def reconstruct_outcome(run_root: Path) -> dict[str, object]:
    """Rebuild one persisted run without live state or output-side effects."""

    source_result = _json_object(run_root / RESULT_PATH, "Outcome result")
    source_digest = source_result.get("result_digest")
    unsigned_source = {key: value for key, value in source_result.items() if key != "result_digest"}
    if not isinstance(source_digest, str) or canonical_digest(unsigned_source) != source_digest:
        raise ValueError("Outcome result digest changed")
    provenance = source_result.get("fact_provenance")
    evidence_git_commit_sha = source_result.get("git_commit_sha")
    if provenance not in {"synthetic", "production_public"} or not _is_git_commit_sha(
        evidence_git_commit_sha
    ):
        raise ValueError("Outcome result replay metadata is invalid")
    assert isinstance(evidence_git_commit_sha, str)
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
        collector_invocation_digest = None
        if source_result.get("collector_invocation_digest") is not None:
            raise ValueError("synthetic Outcome cannot claim a collector invocation")
    else:
        evidence_class = PUBLIC_EVIDENCE_CLASS
        duration_seconds = PUBLIC_CAPTURE_SECONDS
        invocation = validate_public_collector_artifacts(run_root, source_result)
        raw_invocation_digest = invocation.get("invocation_digest")
        if not isinstance(raw_invocation_digest, str):
            raise ValueError("production-public collector invocation digest is missing")
        collector_invocation_digest = raw_invocation_digest
    if (
        source_result.get("evidence_class") != evidence_class
        or source_result.get("duration_seconds") != duration_seconds
        or source_result.get("environment")
        != ("production_public" if provenance == "production_public" else "synthetic")
        or source_result.get("capture_format_id") != CAPTURE_FORMAT_ID
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
        collector_invocation_digest=collector_invocation_digest,
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
        "computation_reconstructed": True,
        "collector_witness_verified": provenance == "production_public",
        "external_source_attested": False,
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
        "collector_invocation_digest": collector_invocation_digest,
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
