from __future__ import annotations

from optimatrix.scenarios import run_all_scenarios


def test_all_declared_business_scenarios_pass(policy, tmp_path) -> None:
    results = run_all_scenarios(policy, root=tmp_path)
    failed = [result for result in results if not result.passed]
    assert not failed, [(result.name, result.facts) for result in failed]
    names = {result.name for result in results}
    assert names == {
        "whole_product_candidate",
        "missing_window_is_unknown",
        "shallow_close_depth_is_diagnostic",
        "known_path_risk_abstains",
        "atomic_shadow_case_exit",
        "gap_preserves_position_then_settlement",
        "all_window_outcome_is_independent",
    }
