from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from radar_runtime.funnel import FunnelTracker
from radar_runtime.observation import (
    PRECOMMITTED_STOP_REASON,
    build_radar_candidate_observation,
    request_precommitted_stop,
)
from radar_runtime.service import PersistentStopEvent


def _summary(*, batch_count: int = 0) -> dict[str, object]:
    return {
        "object_kind": "RADAR_RUN_SUMMARY",
        "code_identity": "a" * 40,
        "runtime_identity": "sha256:" + "b" * 64,
        "policy_identity": "sha256:" + "c" * 64,
        "coverage": {"observation_interval_ms": 43_200_000},
        "counts_by_scope": [
            {
                "option_type": "call",
                "tte_band_id": "band",
                "candidate_activation_batch_count": batch_count,
            }
        ],
        "anomaly_end_count_by_reason": {"CLEAR": 0, "CENSORED_AT_STOP": 0},
        "known_active_duration_ms_sum_by_end_reason": {
            "CLEAR": 0,
            "CENSORED_AT_STOP": 0,
        },
        "public_atomic_quote_state_transition_count": {},
    }


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


def test_observation_reports_candidate_batches_and_zero_pre_shadow_files(
    tmp_path: Path,
) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    observation = build_radar_candidate_observation(
        requested_duration_seconds=43_200,
        started_monotonic_ms=100,
        stop_deadline_monotonic_ms=43_200_100,
        terminal_monotonic_ms=43_200_100,
        stop_reason=PRECOMMITTED_STOP_REASON,
        terminal_summary=_summary(batch_count=2),
        funnel=FunnelTracker().snapshot(),
        cases_directory=cases,
    )

    value = observation.as_object()
    stop_boundary = cast(Mapping[str, object], value["stop_boundary"])
    assert stop_boundary == {
        "requested_duration_seconds": 43_200,
        "started_monotonic_ms": 100,
        "deadline_monotonic_ms": 43_200_100,
        "terminal_monotonic_ms": 43_200_100,
        "terminal_offset_ms": 0,
        "stop_reason": PRECOMMITTED_STOP_REASON,
    }
    candidates = cast(Mapping[str, object], value["radar_candidates"])
    assert candidates["instrument_episode_count"] == 0
    assert candidates["temporal_activation_batch_count"] == 2
    assert candidates["activation_batch_non_claim"] == "NOT_STATISTICAL_INDEPENDENCE"
    assert value["durable_shadow_case_files"] == {
        "count": 0,
        "shadow_case_opened_count": 0,
        "zero_when_no_shadow_admission": True,
    }
    assert value["candidate_required"] is False


def test_observation_rejects_pre_shadow_business_files(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "unexpected.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="pre-Shadow observation"):
        build_radar_candidate_observation(
            requested_duration_seconds=43_200,
            started_monotonic_ms=100,
            stop_deadline_monotonic_ms=43_200_100,
            terminal_monotonic_ms=43_200_100,
            stop_reason=PRECOMMITTED_STOP_REASON,
            terminal_summary=_summary(),
            funnel=FunnelTracker().snapshot(),
            cases_directory=cases,
        )


def test_observation_duration_is_exactly_the_authorized_boundary() -> None:
    with pytest.raises(ValueError, match="exactly 43200"):
        build_radar_candidate_observation(
            requested_duration_seconds=43_199,
            started_monotonic_ms=0,
            stop_deadline_monotonic_ms=43_199_000,
            terminal_monotonic_ms=43_199_000,
            stop_reason=PRECOMMITTED_STOP_REASON,
            terminal_summary=_summary(),
            funnel=FunnelTracker().snapshot(),
            cases_directory=Path("/unused"),
        )
