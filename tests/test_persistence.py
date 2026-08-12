from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from optimatrix.engine import ShadowEngine
from optimatrix.lifecycle import EntryStatus, ExitReason, PositionRiskAction, PositionState
from optimatrix.persistence import (
    CaseJournal,
    JournalError,
    position_from_object,
    position_to_object,
)
from optimatrix.scenarios import (
    _opened_position,
    _remove_ask,
    _update_delta,
    base_chain,
    current_expiry,
    market_context,
    restamp_quotes,
)


def test_process_restart_recovers_same_position_and_exit_duty(policy, tmp_path) -> None:
    now, _engine, position, quotes = _opened_position(policy, tmp_path)
    restarted = ShadowEngine(policy=policy, case_root=tmp_path)
    recovered = restarted.recover_position(position.case_identity)
    assert recovered is not None
    assert recovered.position_identity == position.position_identity
    risk_at = now + timedelta(hours=2)
    armed = restarted.observe_position(
        position=recovered,
        quotes=_update_delta(
            quotes,
            put_delta=Decimal("-0.58"),
            call_delta=Decimal("0.08"),
            observed_at=risk_at,
        ),
        context=market_context(risk_at, index=Decimal("96000")),
    )
    assert armed.action is PositionRiskAction.EXIT_DUTY_ARMED
    assert recovered.put_side.short_open and recovered.call_side.short_open

    recovered_again = ShadowEngine(policy=policy, case_root=tmp_path).recover_position(
        position.case_identity
    )
    assert recovered_again is not None
    assert recovered_again.first_instruction == armed.instruction
    assert recovered_again.state is PositionState.EXIT_REQUIRED
    exit_at = risk_at + timedelta(minutes=1)
    projected = restarted.observe_position(
        position=recovered_again,
        quotes=restamp_quotes(quotes, exit_at),
        context=market_context(exit_at, index=Decimal("96000")),
    )
    assert projected.action is PositionRiskAction.PORTFOLIO_TERMINAL
    assert not recovered_again.has_short_risk


def test_journal_rejects_non_consecutive_or_corrupt_records(policy, tmp_path) -> None:
    _now, _engine, position, _quotes = _opened_position(policy, tmp_path)
    journal = CaseJournal(tmp_path, position.case_identity)
    journal.append("POSITION_CHECKPOINT", position_to_object(position))
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    journal.path.write_text(lines[0] + "\n" + '{"bad":true}\n', encoding="utf-8")
    try:
        journal.read()
    except JournalError:
        pass
    else:
        raise AssertionError("corrupt journal was accepted")


def test_read_only_recovery_does_not_create_a_case_root(policy, tmp_path) -> None:
    from optimatrix.engine import ShadowEngine

    root = tmp_path / "absent-root"
    recovered = ShadowEngine(policy=policy, case_root=root).recover_position("sha256:" + "1" * 64)
    assert recovered is None
    assert not root.exists()


def test_recovery_rejects_position_identity_chain_tampering(policy, tmp_path) -> None:
    import json

    _now, _engine, position, _quotes = _opened_position(policy, tmp_path)
    journal = CaseJournal(tmp_path, position.case_identity)
    records = [json.loads(line) for line in journal.path.read_text(encoding="utf-8").splitlines()]
    checkpoint = next(
        record for record in reversed(records) if record["kind"] == "POSITION_CHECKPOINT"
    )
    checkpoint["payload"]["entry_identity"] = "sha256:" + "e" * 64
    journal.path.write_text(
        "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records)
        + "\n",
        encoding="utf-8",
    )

    try:
        journal.latest_position()
    except JournalError as exc:
        assert "Position identity mismatch" in str(exc)
    else:
        raise AssertionError("tampered Position identity chain was accepted")


def test_recovery_rejects_entry_result_identity_tampering(policy, tmp_path) -> None:
    import json

    _now, _engine, position, _quotes = _opened_position(policy, tmp_path)
    journal = CaseJournal(tmp_path, position.case_identity)
    records = [json.loads(line) for line in journal.path.read_text(encoding="utf-8").splitlines()]
    entry = next(record for record in records if record["kind"] == "ENTRY_TERMINAL")
    entry["payload"]["entry_result"]["entry_identity"] = "sha256:" + "f" * 64
    journal.path.write_text(
        "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records)
        + "\n",
        encoding="utf-8",
    )

    try:
        journal.latest_entry_result()
    except JournalError as exc:
        assert "Entry result identity mismatch" in str(exc)
    else:
        raise AssertionError("tampered Entry result identity was accepted")


def test_partial_entry_remediation_survives_restart(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(at)
    chain = base_chain(expiry=current_expiry(at), observed_at=at)
    engine = ShadowEngine(policy=policy, case_root=tmp_path)
    case = engine.open_decision_case(
        decision=engine.evaluate(quotes=chain, context=context),
        opened_at=at,
    )
    entry_at = at + timedelta(minutes=1)
    result, position = engine.attempt_entry(
        case=case,
        quotes=restamp_quotes(_remove_ask(chain, instrument_suffix="107000-C"), entry_at),
        context=replace(context, now=entry_at),
        attempted_at=entry_at,
    )
    assert result.status is EntryStatus.PUT_SIDE_ONLY and position is not None
    restarted = ShadowEngine(policy=policy, case_root=tmp_path)
    recovered = restarted.recover_position(case.case_identity)
    assert recovered is not None
    assert recovered.state is PositionState.EXIT_REQUIRED
    assert recovered.first_instruction is not None
    assert recovered.first_instruction.reason is ExitReason.ENTRY_ACQUISITION_INCOMPLETE
    assert recovered.put_side.exit_requested_reason is ExitReason.ENTRY_ACQUISITION_INCOMPLETE
    blocked_at = entry_at + timedelta(minutes=1)
    restarted.observe_position(
        position=recovered,
        quotes=restamp_quotes(
            _remove_ask(chain, instrument_suffix="95000-P"),
            blocked_at,
        ),
        context=replace(context, now=blocked_at),
    )
    recovered_again = ShadowEngine(policy=policy, case_root=tmp_path).recover_position(
        case.case_identity
    )
    assert recovered_again is not None
    assert recovered_again.state is PositionState.EXIT_REQUIRED
    assert recovered_again.put_side.exit_attempt_count == 1


def test_codec_rejects_partial_position_that_was_tampered_back_to_monitoring(
    policy,
    tmp_path,
) -> None:
    at = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(at)
    chain = base_chain(expiry=current_expiry(at), observed_at=at)
    engine = ShadowEngine(policy=policy, case_root=tmp_path)
    case = engine.open_decision_case(
        decision=engine.evaluate(quotes=chain, context=context),
        opened_at=at,
    )
    entry_at = at + timedelta(minutes=1)
    _result, position = engine.attempt_entry(
        case=case,
        quotes=restamp_quotes(_remove_ask(chain, instrument_suffix="107000-C"), entry_at),
        context=replace(context, now=entry_at),
        attempted_at=entry_at,
    )
    assert position is not None
    payload = position_to_object(position)
    payload["state"] = PositionState.MONITORING.value
    try:
        position_from_object(payload)
    except JournalError as exc:
        assert "must remain EXIT_REQUIRED" in str(exc)
    else:
        raise AssertionError("partial short exposure was accepted as normal carry")
