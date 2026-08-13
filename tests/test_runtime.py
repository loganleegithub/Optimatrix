from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from optimatrix.case_journal import CaseJournal
from optimatrix.decision import MarketObservation
from optimatrix.deribit_snapshot import (
    DERIBIT_DELIVERY_PRICE_METHOD_ID,
    DERIBIT_DELIVERY_PRICE_SOURCE_ID,
    DeribitSourceError,
    PublicSnapshotEvaluation,
    SnapshotMethodology,
)
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
        event_state: EventState = EventState.NONE,
    ) -> None:
        self.policy = policy
        self.session = session
        self.fail_snapshot = fail_snapshot
        self.snapshot_delay = snapshot_delay
        self.event_state = event_state
        self.preflight_calls = 0
        self.snapshot_calls = 0
        self.history_calls = 0
        self.settlement_calls = 0
        self.sleeps: list[float] = []
        self.history_points = _history(session)

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
        if self.fail_snapshot:
            raise DeribitSourceError("bounded fake market failure")
        response_at = now + self.snapshot_delay
        quotes = base_chain(expiry=self.session.end, observed_at=response_at)
        quote_names = tuple(sorted(quote.instrument_name for quote in quotes))
        assert set(required_instrument_names) <= set(quote_names)
        context = market_context(response_at, event=self.event_state, book_names=quote_names)
        captured = MarketObservation.capture(
            channel_id=self.policy.channel_id,
            policy=self.policy.observation,
            context=context,
            quotes=quotes,
        )
        selection = select_btc_0dte_condor(observation=captured, policy=self.policy)
        return PublicSnapshotEvaluation(
            observed_at=response_at,
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

    def history(self, *, known_at: datetime) -> IndexHistoryCapture:
        assert known_at >= self.session.end
        self.history_calls += 1
        return IndexHistoryCapture(points=self.history_points, known_at=known_at, error=None)

    def settlement(
        self,
        *,
        expiry: datetime,
        known_at: datetime,
    ) -> ExpirySettlementFact:
        self.settlement_calls += 1
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
        assert document["population"]["decisions"]["recorded"] == "96"
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
        assert (root / "settlement.json").is_file()
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


def test_preflight_retry_refreshes_production_request_boundary(
    policy,
    tmp_path,
    monkeypatch,
) -> None:
    session = _session(policy)
    boundary = session.start - timedelta(minutes=5)
    wall_times = iter((boundary + timedelta(seconds=1), boundary + timedelta(seconds=7)))

    class ControlledDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = next(wall_times)
            return value if tz is None else value.astimezone(tz)

    observed: list[datetime] = []

    def fake_preflight(_client, *, local_now, maximum_clock_skew_ms):
        assert maximum_clock_skew_ms == 5_000
        observed.append(local_now)
        if len(observed) == 1:
            raise DeribitSourceError("first bounded preflight timeout")
        return SimpleNamespace(known_at=local_now)

    monkeypatch.setattr("optimatrix.runtime.datetime", ControlledDateTime)
    monkeypatch.setattr("optimatrix.runtime.preflight_public_clock", fake_preflight)
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
        assert observed == [boundary + timedelta(seconds=1), boundary + timedelta(seconds=7)]
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
