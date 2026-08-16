# ruff: noqa: RUF001 -- assertions intentionally match Chinese trader-facing copy.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from optimatrix.ai_lab.cli import main as ai_lab_main
from optimatrix.ai_lab.memory import MemoryDigest
from optimatrix.ai_lab.report import render_session_report, write_session_report
from optimatrix.ai_lab.session_review import SessionVerdict, review_session
from optimatrix.decision import DecisionResult, schedule_decision_windows
from optimatrix.engine import Btc0DteShortVolEngine
from optimatrix.lifecycle import FuturePathSummary, WindowOutcome, window_outcome_eligibility
from optimatrix.market import ExpirySettlementFact, SettlementEvidenceKind
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.products import ProductId
from optimatrix.radar import evaluate_btc_short_vol_window
from optimatrix.risk import ShadowCapacity
from optimatrix.scenarios import base_chain, market_context
from optimatrix.session import current_deribit_session


def test_terminal_profit_alone_is_not_a_hindsight_opportunity(policy, tmp_path) -> None:
    session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0010"),
        realized_variance=Decimal("0.0016"),
        delivery_price=Decimal("100000"),
        path_mode="SAFE_ALL",
    )

    review = review_session(
        session_id=session_id,
        policy=policy,
        records=records,
        outcomes=outcomes,
    )

    assert review.verdict is SessionVerdict.NO_OPPORTUNITY_CORRECTLY_AVOIDED
    assert review.expected_window_count == review.auditable_window_count == 96
    assert review.control_candidate_count > 0
    assert review.hindsight_opportunity_structure_count == 0
    assert review.correct_avoidance_window_count == 96
    assert not review.challenger_comparison_eligible
    markdown = render_session_report(review=review, memory=_empty_memory())
    assert "最终盈利只是其中一项" in markdown
    assert "本 Session 没有机会，Base 避险正确" in markdown
    assert "ENTRY_IV_DID_NOT_EXCEED_HINDSIGHT_RV" in markdown
    json_path, markdown_path = write_session_report(
        review=review,
        memory=_empty_memory(),
        root=tmp_path / "ai-lab",
    )
    assert json_path.is_file() and markdown_path.is_file()
    assert write_session_report(
        review=review,
        memory=_empty_memory(),
        root=tmp_path / "ai-lab",
    ) == (json_path, markdown_path)


def test_complete_hindsight_opportunity_exposes_quantified_base_miss(policy) -> None:
    session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0011"),
        realized_variance=Decimal("0.0010"),
        delivery_price=Decimal("100000"),
        path_mode="SAFE_ALL",
    )

    review = review_session(
        session_id=session_id,
        policy=policy,
        records=records,
        outcomes=outcomes,
    )

    assert review.verdict is SessionVerdict.RULE_TOO_CONSERVATIVE
    assert review.missed_opportunity_window_count > 0
    assert review.hindsight_opportunity_structure_count > 0
    assert review.base_candidate_window_count == 0
    assert not review.challenger_comparison_eligible
    vrp_gates = [
        gate
        for opportunity in review.opportunities
        for gate in opportunity.gate_distances
        if gate.code == "SESSION_VRP_PROXY_BELOW_THRESHOLD"
    ]
    assert vrp_gates
    assert all(gate.quantifiable for gate in vrp_gates)
    assert all(gate.signed_margin_to_pass is not None for gate in vrp_gates)
    assert all(gate.signed_margin_to_pass < 0 for gate in vrp_gates)
    assert all(
        gate.signed_margin_to_pass is None or gate.signed_margin_to_pass < 0
        for opportunity in review.opportunities
        for gate in opportunity.gate_distances
    )


def test_short_strike_breach_turns_terminal_profit_into_correct_avoidance(policy) -> None:
    session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0011"),
        realized_variance=Decimal("0.0010"),
        delivery_price=Decimal("100000"),
        path_mode="BREACH_ALL",
    )

    review = review_session(
        session_id=session_id,
        policy=policy,
        records=records,
        outcomes=outcomes,
    )

    assert review.verdict is SessionVerdict.NO_OPPORTUNITY_CORRECTLY_AVOIDED
    assert review.hindsight_opportunity_structure_count == 0
    assert review.correct_avoidance_window_count == 96


def test_base_candidate_with_adverse_path_is_over_risk(policy) -> None:
    session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0024"),
        realized_variance=Decimal("0.0016"),
        delivery_price=Decimal("100000"),
        path_mode="BREACH_ALL",
    )

    review = review_session(
        session_id=session_id,
        policy=policy,
        records=records,
        outcomes=outcomes,
    )

    assert review.verdict is SessionVerdict.RULE_TOO_AGGRESSIVE
    assert review.over_risk_window_count == review.base_candidate_window_count > 0
    assert all(
        "CALL_SHORT_STRIKE_BREACHED" in window.selected_candidate_hindsight_reasons
        for window in review.windows
        if window.classification.value == "OVER_RISK_SELECTION"
    )
    assert all(
        window.selected_settlement_result_usd is not None
        and window.selected_short_call_strike_usd is not None
        and window.selected_path_maximum_index_usd is not None
        for window in review.windows
        if window.classification.value == "OVER_RISK_SELECTION"
    )
    assert not review.challenger_comparison_eligible


def test_only_complete_well_calibrated_session_unlocks_challenger(policy) -> None:
    session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0024"),
        realized_variance=Decimal("0.0016"),
        delivery_price=Decimal("100000"),
        path_mode="SAFE_CANDIDATES_ONLY",
    )

    complete = review_session(
        session_id=session_id,
        policy=policy,
        records=records,
        outcomes=outcomes,
    )
    incomplete = review_session(
        session_id=session_id,
        policy=policy,
        records=records,
        outcomes=outcomes[:-1],
    )

    assert complete.verdict is SessionVerdict.RULE_WELL_CALIBRATED
    assert complete.captured_opportunity_window_count > 0
    assert complete.missed_opportunity_window_count == complete.over_risk_window_count == 0
    assert complete.challenger_comparison_eligible
    assert incomplete.verdict is SessionVerdict.UNKNOWN
    assert incomplete.unknown_window_count == 1
    assert not incomplete.challenger_comparison_eligible


def test_missing_curve_point_makes_whole_session_unknown(policy) -> None:
    session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0011"),
        realized_variance=Decimal("0.0010"),
        delivery_price=Decimal("100000"),
        path_mode="SAFE_ALL",
    )

    review = review_session(
        session_id=session_id,
        policy=policy,
        records=records[:-1],
        outcomes=outcomes,
    )

    assert review.verdict is SessionVerdict.UNKNOWN
    assert review.curve_observation_count == 95
    assert review.auditable_window_count == 0
    assert review.unknown_window_count == 96
    assert dict(review.evidence_reason_counts)["SESSION_IV_RV_CURVE_INCOMPLETE"] == 96


def test_cli_writes_report_before_optional_codex_failure(policy, tmp_path, capsys) -> None:
    session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0011"),
        realized_variance=Decimal("0.0010"),
        delivery_price=Decimal("100000"),
        path_mode="SAFE_ALL",
    )
    ledger_root = tmp_path / "ledger"
    ledger = ObservationLedger(ledger_root)
    for record in records:
        ledger.append(record)
    for outcome in outcomes:
        ledger.append_outcome(outcome)
    lab_root = tmp_path / "ai-lab"
    recorded_at = datetime.fromisoformat(session_id.replace("Z", "+00:00")) + timedelta(minutes=45)

    status = ai_lab_main(
        [
            "review-session",
            "--ledger-root",
            str(ledger_root),
            "--lab-root",
            str(lab_root),
            "--session-id",
            session_id,
            "--recorded-at",
            recorded_at.isoformat().replace("+00:00", "Z"),
            "--with-codex",
            "--codex-binary",
            str(tmp_path / "missing-codex"),
        ]
    )

    assert status == 0
    output = capsys.readouterr().out
    assert '"verdict": "RULE_TOO_CONSERVATIVE"' in output
    assert '"codex_status": "FAILED_OPTIONAL_ANALYSIS"' in output
    assert (lab_root / "policy-quality-reviews.jsonl").is_file()
    reports = tuple((lab_root / "reports").rglob("policy-quality-review.md"))
    assert len(reports) == 1
    assert "规则偏保守，漏掉了机会" in reports[0].read_text(encoding="utf-8")


def _population(
    policy: BtcShortVolPolicy,
    *,
    implied_variance: Decimal,
    realized_variance: Decimal,
    delivery_price: Decimal,
    path_mode: str,
) -> tuple[str, tuple, tuple]:
    if path_mode not in {"SAFE_ALL", "BREACH_ALL", "SAFE_CANDIDATES_ONLY"}:
        raise ValueError("unsupported synthetic path mode")
    anchor = datetime(2026, 8, 14, 12, tzinfo=UTC)
    session = current_deribit_session(anchor, phase_policy=policy.session)
    windows = schedule_decision_windows(
        session=session,
        channel_id=policy.channel_id,
        policy=policy.window,
    )
    engine = Btc0DteShortVolEngine(policy=policy)
    records = []
    for window in windows:
        observed_at = window.starts_at + timedelta(seconds=1)
        observation = engine.capture_observation(
            quotes=base_chain(expiry=session.end, observed_at=observed_at),
            context=market_context(
                observed_at,
                implied_variance=implied_variance,
                realized_variance=realized_variance,
            ),
        )
        record = evaluate_btc_short_vol_window(
            window=window,
            observation=observation,
            capacity=ShadowCapacity.empty(
                channel_id=policy.channel_id,
                market_session_id=session.session_id,
                known_at=window.input_deadline,
            ),
            policy=policy,
            known_at=window.input_deadline,
        ).record
        assert record.result is not DecisionResult.UNKNOWN
        records.append(record)
    settlement = ExpirySettlementFact(
        product_id=ProductId.INVERSE_BTC,
        expiry=session.end,
        delivery_price_usd=delivery_price,
        known_at=session.end + timedelta(minutes=1),
        evidence_kind=SettlementEvidenceKind.DETERMINISTIC_ACCEPTANCE_FIXTURE,
        source_id="AI_LAB_SYNTHETIC_SETTLEMENT",
        method_id="FIXED_DELIVERY_PRICE",
    )
    outcomes = []
    for record in records:
        horizon_start = record.window.ends_at
        horizon_end = max(session.end, horizon_start + timedelta(minutes=15))
        breach = path_mode == "BREACH_ALL" or (
            path_mode == "SAFE_CANDIDATES_ONLY" and record.result is not DecisionResult.CANDIDATE
        )
        minimum = min(Decimal("99000"), delivery_price)
        maximum = Decimal("110000") if breach else max(Decimal("101000"), delivery_price)
        outcomes.append(
            WindowOutcome(
                decision_window_id=record.window.identity,
                horizon_starts_at=horizon_start,
                horizon_ends_at=horizon_end,
                known_at=session.end + timedelta(minutes=30),
                future_path_known=True,
                future_path_continuous=True,
                expiry_settlement=settlement,
                future_path=FuturePathSummary(
                    source_id="AI_LAB_SYNTHETIC_CONTINUOUS_PATH",
                    method_id="FIXED_EXTREMA",
                    starts_at=horizon_start,
                    ends_at=horizon_end,
                    observation_count=96,
                    start_index_price_usd=Decimal("100000"),
                    end_index_price_usd=delivery_price,
                    minimum_index_price_usd=minimum,
                    maximum_index_price_usd=maximum,
                    maximum_rv_acceleration=Decimal("0.20"),
                ),
                regime_labels=("SYNTHETIC_AI_LAB_ACCEPTANCE",),
                reason=None,
                eligibility=window_outcome_eligibility(
                    decision_evaluable=True,
                    future_path_known=True,
                    future_path_continuous=True,
                ),
            )
        )
    return session.session_id, tuple(records), tuple(outcomes)


def _empty_memory() -> MemoryDigest:
    return MemoryDigest(
        prior_review_count=0,
        invalid_legacy_review_count=0,
        verdict_counts=(),
        recurring_base_blockers=(),
        hypothesis_counts=(),
        prior_sessions=(),
        fact_ids=(),
    )
