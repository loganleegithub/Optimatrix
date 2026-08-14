from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from optimatrix.case_journal import CaseJournal
from optimatrix.decision import DecisionRecord, DecisionResult, DecisionWindow, MarketObservation
from optimatrix.deribit_snapshot import (
    DERIBIT_DELIVERY_PRICE_METHOD_ID,
    DERIBIT_DELIVERY_PRICE_SOURCE_ID,
    DeribitClockReading,
    DeribitSourceError,
    PublicClockPreflight,
    PublicSnapshotEvaluation,
    SnapshotMethodology,
)
from optimatrix.identity import canonical_identity
from optimatrix.lifecycle import PositionState, TerminalMethod, open_trade_case
from optimatrix.market import (
    EventState,
    ExpirySettlementFact,
    SettlementEvidenceKind,
)
from optimatrix.products import BTC
from optimatrix.runtime import (
    BtcPublicShadowRuntime,
    DeribitPublicRuntimeSource,
    IndexHistoryCapture,
)
from optimatrix.scenarios import base_chain, market_context
from optimatrix.session import DeribitSession, current_deribit_session
from optimatrix.structure import select_btc_0dte_condor


class FakeRuntimeSource:
    def __init__(
        self,
        policy,
        session: DeribitSession,
        *,
        fail_snapshot: bool = False,
        snapshot_delay: timedelta = timedelta(0),
        frozen_source_at: datetime | None = None,
        settlement_failures: int = 0,
        event_state: EventState = EventState.NONE,
    ) -> None:
        self.policy = policy
        self.session = session
        self.fail_snapshot = fail_snapshot
        self.snapshot_delay = snapshot_delay
        self.frozen_source_at = frozen_source_at
        self.settlement_failures = settlement_failures
        self.event_state = event_state
        self.preflight_calls = 0
        self.snapshot_calls = 0
        self.snapshot_windows: list[DecisionWindow] = []
        self.history_calls = 0
        self.history_sessions: list[DeribitSession] = []
        self.settlement_calls = 0
        self.settlement_expiries: list[datetime] = []
        self.sleeps: list[float] = []

    def preflight(self, *, local_now: datetime) -> datetime:
        assert local_now.tzinfo is not None
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
        self.snapshot_windows.append(target_window)
        if self.fail_snapshot:
            raise DeribitSourceError("bounded fake market failure")
        response_at = now + self.snapshot_delay
        observed_at = self.frozen_source_at or response_at
        target_session = current_deribit_session(
            target_window.starts_at,
            phase_policy=self.policy.session,
        )
        quotes = base_chain(expiry=target_session.end, observed_at=observed_at)
        quote_names = tuple(sorted(quote.instrument_name for quote in quotes))
        assert set(required_instrument_names) <= set(quote_names)
        context = market_context(observed_at, event=self.event_state, book_names=quote_names)
        captured = MarketObservation.capture(
            channel_id=self.policy.channel_id,
            policy=self.policy.observation,
            context=context,
            quotes=quotes,
            known_at=response_at,
        )
        selection = (
            None
            if captured.data_health_blockers
            else select_btc_0dte_condor(observation=captured, policy=self.policy)
        )
        return PublicSnapshotEvaluation(
            observed_at=observed_at,
            session_id=self.session.session_id,
            instrument_count=len(quotes),
            requested_book_count=len(quotes),
            fetched_book_count=len(quotes),
            quotes=quotes,
            context=context,
            observation=captured,
            selection=selection,
            methodology=SnapshotMethodology(
                delta_method="DETERMINISTIC_RUNTIME_TEST",
                concentration_method="DETERMINISTIC_RUNTIME_TEST",
                index_history_cadence_ms=300_000,
                book_fetch_mode="DETERMINISTIC_RUNTIME_TEST",
            ),
            warnings=(),
            decision_window=target_window,
        )

    def history(
        self,
        *,
        known_at: datetime,
        session: DeribitSession | None = None,
    ) -> IndexHistoryCapture:
        target_session = session or self.session
        assert known_at >= target_session.end
        self.history_calls += 1
        self.history_sessions.append(target_session)
        known_at_ms = int(known_at.timestamp() * 1000)
        return IndexHistoryCapture(
            points=tuple(point for point in _history(target_session) if point[0] <= known_at_ms),
            known_at=known_at,
            error=None,
        )

    def settlement(
        self,
        *,
        expiry: datetime,
        known_at: datetime,
    ) -> ExpirySettlementFact:
        self.settlement_calls += 1
        self.settlement_expiries.append(expiry)
        if self.settlement_calls <= self.settlement_failures:
            raise DeribitSourceError("official settlement is not available yet")
        return ExpirySettlementFact(
            product_id=BTC.product_id,
            expiry=expiry,
            delivery_price_usd=Decimal("100000"),
            known_at=known_at,
            evidence_kind=SettlementEvidenceKind.OFFICIAL_EXCHANGE,
            source_id=DERIBIT_DELIVERY_PRICE_SOURCE_ID,
            method_id=DERIBIT_DELIVERY_PRICE_METHOD_ID,
        )


def _session(policy) -> DeribitSession:
    return current_deribit_session(
        datetime(2026, 8, 12, 8, tzinfo=UTC),
        phase_policy=policy.session,
    )


def _history(session: DeribitSession) -> tuple[tuple[int, Decimal], ...]:
    cursor = session.start - timedelta(hours=3)
    end = session.end + timedelta(minutes=15)
    price = Decimal("100000")
    output: list[tuple[int, Decimal]] = []
    index = 0
    while cursor <= end:
        if index:
            price *= Decimal("1.0002") if index % 2 else Decimal("0.9998")
        output.append((int(cursor.timestamp() * 1000), price))
        cursor += timedelta(minutes=5)
        index += 1
    return tuple(output)


def _document(path: Path) -> dict[str, object]:
    source = path.read_text(encoding="utf-8")
    prefix = "window.OPTIMATRIX_WORKBENCH = Object.freeze("
    return json.loads(source.removeprefix(prefix).removesuffix(");\n"))


def _display_value(rows: object, key: str) -> object:
    assert isinstance(rows, list)
    row = next(item for item in rows if isinstance(item, dict) and item.get("key") == key)
    return row["value"]


def _open_case(runtime, source: FakeRuntimeSource, *, window_index: int):
    before = set(runtime.cases)
    window = runtime.windows[window_index]
    runtime.tick(window.starts_at + timedelta(seconds=1))
    source.fail_snapshot = True
    try:
        runtime.tick(window.input_deadline)
    finally:
        source.fail_snapshot = False
    opened = set(runtime.cases) - before
    assert len(opened) == 1
    return runtime.cases[opened.pop()]


def _enter_case(runtime, case):
    case_ids = set(runtime.cases)
    entry_request_at = case.decision_boundary + timedelta(
        seconds=runtime.policy.lifecycle.monitoring_cadence_seconds + 1
    )
    runtime.tick(entry_request_at)
    assert set(runtime.cases) == case_ids
    entered = runtime.cases[case.identity]
    assert entered.position_id is not None
    assert entered.position_state is PositionState.MONITORING
    return entered, entry_request_at


def test_runtime_records_one_complete_unknown_session_and_workbench(policy, tmp_path) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session, fail_snapshot=True)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        runtime.tick(session.start - timedelta(minutes=5))
        runtime.tick(runtime.windows[0].starts_at + timedelta(seconds=1))
        for window in runtime.windows:
            runtime.tick(window.input_deadline)
        runtime.tick(session.end + timedelta(minutes=5))
        runtime.tick(runtime.finalization_at)

        decisions = runtime.ledger.summarize(expected_windows=runtime.windows)
        outcomes = runtime.ledger.summarize_outcomes(expected_windows=runtime.windows)
        assert decisions.denominator == decisions.recorded == 96
        assert decisions.result_counts == (("UNKNOWN", 96),)
        assert outcomes.denominator == outcomes.recorded == 96
        assert outcomes.future_path_known == outcomes.continuous == 96
        assert runtime.complete
        assert source.preflight_calls == source.history_calls == source.settlement_calls == 1
        assert source.snapshot_calls == 96 * 3
        assert source.sleeps == [1.0, 2.0] * 96

        document = _document(tmp_path / "stable/workbench/workbench-data.js")
        assert document["runtime"]["status"] == "COMPLETE_PENDING_TRADER_ACCEPTANCE"
        assert document["runtime"]["attempted_window_count"] == "96"
        assert document["population"]["decisions"]["recorded"] == "96"
        assert document["population"]["decisions"]["attempted"] == "96"
        assert document["population"]["outcomes"]["recorded"] == "96"
        assert document["cases"] == []
    finally:
        runtime.close()


def test_runtime_restart_consumes_attempted_window_and_enforces_exclusive_root(
    policy, tmp_path
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session, fail_snapshot=True)
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
    runtime.tick(session.start - timedelta(minutes=5))
    runtime.tick(session.start + timedelta(seconds=1))
    with pytest.raises(RuntimeError, match="already owned"):
        BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=source,
            event_state=EventState.NONE,
            now=session.start + timedelta(seconds=2),
            target_session=session,
            sleep=source.sleeps.append,
        )
    assert source.snapshot_calls == 3
    runtime.close()

    recovered = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start + timedelta(seconds=2),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        assert recovered.progress.restart_count == 1
        assert recovered.progress.preflight_complete
        recovered.tick(session.start + timedelta(seconds=30))
        assert source.preflight_calls == 1
        assert source.snapshot_calls == 3
    finally:
        recovered.close()


def test_runtime_recovers_unresolved_case_and_persists_monitoring_gap(policy, tmp_path) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
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
    runtime.tick(session.start - timedelta(minutes=5))
    candidate_window = runtime.windows[4]
    runtime.tick(candidate_window.starts_at + timedelta(seconds=1))
    runtime.tick(candidate_window.input_deadline)
    assert len(runtime.cases) == 1
    pending = next(iter(runtime.cases.values()))
    assert not pending.entry_final
    runtime.close()

    recovered = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=candidate_window.input_deadline + timedelta(seconds=1),
        target_session=session,
        sleep=source.sleeps.append,
    )
    assert recovered.progress.recovered_case_count == 1
    entry_at = pending.decision_boundary + timedelta(
        seconds=policy.lifecycle.monitoring_cadence_seconds + 1
    )
    recovered.tick(entry_at)
    entered = next(iter(recovered.cases.values()))
    assert entered.position_id is not None
    assert entered.position_state is PositionState.MONITORING

    source.fail_snapshot = True
    gap_at = entry_at + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds + 1)
    recovered.tick(gap_at)
    gapped = next(iter(recovered.cases.values()))
    assert gapped.position_id == entered.position_id
    assert gapped.gap_observed
    assert recovered.progress.status == "MARKET_GAP"
    recovered.close()

    restarted = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=gap_at + timedelta(seconds=1),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        restored = next(iter(restarted.cases.values()))
        assert restored.position_id == entered.position_id
        assert restored.gap_observed
        assert restarted.progress.restart_count == 2
    finally:
        restarted.close()


def test_runtime_refuses_foreign_stable_root(policy, tmp_path) -> None:
    root = tmp_path / "stable"
    root.mkdir()
    (root / "foreign.db").write_text("not optimatrix", encoding="utf-8")
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    with pytest.raises(ValueError, match="foreign members"):
        BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=source,
            event_state=EventState.NONE,
            now=session.start - timedelta(minutes=10),
            target_session=session,
            sleep=source.sleeps.append,
        )


def test_runtime_rejects_foreign_session_decision_record(policy, tmp_path) -> None:
    session = _session(policy)
    root = tmp_path / "stable"
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    runtime.close()

    foreign_session = current_deribit_session(session.end, phase_policy=policy.session)
    foreign_source = FakeRuntimeSource(policy, foreign_session, fail_snapshot=True)
    foreign_runtime = BtcPublicShadowRuntime(
        root=tmp_path / "foreign",
        policy=policy,
        source=foreign_source,
        event_state=EventState.NONE,
        now=foreign_session.start - timedelta(minutes=10),
        target_session=foreign_session,
        sleep=foreign_source.sleeps.append,
    )
    try:
        foreign_runtime.tick(foreign_runtime.windows[0].starts_at + timedelta(seconds=1))
        foreign_runtime.tick(foreign_runtime.windows[0].input_deadline)
        foreign_payload = foreign_runtime.ledger.path.read_bytes()
        assert foreign_runtime.ledger.read()
    finally:
        foreign_runtime.close()
    ledger_path = root / "decision-records.jsonl"
    ledger_path.write_bytes(foreign_payload)

    with pytest.raises(ValueError, match="foreign Session or Policy record"):
        BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=source,
            event_state=EventState.NONE,
            now=session.start - timedelta(minutes=5),
            target_session=session,
            sleep=source.sleeps.append,
        )
    assert ledger_path.read_bytes() == foreign_payload


def test_runtime_rejects_foreign_session_case_without_rewriting_it(policy, tmp_path) -> None:
    session = _session(policy)
    root = tmp_path / "stable"
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    runtime.close()

    foreign_session = current_deribit_session(session.end, phase_policy=policy.session)
    foreign_source = FakeRuntimeSource(policy, foreign_session)
    foreign_runtime = BtcPublicShadowRuntime(
        root=tmp_path / "foreign-case",
        policy=policy,
        source=foreign_source,
        event_state=EventState.NONE,
        now=foreign_session.start - timedelta(minutes=10),
        target_session=foreign_session,
        sleep=foreign_source.sleeps.append,
    )
    try:
        foreign_case = _open_case(foreign_runtime, foreign_source, window_index=4)
        assert foreign_case.risk_allocation["market_session_id"] == foreign_session.session_id
        foreign_path = foreign_runtime.journal.path_for(foreign_case.identity)
        foreign_payload = foreign_path.read_bytes()
    finally:
        foreign_runtime.close()

    journal = CaseJournal(root)
    injected_path = journal.path_for(foreign_case.identity)
    injected_path.parent.mkdir(parents=True)
    injected_path.write_bytes(foreign_payload)

    with pytest.raises(ValueError, match="foreign or duplicate runtime Case"):
        BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=source,
            event_state=EventState.NONE,
            now=session.start - timedelta(minutes=5),
            target_session=session,
            sleep=source.sleeps.append,
        )
    assert injected_path.read_bytes() == foreign_payload


def test_runtime_rejects_wrong_session_settlement_without_rewriting_it(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    root = tmp_path / "stable"
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    runtime.close()

    wrong_expiry = session.end + timedelta(days=1)
    wrong = ExpirySettlementFact(
        product_id=BTC.product_id,
        expiry=wrong_expiry,
        delivery_price_usd=Decimal("100000"),
        known_at=wrong_expiry + timedelta(minutes=5),
        evidence_kind=SettlementEvidenceKind.OFFICIAL_EXCHANGE,
        source_id=DERIBIT_DELIVERY_PRICE_SOURCE_ID,
        method_id=DERIBIT_DELIVERY_PRICE_METHOD_ID,
    )
    settlement_path = root / "settlement.json"
    settlement_path.write_text(json.dumps(wrong.as_object()) + "\n", encoding="utf-8")
    before = settlement_path.read_bytes()

    with pytest.raises(ValueError, match="does not match the runtime Session and source"):
        BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=source,
            event_state=EventState.NONE,
            now=session.end + timedelta(minutes=5),
            target_session=session,
            sleep=source.sleeps.append,
        )
    assert settlement_path.read_bytes() == before


def test_runtime_without_target_session_resumes_manifest_session_mid_session(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    root = tmp_path / "stable"
    first = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start + timedelta(hours=2),
        sleep=source.sleeps.append,
    )
    try:
        assert first.session == session
        manifest_session_id = first.manifest.target_session_id
    finally:
        first.close()

    restarted = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start + timedelta(hours=6),
        sleep=source.sleeps.append,
    )
    try:
        assert restarted.manifest.target_session_id == manifest_session_id
        assert restarted.session == session
        assert {window.market_session_id for window in restarted.windows} == {session.session_id}
    finally:
        restarted.close()


def test_runtime_without_target_session_starts_current_partial_session_immediately(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    now = session.start + timedelta(hours=6, minutes=7)
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=now,
        sleep=source.sleeps.append,
    )
    try:
        current = current_deribit_session(now, phase_policy=policy.session)
        assert runtime.session.session_id == current.session_id
        assert runtime.session.start == current.start
        assert runtime.session.end == current.end
        serialized_starting_snapshot = json.dumps(runtime.latest_snapshot, sort_keys=True)
        assert "AWAITING_FIRST_CURRENT_MARKET_CUT" in serialized_starting_snapshot
        assert "WAITING_FOR_AUTHORIZED_COMPLETE_SESSION" not in serialized_starting_snapshot
        assert "COMPLETE_SESSION_NOT_STARTED" not in serialized_starting_snapshot
        runtime.tick(now)
        assert source.preflight_calls == 1
        assert source.snapshot_calls == 1
        assert runtime.latest_snapshot["session_id"] == session.session_id

        recorded = runtime.ledger.read()
        current_window = next(
            window for window in runtime.windows if window.starts_at <= now < window.ends_at
        )
        assert recorded == ()
        assert runtime.progress.status == "RUNNING"
        assert runtime.cases == {}

        runtime.tick(current_window.input_deadline)
        recorded = runtime.ledger.read()
        assert len(recorded) == 1
        assert recorded[-1].window == current_window
        assert source.snapshot_calls == 2
    finally:
        runtime.close()


def test_late_window_finalization_does_not_replay_an_old_candidate_cut(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start + timedelta(hours=1),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        window = runtime.windows[4]
        runtime.tick(window.starts_at + timedelta(seconds=1))
        assert window.identity in runtime.pending_observations

        runtime.tick(
            window.input_deadline
            + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds + 1)
        )

        record = next(
            item for item in runtime.ledger.read() if item.window.identity == window.identity
        )
        assert record.result is DecisionResult.UNKNOWN
        assert record.observation_id is None
        assert runtime.cases == {}
        assert "DECISION_FINALIZATION_CADENCE_MISSED" in (
            runtime.root_owner.root / "runtime-events.jsonl"
        ).read_text(encoding="utf-8")
    finally:
        runtime.close()


def test_second_owner_does_not_delete_temporary_file_while_lock_is_held(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    root = tmp_path / "stable"
    owner = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    temporary = root / ".latest-snapshot.json.optimatrix-tmp"
    temporary.write_bytes(b"first-owner-incomplete-write")
    try:
        with pytest.raises(RuntimeError, match="already owned"):
            BtcPublicShadowRuntime(
                root=root,
                policy=policy,
                source=source,
                event_state=EventState.NONE,
                now=session.start - timedelta(minutes=9),
                target_session=session,
                sleep=source.sleeps.append,
            )
        assert temporary.read_bytes() == b"first-owner-incomplete-write"
    finally:
        owner.close()


@pytest.mark.parametrize("crash_tail", (None, b"", b'{"case":'))
def test_restart_opens_case_when_candidate_record_survived_case_append_crash(
    policy,
    tmp_path,
    monkeypatch,
    crash_tail,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
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
    window = runtime.windows[4]
    runtime.tick(window.starts_at + timedelta(seconds=1))

    def crash_before_case_append(**_kwargs) -> None:
        raise RuntimeError("injected crash after Candidate ledger append")

    monkeypatch.setattr(runtime.engine, "open_case", crash_before_case_append)
    try:
        with pytest.raises(RuntimeError, match="Candidate ledger append"):
            runtime.tick(window.input_deadline)
        candidate = next(record for record in runtime.ledger.read() if record.window == window)
        assert candidate.result.value == "CANDIDATE"
        expected_case = open_trade_case(candidate, policy)
        if crash_tail is not None:
            path = runtime.journal.path_for(expected_case.identity)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(crash_tail)
            with pytest.raises(ValueError, match="no accepted snapshot"):
                runtime.journal.recover_all()
        else:
            assert runtime.journal.recover_all() == ()
    finally:
        runtime.close()

    recovered = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=window.input_deadline + timedelta(seconds=1),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        assert len(recovered.cases) == 1
        case = next(iter(recovered.cases.values()))
        assert case.identity == expected_case.identity
        assert case.decision_record_id == candidate.identity
        assert recovered.journal.recover_all() == (case,)
        assert recovered.journal.path_for(case.identity).read_bytes().endswith(b"\n")
    finally:
        recovered.close()


def test_entry_uses_snapshot_response_known_at_boundary(policy, tmp_path) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session, snapshot_delay=timedelta(seconds=1))
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        case = _open_case(runtime, source, window_index=4)
        entered, request_at = _enter_case(runtime, case)
        assert entered.entry_known_at == request_at + timedelta(seconds=1)
        assert entered.entry_observed_at == request_at + timedelta(seconds=1)
    finally:
        runtime.close()


def test_healthy_cut_after_three_missed_cadences_preserves_gap_truth(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        case = _open_case(runtime, source, window_index=4)
        entered, _request_at = _enter_case(runtime, case)
        assert entered.last_observed_at is not None
        missed_cut = entered.last_observed_at + timedelta(
            seconds=policy.lifecycle.monitoring_cadence_seconds * 3 + 1
        )
        runtime.tick(missed_cut)

        monitored = runtime.cases[case.identity]
        assert monitored.last_observed_at == missed_cut
        assert monitored.gap_observed
    finally:
        runtime.close()


def test_snapshot_requested_before_expiry_and_received_after_expiry_does_not_exit(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        case = _open_case(runtime, source, window_index=80)
        entered, _request_at = _enter_case(runtime, case)
        assert entered.last_observed_at is not None
        source.event_state = EventState.LIVE_EVENT
        trigger_at = entered.last_observed_at + timedelta(
            seconds=policy.lifecycle.monitoring_cadence_seconds + 1
        )
        runtime.tick(trigger_at)
        armed = runtime.cases[case.identity]
        assert armed.exit_intent is not None

        source.event_state = EventState.NONE
        source.snapshot_delay = timedelta(seconds=2)
        runtime.tick(session.end - timedelta(seconds=1))

        preserved = runtime.cases[case.identity]
        assert preserved.exit_intent == armed.exit_intent
        assert preserved.position_id == armed.position_id
        assert preserved.outcome is None
    finally:
        runtime.close()


def test_restart_finishes_all_cases_after_settlement_file_survives_partial_crash(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
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
    first = _open_case(runtime, source, window_index=4)
    _enter_case(runtime, first)
    second = _open_case(runtime, source, window_index=8)
    _enter_case(runtime, second)
    assert sum(case.position_id is not None for case in runtime.cases.values()) == 2

    original_settle = runtime.engine.settle_position
    settlement_calls = 0

    def crash_on_second_case(**kwargs):
        nonlocal settlement_calls
        settlement_calls += 1
        if settlement_calls == 2:
            raise RuntimeError("injected crash during Case settlement")
        return original_settle(**kwargs)

    monkeypatch.setattr(runtime.engine, "settle_position", crash_on_second_case)
    settlement_at = session.end + timedelta(minutes=5)
    try:
        with pytest.raises(RuntimeError, match="Case settlement"):
            runtime.tick(settlement_at)
        assert (root / "settlements.jsonl").is_file()
        accepted = runtime.journal.recover_all()
        terminal_before = next(case for case in accepted if case.outcome is not None)
        accepted_terminal_path = runtime.journal.path_for(terminal_before.identity)
        accepted_terminal_bytes = accepted_terminal_path.read_bytes()
        assert sum(case.outcome is not None for case in accepted) == 1
    finally:
        runtime.close()

    restarted = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=settlement_at + timedelta(seconds=1),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        assert len(restarted.cases) == 2
        assert all(case.outcome is not None for case in restarted.cases.values())
        assert restarted.cases[terminal_before.identity] == terminal_before
        assert accepted_terminal_path.read_bytes() == accepted_terminal_bytes
        assert source.settlement_calls == 1

        recovered_prefixes = {
            case_id: restarted.journal.path_for(case_id).read_bytes() for case_id in restarted.cases
        }
        restarted.tick(settlement_at + timedelta(seconds=1))
        assert all(
            restarted.journal.path_for(case_id).read_bytes() == prefix
            for case_id, prefix in recovered_prefixes.items()
        )
    finally:
        restarted.close()


def test_restart_completes_window_outcomes_after_nth_append_crash(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session, fail_snapshot=True)
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
    for window in runtime.windows:
        runtime.tick(window.starts_at + timedelta(seconds=1))
        runtime.tick(window.input_deadline)
    runtime.tick(session.end + timedelta(minutes=5))
    assert len(runtime.ledger.read()) == 96

    original_append = runtime.ledger.append_outcome
    append_calls = 0

    def crash_on_seventh_outcome(outcome):
        nonlocal append_calls
        append_calls += 1
        if append_calls == 7:
            raise RuntimeError("injected crash during WindowOutcome append")
        return original_append(outcome)

    monkeypatch.setattr(runtime.ledger, "append_outcome", crash_on_seventh_outcome)
    try:
        with pytest.raises(RuntimeError, match="WindowOutcome append"):
            runtime.tick(runtime.finalization_at)
        accepted_prefix = runtime.ledger.read_outcomes()
        assert len(accepted_prefix) == 6
        assert runtime.history_capture is not None
        capture_known_at = runtime.history_capture.known_at
    finally:
        runtime.close()

    restarted = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=runtime.finalization_at + timedelta(seconds=1),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        restarted.tick(runtime.finalization_at + timedelta(seconds=1))
        recorded_outcomes = restarted.ledger.read_outcomes()
        outcomes = restarted.ledger.summarize_outcomes(expected_windows=restarted.windows)
        assert outcomes.denominator == outcomes.recorded == 96
        assert recorded_outcomes[:6] == accepted_prefix
        assert {outcome.known_at for outcome in recorded_outcomes} == {capture_known_at}
        assert source.history_calls == 1
    finally:
        restarted.close()


def test_successful_position_settles_and_populates_encountered_window_outcomes(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
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
    try:
        opened = _open_case(runtime, source, window_index=4)
        entered, _entry_at = _enter_case(runtime, opened)
        position_id = entered.position_id
        assert position_id is not None
        assert entered.outcome is None

        runtime.tick(runtime.windows[-1].starts_at + timedelta(seconds=1))
        runtime.tick(runtime.windows[-1].input_deadline)
        decisions = runtime.ledger.summarize(expected_windows=runtime.windows)
        assert decisions.denominator == 96
        assert decisions.recorded == 3
        assert decisions.missing == 93
        assert decisions.result_counts == (
            ("ABSTAIN", 1),
            ("CANDIDATE", 1),
            ("UNKNOWN", 1),
        )
        unresolved = runtime.cases[opened.identity]
        assert unresolved.position_id == position_id
        assert unresolved.outcome is None
        assert unresolved.gap_observed

        settlement_at = session.end + timedelta(minutes=5)
        runtime.tick(settlement_at)
        terminal = runtime.cases[opened.identity]
        assert terminal.position_id == position_id
        assert terminal.position_state is PositionState.TERMINAL
        assert terminal.outcome is not None
        assert terminal.outcome.terminal_method is TerminalMethod.CONTRACT_SETTLEMENT
        assert terminal.outcome.terminal_evidence_id == runtime.settlement_fact.identity
        assert terminal.outcome.native_result_btc is not None
        assert terminal.outcome.eligibility.terminal_economics_evaluable.value is True

        runtime.tick(runtime.finalization_at)
        outcomes = runtime.ledger.read_outcomes()
        outcome_summary = runtime.ledger.summarize_outcomes(expected_windows=runtime.windows)
        assert outcome_summary.denominator == 96
        assert outcome_summary.recorded == 3
        assert outcome_summary.missing == 93
        assert outcome_summary.future_path_known == outcome_summary.continuous == 3
        assert outcome_summary.decision_evaluable == 2
        assert outcome_summary.strategy_population_eligible == 3
        assert all(outcome.expiry_settlement == runtime.settlement_fact for outcome in outcomes)
        assert all(outcome.future_path_known for outcome in outcomes)
        assert runtime.journal.recover_all() == (terminal,)
        assert source.preflight_calls == source.history_calls == source.settlement_calls == 1
        assert not runtime.complete

        document = _document(root / "workbench/workbench-data.js")
        assert document["runtime"]["status"] == "RUNNING"
        assert document["population"]["decisions"]["recorded"] == "3"
        assert document["population"]["outcomes"]["recorded"] == "3"
        rendered_case = next(
            item for item in document["cases"] if item["trade_case_id"] == terminal.identity
        )
        assert rendered_case["position_state"] == "TERMINAL"
    finally:
        runtime.close()


def test_official_settlement_retries_on_a_later_cadence_until_position_is_terminal(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session, settlement_failures=3)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        opened = _open_case(runtime, source, window_index=4)
        entered, _entry_at = _enter_case(runtime, opened)
        assert entered.position_id is not None

        first_boundary = session.end + timedelta(minutes=5)
        runtime.tick(first_boundary)
        unresolved = runtime.cases[opened.identity]
        assert unresolved.outcome is None
        assert runtime.settlement_fact is None
        assert source.settlement_calls == 3
        assert runtime.progress.status == "SETTLEMENT_UNVERIFIED"
        assert runtime.progress.last_error is not None

        runtime.tick(first_boundary + timedelta(seconds=30))
        assert source.settlement_calls == 3

        runtime.tick(
            first_boundary + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds)
        )
        terminal = runtime.cases[opened.identity]
        assert source.settlement_calls == 4
        assert runtime.settlement_fact is not None
        assert terminal.outcome is not None
        assert terminal.outcome.terminal_method is TerminalMethod.CONTRACT_SETTLEMENT
        assert runtime.progress.status == "RUNNING"
        assert runtime.progress.last_error is None
    finally:
        runtime.close()


def test_restart_after_expiry_preserves_pre_expiry_monitoring_gap_in_outcome(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    root = tmp_path / "stable"
    first = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    opened = _open_case(first, source, window_index=4)
    entered, _entry_at = _enter_case(first, opened)
    assert entered.position_id is not None
    assert not entered.gap_observed
    first.close()

    settlement_at = session.end + timedelta(minutes=5)
    recovered = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=settlement_at,
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        assert recovered.cases[opened.identity].gap_observed
        recovered.tick(settlement_at)
        terminal = recovered.cases[opened.identity]
        assert terminal.outcome is not None
        assert terminal.outcome.data_gap_observed
    finally:
        recovered.close()


@pytest.mark.parametrize(
    ("member", "is_directory"),
    (
        ("decision-records.jsonl", False),
        ("settlement.json", False),
        ("cases", True),
        ("workbench", True),
    ),
)
def test_runtime_rejects_symlinked_allowed_members_without_touching_target(
    policy,
    tmp_path,
    member,
    is_directory,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    root = tmp_path / "stable"
    root.mkdir()
    external = tmp_path / f"external-{member.replace('.', '-')}"
    if is_directory:
        external.mkdir()
        sentinel = external / "sentinel"
    else:
        sentinel = external
    sentinel.write_bytes(b"external-must-not-change")
    (root / member).symlink_to(external, target_is_directory=is_directory)

    with pytest.raises(ValueError, match="foreign type"):
        BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=source,
            event_state=EventState.NONE,
            now=session.start - timedelta(minutes=10),
            target_session=session,
            sleep=source.sleeps.append,
        )
    assert sentinel.read_bytes() == b"external-must-not-change"


def test_market_failure_workbench_shows_current_window_and_gap(policy, tmp_path) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session, event_state=EventState.LIVE_EVENT)
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
    try:
        prior_window = runtime.windows[3]
        runtime.tick(prior_window.starts_at + timedelta(seconds=1))
        prior_document = _document(root / "workbench/workbench-data.js")
        assert _display_value(prior_document["window"], "decision_window_id") == (
            prior_window.identity
        )

        source.fail_snapshot = True
        window = runtime.windows[4]
        runtime.tick(window.starts_at + timedelta(seconds=1))
        document = _document(root / "workbench/workbench-data.js")

        assert document["runtime"]["status"] == "MARKET_GAP"
        assert _display_value(document["runtime"]["facts"], "current_window_id") == (
            window.identity
        )
        assert _display_value(document["window"], "decision_window_id") == window.identity
        assert "GAP" in str(_display_value(document["window"], "ledger_state"))
        assert any("GAP" in blocker["code"] for blocker in document["projection"]["blockers"])
    finally:
        runtime.close()


def test_complete_market_failure_at_latest_exit_still_freezes_time_responsibility(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        opened = _open_case(runtime, source, window_index=4)
        entered, _entry_at = _enter_case(runtime, opened)
        source.fail_snapshot = True
        latest_exit_at = session.end - timedelta(
            minutes=policy.lifecycle.latest_exit_minutes_to_expiry
        )

        runtime.tick(latest_exit_at)

        updated = runtime.cases[entered.identity]
        assert updated.gap_observed
        assert updated.position_state is PositionState.EXIT_INTENT_FROZEN
        assert updated.exit_intent is not None
        assert updated.exit_intent.reason == "LATEST_EXIT"
        assert updated.exit_intent.source == "DERIBIT_TIME_BOUNDARY_WITHOUT_MARKET_CUT"
    finally:
        runtime.close()


def test_wake_after_expiry_freezes_latest_exit_before_official_settlement(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        opened = _open_case(runtime, source, window_index=4)
        entered, _entry_at = _enter_case(runtime, opened)
        assert entered.exit_intent is None

        runtime.tick(session.end + timedelta(minutes=5))

        terminal = runtime.cases[entered.identity]
        assert terminal.gap_observed
        assert terminal.exit_intent is not None
        assert terminal.exit_intent.reason == "LATEST_EXIT"
        assert terminal.exit_intent.observed_at == session.end - timedelta(
            minutes=policy.lifecycle.latest_exit_minutes_to_expiry
        )
        assert terminal.exit_intent.known_at == session.end + timedelta(minutes=5)
        assert terminal.outcome is not None
        assert terminal.outcome.terminal_method is TerminalMethod.CONTRACT_SETTLEMENT
    finally:
        runtime.close()


def test_fixed_runtime_preflight_retries_without_consulting_host_wall(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    session = _session(policy)
    boundary = session.start - timedelta(minutes=5)

    class ForbiddenHostWall(datetime):
        @classmethod
        def now(cls, tz=None):
            raise AssertionError("runtime preflight must not consult host wall time")

    attempts: list[int] = []

    def fake_preflight(_client):
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise DeribitSourceError("first bounded preflight timeout")
        reading = DeribitClockReading(
            earliest_at=boundary + timedelta(seconds=7),
            estimate_at=boundary + timedelta(seconds=7),
            latest_at=boundary + timedelta(seconds=7),
            monotonic_ns=1,
        )
        return PublicClockPreflight(
            server_time_ms=int(reading.estimate_at.timestamp() * 1000),
            request_round_trip_ms=1,
            known_at=reading.latest_at,
            clock_reading=reading,
        )

    monkeypatch.setattr("optimatrix.runtime.datetime", ForbiddenHostWall)
    monkeypatch.setattr("optimatrix.runtime.preflight_public_clock", fake_preflight)
    monkeypatch.setattr(
        "optimatrix.runtime.AUTHORIZED_RUNTIME_POLICY_IDENTITY",
        policy.identity,
    )
    source = DeribitPublicRuntimeSource(policy=policy, event_state=EventState.NONE)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=lambda _seconds: None,
    )
    try:
        runtime.tick(boundary)
        assert attempts == [1, 2]
        assert runtime.progress.preflight_attempt_count == 2
        assert runtime.progress.preflight_complete
    finally:
        runtime.close()


def test_snapshot_duration_crossing_two_cadences_preserves_gap(policy, tmp_path) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        opened = _open_case(runtime, source, window_index=4)
        entered, _entry_at = _enter_case(runtime, opened)
        assert entered.last_observed_at is not None
        source.snapshot_delay = timedelta(seconds=121)
        request_at = entered.last_observed_at + timedelta(
            seconds=policy.lifecycle.monitoring_cadence_seconds
        )

        runtime.tick(request_at)

        updated = runtime.cases[opened.identity]
        assert updated.last_observed_at == request_at + timedelta(seconds=121)
        assert updated.gap_observed
    finally:
        runtime.close()


def test_repeated_market_source_boundary_preserves_position_as_gap(policy, tmp_path) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        opened = _open_case(runtime, source, window_index=4)
        entered, _entry_at = _enter_case(runtime, opened)
        assert entered.last_observed_at is not None
        source.frozen_source_at = entered.last_observed_at

        runtime.tick(
            entered.last_observed_at
            + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds)
        )

        preserved = runtime.cases[opened.identity]
        assert preserved.position_id == entered.position_id
        assert preserved.last_observed_at == entered.last_observed_at
        assert preserved.gap_observed
        assert preserved.outcome is None
        assert "LIFECYCLE_MARKET_BOUNDARY_NOT_ADVANCING" in (
            runtime.root_owner.root / "runtime-events.jsonl"
        ).read_text(encoding="utf-8")
    finally:
        runtime.close()


def test_restart_projects_window_attempt_interruption_as_current_gap(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
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
    runtime.tick(session.start - timedelta(minutes=5))
    window = runtime.windows[4]
    monkeypatch.setattr(
        runtime,
        "_capture",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("crash after Window mark")),
    )
    try:
        with pytest.raises(RuntimeError, match="Window mark"):
            runtime.tick(window.starts_at + timedelta(seconds=1))
    finally:
        runtime.close()

    restarted = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=window.starts_at + timedelta(seconds=2),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        document = _document(root / "workbench/workbench-data.js")
        assert restarted.progress.status == "RECOVERY_GAP"
        assert _display_value(document["window"], "decision_window_id") == window.identity
        assert "GAP" in str(_display_value(document["window"], "ledger_state"))
        assert "RESTART_INTERRUPTED_WINDOW_ATTEMPT" in str(document["projection"])
    finally:
        restarted.close()


def test_restart_marks_interrupted_case_cut_as_gap(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
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
    opened = _open_case(runtime, source, window_index=4)
    entered, _entry_at = _enter_case(runtime, opened)
    assert entered.last_observed_at is not None
    original_mark = runtime._mark_cases_attempted

    def crash_after_case_mark(cases, now):
        original_mark(cases, now)
        raise RuntimeError("crash after Case mark")

    monkeypatch.setattr(runtime, "_mark_cases_attempted", crash_after_case_mark)
    attempt_at = entered.last_observed_at + timedelta(
        seconds=policy.lifecycle.monitoring_cadence_seconds
    )
    try:
        with pytest.raises(RuntimeError, match="Case mark"):
            runtime.tick(attempt_at)
    finally:
        runtime.close()

    restarted = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=attempt_at + timedelta(seconds=1),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        recovered = restarted.cases[opened.identity]
        assert recovered.position_id == entered.position_id
        assert recovered.gap_observed
        assert restarted.progress.status == "RECOVERY_GAP"
    finally:
        restarted.close()


def test_pending_entry_recovered_after_expiry_terminalizes_partial_session(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
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
    pending = _open_case(runtime, source, window_index=4)
    assert not pending.entry_final
    runtime.close()

    recovered = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.end + timedelta(minutes=5),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        terminal = recovered.cases[pending.identity]
        assert terminal.entry_final
        assert terminal.position_id is None
        assert terminal.outcome is not None
        assert terminal.outcome.terminal_method is TerminalMethod.NO_POSITION

        recovered.tick(session.end + timedelta(minutes=5))
        recovered.tick(recovered.finalization_at)
        assert not recovered.complete
        assert len(recovered.ledger.read()) == 2
        assert len(recovered.ledger.read_outcomes()) == 2
    finally:
        recovered.close()


def test_restart_count_reports_restarts_not_process_starts(policy, tmp_path) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    root = tmp_path / "stable"
    first = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=10),
        target_session=session,
        sleep=source.sleeps.append,
    )
    assert first.progress.restart_count == 0
    first.close()

    second = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start - timedelta(minutes=9),
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        assert second.progress.restart_count == 1
        document = _document(root / "workbench/workbench-data.js")
        assert _display_value(document["runtime"]["facts"], "restart_count") == "1"
    finally:
        second.close()


def test_runtime_rolls_at_session_boundary_and_finishes_prior_last_window(
    policy,
    tmp_path,
) -> None:
    prior_session = _session(policy)
    next_session = current_deribit_session(
        prior_session.end,
        phase_policy=policy.session,
    )
    source = FakeRuntimeSource(policy, prior_session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=prior_session.end - timedelta(minutes=1),
        sleep=source.sleeps.append,
    )
    try:
        prior_last_window = runtime.windows[-1]
        runtime.tick(prior_session.end - timedelta(seconds=1))
        assert source.snapshot_windows[-1] == prior_last_window
        assert runtime.ledger.read() == ()

        runtime.tick(prior_session.end)
        next_first_window = runtime.windows[0]
        assert runtime.session.session_id == next_session.session_id
        assert next_first_window.market_session_id == next_session.session_id
        assert source.snapshot_windows[-1] == next_first_window
        assert all(
            record.window.identity != prior_last_window.identity for record in runtime.ledger.read()
        )

        runtime.tick(prior_last_window.input_deadline)
        prior_record = next(
            record
            for record in runtime.ledger.read()
            if record.window.identity == prior_last_window.identity
        )
        assert prior_record.window == prior_last_window
        assert prior_record.known_at == prior_last_window.input_deadline
        assert runtime.session.session_id == next_session.session_id
    finally:
        runtime.close()


def test_prior_session_position_settles_while_next_session_is_active(
    policy,
    tmp_path,
) -> None:
    prior_session = _session(policy)
    next_session = current_deribit_session(
        prior_session.end,
        phase_policy=policy.session,
    )
    source = FakeRuntimeSource(policy, prior_session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=prior_session.start + timedelta(seconds=1),
        sleep=source.sleeps.append,
    )
    try:
        opened = _open_case(runtime, source, window_index=80)
        entered, _entry_at = _enter_case(runtime, opened)
        assert entered.position_id is not None
        assert entered.outcome is None

        runtime.tick(prior_session.end)
        assert runtime.session.session_id == next_session.session_id
        assert runtime.cases[opened.identity].outcome is None

        runtime.tick(prior_session.end + timedelta(minutes=5))
        terminal = runtime.cases[opened.identity]
        assert runtime.session.session_id == next_session.session_id
        assert terminal.position_state is PositionState.TERMINAL
        assert terminal.outcome is not None
        assert terminal.outcome.terminal_method is TerminalMethod.CONTRACT_SETTLEMENT
        assert source.settlement_expiries == [prior_session.end]
    finally:
        runtime.close()


def test_run_forever_keeps_ticking_after_session_population_is_complete(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start + timedelta(hours=1),
        target_session=session,
        sleep=source.sleeps.append,
    )

    class DummyWorkbenchServer:
        def __init__(self, _directory, _port) -> None:
            self.started = False
            self.stopped = False

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

    tick_count = 0
    sleep_calls: list[float] = []

    def interrupt_after_two_ticks(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) == 2:
            raise KeyboardInterrupt

    def record_tick() -> None:
        nonlocal tick_count
        tick_count += 1

    monkeypatch.setattr("optimatrix.runtime._WorkbenchServer", DummyWorkbenchServer)
    monkeypatch.setattr(runtime, "tick", record_tick)
    monkeypatch.setattr(runtime, "sleep", interrupt_after_two_ticks)
    monkeypatch.setattr(
        BtcPublicShadowRuntime,
        "complete",
        property(lambda _runtime: True),
        raising=False,
    )

    assert runtime.run_forever(port=18_765) == 0
    assert tick_count == 2


def test_stable_root_restart_uses_active_session_and_keeps_mixed_session_ledger(
    policy,
    tmp_path,
) -> None:
    prior_session = _session(policy)
    next_session = current_deribit_session(
        prior_session.end,
        phase_policy=policy.session,
    )
    source = FakeRuntimeSource(policy, prior_session)
    root = tmp_path / "stable"
    runtime = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=prior_session.end - timedelta(minutes=1),
        sleep=source.sleeps.append,
    )
    try:
        prior_last_window = runtime.windows[-1]
        runtime.tick(prior_session.end - timedelta(seconds=1))
        runtime.tick(prior_session.end)
        next_first_window = runtime.windows[0]
        runtime.tick(prior_last_window.input_deadline)
        runtime.tick(next_first_window.input_deadline)
        first_enrollment_manifest = runtime.manifest.as_object()
        assert {record.window.market_session_id for record in runtime.ledger.read()} == {
            prior_session.session_id,
            next_session.session_id,
        }
    finally:
        runtime.close()

    restarted = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=next_session.start + timedelta(hours=2),
        sleep=source.sleeps.append,
    )
    try:
        assert restarted.session.session_id == next_session.session_id
        assert restarted.manifest.as_object() == first_enrollment_manifest
        assert {record.window.market_session_id for record in restarted.ledger.read()} == {
            prior_session.session_id,
            next_session.session_id,
        }
    finally:
        restarted.close()


@pytest.mark.parametrize("foreign_kind", ("WINDOW", "POLICY"))
def test_runtime_rejects_forged_window_or_policy_in_cross_session_root(
    policy,
    tmp_path,
    foreign_kind,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    root = tmp_path / "stable"
    runtime = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start + timedelta(hours=1),
        sleep=source.sleeps.append,
    )
    base_window = runtime.windows[8]
    runtime.close()

    forged_window = (
        replace(
            base_window,
            starts_at=base_window.starts_at + timedelta(minutes=1),
            ends_at=base_window.ends_at + timedelta(minutes=1),
            input_deadline=base_window.input_deadline + timedelta(minutes=1),
        )
        if foreign_kind == "WINDOW"
        else base_window
    )
    forged_policy_id = (
        canonical_identity("ForgedDecisionPolicy", policy.identity)
        if foreign_kind == "POLICY"
        else policy.identity
    )
    forged = DecisionRecord(
        window=forged_window,
        decision_policy_id=forged_policy_id,
        known_at=forged_window.input_deadline,
        observation_id=None,
        result=DecisionResult.UNKNOWN,
        blockers=("NO_OBSERVATION",),
    )
    runtime.ledger.append(forged)

    with pytest.raises(ValueError, match=r"Window|Policy|schedule"):
        BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=source,
            event_state=EventState.NONE,
            now=session.start + timedelta(hours=2),
            sleep=source.sleeps.append,
        )


class ClockedRuntimeSource(FakeRuntimeSource):
    def __init__(
        self,
        policy,
        session: DeribitSession,
        *,
        reading: DeribitClockReading,
    ) -> None:
        super().__init__(policy, session)
        self.reading = reading

    def preflight(self) -> PublicClockPreflight:
        self.preflight_calls += 1
        return PublicClockPreflight(
            server_time_ms=int(self.reading.estimate_at.timestamp() * 1000),
            request_round_trip_ms=1,
            known_at=self.reading.latest_at,
            clock_reading=self.reading,
        )

    def clock_reading(self) -> DeribitClockReading:
        return self.reading

    def set_clock(
        self,
        estimate_at: datetime,
        *,
        earliest_at: datetime | None = None,
        latest_at: datetime | None = None,
    ) -> None:
        self.reading = DeribitClockReading(
            earliest_at=earliest_at or estimate_at,
            estimate_at=estimate_at,
            latest_at=latest_at or estimate_at,
            monotonic_ns=self.reading.monotonic_ns + 1_000_000_000,
        )


def test_runtime_reanchors_deribit_clock_once_and_continues(policy, tmp_path) -> None:
    session = _session(policy)

    class RecoveringClockSource(ClockedRuntimeSource):
        poisoned = False

        def preflight(self) -> PublicClockPreflight:
            if self.poisoned:
                self.poisoned = False
                self.set_clock(self.reading.earliest_at + timedelta(seconds=1))
            return super().preflight()

        def clock_reading(self) -> DeribitClockReading:
            if self.poisoned:
                raise DeribitSourceError("new Deribit clock anchor is inconsistent")
            return super().clock_reading()

    boundary = session.start + timedelta(hours=1)
    reading = DeribitClockReading(boundary, boundary, boundary, 1_000_000_000)
    source = RecoveringClockSource(policy, session, reading=reading)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        sleep=source.sleeps.append,
    )
    try:
        source.poisoned = True
        runtime.tick()
        assert source.preflight_calls == 2
        assert runtime.progress.status == "RUNNING"
        assert "DERIBIT_CLOCK_REANCHORED" in (
            runtime.root_owner.root / "runtime-events.jsonl"
        ).read_text(encoding="utf-8")
    finally:
        runtime.close()


def test_runtime_stops_when_bounded_deribit_clock_reanchor_fails(policy, tmp_path) -> None:
    session = _session(policy)
    boundary = session.start + timedelta(hours=1)
    reading = DeribitClockReading(boundary, boundary, boundary, 1_000_000_000)
    source = ClockedRuntimeSource(policy, session, reading=reading)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        sleep=source.sleeps.append,
    )

    def failed_clock() -> DeribitClockReading:
        raise DeribitSourceError("Deribit clock remains inconsistent")

    def failed_preflight() -> PublicClockPreflight:
        source.preflight_calls += 1
        raise DeribitSourceError("public/get_time unavailable")

    source.clock_reading = failed_clock  # type: ignore[method-assign]
    source.preflight = failed_preflight  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="clock re-anchor failed"):
            runtime.tick()
        assert source.preflight_calls == 4
        assert source.sleeps[-2:] == [1.0, 2.0]
        assert runtime.progress.status == "CLOCK_UNVERIFIED"
    finally:
        runtime.close()


def test_authorized_root_rejects_nonproduction_source_before_creation(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    authorized_root = tmp_path / "authorized"
    monkeypatch.setattr("optimatrix.runtime.AUTHORIZED_RUNTIME_ROOT", authorized_root)

    with pytest.raises(ValueError, match="authorized frozen Policy"):
        BtcPublicShadowRuntime(
            root=authorized_root,
            policy=policy,
            source=source,
            event_state=EventState.NONE,
        )

    assert not authorized_root.exists()


def test_authorized_runtime_rejects_foreign_workbench_port(policy, tmp_path) -> None:
    session = _session(policy)
    source = FakeRuntimeSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start,
        target_session=session,
        sleep=source.sleeps.append,
    )
    runtime._authorized_runtime_root = True
    try:
        with pytest.raises(ValueError, match="authorized Workbench port"):
            runtime.run_forever(port=9999)
    finally:
        runtime.close()


def _clocked_source(policy, at: datetime) -> ClockedRuntimeSource:
    session = current_deribit_session(at, phase_policy=policy.session)
    return ClockedRuntimeSource(
        policy,
        session,
        reading=DeribitClockReading(
            earliest_at=at,
            estimate_at=at,
            latest_at=at,
            monotonic_ns=1_000_000_000,
        ),
    )


def test_get_time_failure_exhausts_before_creating_a_new_stable_root(
    policy,
    tmp_path,
) -> None:
    at = datetime(2026, 8, 14, 9, 2, tzinfo=UTC)
    source = _clocked_source(policy, at)

    def failed_preflight() -> PublicClockPreflight:
        source.preflight_calls += 1
        raise DeribitSourceError("public/get_time unavailable")

    source.preflight = failed_preflight  # type: ignore[method-assign]
    root = tmp_path / "stable"

    with pytest.raises(RuntimeError, match=r"preflight|public/get_time"):
        BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=source,
            event_state=EventState.NONE,
            sleep=source.sleeps.append,
        )

    assert source.preflight_calls == 3
    assert source.sleeps == [1.0, 2.0]
    assert not root.exists()


def test_every_process_restart_recalibrates_before_mutating_the_existing_root(
    policy,
    tmp_path,
) -> None:
    first_at = datetime(2026, 8, 14, 9, 2, tzinfo=UTC)
    root = tmp_path / "stable"
    first_source = _clocked_source(policy, first_at)
    first = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=first_source,
        event_state=EventState.NONE,
        sleep=first_source.sleeps.append,
    )
    first.close()
    assert first_source.preflight_calls == 1
    accepted = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }

    failed_source = _clocked_source(policy, first_at + timedelta(minutes=4))

    def failed_preflight() -> PublicClockPreflight:
        failed_source.preflight_calls += 1
        raise DeribitSourceError("restart get_time unavailable")

    failed_source.preflight = failed_preflight  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match=r"preflight|restart get_time"):
        BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=failed_source,
            event_state=EventState.NONE,
            sleep=failed_source.sleeps.append,
        )
    assert failed_source.preflight_calls == 3
    assert {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    } == accepted

    second_source = _clocked_source(policy, first_at + timedelta(minutes=5))
    second = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=second_source,
        event_state=EventState.NONE,
        sleep=second_source.sleeps.append,
    )
    try:
        assert second_source.preflight_calls == 1
        assert second.progress.restart_count == 1
    finally:
        second.close()


def test_restart_rejects_deribit_clock_behind_durable_business_floor(
    policy,
    tmp_path,
) -> None:
    started_at = datetime(2026, 8, 14, 9, 2, tzinfo=UTC)
    root = tmp_path / "stable"
    first_source = _clocked_source(policy, started_at)
    first = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=first_source,
        event_state=EventState.NONE,
        sleep=first_source.sleeps.append,
    )
    first_source.set_clock(started_at + timedelta(minutes=1))
    first.tick()
    committed_at = first.progress.updated_at
    first.close()
    accepted = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }

    lagging_source = _clocked_source(policy, committed_at - timedelta(seconds=30))
    with pytest.raises(DeribitSourceError, match="behind durable runtime business time"):
        BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=lagging_source,
            event_state=EventState.NONE,
            sleep=lagging_source.sleeps.append,
        )
    assert {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    } == accepted

    caught_up_source = _clocked_source(policy, committed_at)
    caught_up = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=caught_up_source,
        event_state=EventState.NONE,
        sleep=caught_up_source.sleeps.append,
    )
    try:
        assert caught_up.progress.updated_at >= committed_at
        assert caught_up._business_time_floor >= committed_at
    finally:
        caught_up.close()


def test_restart_rejects_regressing_runtime_audit_boundary(policy, tmp_path) -> None:
    started_at = datetime(2026, 8, 14, 9, 2, tzinfo=UTC)
    root = tmp_path / "stable"
    first_source = _clocked_source(policy, started_at)
    first = BtcPublicShadowRuntime(
        root=root,
        policy=policy,
        source=first_source,
        event_state=EventState.NONE,
        sleep=first_source.sleeps.append,
    )
    first.close()

    event_path = root / "runtime-events.jsonl"
    last_event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[-1])
    regressing_event = {
        **last_event,
        "at": (started_at - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "kind": "FORGED_REGRESSING_BOUNDARY",
        "detail": "test-only durable audit corruption",
    }
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(regressing_event, separators=(",", ":")) + "\n")
    corrupted = event_path.read_bytes()

    restart_source = _clocked_source(policy, started_at + timedelta(minutes=1))
    with pytest.raises(ValueError, match="regressing boundary"):
        BtcPublicShadowRuntime(
            root=root,
            policy=policy,
            source=restart_source,
            event_state=EventState.NONE,
            sleep=restart_source.sleeps.append,
        )
    assert event_path.read_bytes() == corrupted


def test_production_runtime_uses_deribit_time_when_host_wall_disagrees_and_jumps(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    deribit_start = datetime(2026, 8, 14, 9, 2, tzinfo=UTC)
    source = _clocked_source(policy, deribit_start)

    class ForbiddenHostWall:
        @classmethod
        def now(cls, _tz: object = None) -> datetime:
            raise AssertionError("host wall time cannot select or advance business state")

        fromisoformat = staticmethod(datetime.fromisoformat)

    monkeypatch.setattr("optimatrix.runtime.datetime", ForbiddenHostWall)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        sleep=source.sleeps.append,
    )
    try:
        runtime.tick()
        first = source.snapshot_windows[-1]
        assert first.starts_at == datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
        assert runtime.session.session_id == "2026-08-15T08:00:00Z"

        source.set_clock(datetime(2026, 8, 14, 9, 16, tzinfo=UTC))
        runtime.tick()
        second = source.snapshot_windows[-1]
        assert second.starts_at == datetime(2026, 8, 14, 9, 15, tzinfo=UTC)
        assert second.market_session_id == first.market_session_id
    finally:
        runtime.close()


def test_runtime_requests_market_cut_at_earliest_proven_deribit_boundary(
    policy,
    tmp_path,
) -> None:
    earliest = datetime(2026, 8, 14, 9, 2, tzinfo=UTC)
    estimate = earliest + timedelta(milliseconds=500)
    latest = earliest + timedelta(seconds=1)
    session = current_deribit_session(earliest, phase_policy=policy.session)

    class CapturingBoundarySource(ClockedRuntimeSource):
        def __init__(self) -> None:
            super().__init__(
                policy,
                session,
                reading=DeribitClockReading(
                    earliest_at=earliest,
                    estimate_at=estimate,
                    latest_at=latest,
                    monotonic_ns=1_000_000_000,
                ),
            )
            self.snapshot_boundaries: list[datetime] = []

        def snapshot(self, **kwargs: object) -> PublicSnapshotEvaluation:
            self.snapshot_boundaries.append(cast(datetime, kwargs["now"]))
            return super().snapshot(**kwargs)

    source = CapturingBoundarySource()
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        sleep=source.sleeps.append,
    )
    try:
        runtime.tick()

        assert source.snapshot_boundaries == [earliest]
    finally:
        runtime.close()


def test_uncertain_startup_clock_crossing_08_00_cannot_create_the_stable_root(
    policy,
    tmp_path,
) -> None:
    boundary = datetime(2026, 8, 14, 8, tzinfo=UTC)
    preflight_reading = DeribitClockReading(
        earliest_at=boundary - timedelta(milliseconds=2),
        estimate_at=boundary - timedelta(milliseconds=2),
        latest_at=boundary - timedelta(milliseconds=2),
        monotonic_ns=1_000_000_000,
    )
    source = ClockedRuntimeSource(
        policy,
        current_deribit_session(preflight_reading.estimate_at, phase_policy=policy.session),
        reading=preflight_reading,
    )
    projected_reading = DeribitClockReading(
        earliest_at=boundary - timedelta(milliseconds=1),
        estimate_at=boundary,
        latest_at=boundary + timedelta(milliseconds=1),
        monotonic_ns=2_000_000_000,
    )

    def preflight_then_advance() -> PublicClockPreflight:
        source.preflight_calls += 1
        source.reading = projected_reading
        return PublicClockPreflight(
            server_time_ms=int(preflight_reading.estimate_at.timestamp() * 1000),
            request_round_trip_ms=1,
            known_at=preflight_reading.latest_at,
            clock_reading=preflight_reading,
        )

    source.preflight = preflight_then_advance  # type: ignore[method-assign]
    root = tmp_path / "stable"
    runtime: BtcPublicShadowRuntime | None = None

    try:
        with pytest.raises((DeribitSourceError, RuntimeError), match=r"clock|boundary|uncertain"):
            runtime = BtcPublicShadowRuntime(
                root=root,
                policy=policy,
                source=source,
                event_state=EventState.NONE,
                sleep=source.sleeps.append,
            )
    finally:
        if runtime is not None:
            runtime.close()

    assert source.preflight_calls == 1
    assert not root.exists()


def test_clock_uncertainty_crossing_input_deadline_waits_for_a_proven_boundary(
    policy,
    tmp_path,
) -> None:
    at = datetime(2026, 8, 14, 9, 0, 1, tzinfo=UTC)
    source = _clocked_source(policy, at)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        sleep=source.sleeps.append,
    )
    try:
        runtime.tick()
        attempted = source.snapshot_windows[-1]
        assert attempted.input_deadline == datetime(2026, 8, 14, 9, 16, tzinfo=UTC)
        pending_observation_id = runtime.pending_observations[
            attempted.identity
        ].observation.identity

        source.set_clock(
            attempted.input_deadline,
            earliest_at=attempted.input_deadline - timedelta(milliseconds=1),
            latest_at=attempted.input_deadline + timedelta(milliseconds=1),
        )
        runtime.tick()
        assert attempted.identity in runtime.pending_observations
        assert not any(item.window.identity == attempted.identity for item in runtime.ledger.read())
        assert runtime.cases == {}

        source.set_clock(attempted.input_deadline + timedelta(milliseconds=2))
        runtime.tick()

        record = next(
            item for item in runtime.ledger.read() if item.window.identity == attempted.identity
        )
        assert record.observation_id == pending_observation_id
        assert record.result is not DecisionResult.UNKNOWN
    finally:
        runtime.close()


def test_market_cut_received_after_input_deadline_cannot_become_a_decision(
    policy,
    tmp_path,
) -> None:
    session = _session(policy)

    class LateReceiptSource(FakeRuntimeSource):
        def snapshot(self, **kwargs: object) -> PublicSnapshotEvaluation:
            evaluation = super().snapshot(**kwargs)
            target_window = cast(DecisionWindow, kwargs["target_window"])
            late_known_at = target_window.input_deadline + timedelta(milliseconds=1)
            late_observation = MarketObservation.capture(
                channel_id=evaluation.observation.channel_id,
                policy=self.policy.observation,
                context=evaluation.observation.context,
                quotes=evaluation.observation.quotes,
                known_at=late_known_at,
            )
            return replace(evaluation, observation=late_observation)

    source = LateReceiptSource(policy, session)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        now=session.start,
        target_session=session,
        sleep=source.sleeps.append,
    )
    try:
        window = runtime.windows[4]
        runtime.tick(window.ends_at - timedelta(milliseconds=1))
        runtime.tick(window.input_deadline)

        record = next(
            item for item in runtime.ledger.read() if item.window.identity == window.identity
        )
        assert record.result is DecisionResult.UNKNOWN
        assert record.earliest_blocker == "OBSERVATION_AFTER_INPUT_DEADLINE"
        assert runtime.cases == {}
    finally:
        runtime.close()


def test_deribit_07_59_59_to_08_00_rollover_keeps_prior_last_window_until_deadline(
    policy,
    tmp_path,
) -> None:
    before_roll = datetime(2026, 8, 14, 7, 59, 59, 999000, tzinfo=UTC)
    source = _clocked_source(policy, before_roll)
    runtime = BtcPublicShadowRuntime(
        root=tmp_path / "stable",
        policy=policy,
        source=source,
        event_state=EventState.NONE,
        sleep=source.sleeps.append,
    )
    try:
        runtime.tick()
        prior_last_window = source.snapshot_windows[-1]
        assert prior_last_window.ends_at == datetime(2026, 8, 14, 8, tzinfo=UTC)
        assert prior_last_window.identity in runtime.pending_observations

        source.set_clock(datetime(2026, 8, 14, 8, tzinfo=UTC))
        runtime.tick()
        next_first_window = source.snapshot_windows[-1]
        assert next_first_window.starts_at == datetime(2026, 8, 14, 8, tzinfo=UTC)
        assert next_first_window.market_session_id != prior_last_window.market_session_id
        assert prior_last_window.identity in runtime.pending_observations

        source.set_clock(prior_last_window.input_deadline)
        runtime.tick()
        prior_record = next(
            item
            for item in runtime.ledger.read()
            if item.window.identity == prior_last_window.identity
        )
        assert prior_record.window == prior_last_window
    finally:
        runtime.close()
