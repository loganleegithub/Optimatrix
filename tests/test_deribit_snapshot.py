from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace

import pytest

import optimatrix.deribit_snapshot as deribit_snapshot
from optimatrix.decision import MarketObservation, schedule_decision_windows
from optimatrix.deribit_snapshot import (
    DERIBIT_DELIVERY_PRICE_METHOD_ID,
    DERIBIT_DELIVERY_PRICE_SOURCE_ID,
    DERIBIT_INDEX_PATH_METHOD_ID,
    DERIBIT_PUBLIC_METHOD_ALLOWLIST,
    DeribitClock,
    DeribitHttpClient,
    DeribitSourceError,
    PublicRpcResponse,
    evaluate_live_btc_snapshot,
    fetch_btc_expiry_settlement,
    fetch_btc_index_history,
    preflight_public_clock,
    summarize_btc_index_path,
)
from optimatrix.market import EventState, EventStateSource, SettlementEvidenceKind
from optimatrix.products import BTC
from optimatrix.session import current_deribit_session
from optimatrix.workbench import build_workbench_document


class FakeDeribitClient:
    def __init__(self, now: datetime, *, remove_history: frozenset[int] = frozenset()) -> None:
        self.now = now
        self.remove_history = remove_history
        self.expiry_ms = int(current_deribit_session(now).end.timestamp() * 1000)
        self.books = {
            "BTC-X-93000-P": self._book("BTC-X-93000-P", "-0.05", "0.0008", "0.0009"),
            "BTC-X-95000-P": self._book("BTC-X-95000-P", "-0.15", "0.0028", "0.0029"),
            "BTC-X-99000-P": self._book("BTC-X-99000-P", "-0.45", "0.0080", "0.0081"),
            "BTC-X-101000-C": self._book("BTC-X-101000-C", "0.45", "0.0080", "0.0081"),
            "BTC-X-105000-C": self._book("BTC-X-105000-C", "0.15", "0.0028", "0.0029"),
            "BTC-X-107000-C": self._book("BTC-X-107000-C", "0.05", "0.0008", "0.0009"),
        }

    def call(self, method: str, params: Mapping[str, object]) -> object:
        if method == "public/get_index_price":
            return {"index_price": 100000, "estimated_delivery_price": 100000}
        if method == "public/get_instruments":
            return [
                self._instrument("BTC-X-93000-P", 93000, "put"),
                self._instrument("BTC-X-95000-P", 95000, "put"),
                self._instrument("BTC-X-99000-P", 99000, "put"),
                self._instrument("BTC-X-101000-C", 101000, "call"),
                self._instrument("BTC-X-105000-C", 105000, "call"),
                self._instrument("BTC-X-107000-C", 107000, "call"),
            ]
        if method == "public/get_order_book":
            return self.books[str(params["instrument_name"])]
        if method == "public/get_index_chart_data":
            return [
                point
                for index, point in enumerate(self._history())
                if index not in self.remove_history
            ]
        raise AssertionError(f"unexpected method: {method}")

    def _instrument(self, name: str, strike: int, option_type: str) -> dict[str, object]:
        return {
            "kind": "option",
            "is_active": True,
            "base_currency": "BTC",
            "settlement_currency": "BTC",
            "price_index": "btc_usd",
            "instrument_name": name,
            "expiration_timestamp": self.expiry_ms,
            "contract_size": 1,
            "min_trade_amount": 0.1,
            "option_type": option_type,
            "settlement_period": "day",
            "strike": strike,
            "tick_size": 0.0001,
            "tick_size_steps": [{"above_price": 0.005, "tick_size": 0.0005}],
        }

    def _book(self, name: str, delta: str, bid: str, ask: str) -> dict[str, object]:
        observed_ms = int(self.now.timestamp() * 1000)
        return {
            "state": "open",
            "instrument_name": name,
            "timestamp": observed_ms,
            "greeks": {"delta": delta, "gamma": "0.0001"},
            "mark_iv": 55,
            "bids": [[bid, 1]],
            "asks": [[ask, 1]],
            "open_interest": 1000,
            "underlying_price": 100000,
        }

    def _history(self) -> list[list[object]]:
        start = self.now - timedelta(hours=16)
        output: list[list[object]] = []
        price = Decimal("100000")
        for index in range(193):
            if index:
                price *= Decimal("1.00045") if index % 2 else Decimal("0.99955")
            output.append(
                [int((start + timedelta(minutes=5 * index)).timestamp() * 1000), str(price)]
            )
        return output


def test_public_snapshot_projects_bounded_whole_product_without_writes(
    policy, tmp_path, monkeypatch
) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    monkeypatch.chdir(tmp_path)
    evaluation = evaluate_live_btc_snapshot(
        client=FakeDeribitClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        depth=20,
    )
    assert evaluation.instrument_count == 6
    assert evaluation.fetched_book_count == 6
    assert evaluation.selection is not None and evaluation.selection.selected is not None
    assert (
        evaluation.context.evidence.event_state_source
        is EventStateSource.B3_RUNTIME_FIXED_NONE_NO_LIVE_EVENT_SOURCE
    )
    snapshot = evaluation.as_object()
    assert snapshot["observed_at"] == evaluation.observed_at.isoformat()
    assert snapshot["known_at"] == evaluation.observation.known_at.isoformat()
    counts = snapshot["market_counts"]
    assert counts["legal_structures"] > 0
    assert snapshot["window"]["ledger_state"] == "NOT_RECORDED_BY_BOUNDED_SNAPSHOT"
    workbench = build_workbench_document(snapshot)
    assert workbench["structure"]["kind"] == "ASYMMETRIC_IRON_CONDOR"
    assert not tuple(tmp_path.rglob("*.jsonl"))


def test_incomplete_book_universe_is_unknown_and_skips_structure(policy) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    client = FakeDeribitClient(now)
    client.books["BTC-X-99000-P"] = {"state": "closed", "instrument_name": "BTC-X-99000-P"}
    evaluation = evaluate_live_btc_snapshot(
        client=client,
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        depth=20,
    )
    assert not evaluation.observation.data_health_blockers
    assert [book.instrument_name for book in evaluation.observation.unavailable_books] == [
        "BTC-X-99000-P"
    ]
    assert evaluation.selection is not None
    assert not evaluation.selection.primary_rank_resolved
    assert evaluation.selection.selected is None
    assert evaluation.selection.primary_rank_unresolved_book_names == ("BTC-X-99000-P",)
    assert (
        MarketObservation.from_object(evaluation.observation.as_object()) == evaluation.observation
    )
    malformed = evaluation.observation.as_object()
    unavailable = malformed["unavailable_books"]
    assert isinstance(unavailable, list) and isinstance(unavailable[0], dict)
    unavailable[0]["combo_instrument_name"] = "FORBIDDEN"
    with pytest.raises(ValueError, match="fields are invalid"):
        MarketObservation.from_object(malformed)
    snapshot = evaluation.as_object()
    assert snapshot["projection"]["state"] == "UNKNOWN"
    assert snapshot["projection"]["blockers"] == ["PRIMARY_RANK_UNRESOLVED_BY_MISSING_BOOKS"]


def test_irrelevant_unavailable_book_does_not_pollute_primary_rank(policy) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)

    class IrrelevantClosedBookClient(FakeDeribitClient):
        def call(self, method: str, params: Mapping[str, object]) -> object:
            if method == "public/get_instruments":
                instruments = super().call(method, params)
                assert isinstance(instruments, list)
                return [*instruments, self._instrument("BTC-X-80000-P", 80000, "put")]
            if method == "public/get_order_book" and params["instrument_name"] == "BTC-X-80000-P":
                return {"state": "closed", "instrument_name": "BTC-X-80000-P"}
            return super().call(method, params)

    evaluation = evaluate_live_btc_snapshot(
        client=IrrelevantClosedBookClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        depth=20,
    )

    assert not evaluation.observation.data_health_blockers
    assert evaluation.selection is not None and evaluation.selection.primary_rank_resolved
    assert evaluation.selection.selected is not None
    assert evaluation.selection.unavailable_book_names == ("BTC-X-80000-P",)
    assert not evaluation.selection.primary_rank_unresolved_book_names
    snapshot = evaluation.as_object()
    assert snapshot["projection"]["state"] == "STRUCTURE_FOUND"
    assert snapshot["candidate_data_readiness"] == {
        "status": "COMPLETE",
        "unavailable_books": ["BTC-X-80000-P"],
        "primary_rank_unresolved_books": [],
    }


def test_incomplete_book_response_still_advances_complete_cut_known_at(policy) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    boundary_us = int(now.timestamp() * 1_000_000)
    boundary_ms = boundary_us // 1_000

    class TimedClosedBookClient(FakeDeribitClient):
        def call(self, method: str, params: Mapping[str, object]) -> object:
            result = super().call(method, params)
            is_closed = (
                method == "public/get_order_book" and params["instrument_name"] == "BTC-X-99000-P"
            )
            if is_closed:
                result = {"state": "closed", "instrument_name": "BTC-X-99000-P"}
            round_trip_ms = 8_500 if is_closed else 20
            return PublicRpcResponse(
                jsonrpc="2.0",
                request_id=1,
                result=result,
                testnet=False,
                server_received_at_us=boundary_us,
                server_sent_at_us=boundary_us + 1_000,
                server_processing_us=1_000,
                request_sent_monotonic_ns=1_000_000_000,
                response_received_monotonic_ns=(1_000_000_000 + round_trip_ms * 1_000_000),
            )

    evaluation = evaluate_live_btc_snapshot(
        client=TimedClosedBookClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        depth=20,
    )

    assert evaluation.observation.known_at == now + timedelta(milliseconds=8_500)
    assert evaluation.context.evidence.market_received_min_ms == boundary_ms + 20
    assert evaluation.context.evidence.market_received_max_ms == boundary_ms + 8_500
    assert "MARKET_RECEIVE_SPAN_EXCEEDED" in evaluation.observation.data_health_blockers
    assert "SELECTION_UNIVERSE_INCOMPLETE" not in evaluation.observation.data_health_blockers


def test_default_elapsed_clock_advances_across_macos_sleep(monkeypatch) -> None:
    calls: list[int] = []
    fake_time = SimpleNamespace(
        CLOCK_MONOTONIC_RAW=4,
        clock_gettime_ns=lambda clock_id: calls.append(clock_id) or 123_456_789,
    )
    monkeypatch.setattr(deribit_snapshot, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(deribit_snapshot, "time", fake_time)

    assert deribit_snapshot.continuous_monotonic_ns() == 123_456_789
    assert calls == [4]


def test_deribit_clock_ignores_late_response_with_older_server_send_anchor() -> None:
    at = datetime(2026, 8, 12, 9, tzinfo=UTC)
    at_us = int(at.timestamp() * 1_000_000)
    monotonic_ns = 1_300_000_000
    clock = DeribitClock(monotonic_ns=lambda: monotonic_ns)
    newer = PublicRpcResponse(
        jsonrpc="2.0",
        request_id=2,
        result={},
        testnet=False,
        server_received_at_us=at_us + 100_000,
        server_sent_at_us=at_us + 110_000,
        server_processing_us=10_000,
        request_sent_monotonic_ns=1_000_000_000,
        response_received_monotonic_ns=1_200_000_000,
    )
    clock.initialize(
        newer.clock_reading,
        server_sent_at_us=newer.server_sent_at_us,
    )
    before = clock.read()

    older_but_received_later = PublicRpcResponse(
        jsonrpc="2.0",
        request_id=1,
        result={},
        testnet=False,
        server_received_at_us=at_us - 100_000,
        server_sent_at_us=at_us - 90_000,
        server_processing_us=10_000,
        request_sent_monotonic_ns=900_000_000,
        response_received_monotonic_ns=monotonic_ns,
    )
    clock.refresh(
        older_but_received_later.clock_reading,
        server_sent_at_us=older_but_received_later.server_sent_at_us,
    )
    after = clock.read()

    assert after == before


def test_deribit_clock_newer_server_send_anchor_can_reanchor_and_widen() -> None:
    at = datetime(2026, 8, 12, 9, tzinfo=UTC)
    at_us = int(at.timestamp() * 1_000_000)
    monotonic_ns = 1_401_000_000
    clock = DeribitClock(monotonic_ns=lambda: monotonic_ns)
    initial = PublicRpcResponse(
        jsonrpc="2.0",
        request_id=1,
        result={},
        testnet=False,
        server_received_at_us=at_us,
        server_sent_at_us=at_us + 1_000,
        server_processing_us=1_000,
        request_sent_monotonic_ns=1_000_000_000,
        response_received_monotonic_ns=1_011_000_000,
    )
    clock.initialize(
        initial.clock_reading,
        server_sent_at_us=initial.server_sent_at_us,
    )
    before = clock.read()

    newer = PublicRpcResponse(
        jsonrpc="2.0",
        request_id=2,
        result={},
        testnet=False,
        server_received_at_us=at_us + 500_000,
        server_sent_at_us=at_us + 501_000,
        server_processing_us=1_000,
        request_sent_monotonic_ns=1_200_000_000,
        response_received_monotonic_ns=monotonic_ns,
    )
    clock.refresh(
        newer.clock_reading,
        server_sent_at_us=newer.server_sent_at_us,
    )
    after = clock.read()

    assert after == newer.clock_reading
    assert after.latest_at - after.earliest_at > before.latest_at - before.earliest_at


def test_deribit_clock_never_moves_an_emitted_business_floor_backwards() -> None:
    at = datetime(2026, 8, 12, 9, tzinfo=UTC)
    at_us = int(at.timestamp() * 1_000_000)
    monotonic_ns = [1_500_000_000]
    clock = DeribitClock(monotonic_ns=lambda: monotonic_ns[0])
    initial = PublicRpcResponse(
        jsonrpc="2.0",
        request_id=1,
        result={},
        testnet=False,
        server_received_at_us=at_us,
        server_sent_at_us=at_us,
        server_processing_us=0,
        request_sent_monotonic_ns=1_000_000_000,
        response_received_monotonic_ns=1_000_000_000,
    )
    clock.initialize(
        initial.clock_reading,
        server_sent_at_us=initial.server_sent_at_us,
    )
    committed = clock.read()
    assert committed.earliest_at == at + timedelta(milliseconds=500)

    partially_behind = PublicRpcResponse(
        jsonrpc="2.0",
        request_id=2,
        result={},
        testnet=False,
        server_received_at_us=at_us + 400_000,
        server_sent_at_us=at_us + 400_000,
        server_processing_us=0,
        request_sent_monotonic_ns=1_300_000_000,
        response_received_monotonic_ns=monotonic_ns[0],
    )
    clock.refresh(
        partially_behind.clock_reading,
        server_sent_at_us=partially_behind.server_sent_at_us,
    )
    clamped = clock.read()
    assert clamped.earliest_at == committed.earliest_at
    assert clamped.latest_at == at + timedelta(milliseconds=600)

    monotonic_ns[0] += 200_000_000
    progressed = clock.read()
    assert progressed.earliest_at > clamped.earliest_at

    wholly_behind = PublicRpcResponse(
        jsonrpc="2.0",
        request_id=3,
        result={},
        testnet=False,
        server_received_at_us=at_us + 550_000,
        server_sent_at_us=at_us + 550_000,
        server_processing_us=0,
        request_sent_monotonic_ns=monotonic_ns[0] - 40_000_000,
        response_received_monotonic_ns=monotonic_ns[0],
    )
    with pytest.raises(DeribitSourceError, match="behind committed business time"):
        clock.refresh(
            wholly_behind.clock_reading,
            server_sent_at_us=wholly_behind.server_sent_at_us,
        )
    with pytest.raises(DeribitSourceError, match="behind committed business time"):
        clock.read()


def test_snapshot_captures_independent_inputs_and_all_books_concurrently(policy) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)

    class ConcurrentCutClient(FakeDeribitClient):
        def __init__(self, boundary: datetime) -> None:
            super().__init__(boundary)
            self.input_barrier = Barrier(3)
            self.book_barrier = Barrier(10)
            self.extra = (
                ("BTC-X-96000-P", 96000, "put", "-0.20"),
                ("BTC-X-97000-P", 97000, "put", "-0.30"),
                ("BTC-X-103000-C", 103000, "call", "0.20"),
                ("BTC-X-109000-C", 109000, "call", "0.03"),
            )
            for name, _strike, _option_type, delta in self.extra:
                self.books[name] = self._book(name, delta, "0.0010", "0.0011")

        def call(self, method: str, params: Mapping[str, object]) -> object:
            if method in {
                "public/get_index_price",
                "public/get_instruments",
                "public/get_index_chart_data",
            }:
                self.input_barrier.wait(timeout=2)
            if method == "public/get_instruments":
                return [
                    *super().call(method, params),
                    *(
                        self._instrument(name, strike, option_type)
                        for name, strike, option_type, _delta in self.extra
                    ),
                ]
            if method == "public/get_order_book":
                self.book_barrier.wait(timeout=2)
            return super().call(method, params)

    evaluation = evaluate_live_btc_snapshot(
        client=ConcurrentCutClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=10,
        depth=20,
    )

    assert evaluation.requested_book_count == evaluation.fetched_book_count == 10
    assert not evaluation.observation.data_health_blockers


def test_snapshot_rejects_request_failure_without_causal_completion_boundary(policy) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)

    class FailedBookClient(FakeDeribitClient):
        def call(self, method: str, params: Mapping[str, object]) -> object:
            if (
                method == "public/get_order_book"
                and params.get("instrument_name") == "BTC-X-99000-P"
            ):
                raise DeribitSourceError("bounded book request failed")
            return super().call(method, params)

    with pytest.raises(
        DeribitSourceError,
        match=(
            "1 of 6 requested option books failed without a validated causal completion boundary: "
            "BOOK_REQUEST_FAILED:BTC-X-99000-P:DeribitSourceError"
        ),
    ):
        evaluate_live_btc_snapshot(
            client=FailedBookClient(now),
            policy=policy,
            now=now,
            event_state=EventState.NONE,
            maximum_books=8,
            depth=20,
        )


def test_causally_bounded_irrelevant_request_failure_is_candidate_local(policy) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    boundary_us = int(now.timestamp() * 1_000_000)

    class FailedIrrelevantBookClient(FakeDeribitClient):
        def __init__(self, boundary: datetime) -> None:
            super().__init__(boundary)
            self.clock = DeribitClock(monotonic_ns=lambda: 1_000_000_000)
            envelope = PublicRpcResponse(
                jsonrpc="2.0",
                request_id=1,
                result={},
                testnet=False,
                server_received_at_us=boundary_us,
                server_sent_at_us=boundary_us,
                server_processing_us=0,
                request_sent_monotonic_ns=1_000_000_000,
                response_received_monotonic_ns=1_000_000_000,
            )
            self.clock.initialize(
                envelope.clock_reading,
                server_sent_at_us=envelope.server_sent_at_us,
            )

        def call(self, method: str, params: Mapping[str, object]) -> object:
            if method == "public/get_instruments":
                instruments = super().call(method, params)
                assert isinstance(instruments, list)
                return [*instruments, self._instrument("BTC-X-80000-P", 80000, "put")]
            if (
                method == "public/get_order_book"
                and params.get("instrument_name") == "BTC-X-80000-P"
            ):
                raise DeribitSourceError("bounded book request failed")
            return super().call(method, params)

    evaluation = evaluate_live_btc_snapshot(
        client=FailedIrrelevantBookClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        depth=20,
    )

    assert not evaluation.observation.data_health_blockers
    assert evaluation.selection is not None and evaluation.selection.selected is not None
    assert evaluation.observation.unavailable_books[0].reason.value == "BOOK_REQUEST_FAILED"
    assert "BOOK_REQUEST_FAILED:BTC-X-80000-P:DeribitSourceError" in evaluation.warnings


def test_irrelevant_invalid_book_response_is_candidate_local(policy) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)

    class InvalidIrrelevantBookClient(FakeDeribitClient):
        def call(self, method: str, params: Mapping[str, object]) -> object:
            if method == "public/get_instruments":
                instruments = super().call(method, params)
                assert isinstance(instruments, list)
                return [*instruments, self._instrument("BTC-X-80000-P", 80000, "put")]
            if (
                method == "public/get_order_book"
                and params.get("instrument_name") == "BTC-X-80000-P"
            ):
                return {
                    "state": "open",
                    "instrument_name": "BTC-X-80000-P",
                    "timestamp": int(now.timestamp() * 1000),
                    "greeks": None,
                }
            return super().call(method, params)

    evaluation = evaluate_live_btc_snapshot(
        client=InvalidIrrelevantBookClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        depth=20,
    )

    assert not evaluation.observation.data_health_blockers
    assert evaluation.selection is not None and evaluation.selection.selected is not None
    assert evaluation.observation.unavailable_books[0].reason.value == "BOOK_RESPONSE_INVALID"
    assert "BOOK_RESPONSE_INVALID:BTC-X-80000-P:DeribitSourceError" in evaluation.warnings


def test_snapshot_uses_server_response_envelope_for_causal_book_receipt(policy) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    boundary_ms = int(now.timestamp() * 1000)

    class ClockSkewedBookClient(FakeDeribitClient):
        def call(self, method: str, params: Mapping[str, object]) -> object:
            result = super().call(method, params)
            if method != "public/get_order_book":
                return result
            return PublicRpcResponse(
                jsonrpc="2.0",
                request_id=1,
                result=result,
                testnet=False,
                server_received_at_us=boundary_ms * 1000,
                server_sent_at_us=boundary_ms * 1000 + 500,
                server_processing_us=500,
                request_sent_monotonic_ns=1_000_000_000,
                response_received_monotonic_ns=1_100_000_000,
            )

    evaluation = evaluate_live_btc_snapshot(
        client=ClockSkewedBookClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        depth=20,
    )

    assert not evaluation.observation.data_health_blockers
    assert evaluation.observed_at == now
    assert {quote.received_timestamp_ms for quote in evaluation.quotes} == {boundary_ms + 100}
    assert evaluation.observation.known_at == now + timedelta(milliseconds=100)


@pytest.mark.parametrize(
    "latest_method",
    (
        "public/get_index_price",
        "public/get_instruments",
        "public/get_index_chart_data",
        "public/get_order_book",
    ),
)
def test_snapshot_known_at_covers_every_public_input_response(policy, latest_method) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    boundary_us = int(now.timestamp() * 1_000_000)
    boundary_ms = boundary_us // 1_000

    class TimedCutClient(FakeDeribitClient):
        def call(self, method: str, params: Mapping[str, object]) -> object:
            result = super().call(method, params)
            round_trip_ms = 200 if method == latest_method else 20
            return PublicRpcResponse(
                jsonrpc="2.0",
                request_id=1,
                result=result,
                testnet=False,
                server_received_at_us=boundary_us,
                server_sent_at_us=boundary_us + 1_000,
                server_processing_us=1_000,
                request_sent_monotonic_ns=1_000_000_000,
                response_received_monotonic_ns=(1_000_000_000 + round_trip_ms * 1_000_000),
            )

    evaluation = evaluate_live_btc_snapshot(
        client=TimedCutClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        depth=20,
    )

    assert evaluation.observed_at == now + timedelta(milliseconds=1)
    assert evaluation.observation.known_at == now + timedelta(milliseconds=200)
    assert evaluation.context.evidence.market_received_min_ms == boundary_ms + 20
    assert evaluation.context.evidence.market_received_max_ms == boundary_ms + 200
    assert not evaluation.observation.data_health_blockers


def test_snapshot_rejects_source_timestamp_after_its_server_response_envelope(policy) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    boundary_ms = int(now.timestamp() * 1000)

    class InvalidBookCausalityClient(FakeDeribitClient):
        def call(self, method: str, params: Mapping[str, object]) -> object:
            result = super().call(method, params)
            if method != "public/get_order_book":
                return result
            return PublicRpcResponse(
                jsonrpc="2.0",
                request_id=1,
                result=result,
                testnet=False,
                server_received_at_us=(boundary_ms - 200) * 1000,
                server_sent_at_us=(boundary_ms - 100) * 1000,
                server_processing_us=100_000,
                request_sent_monotonic_ns=1_000_000_000,
                response_received_monotonic_ns=1_800_000_000,
            )

    with pytest.raises(
        DeribitSourceError,
        match="order book source timestamp follows its response envelope",
    ):
        evaluate_live_btc_snapshot(
            client=InvalidBookCausalityClient(now),
            policy=policy,
            now=now,
            event_state=EventState.NONE,
            maximum_books=8,
            depth=20,
        )


def test_material_index_history_gap_rejects_snapshot(policy) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    client = FakeDeribitClient(now, remove_history=frozenset({80, 81, 82}))
    with pytest.raises(DeribitSourceError, match="material risk-horizon gap"):
        evaluate_live_btc_snapshot(
            client=client,
            policy=policy,
            now=now,
            event_state=EventState.NONE,
            maximum_books=8,
            depth=20,
        )


def test_snapshot_keeps_matched_physical_horizon_evaluable_with_five_minute_cadence_near_expiry(
    policy,
) -> None:
    session = current_deribit_session(
        datetime(2026, 8, 12, 18, 7, tzinfo=UTC),
        phase_policy=policy.session,
    )
    now = session.end - timedelta(minutes=29)
    evaluation = evaluate_live_btc_snapshot(
        client=FakeDeribitClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        depth=20,
    )

    assert evaluation.methodology.index_history_cadence_ms == 5 * 60_000
    assert not evaluation.observation.data_health_blockers


def test_http_client_allowlist_matches_b3_runtime_permission() -> None:
    assert DERIBIT_PUBLIC_METHOD_ALLOWLIST == frozenset(
        {
            "public/get_time",
            "public/get_instruments",
            "public/get_index_price",
            "public/get_index_chart_data",
            "public/get_order_book",
            "public/get_delivery_prices",
        }
    )


@pytest.mark.parametrize(
    "method",
    (
        "private/buy",
        "public/auth",
        "public/get_announcements",
    ),
)
def test_http_client_refuses_methods_outside_b3_allowlist_before_request_construction(
    method, monkeypatch
) -> None:
    connection_constructed = False

    def unexpected_connection(*args, **kwargs):
        nonlocal connection_constructed
        connection_constructed = True
        raise AssertionError("connection must not be constructed for a forbidden method")

    monkeypatch.setattr("optimatrix.deribit_snapshot.HTTPSConnection", unexpected_connection)
    with pytest.raises(ValueError, match="B3 allowlist"):
        DeribitHttpClient(base_url="https://invalid.example").call(method, {})
    assert connection_constructed is False


def test_http_client_requires_get_time_before_other_public_calls(monkeypatch) -> None:
    sent_ms = int(datetime(2026, 8, 12, 18, 7, tzinfo=UTC).timestamp() * 1000)
    server_in_us = sent_ms * 1000 + 10_000
    server_out_us = sent_ms * 1000 + 20_000
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"index_price": 100000},
        "testnet": False,
        "usIn": server_in_us,
        "usOut": server_out_us,
        "usDiff": server_out_us - server_in_us,
    }
    requests = []

    class FakeHttpResponse:
        status = 200

        def getheader(self, _name):
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    class FakeHttpsConnection:
        def __init__(self, host, *, port, timeout):
            requests.append((host, port, timeout))

        def request(self, method, path, *, body, headers):
            requests.append((method, path, body, headers))

        def getresponse(self):
            return FakeHttpResponse()

        def close(self) -> None:
            requests.append("closed")

    monotonic = iter((1_000_000_000, 1_050_000_000))
    monkeypatch.setattr("optimatrix.deribit_snapshot.HTTPSConnection", FakeHttpsConnection)
    client = DeribitHttpClient(timeout_seconds=10, monotonic_ns=lambda: next(monotonic))
    with pytest.raises(DeribitSourceError, match="get_time"):
        client.call(
            "public/get_index_price",
            {"index_name": "btc_usd"},
        )
    assert not requests


def test_http_client_get_time_initializes_deribit_clock(monkeypatch) -> None:
    boundary_ms = int(datetime(2026, 8, 12, 18, 7, tzinfo=UTC).timestamp() * 1000)
    payloads = iter(
        (
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": boundary_ms + 10,
                "testnet": False,
                "usIn": (boundary_ms + 10) * 1000,
                "usOut": (boundary_ms + 20) * 1000,
                "usDiff": 10_000,
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"index_price": 100000},
                "testnet": False,
                "usIn": (boundary_ms + 70) * 1000,
                "usOut": (boundary_ms + 80) * 1000,
                "usDiff": 10_000,
            },
        )
    )

    class FakeHttpResponse:
        status = 200

        def getheader(self, _name):
            return None

        def read(self) -> bytes:
            return json.dumps(next(payloads)).encode("utf-8")

    requests: list[object] = []

    class FakeHttpsConnection:
        def __init__(self, host, *, port, timeout):
            requests.append((host, port, timeout))

        def request(self, method, path, *, body, headers):
            requests.append((method, path, body, headers))

        def getresponse(self):
            return FakeHttpResponse()

        def close(self) -> None:
            requests.append("closed")

    monotonic_values = iter(
        (
            1_000_000_000,
            1_050_000_000,
            1_060_000_000,
            1_110_000_000,
            1_120_000_000,
        )
    )
    monkeypatch.setattr("optimatrix.deribit_snapshot.HTTPSConnection", FakeHttpsConnection)
    monkeypatch.setattr(
        "optimatrix.deribit_snapshot.time.time",
        lambda: (_ for _ in ()).throw(AssertionError("wall clock must not be read")),
    )
    client = DeribitHttpClient(monotonic_ns=lambda: next(monotonic_values))
    preflight = preflight_public_clock(client)
    response = client.call(
        "public/get_index_price",
        {"index_name": "btc_usd"},
    )
    assert isinstance(response, PublicRpcResponse)
    assert response.result == {"index_price": 100000}
    assert response.testnet is False
    assert preflight.clock_reading.earliest_at == datetime.fromtimestamp(
        (boundary_ms + 20) / 1000,
        tz=UTC,
    )
    assert preflight.clock_reading.estimate_at == datetime.fromtimestamp(
        (boundary_ms + 40) / 1000,
        tz=UTC,
    )
    assert preflight.clock_reading.latest_at == datetime.fromtimestamp(
        (boundary_ms + 60) / 1000,
        tz=UTC,
    )
    assert response.request_round_trip_ms == 50
    assert response.server_processing_us == 10_000
    assert response.clock_reading.latest_at == datetime.fromtimestamp(
        (boundary_ms + 120) / 1000,
        tz=UTC,
    )
    assert client.clock.read().latest_at == datetime.fromtimestamp(
        (boundary_ms + 130) / 1000,
        tz=UTC,
    )
    assert requests[0] == ("www.deribit.com", None, 10.0)
    method, path, body, headers = requests[1]
    assert method == "POST"
    assert path == "/api/v2/public/get_time"
    assert json.loads(body) == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "public/get_time",
        "params": {},
    }
    assert headers["Connection"] == "keep-alive"
    assert headers["Accept-Encoding"] == "gzip"
    assert requests[2] == "closed"


def test_http_client_rejects_nonproduction_envelope(monkeypatch) -> None:
    boundary_ms = int(datetime(2026, 8, 12, 18, 7, tzinfo=UTC).timestamp() * 1000)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": boundary_ms,
        "testnet": True,
        "usIn": boundary_ms * 1000,
        "usOut": boundary_ms * 1000 + 100,
        "usDiff": 100,
    }

    class FakeHttpResponse:
        status = 200

        def getheader(self, _name):
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    class FakeHttpsConnection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return FakeHttpResponse()

        def close(self) -> None:
            pass

    monkeypatch.setattr("optimatrix.deribit_snapshot.HTTPSConnection", FakeHttpsConnection)
    with pytest.raises(DeribitSourceError, match="not from production"):
        DeribitHttpClient().call("public/get_time", {})


@pytest.mark.parametrize(
    ("status", "encoding", "response_body", "error"),
    (
        (503, None, b"{}", "not successful"),
        (200, "br", b"{}", "unsupported encoding"),
        (200, "gzip", b"not-gzip", "BadGzipFile"),
        (200, None, b"not-json", "JSONDecodeError"),
    ),
)
def test_http_client_rejects_invalid_http_transport_facts(
    status,
    encoding,
    response_body,
    error,
    monkeypatch,
) -> None:
    class FakeHttpResponse:
        def __init__(self) -> None:
            self.status = status

        def getheader(self, name):
            return encoding if name == "Content-Encoding" else None

        def read(self) -> bytes:
            return response_body

    class FakeHttpsConnection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return FakeHttpResponse()

        def close(self) -> None:
            pass

    monkeypatch.setattr("optimatrix.deribit_snapshot.HTTPSConnection", FakeHttpsConnection)
    with pytest.raises(DeribitSourceError, match=error):
        DeribitHttpClient().call("public/get_time", {})


def test_public_clock_preflight_requires_validated_response_envelope() -> None:
    server_time_ms = int(datetime(2026, 8, 12, 18, 7, tzinfo=UTC).timestamp() * 1000)

    class ClockClient:
        def call(self, method: str, params: Mapping[str, object]) -> object:
            assert method == "public/get_time"
            assert not params
            return server_time_ms

    with pytest.raises(DeribitSourceError, match="validated response envelope"):
        preflight_public_clock(ClockClient())


def test_public_clock_preflight_rejects_get_time_outside_response_envelope() -> None:
    boundary = datetime(2026, 8, 13, 8, 5, tzinfo=UTC)
    boundary_ms = int(boundary.timestamp() * 1_000)

    class InvalidEnvelopeClient:
        def call(self, method: str, params: Mapping[str, object]) -> object:
            assert method == "public/get_time"
            assert not params
            return PublicRpcResponse(
                jsonrpc="2.0",
                request_id=1,
                result=boundary_ms + 1_000,
                testnet=False,
                server_received_at_us=boundary_ms * 1_000,
                server_sent_at_us=boundary_ms * 1_000 + 500,
                server_processing_us=500,
                request_sent_monotonic_ns=1_000_000_000,
                response_received_monotonic_ns=1_100_000_000,
            )

    with pytest.raises(DeribitSourceError, match="outside its response timing envelope"):
        preflight_public_clock(InvalidEnvelopeClient())


def test_public_clock_and_settlement_use_causal_server_send_boundary() -> None:
    boundary = datetime(2026, 8, 13, 8, 5, tzinfo=UTC)
    boundary_ms = int(boundary.timestamp() * 1000)

    class EnvelopeClient:
        def call(self, method: str, params: Mapping[str, object]) -> object:
            result: object
            if method == "public/get_time":
                result = boundary_ms
            elif method == "public/get_delivery_prices":
                result = {
                    "data": [{"date": "2026-08-13", "delivery_price": "119123.45"}],
                    "records_total": 1,
                }
            else:
                raise AssertionError(f"unexpected method: {method}")
            return PublicRpcResponse(
                jsonrpc="2.0",
                request_id=1,
                result=result,
                testnet=False,
                server_received_at_us=boundary_ms * 1000,
                server_sent_at_us=boundary_ms * 1000 + 500,
                server_processing_us=500,
                request_sent_monotonic_ns=1_000_000_000,
                response_received_monotonic_ns=1_100_000_000,
            )

    preflight = preflight_public_clock(EnvelopeClient())
    settlement = fetch_btc_expiry_settlement(
        EnvelopeClient(),
        expiry=datetime(2026, 8, 13, 8, tzinfo=UTC),
        known_at=boundary,
    )

    expected = boundary + timedelta(milliseconds=100)
    assert preflight.known_at == expected
    assert settlement.known_at == expected


def test_snapshot_binds_explicit_target_and_forces_required_books(policy) -> None:
    now = datetime(2026, 8, 12, 18, 14, 59, tzinfo=UTC)
    session = current_deribit_session(now, phase_policy=policy.session)
    target = next(
        window
        for window in schedule_decision_windows(
            session=session,
            channel_id=policy.channel_id,
            policy=policy.window,
        )
        if window.starts_at <= now < window.ends_at
    )
    required_names = (
        "BTC-X-93000-P",
        "BTC-X-95000-P",
        "BTC-X-105000-C",
        "BTC-X-107000-C",
    )
    evaluation = evaluate_live_btc_snapshot(
        client=FakeDeribitClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=4,
        target_window=target,
        required_instrument_names=required_names,
    )
    assert evaluation.decision_window == target
    assert {quote.instrument_name for quote in evaluation.quotes} == set(required_names)

    within_grace_at = target.ends_at + timedelta(milliseconds=500)
    within_grace_ms = int(within_grace_at.timestamp() * 1000)
    window_end_ms = int(target.ends_at.timestamp() * 1000)

    class GraceBoundaryClient(FakeDeribitClient):
        def call(self, method: str, params: Mapping[str, object]) -> object:
            result = super().call(method, params)
            return PublicRpcResponse(
                jsonrpc="2.0",
                request_id=1,
                result=result,
                testnet=False,
                server_received_at_us=(window_end_ms - 20) * 1_000,
                server_sent_at_us=(window_end_ms - 10) * 1_000,
                server_processing_us=10_000,
                request_sent_monotonic_ns=1_000_000_000,
                response_received_monotonic_ns=1_520_000_000,
            )

    within_grace = evaluate_live_btc_snapshot(
        client=GraceBoundaryClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=4,
        target_window=target,
        required_instrument_names=required_names,
    )
    assert within_grace.observation.observed_at == target.ends_at - timedelta(milliseconds=10)
    assert within_grace.observation.known_at == within_grace_at
    assert "SNAPSHOT_CROSSED_TARGET_WINDOW_BOUNDARY" not in (
        within_grace.observation.data_health_blockers
    )

    class PostWindowInputClient(FakeDeribitClient):
        def call(self, method: str, params: Mapping[str, object]) -> object:
            result = super().call(method, params)
            return PublicRpcResponse(
                jsonrpc="2.0",
                request_id=1,
                result=result,
                testnet=False,
                server_received_at_us=(within_grace_ms - 20) * 1_000,
                server_sent_at_us=(within_grace_ms - 10) * 1_000,
                server_processing_us=10_000,
                request_sent_monotonic_ns=1_000_000_000,
                response_received_monotonic_ns=1_020_000_000,
            )

    post_window_input = evaluate_live_btc_snapshot(
        client=PostWindowInputClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=4,
        target_window=target,
        required_instrument_names=required_names,
    )
    assert post_window_input.observation.observed_at == within_grace_at - timedelta(milliseconds=10)
    assert "SNAPSHOT_CROSSED_TARGET_WINDOW_BOUNDARY" in (
        post_window_input.observation.data_health_blockers
    )
    assert post_window_input.selection is None

    crossed_at = target.input_deadline + timedelta(seconds=1)
    crossed_ms = int(crossed_at.timestamp() * 1000)

    class CrossedBoundaryClient(FakeDeribitClient):
        def call(self, method: str, params: Mapping[str, object]) -> object:
            result = super().call(method, params)
            return PublicRpcResponse(
                jsonrpc="2.0",
                request_id=1,
                result=result,
                testnet=False,
                server_received_at_us=(crossed_ms - 20) * 1_000,
                server_sent_at_us=(crossed_ms - 10) * 1_000,
                server_processing_us=10_000,
                request_sent_monotonic_ns=1_000_000_000,
                response_received_monotonic_ns=1_020_000_000,
            )

    crossed = evaluate_live_btc_snapshot(
        client=CrossedBoundaryClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=4,
        target_window=target,
        required_instrument_names=required_names,
    )
    assert crossed.observation.known_at == crossed_at
    assert "SNAPSHOT_CROSSED_TARGET_WINDOW_BOUNDARY" in (crossed.observation.data_health_blockers)
    assert crossed.selection is None


def test_snapshot_marks_missing_required_instrument_metadata_unknown(policy) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    evaluation = evaluate_live_btc_snapshot(
        client=FakeDeribitClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        required_instrument_names=("BTC-X-NOT-CURRENT-C",),
    )
    assert "REQUIRED_INSTRUMENT_METADATA_MISSING" in evaluation.observation.data_health_blockers
    assert evaluation.selection is None


def test_history_reader_and_path_summary_expose_outcome_inputs() -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    client = FakeDeribitClient(now)
    history = fetch_btc_index_history(client, known_at=now)
    starts_at = now - timedelta(hours=1)
    summary = summarize_btc_index_path(
        history,
        starts_at=starts_at,
        ends_at=now,
    )
    assert summary is not None
    assert summary.source_id == "DERIBIT_PUBLIC_GET_INDEX_CHART_DATA_BTC_USD_2D"
    assert summary.method_id == DERIBIT_INDEX_PATH_METHOD_ID
    assert summary.observation_count == 13
    assert Decimal(0) <= summary.maximum_rv_acceleration <= Decimal(1)

    cadence_covered = summarize_btc_index_path(
        history,
        starts_at=starts_at + timedelta(minutes=1),
        ends_at=now - timedelta(minutes=1),
    )
    assert cadence_covered is not None
    assert cadence_covered.starts_at == starts_at + timedelta(minutes=1)
    assert cadence_covered.ends_at == now - timedelta(minutes=1)

    removed = {
        int((starts_at + timedelta(minutes=offset)).timestamp() * 1000) for offset in (20, 25, 30)
    }
    gapped = tuple(point for point in history if point[0] not in removed)
    assert summarize_btc_index_path(gapped, starts_at=starts_at, ends_at=now) is None


def test_delivery_price_uses_exact_expiry_utc_date_and_official_evidence() -> None:
    expiry = datetime(2026, 8, 13, 8, tzinfo=UTC)

    class DeliveryClient:
        def __init__(self, data: list[dict[str, object]]) -> None:
            self.data = data
            self.calls: list[tuple[str, Mapping[str, object]]] = []

        def call(self, method: str, params: Mapping[str, object]) -> object:
            self.calls.append((method, params))
            return {"data": self.data, "records_total": len(self.data)}

    client = DeliveryClient(
        [
            {"date": "2026-08-12", "delivery_price": 118000},
            {"date": "2026-08-13", "delivery_price": "119123.45"},
        ]
    )
    fact = fetch_btc_expiry_settlement(
        client,
        expiry=expiry,
        known_at=expiry + timedelta(minutes=1),
    )
    assert fact.product_id is BTC.product_id
    assert fact.delivery_price_usd == Decimal("119123.45")
    assert fact.evidence_kind is SettlementEvidenceKind.OFFICIAL_EXCHANGE
    assert fact.source_id == DERIBIT_DELIVERY_PRICE_SOURCE_ID
    assert fact.method_id == DERIBIT_DELIVERY_PRICE_METHOD_ID
    assert client.calls == [
        (
            "public/get_delivery_prices",
            {"index_name": "btc_usd", "offset": 0, "count": 10},
        )
    ]

    with pytest.raises(DeribitSourceError, match="exact UTC expiry date"):
        fetch_btc_expiry_settlement(
            DeliveryClient([{"date": "2026-08-12", "delivery_price": 118000}]),
            expiry=expiry,
            known_at=expiry + timedelta(minutes=1),
        )
