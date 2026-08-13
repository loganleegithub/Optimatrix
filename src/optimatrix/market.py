from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from optimatrix.identity import canonical_identity
from optimatrix.products import ProductId, ProductSpec


class OptionType(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class EventState(StrEnum):
    NONE = "NONE"
    PRE_EVENT = "PRE_EVENT"
    LIVE_EVENT = "LIVE_EVENT"
    POST_EVENT = "POST_EVENT"
    UNSCHEDULED_SHOCK = "UNSCHEDULED_SHOCK"


class SettlementEvidenceKind(StrEnum):
    OFFICIAL_EXCHANGE = "OFFICIAL_EXCHANGE"
    DETERMINISTIC_ACCEPTANCE_FIXTURE = "DETERMINISTIC_ACCEPTANCE_FIXTURE"


@dataclass(frozen=True)
class ExpirySettlementFact:
    """One product-level expiry settlement fact, independent of any strategy."""

    product_id: ProductId
    expiry: datetime
    delivery_price_usd: Decimal
    known_at: datetime
    evidence_kind: SettlementEvidenceKind
    source_id: str
    method_id: str

    def __post_init__(self) -> None:
        if self.expiry.tzinfo is None or self.known_at.tzinfo is None:
            raise ValueError("settlement boundaries must be timezone-aware")
        if self.known_at < self.expiry:
            raise ValueError("settlement cannot be known before expiry")
        if not self.delivery_price_usd.is_finite() or self.delivery_price_usd <= 0:
            raise ValueError("settlement delivery price must be finite and positive")
        if not self.source_id or not self.method_id:
            raise ValueError("settlement source and method must be non-empty")

    @property
    def identity(self) -> str:
        return canonical_identity("ExpirySettlementFactV1", self)

    def as_object(self) -> dict[str, object]:
        return {
            "settlement_fact_id": self.identity,
            "product_id": self.product_id.value,
            "expiry": self.expiry.isoformat(),
            "delivery_price_usd": str(self.delivery_price_usd),
            "known_at": self.known_at.isoformat(),
            "evidence_kind": self.evidence_kind.value,
            "source_id": self.source_id,
            "method_id": self.method_id,
        }

    @classmethod
    def from_object(cls, value: object) -> ExpirySettlementFact:
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise ValueError("settlement fact must be an object")
        source_id = value.get("source_id")
        method_id = value.get("method_id")
        if not isinstance(source_id, str) or not isinstance(method_id, str):
            raise ValueError("settlement source and method must be text")
        try:
            fact = cls(
                product_id=ProductId(value["product_id"]),
                expiry=datetime.fromisoformat(str(value["expiry"]).replace("Z", "+00:00")),
                delivery_price_usd=Decimal(str(value["delivery_price_usd"])),
                known_at=datetime.fromisoformat(str(value["known_at"]).replace("Z", "+00:00")),
                evidence_kind=SettlementEvidenceKind(value["evidence_kind"]),
                source_id=source_id,
                method_id=method_id,
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(f"invalid settlement fact: {exc}") from exc
        if value.get("settlement_fact_id") != fact.identity:
            raise ValueError("settlement fact identity mismatch")
        return fact


class MarketContextKnowledge(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class RealizedVarianceMethod(StrEnum):
    TRAILING_MATCHED_HORIZON_INDEX_REALIZED_VARIANCE_PROXY = (
        "TRAILING_MATCHED_HORIZON_INDEX_REALIZED_VARIANCE_PROXY"
    )
    DETERMINISTIC_MATCHED_HORIZON_REALIZED_VARIANCE_PROXY = (
        "DETERMINISTIC_MATCHED_HORIZON_REALIZED_VARIANCE_PROXY"
    )


class ImpliedVarianceMethod(StrEnum):
    NEAREST_ATM_CALL_PUT_MARK_IV_SQUARED_TIMES_RISK_HORIZON = (
        "NEAREST_ATM_CALL_PUT_MARK_IV_SQUARED_TIMES_RISK_HORIZON"
    )
    DETERMINISTIC_ATM_MARK_VARIANCE_PROXY = "DETERMINISTIC_ATM_MARK_VARIANCE_PROXY"


class EventStateSource(StrEnum):
    EXPLICIT_HUMAN_OR_EXTERNAL_CALENDAR_INPUT = "EXPLICIT_HUMAN_OR_EXTERNAL_CALENDAR_INPUT"
    DETERMINISTIC_SCENARIO_INPUT = "DETERMINISTIC_SCENARIO_INPUT"


@dataclass(frozen=True)
class MarketContextEvidence:
    """Transient proof that the numeric MarketContext has a causal public-data basis."""

    realized_variance_method: RealizedVarianceMethod | None
    implied_variance_method: ImpliedVarianceMethod | None
    event_state_source: EventStateSource | None
    required_history_start_ms: int | None
    history_coverage_start_ms: int | None
    history_coverage_end_ms: int | None
    history_cadence_ms: int | None
    market_source_min_ms: int | None
    market_source_max_ms: int | None
    market_received_min_ms: int | None
    market_received_max_ms: int | None
    event_state_known_at_ms: int | None
    maximum_market_age_ms: int
    requested_books: tuple[str, ...] = ()
    usable_books: tuple[str, ...] = ()
    declared_blockers: tuple[str, ...] = ()

    @classmethod
    def unknown(cls, *, maximum_market_age_ms: int = 5_000) -> MarketContextEvidence:
        return cls(
            realized_variance_method=None,
            implied_variance_method=None,
            event_state_source=None,
            required_history_start_ms=None,
            history_coverage_start_ms=None,
            history_coverage_end_ms=None,
            history_cadence_ms=None,
            market_source_min_ms=None,
            market_source_max_ms=None,
            market_received_min_ms=None,
            market_received_max_ms=None,
            event_state_known_at_ms=None,
            maximum_market_age_ms=maximum_market_age_ms,
        )

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.required_history_start_ms, "required_history_start_ms"),
            (self.history_coverage_start_ms, "history_coverage_start_ms"),
            (self.history_coverage_end_ms, "history_coverage_end_ms"),
            (self.history_cadence_ms, "history_cadence_ms"),
            (self.market_source_min_ms, "market_source_min_ms"),
            (self.market_source_max_ms, "market_source_max_ms"),
            (self.market_received_min_ms, "market_received_min_ms"),
            (self.market_received_max_ms, "market_received_max_ms"),
            (self.event_state_known_at_ms, "event_state_known_at_ms"),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{field_name} must be a non-negative integer when present")
        if (
            isinstance(self.maximum_market_age_ms, bool)
            or not isinstance(self.maximum_market_age_ms, int)
            or self.maximum_market_age_ms <= 0
        ):
            raise ValueError("maximum_market_age_ms must be a positive integer")
        for values, field_name in (
            (self.requested_books, "requested_books"),
            (self.usable_books, "usable_books"),
        ):
            if len(set(values)) != len(values) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"{field_name} must contain unique non-empty identities")
        if len(set(self.declared_blockers)) != len(self.declared_blockers) or any(
            not isinstance(blocker, str) or not blocker.strip()
            for blocker in self.declared_blockers
        ):
            raise ValueError("declared blockers must be unique non-empty strings")

    def blockers_at(self, *, known_at_ms: int) -> tuple[str, ...]:
        blockers: list[str] = []
        required_text = (
            (self.realized_variance_method, "REALIZED_VARIANCE_METHOD_UNKNOWN"),
            (self.implied_variance_method, "IMPLIED_VARIANCE_METHOD_UNKNOWN"),
            (self.event_state_source, "EVENT_STATE_SOURCE_UNKNOWN"),
        )
        blockers.extend(code for value, code in required_text if value is None)
        required_boundary = (
            (self.required_history_start_ms, "REQUIRED_HISTORY_START_UNKNOWN"),
            (self.history_coverage_start_ms, "HISTORY_COVERAGE_START_UNKNOWN"),
            (self.history_coverage_end_ms, "HISTORY_COVERAGE_END_UNKNOWN"),
            (self.history_cadence_ms, "HISTORY_CADENCE_UNKNOWN"),
            (self.market_source_min_ms, "MARKET_SOURCE_MIN_UNKNOWN"),
            (self.market_source_max_ms, "MARKET_SOURCE_MAX_UNKNOWN"),
            (self.market_received_min_ms, "MARKET_RECEIVED_MIN_UNKNOWN"),
            (self.market_received_max_ms, "MARKET_RECEIVED_MAX_UNKNOWN"),
            (self.event_state_known_at_ms, "EVENT_STATE_KNOWN_AT_UNKNOWN"),
        )
        blockers.extend(code for value, code in required_boundary if value is None)
        if (
            self.required_history_start_ms is not None
            and self.history_coverage_start_ms is not None
            and self.history_coverage_start_ms > self.required_history_start_ms
        ):
            blockers.append("RISK_HORIZON_COVERAGE_INCOMPLETE")
        if (
            self.history_coverage_start_ms is not None
            and self.history_coverage_end_ms is not None
            and self.history_coverage_start_ms >= self.history_coverage_end_ms
        ):
            blockers.append("HISTORY_COVERAGE_INVALID")
        if (
            self.history_coverage_end_ms is not None
            and self.history_cadence_ms is not None
            and known_at_ms - self.history_coverage_end_ms > self.history_cadence_ms * 2
        ):
            blockers.append("HISTORY_TAIL_STALE")
        if set(self.requested_books) != set(self.usable_books):
            blockers.append("SELECTION_UNIVERSE_INCOMPLETE")
        if self.history_coverage_end_ms is not None and self.history_coverage_end_ms > known_at_ms:
            blockers.append("HISTORY_COVERAGE_IN_FUTURE")
        for minimum, maximum, label in (
            (self.market_source_min_ms, self.market_source_max_ms, "MARKET_SOURCE"),
            (self.market_received_min_ms, self.market_received_max_ms, "MARKET_RECEIVED"),
        ):
            if minimum is not None and maximum is not None and minimum > maximum:
                blockers.append(f"{label}_BOUNDARY_INVALID")
            if maximum is not None and maximum > known_at_ms:
                blockers.append(f"{label}_BOUNDARY_IN_FUTURE")
            if minimum is not None and known_at_ms - minimum > self.maximum_market_age_ms:
                blockers.append(f"{label}_BOUNDARY_STALE")
        if self.event_state_known_at_ms is not None and self.event_state_known_at_ms > known_at_ms:
            blockers.append("EVENT_STATE_KNOWN_AT_IN_FUTURE")
        blockers.extend(self.declared_blockers)
        return tuple(dict.fromkeys(blockers))


@dataclass(frozen=True)
class PriceLevel:
    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("level price must be finite and positive")
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError("level quantity must be finite and positive")


@dataclass(frozen=True)
class TickStep:
    above_price: Decimal
    tick_size: Decimal


@dataclass(frozen=True)
class TickSchedule:
    base_tick: Decimal
    steps: tuple[TickStep, ...] = ()

    def __post_init__(self) -> None:
        if not self.base_tick.is_finite() or self.base_tick <= 0:
            raise ValueError("base tick must be finite and positive")
        prior = Decimal("-1")
        prior_tick = self.base_tick
        for step in self.steps:
            if (
                not step.above_price.is_finite()
                or step.above_price < 0
                or not step.tick_size.is_finite()
                or step.tick_size <= prior_tick
                or step.tick_size % self.base_tick != 0
                or step.above_price <= prior
            ):
                raise ValueError("tick steps must increase and use positive base-tick multiples")
            prior = step.above_price
            prior_tick = step.tick_size

    def tick_at(self, price: Decimal) -> Decimal:
        if not price.is_finite() or price <= 0:
            raise ValueError("price must be finite and positive")
        tick = self.base_tick
        for step in self.steps:
            if price < step.above_price:
                break
            tick = step.tick_size
        return tick

    def previous_price(self, price: Decimal) -> Decimal | None:
        if not price.is_finite() or price <= 0:
            raise ValueError("price must be finite and positive")
        regime_index = self._regime_index(price)
        lower_boundary = (
            self.steps[regime_index - 1].above_price if regime_index > 0 else Decimal(0)
        )
        current_tick = (
            self.steps[regime_index - 1].tick_size if regime_index > 0 else self.base_tick
        )
        candidate = price - current_tick
        if candidate >= lower_boundary and candidate > 0:
            return candidate
        if regime_index == 0:
            return None
        previous_tick = (
            self.steps[regime_index - 2].tick_size if regime_index > 1 else self.base_tick
        )
        candidate = lower_boundary - previous_tick
        return candidate if candidate > 0 else None

    def next_price(self, price: Decimal) -> Decimal:
        if not price.is_finite() or price <= 0:
            raise ValueError("price must be finite and positive")
        regime_index = self._regime_index(price)
        current_tick = (
            self.steps[regime_index - 1].tick_size if regime_index > 0 else self.base_tick
        )
        candidate = price + current_tick
        if regime_index < len(self.steps):
            next_boundary = self.steps[regime_index].above_price
            if price < next_boundary <= candidate:
                return next_boundary
        return candidate

    def _regime_index(self, price: Decimal) -> int:
        index = 0
        for step in self.steps:
            if price < step.above_price:
                break
            index += 1
        return index

    def tick_distance(self, lower: Decimal, upper: Decimal) -> Decimal:
        if lower <= 0 or upper < lower:
            raise ValueError("tick distance bounds are invalid")
        if lower == upper:
            return Decimal(0)
        boundaries = tuple(
            step.above_price for step in self.steps if lower < step.above_price < upper
        )
        current = lower
        distance = Decimal(0)
        for boundary in (*boundaries, upper):
            distance += (boundary - current) / self.tick_at(current)
            current = boundary
        return distance


@dataclass(frozen=True)
class OptionQuote:
    instrument_name: str
    product: ProductSpec
    expiry: datetime
    strike: Decimal
    option_type: OptionType
    signed_delta: Decimal
    mark_iv: Decimal
    bid: tuple[PriceLevel, ...]
    ask: tuple[PriceLevel, ...]
    tick_schedule: TickSchedule
    source_timestamp_ms: int
    received_timestamp_ms: int
    continuity_epoch: int
    delivery_fee_exempt: bool
    open_interest: Decimal = Decimal(0)
    gamma: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if not self.instrument_name.startswith(self.product.instrument_prefix):
            raise ValueError("instrument_name does not match product")
        if self.expiry.tzinfo is None:
            raise ValueError("expiry must be timezone-aware")
        if not self.strike.is_finite() or self.strike <= 0:
            raise ValueError("strike must be finite and positive")
        if not self.signed_delta.is_finite() or abs(self.signed_delta) > 1:
            raise ValueError("signed_delta must be finite and bounded")
        if not self.mark_iv.is_finite() or self.mark_iv <= 0:
            raise ValueError("mark_iv must be finite and positive")
        if not self.open_interest.is_finite() or self.open_interest < 0:
            raise ValueError("open_interest must be finite and non-negative")
        if not self.gamma.is_finite() or self.gamma < 0:
            raise ValueError("gamma must be finite and non-negative")
        if not isinstance(self.delivery_fee_exempt, bool):
            raise ValueError("delivery_fee_exempt must be boolean")
        if any(
            current.price > previous.price
            for previous, current in zip(self.bid, self.bid[1:], strict=False)
        ):
            raise ValueError("bid levels must be sorted from highest to lowest")
        if any(
            current.price < previous.price
            for previous, current in zip(self.ask, self.ask[1:], strict=False)
        ):
            raise ValueError("ask levels must be sorted from lowest to highest")
        if self.bid and self.ask and self.bid[0].price >= self.ask[0].price:
            raise ValueError("option quote must be uncrossed")
        for value, field_name in (
            (self.source_timestamp_ms, "source_timestamp_ms"),
            (self.received_timestamp_ms, "received_timestamp_ms"),
            (self.continuity_epoch, "continuity_epoch"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True)
class MarketContext:
    now: datetime
    index_price: Decimal
    forward_price: Decimal
    trailing_realized_variance_proxy: Decimal
    same_session_implied_variance_proxy: Decimal
    rv_acceleration: Decimal
    jump_share: Decimal
    directional_persistence: Decimal
    event_state: EventState
    concentrated_strike: Decimal | None
    concentration_strength: Decimal
    evidence: MarketContextEvidence

    def __post_init__(self) -> None:
        if self.now.tzinfo is None:
            raise ValueError("market context time must be timezone-aware")
        for value, field_name in (
            (self.index_price, "index_price"),
            (self.forward_price, "forward_price"),
            (self.trailing_realized_variance_proxy, "trailing_realized_variance_proxy"),
            (self.same_session_implied_variance_proxy, "same_session_implied_variance_proxy"),
        ):
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{field_name} must be finite and positive")
        for value, field_name in (
            (self.rv_acceleration, "rv_acceleration"),
            (self.jump_share, "jump_share"),
            (self.directional_persistence, "directional_persistence"),
            (self.concentration_strength, "concentration_strength"),
        ):
            if not value.is_finite() or value < 0 or value > 1:
                raise ValueError(f"{field_name} must be in [0, 1]")
        if self.concentrated_strike is not None and (
            not self.concentrated_strike.is_finite() or self.concentrated_strike <= 0
        ):
            raise ValueError("concentrated_strike must be positive when present")

    @property
    def evidence_blockers(self) -> tuple[str, ...]:
        return self.evidence_blockers_at(self.now)

    def evidence_blockers_at(self, known_at: datetime) -> tuple[str, ...]:
        """Evaluate evidence against one causal boundary in Deribit UTC."""

        if known_at.tzinfo is None:
            raise ValueError("market context known_at must be timezone-aware")
        normalized = known_at.astimezone(UTC)
        known_at_ms = int(normalized.timestamp()) * 1000 + normalized.microsecond // 1000
        return self.evidence.blockers_at(known_at_ms=known_at_ms)

    def knowledge_at(self, known_at: datetime) -> MarketContextKnowledge:
        return (
            MarketContextKnowledge.KNOWN
            if not self.evidence_blockers_at(known_at)
            else MarketContextKnowledge.UNKNOWN
        )

    @property
    def knowledge(self) -> MarketContextKnowledge:
        return (
            MarketContextKnowledge.KNOWN
            if not self.evidence_blockers
            else MarketContextKnowledge.UNKNOWN
        )
