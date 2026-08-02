from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from market_monitor.types import (
    SourceDataError,
    TimeInterval,
    decimal_from_source,
    require_bool,
    require_int,
    require_list,
    require_mapping,
    require_str,
)

MAX_TTE_MS = 72 * 60 * 60 * 1_000
SETTLEMENT_WINDOW_MS = 30 * 60 * 1_000


class OptionType(StrEnum):
    CALL = "call"
    PUT = "put"


class InstrumentLifecycleState(StrEnum):
    OPEN = "open"
    SETTLEMENT = "settlement"
    DELIVERED = "delivered"
    INACTIVE = "inactive"
    LOCKED = "locked"
    HALTED = "halted"
    ARCHIVIZED = "archivized"


INSTRUMENT_LIFECYCLE_STATES = frozenset(state.value for state in InstrumentLifecycleState)
FINAL_INSTRUMENT_LIFECYCLE_STATES = frozenset(
    {
        InstrumentLifecycleState.DELIVERED.value,
        InstrumentLifecycleState.INACTIVE.value,
        InstrumentLifecycleState.ARCHIVIZED.value,
    }
)
TEMPORARILY_UNAVAILABLE_INSTRUMENT_STATES = frozenset(
    {
        InstrumentLifecycleState.SETTLEMENT.value,
        InstrumentLifecycleState.LOCKED.value,
        InstrumentLifecycleState.HALTED.value,
    }
)


class Applicability(StrEnum):
    APPLICABLE = "APPLICABLE"
    OUT_OF_MONITOR_SCOPE = "OUT_OF_MONITOR_SCOPE"
    TIME_BOUNDARY_UNKNOWN = "TIME_BOUNDARY_UNKNOWN"


@dataclass(frozen=True)
class AmountMetadata:
    contract_size: Decimal
    min_trade_amount: Decimal
    qty_tick_size: Decimal | None


@dataclass(frozen=True)
class OptionInstrument:
    instrument_name: str
    expiration_timestamp_ms: int
    strike: Decimal
    option_type: OptionType
    amount: AmountMetadata | None
    lifecycle_state: InstrumentLifecycleState = InstrumentLifecycleState.OPEN
    is_active: bool = True
    taker_commission: Decimal | None = None


@dataclass(frozen=True)
class ComboLeg:
    instrument_name: str
    amount: Decimal


@dataclass(frozen=True)
class ComboInstrument:
    instrument_name: str
    state: str
    legs: tuple[ComboLeg, ComboLeg]
    amount: AmountMetadata | None


def parse_option_instrument(payload: object) -> OptionInstrument | None:
    data = require_mapping(payload, "instrument")
    product_fields = {
        "kind": require_str(data.get("kind"), "instrument.kind"),
        "base_currency": require_str(data.get("base_currency"), "instrument.base_currency"),
        "quote_currency": require_str(data.get("quote_currency"), "instrument.quote_currency"),
        "settlement_currency": require_str(
            data.get("settlement_currency"), "instrument.settlement_currency"
        ),
        "counter_currency": require_str(
            data.get("counter_currency"), "instrument.counter_currency"
        ),
        "price_index": require_str(data.get("price_index"), "instrument.price_index"),
        "instrument_type": require_str(data.get("instrument_type"), "instrument.instrument_type"),
    }
    if product_fields != {
        "kind": "option",
        "base_currency": "BTC",
        "quote_currency": "USDC",
        "settlement_currency": "USDC",
        "counter_currency": "USDC",
        "price_index": "btc_usdc",
        "instrument_type": "linear",
    }:
        return None
    is_active = require_bool(data.get("is_active"), "instrument.is_active")
    state_raw = require_str(data.get("state"), "instrument.state")
    try:
        state = InstrumentLifecycleState(state_raw)
    except ValueError as exc:
        raise SourceDataError("instrument.state is unsupported") from exc
    if state.value in FINAL_INSTRUMENT_LIFECYCLE_STATES:
        return None
    option_type_raw = require_str(data.get("option_type"), "instrument.option_type")
    try:
        option_type = OptionType(option_type_raw)
    except ValueError as exc:
        raise SourceDataError("instrument.option_type must be call or put") from exc
    expiry = require_int(data.get("expiration_timestamp"), "instrument.expiration_timestamp")
    if expiry <= 0:
        raise SourceDataError("instrument.expiration_timestamp must be positive")
    strike = decimal_from_source(data.get("strike"), "instrument.strike")
    if strike <= 0:
        raise SourceDataError("instrument.strike must be positive")
    try:
        amount = parse_amount_metadata(data, "instrument")
    except SourceDataError:
        amount = None
    taker_commission: Decimal | None = None
    if "taker_commission" in data:
        taker_commission = decimal_from_source(
            data["taker_commission"],
            "instrument.taker_commission",
        )
        if taker_commission < 0:
            raise SourceDataError("instrument.taker_commission must be non-negative")
    return OptionInstrument(
        instrument_name=require_str(data.get("instrument_name"), "instrument.instrument_name"),
        expiration_timestamp_ms=expiry,
        strike=strike,
        option_type=option_type,
        amount=amount,
        lifecycle_state=state,
        is_active=is_active,
        taker_commission=taker_commission,
    )


def parse_combo_instrument(
    summary_payload: object, metadata_payload: object
) -> ComboInstrument | None:
    summary = require_mapping(summary_payload, "combo")
    metadata = require_mapping(metadata_payload, "combo metadata")
    state = require_str(summary.get("state"), "combo.state")
    if state != "active":
        return None
    instrument_name = require_str(summary.get("id"), "combo.id")
    metadata_name = require_str(metadata.get("instrument_name"), "combo metadata.instrument_name")
    if metadata_name != instrument_name:
        raise SourceDataError("combo metadata identity mismatch")
    product_fields = {
        "kind": require_str(metadata.get("kind"), "combo metadata.kind"),
        "base_currency": require_str(metadata.get("base_currency"), "combo metadata.base_currency"),
        "quote_currency": require_str(
            metadata.get("quote_currency"), "combo metadata.quote_currency"
        ),
        "settlement_currency": require_str(
            metadata.get("settlement_currency"), "combo metadata.settlement_currency"
        ),
        "counter_currency": require_str(
            metadata.get("counter_currency"), "combo metadata.counter_currency"
        ),
        "instrument_type": require_str(
            metadata.get("instrument_type"), "combo metadata.instrument_type"
        ),
    }
    if product_fields != {
        "kind": "option_combo",
        "base_currency": "BTC",
        "quote_currency": "USDC",
        "settlement_currency": "USDC",
        "counter_currency": "USDC",
        "instrument_type": "linear",
    }:
        return None
    is_active = require_bool(metadata.get("is_active"), "combo metadata.is_active")
    state_raw = require_str(metadata.get("state"), "combo metadata.state")
    try:
        metadata_state = InstrumentLifecycleState(state_raw)
    except ValueError as exc:
        raise SourceDataError("combo metadata.state is unsupported") from exc
    if not is_active or metadata_state is not InstrumentLifecycleState.OPEN:
        return None
    raw_legs = require_list(summary.get("legs"), "combo.legs")
    if len(raw_legs) != 2:
        return None
    legs: list[ComboLeg] = []
    for index, raw_leg in enumerate(raw_legs):
        leg = require_mapping(raw_leg, f"combo.legs[{index}]")
        leg_amount = decimal_from_source(leg.get("amount"), f"combo.legs[{index}].amount")
        if leg_amount == 0:
            raise SourceDataError("combo leg amount cannot be zero")
        legs.append(
            ComboLeg(
                require_str(leg.get("instrument_name"), f"combo.legs[{index}].instrument_name"),
                leg_amount,
            )
        )
    try:
        combo_amount = parse_amount_metadata(metadata, "combo metadata")
    except SourceDataError:
        combo_amount = None
    return ComboInstrument(
        instrument_name=instrument_name,
        state=state,
        legs=(legs[0], legs[1]),
        amount=combo_amount,
    )


def parse_amount_metadata(data: dict[str, object], prefix: str) -> AmountMetadata:
    contract_size = decimal_from_source(data.get("contract_size"), f"{prefix}.contract_size")
    minimum = decimal_from_source(data.get("min_trade_amount"), f"{prefix}.min_trade_amount")
    if contract_size != 1:
        raise SourceDataError(f"{prefix}.contract_size must be exactly 1")
    if minimum <= 0:
        raise SourceDataError(f"{prefix}.min_trade_amount must be positive")
    step: Decimal | None = None
    if "qty_tick_size" in data:
        step = decimal_from_source(data["qty_tick_size"], f"{prefix}.qty_tick_size")
        if step <= 0:
            raise SourceDataError(f"{prefix}.qty_tick_size must be positive when present")
    return AmountMetadata(contract_size, minimum, step)


def monitor_applicability(
    expiration_timestamp_ms: int, trusted_time: TimeInterval
) -> Applicability:
    lower_tte = expiration_timestamp_ms - trusted_time.upper_ms
    upper_tte = expiration_timestamp_ms - trusted_time.lower_ms
    if upper_tte <= 0 or lower_tte > MAX_TTE_MS:
        return Applicability.OUT_OF_MONITOR_SCOPE
    if lower_tte <= 0 or upper_tte > MAX_TTE_MS:
        return Applicability.TIME_BOUNDARY_UNKNOWN
    return Applicability.APPLICABLE
