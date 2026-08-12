from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from optimatrix.products import BTC, ETH, ProductSpec


class StrategyId(StrEnum):
    TWO_SIDED_SHORT_VOL = "TWO_SIDED_SHORT_VOL"
    LONG_GAMMA = "LONG_GAMMA"


class ChannelId(StrEnum):
    INVERSE_BTC_SHORT_VOL = "INVERSE_BTC_SHORT_VOL"
    INVERSE_BTC_LONG_GAMMA = "INVERSE_BTC_LONG_GAMMA"
    INVERSE_ETH_SHORT_VOL = "INVERSE_ETH_SHORT_VOL"
    INVERSE_ETH_LONG_GAMMA = "INVERSE_ETH_LONG_GAMMA"


@dataclass(frozen=True)
class ChannelDescriptor:
    channel_id: ChannelId
    product: ProductSpec
    strategy_id: StrategyId
    implemented: bool
    implementation_name: str | None


CHANNELS = {
    ChannelId.INVERSE_BTC_SHORT_VOL: ChannelDescriptor(
        channel_id=ChannelId.INVERSE_BTC_SHORT_VOL,
        product=BTC,
        strategy_id=StrategyId.TWO_SIDED_SHORT_VOL,
        implemented=True,
        implementation_name="BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1",
    ),
    ChannelId.INVERSE_BTC_LONG_GAMMA: ChannelDescriptor(
        channel_id=ChannelId.INVERSE_BTC_LONG_GAMMA,
        product=BTC,
        strategy_id=StrategyId.LONG_GAMMA,
        implemented=False,
        implementation_name=None,
    ),
    ChannelId.INVERSE_ETH_SHORT_VOL: ChannelDescriptor(
        channel_id=ChannelId.INVERSE_ETH_SHORT_VOL,
        product=ETH,
        strategy_id=StrategyId.TWO_SIDED_SHORT_VOL,
        implemented=False,
        implementation_name=None,
    ),
    ChannelId.INVERSE_ETH_LONG_GAMMA: ChannelDescriptor(
        channel_id=ChannelId.INVERSE_ETH_LONG_GAMMA,
        product=ETH,
        strategy_id=StrategyId.LONG_GAMMA,
        implemented=False,
        implementation_name=None,
    ),
}


def require_implemented_channel(channel_id: ChannelId) -> ChannelDescriptor:
    descriptor = CHANNELS[channel_id]
    if not descriptor.implemented:
        raise NotImplementedError(f"channel is reserved but not implemented: {channel_id.value}")
    return descriptor
