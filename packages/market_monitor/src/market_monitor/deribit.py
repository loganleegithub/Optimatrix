from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from market_monitor.types import (
    SourceDataError,
    require_bool,
    require_list,
    require_mapping,
    require_str,
)


def option_lifecycle_channel(currency: str) -> str:
    if not currency:
        raise ValueError("lifecycle currency must be non-empty")
    return f"instrument.state.option.{currency}"


def combo_lifecycle_channel(currency: str) -> str:
    if not currency:
        raise ValueError("lifecycle currency must be non-empty")
    return f"instrument.state.option_combo.{currency}"


def index_channel(index_name: str) -> str:
    if not index_name:
        raise ValueError("index name must be non-empty")
    return f"deribit_price_index.{index_name}"


OPTION_LIFECYCLE_CHANNEL = option_lifecycle_channel("BTC")
COMBO_LIFECYCLE_CHANNEL = combo_lifecycle_channel("BTC")
PLATFORM_CHANNELS = ("platform_state", "platform_state.public_methods_state")
INDEX_CHANNEL = index_channel("btc_usd")
DEFAULT_SUBSCRIPTION_BATCH_SIZE = 100
MAX_BUFFERED_LIFECYCLE_EVENTS = 10_000


def ticker_channel(instrument_name: str) -> str:
    return f"ticker.{instrument_name}.agg2"


def book_channel(instrument_name: str) -> str:
    return f"book.{instrument_name}.agg2"


def subscription_batches(
    channels: Iterable[str], maximum_size: int = DEFAULT_SUBSCRIPTION_BATCH_SIZE
) -> tuple[tuple[str, ...], ...]:
    if maximum_size <= 0:
        raise ValueError("maximum_size must be positive")
    unique = tuple(dict.fromkeys(channels))
    if any(not channel for channel in unique):
        raise ValueError("subscription channels must be non-empty")
    return tuple(
        unique[index : index + maximum_size] for index in range(0, len(unique), maximum_size)
    )


def validate_subscription_ack(requested: Sequence[str], result: object) -> tuple[str, ...]:
    acknowledged = tuple(
        require_str(channel, f"subscription result[{index}]")
        for index, channel in enumerate(require_list(result, "subscription result"))
    )
    requested_channels = tuple(requested)
    acknowledged_set = set(acknowledged)
    if len(acknowledged_set) != len(acknowledged) or not acknowledged_set <= set(
        requested_channels
    ):
        raise SourceDataError("subscription acknowledgement is not a unique subset of request")
    return tuple(channel for channel in requested_channels if channel in acknowledged_set)


@dataclass
class CatalogBootstrap:
    lifecycle_acknowledged: bool = False
    buffering: bool = False
    complete: bool = False
    source_complete: bool = True
    buffered_events: list[dict[str, object]] = field(default_factory=list)

    def acknowledge_lifecycle(self) -> None:
        self.lifecycle_acknowledged = True
        self.buffering = True
        self.complete = False
        self.source_complete = True

    def begin_reconciliation(self) -> None:
        if not self.lifecycle_acknowledged:
            raise RuntimeError("lifecycle must be acknowledged before catalog reconciliation")
        if self.buffering:
            return
        self.buffering = True
        self.complete = False
        self.source_complete = True

    def accept_lifecycle(self, payload: object) -> dict[str, object] | None:
        event = require_mapping(payload, "instrument lifecycle")
        require_str(event.get("instrument_name"), "instrument lifecycle.instrument_name")
        require_str(event.get("state"), "instrument lifecycle.state")
        if self.buffering:
            if len(self.buffered_events) >= MAX_BUFFERED_LIFECYCLE_EVENTS:
                self.mark_incomplete()
                return None
            self.buffered_events.append(event)
            return None
        return event

    def reconcile(self) -> tuple[dict[str, object], ...]:
        if not self.lifecycle_acknowledged or not self.buffering:
            raise RuntimeError("lifecycle must be acknowledged before catalog reconciliation")
        events = tuple(self.buffered_events)
        self.buffered_events.clear()
        self.buffering = False
        self.complete = self.source_complete
        return events

    def mark_incomplete(self) -> None:
        self.source_complete = False
        self.complete = False


@dataclass
class PlatformReadiness:
    price_index: str = "btc_usd"
    bootstrap_epoch: int = 0
    platform_subscription_acknowledged: bool = False
    public_methods_subscription_acknowledged: bool = False
    lock_snapshot: bool | None = None
    status_usable: bool = False
    maintenance_guard: bool | None = None
    public_method_guard: bool | None = None
    post_status_probe: bool = False
    fresh_index_coverage: bool = False
    post_status_bootstrap_complete: bool = False
    maintenance: bool | None = None
    public_methods_allowed: bool | None = None
    reason: str = "PLATFORM_UNESTABLISHED"

    @property
    def usable(self) -> bool:
        return (
            self.platform_subscription_acknowledged
            and self.public_methods_subscription_acknowledged
            and self.status_usable
            and self.lock_snapshot is False
            and self.maintenance_guard is False
            and self.public_method_guard is True
            and self.post_status_probe
            and self.fresh_index_coverage
        )

    def start_epoch(self, epoch: int) -> None:
        if epoch <= 0:
            raise ValueError("platform bootstrap epoch must be positive")
        replacement = PlatformReadiness(price_index=self.price_index, bootstrap_epoch=epoch)
        self.__dict__.update(replacement.__dict__)

    def acknowledge(self, channels: Sequence[str]) -> None:
        self.platform_subscription_acknowledged = (
            self.platform_subscription_acknowledged or "platform_state" in channels
        )
        self.public_methods_subscription_acknowledged = (
            self.public_methods_subscription_acknowledged
            or "platform_state.public_methods_state" in channels
        )

    def apply_status(self, payload: object) -> None:
        status = require_mapping(payload, "public/status")
        locked = status.get("locked")
        if not (
            isinstance(locked, bool)
            or (isinstance(locked, str) and locked in {"true", "false", "partial"})
        ):
            raise SourceDataError("public/status.locked has an unsupported value")
        all_locked = locked is True or locked == "true"
        partially_locked = locked == "partial"
        locked_indices: list[object] = []
        if partially_locked:
            locked_indices = require_list(
                status.get("locked_indices"), "public/status.locked_indices"
            )
            if not all(isinstance(item, str) for item in locked_indices):
                raise SourceDataError("public/status.locked_indices must contain strings")
        relevant_locked = all_locked or self.price_index in locked_indices
        if self.lock_snapshot is not True:
            self.lock_snapshot = relevant_locked
        self.status_usable = self.lock_snapshot is False
        if self.lock_snapshot is True:
            self.reason = "RELEVANT_PLATFORM_LOCK"
        elif self.maintenance_guard is True:
            self.reason = "PLATFORM_MAINTENANCE"
        elif self.public_method_guard is False:
            self.reason = "PUBLIC_METHODS_DENIED"
        else:
            self.reason = "POST_STATUS_BOOTSTRAP_REQUIRED"
        self.post_status_bootstrap_complete = False

    def apply_platform_notification(self, payload: object) -> None:
        data = require_mapping(payload, "platform_state")
        if "maintenance" in data:
            observed = require_bool(data["maintenance"], "platform_state.maintenance")
            if self.maintenance_guard is not True:
                self.maintenance_guard = observed
                self.maintenance = observed
            if observed:
                self._invalidate("PLATFORM_MAINTENANCE")
            return
        if "price_index" in data or "locked" in data:
            price_index = require_str(data.get("price_index"), "platform_state.price_index")
            locked = require_bool(data.get("locked"), "platform_state.locked")
            if price_index == self.price_index and locked:
                self.lock_snapshot = True
                self._invalidate("RELEVANT_PLATFORM_LOCK")
            return
        else:
            raise SourceDataError(
                "platform_state lacks consumed maintenance or price_index/locked fields"
            )

    def apply_public_methods_notification(self, payload: object) -> None:
        data = require_mapping(payload, "platform_state.public_methods_state")
        allowed = require_bool(
            data.get("allow_unauthenticated_public_requests"),
            "platform_state.public_methods_state.allow_unauthenticated_public_requests",
        )
        if self.public_method_guard is not False:
            self.public_method_guard = allowed
            self.public_methods_allowed = allowed
        if not allowed:
            self._invalidate("PUBLIC_METHODS_DENIED")

    def note_post_status_probe(self) -> None:
        self.post_status_probe = True
        self._derive_completion()

    def note_fresh_index_coverage(self) -> None:
        self.fresh_index_coverage = True
        self._derive_completion()

    def invalidate_fresh_index_coverage(self, reason: str) -> None:
        self.fresh_index_coverage = False
        self.post_status_bootstrap_complete = False
        self.reason = reason

    def complete_post_status_bootstrap(self) -> None:
        self._derive_completion()
        if not self.post_status_bootstrap_complete:
            raise RuntimeError("platform facts are not all usable")

    def prove_operational_from_post_status_public_success(self) -> None:
        if not self.status_usable:
            raise RuntimeError("public/status is not usable")
        if self.maintenance_guard is None:
            self.maintenance_guard = False
            self.maintenance = False
        self.note_post_status_probe()

    def _derive_completion(self) -> None:
        self.post_status_bootstrap_complete = self.usable
        if self.usable:
            self.reason = "USABLE"

    def _invalidate(self, reason: str) -> None:
        self.status_usable = False
        self.post_status_bootstrap_complete = False
        self.reason = reason
