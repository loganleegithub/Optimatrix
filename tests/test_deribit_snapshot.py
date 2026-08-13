from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from optimatrix.decision import schedule_decision_windows
from optimatrix.deribit_snapshot import (
    DERIBIT_DELIVERY_PRICE_METHOD_ID,
    DERIBIT_DELIVERY_PRICE_SOURCE_ID,
    DERIBIT_INDEX_PATH_METHOD_ID,
    DERIBIT_PUBLIC_METHOD_ALLOWLIST,
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


@pytest.fixture(autouse=True)
def _freeze_public_snapshot_receive_clock(monkeypatch) -> None:
    boundary = datetime(2026, 8, 12, 18, 7, tzinfo=UTC).timestamp()
    monkeypatch.setattr("optimatrix.deribit_snapshot.time.time", lambda: boundary)


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
        is EventStateSource.EXPLICIT_HUMAN_OR_EXTERNAL_CALENDAR_INPUT
    )
    snapshot = evaluation.as_object()
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
    assert "SELECTION_UNIVERSE_INCOMPLETE" in evaluation.observation.data_health_blockers
    assert evaluation.selection is None
    snapshot = evaluation.as_object()
    assert snapshot["projection"]["state"] == "UNKNOWN"


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
    monkeypatch,
) -> None:
    session = current_deribit_session(
        datetime(2026, 8, 12, 18, 7, tzinfo=UTC),
        phase_policy=policy.session,
    )
    now = session.end - timedelta(minutes=29)
    monkeypatch.setattr("optimatrix.deribit_snapshot.time.time", lambda: now.timestamp())

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


def test_http_client_preserves_validated_production_json_rpc_envelope(monkeypatch) -> None:
    sent_ms = int(datetime(2026, 8, 12, 18, 7, tzinfo=UTC).timestamp() * 1000)
    receive_ms = sent_ms + 50
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

    clock = iter((sent_ms / 1000, receive_ms / 1000))
    monkeypatch.setattr("optimatrix.deribit_snapshot.time.time", lambda: next(clock))
    monkeypatch.setattr("optimatrix.deribit_snapshot.HTTPSConnection", FakeHttpsConnection)
    response = DeribitHttpClient(timeout_seconds=10).call(
        "public/get_index_price",
        {"index_name": "btc_usd"},
    )
    assert isinstance(response, PublicRpcResponse)
    assert response.result == {"index_price": 100000}
    assert response.testnet is False
    assert response.local_sent_at_ms == sent_ms
    assert response.local_received_at_ms == receive_ms
    assert response.server_processing_us == 10_000
    assert requests[0] == ("www.deribit.com", None, 10)
    method, path, body, headers = requests[1]
    assert method == "POST"
    assert path == "/api/v2/public/get_index_price"
    assert json.loads(body) == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "public/get_index_price",
        "params": {"index_name": "btc_usd"},
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


def test_public_clock_preflight_supports_result_only_fake_clients() -> None:
    local_now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    server_time_ms = int(local_now.timestamp() * 1000) + 75

    class ClockClient:
        def call(self, method: str, params: Mapping[str, object]) -> object:
            assert method == "public/get_time"
            assert not params
            return server_time_ms

    preflight = preflight_public_clock(
        ClockClient(),
        local_now=local_now,
        maximum_clock_skew_ms=100,
    )
    assert preflight.clock_skew_ms == 75
    assert preflight.request_round_trip_ms is None
    with pytest.raises(DeribitSourceError, match="clock skew"):
        preflight_public_clock(
            ClockClient(),
            local_now=local_now,
            maximum_clock_skew_ms=50,
        )


def test_snapshot_binds_explicit_target_and_forces_required_books(policy, monkeypatch) -> None:
    now = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
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

    crossed_at = target.ends_at + timedelta(seconds=1)
    monkeypatch.setattr(
        "optimatrix.deribit_snapshot.time.time",
        lambda: crossed_at.timestamp(),
    )
    crossed = evaluate_live_btc_snapshot(
        client=FakeDeribitClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=4,
        target_window=target,
        required_instrument_names=required_names,
    )
    assert crossed.decision_window == target
    assert "SNAPSHOT_CROSSED_TARGET_WINDOW_BOUNDARY" in crossed.observation.data_health_blockers
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
