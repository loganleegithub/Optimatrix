from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from threading import Lock
from typing import Any

import pytest

from optimatrix.decision import DecisionResult
from optimatrix.deribit_snapshot import (
    evaluate_live_btc_snapshot,
    fetch_btc_expiry_settlement,
    fetch_btc_index_history,
)
from optimatrix.lifecycle import (
    ObservationStatus,
    PositionState,
    TerminalMethod,
    evaluate_shadow_exit,
    monitor_shadow_position,
)
from optimatrix.market import EventState
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.runtime import BtcPublicShadowRuntime, IndexHistoryCapture
from optimatrix.session import DeribitSession, current_deribit_session


@dataclass(frozen=True)
class TapeStage:
    label: str
    index_price: Decimal
    mark_iv: Decimal = Decimal("55")
    bid_shift: Decimal = Decimal(0)
    ask_shift: Decimal = Decimal(0)
    shallow_buyback_role: str | None = None


class RawDeribitTapeClient:
    """A deterministic tape whose values have Deribit's public result shapes."""

    _LEG_SPECS = (
        ("long_put", "93000", "put", "-0.05", "0.0008", "0.0009"),
        ("short_put", "95000", "put", "-0.15", "0.0028", "0.0029"),
        ("short_call", "105000", "call", "0.15", "0.0028", "0.0029"),
        ("long_call", "107000", "call", "0.05", "0.0008", "0.0009"),
    )

    def __init__(self, session: DeribitSession) -> None:
        self.session = session
        self.now = session.start
        self.stage = TapeStage("BOOT", Decimal("100000"))
        self.calls: list[tuple[str, dict[str, object], str]] = []
        self._lock = Lock()
        self._history: list[tuple[int, Decimal]] = []
        self._pending_history_point: tuple[int, Decimal, str] | None = None
        self.include_current_history_point = False
        self.stage_points: dict[str, list[tuple[int, Decimal]]] = {}
        self.history_retention_start_ms = int(
            (session.start - timedelta(days=2)).timestamp() * 1000
        )
        expiry_code = session.end.strftime("%d%b%y").lstrip("0").upper()
        self.names = {
            role: f"BTC-{expiry_code}-{strike}-{option_type[0].upper()}"
            for role, strike, option_type, _delta, _bid, _ask in self._LEG_SPECS
        }

    def set_cut(self, *, now: datetime, stage: TapeStage) -> None:
        self.now = now
        self.stage = stage

    def call(self, method: str, params: dict[str, object]) -> object:
        with self._lock:
            self.calls.append((method, dict(params), self.stage.label))
        if method == "public/get_time":
            return int(self.now.timestamp() * 1000)
        if method == "public/get_index_price":
            assert params == {"index_name": "btc_usd"}
            return {"index_price": float(self.stage.index_price)}
        if method == "public/get_instruments":
            assert params == {"currency": "BTC", "kind": "option", "expired": False}
            return self._instruments()
        if method == "public/get_order_book":
            assert params["depth"] == 20
            return self._order_book(str(params["instrument_name"]))
        if method == "public/get_index_chart_data":
            assert params == {"index_name": "btc_usd", "range": "2d"}
            return self._index_history()
        if method == "public/get_delivery_prices":
            assert params == {"index_name": "btc_usd", "offset": 0, "count": 10}
            return {
                "data": [
                    {
                        "date": self.session.end.date().isoformat(),
                        "delivery_price": 104_000.0,
                    }
                ],
                "records_total": 1,
            }
        raise AssertionError(f"unexpected public method: {method}")

    def _instruments(self) -> list[dict[str, object]]:
        expiry_ms = int(self.session.end.timestamp() * 1000)
        return [
            {
                "instrument_name": self.names[role],
                "kind": "option",
                "is_active": True,
                "expiration_timestamp": expiry_ms,
                "base_currency": "BTC",
                "settlement_currency": "BTC",
                "price_index": "btc_usd",
                "contract_size": 1,
                "min_trade_amount": 0.1,
                "strike": int(strike),
                "option_type": option_type,
                "tick_size": 0.0001,
                "tick_size_steps": [{"above_price": 0.005, "tick_size": 0.0005}],
                "settlement_period": "day",
            }
            for role, strike, option_type, _delta, _bid, _ask in self._LEG_SPECS
        ]

    def _order_book(self, instrument_name: str) -> dict[str, object]:
        for offset, (role, _strike, _option_type, delta, bid, ask) in enumerate(self._LEG_SPECS):
            if self.names[role] != instrument_name:
                continue
            bid_price = Decimal(bid) + self.stage.bid_shift
            ask_price = Decimal(ask) + self.stage.ask_shift
            ask_quantity = (
                Decimal("0.05") if self.stage.shallow_buyback_role == role else Decimal("1")
            )
            timestamp_ms = int(self.now.timestamp() * 1000) - 1_000 + offset * 100
            return {
                "instrument_name": instrument_name,
                "state": "open",
                "timestamp": timestamp_ms,
                "underlying_price": float(self.stage.index_price),
                "mark_iv": float(self.stage.mark_iv),
                "open_interest": 1_000.0,
                "greeks": {"delta": float(Decimal(delta)), "gamma": 0.0001},
                "bids": [[float(bid_price), 1.0]],
                "asks": [[float(ask_price), float(ask_quantity)]],
            }
        raise AssertionError(f"unexpected instrument: {instrument_name}")

    def _index_history(self) -> list[list[float | int]]:
        now_ms = int(self.now.timestamp() * 1000)
        if not self._history:
            self._seed_history(now_ms)
        self._commit_pending_history_point()
        self._fill_history_before(now_ms)
        history_timestamp_ms = now_ms - 1_000 if now_ms % (5 * 60_000) == 1_000 else now_ms
        self._queue_history_point(
            history_timestamp_ms,
            self.stage.index_price,
            self.stage.label,
        )
        if self.include_current_history_point or history_timestamp_ms != now_ms:
            self._commit_pending_history_point()
            self.include_current_history_point = False
        return [
            [timestamp_ms, float(price)]
            for timestamp_ms, price in self._history
            if timestamp_ms >= self.history_retention_start_ms
        ]

    @property
    def history_points(self) -> tuple[tuple[int, Decimal], ...]:
        return tuple(self._history)

    def _seed_history(self, now_ms: int) -> None:
        cadence_ms = 5 * 60_000
        start_ms = self.history_retention_start_ms
        for index, timestamp_ms in enumerate(range(start_ms, now_ms, cadence_ms)):
            factor = Decimal("1.0014") if index % 2 else Decimal(1)
            self._append_history_point(timestamp_ms, Decimal("100000") * factor)

    def _fill_history_before(self, now_ms: int) -> None:
        cadence_ms = 5 * 60_000
        assert self._history
        timestamp_ms = self._history[-1][0] + cadence_ms
        price = self._history[-1][1]
        while timestamp_ms < now_ms:
            self._append_history_point(timestamp_ms, price)
            timestamp_ms += cadence_ms

    def _queue_history_point(self, timestamp_ms: int, price: Decimal, label: str) -> None:
        if self._history and timestamp_ms <= self._history[-1][0]:
            self._append_history_point(timestamp_ms, price)
            return
        self._pending_history_point = (timestamp_ms, price, label)
        self.stage_points.setdefault(label, []).append((timestamp_ms, price))

    def _commit_pending_history_point(self) -> None:
        if self._pending_history_point is None:
            return
        timestamp_ms, price, _label = self._pending_history_point
        self._append_history_point(timestamp_ms, price)
        self._pending_history_point = None

    def _append_history_point(self, timestamp_ms: int, price: Decimal) -> None:
        if self._history:
            last_timestamp_ms, last_price = self._history[-1]
            if timestamp_ms < last_timestamp_ms:
                raise ValueError("raw index history cannot move backwards")
            if timestamp_ms == last_timestamp_ms:
                if price != last_price:
                    raise ValueError("raw index history cannot rewrite a timestamp")
                return
        self._history.append((timestamp_ms, price))


class RawMarketTapeSource:
    def __init__(self, policy: BtcShortVolPolicy, session: DeribitSession) -> None:
        self.policy = policy
        self.session = session
        self.client = RawDeribitTapeClient(session)
        self.stage = TapeStage("DEFAULT", Decimal("100000"))
        self.required_name_requests: list[tuple[str, ...]] = []
        self.evaluations: list[tuple[str, Any]] = []
        self.sleeps: list[float] = []

    def preflight(self, *, local_now: datetime) -> datetime:
        self.client.set_cut(now=local_now, stage=self.stage)
        return local_now

    def snapshot(
        self,
        *,
        now: datetime,
        target_window: Any,
        required_instrument_names: tuple[str, ...],
    ):
        self.required_name_requests.append(required_instrument_names)
        self.client.set_cut(now=now, stage=self.stage)
        evaluation = evaluate_live_btc_snapshot(
            client=self.client,
            policy=self.policy,
            now=now,
            event_state=EventState.NONE,
            maximum_books=32,
            depth=20,
            target_window=target_window,
            required_instrument_names=required_instrument_names,
        )
        self.evaluations.append((self.stage.label, evaluation))
        return evaluation

    def history(self, *, known_at: datetime) -> IndexHistoryCapture:
        self.client.set_cut(now=known_at, stage=self.stage)
        self.client.include_current_history_point = True
        self.client.history_retention_start_ms = 0
        return IndexHistoryCapture(
            points=fetch_btc_index_history(self.client, known_at=known_at),
            known_at=known_at,
            error=None,
        )

    def settlement(self, *, expiry: datetime, known_at: datetime):
        self.client.set_cut(now=known_at, stage=self.stage)
        return fetch_btc_expiry_settlement(
            self.client,
            expiry=expiry,
            known_at=known_at,
        )


def _session(policy: BtcShortVolPolicy) -> DeribitSession:
    return current_deribit_session(
        datetime(2026, 8, 12, 8, tzinfo=UTC),
        phase_policy=policy.session,
    )


def _document(path: Path) -> dict[str, object]:
    source = path.read_text(encoding="utf-8")
    prefix = "window.OPTIMATRIX_WORKBENCH = Object.freeze("
    return json.loads(source.removeprefix(prefix).removesuffix(");\n"))


def _row_value(rows: object, key: str) -> object:
    assert isinstance(rows, list)
    row = next(item for item in rows if isinstance(item, dict) and item.get("key") == key)
    return row["value"]


def _start_candidate_case(runtime: BtcPublicShadowRuntime, source: RawMarketTapeSource):
    runtime.tick(runtime.session.start - timedelta(minutes=5))
    candidate_window = runtime.windows[4]
    source.stage = TapeStage(
        "WINDOW_ABSTAIN",
        Decimal("100000"),
        mark_iv=Decimal("0.000001"),
    )
    runtime.tick(runtime.windows[0].starts_at + timedelta(seconds=1))
    for window in runtime.windows[:3]:
        runtime.tick(window.input_deadline)
    source.stage = TapeStage("CANDIDATE", Decimal("100000"))
    runtime.tick(runtime.windows[3].input_deadline)
    source.stage = TapeStage(
        "WINDOW_ABSTAIN",
        Decimal("100000"),
        mark_iv=Decimal("0.000001"),
    )
    runtime.tick(candidate_window.input_deadline)

    candidate_records = [
        record for record in runtime.ledger.read() if record.result is DecisionResult.CANDIDATE
    ]
    assert len(candidate_records) == 1
    assert len(runtime.cases) == 1
    return candidate_records[0], next(iter(runtime.cases.values()))


def _tick_case_stage(
    runtime: BtcPublicShadowRuntime,
    source: RawMarketTapeSource,
    *,
    at: datetime,
    stage: TapeStage,
):
    source.stage = stage
    runtime.tick(at)
    assert len(runtime.cases) == 1
    return next(iter(runtime.cases.values()))


def _finish_session(
    runtime: BtcPublicShadowRuntime,
    source: RawMarketTapeSource,
    *,
    after: datetime,
    continuation_stage: TapeStage,
) -> None:
    source.stage = continuation_stage
    cursor = after
    for window in runtime.windows:
        if window.input_deadline > after:
            capture_at = window.starts_at + timedelta(minutes=5)
            if capture_at > cursor:
                runtime.tick(capture_at)
                cursor = capture_at
            assert window.input_deadline > cursor
            runtime.tick(window.input_deadline)
            cursor = window.input_deadline
    source.stage = TapeStage(
        "OUTCOME_PATH",
        continuation_stage.index_price,
        mark_iv=continuation_stage.mark_iv,
    )
    runtime.tick(runtime.session.end + timedelta(minutes=5))
    runtime.tick(runtime.finalization_at)

    decisions = runtime.ledger.summarize(expected_windows=runtime.windows)
    outcomes = runtime.ledger.summarize_outcomes(expected_windows=runtime.windows)
    assert decisions.denominator == decisions.recorded == 96
    assert outcomes.denominator == outcomes.recorded == 96
    assert outcomes.future_path_known == outcomes.continuous == 96
    assert source.client.calls[-1][0] == "public/get_index_chart_data"
    evaluated_window_ids = {
        evaluation.decision_window.identity for _stage, evaluation in source.evaluations
    }
    assert evaluated_window_ids == {window.identity for window in runtime.windows}
    assert all(
        evaluation.requested_book_count == evaluation.fetched_book_count == 4
        and len(evaluation.quotes) == 4
        and evaluation.observation.context.event_state is EventState.NONE
        and not evaluation.observation.data_health_blockers
        for _stage, evaluation in source.evaluations
    )
    assert len(runtime.cases) == 1
    event_lines = (runtime.root_owner.root / "runtime-events.jsonl").read_text(encoding="utf-8")
    assert "PUBLIC_MARKET_CUT_ATTEMPT_FAILED" not in event_lines
    assert "PUBLIC_MARKET_GAP" not in event_lines
    assert all(
        record.result in {DecisionResult.ABSTAIN, DecisionResult.REVIEW}
        for record in runtime.ledger.read()
        if record.result is not DecisionResult.CANDIDATE
    )
    assert runtime.complete


def _assert_staged_points_are_in_final_history(
    source: RawMarketTapeSource,
    *labels: str,
) -> None:
    history = source.client.history_points
    assert all(current[0] > previous[0] for previous, current in pairwise(history))
    by_timestamp = dict(history)
    for label in labels:
        staged = source.client.stage_points[label]
        assert staged
        assert all(by_timestamp[timestamp_ms] == price for timestamp_ms, price in staged)


def test_raw_four_leg_tape_runs_candidate_to_strictly_later_whole_product_exit(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = RawMarketTapeSource(policy, session)
    root = tmp_path / "raw-market-exit"
    runtime = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        record, opened = _start_candidate_case(runtime, source)
        expected_names = tuple(sorted(source.client.names.values()))
        structure = record.selected_structure
        allocation = record.risk_allocation
        assert structure is not None
        assert allocation is not None
        assert tuple(sorted(leg["instrument_name"] for leg in structure["legs"].values())) == (
            expected_names
        )
        assert structure["option_amount"] == "0.1"
        assert allocation["result"] == "AVAILABLE"
        assert allocation["candidate_id"] == structure["candidate_id"]
        assert allocation["option_amount"] == "0.1"
        assert allocation["maximum_contractual_payoff_usd"] == "200.0"
        assert allocation["session_budget_usd"] == "600"
        assert allocation["session_used_before_usd"] == "0"
        assert allocation["session_remaining_after_usd"] == "400.0"
        assert len(allocation["delivery_stress"]) == 3
        assert opened.selected_structure_json == record.selected_structure_json
        assert opened.risk_allocation_json == record.risk_allocation_json

        entry_at = opened.decision_boundary + timedelta(seconds=61)
        entered = _tick_case_stage(
            runtime,
            source,
            at=entry_at,
            stage=TapeStage("ENTRY", Decimal("100000")),
        )
        assert entered.entry_final
        assert entered.position_state is PositionState.MONITORING
        assert entered.entry_observed_at is not None
        assert entered.entry_observed_at > opened.decision_boundary
        assert entered.entry_observation_id != record.observation_id

        hold_one_at = entry_at + timedelta(seconds=60)
        held_one = _tick_case_stage(
            runtime,
            source,
            at=hold_one_at,
            stage=TapeStage(
                "HOLD_ONE",
                Decimal("100100"),
                bid_shift=Decimal("0.0001"),
                ask_shift=Decimal("0.0001"),
            ),
        )
        assert held_one.position_state is PositionState.MONITORING
        assert held_one.exit_intent is None

        hold_two_at = hold_one_at + timedelta(seconds=60)
        held_two = _tick_case_stage(
            runtime,
            source,
            at=hold_two_at,
            stage=TapeStage(
                "HOLD_TWO",
                Decimal("99900"),
                bid_shift=Decimal("-0.0001"),
                ask_shift=Decimal("0.0001"),
            ),
        )
        assert held_two.position_state is PositionState.MONITORING
        assert held_two.exit_intent is None
        assert held_two.last_observed_at is not None
        assert held_one.last_observed_at is not None
        assert held_two.last_observed_at > held_one.last_observed_at

        trigger_at = hold_two_at + timedelta(seconds=60)
        armed = _tick_case_stage(
            runtime,
            source,
            at=trigger_at,
            stage=TapeStage("ADVERSE_TRIGGER", Decimal("104100")),
        )
        assert armed.position_state is PositionState.EXIT_INTENT_FROZEN
        assert armed.exit_intent is not None
        assert armed.exit_intent.reason == "ADVERSE_MOVE"
        assert armed.exit_intent.observation_id == armed.last_observation_id
        trigger_evaluation = next(
            evaluation for stage, evaluation in source.evaluations if stage == "ADVERSE_TRIGGER"
        )
        _replayed_armed, monitor = monitor_shadow_position(
            held_two,
            observation=trigger_evaluation.observation,
            policy=policy,
        )
        assert monitor.known_triggers == (
            "ADVERSE_MOVE",
            "RV_ACCELERATION",
            "VRP_PROXY_DISSIPATED",
        )

        exit_at = trigger_at + timedelta(seconds=60)
        terminal = _tick_case_stage(
            runtime,
            source,
            at=exit_at,
            stage=TapeStage("FULL_DEPTH_EXIT", Decimal("104100")),
        )
        assert terminal.position_state is PositionState.TERMINAL
        assert terminal.outcome is not None
        assert terminal.outcome.terminal_method is TerminalMethod.WHOLE_PRODUCT_EXIT
        assert terminal.outcome.terminal_source == "STRICTLY_LATER_PUBLIC_FOUR_LEG_ESTIMATE"
        assert terminal.outcome.terminal_evidence_id == terminal.last_observation_id
        assert terminal.exit_intent == armed.exit_intent
        assert terminal.last_observed_at is not None
        assert terminal.exit_intent.observed_at < terminal.last_observed_at
        assert terminal.entry_observed_at is not None
        assert (
            record.known_at
            < terminal.entry_observed_at
            < held_one.last_observed_at
            < held_two.last_observed_at
            < terminal.exit_intent.observed_at
            < terminal.last_observed_at
        )

        snapshots = runtime.journal.read(terminal.identity)
        assert snapshots[-1] == terminal
        assert len({case.selected_structure_json for case in snapshots}) == 1
        assert len({case.risk_allocation_json for case in snapshots}) == 1
        lifecycle_required = [names for names in source.required_name_requests if names]
        assert len(lifecycle_required) == 5
        assert all(names == expected_names for names in lifecycle_required)
        lifecycle_book_calls = [
            params
            for method, params, stage in source.client.calls
            if method == "public/get_order_book"
            and stage in {"ENTRY", "HOLD_ONE", "HOLD_TWO", "ADVERSE_TRIGGER", "FULL_DEPTH_EXIT"}
        ]
        assert len(lifecycle_book_calls) == 5 * 4
        assert {str(params["instrument_name"]) for params in lifecycle_book_calls} == set(
            expected_names
        )
        assert {params["depth"] for params in lifecycle_book_calls} == {20}

        _finish_session(
            runtime,
            source,
            after=exit_at,
            continuation_stage=TapeStage(
                "WINDOW_ABSTAIN_AFTER_EXIT",
                Decimal("104100"),
                mark_iv=Decimal("0.000001"),
            ),
        )
        _assert_staged_points_are_in_final_history(
            source,
            "CANDIDATE",
            "ENTRY",
            "HOLD_ONE",
            "HOLD_TWO",
            "ADVERSE_TRIGGER",
            "FULL_DEPTH_EXIT",
        )
        document = _document(root / "workbench/workbench-data.js")
        assert document["runtime"]["status"] == "COMPLETE_PENDING_TRADER_ACCEPTANCE"
        assert document["population"]["decisions"]["recorded"] == "96"
        assert document["population"]["outcomes"]["recorded"] == "96"
        rendered = next(
            item for item in document["cases"] if item["trade_case_id"] == terminal.identity
        )
        assert rendered["position_state"] == "TERMINAL"
        assert _row_value(rendered["exit_intent"], "reason") == "ADVERSE_MOVE"
        assert _row_value(rendered["outcome"], "terminal_method") == "WHOLE_PRODUCT_EXIT"
        assert len(rendered["selected_structure"]["legs"]) == 4
        assert _row_value(rendered["risk_allocation"], "result") == "AVAILABLE"

        last_timestamp_ms, last_price = source.client.history_points[-1]
        source.client.set_cut(
            now=datetime.fromtimestamp(last_timestamp_ms / 1000, tz=UTC),
            stage=TapeStage("CONFLICTING_REPLAY", last_price + Decimal(1)),
        )
        with pytest.raises(ValueError, match="cannot rewrite a timestamp"):
            source.client.call(
                "public/get_index_chart_data",
                {"index_name": "btc_usd", "range": "2d"},
            )
    finally:
        runtime.close()


def test_raw_shallow_buyback_keeps_exit_intent_until_official_settlement(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = RawMarketTapeSource(policy, session)
    root = tmp_path / "raw-market-settlement"
    runtime = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        _record, opened = _start_candidate_case(runtime, source)
        expected_names = tuple(sorted(source.client.names.values()))
        entry_at = opened.decision_boundary + timedelta(seconds=61)
        entered = _tick_case_stage(
            runtime,
            source,
            at=entry_at,
            stage=TapeStage("ENTRY", Decimal("100000")),
        )
        trigger_at = entry_at + timedelta(seconds=60)
        armed = _tick_case_stage(
            runtime,
            source,
            at=trigger_at,
            stage=TapeStage("ADVERSE_TRIGGER", Decimal("104100")),
        )
        assert entered.position_id is not None
        assert armed.exit_intent is not None
        assert armed.exit_intent.reason == "ADVERSE_MOVE"

        shallow_exit_at = trigger_at + timedelta(seconds=60)
        shallow_stage = TapeStage(
            "SHALLOW_BUYBACK",
            Decimal("104100"),
            mark_iv=Decimal("5"),
            shallow_buyback_role="short_call",
        )
        unresolved = _tick_case_stage(
            runtime,
            source,
            at=shallow_exit_at,
            stage=shallow_stage,
        )
        assert unresolved.position_id == entered.position_id
        assert unresolved.position_state is PositionState.EXIT_INTENT_FROZEN
        assert unresolved.exit_intent == armed.exit_intent
        assert unresolved.outcome is None
        assert unresolved.last_observation_id != armed.last_observation_id
        assert source.required_name_requests[-1] == expected_names
        shallow_evaluation = next(
            evaluation for stage, evaluation in source.evaluations if stage == "SHALLOW_BUYBACK"
        )
        _replayed_unresolved, exit_evaluation = evaluate_shadow_exit(
            armed,
            observation=shallow_evaluation.observation,
            policy=policy,
        )
        assert exit_evaluation.observation_status is ObservationStatus.UNKNOWN
        assert not exit_evaluation.terminal
        assert exit_evaluation.reason == "WHOLE_PRODUCT_EXIT_NOT_PRICE_EVALUABLE"
        shallow_books = [
            params
            for method, params, stage in source.client.calls
            if method == "public/get_order_book" and stage == "SHALLOW_BUYBACK"
        ]
        assert len(shallow_books) == 4

        source.stage = shallow_stage
        _finish_session(
            runtime,
            source,
            after=shallow_exit_at,
            continuation_stage=TapeStage(
                "WINDOW_ABSTAIN_AFTER_SHALLOW_EXIT",
                Decimal("104100"),
                mark_iv=Decimal("0.000001"),
                shallow_buyback_role="short_call",
            ),
        )
        _assert_staged_points_are_in_final_history(
            source,
            "CANDIDATE",
            "ENTRY",
            "ADVERSE_TRIGGER",
            "SHALLOW_BUYBACK",
        )
        terminal = runtime.cases[opened.identity]
        assert terminal.position_id == entered.position_id
        assert terminal.position_state is PositionState.TERMINAL
        assert terminal.exit_intent == armed.exit_intent
        assert terminal.outcome is not None
        assert terminal.outcome.terminal_method is TerminalMethod.CONTRACT_SETTLEMENT
        assert terminal.outcome.terminal_evidence_id == runtime.settlement_fact.identity
        assert terminal.outcome.data_gap_observed
        assert runtime.settlement_fact.delivery_price_usd == Decimal("104000.0")

        journal = runtime.journal.read(terminal.identity)
        assert journal[-1] == terminal
        assert any(
            case.position_state is PositionState.EXIT_INTENT_FROZEN and case.outcome is None
            for case in journal
        )
        assert len({case.selected_structure_json for case in journal}) == 1
        assert len({case.risk_allocation_json for case in journal}) == 1

        document = _document(root / "workbench/workbench-data.js")
        rendered = next(
            item for item in document["cases"] if item["trade_case_id"] == terminal.identity
        )
        assert document["runtime"]["status"] == "COMPLETE_PENDING_TRADER_ACCEPTANCE"
        assert rendered["position_state"] == "TERMINAL"
        assert _row_value(rendered["exit_intent"], "reason") == "ADVERSE_MOVE"
        assert _row_value(rendered["outcome"], "terminal_method") == "CONTRACT_SETTLEMENT"
        assert _row_value(rendered["outcome"], "data_gap_observed") == "YES"
    finally:
        runtime.close()
