from __future__ import annotations

import json
from pathlib import Path

import pytest

from optimatrix.policy import (
    DEFAULT_BTC_SHORT_VOL_POLICY_PATH,
    load_btc_short_vol_policy,
)

POLICY_PATH = DEFAULT_BTC_SHORT_VOL_POLICY_PATH


def _write_policy(tmp_path: Path, mutate) -> Path:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    mutate(value)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_policy_rejects_session_without_entry_capable_time(tmp_path) -> None:
    path = _write_policy(
        tmp_path,
        lambda value: value["session"].update(
            {"roll_reprice_minutes": 1400, "exit_only_minutes_to_expiry": 90}
        ),
    )
    with pytest.raises(ValueError, match="entry-capable"):
        load_btc_short_vol_policy(path)


def test_policy_rejects_invalid_risk_and_execution_ranges(tmp_path) -> None:
    path = _write_policy(
        tmp_path,
        lambda value: value["position"].update({"maximum_short_abs_delta": 1.2}),
    )
    with pytest.raises(ValueError, match="maximum short Delta"):
        load_btc_short_vol_policy(path)


def test_policy_identity_is_stable_and_content_addressed(policy) -> None:
    assert policy.identity.startswith("sha256:")
    assert len(policy.identity) == 71
