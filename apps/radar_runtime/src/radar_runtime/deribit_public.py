"""Bounded Deribit production-public capture for the Short Vol radar."""

from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from market_tape import (
    CanonicalEvent,
    CaptureManifest,
    EventKind,
    MarketTapeReducer,
    canonical_value,
    validate_capture,
    write_capture,
)
from short_vol_radar import (
    DecisionFrame,
    RadarAction,
    RadarDecision,
    RadarProjector,
    evaluate_radar,
)
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect
from websockets.sync.connection import Connection

REFERENCE = "BTC_USDC-PERPETUAL"
REST_ROOT = "https://www.deribit.com/api/v2/public"
WEBSOCKET_URL = "wss://www.deribit.com/ws/api/v2"
MAX_OPTION_TTE_MS = 72 * 3_600 * 1_000
HEARTBEAT_SECONDS = 10
TIMESTAMP_CONTRACT_ID = "CAPTURE_SEQUENCE_WITH_PERSISTED_ELAPSED"
ELAPSED_SOURCE_ID = "PERSISTED_MONOTONIC"
PLATFORM_STATE_CONTRACT_ID = "CONNECTION_GENERATION_SCOPED_STATUS"
UNPROVEN_PLATFORM_STATE_CONTRACT_ID = "PLATFORM_STATUS_BARRIER_UNPROVEN"
CAPTURE_RECEIPT_TYPE = "DERIBIT_PUBLIC_RADAR_CAPTURE"
LIVE_CAPTURE_EVIDENCE = "BOUNDED_PRODUCTION_PUBLIC_CAPTURE"
LIVE_REPLAY_EVIDENCE = "BOUNDED_PRODUCTION_PUBLIC_LIVE_REPLAY"
SEALED_REPLAY_EVIDENCE = "CANONICAL_CAPTURE_REPLAY"
UNPROVEN_PLATFORM_REPLAY_EVIDENCE = "PLATFORM_STATUS_BARRIER_REPLAY_ONLY"


@dataclass(frozen=True, slots=True)
class _ClockSample:
    received_at_ms: int
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class _PublicResponse:
    result: object
    clock: _ClockSample
    server_at_ms: int


@dataclass(frozen=True, slots=True)
class _ReceivedMessage:
    value: dict[str, object]
    clock: _ClockSample


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _integer(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return value


def _required_decimal_value(
    value: object,
    field: str,
    *,
    allow_zero: bool = False,
) -> object:
    if value is None or isinstance(value, bool):
        raise ValueError(f"Deribit instrument has no valid {field}")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Deribit instrument has no valid {field}") from error
    if not parsed.is_finite() or parsed < 0 or (parsed == 0 and not allow_zero):
        raise ValueError(f"Deribit instrument has no valid {field}")
    return value


def _deribit_server_at_ms(envelope: Mapping[str, object]) -> int:
    us_out = _integer(envelope.get("usOut"))
    if us_out is None:
        raise RuntimeError("Deribit public REST response has no valid usOut timestamp")
    return us_out // 1_000


def _payload(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _public_result(
    method: str,
    params: Mapping[str, str],
    session: _LiveSession,
) -> _PublicResponse:
    if method not in {"get_instruments", "status"}:
        raise ValueError("unsupported Deribit public REST method")
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{REST_ROOT}/{method}{query}",
        headers={"User-Agent": "Optimatrix-public-shadow"},
    )
    with urlopen(request, timeout=20) as response:
        raw = response.read()
        clock = session.clock_sample()
    decoded: object = json.loads(raw)
    envelope = _object(decoded, "Deribit REST response")
    if "error" in envelope:
        raise RuntimeError(f"Deribit public REST error: {envelope['error']}")
    if "result" not in envelope:
        raise RuntimeError("Deribit public REST response has no result")
    return _PublicResponse(envelope["result"], clock, _deribit_server_at_ms(envelope))


def _instrument_rows(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError("Deribit instrument catalog must be an array")
    return tuple(_object(item, "Deribit instrument") for item in value)


def select_btc_usdc_catalog(
    option_rows: Iterable[Mapping[str, object]],
    future_rows: Iterable[Mapping[str, object]],
    *,
    as_of_ms: int,
) -> tuple[dict[str, object], ...]:
    """Select exactly the active BTC-USDC perpetual and 0-72h linear options."""

    selected: list[dict[str, object]] = []
    reference = next(
        (
            row
            for row in future_rows
            if row.get("instrument_name") == REFERENCE
            and row.get("base_currency") == "BTC"
            and row.get("counter_currency") == "USDC"
            and row.get("is_active") is True
        ),
        None,
    )
    if reference is None:
        raise RuntimeError(f"Deribit public catalog has no active {REFERENCE}")
    selected.append(dict(reference))
    options = []
    for row in option_rows:
        expiry = _integer(row.get("expiration_timestamp"))
        if (
            row.get("kind") != "option"
            or row.get("base_currency") != "BTC"
            or row.get("counter_currency") != "USDC"
            or row.get("instrument_type") != "linear"
            or row.get("is_active") is not True
            or expiry is None
            or not as_of_ms < expiry <= as_of_ms + MAX_OPTION_TTE_MS
        ):
            continue
        options.append(dict(row))
    selected.extend(sorted(options, key=lambda row: str(row["instrument_name"])))
    return tuple(selected)


def _canonical_instrument(row: Mapping[str, object]) -> dict[str, object]:
    name = str(row.get("instrument_name", ""))
    if not name:
        raise ValueError("Deribit instrument has no instrument_name")
    active = row.get("is_active")
    if not isinstance(active, bool):
        raise ValueError("Deribit instrument has no valid is_active")
    contract_size = _required_decimal_value(row.get("contract_size"), "contract_size")
    minimum = _required_decimal_value(row.get("min_trade_amount"), "min_trade_amount")
    taker_commission = _required_decimal_value(
        row.get("taker_commission"),
        "taker_commission",
        allow_zero=True,
    )
    value: dict[str, object] = {
        "instrument_name": name,
        "kind": "perpetual" if name == REFERENCE else "option",
        "active": active,
        "contract_size": contract_size,
        "min_trade_amount": minimum,
        "amount_step": minimum,
        "taker_commission": taker_commission,
    }
    if name != REFERENCE:
        expiry = _integer(row.get("expiration_timestamp"))
        if expiry is None:
            raise ValueError("Deribit option has no valid expiration_timestamp")
        strike = _required_decimal_value(row.get("strike"), "strike")
        option_type = row.get("option_type")
        if option_type not in {"call", "put"}:
            raise ValueError("Deribit option has no valid option_type")
        value.update(
            {
                "expiration_timestamp": expiry,
                "strike": strike,
                "option_type": option_type,
            }
        )
    return value


def _status_locked(payload: Mapping[str, object]) -> bool:
    raw = payload.get("locked")
    if raw is False or raw == "false":
        return False
    if raw is True or raw == "true":
        return True
    if raw != "partial":
        raise ValueError("Deribit public status has no valid locked state")
    raw_indices = payload.get("locked_indices")
    raw_currencies = payload.get("locked_currencies")
    if raw_indices is None and raw_currencies is None:
        raise ValueError("Deribit partial public status has no lock scope")
    if raw_indices is not None and (
        not isinstance(raw_indices, list) or not all(isinstance(item, str) for item in raw_indices)
    ):
        raise ValueError("Deribit public status has no valid locked_indices")
    if raw_currencies is not None and (
        not isinstance(raw_currencies, list)
        or not all(isinstance(item, str) for item in raw_currencies)
    ):
        raise ValueError("Deribit public status has no valid locked_currencies")
    indices = raw_indices if isinstance(raw_indices, list) else []
    currencies = raw_currencies if isinstance(raw_currencies, list) else []
    if not indices and not currencies:
        raise ValueError("Deribit partial public status has empty lock scope")
    return "btc_usdc" in indices or bool({"BTC", "USDC"}.intersection(currencies))


def _complete_60m(frame: DecisionFrame) -> bool:
    window = frame.window(3_600)
    return bool(
        window is not None
        and window.coverage.price_complete
        and window.coverage.trade_complete
        and window.path is not None
        and window.flow is not None
    )


@dataclass(frozen=True, slots=True)
class RadarProjection:
    final_event_capture_seq: int
    frame: DecisionFrame
    decision: RadarDecision
    current_complete_60m: bool
    ever_observed_complete_60m: bool


def project_events(events: Iterable[CanonicalEvent]) -> RadarProjection:
    """Independently project one capture using the fixed production RadarPolicy."""

    projector = RadarProjector()
    final_event_capture_seq: int | None = None
    ever_observed_complete_60m = False
    for event in events:
        final_event_capture_seq = event.capture_seq
        frame = projector.ingest(event)
        ever_observed_complete_60m = ever_observed_complete_60m or bool(
            frame is not None and _complete_60m(frame)
        )
    if final_event_capture_seq is None:
        raise RuntimeError("capture produced no canonical event")
    current = projector.finalize()
    ever_observed_complete_60m = ever_observed_complete_60m or _complete_60m(current)
    return RadarProjection(
        final_event_capture_seq=final_event_capture_seq,
        frame=current,
        decision=evaluate_radar(current),
        current_complete_60m=_complete_60m(current),
        ever_observed_complete_60m=ever_observed_complete_60m,
    )


def projection_payload(projection: RadarProjection) -> dict[str, object]:
    frame = projection.frame
    decision = projection.decision
    window = frame.window(3_600)
    frame_lineage_violations = sum(
        capture_seq > frame.as_of_capture_seq for capture_seq in frame.source_capture_seqs
    )
    return {
        "final_event_capture_seq": projection.final_event_capture_seq,
        "frame_capture_seq": frame.as_of_capture_seq,
        "current_frame_is_final_event": (
            frame.as_of_capture_seq == projection.final_event_capture_seq
        ),
        "frame_digest": frame.digest,
        "frame_lineage_order": ("VERIFIED" if frame_lineage_violations == 0 else "VIOLATION"),
        "frame_lineage_violations": frame_lineage_violations,
        "decision_action": decision.action.value,
        "decision_reason": decision.reason,
        "decision_digest": decision.digest,
        "evaluated_structure_id": decision.selected_candidate_id,
        "research_candidate_emitted": (decision.action is RadarAction.RESEARCH_CANDIDATE),
        "research_candidate_count": int(decision.action is RadarAction.RESEARCH_CANDIDATE),
        "horizon_seconds": decision.horizon_seconds,
        "platform_state": frame.platform_state,
        "platform_locked": frame.platform_locked,
        "current_complete_60m": projection.current_complete_60m,
        "ever_observed_complete_60m": projection.ever_observed_complete_60m,
        "market_requested_start_at": (
            window.coverage.requested_market_start_at.isoformat()
            if window is not None and window.coverage.requested_market_start_at is not None
            else None
        ),
        "market_as_of": (
            window.coverage.market_as_of.isoformat()
            if window is not None and window.coverage.market_as_of is not None
            else None
        ),
        "price_market_anchor_at": (
            window.coverage.price_market_anchor_at.isoformat()
            if window is not None and window.coverage.price_market_anchor_at is not None
            else None
        ),
        "price_market_endpoint_at": (
            window.coverage.price_market_endpoint_at.isoformat()
            if window is not None and window.coverage.price_market_endpoint_at is not None
            else None
        ),
        "price_market_lookback_seconds": (
            window.coverage.price_market_lookback_seconds if window is not None else 0
        ),
        "price_subscription_elapsed_seconds": (
            window.coverage.price_subscription_elapsed_seconds if window is not None else 0
        ),
        "trade_subscription_elapsed_seconds": (
            window.coverage.trade_subscription_elapsed_seconds if window is not None else 0
        ),
        "price_watermark_progress_age_ms": (
            window.coverage.price_watermark_progress_age_ms if window is not None else None
        ),
        "window_incomplete_reasons": (
            list(window.coverage.incomplete_reasons) if window is not None else ["NO_60M_WINDOW"]
        ),
    }


def _has_generation_scoped_platform_status(events: tuple[CanonicalEvent, ...]) -> bool:
    platform_subscription_capture_seq: int | None = None
    platform_status_capture_seq: int | None = None
    barrier_complete = False
    for event in events:
        if event.event_kind is EventKind.RECONNECT:
            platform_subscription_capture_seq = None
            platform_status_capture_seq = None
            barrier_complete = False
            continue
        value: object = json.loads(event.raw_payload)
        if not isinstance(value, dict):
            continue
        if (
            event.event_kind is EventKind.SUBSCRIPTION_START
            and value.get("stream") == "platform_state"
        ):
            platform_subscription_capture_seq = event.capture_seq
            platform_status_capture_seq = None
            barrier_complete = False
        elif event.event_kind is EventKind.PLATFORM_STATE:
            status_capture_seq = value.get("status_capture_seq")
            if event.channel == "public/status":
                if status_capture_seq is None:
                    continue
                if (
                    not isinstance(status_capture_seq, int)
                    or isinstance(status_capture_seq, bool)
                    or status_capture_seq != event.capture_seq
                ):
                    return False
                if (
                    platform_subscription_capture_seq is not None
                    and status_capture_seq > platform_subscription_capture_seq
                ):
                    platform_status_capture_seq = status_capture_seq
                    barrier_complete = True
            elif (
                status_capture_seq is not None and status_capture_seq != platform_status_capture_seq
            ):
                return False
            if platform_status_capture_seq is None:
                barrier_complete = False
            elif platform_subscription_capture_seq is not None and (
                platform_status_capture_seq > platform_subscription_capture_seq
            ):
                barrier_complete = True
    return barrier_complete


def capture_evidence_metadata(
    manifest: CaptureManifest,
    events: tuple[CanonicalEvent, ...],
) -> dict[str, object]:
    validate_capture(manifest, events)
    generation_scoped_platform = _has_generation_scoped_platform_status(events)
    return {
        "capture_format": manifest.format_id,
        "capture_complete": manifest.complete,
        "timestamp_contract": TIMESTAMP_CONTRACT_ID,
        "collector_elapsed_source": ELAPSED_SOURCE_ID,
        "platform_state_contract": (
            PLATFORM_STATE_CONTRACT_ID
            if generation_scoped_platform
            else UNPROVEN_PLATFORM_STATE_CONTRACT_ID
        ),
        "evidence_class": (
            SEALED_REPLAY_EVIDENCE
            if generation_scoped_platform
            else UNPROVEN_PLATFORM_REPLAY_EVIDENCE
        ),
        "live_comparison_eligible": generation_scoped_platform and manifest.complete,
    }


def replay_payload(
    manifest: CaptureManifest,
    events: tuple[CanonicalEvent, ...],
    *,
    live: Mapping[str, object] | None = None,
) -> dict[str, object]:
    metadata = capture_evidence_metadata(manifest, events)
    projection = projection_payload(project_events(events))
    payload = {
        **metadata,
        "records": manifest.record_count,
        "capture_digest": manifest.content_sha256,
        **projection,
    }
    if (
        payload["final_event_capture_seq"] != manifest.last_capture_seq
        or payload["frame_capture_seq"] != manifest.last_capture_seq
        or payload["current_frame_is_final_event"] is not True
    ):
        raise ValueError("replay projection is not bound to the final capture event")
    if live is None:
        return payload
    if metadata["live_comparison_eligible"] is not True:
        raise ValueError("unscoped or incomplete capture cannot claim live/replay equality")
    expected_binding = {
        "receipt_type": CAPTURE_RECEIPT_TYPE,
        "environment": "production_public",
        "evidence_class": LIVE_CAPTURE_EVIDENCE,
        "capture_format": manifest.format_id,
        "capture_complete": True,
        "timestamp_contract": metadata["timestamp_contract"],
        "collector_elapsed_source": metadata["collector_elapsed_source"],
        "platform_state_contract": metadata["platform_state_contract"],
        "capture_digest": manifest.content_sha256,
        "records": manifest.record_count,
        "final_event_capture_seq": manifest.last_capture_seq,
        "frame_capture_seq": manifest.last_capture_seq,
        "current_frame_is_final_event": True,
        **projection,
    }
    mismatches = tuple(
        key
        for key, expected in expected_binding.items()
        if key not in live or type(live[key]) is not type(expected) or live[key] != expected
    )
    duration_seconds = live.get("duration_seconds")
    if (
        not isinstance(duration_seconds, int)
        or isinstance(duration_seconds, bool)
        or duration_seconds <= 0
    ):
        mismatches = (*mismatches, "duration_seconds")
    if mismatches:
        raise ValueError(f"live result does not match capture binding: {','.join(mismatches)}")
    payload["live_binding_verified"] = True
    payload["live_frame_digest_match"] = True
    payload["live_decision_digest_match"] = True
    payload["evidence_class"] = LIVE_REPLAY_EVIDENCE
    return payload


class _LiveSession:
    def __init__(self) -> None:
        self._started_monotonic_ns = time.monotonic_ns()
        self.events: list[CanonicalEvent] = []
        self.projector = RadarProjector()
        self.ever_observed_complete_60m = False
        self.last_trade_seq: int | None = None
        self._platform_maintenance: bool | None = None
        self._platform_maintenance_capture_seq: int | None = None
        self._platform_index_locked: bool | None = None
        self._platform_index_capture_seq: int | None = None
        self._platform_subscription_capture_seq: int | None = None
        self._platform_status_capture_seq: int | None = None

    def clock_sample(self) -> _ClockSample:
        return _ClockSample(
            received_at_ms=_now_ms(),
            elapsed_ms=(time.monotonic_ns() - self._started_monotonic_ns) // 1_000_000,
        )

    def _record(
        self,
        event_kind: EventKind,
        channel: str,
        value: object,
        *,
        instrument_name: str | None = None,
        exchange_timestamp_ms: int | None = None,
        received_at_ms: int | None = None,
        elapsed_ms: int | None = None,
    ) -> CanonicalEvent:
        clock = self.clock_sample()
        received = received_at_ms if received_at_ms is not None else clock.received_at_ms
        elapsed = elapsed_ms if elapsed_ms is not None else clock.elapsed_ms
        event = CanonicalEvent(
            capture_seq=len(self.events) + 1,
            collector_received_at_ms=received,
            collector_elapsed_ms=elapsed,
            exchange_timestamp_ms=exchange_timestamp_ms,
            channel=channel,
            event_kind=event_kind,
            instrument_name=instrument_name,
            raw_payload=_payload(value),
        )
        frame = self.projector.ingest(event)
        self.events.append(event)
        self.ever_observed_complete_60m = self.ever_observed_complete_60m or bool(
            frame is not None and _complete_60m(frame)
        )
        return event

    def record_catalog(
        self,
        rows: Iterable[Mapping[str, object]],
        *,
        received_at_ms: int,
        elapsed_ms: int | None = None,
    ) -> None:
        for row in rows:
            name = str(row["instrument_name"])
            self._record(
                EventKind.INSTRUMENT,
                "public/get_instruments",
                _canonical_instrument(row),
                instrument_name=name,
                received_at_ms=received_at_ms,
                elapsed_ms=elapsed_ms,
            )

    def record_platform(
        self,
        value: Mapping[str, object],
        *,
        channel: str,
        received_at_ms: int,
        elapsed_ms: int | None = None,
    ) -> None:
        next_capture_seq = len(self.events) + 1
        price_index = value.get("price_index")
        maintenance = self._platform_maintenance
        maintenance_capture_seq = self._platform_maintenance_capture_seq
        index_locked = self._platform_index_locked
        index_capture_seq = self._platform_index_capture_seq
        status_capture_seq = self._platform_status_capture_seq
        if channel == "public/status":
            index_locked = _status_locked(value)
            index_capture_seq = next_capture_seq
            status_capture_seq = next_capture_seq
        elif channel == "platform_state":
            raw_maintenance = value.get("maintenance")
            if raw_maintenance is not None:
                if not isinstance(raw_maintenance, bool):
                    raise ValueError("Deribit platform maintenance state must be boolean")
                maintenance = raw_maintenance
                maintenance_capture_seq = next_capture_seq
            if price_index is not None:
                if price_index != "btc_usdc":
                    if raw_maintenance is None:
                        return
                else:
                    raw_index_locked = value.get("locked")
                    if not isinstance(raw_index_locked, bool):
                        raise ValueError("Deribit platform index lock state must be boolean")
                    index_locked = raw_index_locked
                    index_capture_seq = next_capture_seq
            elif raw_maintenance is None:
                raise ValueError("Deribit platform state has no recognized control fact")
        else:
            raise ValueError("unsupported Deribit platform state channel")
        positively_locked = maintenance is True or index_locked is True
        barrier_complete = (
            self._platform_subscription_capture_seq is not None
            and status_capture_seq is not None
            and status_capture_seq > self._platform_subscription_capture_seq
        )
        state = "LOCKED" if positively_locked else "OPEN" if barrier_complete else "UNKNOWN"
        locked: bool | None = True if positively_locked else False if barrier_complete else None
        lineage = tuple(
            sorted(
                {
                    *(
                        ()
                        if self._platform_subscription_capture_seq is None
                        else (self._platform_subscription_capture_seq,)
                    ),
                    *(
                        ()
                        if status_capture_seq in {None, next_capture_seq}
                        else (status_capture_seq,)
                    ),
                    *(
                        ()
                        if maintenance_capture_seq in {None, next_capture_seq}
                        else (maintenance_capture_seq,)
                    ),
                    *(
                        ()
                        if index_capture_seq in {None, next_capture_seq}
                        else (index_capture_seq,)
                    ),
                }
            )
        )
        self._record(
            EventKind.PLATFORM_STATE,
            channel,
            {
                "state": state,
                "locked": locked,
                "price_index": price_index,
                "maintenance": maintenance,
                "index_locked": index_locked,
                "status_capture_seq": status_capture_seq,
                "source_capture_seqs": lineage,
            },
            exchange_timestamp_ms=_integer(value.get("timestamp")),
            received_at_ms=received_at_ms,
            elapsed_ms=elapsed_ms,
        )
        self._platform_maintenance = maintenance
        self._platform_maintenance_capture_seq = maintenance_capture_seq
        self._platform_index_locked = index_locked
        self._platform_index_capture_seq = index_capture_seq
        self._platform_status_capture_seq = status_capture_seq

    def record_subscription_start(
        self,
        *,
        received_at_ms: int,
        elapsed_ms: int | None = None,
    ) -> None:
        for stream, channel in (
            ("reference_price", f"ticker.{REFERENCE}.agg2"),
            ("reference_trade", f"trades.{REFERENCE}.agg2"),
            ("platform_state", "platform_state"),
        ):
            event = self._record(
                EventKind.SUBSCRIPTION_START,
                "control",
                {"stream": stream, "channel": channel},
                received_at_ms=received_at_ms,
                elapsed_ms=elapsed_ms,
            )
            if stream == "platform_state":
                self._platform_status_capture_seq = None
                self._platform_subscription_capture_seq = event.capture_seq

    def record_reconnect(
        self,
        reason: str,
        *,
        received_at_ms: int,
        elapsed_ms: int | None = None,
    ) -> None:
        self._record(
            EventKind.RECONNECT,
            "control",
            {"reason": reason},
            received_at_ms=received_at_ms,
            elapsed_ms=elapsed_ms,
        )
        self.last_trade_seq = None
        self._platform_maintenance = None
        self._platform_maintenance_capture_seq = None
        self._platform_index_locked = None
        self._platform_index_capture_seq = None
        self._platform_subscription_capture_seq = None
        self._platform_status_capture_seq = None

    def record_heartbeat(
        self,
        value: Mapping[str, object],
        *,
        received_at_ms: int,
        elapsed_ms: int | None = None,
    ) -> None:
        self._record(
            EventKind.HEARTBEAT,
            "heartbeat",
            dict(value),
            received_at_ms=received_at_ms,
            elapsed_ms=elapsed_ms,
        )

    def record_ticker(
        self,
        channel: str,
        value: Mapping[str, object],
        *,
        received_at_ms: int,
        elapsed_ms: int | None = None,
    ) -> None:
        name = str(value.get("instrument_name", ""))
        if not name:
            raise ValueError("Deribit ticker has no instrument_name")
        if channel != f"ticker.{name}.agg2":
            raise ValueError("Deribit ticker channel and instrument_name differ")
        timestamp = _integer(value.get("timestamp"))
        if timestamp is None:
            raise ValueError("Deribit ticker has no positive timestamp")
        self._record(
            EventKind.TICKER,
            channel,
            dict(value),
            instrument_name=name,
            exchange_timestamp_ms=timestamp,
            received_at_ms=received_at_ms,
            elapsed_ms=elapsed_ms,
        )

    def record_trades(
        self,
        channel: str,
        value: object,
        *,
        received_at_ms: int,
        elapsed_ms: int | None = None,
    ) -> None:
        if not isinstance(value, list):
            raise ValueError("Deribit trades notification must be an array")
        raw_trades = tuple(_object(item, "Deribit trade") for item in value)
        validated: list[tuple[int, int, dict[str, object]]] = []
        for trade in raw_trades:
            sequence = _integer(trade.get("trade_seq"))
            timestamp = _integer(trade.get("timestamp"))
            if sequence is None:
                raise ValueError("Deribit trade has no positive trade_seq")
            if timestamp is None:
                raise ValueError("Deribit trade has no positive timestamp")
            if trade.get("instrument_name") != REFERENCE:
                raise ValueError("Deribit trade has an unexpected instrument_name")
            validated.append((sequence, timestamp, trade))
        trades = tuple(item[2] for item in sorted(validated, key=lambda item: item[0]))
        if not trades:
            return
        concrete_sequences = tuple(item[0] for item in sorted(validated, key=lambda item: item[0]))
        timestamps = tuple(item[1] for item in validated)
        novel_sequences = tuple(
            sequence
            for sequence in concrete_sequences
            if self.last_trade_seq is None or sequence > self.last_trade_seq
        )
        expected = self.last_trade_seq + 1 if self.last_trade_seq is not None else None
        first_novel = novel_sequences[0] if novel_sequences else None
        discontinuous = expected is not None and first_novel is not None and first_novel > expected
        discontinuous = discontinuous or any(
            current > previous + 1 for previous, current in pairwise(novel_sequences)
        )
        event_kind = EventKind.TRADE_GAP if discontinuous else EventKind.TRADE
        self._record(
            event_kind,
            channel,
            {
                "expected_sequence": expected,
                "observed_sequence": first_novel,
                "trades": trades,
            },
            instrument_name=REFERENCE,
            exchange_timestamp_ms=max(timestamps),
            received_at_ms=received_at_ms,
            elapsed_ms=elapsed_ms,
        )
        self.last_trade_seq = max(
            concrete_sequences[-1],
            self.last_trade_seq or concrete_sequences[-1],
        )

    def consume_subscription(
        self,
        channel: str,
        value: object,
        *,
        received_at_ms: int,
        elapsed_ms: int | None = None,
    ) -> None:
        if channel == "platform_state":
            self.record_platform(
                _object(value, "Deribit platform state"),
                channel=channel,
                received_at_ms=received_at_ms,
                elapsed_ms=elapsed_ms,
            )
        elif channel.startswith("ticker."):
            self.record_ticker(
                channel,
                _object(value, "Deribit ticker"),
                received_at_ms=received_at_ms,
                elapsed_ms=elapsed_ms,
            )
        elif channel == f"trades.{REFERENCE}.agg2":
            self.record_trades(
                channel,
                value,
                received_at_ms=received_at_ms,
                elapsed_ms=elapsed_ms,
            )

    def live_projection(self) -> RadarProjection:
        if not self.events:
            raise RuntimeError("live capture produced no DecisionFrame")
        current = self.projector.finalize()
        ever_observed_complete_60m = self.ever_observed_complete_60m or _complete_60m(current)
        return RadarProjection(
            final_event_capture_seq=self.events[-1].capture_seq,
            frame=current,
            decision=evaluate_radar(current),
            current_complete_60m=_complete_60m(current),
            ever_observed_complete_60m=ever_observed_complete_60m,
        )


def _rpc(connection: Connection, request_id: int, method: str, params: object) -> None:
    if not method.startswith("public/"):
        raise ValueError("Deribit WebSocket method must be public")
    connection.send(
        _payload(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
    )


def _message(
    connection: Connection,
    session: _LiveSession,
    timeout: float,
) -> _ReceivedMessage:
    raw = connection.recv(timeout=timeout)
    clock = session.clock_sample()
    decoded: object = json.loads(raw)
    return _ReceivedMessage(_object(decoded, "Deribit WebSocket message"), clock)


def _handle_message(
    connection: Connection,
    session: _LiveSession,
    message: Mapping[str, object],
    *,
    received_at_ms: int,
    elapsed_ms: int,
    test_request_id: int,
) -> int:
    method = message.get("method")
    if method == "heartbeat":
        params = _object(message.get("params", {}), "Deribit heartbeat")
        session.record_heartbeat(
            params,
            received_at_ms=received_at_ms,
            elapsed_ms=elapsed_ms,
        )
        if params.get("type") == "test_request":
            _rpc(connection, test_request_id, "public/test", {})
            return test_request_id + 1
        return test_request_id
    if method == "subscription":
        params = _object(message.get("params"), "Deribit subscription")
        session.consume_subscription(
            str(params.get("channel", "")),
            params.get("data"),
            received_at_ms=received_at_ms,
            elapsed_ms=elapsed_ms,
        )
    return test_request_id


def _wait_result(
    connection: Connection,
    session: _LiveSession,
    request_id: int,
    *,
    test_request_id: int,
) -> tuple[object, int, _ClockSample]:
    while True:
        received = _message(connection, session, 10)
        message = received.value
        if message.get("id") == request_id:
            if "error" in message:
                raise RuntimeError(f"Deribit WebSocket error: {message['error']}")
            return message.get("result"), test_request_id, received.clock
        test_request_id = _handle_message(
            connection,
            session,
            message,
            received_at_ms=received.clock.received_at_ms,
            elapsed_ms=received.clock.elapsed_ms,
            test_request_id=test_request_id,
        )


def _subscribe(
    connection: Connection,
    session: _LiveSession,
    channels: tuple[str, ...],
) -> int:
    _rpc(connection, 1, "public/set_heartbeat", {"interval": HEARTBEAT_SECONDS})
    result, test_request_id, _ = _wait_result(
        connection,
        session,
        1,
        test_request_id=1_000,
    )
    if result != "ok":
        raise RuntimeError("Deribit public heartbeat was not accepted")
    _rpc(connection, 2, "public/subscribe", {"channels": list(channels)})
    result, test_request_id, subscription_clock = _wait_result(
        connection,
        session,
        2,
        test_request_id=test_request_id,
    )
    if not isinstance(result, list) or set(str(item) for item in result) != set(channels):
        raise RuntimeError("Deribit public subscriptions were not fully accepted")
    session.record_subscription_start(
        received_at_ms=subscription_clock.received_at_ms,
        elapsed_ms=subscription_clock.elapsed_ms,
    )
    return test_request_id


def _event_summary(
    manifest: CaptureManifest,
    events: tuple[CanonicalEvent, ...],
) -> dict[str, object]:
    evidence_metadata = capture_evidence_metadata(manifest, events)
    reducer = MarketTapeReducer()
    for event in events:
        reducer.ingest(event)
    snapshot = reducer.snapshot()
    kinds = Counter(event.event_kind.value for event in events)
    exchange_minus_collector_ms = tuple(
        event.exchange_timestamp_ms - event.collector_received_at_ms
        for event in events
        if event.exchange_timestamp_ms is not None
    )
    collector_wall_regressions = sum(
        current.collector_received_at_ms < previous.collector_received_at_ms
        for previous, current in pairwise(events)
    )
    collector_elapsed_regressions = sum(
        current.collector_elapsed_ms < previous.collector_elapsed_ms
        for previous, current in pairwise(events)
    )
    latest_ticker_source_by_instrument: dict[str, int] = {}
    ticker_source_regression_sizes: list[int] = []
    for event in events:
        if (
            event.event_kind is not EventKind.TICKER
            or event.instrument_name is None
            or event.exchange_timestamp_ms is None
        ):
            continue
        previous_source = latest_ticker_source_by_instrument.get(event.instrument_name)
        if previous_source is not None and event.exchange_timestamp_ms < previous_source:
            ticker_source_regression_sizes.append(previous_source - event.exchange_timestamp_ms)
            continue
        latest_ticker_source_by_instrument[event.instrument_name] = event.exchange_timestamp_ms
    platform_subscription_capture_seq: int | None = None
    for event in events:
        if event.event_kind is EventKind.RECONNECT:
            platform_subscription_capture_seq = None
            continue
        if event.event_kind is not EventKind.SUBSCRIPTION_START:
            continue
        value: object = json.loads(event.raw_payload)
        if isinstance(value, dict) and value.get("stream") == "platform_state":
            platform_subscription_capture_seq = event.capture_seq
    book_stream_observed = any(
        kinds[event_kind.value] > 0
        for event_kind in (
            EventKind.BOOK_SNAPSHOT,
            EventKind.BOOK_CHANGE,
            EventKind.BOOK_GAP,
        )
    )
    return {
        **evidence_metadata,
        "records": manifest.record_count,
        "capture_digest": manifest.content_sha256,
        "capture_order": "VERIFIED",
        "collector_elapsed_order": (
            "VERIFIED" if collector_elapsed_regressions == 0 else "VIOLATION"
        ),
        "collector_elapsed_regressions": collector_elapsed_regressions,
        "collector_elapsed_span_ms": (
            events[-1].collector_elapsed_ms - events[0].collector_elapsed_ms
        ),
        "collector_wall_regressions": collector_wall_regressions,
        "collector_wall_span_ms": (
            events[-1].collector_received_at_ms - events[0].collector_received_at_ms
        ),
        "first_collector_received_at_ms": events[0].collector_received_at_ms,
        "last_collector_received_at_ms": events[-1].collector_received_at_ms,
        "exchange_ahead_records": sum(item > 0 for item in exchange_minus_collector_ms),
        "exchange_minus_collector_min_ms": (
            min(exchange_minus_collector_ms) if exchange_minus_collector_ms else None
        ),
        "exchange_minus_collector_median_ms": (
            statistics.median(exchange_minus_collector_ms) if exchange_minus_collector_ms else None
        ),
        "exchange_minus_collector_max_ms": (
            max(exchange_minus_collector_ms) if exchange_minus_collector_ms else None
        ),
        "market_timestamp_contract": "VERIFIED",
        "ticker_source_regressions": len(ticker_source_regression_sizes),
        "maximum_ticker_source_regression_ms": (
            max(ticker_source_regression_sizes) if ticker_source_regression_sizes else 0
        ),
        "trade_source_regressions": 0,
        "instrument_count": len(snapshot.instruments),
        "option_instrument_count": sum(
            item.kind.value == "OPTION" for item in snapshot.instruments
        ),
        "ticker_records": kinds[EventKind.TICKER.value],
        "trade_records": kinds[EventKind.TRADE.value] + kinds[EventKind.TRADE_GAP.value],
        "heartbeat_records": kinds[EventKind.HEARTBEAT.value],
        "platform_state_records": kinds[EventKind.PLATFORM_STATE.value],
        "subscription_start_records": kinds[EventKind.SUBSCRIPTION_START.value],
        "trade_gap_records": len(snapshot.trade_gaps),
        "book_stream_observed": book_stream_observed,
        "book_gap_records": (len(snapshot.book_gaps) if book_stream_observed else None),
        "reconnect_records": kinds[EventKind.RECONNECT.value],
        "platform_locked": (
            snapshot.platform_state.locked if snapshot.platform_state is not None else None
        ),
        "platform_state": (
            snapshot.platform_state.state if snapshot.platform_state is not None else "UNKNOWN"
        ),
        "platform_subscription_capture_seq": platform_subscription_capture_seq,
        "platform_status_capture_seq": (
            snapshot.platform_state.status_capture_seq
            if snapshot.platform_state is not None
            else None
        ),
        "platform_state_capture_seq": (
            snapshot.platform_state.capture_seq if snapshot.platform_state is not None else None
        ),
        "platform_source_capture_seqs": (
            list(snapshot.platform_state.source_capture_seqs)
            if snapshot.platform_state is not None
            else []
        ),
        "snapshot_digest": snapshot.digest,
    }


def inspect_payload(
    manifest: CaptureManifest,
    events: tuple[CanonicalEvent, ...],
) -> dict[str, object]:
    payload = _event_summary(manifest, events)
    try:
        payload.update(projection_payload(project_events(events)))
    except RuntimeError as error:
        payload["projection_error"] = str(error)
    return payload


def run_public_capture(output: Path, duration_seconds: int) -> dict[str, object]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if output.exists() and any(output.iterdir()):
        raise ValueError("capture output directory must be empty or absent")
    session = _LiveSession()
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
    )
    session.record_catalog(
        selected[1:],
        received_at_ms=option_catalog.clock.received_at_ms,
        elapsed_ms=option_catalog.clock.elapsed_ms,
    )
    session.record_catalog(
        selected[:1],
        received_at_ms=future_catalog.clock.received_at_ms,
        elapsed_ms=future_catalog.clock.elapsed_ms,
    )
    option_names = tuple(str(row["instrument_name"]) for row in selected[1:])
    channels = (
        f"ticker.{REFERENCE}.agg2",
        f"trades.{REFERENCE}.agg2",
        "platform_state",
        *(f"ticker.{name}.agg2" for name in option_names),
    )
    deadline: float | None = None
    reconnect_pending = False
    active_connection = False
    while deadline is None or time.monotonic() < deadline:
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
            ) as connection:
                test_request_id = _subscribe(connection, session, channels)
                _rpc(connection, 3, "public/status", {})
                status_result, test_request_id, status_clock = _wait_result(
                    connection,
                    session,
                    3,
                    test_request_id=test_request_id,
                )
                status = _object(status_result, "Deribit public status")
                session.record_platform(
                    status,
                    channel="public/status",
                    received_at_ms=status_clock.received_at_ms,
                    elapsed_ms=status_clock.elapsed_ms,
                )
                active_connection = True
                reconnect_pending = False
                if deadline is None:
                    deadline = time.monotonic() + duration_seconds
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    try:
                        received = _message(
                            connection,
                            session,
                            min(1.0, remaining),
                        )
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
            if active_connection and not reconnect_pending:
                reconnect_clock = session.clock_sample()
                session.record_reconnect(
                    type(error).__name__,
                    received_at_ms=reconnect_clock.received_at_ms,
                    elapsed_ms=reconnect_clock.elapsed_ms,
                )
                reconnect_pending = True
            active_connection = False
            if time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))
    projection = session.live_projection()
    output.mkdir(parents=True, exist_ok=True)
    manifest = write_capture(output / "capture", session.events, complete=True)
    events = tuple(session.events)
    result = {
        "receipt_type": CAPTURE_RECEIPT_TYPE,
        "environment": "production_public",
        "duration_seconds": duration_seconds,
        **_event_summary(manifest, events),
        **projection_payload(projection),
        "evidence_class": LIVE_CAPTURE_EVIDENCE,
    }
    (output / "live.json").write_text(
        json.dumps(canonical_value(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result
