from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
import radar_runtime.runtime as runtime_module
from conftest import PolicyFactory
from market_monitor import (
    PriceLevel,
    TimeInterval,
)
from radar_runtime.identity import (
    StartupGuardError,
    prepare_evidence_directory,
    validate_clean_git_outputs,
)
from radar_runtime.runtime import CoverageLedger, LiveRadarRuntime, ScopeCounts
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
        CoverageSegment(0, 10, CoverageState.UNKNOWN),
        CoverageSegment(10, 20, CoverageState.KNOWN_COMPLETE),
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
        operational_diagnostics=operational_diagnostics(),
    )


def operational_diagnostics(*, observation_ms: int = 20) -> dict[str, object]:
    return {
        "operational_diagnostics_schema_version": 1,
        "runtime_limits": {
            "heartbeat_interval_seconds": 30,
            "session_liveness_deadline_ms": 60_000,
            "rpc_deadline_ms": 30_000,
            "clock_refresh_interval_ms": 30_000,
            "clock_stale_deadline_ms": 60_000,
            "index_source_stale_deadline_ms": 90_000,
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
                CoverageSegment(0, 10, CoverageState.UNKNOWN),
                CoverageSegment(9, 20, CoverageState.KNOWN_COMPLETE),
            )
        )
    with pytest.raises(EvidenceError, match="overlap or contain a gap"):
        summary_object(
            segments=(
                CoverageSegment(0, 10, CoverageState.UNKNOWN),
                CoverageSegment(11, 20, CoverageState.KNOWN_COMPLETE),
            )
        )
    summary = summary_object()
    coverage = summary["coverage"]
    assert isinstance(coverage, dict)
    summary["coverage"] = {**coverage, "coverage_partition_error_ms": 1}
    with pytest.raises(EvidenceError, match="totals"):
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


def test_operational_diagnostics_are_strict_derived_and_payload_free() -> None:
    summary = summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    assert diagnostics["operational_diagnostics_schema_version"] == 1
    assert "price" not in json.dumps(diagnostics)

    channels = diagnostics["channel_by_class"]
    assert isinstance(channels, list)
    channels[0]["received_count"] = 1
    with pytest.raises(EvidenceError, match="rate"):
        validate_run_summary(summary)

    summary = summary_object()
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    source_shapes = diagnostics["source_shapes"]
    assert isinstance(source_shapes, list)
    source_shapes[0]["payload"] = {"price": 100}
    with pytest.raises(EvidenceError, match="exact"):
        validate_run_summary(summary)


def test_zero_duration_coverage_is_truthful_not_fabricated() -> None:
    segments = CoverageLedger(100).close(100)
    assert segments == (CoverageSegment(100, 100, CoverageState.UNKNOWN),)
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
        operational_diagnostics=operational_diagnostics(observation_ms=0),
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
