"""Future-only Shadow position and outcome contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from market_tape import canonical_digest
from options_domain import VerticalQuote


class OutcomeStatus(StrEnum):
    CLOSED = "CLOSED"
    UNEXITABLE = "UNEXITABLE"
    OPEN = "OPEN"


class ExitReason(StrEnum):
    PROFIT_TARGET = "PROFIT_TARGET"
    FIRST_TOUCH = "FIRST_TOUCH"
    HORIZON = "HORIZON"
    DATA_END = "DATA_END"
    UNEXITABLE_AT_HORIZON = "UNEXITABLE_AT_HORIZON"


@dataclass(frozen=True, slots=True)
class ShadowPolicy:
    profit_close_fraction: Decimal = Decimal("0.50")


@dataclass(frozen=True, slots=True)
class ShadowPosition:
    decision_digest: str
    frame_digest: str
    entry_capture_seq: int
    entry_at: datetime
    entry_elapsed_ms: int
    entry_reference_price: Decimal
    horizon_seconds: int
    structure: VerticalQuote

    def __post_init__(self) -> None:
        if self.entry_capture_seq != self.structure.frame_capture_seq:
            raise ValueError("position entry frame and structure frame differ")
        if self.entry_elapsed_ms < 0:
            raise ValueError("position entry elapsed time cannot be negative")
        if self.horizon_seconds <= 0 or self.entry_reference_price <= 0:
            raise ValueError("position horizon and entry price must be positive")

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class OutcomePoint:
    frame_capture_seq: int
    as_of: datetime
    observed_elapsed_ms: int
    reference_price: Decimal | None
    close_debit: Decimal | None
    close_fee_usdc: Decimal | None
    executable_depth: Decimal | None
    short_delta: Decimal | None
    source_capture_seqs: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.observed_elapsed_ms < 0:
            raise ValueError("outcome elapsed time cannot be negative")
        if self.source_capture_seqs != tuple(sorted(set(self.source_capture_seqs))):
            raise ValueError("outcome lineage must be sorted and unique")
        if any(item <= 0 or item > self.frame_capture_seq for item in self.source_capture_seqs):
            raise ValueError("outcome lineage exceeds its frame")


@dataclass(frozen=True, slots=True)
class OutcomePath:
    position_digest: str
    entry_capture_seq: int
    points: tuple[OutcomePoint, ...]

    def __post_init__(self) -> None:
        if any(item.frame_capture_seq <= self.entry_capture_seq for item in self.points):
            raise ValueError("OutcomePath may contain only facts after entry")
        if any(
            source_capture_seq <= self.entry_capture_seq
            for point in self.points
            for source_capture_seq in point.source_capture_seqs
        ):
            raise ValueError("OutcomePath lineage may contain only facts after entry")
        if any(
            left.frame_capture_seq >= right.frame_capture_seq
            for left, right in zip(self.points, self.points[1:], strict=False)
        ):
            raise ValueError("OutcomePath points must be ordered by capture sequence")
        if any(
            left.observed_elapsed_ms > right.observed_elapsed_ms
            for left, right in zip(self.points, self.points[1:], strict=False)
        ):
            raise ValueError("OutcomePath elapsed time must be nondecreasing")

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class MaturedOutcome:
    position_digest: str
    outcome_path_digest: str
    status: OutcomeStatus
    exit_reason: ExitReason
    exit_capture_seq: int | None
    holding_seconds: int
    close_debit_usdc: Decimal | None
    total_fee_usdc: Decimal
    objective_usdc: Decimal | None
    maximum_up_fraction: Decimal | None
    maximum_down_fraction: Decimal | None
    first_touch_capture_seq: int | None
    time_to_touch_seconds: int | None
    max_loss_region: bool | None

    @property
    def digest(self) -> str:
        return canonical_digest(self)
