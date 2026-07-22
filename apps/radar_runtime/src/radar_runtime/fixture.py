"""Deterministic end-to-end radar reference."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from market_tape import CanonicalEvent, EventKind, write_capture
from options_domain import OptionQuote, build_surface_summary
from shadow_engine import build_outcome_path, mature_outcome, open_position
from short_vol_radar import (
    DecisionFrame,
    RadarAction,
    RadarDecision,
    RadarPolicy,
    RadarProjector,
    evaluate_radar,
)

REFERENCE = "BTC_USDC-PERPETUAL"


def _event(
    capture_seq: int,
    at_ms: int,
    event_kind: EventKind,
    instrument_name: str | None,
    payload: dict[str, object],
    channel: str,
) -> CanonicalEvent:
    return CanonicalEvent(
        capture_seq=capture_seq,
        collector_received_at_ms=at_ms,
        collector_elapsed_ms=at_ms,
        exchange_timestamp_ms=at_ms,
        channel=channel,
        event_kind=event_kind,
        instrument_name=instrument_name,
        raw_payload=json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def build_fixture_events() -> tuple[CanonicalEvent, ...]:
    start = datetime(2026, 7, 20, tzinfo=UTC)
    start_ms = int(start.timestamp() * 1_000)
    expiry_ms = int((start + timedelta(hours=4)).timestamp() * 1_000)
    option_rows = (
        ("BTC_USDC-20JUL26-98000-P", "put", 98_000),
        ("BTC_USDC-20JUL26-96000-P", "put", 96_000),
        ("BTC_USDC-20JUL26-102000-C", "call", 102_000),
        ("BTC_USDC-20JUL26-104000-C", "call", 104_000),
    )
    events: list[CanonicalEvent] = []
    sequence = 1
    events.append(
        _event(
            sequence,
            start_ms,
            EventKind.SUBSCRIPTION_START,
            None,
            {"stream": "reference_price"},
            "control",
        )
    )
    sequence += 1
    events.append(
        _event(
            sequence,
            start_ms,
            EventKind.SUBSCRIPTION_START,
            None,
            {"stream": "platform_state", "channel": "platform_state"},
            "control",
        )
    )
    sequence += 1
    events.append(
        _event(
            sequence,
            start_ms,
            EventKind.PLATFORM_STATE,
            None,
            {
                "state": "OPEN",
                "locked": False,
                "price_index": "btc_usdc",
                "status_capture_seq": sequence,
            },
            "public/status",
        )
    )
    sequence += 1
    events.append(
        _event(
            sequence,
            start_ms,
            EventKind.SUBSCRIPTION_START,
            None,
            {"stream": "reference_trade"},
            "control",
        )
    )
    sequence += 1
    events.append(
        _event(
            sequence,
            start_ms,
            EventKind.INSTRUMENT,
            REFERENCE,
            {
                "instrument_name": REFERENCE,
                "kind": "perpetual",
                "active": True,
                "contract_size": 1,
                "min_trade_amount": 0.001,
                "amount_step": 0.001,
                "taker_commission": 0.0001,
            },
            "catalog",
        )
    )
    for name, option_type, strike in option_rows:
        sequence += 1
        events.append(
            _event(
                sequence,
                start_ms,
                EventKind.INSTRUMENT,
                name,
                {
                    "instrument_name": name,
                    "kind": "option",
                    "active": True,
                    "expiration_timestamp": expiry_ms,
                    "strike": strike,
                    "option_type": option_type,
                    "contract_size": 1,
                    "min_trade_amount": 0.01,
                    "amount_step": 0.01,
                    "taker_commission": 0.0001,
                },
                "catalog",
            )
        )
    catalog_names = tuple(sorted((REFERENCE, *(item[0] for item in option_rows))))
    sequence += 1
    events.append(
        _event(
            sequence,
            start_ms,
            EventKind.CATALOG_SNAPSHOT,
            None,
            {
                "timestamp": start_ms,
                "scope": "BTC_USDC_LINEAR_OPTIONS_DECISION_BUFFER",
                "instrument_names": catalog_names,
            },
            "public/get_instruments",
        )
    )
    sequence += 1
    events.append(
        _event(
            sequence,
            start_ms,
            EventKind.SCHEDULED_BLOCK_STATE,
            None,
            {"state": "CLEAR", "label": None},
            "fixture/scheduled_block",
        )
    )
    trade_sequence = 0
    for minute in range(61):
        at_ms = start_ms + minute * 60_000
        price = Decimal("100000") + Decimal((minute % 6) - 3) * Decimal("4")
        sequence += 1
        events.append(
            _event(
                sequence,
                at_ms,
                EventKind.TICKER,
                REFERENCE,
                {
                    "timestamp": at_ms,
                    "state": "open",
                    "last_price": str(price),
                    "index_price": str(price),
                    "mark_price": str(price + Decimal("2")),
                    "best_bid_price": str(price - 1),
                    "best_ask_price": str(price + 1),
                    "funding_8h": "0.00002",
                    "open_interest": "1500",
                },
                f"ticker.{REFERENCE}.100ms",
            )
        )
        trade_sequence += 1
        sequence += 1
        events.append(
            _event(
                sequence,
                at_ms + 1,
                EventKind.TRADE,
                REFERENCE,
                {
                    "trades": [
                        {
                            "trade_seq": trade_sequence,
                            "timestamp": at_ms + 1,
                            "price": str(price),
                            "amount": "1",
                            "direction": ("buy" if minute % 2 == 0 else "sell"),
                        }
                    ]
                },
                f"trades.{REFERENCE}.raw",
            )
        )
    final_ms = start_ms + 61 * 60_000
    ticker_rows: dict[str, dict[str, object]] = {
        option_rows[0][0]: {
            "timestamp": final_ms,
            "state": "open",
            "best_bid_price": "700",
            "best_ask_price": "710",
            "best_bid_amount": "1",
            "best_ask_amount": "1",
            "bid_iv": "78",
            "ask_iv": "79",
            "mark_iv": "78.5",
            "open_interest": "100",
            "greeks": {"delta": "-0.22", "gamma": "0.00002"},
        },
        option_rows[1][0]: {
            "timestamp": final_ms,
            "state": "open",
            "best_bid_price": "95",
            "best_ask_price": "100",
            "best_bid_amount": "1",
            "best_ask_amount": "1",
            "bid_iv": "80",
            "ask_iv": "81",
            "mark_iv": "80.5",
            "open_interest": "80",
            "greeks": {"delta": "-0.10", "gamma": "0.00001"},
        },
        option_rows[2][0]: {
            "timestamp": final_ms,
            "state": "open",
            "best_bid_price": "520",
            "best_ask_price": "530",
            "best_bid_amount": "1",
            "best_ask_amount": "1",
            "bid_iv": "70",
            "ask_iv": "71",
            "mark_iv": "70.5",
            "open_interest": "90",
            "greeks": {"delta": "0.22", "gamma": "0.00002"},
        },
        option_rows[3][0]: {
            "timestamp": final_ms,
            "state": "open",
            "best_bid_price": "190",
            "best_ask_price": "195",
            "best_bid_amount": "1",
            "best_ask_amount": "1",
            "bid_iv": "72",
            "ask_iv": "73",
            "mark_iv": "72.5",
            "open_interest": "70",
            "greeks": {"delta": "0.10", "gamma": "0.00001"},
        },
    }
    for name, payload in ticker_rows.items():
        sequence += 1
        events.append(
            _event(
                sequence,
                final_ms,
                EventKind.TICKER,
                name,
                payload,
                f"ticker.{name}.agg2",
            )
        )
    sequence += 1
    events.append(
        _event(
            sequence,
            final_ms,
            EventKind.CATALOG_SNAPSHOT,
            None,
            {
                "timestamp": final_ms,
                "scope": "BTC_USDC_LINEAR_OPTIONS_DECISION_BUFFER",
                "instrument_names": catalog_names,
            },
            "public/get_instruments",
        )
    )
    sequence += 1
    events.append(
        _event(
            sequence,
            final_ms,
            EventKind.TICKER,
            REFERENCE,
            {
                "timestamp": final_ms,
                "state": "open",
                "last_price": "100000",
                "index_price": "100000",
                "mark_price": "100002",
                "best_bid_price": "99999",
                "best_ask_price": "100001",
                "funding_8h": "0.00002",
                "open_interest": "1500",
            },
            f"ticker.{REFERENCE}.100ms",
        )
    )
    return tuple(events)


def replay_fixture(
    events: tuple[CanonicalEvent, ...],
) -> tuple[DecisionFrame, RadarDecision]:
    policy = RadarPolicy()
    projector = RadarProjector(policy=policy)
    for event in events:
        projector.ingest(event)
    frame = projector.finalize()
    if not frame.complete:
        raise RuntimeError("fixture produced no complete DecisionFrame")
    decision = evaluate_radar(frame, policy=policy)
    if decision.action is not RadarAction.RESEARCH_CANDIDATE:
        raise RuntimeError(f"fixture did not produce a research candidate: {decision.reason}")
    return frame, decision


def _future_frame(
    entry: DecisionFrame,
    capture_seq: int,
    minutes: int,
    premium_factor: Decimal,
) -> DecisionFrame:
    at = entry.collector_as_of + timedelta(minutes=minutes)
    market_at = (
        entry.market_as_of + timedelta(minutes=minutes) if entry.market_as_of is not None else at
    )
    quotes: list[OptionQuote] = []
    for quote in entry.option_quotes:
        if quote.bid is None or quote.ask is None:
            quotes.append(quote)
            continue
        midpoint = (quote.bid + quote.ask) / Decimal("2")
        spread = quote.ask - quote.bid
        new_midpoint = midpoint * premium_factor
        quotes.append(
            replace(
                quote,
                bid=max(
                    Decimal("0.01"),
                    new_midpoint - spread / Decimal("2"),
                ),
                ask=max(
                    Decimal("0.02"),
                    new_midpoint + spread / Decimal("2"),
                ),
                quote_age_ms=0,
                ticker_source_capture_seq=capture_seq,
                source_at=market_at,
            )
        )
    option_quotes = tuple(quotes)
    source_capture_seqs = tuple(
        sorted(
            {
                *entry.source_capture_seqs,
                capture_seq,
                *(seq for quote in option_quotes for seq in quote.source_capture_seqs),
            }
        )
    )
    return replace(
        entry,
        as_of_capture_seq=capture_seq,
        collector_as_of=at,
        collector_elapsed_ms=entry.collector_elapsed_ms + minutes * 60 * 1_000,
        market_as_of=market_at,
        market_as_of_capture_seq=capture_seq,
        reference_source_capture_seq=capture_seq,
        reference_price=Decimal("100010"),
        index_price=Decimal("100010"),
        option_quotes=option_quotes,
        surface=build_surface_summary(option_quotes, as_of=market_at),
        source_capture_seqs=source_capture_seqs,
    )


def build_fixture_result(output: Path | None = None) -> dict[str, object]:
    events = build_fixture_events()
    frame, decision = replay_fixture(events)
    position = open_position(decision, frame)
    future_frames = (
        _future_frame(
            frame,
            frame.as_of_capture_seq + 1,
            30,
            Decimal("0.75"),
        ),
        _future_frame(
            frame,
            frame.as_of_capture_seq + 2,
            60,
            Decimal("0.45"),
        ),
    )
    path = build_outcome_path(position, future_frames)
    outcome = mature_outcome(position, path)
    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
        write_capture(output / "capture", events, complete=True)
        (output / "decision.json").write_text(
            json.dumps(
                {
                    "decision_digest": decision.digest,
                    "action": decision.action.value,
                    "reason": decision.reason,
                    "candidate_id": decision.selected_candidate_id,
                    "horizon_seconds": decision.horizon_seconds,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (output / "outcome.json").write_text(
            json.dumps(
                {
                    "outcome_digest": outcome.digest,
                    "status": outcome.status.value,
                    "exit_reason": outcome.exit_reason.value,
                    "objective_usdc": (
                        str(outcome.objective_usdc) if outcome.objective_usdc is not None else None
                    ),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "receipt_type": "RADAR_REFERENCE_FIXTURE",
        "capture_records": len(events),
        "frame_capture_seq": frame.as_of_capture_seq,
        "frame_digest": frame.digest,
        "decision_action": decision.action.value,
        "decision_reason": decision.reason,
        "decision_digest": decision.digest,
        "candidate_id": decision.selected_candidate_id,
        "horizon_seconds": decision.horizon_seconds,
        "outcome_status": outcome.status.value,
        "exit_reason": outcome.exit_reason.value,
        "objective_usdc": (
            str(outcome.objective_usdc) if outcome.objective_usdc is not None else None
        ),
        "outcome_digest": outcome.digest,
    }
