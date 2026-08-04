from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
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

PRECOMMITTED_STOP_REASON = "PRECOMMITTED_RADAR_CANDIDATE_VALIDITY_BOUNDARY"
OBSERVATION_DURATION_SECONDS = 43_200

MonotonicClock = Callable[[], int]
AsyncSleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class RadarCandidateObservation:
    requested_duration_seconds: int
    started_monotonic_ms: int
    stop_deadline_monotonic_ms: int
    terminal_monotonic_ms: int
    stop_reason: str
    terminal_summary: Mapping[str, object]
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
        candidate_episode_count = _stage_observed_count_object(self.funnel, "ANOMALY_ACTIVE")
        activation_batch_count = _sum_scope_count(
            self.terminal_summary,
            "candidate_activation_batch_count",
        )
        no_admission = self.shadow_case_opened_count == 0
        return {
            "observation_kind": "SHORT_VOL_RADAR_CANDIDATE_VALIDITY",
            "stop_boundary": {
                "requested_duration_seconds": self.requested_duration_seconds,
                "started_monotonic_ms": self.started_monotonic_ms,
                "deadline_monotonic_ms": self.stop_deadline_monotonic_ms,
                "terminal_monotonic_ms": self.terminal_monotonic_ms,
                "terminal_offset_ms": self.terminal_monotonic_ms - self.stop_deadline_monotonic_ms,
                "stop_reason": self.stop_reason,
            },
            "post_warmup_radar_known_over_applicable": ratio,
            "radar_candidates": {
                "instrument_episode_count": candidate_episode_count,
                "temporal_activation_batch_count": activation_batch_count,
                "activation_batch_unit": (
                    "SAME_OPTION_TYPE_AND_TTE_BAND_ACTIVATIONS_AT_ONE_CAUSAL_BOUNDARY"
                ),
                "activation_batch_non_claim": "NOT_STATISTICAL_INDEPENDENCE",
                "counts_by_scope": self.terminal_summary["counts_by_scope"],
                "end_count_by_reason": self.terminal_summary["anomaly_end_count_by_reason"],
                "known_active_duration_ms_sum_by_end_reason": self.terminal_summary[
                    "known_active_duration_ms_sum_by_end_reason"
                ],
            },
            "public_atomic_quote_state_transition_count": self.terminal_summary[
                "public_atomic_quote_state_transition_count"
            ],
            "coverage": self.terminal_summary["coverage"],
            "funnel": dict(self.funnel),
            "durable_shadow_case_files": {
                "count": self.durable_shadow_case_file_count,
                "shadow_case_opened_count": self.shadow_case_opened_count,
                "zero_when_no_shadow_admission": (
                    self.durable_shadow_case_file_count == 0 if no_admission else None
                ),
            },
            "terminal_summary_identity": {
                key: self.terminal_summary[key]
                for key in ("object_kind", "code_identity", "runtime_identity", "policy_identity")
            },
            "candidate_required": False,
            "non_claims": [
                "PUBLIC_ONLY_READ_ONLY_OBSERVATION",
                "NO_FUTURE_FREQUENCY_OR_STATISTICAL_INDEPENDENCE_CLAIM",
                "NO_POLICY_EDGE_OR_PROFITABILITY_CLAIM",
                "NO_SHADOW_ADMISSION_REQUIREMENT",
                "NO_DEPLOYMENT_OR_TRADING_AUTHORITY",
            ],
        }


def build_radar_candidate_observation(
    *,
    requested_duration_seconds: int,
    started_monotonic_ms: int,
    stop_deadline_monotonic_ms: int,
    terminal_monotonic_ms: int,
    stop_reason: str,
    terminal_summary: Mapping[str, object],
    funnel: FunnelSnapshot,
    cases_directory: Path,
) -> RadarCandidateObservation:
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
        and terminal_monotonic_ms < stop_deadline_monotonic_ms
    ):
        raise ValueError("terminal boundary cannot precede the precommitted deadline")
    if not stop_reason:
        raise ValueError("stop reason must be non-empty")
    summary = _terminal_summary_projection(terminal_summary)

    snapshot = funnel.as_object()
    shadow_case_opened_count = _stage_observed_count(funnel, "SHADOW_CASE_OPENED")
    durable_files = tuple(
        path for path in cases_directory.rglob("*") if path.is_file() or path.is_symlink()
    )
    if shadow_case_opened_count == 0 and durable_files:
        raise RuntimeError("pre-Shadow observation created durable Shadow Case files")

    return RadarCandidateObservation(
        requested_duration_seconds=requested_duration_seconds,
        started_monotonic_ms=started_monotonic_ms,
        stop_deadline_monotonic_ms=stop_deadline_monotonic_ms,
        terminal_monotonic_ms=terminal_monotonic_ms,
        stop_reason=stop_reason,
        terminal_summary=summary,
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
        requested_ms = monotonic_ms()
        remaining_ms = deadline_monotonic_ms - requested_ms
        if remaining_ms <= 0:
            stop_event.request(
                terminal_monotonic_ms=requested_ms,
                reason=PRECOMMITTED_STOP_REASON,
            )
            return
        await sleep(remaining_ms / 1_000)


async def run_bounded_radar_candidate_observation(
    *,
    state_root: Path,
    process_cwd: Path,
    duration_seconds: int,
) -> tuple[PersistentServiceStartup, RadarCandidateObservation]:
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
            observation = build_radar_candidate_observation(
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


def _terminal_summary_projection(value: Mapping[str, object]) -> dict[str, object]:
    fields = (
        "object_kind",
        "code_identity",
        "runtime_identity",
        "policy_identity",
        "coverage",
        "counts_by_scope",
        "anomaly_end_count_by_reason",
        "known_active_duration_ms_sum_by_end_reason",
        "public_atomic_quote_state_transition_count",
    )
    missing = tuple(field for field in fields if field not in value)
    if missing:
        raise ValueError(f"terminal summary lacks required fields: {missing!r}")
    if value["object_kind"] != "RADAR_RUN_SUMMARY":
        raise ValueError("terminal summary must be a RADAR_RUN_SUMMARY")
    projection = {field: value[field] for field in fields}
    _sum_scope_count(projection, "candidate_activation_batch_count")
    return projection


def _sum_scope_count(summary: Mapping[str, object], field: str) -> int:
    rows = summary.get("counts_by_scope")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("terminal summary counts_by_scope must be an array")
    total = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("terminal summary scope count must be an object")
        count = row.get(field)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"terminal summary scope {field} must be non-negative")
        total += count
    return total


def _stage_observed_count(funnel: FunnelSnapshot, stage_name: str) -> int:
    for stage in funnel.stages:
        if stage.stage == stage_name:
            return stage.observed_count
    raise ValueError(f"funnel stage is absent: {stage_name}")


def _stage_observed_count_object(funnel: Mapping[str, object], stage_name: str) -> int:
    stages = funnel.get("stages")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)):
        raise ValueError("funnel stages must be an array")
    for stage in stages:
        if not isinstance(stage, Mapping) or stage.get("stage") != stage_name:
            continue
        count = stage.get("observed_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("funnel observed count must be non-negative")
        return count
    raise ValueError(f"funnel stage is absent: {stage_name}")


def _validate_duration_seconds(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("observation duration must be an integer")
    if value != OBSERVATION_DURATION_SECONDS:
        raise ValueError(
            f"observation duration must be exactly {OBSERVATION_DURATION_SECONDS} seconds"
        )


def _monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


__all__ = [
    "OBSERVATION_DURATION_SECONDS",
    "PRECOMMITTED_STOP_REASON",
    "RadarCandidateObservation",
    "build_radar_candidate_observation",
    "request_precommitted_stop",
    "run_bounded_radar_candidate_observation",
]
