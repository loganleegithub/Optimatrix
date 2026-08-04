from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from radar_runtime.funnel import FunnelTracker
from radar_runtime.observation import (
    PRECOMMITTED_STOP_REASON,
    build_radar_knownness_observation,
    request_precommitted_stop,
)
from radar_runtime.service import PersistentStopEvent


def test_precommitted_stop_reports_the_actual_request_after_the_fixed_deadline() -> None:
    event = PersistentStopEvent()
    now = 100

    def monotonic_ms() -> int:
        return now

    async def advance(seconds: float) -> None:
        nonlocal now
        now += round(seconds * 1_000) + 7

    asyncio.run(
        request_precommitted_stop(
            event,
            deadline_monotonic_ms=1_100,
            monotonic_ms=monotonic_ms,
            sleep=advance,
        )
    )

    assert event.terminal_monotonic_ms == 1_107
    assert event.reason == PRECOMMITTED_STOP_REASON


def test_observation_reports_zero_durable_files_without_shadow_admission(
    tmp_path: Path,
) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    observation = build_radar_knownness_observation(
        requested_duration_seconds=900,
        started_monotonic_ms=100,
        stop_deadline_monotonic_ms=900_100,
        terminal_monotonic_ms=900_100,
        stop_reason=PRECOMMITTED_STOP_REASON,
        terminal_summary={"object_kind": "RADAR_RUN_SUMMARY"},
        funnel=FunnelTracker().snapshot(),
        cases_directory=cases,
    )

    value = observation.as_object()
    stop_boundary = cast(Mapping[str, object], value["stop_boundary"])
    assert stop_boundary == {
        "requested_duration_seconds": 900,
        "started_monotonic_ms": 100,
        "deadline_monotonic_ms": 900_100,
        "terminal_monotonic_ms": 900_100,
        "terminal_offset_ms": 0,
        "stop_reason": PRECOMMITTED_STOP_REASON,
    }
    assert value["post_warmup_radar_known_over_applicable"] == {
        "numerator": 0,
        "denominator": 0,
        "ratio": None,
    }
    assert value["durable_shadow_case_files"] == {
        "count": 0,
        "shadow_case_opened_count": 0,
        "zero_when_no_shadow_admission": True,
    }
    assert value["anomaly_required"] is False


def test_observation_rejects_pre_shadow_business_files(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "unexpected.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="pre-Shadow observation"):
        build_radar_knownness_observation(
            requested_duration_seconds=900,
            started_monotonic_ms=100,
            stop_deadline_monotonic_ms=900_100,
            terminal_monotonic_ms=900_100,
            stop_reason=PRECOMMITTED_STOP_REASON,
            terminal_summary={"object_kind": "RADAR_RUN_SUMMARY"},
            funnel=FunnelTracker().snapshot(),
            cases_directory=cases,
        )


def test_observation_duration_is_bounded() -> None:
    cases = Path("/unused")
    with pytest.raises(ValueError, match="exactly 900"):
        build_radar_knownness_observation(
            requested_duration_seconds=86_400,
            started_monotonic_ms=0,
            stop_deadline_monotonic_ms=86_400_000,
            terminal_monotonic_ms=86_400_000,
            stop_reason=PRECOMMITTED_STOP_REASON,
            terminal_summary={"object_kind": "RADAR_RUN_SUMMARY"},
            funnel=FunnelTracker().snapshot(),
            cases_directory=cases,
        )
