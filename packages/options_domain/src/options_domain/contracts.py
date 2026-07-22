"""Observed option, surface, and executable vertical contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from market_tape import OptionKind, canonical_digest


@dataclass(frozen=True, slots=True)
class OptionQuote:
    instrument_name: str
    expiry: datetime
    tte_seconds: int
    strike: Decimal
    option_kind: OptionKind
    bid: Decimal | None
    ask: Decimal | None
    bid_amount: Decimal | None
    ask_amount: Decimal | None
    bid_iv: Decimal | None
    ask_iv: Decimal | None
    mark_iv: Decimal | None
    delta: Decimal | None
    gamma: Decimal | None
    open_interest: Decimal | None
    contract_size: Decimal
    min_trade_amount: Decimal
    amount_step: Decimal
    taker_commission: Decimal
    quote_age_ms: int
    fresh: bool
    instrument_source_capture_seq: int
    ticker_source_capture_seq: int
    source_at: datetime

    def __post_init__(self) -> None:
        if self.tte_seconds <= 0:
            raise ValueError("option quote must have positive TTE")
        if self.strike <= 0 or self.contract_size <= 0:
            raise ValueError("option strike and contract size must be positive")
        if any(item is not None and item < 0 for item in (self.bid_amount, self.ask_amount)):
            raise ValueError("option depth cannot be negative")
        if self.quote_age_ms < 0:
            raise ValueError("option quote age cannot be negative")
        if self.instrument_source_capture_seq <= 0 or self.ticker_source_capture_seq <= 0:
            raise ValueError("option quote source sequences must be positive")

    @property
    def source_capture_seqs(self) -> tuple[int, ...]:
        return tuple(sorted({self.instrument_source_capture_seq, self.ticker_source_capture_seq}))


@dataclass(frozen=True, slots=True)
class ComboQuote:
    combo_id: str
    short_instrument: str
    long_instrument: str
    bid: Decimal | None
    ask: Decimal | None
    bid_amount: Decimal
    ask_amount: Decimal
    quote_age_ms: int
    fresh: bool
    valid: bool
    source_capture_seq: int

    def __post_init__(self) -> None:
        if self.source_capture_seq <= 0:
            raise ValueError("combo quote source sequence must be positive")


@dataclass(frozen=True, slots=True)
class ExecutableVerticalClose:
    combo_id: str | None
    execution_source: str
    debit: Decimal
    fee_usdc: Decimal
    depth: Decimal
    combo_source_capture_seq: int | None

    def __post_init__(self) -> None:
        if self.debit < 0 or self.fee_usdc < 0 or self.depth < 0:
            raise ValueError("vertical close values cannot be negative")
        if self.combo_source_capture_seq is not None and self.combo_source_capture_seq <= 0:
            raise ValueError("vertical close combo source sequence must be positive")


@dataclass(frozen=True, slots=True)
class SurfaceExpirySummary:
    expiry: datetime
    atm_bid_iv: Decimal | None
    atm_ask_iv: Decimal | None
    atm_mark_iv: Decimal | None
    risk_reversal_25d: Decimal | None
    butterfly_25d: Decimal | None
    adjacent_expiry_total_variance_slope: Decimal | None
    minimum_quote_age_ms: int
    maximum_quote_age_ms: int
    quote_count: int


@dataclass(frozen=True, slots=True)
class SurfaceSummary:
    expiries: tuple[SurfaceExpirySummary, ...]
    quote_age_dispersion_ms: int | None
    source_capture_seqs: tuple[int, ...]

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class VerticalQuote:
    candidate_id: str
    frame_capture_seq: int
    sold_side: OptionKind
    expiry: datetime
    tte_seconds: int
    short_leg: OptionQuote
    long_leg: OptionQuote
    combo_id: str | None
    execution_source: str
    close_execution_source: str
    executable_entry_credit: Decimal
    executable_close_debit: Decimal
    entry_fee_usdc: Decimal
    close_fee_usdc: Decimal
    quantity: Decimal
    contract_size: Decimal
    width: Decimal
    executable_depth: Decimal
    gross_credit_usdc: Decimal
    immediate_close_usdc: Decimal
    net_entry_premium_usdc: Decimal
    round_trip_friction_usdc: Decimal
    credit_to_friction_ratio: Decimal | None
    max_profit_usdc: Decimal
    max_loss_usdc: Decimal
    short_distance_fraction: Decimal
    first_touch_level: Decimal

    def __post_init__(self) -> None:
        if self.quantity <= 0 or self.width <= 0 or self.contract_size <= 0:
            raise ValueError("vertical dimensions must be positive")
        if self.executable_entry_credit <= 0:
            raise ValueError("vertical entry credit must be positive")
        if self.executable_close_debit < 0:
            raise ValueError("vertical close debit cannot be negative")
        if self.max_loss_usdc <= 0:
            raise ValueError("vertical max loss must be positive")
        if self.short_leg.expiry != self.long_leg.expiry:
            raise ValueError("vertical legs must share expiry")
        if self.short_leg.option_kind is not self.long_leg.option_kind:
            raise ValueError("vertical legs must share option side")

    @property
    def digest(self) -> str:
        return canonical_digest(self)
