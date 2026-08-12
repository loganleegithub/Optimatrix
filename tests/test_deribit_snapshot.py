from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from optimatrix.deribit_snapshot import evaluate_live_btc_snapshot
from optimatrix.market import EventState
from optimatrix.radar import Decision
from optimatrix.session import current_deribit_session
from optimatrix.workbench import build_workbench_document


class FakeDeribitClient:
    def __init__(
        self,
        now: datetime,
        *,
        combos: list[dict[str, object]] | None = None,
        remove_history_indexes: frozenset[int] = frozenset(),
    ) -> None:
        self.now = now
        self.combos = combos or []
        self.remove_history_indexes = remove_history_indexes
        self.expiry_ms = int(current_deribit_session(now).end.timestamp() * 1000)
        self.books = {
            "BTC-X-93000-P": self._book("BTC-X-93000-P", "-0.05", "0.0008", "0.0009"),
            "BTC-X-95000-P": self._book("BTC-X-95000-P", "-0.15", "0.0028", "0.0029"),
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
                self._instrument("BTC-X-105000-C", 105000, "call"),
                self._instrument("BTC-X-107000-C", 107000, "call"),
                {
                    **self._instrument("BTC-NEXT-95000-P", 95000, "put"),
                    "expiration_timestamp": self.expiry_ms + 86_400_000,
                },
            ]
        if method == "public/get_order_book":
            return self.books[str(params["instrument_name"])]
        if method == "public/get_index_chart_data":
            return [
                point
                for index, point in enumerate(self._history())
                if index not in self.remove_history_indexes
            ]
        if method == "public/get_combos":
            return self.combos
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
                [
                    int((start + timedelta(minutes=5 * index)).timestamp() * 1000),
                    str(price),
                ]
            )
        return output


def test_public_snapshot_adapter_evaluates_current_session_without_writing_cases(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    monkeypatch.chdir(tmp_path)
    evaluation = evaluate_live_btc_snapshot(
        client=FakeDeribitClient(now),
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        depth=20,
    )
    assert evaluation.instrument_count == 4
    assert evaluation.fetched_book_count == 4
    assert evaluation.decision.decision is Decision.CANDIDATE
    assert evaluation.decision.structure is not None
    assert evaluation.methodology.event_state_source.startswith("EXPLICIT_")
    assert evaluation.public_combo_id is None
    assert evaluation.selection.considered_condors > 0
    workbench = build_workbench_document(evaluation.as_object())
    assert workbench["structure"]["kind"] == "ASYMMETRIC_IRON_CONDOR"
    assert any(
        row["key"] == "ENTRY_ATTEMPT_SELECTED" and row["value"] == "PASSED · 1/1"
        for row in workbench["funnel"]
    )
    assert not (tmp_path / "build/live-snapshot-no-cases").exists()


def test_public_snapshot_detects_exact_existing_combo(policy) -> None:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    client = FakeDeribitClient(
        now,
        combos=[
            {
                "state": "active",
                "id": "BTC-EXACT-IRON-CONDOR",
                "legs": [
                    {"instrument_name": "BTC-X-93000-P", "amount": 1},
                    {"instrument_name": "BTC-X-95000-P", "amount": -1},
                    {"instrument_name": "BTC-X-105000-C", "amount": -1},
                    {"instrument_name": "BTC-X-107000-C", "amount": 1},
                ],
            }
        ],
    )
    evaluation = evaluate_live_btc_snapshot(
        client=client,
        policy=policy,
        now=now,
        event_state=EventState.NONE,
        maximum_books=8,
        depth=20,
    )
    assert evaluation.public_combo_id == "BTC-EXACT-IRON-CONDOR"


def test_material_index_history_gap_rejects_snapshot(policy) -> None:
    import pytest

    from optimatrix.deribit_snapshot import DeribitSourceError

    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    client = FakeDeribitClient(now, remove_history_indexes=frozenset({80, 81, 82}))
    with pytest.raises(DeribitSourceError, match="material risk-horizon gap"):
        evaluate_live_btc_snapshot(
            client=client,
            policy=policy,
            now=now,
            event_state=EventState.NONE,
            maximum_books=8,
            depth=20,
        )


def test_http_client_refuses_private_methods_without_network() -> None:
    import pytest

    from optimatrix.deribit_snapshot import DeribitHttpClient

    with pytest.raises(ValueError, match="only public"):
        DeribitHttpClient(base_url="https://invalid.example").call("private/buy", {})


def test_http_client_turns_incomplete_transport_into_truthful_source_error(monkeypatch) -> None:
    from http.client import IncompleteRead

    import pytest

    from optimatrix.deribit_snapshot import DeribitHttpClient, DeribitSourceError

    class BrokenResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            raise IncompleteRead(b"partial")

    monkeypatch.setattr(
        "optimatrix.deribit_snapshot.urlopen", lambda *_args, **_kwargs: BrokenResponse()
    )
    with pytest.raises(DeribitSourceError, match="IncompleteRead"):
        DeribitHttpClient(base_url="https://example.test").call("public/get_instruments", {})
