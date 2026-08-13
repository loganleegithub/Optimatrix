from __future__ import annotations

from datetime import UTC, datetime

import pytest

from optimatrix.decision import (
    DecisionRecord,
    MarketObservation,
    unassessed_decision_record,
)
from optimatrix.engine import Btc0DteShortVolEngine
from optimatrix.identity import canonical_identity
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.risk import ShadowCapacity
from optimatrix.scenarios import base_chain, current_expiry, market_context


def test_all_windows_are_counted_once_and_duplicate_is_idempotent(policy, tmp_path) -> None:
    observed_at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    windows = engine.decision_windows(at=observed_at)
    observed_window = next(
        window for window in windows if window.starts_at <= observed_at < window.ends_at
    )
    observation = MarketObservation.capture(
        channel_id=policy.channel_id,
        policy=policy.observation,
        context=market_context(observed_at),
        quotes=base_chain(expiry=current_expiry(observed_at), observed_at=observed_at),
    )
    ledger = ObservationLedger(tmp_path / "ledger")
    records = []
    for window in windows:
        records.append(
            engine.assess_window(
                ledger=ledger,
                window=window,
                observation=observation if window == observed_window else None,
                capacity=None,
                known_at=window.input_deadline,
            ).record
        )

    assert ledger.append(records[0]) is False
    assert len(ledger.read()) == 96
    summary = ledger.summarize(expected_windows=windows)
    assert summary.denominator == 96
    assert summary.recorded == 96
    assert summary.missing == 0
    assert summary.complete
    assert dict(summary.result_counts) == {"UNKNOWN": 96}
    assert dict(summary.earliest_blocker_counts) == {
        "SHADOW_CAPACITY_UNKNOWN": 1,
        "NO_OBSERVATION": 95,
    }
    ledger_text = ledger.path.read_text(encoding="utf-8")
    assert '"source_timestamp_ms"' not in ledger_text
    assert '"bid"' not in ledger_text
    assert '"ask"' not in ledger_text
    assert '"levels"' not in ledger_text
    assert "trailing_realized_variance" not in ledger_text


def test_same_window_with_different_record_conflicts(policy, tmp_path) -> None:
    engine = Btc0DteShortVolEngine(policy=policy)
    window = engine.decision_windows(at=datetime(2026, 8, 12, 18, 0, tzinfo=UTC))[0]
    ledger = ObservationLedger(tmp_path / "ledger")
    record = unassessed_decision_record(
        window=window,
        decision_policy_id=policy.identity,
        known_at=window.input_deadline,
        observation=None,
    )
    ledger.append(record)
    conflicting = unassessed_decision_record(
        window=window,
        decision_policy_id=canonical_identity("DecisionPolicyV1", "other"),
        known_at=window.input_deadline,
        observation=None,
    )

    with pytest.raises(ValueError, match="different DecisionRecord"):
        ledger.append(conflicting)


def test_partial_ledger_reports_missing_windows(policy, tmp_path) -> None:
    engine = Btc0DteShortVolEngine(policy=policy)
    windows = engine.decision_windows(at=datetime(2026, 8, 12, 18, 0, tzinfo=UTC))
    ledger = ObservationLedger(tmp_path / "ledger")
    ledger.append(
        unassessed_decision_record(
            window=windows[0],
            decision_policy_id=policy.identity,
            known_at=windows[0].input_deadline,
            observation=None,
        )
    )

    summary = ledger.summarize(expected_windows=windows)
    assert summary.denominator == 96
    assert summary.recorded == 1
    assert summary.missing == 95
    assert not summary.complete


def test_candidate_payload_tampering_is_rejected(policy, tmp_path) -> None:
    observed_at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    window = next(
        item
        for item in engine.decision_windows(at=observed_at)
        if item.starts_at <= observed_at < item.ends_at
    )
    observation = engine.capture_observation(
        context=market_context(observed_at),
        quotes=base_chain(expiry=current_expiry(observed_at), observed_at=observed_at),
    )
    assessment = engine.assess_window(
        ledger=ObservationLedger(tmp_path / "source"),
        window=window,
        observation=observation,
        capacity=ShadowCapacity.empty(
            channel_id=policy.channel_id,
            market_session_id=window.market_session_id,
            known_at=window.input_deadline,
        ),
        known_at=window.input_deadline,
    )
    encoded = assessment.record.as_object()
    original_identity = assessment.record.identity
    detached = assessment.record.selected_structure
    assert detached is not None
    detached["candidate_id"] = canonical_identity("CandidateV1", "detached-mutation")
    assert assessment.record.identity == original_identity
    assert assessment.record.selected_structure_id == (
        assessment.record.selected_structure or {}
    ).get("candidate_id")
    structure = encoded["selected_structure"]
    assert isinstance(structure, dict)
    structure["candidate_id"] = canonical_identity("CandidateV1", "tampered")
    with pytest.raises(ValueError, match="selected structure payload"):
        DecisionRecord.from_object(encoded)
