from __future__ import annotations

from optimatrix.scenarios import run_all_scenarios


def test_all_declared_business_scenarios_pass(policy, tmp_path) -> None:
    results = run_all_scenarios(policy, root=tmp_path)
    failed = [result for result in results if not result.passed]
    assert not failed, [(result.name, result.facts) for result in failed]
    names = {result.name for result in results}
    assert "unknown_market_context_stops_before_structure" in names
    assert "strict_future_exit_closes_two_sided_duty" in names
    assert "short_risk_exit_keeps_residual_wings" in names
