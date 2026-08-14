from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from optimatrix.decision import DecisionResult, MarketObservation
from optimatrix.deribit_snapshot import PublicSnapshotEvaluation, SnapshotMethodology
from optimatrix.lifecycle import PositionState, TerminalMethod
from optimatrix.market import EventState, PriceLevel
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.runtime import BtcPublicShadowRuntime
from optimatrix.scenarios import base_chain, market_context
from optimatrix.session import DeribitSession, current_deribit_session
from optimatrix.structure import select_btc_0dte_condor


class FourLegRuntimeSource:
    """Deterministic public-market cuts with exactly one four-leg BTC book."""

    def __init__(self, policy: BtcShortVolPolicy, session: DeribitSession) -> None:
        self.policy = policy
        self.session = session
        self.index_price = Decimal("100000")
        self.directional_persistence = Decimal("0.10")
        self.short_ask: Decimal | None = None
        self.preflight_calls = 0
        self.snapshot_calls = 0
        self.sleeps: list[float] = []

    def preflight(self, *, local_now: datetime) -> datetime:
        self.preflight_calls += 1
        return local_now

    def snapshot(
        self,
        *,
        now: datetime,
        target_window,
        required_instrument_names: tuple[str, ...],
    ) -> PublicSnapshotEvaluation:
        self.snapshot_calls += 1
        quotes = base_chain(expiry=self.session.end, observed_at=now)
        if self.short_ask is not None:
            quotes = tuple(
                replace(quote, ask=(PriceLevel(self.short_ask, Decimal("1")),))
                if quote.instrument_name.endswith(("95000-P", "105000-C"))
                else quote
                for quote in quotes
            )
        assert len(quotes) == 4
        quote_names = tuple(sorted(quote.instrument_name for quote in quotes))
        assert set(required_instrument_names) <= set(quote_names)
        context = market_context(
            now,
            index=self.index_price,
            directional_persistence=self.directional_persistence,
            event=EventState.NONE,
            book_names=quote_names,
        )
        observation = MarketObservation.capture(
            channel_id=self.policy.channel_id,
            policy=self.policy.observation,
            context=context,
            quotes=quotes,
        )
        return PublicSnapshotEvaluation(
            observed_at=now,
            session_id=self.session.session_id,
            instrument_count=4,
            requested_book_count=4,
            fetched_book_count=4,
            quotes=quotes,
            context=context,
            observation=observation,
            selection=select_btc_0dte_condor(
                observation=observation,
                policy=self.policy,
            ),
            methodology=SnapshotMethodology(
                delta_method="DETERMINISTIC_CAPACITY_RUNTIME_TEST",
                concentration_method="DETERMINISTIC_CAPACITY_RUNTIME_TEST",
                index_history_cadence_ms=300_000,
                book_fetch_mode="DETERMINISTIC_FOUR_LEG_BOOK",
            ),
            warnings=(),
            decision_window=target_window,
        )


class StrictRuntimeClock:
    def __init__(self, runtime: BtcPublicShadowRuntime, *, after: datetime) -> None:
        self.runtime = runtime
        self.last = after

    def tick(self, now: datetime) -> None:
        assert now > self.last
        self.runtime.tick(now)
        self.last = now


def _session(policy: BtcShortVolPolicy) -> DeribitSession:
    return current_deribit_session(
        datetime(2026, 8, 12, 8, tzinfo=UTC),
        phase_policy=policy.session,
    )


def _record_for(runtime: BtcPublicShadowRuntime, window_index: int):
    window_id = runtime.windows[window_index].identity
    return next(record for record in runtime.ledger.read() if record.window.identity == window_id)


def _open_candidate(
    runtime: BtcPublicShadowRuntime,
    clock: StrictRuntimeClock,
    source: FourLegRuntimeSource,
    window_index: int,
):
    before = set(runtime.cases)
    window = runtime.windows[window_index]
    clock.tick(window.starts_at + timedelta(seconds=1))
    source.directional_persistence = Decimal("0.90")
    clock.tick(runtime.windows[window_index + 1].starts_at + timedelta(seconds=1))
    source.directional_persistence = Decimal("0.10")
    clock.tick(window.input_deadline)
    record = _record_for(runtime, window_index)
    assert record.result is DecisionResult.CANDIDATE
    opened = set(runtime.cases) - before
    assert len(opened) == 1
    return runtime.cases[opened.pop()], record


def _allocation(record) -> dict[str, object]:
    allocation = record.risk_allocation
    assert allocation is not None
    return allocation


def _allocation_decimal(allocation: dict[str, object], field: str) -> Decimal:
    return Decimal(str(allocation[field]))


def _assert_all_case_snapshots_keep_frozen_truth(runtime: BtcPublicShadowRuntime) -> None:
    for case in runtime.cases.values():
        snapshots = runtime.journal.read(case.identity)
        assert snapshots
        assert {snapshot.selected_structure_json for snapshot in snapshots} == {
            case.selected_structure_json
        }
        assert {snapshot.risk_allocation_json for snapshot in snapshots} == {
            case.risk_allocation_json
        }


def test_runtime_capacity_freeze_recovers_and_releases_after_one_strictly_later_exit(
    policy: BtcShortVolPolicy,
    tmp_path,
) -> None:
    assert policy.risk.maximum_concurrent_positions == 2
    assert policy.risk.maximum_session_stress_reserve_usd == Decimal("600")
    session = _session(policy)
    source = FourLegRuntimeSource(policy, session)
    root = tmp_path / "stable"
    runtime = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    clock = StrictRuntimeClock(runtime, after=session.start - timedelta(minutes=10))

    first_case_id: str
    second_case_id: str
    second_entry_at: datetime
    frozen_before_restart: dict[str, tuple[str, str]]
    try:
        first, first_record = _open_candidate(runtime, clock, source, 4)
        first_case_id = first.identity
        first_allocation = _allocation(first_record)
        assert first_allocation["result"] == "AVAILABLE"
        assert _allocation_decimal(first_allocation, "session_used_before_usd") == 0
        assert _allocation_decimal(first_allocation, "session_remaining_after_usd") == 400
        assert first_allocation["open_position_count_before"] == 0

        first_entry_at = first.decision_boundary + timedelta(
            seconds=policy.lifecycle.monitoring_cadence_seconds + 1
        )
        clock.tick(first_entry_at)
        assert runtime.cases[first_case_id].position_state is PositionState.MONITORING

        source.index_price = Decimal("102000")
        second, second_record = _open_candidate(runtime, clock, source, 6)
        second_case_id = second.identity
        second_allocation = _allocation(second_record)
        assert second_allocation["result"] == "AVAILABLE"
        assert _allocation_decimal(second_allocation, "session_used_before_usd") == 200
        assert _allocation_decimal(second_allocation, "session_remaining_after_usd") == 200
        assert second_allocation["open_position_count_before"] == 1

        second_entry_at = second.decision_boundary + timedelta(
            seconds=policy.lifecycle.monitoring_cadence_seconds + 1
        )
        clock.tick(second_entry_at - timedelta(seconds=30))
        clock.tick(second_entry_at)
        assert runtime.cases[second_case_id].position_state is PositionState.MONITORING
        assert (
            sum(case.position_state is PositionState.MONITORING for case in runtime.cases.values())
            == 2
        )

        frozen_before_restart = {
            case_id: (case.selected_structure_json, case.risk_allocation_json)
            for case_id, case in runtime.cases.items()
        }
        _assert_all_case_snapshots_keep_frozen_truth(runtime)
    finally:
        runtime.close()

    restart_at = second_entry_at + timedelta(seconds=1)
    recovered = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=restart_at,
        target_session=session,
        sleep=source.sleeps.append,
    )
    recovered_clock = StrictRuntimeClock(recovered, after=restart_at)
    try:
        assert recovered.progress.restart_count == 1
        assert recovered.progress.recovered_case_count == 2
        assert set(recovered.cases) == {first_case_id, second_case_id}
        assert all(
            case.position_state is PositionState.MONITORING for case in recovered.cases.values()
        )
        assert {
            case_id: (case.selected_structure_json, case.risk_allocation_json)
            for case_id, case in recovered.cases.items()
        } == frozen_before_restart
        _assert_all_case_snapshots_keep_frozen_truth(recovered)

        # Both Positions share cadence, but their frozen Entry indices differ.
        # A 104k cut is adverse by >3% only to the first Position (Entry 100k),
        # while the second Position (Entry 102k) remains below its trigger.
        due_at = second_entry_at + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds)
        blocked_capture_at = recovered.windows[8].starts_at + timedelta(seconds=1)
        cadence = timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds)
        while due_at < blocked_capture_at:
            recovered_clock.tick(due_at)
            due_at += cadence

        assert due_at == blocked_capture_at
        recovered_clock.tick(blocked_capture_at)
        due_at += cadence
        blocked_deadline = recovered.windows[8].input_deadline
        while due_at < blocked_deadline:
            recovered_clock.tick(due_at)
            due_at += cadence

        assert due_at == blocked_deadline + timedelta(seconds=1)
        recovered_clock.tick(blocked_deadline)
        blocked_record = _record_for(recovered, 8)
        blocked_allocation = _allocation(blocked_record)
        assert blocked_record.result is DecisionResult.ABSTAIN
        assert blocked_record.blockers == ("SHADOW_CONCURRENT_POSITION_LIMIT_REACHED",)
        assert blocked_allocation["result"] == "UNAVAILABLE"
        assert blocked_allocation["reason"] == "SHADOW_CONCURRENT_POSITION_LIMIT_REACHED"
        assert _allocation_decimal(blocked_allocation, "session_used_before_usd") == 400
        assert _allocation_decimal(blocked_allocation, "session_remaining_after_usd") == 0
        assert blocked_allocation["open_position_count_before"] == 2
        assert len(recovered.cases) == 2

        source.index_price = Decimal("104000")
        trigger_at = due_at
        recovered_clock.tick(trigger_at)
        due_at += cadence
        assert recovered.cases[first_case_id].position_state is PositionState.EXIT_INTENT_FROZEN
        assert recovered.cases[first_case_id].outcome is None
        assert recovered.cases[second_case_id].position_state is PositionState.MONITORING

        source.index_price = Decimal("102000")
        exit_at = due_at
        recovered_clock.tick(exit_at)
        due_at += cadence
        terminal = recovered.cases[first_case_id]
        surviving = recovered.cases[second_case_id]
        assert surviving.position_state is PositionState.MONITORING
        assert surviving.outcome is None
        assert terminal.position_state is PositionState.TERMINAL
        assert terminal.outcome is not None
        assert terminal.outcome.terminal_method is TerminalMethod.WHOLE_PRODUCT_EXIT
        assert terminal.exit_intent is not None
        assert terminal.outcome.terminal_at > terminal.exit_intent.known_at

        released_deadline = recovered.windows[9].input_deadline
        while due_at < released_deadline:
            recovered_clock.tick(due_at)
            due_at += cadence
        recovered_clock.tick(released_deadline)
        released_record = _record_for(recovered, 9)
        released_allocation = _allocation(released_record)
        assert released_allocation["result"] == "AVAILABLE"
        assert _allocation_decimal(released_allocation, "session_used_before_usd") == 200
        assert _allocation_decimal(released_allocation, "session_remaining_after_usd") == 200
        assert released_allocation["open_position_count_before"] == 1
        released_ids = set(recovered.cases) - {first_case_id, second_case_id}
        assert len(released_ids) == 1
        assert len(recovered.cases) == 3
        _assert_all_case_snapshots_keep_frozen_truth(recovered)
        assert source.preflight_calls == 1
        assert source.sleeps == []
    finally:
        recovered.close()


def test_runtime_reconstructs_and_releases_the_exact_stress_reserve(
    policy: BtcShortVolPolicy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FourLegRuntimeSource(policy, session)
    source.short_ask = Decimal("0.020")
    root = tmp_path / "stress-reserve"
    runtime = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    clock = StrictRuntimeClock(runtime, after=session.start - timedelta(minutes=10))
    try:
        opened, record = _open_candidate(runtime, clock, source, 4)
        allocation = _allocation(record)
        reserve = _allocation_decimal(allocation, "stress_reserve_usd")
        assert reserve == Decimal("402.00000")
        entry_at = opened.decision_boundary + timedelta(
            seconds=policy.lifecycle.monitoring_cadence_seconds + 1
        )
        clock.tick(entry_at)
        assert runtime.cases[opened.identity].position_state is PositionState.MONITORING
        assert runtime._capacity(runtime.windows[6], entry_at).stress_reserve_used_usd == reserve
    finally:
        runtime.close()

    restart_at = entry_at + timedelta(seconds=1)
    recovered = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=restart_at,
        target_session=session,
        sleep=source.sleeps.append,
    )
    recovered_clock = StrictRuntimeClock(recovered, after=restart_at)
    try:
        assert (
            recovered._capacity(recovered.windows[6], restart_at).stress_reserve_used_usd == reserve
        )
        trigger_at = entry_at + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds)
        source.index_price = Decimal("104000")
        recovered_clock.tick(trigger_at)
        armed = recovered.cases[opened.identity]
        assert armed.position_state is PositionState.EXIT_INTENT_FROZEN

        exit_at = trigger_at + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds)
        source.index_price = Decimal("100000")
        recovered_clock.tick(exit_at)
        terminal = recovered.cases[opened.identity]
        assert terminal.position_state is PositionState.TERMINAL
        assert terminal.outcome is not None
        assert recovered._capacity(recovered.windows[6], exit_at).stress_reserve_used_usd == 0
    finally:
        recovered.close()


def test_runtime_capacity_rejects_an_allocation_without_current_stress_truth(
    policy: BtcShortVolPolicy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FourLegRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "malformed-stress-reserve",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    clock = StrictRuntimeClock(runtime, after=session.start - timedelta(minutes=10))
    try:
        opened, _record = _open_candidate(runtime, clock, source, 4)
        allocation = dict(opened.risk_allocation)
        allocation.pop("stress_reserve_usd")
        runtime.cases[opened.identity] = replace(
            opened,
            risk_allocation_json=json.dumps(
                allocation,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )

        with pytest.raises(ValueError, match="content identity"):
            runtime._capacity(runtime.windows[6], opened.decision_boundary)
    finally:
        runtime.close()
