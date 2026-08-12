from __future__ import annotations

import pytest

from optimatrix.channels import CHANNELS, ChannelId, require_implemented_channel


def test_only_btc_short_vol_is_implemented_but_four_channel_contract_is_explicit() -> None:
    assert set(CHANNELS) == set(ChannelId)
    implemented = [item.channel_id for item in CHANNELS.values() if item.implemented]
    assert implemented == [ChannelId.INVERSE_BTC_SHORT_VOL]
    assert require_implemented_channel(ChannelId.INVERSE_BTC_SHORT_VOL).implemented
    with pytest.raises(NotImplementedError):
        require_implemented_channel(ChannelId.INVERSE_ETH_SHORT_VOL)
