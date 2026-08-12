from __future__ import annotations

import pytest

from optimatrix.policy import (
    DEFAULT_BTC_SHORT_VOL_POLICY_PATH,
    BtcShortVolPolicy,
    load_btc_short_vol_policy,
)


@pytest.fixture
def policy() -> BtcShortVolPolicy:
    return load_btc_short_vol_policy(DEFAULT_BTC_SHORT_VOL_POLICY_PATH)
