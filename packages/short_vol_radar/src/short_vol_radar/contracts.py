"""Finite-horizon radar contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from market_tape import OptionKind, canonical_digest
from options_domain import ComboQuote, OptionQuote, SurfaceSummary, VerticalQuote


class BreakoutDirection(StrEnum):
    NONE = "NONE"
    UP = "UP"
    DOWN = "DOWN"


class RadarAction(StrEnum):
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
    WATCH = "WATCH"
    ABSTAIN = "ABSTAIN"


@dataclass(frozen=True, slots=True)
class ScheduledBlock:
    starts_at: datetime
    ends_at: datetime
    label: str

    def __post_init__(self) -> None:
        if self.ends_at <= self.starts_at:
            raise ValueError("scheduled block must end after it starts")

    def contains(self, value: datetime) -> bool:
        return self.starts_at <= value <= self.ends_at


@dataclass(frozen=True, slots=True)
class WindowCoverage:
    requested_seconds: int
    requested_market_start_at: datetime | None
    market_as_of: datetime | None
    price_market_anchor_at: datetime | None
    price_market_endpoint_at: datetime | None
    price_market_lookback_seconds: int
    price_subscription_elapsed_seconds: int
    trade_subscription_elapsed_seconds: int
    price_watermark_progress_age_ms: int | None
    price_complete: bool
    trade_complete: bool
    gap_contaminated: bool
    reconnect_contaminated: bool
    incomplete_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.requested_seconds <= 0:
            raise ValueError("window duration must be positive")
        if (self.requested_market_start_at is None) != (self.market_as_of is None):
            raise ValueError("window market bounds must be paired")
        if (
            self.requested_market_start_at is not None
            and self.market_as_of is not None
            and self.market_as_of - self.requested_market_start_at
            != timedelta(seconds=self.requested_seconds)
        ):
            raise ValueError("window market bounds do not match requested duration")
        spans = (
            self.price_market_lookback_seconds,
            self.price_subscription_elapsed_seconds,
            self.trade_subscription_elapsed_seconds,
        )
        if any(item < 0 or item > self.requested_seconds for item in spans):
            raise ValueError("window coverage spans are invalid")
        if (
            self.price_watermark_progress_age_ms is not None
            and self.price_watermark_progress_age_ms < 0
        ):
            raise ValueError("price watermark progress age is invalid")
        if (
            self.price_market_anchor_at is not None
            and self.price_market_endpoint_at is not None
            and self.price_market_anchor_at > self.price_market_endpoint_at
        ):
            raise ValueError("price market coverage is inverted")
        if self.price_complete and (
            self.requested_market_start_at is None
            or self.market_as_of is None
            or self.price_market_anchor_at is None
            or self.price_market_endpoint_at != self.market_as_of
            or self.price_market_anchor_at > self.requested_market_start_at
            or self.price_market_lookback_seconds != self.requested_seconds
            or self.price_subscription_elapsed_seconds != self.requested_seconds
            or self.price_watermark_progress_age_ms is None
            or self.reconnect_contaminated
        ):
            raise ValueError("complete price window lacks exact coverage")
        if self.trade_complete and (
            self.market_as_of is None
            or self.trade_subscription_elapsed_seconds != self.requested_seconds
            or self.gap_contaminated
            or self.reconnect_contaminated
        ):
            raise ValueError("complete trade window lacks exact coverage")


@dataclass(frozen=True, slots=True)
class PathMetrics:
    return_fraction: Decimal
    range_fraction: Decimal
    realized_variation: Decimal
    directional_efficiency: Decimal
    maximum_up_fraction: Decimal
    maximum_down_fraction: Decimal
    maximum_step_fraction: Decimal
    breakout: BreakoutDirection


@dataclass(frozen=True, slots=True)
class FlowMetrics:
    trade_volume: Decimal
    aggressor_imbalance: Decimal
    liquidation_amount: Decimal
    liquidation_fraction: Decimal


@dataclass(frozen=True, slots=True)
class WindowObservation:
    coverage: WindowCoverage
    path: PathMetrics | None
    flow: FlowMetrics | None
    source_capture_seqs: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReferenceDynamics:
    funding_8h: Decimal | None
    funding_change: Decimal | None
    basis_fraction: Decimal | None
    basis_change: Decimal | None
    open_interest: Decimal | None
    open_interest_change_fraction: Decimal | None
    prior_reference_capture_seq: int | None

    def __post_init__(self) -> None:
        if self.prior_reference_capture_seq is not None and self.prior_reference_capture_seq <= 0:
            raise ValueError("prior reference source sequence must be positive")


@dataclass(frozen=True, slots=True)
class DecisionFrame:
    as_of_capture_seq: int
    collector_as_of: datetime
    collector_elapsed_ms: int
    market_as_of: datetime | None
    market_as_of_capture_seq: int | None
    reference_instrument: str
    reference_source_capture_seq: int | None
    reference_price: Decimal | None
    index_price: Decimal | None
    best_bid: Decimal | None
    best_ask: Decimal | None
    windows: tuple[WindowObservation, ...]
    reference_dynamics: ReferenceDynamics
    surface: SurfaceSummary
    option_quotes: tuple[OptionQuote, ...]
    combo_quotes: tuple[ComboQuote, ...]
    platform_state: str | None
    platform_locked: bool | None
    scheduled_block: str | None
    complete: bool
    completeness_reasons: tuple[str, ...]
    source_capture_seqs: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.as_of_capture_seq <= 0 or self.collector_elapsed_ms < 0:
            raise ValueError("decision frame sequence and elapsed time are invalid")
        if (self.market_as_of is None) != (self.market_as_of_capture_seq is None):
            raise ValueError("market as-of time and source sequence must be paired")
        expected_platform_lock = {None: None, "UNKNOWN": None, "OPEN": False, "LOCKED": True}
        if (
            self.platform_state not in expected_platform_lock
            or self.platform_locked is not expected_platform_lock[self.platform_state]
        ):
            raise ValueError("decision frame platform state is inconsistent")
        direct_sequences = tuple(
            item
            for item in (
                self.market_as_of_capture_seq,
                self.reference_source_capture_seq,
            )
            if item is not None
        )
        if any(item <= 0 or item > self.as_of_capture_seq for item in direct_sequences):
            raise ValueError("decision frame direct source sequence is invalid")
        if tuple(sorted(set(self.source_capture_seqs))) != self.source_capture_seqs:
            raise ValueError("decision frame source sequences must be sorted and unique")
        if any(item <= 0 or item > self.as_of_capture_seq for item in self.source_capture_seqs):
            raise ValueError("decision frame source sequence is invalid")
        required_sources = {
            self.as_of_capture_seq,
            *direct_sequences,
            *self.surface.source_capture_seqs,
            *(seq for window in self.windows for seq in window.source_capture_seqs),
            *(seq for quote in self.option_quotes for seq in quote.source_capture_seqs),
            *(quote.source_capture_seq for quote in self.combo_quotes),
            *(
                ()
                if self.reference_dynamics.prior_reference_capture_seq is None
                else (self.reference_dynamics.prior_reference_capture_seq,)
            ),
        }
        if not required_sources.issubset(self.source_capture_seqs):
            raise ValueError("decision frame provenance is incomplete")
        if self.complete and (
            self.market_as_of is None or self.reference_source_capture_seq is None
        ):
            raise ValueError("complete decision frame requires current market sources")

    @property
    def digest(self) -> str:
        return canonical_digest(self)

    def window(self, seconds: int) -> WindowObservation | None:
        return next(
            (item for item in self.windows if item.coverage.requested_seconds == seconds),
            None,
        )


@dataclass(frozen=True, slots=True)
class FiniteHorizonPathRisk:
    method_id: str
    frame_capture_seq: int
    horizon_seconds: int
    complete: bool
    base_move_fraction: Decimal | None
    up_stress_move_fraction: Decimal | None
    down_stress_move_fraction: Decimal | None
    acceleration_ratio: Decimal | None
    directional_efficiency: Decimal | None
    maximum_step_fraction: Decimal | None
    directional_flow_score: Decimal | None
    breakout: BreakoutDirection
    multiplier_terms: tuple[tuple[str, Decimal], ...]
    incomplete_reasons: tuple[str, ...]

    @property
    def digest(self) -> str:
        return canonical_digest(self)

    def adverse_move(self, sold_side: OptionKind) -> Decimal | None:
        if sold_side is OptionKind.CALL:
            return self.up_stress_move_fraction
        return self.down_stress_move_fraction


@dataclass(frozen=True, slots=True)
class PredicateResult:
    name: str
    passed: bool
    observed: str


@dataclass(frozen=True, slots=True)
class InsuranceAssessment:
    candidate: VerticalQuote
    risk: FiniteHorizonPathRisk
    adverse_move_fraction: Decimal
    safety_multiple: Decimal
    stress_intrinsic_payout_usdc: Decimal
    residual_time_value_floor_usdc: Decimal
    claim_reserve_usdc: Decimal
    liquidity_reserve_usdc: Decimal
    method_uncertainty_reserve_usdc: Decimal
    conservative_margin_usdc: Decimal
    predicates: tuple[PredicateResult, ...]

    @property
    def all_passed(self) -> bool:
        return all(item.passed for item in self.predicates)

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class RadarDecision:
    action: RadarAction
    frame_capture_seq: int
    frame_digest: str
    selected_candidate_id: str | None
    horizon_seconds: int | None
    assessment: InsuranceAssessment | None
    reason: str

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class RadarPolicy:
    horizons_seconds: tuple[int, ...] = (1_800, 3_600, 7_200, 14_400)
    required_windows_seconds: tuple[int, ...] = (60, 300, 900, 1_800, 3_600)
    quantity: Decimal = Decimal("0.04")
    minimum_tte_seconds: int = 1_800
    maximum_tte_seconds: int = 72 * 3_600
    settlement_buffer_seconds: int = 1_800
    minimum_complete_path_windows: int = 3
    minimum_credit_to_friction: Decimal = Decimal("2.5")
    minimum_safety_multiple: Decimal = Decimal("1.25")
    minimum_net_premium_to_max_loss: Decimal = Decimal("0.0025")
    liquidity_reserve_fraction: Decimal = Decimal("0.02")
    method_uncertainty_reserve_fraction: Decimal = Decimal("0.02")
    minimum_move_floor_fraction: Decimal = Decimal("0.001")
    option_freshness_ms: int = 5_000
    reference_freshness_ms: int = 2_000
    minimum_fresh_option_quotes: int = 4
    directional_flow_veto: Decimal = Decimal("0.75")
