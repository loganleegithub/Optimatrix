from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from radar_runtime.funnel import FunnelSnapshot
from radar_runtime.identity import git_repository_root
from radar_runtime.service import (
    PersistentServiceStartup,
    PersistentStopEvent,
    SingleInstanceLease,
    _prepare_state_root,
    build_persistent_service_composition,
    prepare_persistent_service_startup,
    run_persistent_service_composition,
)

PRECOMMITTED_STOP_REASON = "PRECOMMITTED_RADAR_KNOWNNESS_BOUNDARY"
MAX_BOUNDED_OBSERVATION_SECONDS = 3_600

MonotonicClock = Callable[[], int]
AsyncSleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class RadarKnownnessObservation:
    requested_duration_seconds: int
    started_monotonic_ms: int
    stop_deadline_monotonic_ms: int
    terminal_monotonic_ms: int
    stop_reason: str
    terminal_summary_kind: str
    funnel: Mapping[str, object]
    durable_shadow_case_file_count: int
    shadow_case_opened_count: int

    def as_object(self) -> dict[str, object]:
        knownness = self.funnel.get("radar_knownness")
        post_warmup = knownness.get("post_warmup") if isinstance(knownness, Mapping) else None
        ratio = (
            post_warmup.get("radar_known_over_applicable")
            if isinstance(post_warmup, Mapping)
            else None
        )
        no_admission = self.shadow_case_opened_count == 0
        return {
            "observation_kind": "SHORT_VOL_RADAR_STEADY_STATE_KNOWNNESS",
            "stop_boundary": {
                "requested_duration_seconds": self.requested_duration_seconds,
                "started_monotonic_ms": self.started_monotonic_ms,
                "deadline_monotonic_ms": self.stop_deadline_monotonic_ms,
                "terminal_monotonic_ms": self.terminal_monotonic_ms,
                "stop_reason": self.stop_reason,
                "precommitted_boundary_reached": (
                    self.stop_reason == PRECOMMITTED_STOP_REASON
                    and self.terminal_monotonic_ms == self.stop_deadline_monotonic_ms
                ),
            },
            "post_warmup_radar_known_over_applicable": ratio,
            "funnel": dict(self.funnel),
            "durable_shadow_case_files": {
                "count": self.durable_shadow_case_file_count,
                "shadow_case_opened_count": self.shadow_case_opened_count,
                "zero_when_no_shadow_admission": (
                    self.durable_shadow_case_file_count == 0 if no_admission else None
                ),
            },
            "terminal_summary_kind": self.terminal_summary_kind,
            "anomaly_required": False,
            "non_claims": [
                "PUBLIC_ONLY_READ_ONLY_OBSERVATION",
                "NO_POLICY_OR_UNIVERSE_CHANGE",
                "NO_ANOMALY_FREQUENCY_CLAIM",
                "NO_SHADOW_ADMISSION_REQUIREMENT",
                "NO_DEPLOYMENT_OR_TRADING_AUTHORITY",
            ],
        }


def build_radar_knownness_observation(
    *,
    requested_duration_seconds: int,
    started_monotonic_ms: int,
    stop_deadline_monotonic_ms: int,
    terminal_monotonic_ms: int,
    stop_reason: str,
    terminal_summary: Mapping[str, object],
    funnel: FunnelSnapshot,
    cases_directory: Path,
) -> RadarKnownnessObservation:
    _validate_duration_seconds(requested_duration_seconds)
    for value, field in (
        (started_monotonic_ms, "started_monotonic_ms"),
        (stop_deadline_monotonic_ms, "stop_deadline_monotonic_ms"),
        (terminal_monotonic_ms, "terminal_monotonic_ms"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")
    if stop_deadline_monotonic_ms < started_monotonic_ms:
        raise ValueError("stop deadline cannot precede observation start")
    if terminal_monotonic_ms < started_monotonic_ms:
        raise ValueError("terminal boundary cannot precede observation start")
    if (
        stop_reason == PRECOMMITTED_STOP_REASON
        and terminal_monotonic_ms != stop_deadline_monotonic_ms
    ):
        raise ValueError("precommitted stop must preserve the exact fixed deadline")
    if not stop_reason:
        raise ValueError("stop reason must be non-empty")
    terminal_kind = terminal_summary.get("object_kind")
    if not isinstance(terminal_kind, str) or not terminal_kind:
        raise ValueError("terminal summary must name its object kind")

    snapshot = funnel.as_object()
    shadow_case_opened_count = _stage_observed_count(funnel, "SHADOW_CASE_OPENED")
    durable_files = tuple(
        path for path in cases_directory.rglob("*") if path.is_file() or path.is_symlink()
    )
    if shadow_case_opened_count == 0 and durable_files:
        raise RuntimeError("pre-Shadow observation created durable Shadow Case files")

    return RadarKnownnessObservation(
        requested_duration_seconds=requested_duration_seconds,
        started_monotonic_ms=started_monotonic_ms,
        stop_deadline_monotonic_ms=stop_deadline_monotonic_ms,
        terminal_monotonic_ms=terminal_monotonic_ms,
        stop_reason=stop_reason,
        terminal_summary_kind=terminal_kind,
        funnel=snapshot,
        durable_shadow_case_file_count=len(durable_files),
        shadow_case_opened_count=shadow_case_opened_count,
    )


async def request_precommitted_stop(
    stop_event: PersistentStopEvent,
    *,
    deadline_monotonic_ms: int,
    monotonic_ms: MonotonicClock,
    sleep: AsyncSleep = asyncio.sleep,
) -> None:
    if isinstance(deadline_monotonic_ms, bool) or not isinstance(deadline_monotonic_ms, int):
        raise TypeError("precommitted stop deadline must be an integer")
    if deadline_monotonic_ms < 0:
        raise ValueError("precommitted stop deadline must be non-negative")
    while not stop_event.is_set():
        remaining_ms = deadline_monotonic_ms - monotonic_ms()
        if remaining_ms <= 0:
            stop_event.request(
                terminal_monotonic_ms=deadline_monotonic_ms,
                reason=PRECOMMITTED_STOP_REASON,
            )
            return
        await sleep(remaining_ms / 1_000)


async def run_bounded_radar_knownness_observation(
    *,
    state_root: Path,
    process_cwd: Path,
    duration_seconds: int,
) -> tuple[PersistentServiceStartup, RadarKnownnessObservation]:
    _validate_duration_seconds(duration_seconds)
    repository = git_repository_root(process_cwd)
    resolved_state_root = _prepare_state_root(state_root, repository)
    clock = _monotonic_ms

    with SingleInstanceLease(resolved_state_root):
        startup = prepare_persistent_service_startup(
            state_root=resolved_state_root,
            process_cwd=repository,
            workbench_host="127.0.0.1",
            workbench_port=0,
        )
        composition = build_persistent_service_composition(startup)
        stop_event = PersistentStopEvent()
        deadline_ms = startup.startup_monotonic_ms + duration_seconds * 1_000
        stop_task = asyncio.create_task(
            request_precommitted_stop(
                stop_event,
                deadline_monotonic_ms=deadline_ms,
                monotonic_ms=clock,
            )
        )
        try:
            terminal_summary = await run_persistent_service_composition(
                composition,
                stop_event=stop_event,
                monotonic_ms=clock,
                start_workbench=False,
            )
            terminal_ms = stop_event.terminal_monotonic_ms
            stop_reason = stop_event.reason
            if terminal_ms is None or stop_reason is None:
                raise RuntimeError("bounded observation ended without a terminal stop boundary")
            observation = build_radar_knownness_observation(
                requested_duration_seconds=duration_seconds,
                started_monotonic_ms=startup.startup_monotonic_ms,
                stop_deadline_monotonic_ms=deadline_ms,
                terminal_monotonic_ms=terminal_ms,
                stop_reason=stop_reason,
                terminal_summary=terminal_summary,
                funnel=composition.publisher.funnel_snapshot,
                cases_directory=startup.cases_directory,
            )
            return startup, observation
        finally:
            stop_task.cancel()
            with suppress(asyncio.CancelledError):
                await stop_task
            composition.workbench.close()


def _stage_observed_count(funnel: FunnelSnapshot, stage_name: str) -> int:
    for stage in funnel.stages:
        if stage.stage == stage_name:
            return stage.observed_count
    raise ValueError(f"funnel stage is absent: {stage_name}")


def _validate_duration_seconds(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("observation duration must be an integer")
    if not 1 <= value <= MAX_BOUNDED_OBSERVATION_SECONDS:
        raise ValueError(
            f"observation duration must be between 1 and {MAX_BOUNDED_OBSERVATION_SECONDS} seconds"
        )


def _monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


__all__ = [
    "MAX_BOUNDED_OBSERVATION_SECONDS",
    "PRECOMMITTED_STOP_REASON",
    "RadarKnownnessObservation",
    "build_radar_knownness_observation",
    "request_precommitted_stop",
    "run_bounded_radar_knownness_observation",
]
