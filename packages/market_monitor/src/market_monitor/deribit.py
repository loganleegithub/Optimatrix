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

OPTION_LIFECYCLE_CHANNEL = "instrument.state.option.USDC"
COMBO_LIFECYCLE_CHANNEL = "instrument.state.option_combo.USDC"
PLATFORM_CHANNELS = ("platform_state", "platform_state.public_methods_state")
INDEX_CHANNEL = "deribit_price_index.btc_usdc"
HEARTBEAT_INTERVAL_SECONDS = 30
LIVENESS_DEADLINE_SECONDS = 60
DEFAULT_SUBSCRIPTION_BATCH_SIZE = 100
MAX_BUFFERED_LIFECYCLE_EVENTS = 10_000


def ticker_channel(instrument_name: str) -> str:
    return f"ticker.{instrument_name}.100ms"


def book_channel(instrument_name: str) -> str:
    return f"book.{instrument_name}.100ms"


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


def validate_subscription_ack(requested: Sequence[str], result: object) -> None:
    acknowledged = require_list(result, "subscription result")
    if acknowledged != list(requested):
        raise SourceDataError("subscription acknowledgement does not exactly match request")


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

    def invalidate(self) -> None:
        self.lifecycle_acknowledged = False
        self.buffering = False
        self.complete = False
        self.source_complete = False
        self.buffered_events.clear()


@dataclass
class PlatformReadiness:
    platform_subscription_acknowledged: bool = False
    public_methods_subscription_acknowledged: bool = False
    status_usable: bool = False
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
            and self.post_status_bootstrap_complete
            and self.maintenance is False
            and self.public_methods_allowed is True
        )

    def acknowledge(self, channels: Sequence[str]) -> None:
        self.platform_subscription_acknowledged = "platform_state" in channels
        self.public_methods_subscription_acknowledged = (
            "platform_state.public_methods_state" in channels
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
        relevant_locked = all_locked or "btc_usdc" in locked_indices
        self.status_usable = not relevant_locked
        self.reason = (
            "RELEVANT_PLATFORM_LOCK" if relevant_locked else "POST_STATUS_BOOTSTRAP_REQUIRED"
        )
        self.post_status_bootstrap_complete = False

    def apply_platform_notification(self, payload: object) -> None:
        data = require_mapping(payload, "platform_state")
        if "maintenance" in data:
            self.maintenance = require_bool(data["maintenance"], "platform_state.maintenance")
            if self.maintenance:
                self._invalidate("PLATFORM_MAINTENANCE")
            return
        if "price_index" in data or "locked" in data:
            price_index = require_str(data.get("price_index"), "platform_state.price_index")
            locked = require_bool(data.get("locked"), "platform_state.locked")
            if price_index == "btc_usdc" and locked:
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
        self.public_methods_allowed = allowed
        if not allowed:
            self._invalidate("PUBLIC_METHODS_DENIED")

    def complete_post_status_bootstrap(self) -> None:
        if not self.status_usable:
            raise RuntimeError("public/status is not usable")
        if self.public_methods_allowed is not True:
            raise RuntimeError("public methods state is not usable")
        if self.maintenance is not False:
            raise RuntimeError("platform maintenance state is not usable")
        self.post_status_bootstrap_complete = True
        self.reason = "USABLE"

    def prove_operational_from_post_status_public_success(self) -> None:
        if not self.status_usable:
            raise RuntimeError("public/status is not usable")
        self.maintenance = False

    def _invalidate(self, reason: str) -> None:
        self.status_usable = False
        self.post_status_bootstrap_complete = False
        self.reason = reason
