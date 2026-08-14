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


def test_policy_rejects_invalid_delivery_risk_range(tmp_path) -> None:
    path = _write_policy(
        tmp_path,
        lambda value: value["risk"].update({"delivery_price_stress_factors": [0, 1, 2]}),
    )
    with pytest.raises(ValueError, match="delivery stress factors"):
        load_btc_short_vol_policy(path)


def test_policy_identity_is_stable_and_content_addressed(policy) -> None:
    assert policy.schema_version == 7
    assert policy.window.cadence_minutes == 15
    assert policy.identity.startswith("sha256:")
    assert len(policy.identity) == 71


def test_policy_rejects_removed_single_side_top_n_selector(tmp_path) -> None:
    path = _write_policy(
        tmp_path,
        lambda value: value["structure"].update({"top_verticals_per_side": 3}),
    )
    with pytest.raises(ValueError, match="structure policy has unexpected fields"):
        load_btc_short_vol_policy(path)
