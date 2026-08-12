from __future__ import annotations

from optimatrix.scenarios import run_all_scenarios


def test_all_declared_business_scenarios_pass(policy, tmp_path) -> None:
    results = run_all_scenarios(policy, root=tmp_path)
    failed = [result for result in results if not result.passed]
    assert not failed, [(result.name, result.facts) for result in failed]
    assert len(results) == 18
