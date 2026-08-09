from __future__ import annotations

from dataclasses import dataclass

from options_domain import (
    INVERSE_BTC,
    OptionProductName,
    OptionProductSpec,
    product_for_name,
)
from short_vol_underwriting.constants import (
    INVERSE_BTC_POSITION_POLICY_IDENTITY,
    INVERSE_BTC_RADAR_POLICY_IDENTITY,
    INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
)


@dataclass(frozen=True)
class PersistentProductProfile:
    product: OptionProductSpec
    radar_policy_filename: str
    underwriting_policy_filename: str
    position_policy_filename: str
    radar_policy_identity: str
    underwriting_policy_identity: str
    position_policy_identity: str


INVERSE_BTC_PROFILE = PersistentProductProfile(
    product=INVERSE_BTC,
    radar_policy_filename="short-vol-inverse-btc-public-shadow-radar.json",
    underwriting_policy_filename="short-vol-inverse-btc-public-shadow-underwriting.json",
    position_policy_filename="short-vol-inverse-btc-public-shadow-position.json",
    radar_policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
    underwriting_policy_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
    position_policy_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
)

_PRODUCT_PROFILES = {
    INVERSE_BTC.name: INVERSE_BTC_PROFILE,
}


def persistent_product_profile(
    value: OptionProductName | str | OptionProductSpec,
) -> PersistentProductProfile:
    product = value if isinstance(value, OptionProductSpec) else product_for_name(value)
    try:
        return _PRODUCT_PROFILES[product.name]
    except KeyError as exc:
        raise ValueError(f"unsupported persistent option product: {product.name.value}") from exc
