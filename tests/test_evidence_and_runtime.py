from __future__ import annotations

import asyncio
import json
import os
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
from radar_runtime.deribit_public import InboundEnvelope
from radar_runtime.identity import (
    StartupGuardError,
    prepare_evidence_directory,
    validate_clean_git_outputs,
)
from radar_runtime.runtime import (
    CausalCause,
    CausalCommit,
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
    CoverageSegment,
    CoverageState,
    EvidenceError,
    EvidenceWriter,
    project_anomaly_event,
    project_atomic_event,
    project_run_summary,
    ratio_or_none,
    validate_anomaly_event,
    validate_atomic_event,
    validate_evidence_directory,
    validate_legacy_evidence_directory,
    validate_legacy_run_summary,
    validate_run_summary,
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
        detector_causal_seq=10,
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
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.KNOWN_COMPLETE,
            reason="TICKER_APPLIED",
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
    diagnostics["operational_diagnostics_schema_version"] = 3
    diagnostics["global_continuity"] = {
        "current_epoch": 1,
        "restart_count": 0,
        "restart_count_by_reason": {},
        "restart_edges": [],
        "recovery_edges": [],
    }
    diagnostics["rpc_orphan_late_wire_count"] = 0
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
        "retained_interval_limit": 256,
        "omitted_interval_count": 0,
        "omitted_interval_count_by_reason": {},
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
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.KNOWN_COMPLETE,
            reason="TICKER_APPLIED",
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
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.KNOWN_COMPLETE,
            reason="TICKER_APPLIED",
            affected_scopes=("OPTION:SHORT",),
            global_continuity_epoch=1,
        ),
    ),
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
        operational_diagnostics=current_operational_diagnostics(),
    )


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


def test_coverage_segments_reject_overlap_gap_negative_and_mismatched_totals() -> None:
    with pytest.raises(EvidenceError, match="overlap or contain a gap"):
        summary_object(
            segments=(
                CoverageSegment(
                    0,
                    10,
                    CoverageState.UNKNOWN,
                    reason="RUNTIME_START",
                    affected_scopes=("GLOBAL",),
                    global_continuity_epoch=1,
                ),
                CoverageSegment(
                    9,
                    20,
                    CoverageState.KNOWN_COMPLETE,
                    reason="TICKER_APPLIED",
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
                    affected_scopes=("GLOBAL",),
                    global_continuity_epoch=1,
                ),
                CoverageSegment(
                    11,
                    20,
                    CoverageState.KNOWN_COMPLETE,
                    reason="TICKER_APPLIED",
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
        global_continuity_epoch=2,
        force=True,
    )

    assert ledger.close(20) == (
        CoverageSegment(
            0,
            10,
            CoverageState.UNKNOWN,
            reason="RUNTIME_START",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=1,
        ),
        CoverageSegment(
            10,
            20,
            CoverageState.UNKNOWN,
            reason="INDEX_CONTINUITY_GAP",
            affected_scopes=("GLOBAL",),
            global_continuity_epoch=2,
        ),
    )


def test_schema_three_accepts_bounded_option_local_coverage_scope() -> None:
    summary = current_summary_object()
    coverage_segments = summary["coverage_segments"]
    assert isinstance(coverage_segments, list)
    first = coverage_segments[0]
    assert isinstance(first, dict)
    first["affected_scopes"] = ["OPTION_LOCAL"]

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


def test_version_three_diagnostics_and_attributed_coverage_are_strict() -> None:
    summary = current_summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    assert diagnostics["operational_diagnostics_schema_version"] == 3
    assert "price" not in json.dumps(diagnostics)
    assert summary["coverage_segments"] == [
        {
            "start_monotonic_ms": 0,
            "end_monotonic_ms": 10,
            "state": "UNKNOWN",
            "reason": "RUNTIME_START",
            "affected_scopes": ["GLOBAL"],
            "global_continuity_epoch": 1,
        },
        {
            "start_monotonic_ms": 10,
            "end_monotonic_ms": 20,
            "state": "KNOWN_COMPLETE",
            "reason": "TICKER_APPLIED",
            "affected_scopes": ["OPTION:SHORT"],
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

    assert diagnostics["operational_diagnostics_schema_version"] == 3
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

    with pytest.raises(EvidenceError, match="schema version"):
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

    class FailingClient:
        session_epoch = 1
        queue_high_water_frames = 0
        overflow_count = 0
        enqueued_envelope_count = 0
        received_frame_count = 0

        async def send_request(self, **_kwargs: object) -> None:
            self.queue_high_water_frames = 7
            self.enqueued_envelope_count = 7
            self.received_frame_count = 7
            raise RuntimeError("sender exploded")

        async def next_envelope(
            self,
            timeout_seconds: float | None = None,
        ) -> InboundEnvelope:
            del timeout_seconds
            await asyncio.sleep(0)
            raise TimeoutError

    client = FailingClient()
    with pytest.raises(RuntimeError, match="sender exploded"):
        asyncio.run(runtime.run(client, asyncio.Event()))

    assert runtime.reducer.diagnostics.queue_high_water_frames == 7
    assert runtime.reducer.diagnostics.wire_received_envelope_count == 7


def test_current_writer_and_validator_are_schema_three_only_with_explicit_legacy_entry(
    tmp_path: Path,
) -> None:
    legacy = legacy_summary_object()
    writer = EvidenceWriter(
        tmp_path,
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity="sha256:" + "b" * 64,
    )

    with pytest.raises(EvidenceError, match="version 3"):
        validate_run_summary(legacy)
    with pytest.raises(EvidenceError, match="version 3"):
        writer.write_summary(legacy)

    validate_legacy_run_summary(legacy)
    (tmp_path / "radar-run-summary.json").write_text(
        json.dumps(legacy),
        encoding="utf-8",
    )
    with pytest.raises(EvidenceError, match="version 3"):
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
    segment["reason"] = "RESULT_INFERRED_UNKNOWN_REASON"

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
            "rate_limit_count": 0,
            "latency_observation_count": 0,
            "latency_ms_sum": 0,
            "latency_ms_max": 0,
        }
    )
    with pytest.raises(EvidenceError, match="RPC conservation"):
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


def test_schema_three_epoch_edges_must_match_restart_incidents_one_for_one() -> None:
    summary = current_summary_object()
    segments = summary["coverage_segments"]
    assert isinstance(segments, list)
    second = segments[1]
    assert isinstance(second, dict)
    second["reason"] = "INDEX_CONTINUITY_GAP"
    second["affected_scopes"] = ["GLOBAL"]
    second["global_continuity_epoch"] = 2
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


def test_schema_three_joint_witness_must_fall_in_known_complete_segment() -> None:
    summary = current_summary_object(
        segments=(
            CoverageSegment(
                0,
                20,
                CoverageState.UNKNOWN,
                reason="RUNTIME_START",
                affected_scopes=("GLOBAL",),
                global_continuity_epoch=1,
            ),
        )
    )
    attach_joint_witness(summary, first_ms=10, joint_count=1)

    with pytest.raises(EvidenceError, match="KNOWN_COMPLETE"):
        validate_run_summary(summary)


def test_schema_three_rejects_second_restart_before_incident_recovery() -> None:
    summary = current_summary_object()
    summary["coverage_segments"] = [
        {
            "start_monotonic_ms": 0,
            "end_monotonic_ms": 5,
            "state": "UNKNOWN",
            "reason": "RUNTIME_START",
            "affected_scopes": ["GLOBAL"],
            "global_continuity_epoch": 1,
        },
        {
            "start_monotonic_ms": 5,
            "end_monotonic_ms": 10,
            "state": "UNKNOWN",
            "reason": "CLOCK_GAP",
            "affected_scopes": ["GLOBAL"],
            "global_continuity_epoch": 2,
        },
        {
            "start_monotonic_ms": 10,
            "end_monotonic_ms": 20,
            "state": "UNKNOWN",
            "reason": "INDEX_CONTINUITY_GAP",
            "affected_scopes": ["GLOBAL"],
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
            "reason": "RUNTIME_START",
            "affected_scopes": ["GLOBAL"],
            "global_continuity_epoch": 1,
        },
        {
            "start_monotonic_ms": 10,
            "end_monotonic_ms": 20,
            "state": "UNKNOWN",
            "reason": "TICKER_APPLIED",
            "affected_scopes": ["GLOBAL"],
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
    }
    witness = diagnostics["witness"]
    assert isinstance(witness, dict)
    witness["global_continuity_epoch"] = 2

    with pytest.raises(EvidenceError, match=r"restart.*allowlist|cause.*domain.*scope"):
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
            "rate_limit_count": 0,
            "latency_observation_count": 1,
            "latency_ms_sum": 1,
            "latency_ms_max": 1,
        }
    )

    with pytest.raises(EvidenceError, match="allowlist"):
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
