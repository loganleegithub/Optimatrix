from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class SourceDataError(ValueError):
    """A consumed public-source field is missing or invalid."""


class ContinuityGap(RuntimeError):
    """A public stream can no longer prove continuous current state."""


def require_mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SourceDataError(f"{field} must be an object")
    return value


def require_list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise SourceDataError(f"{field} must be an array")
    return value


def require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceDataError(f"{field} must be a non-empty string")
    return value


def require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise SourceDataError(f"{field} must be a boolean")
    return value


def require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SourceDataError(f"{field} must be an integer")
    return value


def decimal_from_source(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise SourceDataError(f"{field} must be a decimal-compatible number")
    try:
        number = Decimal(str(value)) if not isinstance(value, Decimal) else value
    except InvalidOperation as exc:
        raise SourceDataError(f"{field} is not a valid decimal") from exc
    if not number.is_finite():
        raise SourceDataError(f"{field} must be finite")
    return number


@dataclass(frozen=True, order=True)
class TimeInterval:
    lower_ms: int
    upper_ms: int

    def __post_init__(self) -> None:
        if self.lower_ms > self.upper_ms:
            raise ValueError("time interval lower bound exceeds upper bound")

    def intersection(self, other: TimeInterval) -> TimeInterval | None:
        lower = max(self.lower_ms, other.lower_ms)
        upper = min(self.upper_ms, other.upper_ms)
        return None if lower > upper else TimeInterval(lower, upper)


@dataclass(frozen=True)
class PriceLevel:
    price: Decimal
    amount: Decimal
