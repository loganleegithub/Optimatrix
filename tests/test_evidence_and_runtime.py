from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
import radar_runtime.runtime as runtime_module
import short_vol_radar.evidence as evidence_module
from conftest import PolicyFactory
from market_monitor import (
    PriceLevel,
    TimeInterval,
)
from radar_runtime.deribit_public import (
    ConnectionControlReason,
    DeribitPublicClient,
    InboundEnvelope,
    PublicSessionError,
    SendControlEvent,
)
from radar_runtime.identity import (
    StartupGuardError,
    prepare_evidence_directory,
    validate_clean_git_outputs,
)
from radar_runtime.runtime import (
    CausalCause,
    CausalCommit,
    CausalEffect,
    CoverageLedger,
    FactBoundary,
    FailureScope,
    LiveRadarRuntime,
    ScopeCounts,
)
from short_vol_radar.atomic import (
    AtomicMatch,
    AtomicQuote,
    ComboOrderDirection,
    PublicAtomicQuoteState,
)
from short_vol_radar.baseline import BaselineResult
from short_vol_radar.black import DecimalInterval, TotalVolatilityInterval
from short_vol_radar.detector import (
    DetectorCoverage,
    EpisodeEndReason,
)
from short_vol_radar.evidence import (
    CHANNEL_CLASSES,
    CORE_SOURCE_NAMES,
    AnomalyEvidence,
    AtomicEvidence,
    CoverageBlockingGroup,
    CoverageSegment,
    CoverageState,
    EvidenceError,
    EvidenceWriter,
    operational_soak_window_accounting,
    project_anomaly_event,
    project_atomic_event,
    project_run_summary,
    ratio_or_none,
    sealed_version_five_operational_soak_window_accounting,
    validate_anomaly_event,
    validate_atomic_event,
    validate_evidence_directory,
    validate_legacy_evidence_directory,
    validate_legacy_run_summary,
    validate_run_summary,
    validate_sealed_operational_run_summary,
    validate_sealed_version_five_evidence_directory,
    validate_sealed_version_five_run_summary,
    validate_sealed_version_four_evidence_directory,
    validate_sealed_version_four_run_summary,
)
from short_vol_radar.policy import OptionRule, load_policy_bytes


def anomaly_evidence() -> AnomalyEvidence:
    rule = OptionRule(
        Decimal("0.05"),
        Decimal("0.6"),
        Decimal("1.2"),
        Decimal("0.9"),
        1,
        1,
        0,
    )
    return AnomalyEvidence(
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
        episode_identity="episode",
        causal_seq=10,
        instrument_name="SHORT",
        expiration_timestamp_ms=10_000,
        option_type="call",
        activation_band_id="band",
        aggregate_coverage=DetectorCoverage.COMPLETE,
        target_base_quantity_btc=Decimal("0.1"),
        rule=rule,
        baseline=BaselineResult(
            ((5, Decimal("0.0001")),),
            Decimal("0.0001"),
            Decimal("0.2"),
            Decimal("0.001"),
            Decimal("0.002"),
        ),
        trusted_time=TimeInterval(1_000, 1_001),
        remaining_life_years=DecimalInterval(Decimal("0.01"), Decimal("0.011")),
        consumed_bid_levels=(PriceLevel(Decimal("1"), Decimal("0.1")),),
        forward_usdc=Decimal(100),
        strike_usdc=Decimal(110),
        executable_sell_price_usdc=Decimal(1),
        total_volatility=TotalVolatilityInterval(Decimal("0.1"), Decimal("0.1001")),
        executable_bid_iv=DecimalInterval(Decimal("0.5"), Decimal("0.51")),
        delta=DecimalInterval(Decimal("0.2"), Decimal("0.21")),
        implied_total_variance=DecimalInterval(Decimal("0.01"), Decimal("0.0101")),
        richness=DecimalInterval(Decimal("2.5"), Decimal("2.55")),
    )


def atomic_evidence() -> AtomicEvidence:
    quote = AtomicQuote(
        match=AtomicMatch("COMBO", "LONG", Decimal("0.1"), ComboOrderDirection.BUY),
        consumed_levels=(PriceLevel(Decimal("-5"), Decimal("0.1")),),
        required_side_vwap_usdc_per_btc=Decimal("-5"),
        gross_entry_credit_usdc=Decimal("0.5"),
    )
    return AtomicEvidence(
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
        episode_identity="episode",
        anomaly_activation_seq=10,
        detector_causal_seq=11,
        quote_causal_seq=11,
        short_instrument_name="SHORT",
        combo_legs=(("SHORT", Decimal(-1)), ("LONG", Decimal(1))),
        quote=quote,
        target_base_quantity_btc=Decimal("0.1"),
        source_timestamp_ms=2_000,
    )


def summary_object(
    *,
    runtime_identity: str = "runtime",
    segments: tuple[CoverageSegment, ...] = (
        CoverageSegment(
            0,
            10,
            CoverageState.UNKNOWN,
            reason="RUNTIME_START",
            blocking_reason="RUNTIME_START_PENDING",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.KNOWN_COMPLETE,
            reason="TICKER_APPLIED",
            blocking_reason="NONE",
            affected_scopes=("OPTION:SHORT",),
            global_continuity_epoch=1,
        ),
    ),
) -> dict[str, object]:
    return project_run_summary(
        code_identity="a" * 40,
        runtime_identity=runtime_identity,
        policy_identity="sha256:" + "b" * 64,
        coverage_segments=segments,
        band_suspended_duration_ms=0,
        counts_by_scope=[],
        detector_unknown_transition_count_by_reason={"WARMUP": 1},
        anomaly_end_count_by_reason={EpisodeEndReason.CLEAR: 0},
        known_active_duration_ms_sum_by_end_reason={EpisodeEndReason.CLEAR: 0},
        public_atomic_quote_state_transition_count={},
        operational_diagnostics=current_operational_diagnostics(),
    )


def operational_diagnostics(*, observation_ms: int = 20) -> dict[str, object]:
    return {
        "operational_diagnostics_schema_version": 2,
        "runtime_limits": {
            "heartbeat_interval_seconds": 30,
            "session_liveness_deadline_ms": 60_000,
            "rpc_deadline_ms": 30_000,
            "clock_refresh_interval_ms": 30_000,
            "clock_stale_deadline_ms": 60_000,
            "index_source_stale_deadline_ms": 90_000,
            "ticker_source_stale_deadline_ms": 5_000,
            "notification_queue_lag_deadline_ms": 1_000,
            "time_boundary_poll_interval_ms": 1_000,
        },
        "ingress": {
            "received_envelope_count": 0,
            "reduced_envelope_count": 0,
            "ingress_gap_or_duplicate_count": 0,
            "queue_high_water_frames": 0,
            "max_receive_to_reduce_lag_ms": 0,
            "overflow_count": 0,
        },
        "rpc_by_method": [],
        "channel_by_class": [
            {
                "channel_class": channel_class,
                "received_count": 0,
                "processed_count": 0,
                "received_rate_per_second": None if observation_ms == 0 else "0",
                "processed_rate_per_second": None if observation_ms == 0 else "0",
            }
            for channel_class in CHANNEL_CLASSES
        ],
        "subscriptions": {
            "current_subscribed_instrument_count": 0,
            "peak_subscribed_instrument_count": 0,
            "current_subscribed_channel_count": 0,
            "peak_subscribed_channel_count": 0,
        },
        "heartbeat": {
            "test_request_count": 0,
            "public_test_success_count": 0,
            "public_test_error_count": 0,
            "latency_observation_count": 0,
            "latency_ms_sum": 0,
            "latency_ms_max": 0,
        },
        "recovery": {
            "reconnect_count": 0,
            "session_gap_count": 0,
            "index_gap_count": 0,
            "index_resubscribe_count": 0,
            "option_channel_resync_count": 0,
            "clock_refresh_attempt_count": 0,
            "clock_refresh_success_count": 0,
            "clock_refresh_failure_count": 0,
            "option_catalog_refresh_attempt_count": 0,
            "option_catalog_refresh_success_count": 0,
            "option_catalog_refresh_failure_count": 0,
            "combo_authoritative_refresh_attempt_count": 0,
            "combo_authoritative_refresh_success_count": 0,
            "combo_authoritative_refresh_failure_count": 0,
        },
        "source_shapes": [
            {
                "source": source,
                "observed_count": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "validation": "NOT_OBSERVED",
                "consumed_fields": [],
            }
            for source in CORE_SOURCE_NAMES
        ],
        "witness": {
            "first_joint_witness_monotonic_ms": None,
            "continuous_covered_after_witness_ms": None,
        },
    }


def current_operational_diagnostics(*, observation_ms: int = 20) -> dict[str, object]:
    diagnostics = operational_diagnostics(observation_ms=observation_ms)
    diagnostics["operational_diagnostics_schema_version"] = 6
    ingress = diagnostics["ingress"]
    assert isinstance(ingress, dict)
    ingress["send_control_event_count"] = 0
    ingress["connection_error_event_count"] = 0
    diagnostics["global_continuity"] = {
        "current_epoch": 1,
        "restart_count": 0,
        "restart_count_by_reason": {},
        "restart_edges": [],
        "recovery_edges": [],
        "current_epoch_joint_evaluation_count_by_scope": [],
    }
    diagnostics["rpc_orphan_late_wire_count"] = 0
    diagnostics["transport_terminal_attribution"] = []
    diagnostics["ticker_application"] = {
        "disposition_count": {
            "APPLIED": 0,
            "LATE_IGNORED": 0,
            "AHEAD_IGNORED": 0,
            "STALE_GENERATION_IGNORED": 0,
            "SHAPE_REJECTED": 0,
        },
        "late_ignored_diagnostic_limit": 256,
        "omitted_late_ignored_diagnostic_count": 0,
        "late_ignored_diagnostics": [],
    }
    diagnostics["ticker_currentness"] = {
        "candidate_count_by_classification": {
            "CURRENT": 0,
            "SOURCE_STALE": 0,
            "TIMESTAMP_AHEAD": 0,
            "TRUSTED_TIME_UNKNOWN": 0,
        },
        "accepted_transition_count_by_state": {
            "MISSING": 0,
            "CURRENT": 0,
            "SOURCE_STALE": 0,
        },
    }
    diagnostics["option_local_availability"] = {
        "unavailable_count_by_reason": {},
        "recovery_count_by_reason": {},
        "end_count_by_disposition": {
            "RECOVERED": 0,
            "REASON_CHANGED": 0,
            "CENSORED_AT_STOP": 0,
        },
        "acceptance_window_ms": 3_600_000,
        "retained_interval_limit": 10_000,
        "outside_window_interval_count": 0,
        "outside_window_latest_end_monotonic_ms": None,
        "outside_window_interval_count_by_reason": {},
        "omitted_interval_count": 0,
        "omitted_interval_count_by_reason": {},
        "intervals": [],
    }
    diagnostics["index_baseline_publication"] = {
        "start_count_by_phase": {
            "TIME_BOUNDARY_PENDING": 0,
            "WATERMARK_PENDING": 0,
        },
        "end_count_by_disposition": {
            "PUBLISHED": 0,
            "PHASE_CHANGED": 0,
            "CURRENTNESS_LOST": 0,
            "CENSORED_AT_STOP": 0,
        },
        "acceptance_window_ms": 3_600_000,
        "retained_interval_limit": 10_000,
        "outside_window_interval_count": 0,
        "outside_window_latest_end_monotonic_ms": None,
        "outside_window_interval_count_by_phase_and_disposition": {
            phase: {
                disposition: 0
                for disposition in (
                    "PUBLISHED",
                    "PHASE_CHANGED",
                    "CURRENTNESS_LOST",
                    "CENSORED_AT_STOP",
                )
            }
            for phase in ("TIME_BOUNDARY_PENDING", "WATERMARK_PENDING")
        },
        "omitted_interval_count": 0,
        "omitted_interval_count_by_phase_and_disposition": {
            phase: {
                disposition: 0
                for disposition in (
                    "PUBLISHED",
                    "PHASE_CHANGED",
                    "CURRENTNESS_LOST",
                    "CENSORED_AT_STOP",
                )
            }
            for phase in ("TIME_BOUNDARY_PENDING", "WATERMARK_PENDING")
        },
        "intervals": [],
    }
    diagnostics["witness"] = {
        "global_continuity_epoch": 1,
        "first_joint_witness_monotonic_ms": None,
        "continuous_global_continuity_after_witness_ms": None,
        "scope": None,
        "boundary": None,
        "formula_instrument": None,
    }
    return diagnostics


def legacy_summary_object(
    *,
    runtime_identity: str = "runtime",
    segments: tuple[CoverageSegment, ...] = (
        CoverageSegment(
            0,
            10,
            CoverageState.UNKNOWN,
            reason="RUNTIME_START",
            blocking_reason="RUNTIME_START_PENDING",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.KNOWN_COMPLETE,
            reason="TICKER_APPLIED",
            blocking_reason="NONE",
            affected_scopes=("OPTION:SHORT",),
            global_continuity_epoch=1,
        ),
    ),
) -> dict[str, object]:
    summary = summary_object(runtime_identity=runtime_identity, segments=segments)
    summary["operational_diagnostics"] = operational_diagnostics(
        observation_ms=segments[-1].end_monotonic_ms - segments[0].start_monotonic_ms
    )
    summary["coverage_segments"] = [
        {
            "start_monotonic_ms": segment.start_monotonic_ms,
            "end_monotonic_ms": segment.end_monotonic_ms,
            "state": segment.state.value,
        }
        for segment in segments
    ]
    return summary


def current_summary_object(
    *,
    segments: tuple[CoverageSegment, ...] = (
        CoverageSegment(
            0,
            10,
            CoverageState.UNKNOWN,
            reason="RUNTIME_START",
            blocking_reason="RUNTIME_START_PENDING",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.KNOWN_COMPLETE,
            reason="TICKER_APPLIED",
            blocking_reason="NONE",
            affected_scopes=("OPTION:SHORT",),
            global_continuity_epoch=1,
        ),
    ),
    diagnostics: dict[str, object] | None = None,
) -> dict[str, object]:
    return project_run_summary(
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
        coverage_segments=segments,
        band_suspended_duration_ms=0,
        counts_by_scope=[],
        detector_unknown_transition_count_by_reason={"WARMUP": 1},
        anomaly_end_count_by_reason={EpisodeEndReason.CLEAR: 0},
        known_active_duration_ms_sum_by_end_reason={EpisodeEndReason.CLEAR: 0},
        public_atomic_quote_state_transition_count={},
        operational_diagnostics=(
            current_operational_diagnostics() if diagnostics is None else diagnostics
        ),
    )


def sealed_version_five_summary_object(
    *,
    segments: tuple[CoverageSegment, ...] = (
        CoverageSegment(
            0,
            10,
            CoverageState.UNKNOWN,
            reason="RUNTIME_START",
            blocking_reason="RUNTIME_START_PENDING",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.KNOWN_COMPLETE,
            reason="TICKER_APPLIED",
            blocking_reason="NONE",
            affected_scopes=("OPTION:SHORT",),
            global_continuity_epoch=1,
        ),
    ),
) -> dict[str, object]:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["operational_diagnostics_schema_version"] = 5
    diagnostics.pop("index_baseline_publication")
    summary["runtime_started_monotonic_ms"] = segments[0].start_monotonic_ms
    summary["clean_stop_monotonic_ms"] = segments[-1].end_monotonic_ms
    summary["coverage_segments"] = [
        {
            "start_monotonic_ms": segment.start_monotonic_ms,
            "end_monotonic_ms": segment.end_monotonic_ms,
            "state": segment.state.value,
            "trigger_cause": segment.reason,
            "blocking_reason": segment.blocking_reason,
            "affected_scopes": list(segment.affected_scopes),
            "blocking_groups": [
                {
                    "blocking_reason": group.blocking_reason,
                    "affected_scopes": list(group.affected_scopes),
                }
                for group in segment.blocking_groups
            ],
            "global_continuity_epoch": segment.global_continuity_epoch,
        }
        for segment in segments
    ]
    durations = {
        state: sum(
            segment.end_monotonic_ms - segment.start_monotonic_ms
            for segment in segments
            if segment.state is state
        )
        for state in CoverageState
    }
    observation_ms = segments[-1].end_monotonic_ms - segments[0].start_monotonic_ms
    summary["coverage"] = {
        "observation_interval_ms": observation_ms,
        "known_complete_ms": durations[CoverageState.KNOWN_COMPLETE],
        "known_degraded_ms": durations[CoverageState.KNOWN_DEGRADED],
        "unknown_ms": durations[CoverageState.UNKNOWN],
        "no_applicable_scope_ms": durations[CoverageState.NO_APPLICABLE_SCOPE],
        "coverage_partition_error_ms": observation_ms - sum(durations.values()),
    }
    validate_sealed_version_five_run_summary(summary)
    return summary


def attach_joint_witness(
    summary: dict[str, object],
    *,
    first_ms: int = 15,
    expiration_timestamp_ms: int = 3_600_000,
    option_type: str = "call",
    tte_band_id: str = "band",
    joint_count: int | None = None,
) -> None:
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    clean_stop = summary["clean_stop_monotonic_ms"]
    assert isinstance(clean_stop, int)
    witness.update(
        {
            "first_joint_witness_monotonic_ms": first_ms,
            "continuous_global_continuity_after_witness_ms": clean_stop - first_ms,
            "scope": {
                "expiration_timestamp_ms": expiration_timestamp_ms,
                "option_type": option_type,
                "tte_band_id": tte_band_id,
            },
            "boundary": {
                "session_epoch": 1,
                "ingress_seq": 1,
                "received_monotonic_ms": first_ms,
                "causal_seq": 1,
            },
            "formula_instrument": {
                "instrument_name": "SHORT",
                "expiration_timestamp_ms": expiration_timestamp_ms,
                "option_type": option_type,
                "tte_band_id": tte_band_id,
            },
        }
    )
    if joint_count is None:
        return
    scope = ScopeCounts("sha256:" + "b" * 64, option_type, tte_band_id)
    scope.applicable_instrument_count = 1
    scope.known_per_instrument_detector_evaluation_count = 1
    scope.known_full_detector_formula_evaluation_count = 1
    scope.complete_aggregate_detector_evaluation_count = 1
    scope.complete_aggregate_with_full_formula_evaluation_count = joint_count
    summary["counts_by_scope"] = [scope.as_object()]
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    continuity["current_epoch_joint_evaluation_count_by_scope"] = (
        []
        if joint_count <= 0
        else [
            {
                "policy_identity": "sha256:" + "b" * 64,
                "expiration_timestamp_ms": expiration_timestamp_ms,
                "option_type": option_type,
                "tte_band_id": tte_band_id,
                "formula_instrument_name": "SHORT",
                "count": joint_count,
                "first_joint_evaluation_boundary": dict(witness["boundary"]),
            }
        ]
    )


def epoch_two_summary(
    *,
    recovery_ms: int | None,
    witness_ms: int | None = None,
) -> dict[str, object]:
    summary = current_summary_object()
    recovery_inside_interval = recovery_ms is not None and 10 < recovery_ms < 20
    segments = [
        {
            "start_monotonic_ms": 0,
            "end_monotonic_ms": 10,
            "state": "UNKNOWN",
            "trigger_cause": "RUNTIME_START",
            "blocking_reason": "RUNTIME_START_PENDING",
            "affected_scopes": ["GLOBAL"],
            "blocking_groups": [
                {
                    "blocking_reason": "RUNTIME_START_PENDING",
                    "affected_scopes": ["GLOBAL"],
                }
            ],
            "global_continuity_epoch": 1,
        },
        {
            "start_monotonic_ms": 10,
            "end_monotonic_ms": recovery_ms if recovery_inside_interval else 20,
            "state": "UNKNOWN",
            "trigger_cause": "CLOCK_GAP",
            "blocking_reason": "CLOCK_GAP",
            "affected_scopes": ["GLOBAL"],
            "blocking_groups": [
                {
                    "blocking_reason": "CLOCK_GAP",
                    "affected_scopes": ["GLOBAL"],
                }
            ],
            "global_continuity_epoch": 2,
        },
    ]
    if recovery_inside_interval:
        segments.append(
            {
                "start_monotonic_ms": recovery_ms,
                "end_monotonic_ms": 20,
                "state": "KNOWN_COMPLETE",
                "trigger_cause": "INDEX_TICK",
                "blocking_reason": "NONE",
                "affected_scopes": ["GLOBAL"],
                "blocking_groups": [],
                "global_continuity_epoch": 2,
            }
        )
    summary["coverage_segments"] = segments
    unknown_ms = 10 + (
        recovery_ms - 10 if recovery_inside_interval and recovery_ms is not None else 10
    )
    summary["coverage"] = {
        "observation_interval_ms": 20,
        "known_complete_ms": 20 - unknown_ms,
        "known_degraded_ms": 0,
        "unknown_ms": unknown_ms,
        "no_applicable_scope_ms": 0,
        "coverage_partition_error_ms": 0,
    }
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["global_continuity"] = {
        "current_epoch": 2,
        "restart_count": 1,
        "restart_count_by_reason": {"CLOCK_GAP": 1},
        "restart_edges": [
            {
                "incident_id": 1,
                "from_epoch": 1,
                "to_epoch": 2,
                "trigger_cause": "CLOCK_GAP",
                "reason": "CLOCK_GAP",
                "failure_domain": "CLOCK_INDEX",
                "affected_scopes": ["GLOBAL"],
                "boundary": {
                    "session_epoch": 1,
                    "ingress_seq": 1,
                    "received_monotonic_ms": 10,
                    "causal_seq": 1,
                },
            }
        ],
        "recovery_edges": (
            []
            if recovery_ms is None
            else [
                {
                    "incident_id": 1,
                    "boundary": {
                        "session_epoch": 1,
                        "ingress_seq": 1 if recovery_ms == 10 else 2,
                        "received_monotonic_ms": recovery_ms,
                        "causal_seq": 1 if recovery_ms == 10 else 2,
                    },
                }
            ]
        ),
        "current_epoch_joint_evaluation_count_by_scope": [],
    }
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    witness["global_continuity_epoch"] = 2
    if witness_ms is not None:
        attach_joint_witness(summary, first_ms=witness_ms, joint_count=1)
        witness["global_continuity_epoch"] = 2
    return summary


def index_window_gap_scope_split_summary() -> dict[str, object]:
    scope_a = "SCOPE:3600000:call:band-a"
    scope_b = "SCOPE:7200000:call:band-b"
    ledger = CoverageLedger(
        0,
        initial_commit=CausalCommit(
            boundary=FactBoundary(1, 0, 0, 0),
            cause=CausalCause.RUNTIME_START,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        ),
    )
    restart_commit = CausalCommit(
        boundary=FactBoundary(1, 1, 10, 1),
        cause=CausalCause.INDEX_TICK,
        failure_domain=FailureScope.CLOCK_INDEX,
        affected_scopes=(scope_a,),
    )
    ledger.transition(
        CoverageState.UNKNOWN,
        commit=restart_commit,
        causal_effect=CausalEffect(
            cause=CausalCause.INDEX_WINDOW_GAP,
            failure_domain=FailureScope.CLOCK_INDEX,
            affected_scopes=(scope_a,),
        ),
        blocking_reason="INDEX_WINDOW_GAP",
        global_continuity_epoch=2,
        force=True,
    )
    ledger.transition(
        CoverageState.UNKNOWN,
        commit=CausalCommit(
            boundary=FactBoundary(1, 2, 15, 2),
            cause=CausalCause.TIME_BOUNDARY,
            failure_domain=FailureScope.CLOCK_INDEX,
            affected_scopes=(scope_b,),
        ),
        affected_scopes=(scope_a, scope_b),
        blocking_reason="INDEX_WINDOW_GAP",
        global_continuity_epoch=2,
    )
    diagnostics = current_operational_diagnostics()
    diagnostics["global_continuity"] = {
        "current_epoch": 2,
        "restart_count": 1,
        "restart_count_by_reason": {"INDEX_WINDOW_GAP": 1},
        "restart_edges": [
            {
                "incident_id": 1,
                "from_epoch": 1,
                "to_epoch": 2,
                "trigger_cause": "INDEX_TICK",
                "reason": "INDEX_WINDOW_GAP",
                "failure_domain": "CLOCK_INDEX",
                "affected_scopes": [scope_a],
                "boundary": {
                    "session_epoch": 1,
                    "ingress_seq": 1,
                    "received_monotonic_ms": 10,
                    "causal_seq": 1,
                },
            }
        ],
        "recovery_edges": [],
        "current_epoch_joint_evaluation_count_by_scope": [],
    }
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    witness["global_continuity_epoch"] = 2
    return project_run_summary(
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
        coverage_segments=ledger.close(20),
        band_suspended_duration_ms=0,
        counts_by_scope=[],
        detector_unknown_transition_count_by_reason={"WARMUP": 1},
        anomaly_end_count_by_reason={EpisodeEndReason.CLEAR: 0},
        known_active_duration_ms_sum_by_end_reason={EpisodeEndReason.CLEAR: 0},
        public_atomic_quote_state_transition_count={},
        operational_diagnostics=diagnostics,
    )


def cross_ledger_summary() -> dict[str, object]:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    ingress = diagnostics["ingress"]
    assert isinstance(ingress, dict)
    ingress.update(
        {
            "received_envelope_count": 3,
            "reduced_envelope_count": 3,
            "send_control_event_count": 1,
            "connection_error_event_count": 0,
        }
    )
    channels = diagnostics["channel_by_class"]
    assert isinstance(channels, list)
    for channel in channels:
        if channel["channel_class"] == "HEARTBEAT":
            channel.update(
                {
                    "received_count": 1,
                    "processed_count": 1,
                    "received_rate_per_second": "50",
                    "processed_rate_per_second": "50",
                }
            )
        elif channel["channel_class"] == "CONNECTION_CONTROL":
            channel.update(
                {
                    "received_count": 2,
                    "processed_count": 2,
                    "received_rate_per_second": "100",
                    "processed_rate_per_second": "100",
                }
            )
    diagnostics["rpc_by_method"] = [
        {
            "method": "public/test",
            "scheduled_count": 1,
            "sent_count": 1,
            "success_count": 1,
            "error_count": 0,
            "deadline_late_count": 0,
            "retired_count": 0,
            "censored_count": 0,
            "pre_send_error_count": 0,
            "pre_send_deadline_late_count": 0,
            "pre_send_retired_count": 0,
            "pre_send_censored_count": 0,
            "post_send_success_count": 1,
            "post_send_error_count": 0,
            "post_send_deadline_late_count": 0,
            "post_send_retired_count": 0,
            "post_send_censored_count": 0,
            "rate_limit_count": 0,
            "latency_observation_count": 1,
            "latency_ms_sum": 5,
            "latency_ms_max": 5,
        }
    ]
    heartbeat = diagnostics["heartbeat"]
    assert isinstance(heartbeat, dict)
    heartbeat.update(
        {
            "test_request_count": 1,
            "public_test_success_count": 1,
            "public_test_error_count": 0,
            "latency_observation_count": 1,
            "latency_ms_sum": 5,
            "latency_ms_max": 5,
        }
    )
    source_shapes = diagnostics["source_shapes"]
    assert isinstance(source_shapes, list)
    for row in source_shapes:
        if row["source"] in {"heartbeat", "public/test"}:
            row.update(
                {
                    "observed_count": 1,
                    "valid_count": 1,
                    "invalid_count": 0,
                    "validation": "VALID",
                }
            )
    return summary


@pytest.mark.parametrize(
    "field",
    (
        "heartbeat.test_request_count",
        "heartbeat.public_test_success_count",
        "heartbeat.public_test_error_count",
        "heartbeat.latency_observation_count",
        "heartbeat.latency_ms_sum",
        "heartbeat.latency_ms_max",
        "rpc.scheduled_count",
        "rpc.sent_count",
        "rpc.success_count",
        "rpc.error_count",
        "rpc.deadline_late_count",
        "rpc.retired_count",
        "rpc.censored_count",
        "rpc.pre_send_error_count",
        "rpc.pre_send_deadline_late_count",
        "rpc.pre_send_retired_count",
        "rpc.pre_send_censored_count",
        "rpc.post_send_success_count",
        "rpc.post_send_error_count",
        "rpc.post_send_deadline_late_count",
        "rpc.post_send_retired_count",
        "rpc.post_send_censored_count",
        "rpc.rate_limit_count",
        "rpc.latency_observation_count",
        "rpc.latency_ms_sum",
        "rpc.latency_ms_max",
        "source_shapes.public/test.observed_count",
        "source_shapes.public/test.valid_count",
        "source_shapes.public/test.invalid_count",
        "source_shapes.public/test.validation",
        "rpc_orphan_late_wire_count",
        "ingress.received_envelope_count",
        "ingress.reduced_envelope_count",
        "ingress.send_control_event_count",
        "ingress.connection_error_event_count",
        "channel.CONNECTION_CONTROL.received_count",
        "channel.CONNECTION_CONTROL.processed_count",
        "channel.CONNECTION_CONTROL.received_rate_per_second",
        "channel.CONNECTION_CONTROL.processed_rate_per_second",
    ),
)
def test_schema_three_cross_ledger_conservation_rejects_single_point_tampering(
    field: str,
) -> None:
    summary = cross_ledger_summary()
    validate_run_summary(summary)
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    heartbeat = diagnostics["heartbeat"]
    ingress = diagnostics["ingress"]
    rpc_rows = diagnostics["rpc_by_method"]
    source_rows = diagnostics["source_shapes"]
    channel_rows = diagnostics["channel_by_class"]
    assert isinstance(heartbeat, dict)
    assert isinstance(ingress, dict)
    assert isinstance(rpc_rows, list)
    assert isinstance(source_rows, list)
    assert isinstance(channel_rows, list)

    if field.startswith("heartbeat."):
        heartbeat[field.removeprefix("heartbeat.")] += 1
    elif field.startswith("rpc."):
        rpc_rows[0][field.removeprefix("rpc.")] += 1
    elif field.startswith("source_shapes.public/test."):
        public_test = next(row for row in source_rows if row["source"] == "public/test")
        source_field = field.removeprefix("source_shapes.public/test.")
        if source_field == "validation":
            public_test[source_field] = "INVALID"
        else:
            public_test[source_field] += 1
    elif field == "rpc_orphan_late_wire_count":
        diagnostics[field] = 1
    elif field.startswith("ingress."):
        ingress[field.removeprefix("ingress.")] += 1
    elif field.startswith("channel.CONNECTION_CONTROL."):
        connection_control = next(
            row for row in channel_rows if row["channel_class"] == "CONNECTION_CONTROL"
        )
        channel_field = field.removeprefix("channel.CONNECTION_CONTROL.")
        if channel_field.endswith("_count"):
            connection_control[channel_field] += 1
        else:
            connection_control[channel_field] = "150"
    else:  # pragma: no cover - parameter list is the exhaustive mutation authority
        raise AssertionError(field)

    with pytest.raises(EvidenceError):
        validate_run_summary(summary)


@pytest.mark.parametrize(
    "ledger",
    (
        "source_shapes.public/test",
        "ingress",
        "channel.CONNECTION_CONTROL",
    ),
)
def test_schema_three_cross_ledger_rejects_internally_consistent_row_tampering(
    ledger: str,
) -> None:
    summary = cross_ledger_summary()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    if ledger == "source_shapes.public/test":
        source_rows = diagnostics["source_shapes"]
        assert isinstance(source_rows, list)
        public_test = next(row for row in source_rows if row["source"] == "public/test")
        public_test.update({"observed_count": 2, "valid_count": 2})
    elif ledger == "ingress":
        ingress = diagnostics["ingress"]
        assert isinstance(ingress, dict)
        ingress.update({"received_envelope_count": 4, "reduced_envelope_count": 4})
    else:
        channel_rows = diagnostics["channel_by_class"]
        assert isinstance(channel_rows, list)
        connection_control = next(
            row for row in channel_rows if row["channel_class"] == "CONNECTION_CONTROL"
        )
        connection_control.update(
            {
                "received_count": 3,
                "processed_count": 3,
                "received_rate_per_second": "150",
                "processed_rate_per_second": "150",
            }
        )

    with pytest.raises(EvidenceError, match=r"conservation|reconcile|cross-ledger"):
        validate_run_summary(summary)


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    (
        ("close_code", "4444"),
        ("close_disposition", "CLEAN"),
        ("exception_class", "PrivateImplementationError"),
        ("count", 2),
    ),
)
def test_transport_terminal_attribution_rejects_single_field_tampering(
    field: str,
    tampered_value: object,
) -> None:
    summary = cross_ledger_summary()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    ingress = diagnostics["ingress"]
    channels = diagnostics["channel_by_class"]
    assert isinstance(ingress, dict)
    assert isinstance(channels, list)
    ingress.update(
        {
            "received_envelope_count": 4,
            "reduced_envelope_count": 4,
            "connection_error_event_count": 1,
        }
    )
    connection_control = next(
        row for row in channels if row["channel_class"] == "CONNECTION_CONTROL"
    )
    connection_control.update(
        {
            "received_count": 3,
            "processed_count": 3,
            "received_rate_per_second": "150",
            "processed_rate_per_second": "150",
        }
    )
    attribution = {
        "close_code": "OTHER",
        "close_disposition": "ABNORMAL",
        "exception_class": "OSError",
        "count": 1,
    }
    diagnostics["transport_terminal_attribution"] = [attribution]
    validate_run_summary(summary)

    attribution[field] = tampered_value
    with pytest.raises(EvidenceError):
        validate_run_summary(summary)


def test_minimal_events_are_strict_unit_bearing_and_carry_non_claims() -> None:
    anomaly = project_anomaly_event(anomaly_evidence())
    atomic = project_atomic_event(atomic_evidence())
    assert anomaly["object_kind"] == "SHORT_VOL_ANOMALY_EVENT"
    assert anomaly["target_base_quantity_btc"] == "0.1"
    anomaly_non_claims = anomaly["non_claims"]
    assert isinstance(anomaly_non_claims, list)
    assert "NOT_VALIDATED_FORECAST" in anomaly_non_claims
    assert atomic["object_kind"] == "PUBLIC_ATOMIC_QUOTE_EVENT"
    assert atomic["gross_entry_credit_usdc"] == "0.5"
    atomic_non_claims = atomic["non_claims"]
    assert isinstance(atomic_non_claims, list)
    assert "PUBLIC_QUOTE_NOT_FILL" in atomic_non_claims
    assert "full_option_chain" not in json.dumps((anomaly, atomic))

    changed = dict(anomaly)
    changed["unknown"] = True
    with pytest.raises(EvidenceError, match="exact"):
        validate_anomaly_event(changed)

    nested = project_anomaly_event(anomaly_evidence())
    instrument = nested["instrument"]
    assert isinstance(instrument, dict)
    instrument["unknown"] = True
    with pytest.raises(EvidenceError, match="exact"):
        validate_anomaly_event(nested)

    changed_atomic = project_atomic_event(atomic_evidence())
    changed_atomic["gross_entry_credit_usdc"] = "0.6"
    with pytest.raises(EvidenceError, match="gross credit"):
        validate_atomic_event(changed_atomic)


def test_evidence_writer_deduplicates_events_and_validates_directory(
    tmp_path: Path,
) -> None:
    anomaly = project_anomaly_event(anomaly_evidence())
    atomic = project_atomic_event(atomic_evidence())
    writer = EvidenceWriter(
        tmp_path,
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
    )
    assert writer.write_anomaly(anomaly) is not None
    assert writer.write_anomaly(anomaly) is None
    assert writer.write_atomic(atomic) is not None
    assert writer.write_atomic(atomic) is None
    scope = ScopeCounts("sha256:" + "b" * 64, "call", "band")
    scope.applicable_instrument_count = 1
    scope.distinct_anomaly_episode_count = 1
    scope.anomaly_activation_transition_count = 1
    scope.anomaly_end_count_by_reason[EpisodeEndReason.CENSORED_AT_STOP.value] = 1
    scope.known_active_duration_ms_sum_by_end_reason[EpisodeEndReason.CENSORED_AT_STOP.value] = 0
    scope.public_atomic_quote_state_transition_count[
        PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value
    ] = 1
    summary = summary_object()
    summary["counts_by_scope"] = [scope.as_object()]
    summary["anomaly_end_count_by_reason"] = {
        reason.value: int(reason is EpisodeEndReason.CENSORED_AT_STOP)
        for reason in EpisodeEndReason
    }
    summary["known_active_duration_ms_sum_by_end_reason"] = {
        reason.value: 0 for reason in EpisodeEndReason
    }
    summary["public_atomic_quote_state_transition_count"] = {
        PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value: 1
    }
    writer.write_summary(summary)
    objects = validate_evidence_directory(tmp_path)
    assert len(objects) == 3


def test_evidence_writer_uses_short_temporary_name_for_long_atomic_identity(
    tmp_path: Path,
) -> None:
    runtime_identity = "sha256:" + "0" * 64
    policy_identity = "sha256:" + "1" * 64
    short_instrument_name = "BTC_USDC-2AUG26-63000-C"
    combo_instrument_name = "BTC_USDC-CS-2AUG26-63000_64500"
    episode_identity = f"{runtime_identity}:{policy_identity}:{short_instrument_name}:416138"
    source = atomic_evidence()
    event = project_atomic_event(
        replace(
            source,
            runtime_identity=runtime_identity,
            policy_identity=policy_identity,
            episode_identity=episode_identity,
            short_instrument_name=short_instrument_name,
            combo_legs=(
                (short_instrument_name, Decimal(-1)),
                ("BTC_USDC-2AUG26-64500-C", Decimal(1)),
            ),
            quote=replace(
                source.quote,
                match=replace(
                    source.quote.match,
                    combo_instrument_name=combo_instrument_name,
                ),
            ),
        )
    )
    writer = EvidenceWriter(
        tmp_path,
        code_identity=source.code_identity,
        runtime_identity=runtime_identity,
        policy_identity=policy_identity,
    )

    path = writer.write_atomic(event)

    assert path is not None
    assert len(path.name.encode()) == 230
    assert (
        path.read_text(encoding="utf-8")
        == json.dumps(
            event,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    assert not tuple(tmp_path.glob(".*.tmp"))


def test_evidence_writer_rejects_conflicting_duplicate_identity(tmp_path: Path) -> None:
    event = project_anomaly_event(anomaly_evidence())
    writer = EvidenceWriter(
        tmp_path,
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
    )
    assert writer.write_anomaly(event) is not None
    conflicting = dict(event)
    conflicting["causal_seq"] = 11

    with pytest.raises(EvidenceError, match="conflicting"):
        writer.write_anomaly(conflicting)


def test_evidence_directory_rejects_mixed_runtime_identity(tmp_path: Path) -> None:
    first = summary_object(runtime_identity="one")
    second = summary_object(runtime_identity="two")
    (tmp_path / "one.json").write_text(json.dumps(first), encoding="utf-8")
    (tmp_path / "two.json").write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(EvidenceError, match="mixes"):
        validate_evidence_directory(tmp_path)


def test_evidence_directory_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    (tmp_path / "duplicate.json").write_text(
        '{"object_kind":"RADAR_RUN_SUMMARY","object_kind":"RADAR_RUN_SUMMARY"}',
        encoding="utf-8",
    )
    with pytest.raises(EvidenceError, match="invalid evidence"):
        validate_evidence_directory(tmp_path)


def test_current_evidence_directory_requires_one_canonical_run_summary(
    tmp_path: Path,
) -> None:
    with pytest.raises(EvidenceError, match=r"exactly one.*run summary"):
        validate_evidence_directory(tmp_path)

    anomaly = project_anomaly_event(anomaly_evidence())
    (tmp_path / "anomaly.json").write_text(json.dumps(anomaly), encoding="utf-8")
    with pytest.raises(EvidenceError, match=r"exactly one.*run summary"):
        validate_evidence_directory(tmp_path)

    (tmp_path / "anomaly.json").unlink()
    (tmp_path / "summary.json").write_text(
        json.dumps(current_summary_object()),
        encoding="utf-8",
    )
    with pytest.raises(EvidenceError, match=r"radar-run-summary\.json"):
        validate_evidence_directory(tmp_path)


def test_current_evidence_directory_rejects_non_json_or_non_file_entries(
    tmp_path: Path,
) -> None:
    (tmp_path / "radar-run-summary.json").write_text(
        json.dumps(current_summary_object()),
        encoding="utf-8",
    )
    (tmp_path / "operator-note.txt").write_text("not evidence", encoding="utf-8")
    with pytest.raises(EvidenceError, match="unexpected evidence directory entry"):
        validate_evidence_directory(tmp_path)

    (tmp_path / "operator-note.txt").unlink()
    (tmp_path / "nested").mkdir()
    with pytest.raises(EvidenceError, match="unexpected evidence directory entry"):
        validate_evidence_directory(tmp_path)


def test_evidence_directory_cross_checks_summary_episode_count(tmp_path: Path) -> None:
    scope = ScopeCounts("sha256:" + "b" * 64, "call", "band")
    scope.applicable_instrument_count = 1
    scope.distinct_anomaly_episode_count = 1
    scope.anomaly_activation_transition_count = 1
    scope.anomaly_end_count_by_reason[EpisodeEndReason.CENSORED_AT_STOP.value] = 1
    summary = summary_object()
    summary["counts_by_scope"] = [scope.as_object()]
    summary["anomaly_end_count_by_reason"] = {
        reason.value: int(reason is EpisodeEndReason.CENSORED_AT_STOP)
        for reason in EpisodeEndReason
    }
    (tmp_path / "radar-run-summary.json").write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(EvidenceError, match="episode count"):
        validate_evidence_directory(tmp_path)


def test_evidence_directory_attributes_anomaly_count_to_exact_option_type_and_band(
    tmp_path: Path,
) -> None:
    anomaly = project_anomaly_event(anomaly_evidence())
    wrong_scope = ScopeCounts("sha256:" + "b" * 64, "put", "other-band")
    wrong_scope.applicable_instrument_count = 1
    wrong_scope.distinct_anomaly_episode_count = 1
    wrong_scope.anomaly_activation_transition_count = 1
    wrong_scope.anomaly_end_count_by_reason[EpisodeEndReason.CENSORED_AT_STOP.value] = 1
    summary = current_summary_object()
    summary["counts_by_scope"] = [wrong_scope.as_object()]
    summary["anomaly_end_count_by_reason"] = {
        reason.value: int(reason is EpisodeEndReason.CENSORED_AT_STOP)
        for reason in EpisodeEndReason
    }
    summary["known_active_duration_ms_sum_by_end_reason"] = {
        reason.value: 0 for reason in EpisodeEndReason
    }
    (tmp_path / "anomaly.json").write_text(json.dumps(anomaly), encoding="utf-8")
    (tmp_path / "radar-run-summary.json").write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(EvidenceError, match=r"scope|option_type|band"):
        validate_evidence_directory(tmp_path)


def test_coverage_segments_reject_overlap_gap_negative_and_mismatched_totals() -> None:
    with pytest.raises(EvidenceError, match="overlap or contain a gap"):
        summary_object(
            segments=(
                CoverageSegment(
                    0,
                    10,
                    CoverageState.UNKNOWN,
                    reason="RUNTIME_START",
                    blocking_reason="RUNTIME_START_PENDING",
                    affected_scopes=("GLOBAL",),
                    global_continuity_epoch=1,
                ),
                CoverageSegment(
                    9,
                    20,
                    CoverageState.KNOWN_COMPLETE,
                    reason="TICKER_APPLIED",
                    blocking_reason="NONE",
                    affected_scopes=("OPTION:SHORT",),
                    global_continuity_epoch=1,
                ),
            )
        )
    with pytest.raises(EvidenceError, match="overlap or contain a gap"):
        summary_object(
            segments=(
                CoverageSegment(
                    0,
                    10,
                    CoverageState.UNKNOWN,
                    reason="RUNTIME_START",
                    blocking_reason="RUNTIME_START_PENDING",
                    affected_scopes=("GLOBAL",),
                    global_continuity_epoch=1,
                ),
                CoverageSegment(
                    11,
                    20,
                    CoverageState.KNOWN_COMPLETE,
                    reason="TICKER_APPLIED",
                    blocking_reason="NONE",
                    affected_scopes=("OPTION:SHORT",),
                    global_continuity_epoch=1,
                ),
            )
        )
    summary = summary_object()
    coverage = summary["coverage"]
    assert isinstance(coverage, dict)
    summary["coverage"] = {**coverage, "coverage_partition_error_ms": 1}
    with pytest.raises(EvidenceError, match="totals"):
        validate_run_summary(summary)


def test_coverage_ledger_splits_same_state_on_global_continuity_restart() -> None:
    ledger = CoverageLedger(
        0,
        initial_commit=CausalCommit(
            boundary=FactBoundary(1, 0, 0, 0),
            cause=CausalCause.RUNTIME_START,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        ),
    )
    ledger.transition(
        CoverageState.UNKNOWN,
        commit=CausalCommit(
            boundary=FactBoundary(1, 1, 10, 1),
            cause=CausalCause.INDEX_CONTINUITY_GAP,
            failure_domain=FailureScope.CLOCK_INDEX,
            affected_scopes=("GLOBAL",),
        ),
        blocking_reason="INDEX_CONTINUITY_GAP",
        global_continuity_epoch=2,
        force=True,
    )

    assert ledger.close(20) == (
        CoverageSegment(
            0,
            10,
            CoverageState.UNKNOWN,
            reason="RUNTIME_START",
            blocking_reason="RUNTIME_START_PENDING",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.UNKNOWN,
            reason="INDEX_CONTINUITY_GAP",
            blocking_reason="INDEX_CONTINUITY_GAP",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=2,
        ),
    )


def test_coverage_ledger_preserves_trigger_cause_and_true_blocking_reason() -> None:
    ledger = CoverageLedger(
        0,
        initial_commit=CausalCommit(
            boundary=FactBoundary(1, 0, 0, 0),
            cause=CausalCause.RUNTIME_START,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        ),
    )
    commit = CausalCommit(
        boundary=FactBoundary(1, 1, 10, 1),
        cause=CausalCause.OPTION_BOOK_FACT,
        failure_domain=FailureScope.OPTION,
        affected_scopes=("OPTION:SHORT",),
    )
    effect = CausalEffect(
        cause=CausalCause.TICKER_SOURCE_STALE,
        failure_domain=FailureScope.OPTION,
        affected_scopes=("OPTION:SHORT",),
    )
    ledger.transition(
        CoverageState.UNKNOWN,
        commit=commit,
        causal_effect=effect,
        blocking_reason="TICKER_SOURCE_STALE",
        global_continuity_epoch=1,
    )

    summary = current_summary_object(segments=ledger.close(20))
    coverage_segments = summary["coverage_segments"]
    assert isinstance(coverage_segments, list)
    blocked = coverage_segments[1]
    assert blocked == {
        "start_monotonic_ms": 10,
        "end_monotonic_ms": 20,
        "state": "UNKNOWN",
        "trigger_cause": "OPTION_BOOK_FACT",
        "blocking_reason": "TICKER_SOURCE_STALE",
        "affected_scopes": ["OPTION:SHORT"],
        "blocking_groups": [
            {
                "blocking_reason": "TICKER_SOURCE_STALE",
                "affected_scopes": ["OPTION:SHORT"],
            }
        ],
        "global_continuity_epoch": 1,
    }


def heterogeneous_blocker_summary() -> dict[str, object]:
    summary = current_summary_object()
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    first = segments[0]
    assert isinstance(first, dict)
    first["blocking_reason"] = "CURRENT_SCOPE_INCOMPLETE"
    first["affected_scopes"] = ["OPTION:A", "OPTION:B"]
    first["blocking_groups"] = [
        {
            "blocking_reason": "OPTION_BOOK_UNAVAILABLE",
            "affected_scopes": ["OPTION:A"],
        },
        {
            "blocking_reason": "TICKER_SOURCE_STALE",
            "affected_scopes": ["OPTION:B"],
        },
    ]
    return summary


def test_coverage_ledger_splits_when_reason_to_scope_assignment_changes() -> None:
    ledger = CoverageLedger(
        0,
        initial_commit=CausalCommit(
            boundary=FactBoundary(1, 0, 0, 0),
            cause=CausalCause.RUNTIME_START,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        ),
    )
    scopes = ("OPTION:A", "OPTION:B")
    first_groups = (
        CoverageBlockingGroup("OPTION_BOOK_UNAVAILABLE", ("OPTION:A",)),
        CoverageBlockingGroup("TICKER_SOURCE_STALE", ("OPTION:B",)),
    )
    second_groups = (
        CoverageBlockingGroup("OPTION_BOOK_UNAVAILABLE", ("OPTION:B",)),
        CoverageBlockingGroup("TICKER_SOURCE_STALE", ("OPTION:A",)),
    )
    ledger.transition(
        CoverageState.UNKNOWN,
        commit=CausalCommit(
            boundary=FactBoundary(1, 1, 10, 1),
            cause=CausalCause.OPTION_BOOK_FACT,
            failure_domain=FailureScope.OPTION,
            affected_scopes=scopes,
        ),
        affected_scopes=scopes,
        blocking_reason="CURRENT_SCOPE_INCOMPLETE",
        blocking_groups=first_groups,
        global_continuity_epoch=1,
    )
    ledger.transition(
        CoverageState.UNKNOWN,
        commit=CausalCommit(
            boundary=FactBoundary(1, 2, 15, 2),
            cause=CausalCause.TIME_BOUNDARY,
            failure_domain=FailureScope.OPTION,
            affected_scopes=scopes,
        ),
        affected_scopes=scopes,
        blocking_reason="CURRENT_SCOPE_INCOMPLETE",
        blocking_groups=second_groups,
        global_continuity_epoch=1,
    )

    summary = current_summary_object(segments=ledger.close(20))
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    assert [segment["start_monotonic_ms"] for segment in segments] == [0, 10, 15]
    assert segments[1]["blocking_groups"] != segments[2]["blocking_groups"]
    validate_run_summary(summary)


@pytest.mark.parametrize(
    ("blocking_reason", "affected_scopes", "message"),
    (
        (
            "CURRENT_SCOPE_INCOMPLETE",
            ("OPTION:A",),
            "blocking_reason must summarize",
        ),
        (
            "OPTION_BOOK_UNAVAILABLE",
            ("OPTION:B",),
            "affected_scopes must summarize",
        ),
    ),
)
def test_coverage_ledger_rejects_inconsistent_group_summaries_immediately(
    blocking_reason: str,
    affected_scopes: tuple[str, ...],
    message: str,
) -> None:
    ledger = CoverageLedger(
        0,
        initial_commit=CausalCommit(
            boundary=FactBoundary(1, 0, 0, 0),
            cause=CausalCause.RUNTIME_START,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        ),
    )

    with pytest.raises(ValueError, match=message):
        ledger.transition(
            CoverageState.UNKNOWN,
            commit=CausalCommit(
                boundary=FactBoundary(1, 1, 10, 1),
                cause=CausalCause.OPTION_BOOK_FACT,
                failure_domain=FailureScope.OPTION,
                affected_scopes=affected_scopes,
            ),
            affected_scopes=affected_scopes,
            blocking_reason=blocking_reason,
            blocking_groups=(CoverageBlockingGroup("OPTION_BOOK_UNAVAILABLE", ("OPTION:A",)),),
            global_continuity_epoch=1,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("reverse", "sorted"),
        ("duplicate_reason", "unique"),
        ("wrong_scalar", "summarize blocking groups"),
        ("wrong_summary_scopes", "summarize blocking groups"),
        ("empty", "1 to 256"),
        ("extra_field", "exact repository-owned schema"),
        ("none_group", "synthetic or empty"),
    ),
)
def test_schema_six_blocking_groups_are_strict(
    mutation: str,
    message: str,
) -> None:
    summary = heterogeneous_blocker_summary()
    validate_run_summary(summary)
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    first = segments[0]
    assert isinstance(first, dict)
    groups = first["blocking_groups"]
    assert isinstance(groups, list)
    first_group = groups[0]
    second_group = groups[1]
    assert isinstance(first_group, dict)
    assert isinstance(second_group, dict)
    if mutation == "reverse":
        groups.reverse()
    elif mutation == "duplicate_reason":
        second_group["blocking_reason"] = first_group["blocking_reason"]
    elif mutation == "wrong_scalar":
        first["blocking_reason"] = "OPTION_BOOK_UNAVAILABLE"
    elif mutation == "wrong_summary_scopes":
        first["affected_scopes"] = ["OPTION:A"]
    elif mutation == "empty":
        first["blocking_groups"] = []
    elif mutation == "extra_field":
        first_group["payload"] = {"bid": 1}
    elif mutation == "none_group":
        first["blocking_reason"] = "CURRENT_SCOPE_INCOMPLETE"
        first["blocking_groups"] = [
            {
                "blocking_reason": "NONE",
                "affected_scopes": ["OPTION:A"],
            }
        ]
    else:
        raise AssertionError("unhandled mutation")

    with pytest.raises(EvidenceError, match=message):
        validate_run_summary(summary)


def test_sealed_version_five_soak_accounting_keeps_legacy_p_g_e_u() -> None:
    summary = sealed_version_five_summary_object(
        segments=(
            CoverageSegment(
                0,
                100,
                CoverageState.UNKNOWN,
                reason="TIME_BOUNDARY",
                blocking_reason="CURRENT_SCOPE_INCOMPLETE",
                affected_scopes=("OPTION:A", "OPTION:B"),
                global_continuity_epoch=1,
                blocking_groups=(
                    CoverageBlockingGroup(
                        "INDEX_TIME_BOUNDARY_PENDING",
                        ("OPTION:A",),
                    ),
                    CoverageBlockingGroup(
                        "TICKER_SOURCE_STALE",
                        ("OPTION:B",),
                    ),
                ),
            ),
            CoverageSegment(
                100,
                200,
                CoverageState.UNKNOWN,
                reason="CLOCK_FACT",
                blocking_reason="CLOCK_UNAVAILABLE",
                affected_scopes=("GLOBAL",),
                global_continuity_epoch=1,
            ),
            CoverageSegment(
                200,
                3_600_000,
                CoverageState.KNOWN_COMPLETE,
                reason="TICKER_APPLIED",
                blocking_reason="NONE",
                affected_scopes=("OPTION:A", "OPTION:B"),
                global_continuity_epoch=1,
            ),
        )
    )
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    availability = diagnostics["option_local_availability"]
    assert isinstance(availability, dict)
    availability.update(
        {
            "unavailable_count_by_reason": {"TICKER_SOURCE_STALE": 1},
            "recovery_count_by_reason": {"TICKER_SOURCE_STALE": 1},
            "end_count_by_disposition": {
                "RECOVERED": 1,
                "REASON_CHANGED": 0,
                "CENSORED_AT_STOP": 0,
            },
            "intervals": [
                {
                    "instrument_name": "B",
                    "generation": 1,
                    "reason": "TICKER_SOURCE_STALE",
                    "start_monotonic_ms": 300,
                    "end_monotonic_ms": 450,
                    "duration_ms": 150,
                    "end_disposition": "RECOVERED",
                    "global_continuity_epoch": 1,
                }
            ],
        }
    )

    assert sealed_version_five_operational_soak_window_accounting(summary) == {
        "window_start_monotonic_ms": 0,
        "window_end_monotonic_ms": 3_600_000,
        "known_complete_ms": 3_599_800,
        "normal_boundary_pending_ms": 100,
        "global_currentness_incident_ms": 100,
        "effective_option_local_denominator_ms": 3_599_800,
        "option_local_unavailable_union_ms": 150,
    }


def test_explicit_sealed_operational_summary_path_does_not_weaken_current_schema() -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["operational_diagnostics_schema_version"] = 3
    diagnostics.pop("transport_terminal_attribution")
    diagnostics.pop("index_baseline_publication")
    coverage_segments = summary["coverage_segments"]
    assert isinstance(coverage_segments, list)
    for segment in coverage_segments:
        segment["reason"] = segment.pop("trigger_cause")
        segment.pop("blocking_reason")
        segment.pop("blocking_groups")

    validate_sealed_operational_run_summary(summary)
    with pytest.raises(EvidenceError, match="diagnostics schema 6"):
        validate_run_summary(summary)


def test_sealed_compacted_option_local_schema_remains_exact() -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["operational_diagnostics_schema_version"] = 3
    diagnostics.pop("transport_terminal_attribution")
    diagnostics.pop("index_baseline_publication")
    availability = diagnostics["option_local_availability"]
    assert isinstance(availability, dict)
    availability["retained_interval_limit"] = 256
    for field in (
        "acceptance_window_ms",
        "outside_window_interval_count",
        "outside_window_latest_end_monotonic_ms",
        "outside_window_interval_count_by_reason",
    ):
        availability.pop(field)
    coverage_segments = summary["coverage_segments"]
    assert isinstance(coverage_segments, list)
    for segment in coverage_segments:
        segment["reason"] = segment.pop("trigger_cause")
        segment.pop("blocking_reason")
        segment.pop("blocking_groups")

    validate_sealed_operational_run_summary(summary)
    availability["acceptance_window_ms"] = 3_600_000
    with pytest.raises(EvidenceError, match="exact repository-owned schema"):
        validate_sealed_operational_run_summary(summary)


def test_sealed_operational_schema_retains_historical_queue_lag_restart_semantics() -> None:
    summary = epoch_two_summary(recovery_ms=12)
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["operational_diagnostics_schema_version"] = 3
    diagnostics.pop("transport_terminal_attribution")
    diagnostics.pop("index_baseline_publication")
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    continuity["restart_count_by_reason"] = {"QUEUE_LAG_DEADLINE": 1}
    restart = continuity["restart_edges"][0]
    assert isinstance(restart, dict)
    restart.pop("trigger_cause")
    restart["reason"] = "QUEUE_LAG_DEADLINE"
    restart["failure_domain"] = "SESSION"
    coverage_segments = summary["coverage_segments"]
    assert isinstance(coverage_segments, list)
    blocked = coverage_segments[1]
    assert isinstance(blocked, dict)
    blocked["trigger_cause"] = "QUEUE_LAG_DEADLINE"
    for segment in coverage_segments:
        segment["reason"] = segment.pop("trigger_cause")
        segment.pop("blocking_reason")
        segment.pop("blocking_groups")

    validate_sealed_operational_run_summary(summary)


@pytest.mark.parametrize(
    ("state", "blocking_reason"),
    (
        ("KNOWN_COMPLETE", "CLOCK_GAP"),
        ("UNKNOWN", "NONE"),
        ("NO_APPLICABLE_SCOPE", "CURRENT_SCOPE_INCOMPLETE"),
    ),
)
def test_current_coverage_state_and_blocking_reason_cannot_contradict(
    state: str,
    blocking_reason: str,
) -> None:
    summary = current_summary_object()
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    segments[0]["state"] = state
    segments[0]["blocking_reason"] = blocking_reason
    coverage = summary["coverage"]
    assert isinstance(coverage, dict)
    duration_ms = segments[0]["end_monotonic_ms"] - segments[0]["start_monotonic_ms"]
    coverage.update(
        {
            "known_complete_ms": duration_ms if state == "KNOWN_COMPLETE" else 10,
            "known_degraded_ms": 0,
            "unknown_ms": duration_ms if state == "UNKNOWN" else 0,
            "no_applicable_scope_ms": (duration_ms if state == "NO_APPLICABLE_SCOPE" else 0),
        }
    )

    with pytest.raises(EvidenceError, match="blocking reason"):
        validate_run_summary(summary)


def test_schema_three_accepts_bounded_option_local_coverage_scope() -> None:
    summary = current_summary_object()
    coverage_segments = summary["coverage_segments"]
    assert isinstance(coverage_segments, list)
    first = coverage_segments[0]
    assert isinstance(first, dict)
    first["affected_scopes"] = ["OPTION_LOCAL"]
    first["blocking_groups"] = [
        {
            "blocking_reason": "RUNTIME_START_PENDING",
            "affected_scopes": ["OPTION_LOCAL"],
        }
    ]

    validate_run_summary(summary)


def test_zero_and_unknown_denominators_serialize_as_null_semantics() -> None:
    assert ratio_or_none(0, 0) is None
    assert ratio_or_none(0, None) is None
    assert ratio_or_none(1, 2) == Decimal("0.5")
    rates = ScopeCounts("policy", "call", "band").as_object()
    assert rates["known_full_formula_rate_given_known_per_instrument"] is None
    assert rates["complete_aggregate_with_full_formula_rate_given_complete_aggregate"] is None


def test_run_summary_rejects_impossible_scope_count_relationships() -> None:
    scope = ScopeCounts("sha256:" + "b" * 64, "call", "band")
    scope.applicable_instrument_count = 1
    scope.known_per_instrument_detector_evaluation_count = 1
    scope.known_full_detector_formula_evaluation_count = 2
    summary = summary_object()
    summary["counts_by_scope"] = [scope.as_object()]

    with pytest.raises(EvidenceError, match="full-formula"):
        validate_run_summary(summary)


def test_run_summary_cross_checks_episode_activation_and_end_totals() -> None:
    scope = ScopeCounts("sha256:" + "b" * 64, "call", "band")
    scope.applicable_instrument_count = 1
    scope.distinct_anomaly_episode_count = 1
    scope.anomaly_activation_transition_count = 1
    summary = summary_object()
    summary["counts_by_scope"] = [scope.as_object()]

    with pytest.raises(EvidenceError, match="episode ends"):
        validate_run_summary(summary)


def test_version_two_operational_diagnostics_remain_strict_and_payload_free() -> None:
    summary = legacy_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    assert diagnostics["operational_diagnostics_schema_version"] == 2
    assert "price" not in json.dumps(diagnostics)

    channels = diagnostics["channel_by_class"]
    assert isinstance(channels, list)
    channels[0]["received_count"] = 1
    with pytest.raises(EvidenceError, match="rate"):
        evidence_module.validate_legacy_run_summary(summary)

    summary = legacy_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    source_shapes = diagnostics["source_shapes"]
    assert isinstance(source_shapes, list)
    source_shapes[0]["payload"] = {"price": 100}
    with pytest.raises(EvidenceError, match="exact"):
        evidence_module.validate_legacy_run_summary(summary)


def test_version_six_diagnostics_and_attributed_coverage_are_strict() -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    assert diagnostics["operational_diagnostics_schema_version"] == 6
    assert "price" not in json.dumps(diagnostics)
    assert summary["coverage_segments"] == [
        {
            "start_monotonic_ms": 0,
            "end_monotonic_ms": 10,
            "state": "UNKNOWN",
            "trigger_cause": "RUNTIME_START",
            "blocking_reason": "RUNTIME_START_PENDING",
            "affected_scopes": ["GLOBAL"],
            "blocking_groups": [
                {
                    "blocking_reason": "RUNTIME_START_PENDING",
                    "affected_scopes": ["GLOBAL"],
                }
            ],
            "global_continuity_epoch": 1,
        },
        {
            "start_monotonic_ms": 10,
            "end_monotonic_ms": 20,
            "state": "KNOWN_COMPLETE",
            "trigger_cause": "TICKER_APPLIED",
            "blocking_reason": "NONE",
            "affected_scopes": ["OPTION:SHORT"],
            "blocking_groups": [],
            "global_continuity_epoch": 1,
        },
    ]
    validate_run_summary(summary)

    invalid_scope = current_summary_object()
    invalid_segments = invalid_scope["coverage_segments"]
    assert isinstance(invalid_segments, list)
    invalid_segment = invalid_segments[1]
    assert isinstance(invalid_segment, dict)
    invalid_segment["affected_scopes"] = ["UNBOUNDED"]
    with pytest.raises(EvidenceError, match="affected scope"):
        validate_run_summary(invalid_scope)

    wrong_epoch = current_summary_object()
    wrong_epoch_segments = wrong_epoch["coverage_segments"]
    assert isinstance(wrong_epoch_segments, list)
    wrong_epoch_segment = wrong_epoch_segments[1]
    assert isinstance(wrong_epoch_segment, dict)
    wrong_epoch_segment["global_continuity_epoch"] = 2
    with pytest.raises(EvidenceError, match="continuity epoch"):
        validate_run_summary(wrong_epoch)


def test_current_schema_version_requires_an_integer_token() -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["operational_diagnostics_schema_version"] = 6.0

    with pytest.raises(EvidenceError, match="integer diagnostics schema 6"):
        validate_run_summary(summary)

    writer_diagnostics = current_operational_diagnostics()
    writer_diagnostics["operational_diagnostics_schema_version"] = 6.0
    with pytest.raises(EvidenceError, match="integer diagnostics schema 6"):
        current_summary_object(diagnostics=writer_diagnostics)


def test_explicit_sealed_version_four_summary_keeps_its_exact_shape() -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["operational_diagnostics_schema_version"] = 4
    diagnostics.pop("index_baseline_publication")
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    for segment in segments:
        segment.pop("blocking_groups")

    validate_sealed_version_four_run_summary(summary)
    with pytest.raises(EvidenceError, match="diagnostics schema 6"):
        validate_run_summary(summary)

    segments[0]["blocking_groups"] = []
    with pytest.raises(EvidenceError, match="exact repository-owned schema"):
        validate_sealed_version_four_run_summary(summary)


def test_explicit_sealed_version_four_directory_route_is_isolated(
    tmp_path: Path,
) -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["operational_diagnostics_schema_version"] = 4
    diagnostics.pop("index_baseline_publication")
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    for segment in segments:
        segment.pop("blocking_groups")
    (tmp_path / "radar-run-summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )

    assert len(validate_sealed_version_four_evidence_directory(tmp_path)) == 1
    with pytest.raises(EvidenceError, match="integer diagnostics schema 6"):
        validate_evidence_directory(tmp_path)


def test_version_three_late_diagnostics_are_bounded_and_payload_free() -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    ticker_application = diagnostics["ticker_application"]
    assert isinstance(ticker_application, dict)
    row = {
        "instrument_name": "SHORT",
        "generation": 7,
        "ingress_seq": 9,
        "previous_source_timestamp_ms": 1_000,
        "candidate_source_timestamp_ms": 999,
        "timestamp_delta_ms": -1,
        "received_monotonic_ms": 15,
        "disposition": "LATE_IGNORED",
    }
    ticker_application["disposition_count"]["LATE_IGNORED"] = 1
    ticker_application["late_ignored_diagnostics"] = [row]
    source_shapes = diagnostics["source_shapes"]
    assert isinstance(source_shapes, list)
    ticker_shape = next(item for item in source_shapes if item["source"] == "option_ticker")
    ticker_shape.update(
        {
            "observed_count": 1,
            "valid_count": 1,
            "invalid_count": 0,
            "validation": "VALID",
        }
    )
    ticker_currentness = diagnostics["ticker_currentness"]
    assert isinstance(ticker_currentness, dict)
    ticker_currentness["candidate_count_by_classification"]["CURRENT"] = 1
    validate_run_summary(summary)

    row["payload"] = {"underlying_price": 100}
    with pytest.raises(EvidenceError, match="exact"):
        validate_run_summary(summary)

    over_limit = current_summary_object()
    over_limit_diagnostics = over_limit["operational_diagnostics"]
    assert isinstance(over_limit_diagnostics, dict)
    over_limit_application = over_limit_diagnostics["ticker_application"]
    assert isinstance(over_limit_application, dict)
    over_limit_disposition_count = over_limit_application["disposition_count"]
    assert isinstance(over_limit_disposition_count, dict)
    over_limit_disposition_count["LATE_IGNORED"] = 257
    over_limit_shapes = over_limit_diagnostics["source_shapes"]
    assert isinstance(over_limit_shapes, list)
    over_limit_ticker_shape = next(
        item for item in over_limit_shapes if item["source"] == "option_ticker"
    )
    over_limit_ticker_shape.update(
        {
            "observed_count": 257,
            "valid_count": 257,
            "invalid_count": 0,
            "validation": "VALID",
        }
    )
    over_limit_currentness = over_limit_diagnostics["ticker_currentness"]
    assert isinstance(over_limit_currentness, dict)
    over_limit_currentness["candidate_count_by_classification"]["CURRENT"] = 257
    over_limit_application["late_ignored_diagnostics"] = [
        {
            "instrument_name": f"SHORT-{index}",
            "generation": 1,
            "ingress_seq": index + 1,
            "previous_source_timestamp_ms": 1_000,
            "candidate_source_timestamp_ms": 999,
            "timestamp_delta_ms": -1,
            "received_monotonic_ms": 15,
            "disposition": "LATE_IGNORED",
        }
        for index in range(257)
    ]
    with pytest.raises(EvidenceError, match="256"):
        validate_run_summary(over_limit)

    unattributed = current_summary_object()
    unattributed_diagnostics = unattributed["operational_diagnostics"]
    assert isinstance(unattributed_diagnostics, dict)
    unattributed_application = unattributed_diagnostics["ticker_application"]
    assert isinstance(unattributed_application, dict)
    unattributed_counts = unattributed_application["disposition_count"]
    assert isinstance(unattributed_counts, dict)
    unattributed_counts["LATE_IGNORED"] = 1
    with pytest.raises(EvidenceError, match="do not match"):
        validate_run_summary(unattributed)


def test_operational_diagnostics_requires_exact_nine_runtime_limits() -> None:
    summary = summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    runtime_limits = diagnostics["runtime_limits"]
    assert isinstance(runtime_limits, dict)
    runtime_limits["ticker_source_stale_deadline_ms"] = 5_000

    validate_run_summary(summary)


def test_runtime_projects_exact_policy_runtime_limits(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(ticker_source_stale_deadline_ms=7_777)
    policy = load_policy_bytes(exact, digest)
    runtime = LiveRadarRuntime(
        policy=policy,
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )

    diagnostics = runtime.reducer._operational_diagnostics(0)

    assert diagnostics["operational_diagnostics_schema_version"] == 6
    assert diagnostics["runtime_limits"] == policy.runtime_limits.as_object()
    runtime_limits = diagnostics["runtime_limits"]
    assert isinstance(runtime_limits, dict)
    assert len(runtime_limits) == 9
    assert runtime_limits["ticker_source_stale_deadline_ms"] == 7_777


def test_run_summary_rejects_unknown_operational_diagnostics_schema() -> None:
    summary = summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["operational_diagnostics_schema_version"] = 1

    with pytest.raises(EvidenceError, match="schema"):
        validate_run_summary(summary)


def test_run_summary_rejects_legacy_eight_field_runtime_limits() -> None:
    summary = summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    runtime_limits = diagnostics["runtime_limits"]
    assert isinstance(runtime_limits, dict)
    del runtime_limits["ticker_source_stale_deadline_ms"]

    with pytest.raises(EvidenceError, match="exact repository-owned schema"):
        validate_run_summary(summary)


def test_run_summary_rejects_invalid_ticker_source_stale_deadline() -> None:
    summary = summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    runtime_limits = diagnostics["runtime_limits"]
    assert isinstance(runtime_limits, dict)
    runtime_limits["ticker_source_stale_deadline_ms"] = 0

    with pytest.raises(EvidenceError, match="must be positive"):
        validate_run_summary(summary)


def test_run_summary_rejects_ticker_deadline_shorter_than_poll_interval() -> None:
    summary = summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    runtime_limits = diagnostics["runtime_limits"]
    assert isinstance(runtime_limits, dict)
    runtime_limits["ticker_source_stale_deadline_ms"] = 999

    with pytest.raises(EvidenceError, match="ticker source stale deadline"):
        validate_run_summary(summary)


@pytest.mark.parametrize(
    ("segments", "first_witness_ms", "continuous_ms", "message"),
    (
        (
            (
                CoverageSegment(
                    0,
                    20,
                    CoverageState.KNOWN_COMPLETE,
                    reason="RUNTIME_START",
                    blocking_reason="NONE",
                    affected_scopes=("GLOBAL",),
                    global_continuity_epoch=1,
                ),
            ),
            21,
            0,
            "within the runtime interval",
        ),
        (
            (
                CoverageSegment(
                    100,
                    120,
                    CoverageState.KNOWN_COMPLETE,
                    reason="RUNTIME_START",
                    blocking_reason="NONE",
                    affected_scopes=("GLOBAL",),
                    global_continuity_epoch=1,
                ),
            ),
            99,
            21,
            "within the runtime interval",
        ),
        (
            (
                CoverageSegment(
                    0,
                    20,
                    CoverageState.KNOWN_COMPLETE,
                    reason="RUNTIME_START",
                    blocking_reason="NONE",
                    affected_scopes=("GLOBAL",),
                    global_continuity_epoch=1,
                ),
            ),
            10,
            9,
            "continuous duration",
        ),
    ),
)
def test_run_summary_rejects_impossible_joint_witness_continuity(
    segments: tuple[CoverageSegment, ...],
    first_witness_ms: int,
    continuous_ms: int,
    message: str,
) -> None:
    summary = legacy_summary_object(segments=segments)
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    witness["first_joint_witness_monotonic_ms"] = first_witness_ms
    witness["continuous_covered_after_witness_ms"] = continuous_ms

    with pytest.raises(EvidenceError, match=message):
        evidence_module.validate_legacy_run_summary(summary)


def test_zero_duration_coverage_is_truthful_not_fabricated() -> None:
    ledger = CoverageLedger(
        100,
        initial_commit=CausalCommit(
            boundary=FactBoundary(1, 0, 100, 0),
            cause=CausalCause.RUNTIME_START,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        ),
    )
    segments = ledger.close(100)
    assert segments == (
        CoverageSegment(
            100,
            100,
            CoverageState.UNKNOWN,
            reason="RUNTIME_START",
            blocking_reason="RUNTIME_START_PENDING",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
    )
    summary = project_run_summary(
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
        coverage_segments=segments,
        band_suspended_duration_ms=0,
        counts_by_scope=[],
        detector_unknown_transition_count_by_reason={},
        anomaly_end_count_by_reason={},
        known_active_duration_ms_sum_by_end_reason={},
        public_atomic_quote_state_transition_count={},
        operational_diagnostics=current_operational_diagnostics(observation_ms=0),
    )
    assert summary["runtime_started_monotonic_ms"] == 100
    assert summary["clean_stop_monotonic_ms"] == 100
    assert summary["coverage"] == {
        "observation_interval_ms": 0,
        "known_complete_ms": 0,
        "known_degraded_ms": 0,
        "unknown_ms": 0,
        "no_applicable_scope_ms": 0,
        "coverage_partition_error_ms": 0,
    }


def test_git_and_evidence_startup_guards_fail_before_network(tmp_path: Path) -> None:
    assert validate_clean_git_outputs(head_output="a" * 40 + "\n", status_output="") == "a" * 40
    with pytest.raises(StartupGuardError, match="clean"):
        validate_clean_git_outputs(head_output="a" * 40, status_output=" M file.py\n")
    with pytest.raises(StartupGuardError, match="commit"):
        validate_clean_git_outputs(head_output="short", status_output="")

    repository = tmp_path / "repo"
    repository.mkdir()
    with pytest.raises(StartupGuardError, match="outside"):
        prepare_evidence_directory(repository / "evidence", repository)
    evidence = tmp_path / "evidence"
    assert prepare_evidence_directory(evidence, repository) == evidence
    (evidence / "occupied").write_text("x", encoding="utf-8")
    with pytest.raises(StartupGuardError, match="empty"):
        prepare_evidence_directory(evidence, repository)


def test_evidence_publish_failure_leaves_no_partial_final_or_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = anomaly_evidence()
    writer = EvidenceWriter(
        tmp_path,
        code_identity=evidence.code_identity,
        runtime_identity=evidence.runtime_identity,
        policy_identity=evidence.policy_identity,
    )

    def fail_publish(_source: object, _target: object) -> None:
        raise OSError("injected atomic publish failure")

    monkeypatch.setattr(os, "link", fail_publish)
    with pytest.raises(EvidenceError, match="publish"):
        writer.write_anomaly(project_anomaly_event(evidence))

    assert list(tmp_path.iterdir()) == []


def test_evidence_oserror_is_fatal_without_reconnect(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    policy = load_policy_bytes(exact, digest)
    connection_enters = 0

    class CountingClient:
        def __init__(self, *, session_epoch: int, rpc_deadline_ms: int) -> None:
            self.session_epoch = session_epoch
            assert rpc_deadline_ms == policy.runtime_limits.rpc_deadline_ms

        async def __aenter__(self) -> CountingClient:
            nonlocal connection_enters
            connection_enters += 1
            if connection_enters > 1:
                raise AssertionError("evidence failure attempted a reconnect")
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def write_failing_evidence(
        runtime: LiveRadarRuntime,
        _client: object,
        _stop_event: asyncio.Event,
    ) -> Path:
        evidence = anomaly_evidence()
        event = project_anomaly_event(evidence)
        event["code_identity"] = runtime.code_identity
        event["runtime_identity"] = runtime.runtime_identity
        event["policy_identity"] = runtime.policy.identity
        path = runtime.writer.write_anomaly(event)
        raise AssertionError(f"write unexpectedly succeeded: {path}")

    def fail_publish(_source: object, _target: object) -> None:
        raise OSError("injected evidence publish failure")

    monkeypatch.setattr(runtime_module, "DeribitPublicClient", CountingClient)
    monkeypatch.setattr(LiveRadarRuntime, "run", write_failing_evidence)
    monkeypatch.setattr(os, "link", fail_publish)

    with pytest.raises(EvidenceError, match="publish"):
        asyncio.run(
            runtime_module.observe(
                policy=policy,
                code_identity="a" * 40,
                evidence_directory=tmp_path,
                stop_event=asyncio.Event(),
            )
        )

    assert connection_enters == 1


def test_observe_does_not_rewrite_summary_after_post_stop_transport_close_failure(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    policy = load_policy_bytes(exact, digest)
    stop_event = asyncio.Event()
    summary_path = tmp_path / "radar-run-summary.json"
    run_count = 0

    class CloseFailingClient:
        def __init__(self, *, session_epoch: int, rpc_deadline_ms: int) -> None:
            assert session_epoch == 1
            assert rpc_deadline_ms == policy.runtime_limits.rpc_deadline_ms

        async def __aenter__(self) -> CloseFailingClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            raise OSError("injected post-stop socket close failure")

    async def complete_clean_stop(
        _runtime: LiveRadarRuntime,
        _client: object,
        event: asyncio.Event,
    ) -> Path:
        nonlocal run_count
        run_count += 1
        event.set()
        summary_path.write_text("{}\n", encoding="utf-8")
        return summary_path

    async def reject_second_clean_stop(
        _runtime: LiveRadarRuntime,
        _client: object | None = None,
    ) -> Path:
        raise AssertionError("committed summary was rewritten after transport close")

    monkeypatch.setattr(runtime_module, "DeribitPublicClient", CloseFailingClient)
    monkeypatch.setattr(LiveRadarRuntime, "run", complete_clean_stop)
    monkeypatch.setattr(LiveRadarRuntime, "_clean_stop", reject_second_clean_stop)

    assert (
        asyncio.run(
            runtime_module.observe(
                policy=policy,
                code_identity="a" * 40,
                evidence_directory=tmp_path,
                stop_event=stop_event,
            )
        )
        == summary_path
    )
    assert run_count == 1


def test_continuous_inbound_flow_cannot_starve_absolute_time_boundaries(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    policy = load_policy_bytes(exact, digest)
    runtime = LiveRadarRuntime(
        policy=policy,
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )
    stop_event = asyncio.Event()
    summary_path = tmp_path / "summary.json"
    now_ms = 0
    next_seq = 0
    reduced: list[int] = []
    timer_boundaries: list[int] = []

    class ContinuousClient:
        session_epoch = 1
        queue_high_water_frames = 0
        overflow_count = 0
        received_frame_count = 0

        async def next_envelope(
            self,
            timeout_seconds: float | None = None,
        ) -> InboundEnvelope:
            del timeout_seconds
            nonlocal now_ms, next_seq
            next_seq += 1
            now_ms = next_seq * 400
            if next_seq == 3:
                stop_event.set()
            return InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "method": "heartbeat",
                    "params": {"type": "heartbeat"},
                },
                session_epoch=1,
                ingress_seq=next_seq,
                received_monotonic_ms=now_ms,
            )

        async def send_request(self, **_kwargs: object) -> None:
            raise AssertionError("patched reducer must not emit commands")

        def enqueue_send_control(self, event: SendControlEvent) -> None:
            raise AssertionError(f"patched reducer unexpectedly emitted {event}")

    def reduce_frame(
        frame: InboundEnvelope,
        *,
        processed_monotonic_ms: int,
    ) -> tuple[object, ...]:
        assert processed_monotonic_ms == now_ms
        reduced.append(frame.ingress_seq)
        return ()

    def advance_time(boundary_ms: int) -> tuple[object, ...]:
        timer_boundaries.append(boundary_ms)
        return ()

    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: now_ms)
    monkeypatch.setattr(runtime.reducer, "begin_session", lambda **_kwargs: ())
    monkeypatch.setattr(runtime.reducer, "reduce", reduce_frame)
    monkeypatch.setattr(runtime.reducer, "advance_time", advance_time)
    monkeypatch.setattr(runtime.reducer, "clean_stop", lambda _stop_ms: summary_path)

    assert asyncio.run(runtime.run(ContinuousClient(), stop_event)) == summary_path
    assert reduced == [1, 2, 3]
    assert timer_boundaries == [1_000]


def test_sustained_ingress_heartbeat_round_trip_seals_one_conserved_directory(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )
    stop_event = asyncio.Event()

    class IngressAndHeartbeatClient(DeribitPublicClient):
        def __init__(self) -> None:
            super().__init__(session_epoch=1, rpc_deadline_ms=30_000)
            self.sent_methods: list[str] = []

        async def send_request(
            self,
            *,
            request_id: int,
            method: str,
            params: dict[str, object],
            responding_to_test_request: bool = False,
        ) -> None:
            del params, responding_to_test_request
            self.sent_methods.append(method)
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"version": "test"} if method == "public/test" else "ok",
            }
            received_monotonic_ms = runtime_module._monotonic_ms()

            def enqueue_after_send_receipt() -> None:
                self._enqueue_wire_message(
                    response,
                    received_monotonic_ms=received_monotonic_ms,
                )
                if method == "public/test":
                    stop_event.set()

            asyncio.get_running_loop().call_soon(enqueue_after_send_receipt)

    client = IngressAndHeartbeatClient()
    for _ in range(64):
        client._enqueue_wire_message(
            {
                "jsonrpc": "2.0",
                "method": "heartbeat",
                "params": {"type": "heartbeat"},
            },
            received_monotonic_ms=runtime_module._monotonic_ms(),
        )
    client._enqueue_wire_message(
        {
            "jsonrpc": "2.0",
            "method": "heartbeat",
            "params": {"type": "test_request"},
        },
        received_monotonic_ms=runtime_module._monotonic_ms(),
    )

    summary_path = asyncio.run(runtime.run(client, stop_event))
    summary = json.loads(summary_path.read_text())
    validate_run_summary(summary)
    diagnostics = summary["operational_diagnostics"]

    assert client.sent_methods == ["public/set_heartbeat", "public/test"]
    assert (
        diagnostics["ingress"]["received_envelope_count"]
        == diagnostics["ingress"]["reduced_envelope_count"]
    )
    assert diagnostics["ingress"]["ingress_gap_or_duplicate_count"] == 0
    heartbeat = diagnostics["heartbeat"]
    assert heartbeat["test_request_count"] == 1
    assert heartbeat["public_test_success_count"] == 1
    assert heartbeat["public_test_error_count"] == 0
    assert heartbeat["latency_observation_count"] == 1
    assert heartbeat["latency_ms_sum"] >= heartbeat["latency_ms_max"] >= 0
    public_test = next(
        row for row in diagnostics["rpc_by_method"] if row["method"] == "public/test"
    )
    assert public_test["scheduled_count"] == 1
    assert public_test["sent_count"] == 1
    assert public_test["success_count"] == 1


@pytest.mark.parametrize("outcome", ("SUCCESS", "CANCELLED", "ERROR"))
def test_sender_reports_transport_completion_without_mutating_reducer(
    outcome: str,
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )
    command = runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)[0]
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: 1_100)
    started = asyncio.Event()
    release = asyncio.Event()

    class ControlledClient:
        def __init__(self) -> None:
            self.controls: list[object] = []

        async def send_request(self, **_kwargs: object) -> None:
            started.set()
            await release.wait()
            if outcome == "ERROR":
                raise RuntimeError("send failed")

        def enqueue_send_control(self, event: object) -> None:
            self.controls.append(event)

    client = ControlledClient()

    async def scenario() -> tuple[object, ...]:
        task = asyncio.create_task(runtime._send_commands(client, (command,)))  # type: ignore[arg-type]
        await started.wait()
        assert (
            runtime.reducer._rpc_lifecycles[command.request_id].state
            is runtime_module.RpcState.SCHEDULED
        )
        if outcome == "CANCELLED":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            await task
        return tuple(client.controls)

    controls = asyncio.run(scenario())

    assert len(controls) == 1
    event = controls[0]
    assert isinstance(event, SendControlEvent)
    assert event.request_id == command.request_id
    assert event.kind.value == ("SEND_COMPLETED" if outcome == "SUCCESS" else "SEND_FAILED")
    assert (None if event.failure is None else event.failure.value) == (
        None if outcome == "SUCCESS" else outcome
    )
    assert (
        runtime.reducer._rpc_lifecycles[command.request_id].state
        is runtime_module.RpcState.SCHEDULED
    )


def test_transport_metrics_finalize_before_sender_exception_propagates(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )

    class FailingClient(DeribitPublicClient):
        async def send_request(self, **_kwargs: object) -> None:
            self.queue_high_water_frames = 7
            raise RuntimeError("sender exploded")

    client = FailingClient(session_epoch=1, rpc_deadline_ms=30_000)
    with pytest.raises(PublicSessionError, match="SET_HEARTBEAT"):
        asyncio.run(runtime.run(client, asyncio.Event()))

    assert runtime.reducer.diagnostics.queue_high_water_frames == 7
    assert runtime.reducer.diagnostics.transport_enqueued_envelope_count == 1


def test_send_failure_is_reduced_before_session_failure_propagates(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )

    class SendFailureClient(DeribitPublicClient):
        async def send_request(self, **_kwargs: object) -> None:
            raise OSError("injected transport send failure")

    client = SendFailureClient(session_epoch=1, rpc_deadline_ms=30_000)

    with pytest.raises(PublicSessionError, match="SET_HEARTBEAT"):
        asyncio.run(runtime.run(client, asyncio.Event()))

    lifecycle = next(iter(runtime.reducer._rpc_lifecycles.values()))
    assert lifecycle.state is runtime_module.RpcState.ERROR
    assert runtime.reducer.diagnostics.rpc_error_count["public/set_heartbeat"] == 1
    assert runtime.reducer.diagnostics.received_envelope_count == 1
    assert runtime.reducer.diagnostics.reduced_envelope_count == 1


def test_failure_barrier_drains_every_already_accepted_application_event(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )
    blocked = asyncio.Event()

    class BufferedFailureClient(DeribitPublicClient):
        async def send_request(self, **_kwargs: object) -> None:
            await blocked.wait()

    client = BufferedFailureClient(session_epoch=1, rpc_deadline_ms=30_000)
    first_received_ms = runtime_module._monotonic_ms()
    client._enqueue_wire_message(
        {"jsonrpc": "2.0", "id": 999_999, "result": "orphan"},
        received_monotonic_ms=first_received_ms,
    )
    client._enqueue_connection_error(
        PublicSessionError("injected connection failure"),
        reason=ConnectionControlReason.TRANSPORT_READ_FAILURE,
    )
    client._enqueue_wire_message(
        {
            "jsonrpc": "2.0",
            "method": "heartbeat",
            "params": {"type": "heartbeat"},
        },
        received_monotonic_ms=runtime_module._monotonic_ms(),
    )

    with pytest.raises(PublicSessionError, match="connection"):
        asyncio.run(runtime.run(client, asyncio.Event()))

    assert client.enqueued_envelope_count == runtime.reducer.diagnostics.received_envelope_count
    assert (
        runtime.reducer.diagnostics.received_envelope_count
        == runtime.reducer.diagnostics.reduced_envelope_count
    )
    assert runtime.reducer.diagnostics.retired_epoch_frame_count >= 1


def test_blocked_send_clean_stop_drains_cancellation_then_censors_scheduled(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )
    original_begin_session = runtime.reducer.begin_session

    def begin_with_second_queued_command(
        *,
        session_epoch: int,
        monotonic_ms: int,
    ) -> tuple[runtime_module.PendingRpc, ...]:
        commands = original_begin_session(
            session_epoch=session_epoch,
            monotonic_ms=monotonic_ms,
        )
        queued = runtime.reducer._schedule(
            purpose=runtime_module.RpcPurpose.CLOCK_BOOTSTRAP,
            method="public/get_time",
            params={},
            scope="CLOCK_INDEX",
            generation=None,
            origin_boundary=FactBoundary(session_epoch, 0, monotonic_ms, 0),
            failure_scope=FailureScope.CLOCK_INDEX,
        )
        return (*commands, queued)

    monkeypatch.setattr(runtime.reducer, "begin_session", begin_with_second_queued_command)
    stop_event = asyncio.Event()
    send_started = asyncio.Event()
    never_release = asyncio.Event()

    class BlockingClient(DeribitPublicClient):
        send_attempt_count = 0

        async def send_request(self, **_kwargs: object) -> None:
            self.send_attempt_count += 1
            send_started.set()
            await never_release.wait()

        async def next_envelope(
            self,
            timeout_seconds: float | None = None,
        ) -> InboundEnvelope:
            del timeout_seconds
            await stop_event.wait()
            raise TimeoutError

    client = BlockingClient(session_epoch=1, rpc_deadline_ms=30_000)

    async def scenario() -> Path:
        task = asyncio.create_task(runtime.run(client, stop_event))
        await send_started.wait()
        stop_event.set()
        return await task

    summary_path = asyncio.run(scenario())
    summary = json.loads(summary_path.read_text())
    validate_run_summary(summary)
    lifecycles = tuple(runtime.reducer._rpc_lifecycles.values())
    assert len(lifecycles) == 2
    assert {lifecycle.state for lifecycle in lifecycles} == {runtime_module.RpcState.CENSORED}
    assert {lifecycle.terminal_from_state for lifecycle in lifecycles} == {
        runtime_module.RpcState.SCHEDULED
    }
    assert runtime.reducer.diagnostics.rpc_retired_count["public/set_heartbeat"] == 0
    assert runtime.reducer.diagnostics.rpc_censored_count["public/set_heartbeat"] == 1
    assert runtime.reducer.diagnostics.rpc_censored_count["public/get_time"] == 1
    assert client.enqueued_envelope_count == runtime.reducer.diagnostics.reduced_envelope_count
    assert client.send_attempt_count == 1


def test_unexpected_sender_cancellation_fails_closed(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    runtime = LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
    )

    async def cancelled_sender(*_args: object, **_kwargs: object) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(runtime, "_sender_loop", cancelled_sender)

    class WaitingClient:
        session_epoch = 1
        queue_high_water_frames = 0
        overflow_count = 0
        enqueued_envelope_count = 0
        received_frame_count = 0
        next_call_count = 0

        async def next_envelope(
            self,
            timeout_seconds: float | None = None,
        ) -> InboundEnvelope:
            del timeout_seconds
            self.next_call_count += 1
            await asyncio.sleep(0)
            if self.next_call_count > 1:
                raise AssertionError("cancelled sender was ignored")
            raise TimeoutError

        async def send_request(self, **_kwargs: object) -> None:
            raise AssertionError("patched sender must own transport calls")

        def enqueue_send_control(self, _event: object) -> None:
            raise AssertionError("patched sender must not emit controls")

    with pytest.raises(PublicSessionError, match="sender"):
        asyncio.run(runtime.run(WaitingClient(), asyncio.Event()))


def test_current_writer_and_validator_are_schema_six_only_with_explicit_legacy_entry(
    tmp_path: Path,
) -> None:
    legacy = legacy_summary_object()
    writer = EvidenceWriter(
        tmp_path,
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
    )

    with pytest.raises(EvidenceError, match="diagnostics schema 6"):
        validate_run_summary(legacy)
    with pytest.raises(EvidenceError, match="diagnostics schema 6"):
        writer.write_summary(legacy)

    validate_legacy_run_summary(legacy)
    (tmp_path / "radar-run-summary.json").write_text(
        json.dumps(legacy),
        encoding="utf-8",
    )
    with pytest.raises(EvidenceError, match="diagnostics schema 6"):
        validate_evidence_directory(tmp_path)
    assert len(validate_legacy_evidence_directory(tmp_path)) == 1


def test_coverage_cause_has_no_default_and_rejects_unknown_reason() -> None:
    with pytest.raises(TypeError):
        CoverageSegment(0, 1, CoverageState.UNKNOWN)  # type: ignore[call-arg]

    summary = current_summary_object()
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    segment = segments[1]
    assert isinstance(segment, dict)
    segment["trigger_cause"] = "RESULT_INFERRED_UNKNOWN_REASON"

    with pytest.raises(EvidenceError, match="cause whitelist"):
        validate_run_summary(summary)


def test_schema_three_rejects_unknown_coverage_scope_and_option_local_reason() -> None:
    unknown_scope = current_summary_object()
    segments = unknown_scope["coverage_segments"]
    assert isinstance(segments, list)
    segment = segments[1]
    assert isinstance(segment, dict)
    segment["affected_scopes"] = ["EVERYTHING"]
    with pytest.raises(EvidenceError, match="scope label"):
        validate_run_summary(unknown_scope)

    unknown_local_reason = current_summary_object()
    diagnostics = unknown_local_reason["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    ledger = diagnostics["option_local_availability"]
    assert isinstance(ledger, dict)
    ledger.update(
        {
            "unavailable_count_by_reason": {"UNRECOGNIZED_LOCAL_REASON": 1},
            "recovery_count_by_reason": {},
            "end_count_by_disposition": {
                "RECOVERED": 0,
                "REASON_CHANGED": 0,
                "CENSORED_AT_STOP": 1,
            },
            "omitted_interval_count": 0,
            "omitted_interval_count_by_reason": {},
            "intervals": [
                {
                    "instrument_name": "SHORT",
                    "generation": 1,
                    "reason": "UNRECOGNIZED_LOCAL_REASON",
                    "start_monotonic_ms": 0,
                    "end_monotonic_ms": 20,
                    "duration_ms": 20,
                    "end_disposition": "CENSORED_AT_STOP",
                    "global_continuity_epoch": 1,
                }
            ],
        }
    )
    with pytest.raises(EvidenceError, match="option-local reason whitelist"):
        validate_run_summary(unknown_local_reason)


def test_schema_three_witness_is_strictly_after_epoch_start_and_has_cross_checked_identity() -> (
    None
):
    at_start = current_summary_object()
    diagnostics = at_start["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    witness.update(
        {
            "first_joint_witness_monotonic_ms": 0,
            "continuous_global_continuity_after_witness_ms": 20,
            "scope": {
                "expiration_timestamp_ms": 3_600_000,
                "option_type": "call",
                "tte_band_id": "band",
            },
            "boundary": {
                "session_epoch": 1,
                "ingress_seq": 1,
                "received_monotonic_ms": 0,
                "causal_seq": 1,
            },
            "formula_instrument": {
                "instrument_name": "SHORT",
                "expiration_timestamp_ms": 3_600_000,
                "option_type": "call",
                "tte_band_id": "band",
            },
        }
    )
    with pytest.raises(EvidenceError, match="strictly later"):
        validate_run_summary(at_start)

    cross_identity = current_summary_object()
    diagnostics = cross_identity["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    witness.update(
        {
            "first_joint_witness_monotonic_ms": 10,
            "continuous_global_continuity_after_witness_ms": 10,
            "scope": {
                "expiration_timestamp_ms": 3_600_000,
                "option_type": "call",
                "tte_band_id": "band",
            },
            "boundary": {
                "session_epoch": 1,
                "ingress_seq": 1,
                "received_monotonic_ms": 10,
                "causal_seq": 1,
            },
            "formula_instrument": {
                "instrument_name": "SHORT",
                "expiration_timestamp_ms": 3_600_001,
                "option_type": "call",
                "tte_band_id": "band",
            },
        }
    )
    with pytest.raises(EvidenceError, match="witness identity"):
        validate_run_summary(cross_identity)


def test_schema_three_ticker_rpc_and_option_local_ledgers_must_conserve() -> None:
    ticker = current_summary_object()
    diagnostics = ticker["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    source_shapes = diagnostics["source_shapes"]
    assert isinstance(source_shapes, list)
    source_row = next(row for row in source_shapes if row["source"] == "option_ticker")
    source_row.update(
        {
            "observed_count": 1,
            "valid_count": 1,
            "invalid_count": 0,
            "validation": "VALID",
        }
    )
    ticker_currentness = diagnostics["ticker_currentness"]
    assert isinstance(ticker_currentness, dict)
    ticker_currentness["candidate_count_by_classification"]["CURRENT"] = 1
    with pytest.raises(EvidenceError, match="ticker conservation"):
        validate_run_summary(ticker)

    rpc = current_summary_object()
    diagnostics = rpc["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    rpc_rows = diagnostics["rpc_by_method"]
    assert isinstance(rpc_rows, list)
    rpc_rows.append(
        {
            "method": "public/test",
            "scheduled_count": 1,
            "sent_count": 0,
            "success_count": 0,
            "error_count": 0,
            "deadline_late_count": 0,
            "retired_count": 0,
            "censored_count": 0,
            "pre_send_error_count": 0,
            "pre_send_deadline_late_count": 0,
            "pre_send_retired_count": 0,
            "pre_send_censored_count": 0,
            "post_send_success_count": 0,
            "post_send_error_count": 0,
            "post_send_deadline_late_count": 0,
            "post_send_retired_count": 0,
            "post_send_censored_count": 0,
            "rate_limit_count": 0,
            "latency_observation_count": 0,
            "latency_ms_sum": 0,
            "latency_ms_max": 0,
        }
    )
    with pytest.raises(EvidenceError, match=r"RPC.*scheduled|conservation"):
        validate_run_summary(rpc)

    availability = current_summary_object()
    diagnostics = availability["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    ledger = diagnostics["option_local_availability"]
    assert isinstance(ledger, dict)
    ledger.update(
        {
            "unavailable_count_by_reason": {"TICKER_SOURCE_STALE": 1},
            "recovery_count_by_reason": {},
            "end_count_by_disposition": {
                "RECOVERED": 0,
                "REASON_CHANGED": 0,
                "CENSORED_AT_STOP": 0,
            },
            "omitted_interval_count": 1,
            "omitted_interval_count_by_reason": {
                "TICKER_SOURCE_STALE": {
                    "RECOVERED": 0,
                    "REASON_CHANGED": 0,
                    "CENSORED_AT_STOP": 1,
                }
            },
        }
    )
    with pytest.raises(EvidenceError, match="option-local conservation"):
        validate_run_summary(availability)


def test_schema_three_option_local_ledger_binds_the_exact_final_hour() -> None:
    summary = current_summary_object(
        segments=(
            CoverageSegment(
                0,
                4_000_000,
                CoverageState.UNKNOWN,
                reason="RUNTIME_START",
                blocking_reason="RUNTIME_START_PENDING",
                affected_scopes=("GLOBAL",),
                global_continuity_epoch=1,
            ),
        )
    )
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    ledger = diagnostics["option_local_availability"]
    assert isinstance(ledger, dict)
    ledger.update(
        {
            "acceptance_window_ms": 3_600_000,
            "retained_interval_limit": 10_000,
            "unavailable_count_by_reason": {"TICKER_SOURCE_STALE": 2},
            "recovery_count_by_reason": {"TICKER_SOURCE_STALE": 2},
            "end_count_by_disposition": {
                "RECOVERED": 2,
                "REASON_CHANGED": 0,
                "CENSORED_AT_STOP": 0,
            },
            "outside_window_interval_count": 1,
            "outside_window_latest_end_monotonic_ms": 200,
            "outside_window_interval_count_by_reason": {
                "TICKER_SOURCE_STALE": {
                    "RECOVERED": 1,
                    "REASON_CHANGED": 0,
                    "CENSORED_AT_STOP": 0,
                }
            },
            "omitted_interval_count": 0,
            "omitted_interval_count_by_reason": {},
            "intervals": [
                {
                    "instrument_name": "TAIL",
                    "generation": 1,
                    "reason": "TICKER_SOURCE_STALE",
                    "start_monotonic_ms": 3_999_000,
                    "end_monotonic_ms": 3_999_001,
                    "duration_ms": 1,
                    "end_disposition": "RECOVERED",
                    "global_continuity_epoch": 1,
                }
            ],
        }
    )
    validate_run_summary(summary)

    wrong_window = json.loads(json.dumps(summary))
    wrong_window["operational_diagnostics"]["option_local_availability"]["acceptance_window_ms"] = (
        3_599_999
    )
    with pytest.raises(EvidenceError, match="acceptance window"):
        validate_run_summary(wrong_window)

    wrong_limit = json.loads(json.dumps(summary))
    wrong_limit["operational_diagnostics"]["option_local_availability"][
        "retained_interval_limit"
    ] = 9_999
    with pytest.raises(EvidenceError, match="retained interval limit"):
        validate_run_summary(wrong_limit)

    outside_enters_window = json.loads(json.dumps(summary))
    outside_enters_window["operational_diagnostics"]["option_local_availability"][
        "outside_window_latest_end_monotonic_ms"
    ] = 400_001
    with pytest.raises(EvidenceError, match=r"outside-window.*final acceptance window"):
        validate_run_summary(outside_enters_window)

    retained_before_window = json.loads(json.dumps(summary))
    retained_interval = retained_before_window["operational_diagnostics"][
        "option_local_availability"
    ]["intervals"][0]
    retained_interval.update(
        {
            "start_monotonic_ms": 100,
            "end_monotonic_ms": 200,
            "duration_ms": 100,
        }
    )
    with pytest.raises(EvidenceError, match=r"retained.*final acceptance window"):
        validate_run_summary(retained_before_window)

    false_outside_count = json.loads(json.dumps(summary))
    false_outside_count["operational_diagnostics"]["option_local_availability"][
        "outside_window_interval_count_by_reason"
    ]["TICKER_SOURCE_STALE"]["RECOVERED"] = 2
    with pytest.raises(EvidenceError, match="outside-window intervals"):
        validate_run_summary(false_outside_count)


def test_schema_three_epoch_edges_must_match_restart_incidents_one_for_one() -> None:
    summary = current_summary_object()
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    second = segments[1]
    assert isinstance(second, dict)
    second["state"] = "UNKNOWN"
    second["blocking_reason"] = "INDEX_CONTINUITY_GAP"
    second["affected_scopes"] = ["GLOBAL"]
    second["blocking_groups"] = [
        {
            "blocking_reason": "INDEX_CONTINUITY_GAP",
            "affected_scopes": ["GLOBAL"],
        }
    ]
    second["global_continuity_epoch"] = 2
    summary["coverage"] = {
        "observation_interval_ms": 20,
        "known_complete_ms": 0,
        "known_degraded_ms": 0,
        "unknown_ms": 20,
        "no_applicable_scope_ms": 0,
        "coverage_partition_error_ms": 0,
    }
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["global_continuity"] = {
        "current_epoch": 2,
        "restart_count": 1,
        "restart_count_by_reason": {"CLOCK_GAP": 1},
        "restart_edges": [
            {
                "incident_id": 1,
                "from_epoch": 1,
                "to_epoch": 2,
                "trigger_cause": "TICKER_APPLIED",
                "reason": "CLOCK_GAP",
                "failure_domain": "CLOCK_INDEX",
                "affected_scopes": ["GLOBAL"],
                "boundary": {
                    "session_epoch": 1,
                    "ingress_seq": 1,
                    "received_monotonic_ms": 10,
                    "causal_seq": 1,
                },
            }
        ],
        "recovery_edges": [],
        "current_epoch_joint_evaluation_count_by_scope": [],
    }
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    witness["global_continuity_epoch"] = 2

    with pytest.raises(EvidenceError, match="epoch edge"):
        validate_run_summary(summary)


def test_schema_three_rejects_all_unknown_empty_count_joint_witness() -> None:
    summary = current_summary_object(
        segments=(
            CoverageSegment(
                0,
                20,
                CoverageState.UNKNOWN,
                reason="RUNTIME_START",
                blocking_reason="RUNTIME_START_PENDING",
                affected_scopes=("GLOBAL",),
                global_continuity_epoch=1,
            ),
        )
    )
    attach_joint_witness(summary, first_ms=10)

    with pytest.raises(EvidenceError, match=r"KNOWN_COMPLETE|counts_by_scope|joint"):
        validate_run_summary(summary)


def test_schema_three_joint_witness_binds_nonzero_scope_count() -> None:
    summary = current_summary_object()
    attach_joint_witness(summary, joint_count=0)

    with pytest.raises(EvidenceError, match=r"joint|full-formula|counts_by_scope"):
        validate_run_summary(summary)


def test_schema_three_joint_witness_binds_exact_current_epoch_evaluation_boundary() -> None:
    summary = current_summary_object()
    attach_joint_witness(summary, joint_count=1)
    validate_run_summary(summary)
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    rows = continuity["current_epoch_joint_evaluation_count_by_scope"]
    assert isinstance(rows, list)
    first_boundary = rows[0]["first_joint_evaluation_boundary"]
    assert isinstance(first_boundary, dict)
    first_boundary["causal_seq"] = 2

    with pytest.raises(EvidenceError, match=r"current.epoch|joint|boundary"):
        validate_run_summary(summary)


def test_schema_three_joint_witness_binds_exact_formula_instrument_identity() -> None:
    summary = current_summary_object()
    attach_joint_witness(summary, joint_count=1)
    validate_run_summary(summary)
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    formula_instrument = witness["formula_instrument"]
    assert isinstance(formula_instrument, dict)
    formula_instrument["instrument_name"] = "NON_EXISTENT"

    with pytest.raises(EvidenceError, match=r"current.epoch|joint|instrument"):
        validate_run_summary(summary)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("expiration_timestamp_ms", 3_600_001),
        ("option_type", "put"),
        ("tte_band_id", "other-band"),
    ),
)
def test_schema_three_joint_witness_binds_every_exact_scope_identity_field(
    field: str,
    replacement: object,
) -> None:
    summary = current_summary_object()
    attach_joint_witness(summary, joint_count=1)
    validate_run_summary(summary)
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    scope = witness["scope"]
    formula_instrument = witness["formula_instrument"]
    assert isinstance(scope, dict)
    assert isinstance(formula_instrument, dict)
    scope[field] = replacement
    formula_instrument[field] = replacement

    with pytest.raises(EvidenceError, match=r"current.epoch|joint|scope|counts"):
        validate_run_summary(summary)


def test_schema_three_joint_witness_must_fall_in_known_complete_segment() -> None:
    summary = current_summary_object(
        segments=(
            CoverageSegment(
                0,
                20,
                CoverageState.UNKNOWN,
                reason="RUNTIME_START",
                blocking_reason="RUNTIME_START_PENDING",
                affected_scopes=("GLOBAL",),
                global_continuity_epoch=1,
            ),
        )
    )
    attach_joint_witness(summary, first_ms=10, joint_count=1)

    with pytest.raises(EvidenceError, match="KNOWN_COMPLETE"):
        validate_run_summary(summary)


def test_schema_three_rejects_current_epoch_witness_without_strict_recovery() -> None:
    summary = epoch_two_summary(recovery_ms=None, witness_ms=15)

    with pytest.raises(EvidenceError, match=r"recover|incident"):
        validate_run_summary(summary)


def test_schema_three_rejects_witness_that_precedes_latest_recovery() -> None:
    summary = epoch_two_summary(recovery_ms=18, witness_ms=15)

    with pytest.raises(EvidenceError, match=r"recover|witness"):
        validate_run_summary(summary)


def test_schema_three_recovery_must_be_strictly_later_than_restart() -> None:
    summary = epoch_two_summary(recovery_ms=10)

    with pytest.raises(EvidenceError, match=r"strict|recover|restart"):
        validate_run_summary(summary)


def test_schema_three_recovery_must_be_inside_runtime_interval() -> None:
    summary = epoch_two_summary(recovery_ms=21)

    with pytest.raises(EvidenceError, match=r"runtime|interval|recover"):
        validate_run_summary(summary)


def test_schema_three_rejects_historical_joint_count_after_epoch_restart() -> None:
    summary = epoch_two_summary(recovery_ms=12, witness_ms=15)
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    continuity["current_epoch_joint_evaluation_count_by_scope"] = []

    with pytest.raises(EvidenceError, match=r"current.epoch|joint|scope"):
        validate_run_summary(summary)


def test_schema_three_rejects_second_restart_before_incident_recovery() -> None:
    summary = current_summary_object()
    summary["coverage_segments"] = [
        {
            "start_monotonic_ms": 0,
            "end_monotonic_ms": 5,
            "state": "UNKNOWN",
            "trigger_cause": "RUNTIME_START",
            "blocking_reason": "RUNTIME_START_PENDING",
            "affected_scopes": ["GLOBAL"],
            "blocking_groups": [
                {
                    "blocking_reason": "RUNTIME_START_PENDING",
                    "affected_scopes": ["GLOBAL"],
                }
            ],
            "global_continuity_epoch": 1,
        },
        {
            "start_monotonic_ms": 5,
            "end_monotonic_ms": 10,
            "state": "UNKNOWN",
            "trigger_cause": "CLOCK_GAP",
            "blocking_reason": "CLOCK_GAP",
            "affected_scopes": ["GLOBAL"],
            "blocking_groups": [
                {
                    "blocking_reason": "CLOCK_GAP",
                    "affected_scopes": ["GLOBAL"],
                }
            ],
            "global_continuity_epoch": 2,
        },
        {
            "start_monotonic_ms": 10,
            "end_monotonic_ms": 20,
            "state": "UNKNOWN",
            "trigger_cause": "INDEX_CONTINUITY_GAP",
            "blocking_reason": "INDEX_CONTINUITY_GAP",
            "affected_scopes": ["GLOBAL"],
            "blocking_groups": [
                {
                    "blocking_reason": "INDEX_CONTINUITY_GAP",
                    "affected_scopes": ["GLOBAL"],
                }
            ],
            "global_continuity_epoch": 3,
        },
    ]
    summary["coverage"] = {
        "observation_interval_ms": 20,
        "known_complete_ms": 0,
        "known_degraded_ms": 0,
        "unknown_ms": 20,
        "no_applicable_scope_ms": 0,
        "coverage_partition_error_ms": 0,
    }
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["global_continuity"] = {
        "current_epoch": 3,
        "restart_count": 2,
        "restart_count_by_reason": {
            "CLOCK_GAP": 1,
            "INDEX_CONTINUITY_GAP": 1,
        },
        "restart_edges": [
            {
                "incident_id": 1,
                "from_epoch": 1,
                "to_epoch": 2,
                "trigger_cause": "CLOCK_GAP",
                "reason": "CLOCK_GAP",
                "failure_domain": "CLOCK_INDEX",
                "affected_scopes": ["GLOBAL"],
                "boundary": {
                    "session_epoch": 1,
                    "ingress_seq": 1,
                    "received_monotonic_ms": 5,
                    "causal_seq": 1,
                },
            },
            {
                "incident_id": 2,
                "from_epoch": 2,
                "to_epoch": 3,
                "trigger_cause": "INDEX_CONTINUITY_GAP",
                "reason": "INDEX_CONTINUITY_GAP",
                "failure_domain": "CLOCK_INDEX",
                "affected_scopes": ["GLOBAL"],
                "boundary": {
                    "session_epoch": 1,
                    "ingress_seq": 2,
                    "received_monotonic_ms": 10,
                    "causal_seq": 2,
                },
            },
        ],
        "recovery_edges": [],
        "current_epoch_joint_evaluation_count_by_scope": [],
    }
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    witness["global_continuity_epoch"] = 3

    with pytest.raises(EvidenceError, match=r"recover|incident"):
        validate_run_summary(summary)


def test_schema_three_rejects_illegal_restart_cause_domain_scope_tuple() -> None:
    summary = current_summary_object()
    summary["coverage_segments"] = [
        {
            "start_monotonic_ms": 0,
            "end_monotonic_ms": 10,
            "state": "UNKNOWN",
            "trigger_cause": "RUNTIME_START",
            "blocking_reason": "RUNTIME_START_PENDING",
            "affected_scopes": ["GLOBAL"],
            "blocking_groups": [
                {
                    "blocking_reason": "RUNTIME_START_PENDING",
                    "affected_scopes": ["GLOBAL"],
                }
            ],
            "global_continuity_epoch": 1,
        },
        {
            "start_monotonic_ms": 10,
            "end_monotonic_ms": 20,
            "state": "UNKNOWN",
            "trigger_cause": "TICKER_APPLIED",
            "blocking_reason": "CURRENT_SCOPE_INCOMPLETE",
            "affected_scopes": ["GLOBAL"],
            "blocking_groups": [
                {
                    "blocking_reason": "CURRENT_SCOPE_INCOMPLETE",
                    "affected_scopes": ["GLOBAL"],
                }
            ],
            "global_continuity_epoch": 2,
        },
    ]
    summary["coverage"] = {
        "observation_interval_ms": 20,
        "known_complete_ms": 0,
        "known_degraded_ms": 0,
        "unknown_ms": 20,
        "no_applicable_scope_ms": 0,
        "coverage_partition_error_ms": 0,
    }
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["global_continuity"] = {
        "current_epoch": 2,
        "restart_count": 1,
        "restart_count_by_reason": {"TICKER_APPLIED": 1},
        "restart_edges": [
            {
                "incident_id": 1,
                "from_epoch": 1,
                "to_epoch": 2,
                "trigger_cause": "TICKER_APPLIED",
                "reason": "TICKER_APPLIED",
                "failure_domain": "SESSION",
                "affected_scopes": ["GLOBAL"],
                "boundary": {
                    "session_epoch": 1,
                    "ingress_seq": 1,
                    "received_monotonic_ms": 10,
                    "causal_seq": 1,
                },
            }
        ],
        "recovery_edges": [],
        "current_epoch_joint_evaluation_count_by_scope": [],
    }
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    witness["global_continuity_epoch"] = 2

    with pytest.raises(EvidenceError, match=r"restart.*allowlist|cause.*domain.*scope"):
        validate_run_summary(summary)


def test_schema_three_accepts_exact_transport_session_restart_cause() -> None:
    summary = epoch_two_summary(recovery_ms=12)
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    second = segments[1]
    assert isinstance(second, dict)
    second["blocking_reason"] = "TRANSPORT_READ_FAILURE"
    second["blocking_groups"] = [
        {
            "blocking_reason": "TRANSPORT_READ_FAILURE",
            "affected_scopes": ["GLOBAL"],
        }
    ]
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    continuity["restart_count_by_reason"] = {"TRANSPORT_READ_FAILURE": 1}
    restart = continuity["restart_edges"][0]
    assert isinstance(restart, dict)
    restart["reason"] = "TRANSPORT_READ_FAILURE"
    restart["failure_domain"] = "SESSION"

    validate_run_summary(summary)


def test_current_schema_restart_root_trigger_is_exactly_cross_bound() -> None:
    summary = epoch_two_summary(recovery_ms=12)
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    restarted = segments[1]
    assert isinstance(restarted, dict)
    restarted["trigger_cause"] = "OPTION_BOOK_FACT"
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    restart = continuity["restart_edges"][0]
    assert isinstance(restart, dict)
    restart["trigger_cause"] = "OPTION_BOOK_FACT"

    validate_run_summary(summary)

    forged = json.loads(json.dumps(summary))
    forged["operational_diagnostics"]["global_continuity"]["restart_edges"][0]["trigger_cause"] = (
        "TICKER_APPLIED"
    )
    with pytest.raises(EvidenceError, match="trigger"):
        validate_run_summary(forged)


def test_schema_six_accepts_same_epoch_index_window_gap_scope_expansion() -> None:
    summary = index_window_gap_scope_split_summary()
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    assert segments[1]["blocking_groups"] == [
        {
            "blocking_reason": "INDEX_WINDOW_GAP",
            "affected_scopes": ["SCOPE:3600000:call:band-a"],
        }
    ]
    assert segments[2]["blocking_groups"] == [
        {
            "blocking_reason": "INDEX_WINDOW_GAP",
            "affected_scopes": [
                "SCOPE:3600000:call:band-a",
                "SCOPE:7200000:call:band-b",
            ],
        }
    ]
    validate_run_summary(summary)


def test_same_epoch_index_window_gap_split_keeps_restart_scope_cross_binding() -> None:
    summary = index_window_gap_scope_split_summary()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    restart = continuity["restart_edges"][0]
    assert isinstance(restart, dict)
    restart["affected_scopes"] = ["SCOPE:7200000:call:band-b"]

    with pytest.raises(EvidenceError, match=r"restart trigger and effect"):
        validate_run_summary(summary)


def test_index_window_gap_group_cannot_extend_beyond_recorded_recovery() -> None:
    summary = index_window_gap_scope_split_summary()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    continuity["recovery_edges"] = [
        {
            "incident_id": 1,
            "boundary": {
                "session_epoch": 1,
                "ingress_seq": 3,
                "received_monotonic_ms": 16,
                "causal_seq": 3,
            },
        }
    ]

    with pytest.raises(EvidenceError, match=r"beyond incident recovery"):
        validate_run_summary(summary)


def test_current_schema_rejects_queue_lag_as_global_continuity_restart() -> None:
    summary = epoch_two_summary(recovery_ms=12)
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    blocked = segments[1]
    assert isinstance(blocked, dict)
    blocked["trigger_cause"] = "QUEUE_LAG_DEADLINE"
    blocked["blocking_reason"] = "QUEUE_LAG_CURRENTNESS"
    blocked["blocking_groups"] = [
        {
            "blocking_reason": "QUEUE_LAG_CURRENTNESS",
            "affected_scopes": ["GLOBAL"],
        }
    ]
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    continuity["restart_count_by_reason"] = {"QUEUE_LAG_DEADLINE": 1}
    restart = continuity["restart_edges"][0]
    assert isinstance(restart, dict)
    restart["reason"] = "QUEUE_LAG_DEADLINE"
    restart["failure_domain"] = "SESSION"

    with pytest.raises(EvidenceError, match="allowlist"):
        validate_run_summary(summary)


def test_schema_three_restart_cause_cannot_appear_without_an_epoch_edge() -> None:
    summary = current_summary_object()
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    second = segments[1]
    assert isinstance(second, dict)
    second["state"] = "UNKNOWN"
    second["blocking_reason"] = "TRANSPORT_READ_FAILURE"
    second["affected_scopes"] = ["GLOBAL"]
    second["blocking_groups"] = [
        {
            "blocking_reason": "TRANSPORT_READ_FAILURE",
            "affected_scopes": ["GLOBAL"],
        }
    ]
    summary["coverage"] = {
        "observation_interval_ms": 20,
        "known_complete_ms": 0,
        "known_degraded_ms": 0,
        "unknown_ms": 20,
        "no_applicable_scope_ms": 0,
        "coverage_partition_error_ms": 0,
    }

    with pytest.raises(EvidenceError, match=r"currentness blocker.*epoch edge"):
        validate_run_summary(summary)


def terminal_restart_summary() -> dict[str, object]:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    continuity.update(
        {
            "current_epoch": 2,
            "restart_count": 1,
            "restart_count_by_reason": {"INDEX_SOURCE_STALE": 1},
            "restart_edges": [
                {
                    "incident_id": 1,
                    "from_epoch": 1,
                    "to_epoch": 2,
                    "trigger_cause": "CLEAN_STOP",
                    "reason": "INDEX_SOURCE_STALE",
                    "failure_domain": "CLOCK_INDEX",
                    "affected_scopes": ["GLOBAL"],
                    "boundary": {
                        "session_epoch": 1,
                        "ingress_seq": 3,
                        "received_monotonic_ms": 20,
                        "causal_seq": 3,
                    },
                }
            ],
            "recovery_edges": [],
            "current_epoch_joint_evaluation_count_by_scope": [],
        }
    )
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    witness["global_continuity_epoch"] = 2
    _set_retained_publication_rows(
        summary,
        [
            _publication_row(
                start_ms=12,
                end_ms=20,
                disposition="CURRENTNESS_LOST",
                currentness_loss_reason="INDEX_SOURCE_STALE",
            )
        ],
    )
    return summary


def test_terminal_restart_at_clean_stop_needs_no_zero_duration_coverage_segment() -> None:
    validate_run_summary(terminal_restart_summary())


def test_terminal_restart_without_coverage_cannot_claim_recovery() -> None:
    summary = terminal_restart_summary()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    continuity["recovery_edges"] = [
        {
            "incident_id": 1,
            "boundary": {
                "session_epoch": 1,
                "ingress_seq": 4,
                "received_monotonic_ms": 20,
                "causal_seq": 4,
            },
        }
    ]

    with pytest.raises(EvidenceError, match="coverage continuity epoch"):
        validate_run_summary(summary)


def test_schema_three_rpc_method_uses_exact_allowlist() -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    rpc_rows = diagnostics["rpc_by_method"]
    assert isinstance(rpc_rows, list)
    rpc_rows.append(
        {
            "method": "public/not_authorized",
            "scheduled_count": 1,
            "sent_count": 1,
            "success_count": 1,
            "error_count": 0,
            "deadline_late_count": 0,
            "retired_count": 0,
            "censored_count": 0,
            "pre_send_error_count": 0,
            "pre_send_deadline_late_count": 0,
            "pre_send_retired_count": 0,
            "pre_send_censored_count": 0,
            "post_send_success_count": 1,
            "post_send_error_count": 0,
            "post_send_deadline_late_count": 0,
            "post_send_retired_count": 0,
            "post_send_censored_count": 0,
            "rate_limit_count": 0,
            "latency_observation_count": 1,
            "latency_ms_sum": 1,
            "latency_ms_max": 1,
        }
    )

    with pytest.raises(EvidenceError, match="allowlist"):
        validate_run_summary(summary)


def test_schema_three_source_shape_rejects_unobserved_fabricated_consumed_field() -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    source_rows = diagnostics["source_shapes"]
    assert isinstance(source_rows, list)
    heartbeat = next(
        row for row in source_rows if isinstance(row, dict) and row.get("source") == "heartbeat"
    )
    heartbeat["consumed_fields"] = [{"key": "fabricated", "type": "string"}]

    with pytest.raises(EvidenceError, match=r"source|consumed|field"):
        validate_run_summary(summary)


@pytest.mark.parametrize(
    "consumed_field",
    (
        {"key": "fabricated", "type": "string"},
        {"key": "type", "type": "integer"},
    ),
)
def test_schema_three_source_shape_rejects_observed_field_outside_shared_spec(
    consumed_field: dict[str, str],
) -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    source_rows = diagnostics["source_shapes"]
    assert isinstance(source_rows, list)
    heartbeat = next(
        row for row in source_rows if isinstance(row, dict) and row.get("source") == "heartbeat"
    )
    heartbeat.update(
        {
            "observed_count": 1,
            "valid_count": 1,
            "invalid_count": 0,
            "validation": "VALID",
            "consumed_fields": [consumed_field],
        }
    )
    heartbeat_channel = next(
        row
        for row in diagnostics["channel_by_class"]
        if isinstance(row, dict) and row.get("channel_class") == "HEARTBEAT"
    )
    heartbeat_channel.update(
        {
            "received_count": 1,
            "processed_count": 1,
            "received_rate_per_second": "50",
            "processed_rate_per_second": "50",
        }
    )
    ingress = diagnostics["ingress"]
    assert isinstance(ingress, dict)
    ingress.update({"received_envelope_count": 1, "reduced_envelope_count": 1})

    with pytest.raises(EvidenceError, match=r"source|consumed|field|specification"):
        validate_run_summary(summary)


def test_schema_three_censored_interval_must_end_at_clean_stop() -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    ledger = diagnostics["option_local_availability"]
    assert isinstance(ledger, dict)
    ledger.update(
        {
            "unavailable_count_by_reason": {"TICKER_SOURCE_STALE": 1},
            "recovery_count_by_reason": {},
            "end_count_by_disposition": {
                "RECOVERED": 0,
                "REASON_CHANGED": 0,
                "CENSORED_AT_STOP": 1,
            },
            "intervals": [
                {
                    "instrument_name": "SHORT",
                    "generation": 1,
                    "reason": "TICKER_SOURCE_STALE",
                    "start_monotonic_ms": 10,
                    "end_monotonic_ms": 19,
                    "duration_ms": 9,
                    "end_disposition": "CENSORED_AT_STOP",
                    "global_continuity_epoch": 1,
                }
            ],
        }
    )

    with pytest.raises(EvidenceError, match=r"CENSORED_AT_STOP.*clean stop"):
        validate_run_summary(summary)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda event: event.update({"short_instrument_name": "LONG"}),
            "short leg",
        ),
        (
            lambda event: event.update({"detector_causal_seq": 9}),
            "causal",
        ),
    ],
)
def test_evidence_directory_cross_binds_atomic_to_anomaly(
    tmp_path: Path,
    mutate: object,
    message: str,
) -> None:
    anomaly = project_anomaly_event(anomaly_evidence())
    atomic = project_atomic_event(atomic_evidence())
    assert callable(mutate)
    mutate(atomic)
    (tmp_path / "anomaly.json").write_text(json.dumps(anomaly), encoding="utf-8")
    (tmp_path / "atomic.json").write_text(json.dumps(atomic), encoding="utf-8")

    with pytest.raises(EvidenceError, match=message):
        validate_evidence_directory(tmp_path)


def test_atomic_event_requires_available_transition_in_owning_summary_scope(
    tmp_path: Path,
) -> None:
    anomaly = project_anomaly_event(anomaly_evidence())
    atomic = project_atomic_event(atomic_evidence())
    summary = current_summary_object()
    scope = ScopeCounts("sha256:" + "b" * 64, "call", "band")
    scope.applicable_instrument_count = 1
    scope.distinct_anomaly_episode_count = 1
    scope.anomaly_activation_transition_count = 1
    scope.anomaly_end_count_by_reason[EpisodeEndReason.CENSORED_AT_STOP.value] = 1
    summary["counts_by_scope"] = [scope.as_object()]
    summary["anomaly_end_count_by_reason"] = {
        EpisodeEndReason.CENSORED_AT_STOP.value: 1,
    }
    (tmp_path / "anomaly.json").write_text(json.dumps(anomaly), encoding="utf-8")
    (tmp_path / "atomic.json").write_text(json.dumps(atomic), encoding="utf-8")
    (tmp_path / "radar-run-summary.json").write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(EvidenceError, match=r"atomic|AVAILABLE|scope"):
        validate_evidence_directory(tmp_path)


def test_atomic_causal_invariant_allows_later_quote_only_when_detector_is_same_boundary() -> None:
    evidence_module.validate_atomic_causal_invariant(
        anomaly_activation_seq=10,
        detector_causal_seq=11,
        quote_causal_seq=11,
    )
    with pytest.raises(EvidenceError, match=r"detector.*quote|causal"):
        evidence_module.validate_atomic_causal_invariant(
            anomaly_activation_seq=10,
            detector_causal_seq=10,
            quote_causal_seq=11,
        )
    with pytest.raises(EvidenceError, match=r"activation|causal"):
        evidence_module.validate_atomic_causal_invariant(
            anomaly_activation_seq=12,
            detector_causal_seq=11,
            quote_causal_seq=11,
        )


def test_complete_writer_directory_accepts_anomaly_then_later_normalized_atomic_boundary(
    tmp_path: Path,
) -> None:
    writer = EvidenceWriter(
        tmp_path,
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
    )
    anomaly = project_anomaly_event(anomaly_evidence())
    later_atomic = project_atomic_event(
        replace(
            atomic_evidence(),
            detector_causal_seq=11,
            quote_causal_seq=11,
        )
    )

    writer.write_anomaly(anomaly)
    writer.write_atomic(later_atomic)
    scope = ScopeCounts("sha256:" + "b" * 64, "call", "band")
    scope.applicable_instrument_count = 1
    scope.distinct_anomaly_episode_count = 1
    scope.anomaly_activation_transition_count = 1
    scope.anomaly_end_count_by_reason[EpisodeEndReason.CENSORED_AT_STOP.value] = 1
    scope.known_active_duration_ms_sum_by_end_reason[EpisodeEndReason.CENSORED_AT_STOP.value] = 0
    scope.public_atomic_quote_state_transition_count[
        PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value
    ] = 1
    summary = current_summary_object()
    summary["counts_by_scope"] = [scope.as_object()]
    summary["anomaly_end_count_by_reason"] = {
        reason.value: int(reason is EpisodeEndReason.CENSORED_AT_STOP)
        for reason in EpisodeEndReason
    }
    summary["known_active_duration_ms_sum_by_end_reason"] = {
        reason.value: 0 for reason in EpisodeEndReason
    }
    summary["public_atomic_quote_state_transition_count"] = {
        PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value: 1
    }
    writer.write_summary(summary)

    assert len(validate_evidence_directory(tmp_path)) == 3


def _current_publication_accounting_summary() -> dict[str, object]:
    summary = current_summary_object(
        segments=(
            CoverageSegment(
                0,
                3_600_000,
                CoverageState.KNOWN_COMPLETE,
                reason="TICKER_APPLIED",
                blocking_reason="NONE",
                affected_scopes=("OPTION:SHORT",),
                global_continuity_epoch=1,
            ),
        )
    )
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["index_baseline_publication"] = {
        "start_count_by_phase": {"TIME_BOUNDARY_PENDING": 1, "WATERMARK_PENDING": 0},
        "end_count_by_disposition": {
            "PUBLISHED": 1,
            "PHASE_CHANGED": 0,
            "CURRENTNESS_LOST": 0,
            "CENSORED_AT_STOP": 0,
        },
        "acceptance_window_ms": 3_600_000,
        "retained_interval_limit": 10_000,
        "outside_window_interval_count": 0,
        "outside_window_latest_end_monotonic_ms": None,
        "outside_window_interval_count_by_phase_and_disposition": {
            "TIME_BOUNDARY_PENDING": {
                "PUBLISHED": 0,
                "PHASE_CHANGED": 0,
                "CURRENTNESS_LOST": 0,
                "CENSORED_AT_STOP": 0,
            },
            "WATERMARK_PENDING": {
                "PUBLISHED": 0,
                "PHASE_CHANGED": 0,
                "CURRENTNESS_LOST": 0,
                "CENSORED_AT_STOP": 0,
            },
        },
        "omitted_interval_count": 0,
        "omitted_interval_count_by_phase_and_disposition": {
            "TIME_BOUNDARY_PENDING": {
                "PUBLISHED": 0,
                "PHASE_CHANGED": 0,
                "CURRENTNESS_LOST": 0,
                "CENSORED_AT_STOP": 0,
            },
            "WATERMARK_PENDING": {
                "PUBLISHED": 0,
                "PHASE_CHANGED": 0,
                "CURRENTNESS_LOST": 0,
                "CENSORED_AT_STOP": 0,
            },
        },
        "intervals": [
            {
                "phase": "TIME_BOUNDARY_PENDING",
                "published_tail_last_minute_start_ms": 3_000_000,
                "target_successor_minute_start_ms": 3_060_000,
                "start_monotonic_ms": 100,
                "end_monotonic_ms": 50_100,
                "duration_ms": 50_000,
                "end_disposition": "PUBLISHED",
                "global_continuity_epoch": 1,
                "currentness_loss": None,
            }
        ],
    }
    availability = diagnostics["option_local_availability"]
    assert isinstance(availability, dict)
    availability["omitted_interval_count"] = 0
    availability["intervals"] = []
    return summary


def test_current_publication_pending_overlaps_known_complete_without_reducing_effective_interval() -> (
    None
):
    result = operational_soak_window_accounting(_current_publication_accounting_summary())
    assert result["known_complete_ms"] == 3_600_000
    assert result["publication_pending_ms"] == 50_000
    assert result["global_currentness_incident_ms"] == 0
    assert result["effective_interval_ms"] == 3_600_000


def test_current_publication_pending_does_not_obey_sealed_partition_or_36_second_cap() -> None:
    result = operational_soak_window_accounting(_current_publication_accounting_summary())
    assert result["publication_pending_ms"] == 50_000
    assert result["publication_pending_ms"] > 36_000
    assert result["effective_interval_ms"] == 3_600_000
    assert result["known_complete_ms"] + result["global_currentness_incident_ms"] == 3_600_000


def test_current_omitted_publication_interval_rejects_soak_accounting() -> None:
    summary = _current_publication_accounting_summary()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    publication = diagnostics["index_baseline_publication"]
    assert isinstance(publication, dict)
    publication["omitted_interval_count"] = 1
    publication["omitted_interval_count_by_phase_and_disposition"]["TIME_BOUNDARY_PENDING"][
        "PUBLISHED"
    ] = 1
    with pytest.raises(EvidenceError):
        operational_soak_window_accounting(summary)


def test_sealed_version_five_accounting_is_legacy_only_and_current_rejects_fixture() -> None:
    summary = sealed_version_five_summary_object(
        segments=(
            CoverageSegment(
                0,
                3_600_000,
                CoverageState.KNOWN_COMPLETE,
                reason="TICKER_APPLIED",
                blocking_reason="NONE",
                affected_scopes=("OPTION:SHORT",),
                global_continuity_epoch=1,
            ),
        )
    )
    assert sealed_version_five_operational_soak_window_accounting(summary)
    with pytest.raises(EvidenceError):
        operational_soak_window_accounting(summary)


def test_sealed_version_five_directory_has_an_explicit_read_only_route(
    tmp_path: Path,
) -> None:
    summary = sealed_version_five_summary_object()
    (tmp_path / "run-summary.json").write_text(json.dumps(summary), encoding="utf-8")

    assert validate_sealed_version_five_evidence_directory(tmp_path) == (summary,)
    with pytest.raises(EvidenceError, match="diagnostics schema 6"):
        validate_evidence_directory(tmp_path)


def _publication_row(
    *,
    phase: str = "TIME_BOUNDARY_PENDING",
    published_minute_ms: int = 3_000_000,
    start_ms: int = 100,
    end_ms: int = 200,
    disposition: str = "PUBLISHED",
    epoch: int = 1,
    currentness_loss_reason: str | None = None,
) -> dict[str, object]:
    return {
        "phase": phase,
        "published_tail_last_minute_start_ms": published_minute_ms,
        "target_successor_minute_start_ms": published_minute_ms + 60_000,
        "start_monotonic_ms": start_ms,
        "end_monotonic_ms": end_ms,
        "duration_ms": end_ms - start_ms,
        "end_disposition": disposition,
        "global_continuity_epoch": epoch,
        "currentness_loss": (
            None
            if currentness_loss_reason is None
            else {
                "reason": currentness_loss_reason,
                "boundary": {
                    "session_epoch": 1,
                    "ingress_seq": 3,
                    "received_monotonic_ms": end_ms,
                    "causal_seq": 3,
                },
            }
        ),
    }


def _set_retained_publication_rows(
    summary: dict[str, object],
    rows: list[dict[str, object]],
) -> None:
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    publication = diagnostics["index_baseline_publication"]
    assert isinstance(publication, dict)
    starts = {
        "TIME_BOUNDARY_PENDING": 0,
        "WATERMARK_PENDING": 0,
    }
    ends = {
        "PUBLISHED": 0,
        "PHASE_CHANGED": 0,
        "CURRENTNESS_LOST": 0,
        "CENSORED_AT_STOP": 0,
    }
    for row in rows:
        phase = row["phase"]
        disposition = row["end_disposition"]
        assert isinstance(phase, str)
        assert isinstance(disposition, str)
        starts[phase] += 1
        ends[disposition] += 1
    publication["start_count_by_phase"] = starts
    publication["end_count_by_disposition"] = ends
    publication["outside_window_interval_count"] = 0
    publication["outside_window_latest_end_monotonic_ms"] = None
    publication["omitted_interval_count"] = 0
    for matrix_name in (
        "outside_window_interval_count_by_phase_and_disposition",
        "omitted_interval_count_by_phase_and_disposition",
    ):
        matrix = publication[matrix_name]
        assert isinstance(matrix, dict)
        for dispositions in matrix.values():
            assert isinstance(dispositions, dict)
            for disposition in dispositions:
                dispositions[disposition] = 0
    publication["intervals"] = rows


def _empty_publication_summary(*, clean_stop_ms: int = 3_600_000) -> dict[str, object]:
    summary = current_summary_object(
        segments=(
            CoverageSegment(
                0,
                clean_stop_ms,
                CoverageState.KNOWN_COMPLETE,
                reason="TICKER_APPLIED",
                blocking_reason="NONE",
                affected_scopes=("OPTION:SHORT",),
                global_continuity_epoch=1,
            ),
        )
    )
    _set_retained_publication_rows(summary, [])
    return summary


def test_current_publication_chain_allows_same_epoch_multi_minute_advance() -> None:
    summary = _empty_publication_summary()
    _set_retained_publication_rows(
        summary,
        [
            _publication_row(start_ms=100, end_ms=200),
            _publication_row(
                published_minute_ms=3_180_000,
                start_ms=200,
                end_ms=300,
            ),
        ],
    )

    validate_run_summary(summary)


def test_currentness_loss_is_its_own_transition_inside_an_active_incident() -> None:
    summary = index_window_gap_scope_split_summary()
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    final_segment = segments[-1]
    assert isinstance(final_segment, dict)
    final_segment.update(
        {
            "trigger_cause": "TIME_BOUNDARY",
            "blocking_reason": "INDEX_SOURCE_STALE",
            "affected_scopes": ["GLOBAL"],
            "blocking_groups": [
                {
                    "blocking_reason": "INDEX_SOURCE_STALE",
                    "affected_scopes": ["GLOBAL"],
                }
            ],
        }
    )
    _set_retained_publication_rows(
        summary,
        [
            _publication_row(
                start_ms=12,
                end_ms=15,
                disposition="CURRENTNESS_LOST",
                epoch=2,
                currentness_loss_reason="INDEX_SOURCE_STALE",
            )
        ],
    )

    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    continuity = diagnostics["global_continuity"]
    assert isinstance(continuity, dict)
    assert len(continuity["restart_edges"]) == 1
    validate_run_summary(summary)


@pytest.mark.parametrize(
    ("currentness_loss", "message"),
    [
        (None, "requires exact cause"),
        (
            {
                "reason": "TICKER_SOURCE_STALE",
                "boundary": {
                    "session_epoch": 1,
                    "ingress_seq": 3,
                    "received_monotonic_ms": 15,
                    "causal_seq": 3,
                },
            },
            "invalidating reason",
        ),
    ],
)
def test_currentness_loss_rejects_missing_or_non_global_invalidation(
    currentness_loss: object,
    message: str,
) -> None:
    summary = _empty_publication_summary()
    row = _publication_row(
        start_ms=12,
        end_ms=15,
        disposition="CURRENTNESS_LOST",
        currentness_loss_reason="INDEX_SOURCE_STALE",
    )
    row["currentness_loss"] = currentness_loss
    _set_retained_publication_rows(summary, [row])

    with pytest.raises(EvidenceError, match=message):
        validate_run_summary(summary)


def test_currentness_loss_rejects_a_boundary_that_does_not_end_its_row() -> None:
    summary = _empty_publication_summary()
    row = _publication_row(
        start_ms=12,
        end_ms=15,
        disposition="CURRENTNESS_LOST",
        currentness_loss_reason="INDEX_SOURCE_STALE",
    )
    loss = row["currentness_loss"]
    assert isinstance(loss, dict)
    boundary = loss["boundary"]
    assert isinstance(boundary, dict)
    boundary["received_monotonic_ms"] = 16
    _set_retained_publication_rows(summary, [row])

    with pytest.raises(EvidenceError, match="boundary does not match interval end"):
        validate_run_summary(summary)


def test_non_currentness_disposition_rejects_currentness_loss_attribution() -> None:
    summary = _empty_publication_summary()
    row = _publication_row(
        start_ms=12,
        end_ms=15,
        disposition="PUBLISHED",
        currentness_loss_reason="INDEX_SOURCE_STALE",
    )
    _set_retained_publication_rows(summary, [row])

    with pytest.raises(EvidenceError, match="cannot carry currentness loss"):
        validate_run_summary(summary)


def test_currentness_loss_rejects_a_conflicting_exact_restart_edge() -> None:
    summary = index_window_gap_scope_split_summary()
    row = _publication_row(
        start_ms=5,
        end_ms=10,
        disposition="CURRENTNESS_LOST",
        epoch=1,
        currentness_loss_reason="CLOCK_GAP",
    )
    loss = row["currentness_loss"]
    assert isinstance(loss, dict)
    loss["boundary"] = {
        "session_epoch": 1,
        "ingress_seq": 1,
        "received_monotonic_ms": 10,
        "causal_seq": 1,
    }
    _set_retained_publication_rows(
        summary,
        [row],
    )

    with pytest.raises(EvidenceError, match="conflicts with its restart edge"):
        validate_run_summary(summary)


def test_same_millisecond_different_fact_is_not_misbound_to_a_restart() -> None:
    summary = index_window_gap_scope_split_summary()
    row = _publication_row(
        start_ms=5,
        end_ms=10,
        disposition="CURRENTNESS_LOST",
        epoch=1,
        currentness_loss_reason="INDEX_WINDOW_GAP",
    )
    loss = row["currentness_loss"]
    assert isinstance(loss, dict)
    loss["boundary"] = {
        "session_epoch": 1,
        "ingress_seq": 2,
        "received_monotonic_ms": 10,
        "causal_seq": 2,
    }
    _set_retained_publication_rows(summary, [row])

    with pytest.raises(EvidenceError, match="lacks an owning restart or active incident"):
        validate_run_summary(summary)


def test_orphan_currentness_loss_at_clean_stop_is_rejected() -> None:
    summary = _empty_publication_summary(clean_stop_ms=20)
    _set_retained_publication_rows(
        summary,
        [
            _publication_row(
                start_ms=12,
                end_ms=20,
                disposition="CURRENTNESS_LOST",
                currentness_loss_reason="SESSION_GAP",
            )
        ],
    )

    with pytest.raises(EvidenceError, match="lacks an owning restart or active incident"):
        validate_run_summary(summary)


def test_active_incident_owns_currentness_loss_at_clean_stop() -> None:
    summary = index_window_gap_scope_split_summary()
    _set_retained_publication_rows(
        summary,
        [
            _publication_row(
                start_ms=12,
                end_ms=20,
                disposition="CURRENTNESS_LOST",
                epoch=2,
                currentness_loss_reason="SESSION_GAP",
            )
        ],
    )

    validate_run_summary(summary)


def test_recovered_incident_cannot_own_a_later_currentness_loss() -> None:
    summary = epoch_two_summary(recovery_ms=12)
    _set_retained_publication_rows(
        summary,
        [
            _publication_row(
                start_ms=13,
                end_ms=15,
                disposition="CURRENTNESS_LOST",
                epoch=2,
                currentness_loss_reason="INDEX_SOURCE_STALE",
            )
        ],
    )

    with pytest.raises(EvidenceError, match="lacks an owning restart or active incident"):
        validate_run_summary(summary)


@pytest.mark.parametrize("next_published_minute_ms", [3_000_000, 2_940_000])
def test_current_publication_chain_rejects_same_epoch_repeat_or_rollback(
    next_published_minute_ms: int,
) -> None:
    summary = _empty_publication_summary()
    _set_retained_publication_rows(
        summary,
        [
            _publication_row(start_ms=100, end_ms=200),
            _publication_row(
                published_minute_ms=next_published_minute_ms,
                start_ms=300,
                end_ms=400,
            ),
        ],
    )

    with pytest.raises(EvidenceError, match="strictly advance"):
        validate_run_summary(summary)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [
                _publication_row(start_ms=200, end_ms=300),
                _publication_row(
                    published_minute_ms=3_060_000,
                    start_ms=100,
                    end_ms=150,
                ),
            ],
            "not sorted",
        ),
        (
            [
                _publication_row(start_ms=100, end_ms=300),
                _publication_row(
                    published_minute_ms=3_060_000,
                    start_ms=200,
                    end_ms=400,
                ),
            ],
            "overlap",
        ),
        (
            [
                _publication_row(
                    phase="WATERMARK_PENDING",
                    disposition="PHASE_CHANGED",
                )
            ],
            "PHASE_CHANGED requires TIME",
        ),
        (
            [
                _publication_row(
                    end_ms=3_599_999,
                    disposition="CENSORED_AT_STOP",
                )
            ],
            "end exactly at clean stop",
        ),
    ],
)
def test_current_publication_ledger_rejects_order_phase_and_stop_forgeries(
    rows: list[dict[str, object]],
    message: str,
) -> None:
    summary = _empty_publication_summary()
    _set_retained_publication_rows(summary, deepcopy(rows))

    with pytest.raises(EvidenceError, match=message):
        validate_run_summary(summary)


def test_current_coverage_rejects_legacy_index_pending_blockers() -> None:
    with pytest.raises(EvidenceError, match="cannot use index publication pending blockers"):
        current_summary_object(
            segments=(
                CoverageSegment(
                    0,
                    100,
                    CoverageState.UNKNOWN,
                    reason="TIME_BOUNDARY",
                    blocking_reason="INDEX_TIME_BOUNDARY_PENDING",
                    affected_scopes=("OPTION:SHORT",),
                    global_continuity_epoch=1,
                ),
            )
        )


def _set_compressed_publication_count(
    summary: dict[str, object],
    *,
    bucket: str,
    phase: str,
    disposition: str,
) -> None:
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    publication = diagnostics["index_baseline_publication"]
    assert isinstance(publication, dict)
    count_name = f"{bucket}_interval_count"
    matrix_name = f"{bucket}_interval_count_by_phase_and_disposition"
    publication[count_name] = 1
    if bucket == "outside_window":
        publication["outside_window_latest_end_monotonic_ms"] = 3_000_000
    matrix = publication[matrix_name]
    assert isinstance(matrix, dict)
    phase_counts = matrix[phase]
    assert isinstance(phase_counts, dict)
    phase_counts[disposition] = 1
    starts = publication["start_count_by_phase"]
    ends = publication["end_count_by_disposition"]
    assert isinstance(starts, dict)
    assert isinstance(ends, dict)
    starts[phase] = 1
    ends[disposition] = 1


@pytest.mark.parametrize("bucket", ["outside_window", "omitted"])
@pytest.mark.parametrize(
    ("phase", "disposition", "message"),
    [
        (
            "TIME_BOUNDARY_PENDING",
            "CENSORED_AT_STOP",
            "compressed publication ledger cannot contain CENSORED_AT_STOP",
        ),
        (
            "WATERMARK_PENDING",
            "PHASE_CHANGED",
            "WATERMARK_PENDING cannot end with PHASE_CHANGED",
        ),
    ],
)
def test_current_compressed_publication_matrices_reject_impossible_cells(
    bucket: str,
    phase: str,
    disposition: str,
    message: str,
) -> None:
    summary = _empty_publication_summary(clean_stop_ms=7_200_000)
    _set_compressed_publication_count(
        summary,
        bucket=bucket,
        phase=phase,
        disposition=disposition,
    )

    with pytest.raises(EvidenceError, match=message):
        validate_run_summary(summary)


def test_current_publication_ledger_rejects_more_than_one_stop_censor() -> None:
    summary = _empty_publication_summary(clean_stop_ms=7_200_000)
    _set_retained_publication_rows(
        summary,
        [
            _publication_row(
                start_ms=7_100_000,
                end_ms=7_200_000,
                disposition="CENSORED_AT_STOP",
            )
        ],
    )
    _set_compressed_publication_count(
        summary,
        bucket="outside_window",
        phase="TIME_BOUNDARY_PENDING",
        disposition="CENSORED_AT_STOP",
    )
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    publication = diagnostics["index_baseline_publication"]
    assert isinstance(publication, dict)
    starts = publication["start_count_by_phase"]
    ends = publication["end_count_by_disposition"]
    assert isinstance(starts, dict)
    assert isinstance(ends, dict)
    starts["TIME_BOUNDARY_PENDING"] = 2
    ends["CENSORED_AT_STOP"] = 2

    with pytest.raises(EvidenceError, match="at most one CENSORED_AT_STOP"):
        validate_run_summary(summary)
