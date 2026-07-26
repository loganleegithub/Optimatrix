from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import pytest

type OptionPayloadFactory = Callable[..., dict[str, object]]


class PolicyFactory(Protocol):
    def __call__(
        self,
        target: float = 0.1,
        activation: float = 1.2,
        activation_count: int = 2,
        clear_count: int = 2,
        separation_ms: int = 1_000,
        ticker_source_stale_deadline_ms: int = 5_000,
    ) -> tuple[bytes, str]: ...


def policy_document(
    *,
    target: float = 0.1,
    activation: float = 1.2,
    activation_count: int = 2,
    clear_count: int = 2,
    separation_ms: int = 1_000,
    ticker_source_stale_deadline_ms: int = 5_000,
) -> dict[str, object]:
    rule = {
        "abs_delta_min": 0.05,
        "abs_delta_max": 0.6,
        "activation_ratio": activation,
        "clear_ratio": 0.9,
        "activation_observation_count": activation_count,
        "clear_observation_count": clear_count,
        "minimum_separation_ms": separation_ms,
    }
    return {
        "policy_schema_version": 3,
        "policy_family": "POINTWISE_EXECUTABLE_IV_RICHNESS_BASELINE",
        "target_base_quantity_btc": target,
        "runtime_limits": {
            "heartbeat_interval_seconds": 30,
            "session_liveness_deadline_ms": 60_000,
            "rpc_deadline_ms": 30_000,
            "clock_refresh_interval_ms": 30_000,
            "clock_stale_deadline_ms": 60_000,
            "index_source_stale_deadline_ms": 90_000,
            "ticker_source_stale_deadline_ms": ticker_source_stale_deadline_ms,
            "notification_queue_lag_deadline_ms": 1_000,
            "time_boundary_poll_interval_ms": 1_000,
        },
        "tte_bands": [
            {
                "band_id": "settlement-clear-to-six-hours",
                "lower_bound_minutes": 30,
                "upper_bound_minutes": 360,
                "lookbacks_minutes": [2, 5],
                "lookback_weights": [0.25, 0.75],
                "annualized_variance_floor": 0.01,
                "option_rules": {"call": rule, "put": dict(rule)},
            },
            {
                "band_id": "six-to-seventy-two-hours",
                "lower_bound_minutes": 360,
                "upper_bound_minutes": 4_320,
                "lookbacks_minutes": [5],
                "lookback_weights": [1],
                "annualized_variance_floor": 0.02,
                "option_rules": {"call": dict(rule), "put": dict(rule)},
            },
        ],
    }


def encode_policy(document: dict[str, object]) -> tuple[bytes, str]:
    exact = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    return exact, f"sha256:{hashlib.sha256(exact).hexdigest()}"


@pytest.fixture
def policy_factory() -> PolicyFactory:
    def factory(
        target: float = 0.1,
        activation: float = 1.2,
        activation_count: int = 2,
        clear_count: int = 2,
        separation_ms: int = 1_000,
        ticker_source_stale_deadline_ms: int = 5_000,
    ) -> tuple[bytes, str]:
        return encode_policy(
            policy_document(
                target=target,
                activation=activation,
                activation_count=activation_count,
                clear_count=clear_count,
                separation_ms=separation_ms,
                ticker_source_stale_deadline_ms=ticker_source_stale_deadline_ms,
            )
        )

    return factory


@pytest.fixture
def option_payload_factory() -> OptionPayloadFactory:
    def factory(
        *,
        name: str = "BTC_USDC-TEST-110000-C",
        expiry: int = 10_000_000,
        strike: int = 110_000,
        option_type: str = "call",
        step: float | None = 0.1,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "instrument_name": name,
            "kind": "option",
            "base_currency": "BTC",
            "quote_currency": "USDC",
            "settlement_currency": "USDC",
            "counter_currency": "USDC",
            "price_index": "btc_usdc",
            "instrument_type": "linear",
            "is_active": True,
            "state": "open",
            "option_type": option_type,
            "expiration_timestamp": expiry,
            "strike": strike,
            "contract_size": 1,
            "min_trade_amount": 0.1,
            "unrelated_future_field": "tolerated",
        }
        if step is not None:
            payload["qty_tick_size"] = step
        return payload

    return factory


@pytest.fixture
def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]
