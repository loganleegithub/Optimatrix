from __future__ import annotations

import asyncio
import json
import math
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import radar_runtime.runtime as runtime_module
from conftest import PolicyFactory, encode_policy, policy_document
from market_monitor import (
    ContinuityGap,
    ContinuousOrderBook,
    IndexWindow,
    PriceLevel,
    TimeInterval,
    TrustedClock,
)
from market_monitor.deribit import INDEX_CHANNEL, PLATFORM_CHANNELS, book_channel, ticker_channel
from options_domain import (
    AmountMetadata,
    ComboInstrument,
    ComboLeg,
    OptionInstrument,
    OptionType,
)
from radar_runtime.deribit_public import (
    PUBLIC_METHODS,
    DeribitPublicClient,
    InboundEnvelope,
    PublicProtocolError,
    PublicRequestError,
    PublicSessionError,
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
from short_vol_radar.black import DecimalInterval, TotalVolatilityInterval, black_price
from short_vol_radar.detector import (
    DetectorCoverage,
    DetectorObservation,
    DetectorState,
    EpisodeEndReason,
    EpisodeTracker,
    TrackerState,
)
from short_vol_radar.evidence import (
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
from short_vol_radar.radar import (
    CurrentDisposition,
    CurrentEvaluation,
    TickerState,
)


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
        heartbeat_interval_seconds=30,
        liveness_deadline_seconds=60,
        clock_drift_ppm=1_000,
        notification_queue_lag_limit_ms=1_000,
        max_notification_queue_lag_ms=0,
    )


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
        heartbeat_interval_seconds=30,
        liveness_deadline_seconds=60,
        clock_drift_ppm=1_000,
        notification_queue_lag_limit_ms=1_000,
        max_notification_queue_lag_ms=0,
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


def test_public_client_has_exact_public_allowlist_and_test_request_guard() -> None:
    assert PUBLIC_METHODS
    assert all(method.startswith("public/") for method in PUBLIC_METHODS)
    assert not any(
        fragment in method
        for method in PUBLIC_METHODS
        for fragment in ("private/", "buy", "sell", "order", "rfq")
    )
    with pytest.raises(ValueError, match="production-public"):
        DeribitPublicClient("wss://test.deribit.com/ws/api/" + "v" + "2")

    client = DeribitPublicClient()
    with pytest.raises(PublicProtocolError, match="allowlist"):
        asyncio.run(client.request("private/get_positions", {}))
    with pytest.raises(PublicProtocolError, match="heartbeat response"):
        asyncio.run(client.request("public/test", {}))


class FakePublicClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.last_inbound_monotonic = time.monotonic()
        self.subscriptions: list[str] = []

    async def request(
        self,
        method: str,
        params: dict[str, object],
        *,
        responding_to_test_request: bool = False,
    ) -> object:
        assert method.startswith("public/")
        if method == "public/test":
            assert responding_to_test_request
        self.calls.append(method)
        if method == "public/set_heartbeat":
            return "ok"
        if method == "public/status":
            return {"locked": False, "locked_indices": [], "locked_currencies": []}
        if method == "public/get_time":
            return 1_000_000
        if method == "public/test":
            return {"version": "2.1.1"}
        if method in {"public/get_instruments", "public/get_combos"}:
            return []
        raise AssertionError(f"unexpected fake request {method} {params}")

    async def subscribe(self, channels: tuple[str, ...] | list[str]) -> object:
        self.calls.append("public/subscribe")
        self.subscriptions.extend(channels)
        return None

    async def unsubscribe(self, channels: tuple[str, ...] | list[str]) -> object:
        self.calls.append("public/unsubscribe")
        for channel in channels:
            self.subscriptions.remove(channel)
        return None

    async def next_notification(self, timeout_seconds: float | None = None) -> dict[str, object]:
        raise AssertionError(f"unexpected notification wait {timeout_seconds}")

    def drain_notifications(self) -> tuple[dict[str, object], ...]:
        return ()


class StampedMessage(dict[str, object]):
    def __init__(
        self,
        value: dict[str, object],
        *,
        ingress_seq: int,
        received_monotonic_ms: int,
    ) -> None:
        super().__init__(value)
        self.ingress_seq = ingress_seq
        self.received_monotonic_ms = received_monotonic_ms


class IncomingConnection:
    def __init__(self, messages: list[str]) -> None:
        self._messages = iter(messages)

    def __aiter__(self) -> IncomingConnection:
        return self

    async def __anext__(self) -> str:
        try:
            return next(self._messages)
        except StopIteration:
            raise StopAsyncIteration from None

    async def close(self) -> None:
        return None


def clear_fixture_connection_close(client: DeribitPublicClient) -> None:
    client._reader_error = None
    retained: list[Any] = []
    while True:
        try:
            envelope = client._notifications.get_nowait()
        except asyncio.QueueEmpty:
            break
        if envelope.get("method") != "connection_error":
            retained.append(envelope)
    for envelope in retained:
        client._notifications.put_nowait(envelope)


def test_reader_stamps_rpc_and_notification_frames_in_one_ingress_order() -> None:
    async def scenario() -> tuple[object, dict[str, object]]:
        client = DeribitPublicClient()
        channel = "instrument.state.option.USDC"
        client._active_subscription_generations[channel] = 1
        loop = asyncio.get_running_loop()
        pending: asyncio.Future[InboundEnvelope] = loop.create_future()
        client._pending[7] = pending
        client._connection = IncomingConnection(  # type: ignore[assignment]
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "subscription",
                        "params": {
                            "channel": channel,
                            "data": {"instrument_name": "FIRST", "state": "closed"},
                        },
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "id": 7, "result": []}),
            ]
        )

        await client._reader()
        clear_fixture_connection_close(client)
        return await pending, await client.next_notification(timeout_seconds=0.1)

    response, notification = asyncio.run(scenario())
    notification_seq = getattr(notification, "ingress_seq", None)
    response_seq = getattr(response, "ingress_seq", None)
    assert isinstance(notification_seq, int)
    assert isinstance(response_seq, int)
    assert notification_seq < response_seq
    assert isinstance(getattr(response, "received_monotonic_ms", None), int)


def test_rpc_fact_waits_for_earlier_notification_fact_in_runtime_reducer(
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
    runtime._bootstrap_in_progress = True
    runtime.option_catalog.acknowledge_lifecycle()

    class OrderedClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.queued = StampedMessage(
                {
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option.USDC",
                        "data": {"instrument_name": "FIRST", "state": "closed"},
                    },
                },
                ingress_seq=1,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )

        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            del method, params, responding_to_test_request
            return InboundEnvelope(
                {"jsonrpc": "2.0", "id": 1, "result": []},
                ingress_seq=2,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )

        def drain_notifications(self) -> tuple[dict[str, object], ...]:
            queued, self.queued = self.queued, None  # type: ignore[assignment]
            return (queued,)

    client = OrderedClient()
    result = asyncio.run(runtime._request_public(client, "public/get_instruments", {}))

    assert result == []
    assert runtime.option_catalog.buffered_events == [
        {"instrument_name": "FIRST", "state": "closed"}
    ]
    assert runtime._last_applied_ingress_seq == 2


def test_rpc_response_is_applied_before_simultaneously_ready_later_notification(
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
    runtime._bootstrap_in_progress = True
    runtime.option_catalog.acknowledge_lifecycle()

    class SimultaneousClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.release = asyncio.Event()
            self.sent = False

        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            del method, params, responding_to_test_request
            await self.release.wait()
            return InboundEnvelope(
                {"jsonrpc": "2.0", "id": 1, "result": []},
                ingress_seq=1,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )

        async def next_notification(
            self, timeout_seconds: float | None = None
        ) -> dict[str, object]:
            if self.sent:
                await asyncio.sleep(timeout_seconds or 0)
                raise TimeoutError
            self.sent = True
            self.release.set()
            return InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option.USDC",
                        "data": {"instrument_name": "LATER", "state": "closed"},
                    },
                },
                ingress_seq=2,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                channel="instrument.state.option.USDC",
                subscription_generation=1,
            )

    async def scenario() -> object:
        client = SimultaneousClient()
        result = await runtime._request_public(client, "public/get_instruments", {})
        assert runtime._last_applied_ingress_seq == 1
        assert runtime.option_catalog.buffered_events == []
        await runtime._handle_bootstrap_message(
            client,
            await runtime._next_notification(client, timeout_seconds=0.1),
        )
        return result

    assert asyncio.run(scenario()) == []
    assert runtime.option_catalog.buffered_events == [
        {"instrument_name": "LATER", "state": "closed"}
    ]
    assert runtime._last_applied_ingress_seq == 2


def test_rpc_error_and_notification_share_the_same_ingress_envelope() -> None:
    async def scenario() -> tuple[InboundEnvelope, InboundEnvelope]:
        client = DeribitPublicClient()
        channel = "instrument.state.option.USDC"
        client._active_subscription_generations[channel] = 1
        loop = asyncio.get_running_loop()
        pending: asyncio.Future[InboundEnvelope] = loop.create_future()
        client._pending[7] = pending
        client._connection = IncomingConnection(  # type: ignore[assignment]
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "subscription",
                        "params": {
                            "channel": channel,
                            "data": {"instrument_name": "FIRST", "state": "closed"},
                        },
                    }
                ),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "error": {"code": 10_028, "message": "too_many_requests"},
                    }
                ),
            ]
        )
        await client._reader()
        clear_fixture_connection_close(client)
        response = await pending
        notification = await client.next_notification(timeout_seconds=0.1)
        assert isinstance(notification, InboundEnvelope)
        return response, notification

    response, notification = asyncio.run(scenario())

    assert type(response) is type(notification) is InboundEnvelope
    assert notification.ingress_seq < response.ingress_seq
    with pytest.raises(PublicRequestError, match="too_many_requests"):
        _ = response.value


def test_subscribe_unsubscribe_success_and_failure_keep_rpc_envelopes() -> None:
    async def scenario() -> None:
        client = DeribitPublicClient()
        sequence = 1

        async def respond(
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            nonlocal sequence
            del responding_to_test_request
            envelope = InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "id": sequence,
                    "result": params["channels"],
                },
                ingress_seq=sequence,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )
            sequence += 1
            assert method in {"public/subscribe", "public/unsubscribe"}
            return envelope

        client.request = respond  # type: ignore[method-assign]
        subscribed = await client.subscribe(["book.TEST.100ms"])
        unsubscribed = await client.unsubscribe(["book.TEST.100ms"])
        assert all(type(item) is InboundEnvelope for item in (*subscribed, *unsubscribed))

        async def fail(
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            del method, params, responding_to_test_request
            return InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "id": sequence,
                    "error": {"code": 10_028, "message": "too_many_requests"},
                },
                ingress_seq=sequence,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )

        client.request = fail  # type: ignore[method-assign]
        with pytest.raises(PublicRequestError) as exc_info:
            await client.subscribe(["book.FAIL.100ms"])
        assert type(exc_info.value.envelope) is InboundEnvelope

    asyncio.run(scenario())


def test_channel_rpc_drains_simultaneously_ready_later_notification(
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

    class SimultaneousChannelClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.queued: dict[str, object] | None = InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option.USDC",
                        "data": {"instrument_name": "LATER", "state": "closed"},
                    },
                },
                ingress_seq=2,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                channel="instrument.state.option.USDC",
                subscription_generation=1,
            )

        async def subscribe(
            self, channels: tuple[str, ...] | list[str]
        ) -> tuple[InboundEnvelope, ...]:
            del channels
            return (
                InboundEnvelope(
                    {"jsonrpc": "2.0", "id": 1, "result": []},
                    ingress_seq=1,
                    received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                ),
            )

        def drain_notifications(self) -> tuple[dict[str, object], ...]:
            if self.queued is None:
                return ()
            queued, self.queued = self.queued, None
            return (queued,)

    asyncio.run(runtime._subscribe_public(SimultaneousChannelClient(), ["test"]))

    assert runtime._last_applied_ingress_seq == 1
    assert [item["params"] for item in runtime._deferred_notifications] == [
        {
            "channel": "instrument.state.option.USDC",
            "data": {"instrument_name": "LATER", "state": "closed"},
        }
    ]


def test_public_client_discards_notifications_from_an_old_subscription_generation() -> None:
    async def scenario() -> dict[str, object]:
        client = DeribitPublicClient()

        async def acknowledge(
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            del responding_to_test_request
            assert method in {"public/subscribe", "public/unsubscribe"}
            return params["channels"]

        client.request = acknowledge  # type: ignore[method-assign]
        channel = "book.BTC_USDC-TEST-100ms"
        await client.subscribe([channel])
        client._connection = IncomingConnection(  # type: ignore[assignment]
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "subscription",
                        "params": {"channel": channel, "data": {"change_id": 1}},
                    }
                )
            ]
        )
        await client._reader()
        clear_fixture_connection_close(client)

        await client.unsubscribe([channel])
        await client.subscribe([channel])
        client._connection = IncomingConnection(  # type: ignore[assignment]
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "subscription",
                        "params": {"channel": channel, "data": {"change_id": 2}},
                    }
                )
            ]
        )
        await client._reader()
        clear_fixture_connection_close(client)
        return await client.next_notification(timeout_seconds=0.1)

    message = asyncio.run(scenario())
    assert isinstance(getattr(message, "received_monotonic_ms", None), int)
    assert message["params"] == {
        "channel": "book.BTC_USDC-TEST-100ms",
        "data": {"change_id": 2},
    }


def test_public_client_notification_overflow_cannot_block_rpc_resolution() -> None:
    async def scenario() -> None:
        client = DeribitPublicClient()
        client._notifications = asyncio.Queue(maxsize=1)
        queued: Any = {"jsonrpc": "2.0", "method": "subscription", "params": {}}
        client._notifications.put_nowait(queued)
        loop = asyncio.get_running_loop()
        pending: asyncio.Future[InboundEnvelope] = loop.create_future()
        client._pending[1] = pending
        client._connection = IncomingConnection(  # type: ignore[assignment]
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "subscription",
                        "params": {"channel": "book.BTC_USDC-TEST-100ms", "data": {}},
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": "ok"}),
            ]
        )

        await asyncio.wait_for(client._reader(), timeout=0.1)
        with pytest.raises(PublicProtocolError, match="overflow"):
            await pending

    asyncio.run(scenario())


def test_public_client_surfaces_normal_websocket_close_immediately() -> None:
    async def scenario() -> None:
        client = DeribitPublicClient()
        client._connection = IncomingConnection([])  # type: ignore[assignment]
        await client._reader()
        with pytest.raises(PublicProtocolError, match="closed"):
            await client.next_notification(timeout_seconds=0.1)

    asyncio.run(scenario())


def test_public_client_drops_late_rpc_response_instead_of_treating_it_as_market_data() -> None:
    async def scenario() -> None:
        client = DeribitPublicClient()
        client._connection = IncomingConnection(  # type: ignore[assignment]
            [json.dumps({"jsonrpc": "2.0", "id": 999, "result": "late"})]
        )
        await client._reader()
        clear_fixture_connection_close(client)
        assert client.drain_notifications() == ()

    asyncio.run(scenario())


def test_book_known_at_time_is_socket_receive_time_not_delayed_processing_time(
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
    name = "SHORT"
    runtime.option_books[name] = ContinuousOrderBook(name)
    runtime.trackers[name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name=name,
    )
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: 9_000)

    asyncio.run(
        runtime._handle_book(
            FakePublicClient(),
            name,
            {
                "type": "snapshot",
                "timestamp": 1,
                "instrument_name": name,
                "change_id": 1,
                "bids": [],
                "asks": [],
            },
            received_monotonic_ms=1_000,
        )
    )
    assert runtime.option_books[name].last_mutation_monotonic_ms == 1_000


def test_queue_lag_gate_rejects_stale_market_notifications(
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
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: 5_000)
    runtime._coverage = CoverageLedger(0)

    with pytest.raises(PublicProtocolError, match="queue lag"):
        asyncio.run(
            runtime._handle_message(
                FakePublicClient(),
                {
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option.USDC",
                        "data": {"instrument_name": "X", "state": "closed"},
                    },
                },
                received_monotonic_ms=1_000,
            )
        )
    assert runtime._max_notification_queue_lag_ms == 4_000


def test_bootstrap_uses_the_same_notification_queue_lag_gate(
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
    runtime._coverage = CoverageLedger(0)
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: 5_000)
    delayed = StampedMessage(
        {
            "method": "subscription",
            "params": {
                "channel": "platform_state",
                "data": {"maintenance": False},
            },
        },
        ingress_seq=1,
        received_monotonic_ms=1_000,
    )

    with pytest.raises(PublicProtocolError, match="queue lag"):
        asyncio.run(runtime._handle_bootstrap_message(FakePublicClient(), delayed))

    assert runtime._max_notification_queue_lag_ms == 4_000
    assert runtime.platform.reason == "SESSION_GAP"


def test_bootstrap_services_test_request_while_combo_metadata_rpc_is_blocked(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: Any,
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

    class BlockingBootstrapClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.notifications: asyncio.Queue[dict[str, object]] = asyncio.Queue()
            self.metadata_started = asyncio.Event()
            self.metadata_release = asyncio.Event()
            self.test_answered = asyncio.Event()

        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            if method == "public/get_instruments":
                return [
                    option_payload_factory(name="SHORT", strike=110_000),
                    option_payload_factory(name="LONG", strike=120_000),
                ]
            if method == "public/get_combos":
                return [
                    {
                        "id": "COMBO",
                        "state": "active",
                        "legs": [
                            {"instrument_name": "SHORT", "amount": -1},
                            {"instrument_name": "LONG", "amount": 1},
                        ],
                    }
                ]
            if method == "public/get_instrument":
                self.metadata_started.set()
                await self.metadata_release.wait()
                return {
                    "instrument_name": params["instrument_name"],
                    "kind": "option_combo",
                    "base_currency": "BTC",
                    "quote_currency": "USDC",
                    "settlement_currency": "USDC",
                    "counter_currency": "USDC",
                    "instrument_type": "linear",
                    "contract_size": 1,
                    "min_trade_amount": 0.1,
                    "qty_tick_size": 0.1,
                }
            if method == "public/test":
                assert responding_to_test_request
                self.test_answered.set()
                return {"version": "2.1.1"}
            return await super().request(
                method,
                params,
                responding_to_test_request=responding_to_test_request,
            )

        async def next_notification(
            self, timeout_seconds: float | None = None
        ) -> dict[str, object]:
            if timeout_seconds is None:
                return await self.notifications.get()
            return await asyncio.wait_for(self.notifications.get(), timeout_seconds)

        def drain_notifications(self) -> tuple[dict[str, object], ...]:
            drained: list[dict[str, object]] = []
            while True:
                try:
                    drained.append(self.notifications.get_nowait())
                except asyncio.QueueEmpty:
                    return tuple(drained)

    async def scenario() -> None:
        client = BlockingBootstrapClient()
        bootstrap = asyncio.create_task(runtime._bootstrap(client))
        try:
            await asyncio.wait_for(client.metadata_started.wait(), 0.1)
            await client.notifications.put(
                StampedMessage(
                    {
                        "method": "heartbeat",
                        "params": {"type": "test_request"},
                    },
                    ingress_seq=1,
                    received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                )
            )
            await asyncio.wait_for(client.test_answered.wait(), 0.1)
        finally:
            client.metadata_release.set()
            await bootstrap

    asyncio.run(scenario())


def test_blocked_catalog_request_does_not_outlive_clock_deadline(
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
    runtime.clock = TrustedClock.from_response(1_000_000, 0, 0)
    runtime._coverage = CoverageLedger(0)
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: 60_000)

    class BlockedClient(FakePublicClient):
        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            del method, params, responding_to_test_request
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def next_notification(
            self, timeout_seconds: float | None = None
        ) -> dict[str, object]:
            await asyncio.sleep(timeout_seconds or 0)
            raise TimeoutError

    with pytest.raises(ContinuityGap, match="clock refresh expired"):
        asyncio.run(
            asyncio.wait_for(
                runtime._request_public(BlockedClient(), "public/get_combos", {}),
                timeout=0.2,
            )
        )
    assert runtime.platform.reason == "CLOCK_GAP"


def test_bootstrap_subscription_fact_receives_causal_sequence(
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
    runtime.platform.acknowledge(PLATFORM_CHANNELS)

    asyncio.run(
        runtime._handle_bootstrap_message(
            FakePublicClient(),
            {
                "method": "subscription",
                "params": {
                    "channel": "platform_state",
                    "data": {"maintenance": False},
                },
            },
        )
    )

    assert runtime.causal_seq == 1


def test_connection_gap_receives_causal_sequence_before_invalidation(
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
    tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )
    tracker.known_ineligible(reason="READY", causal_seq=0)
    runtime.trackers["SHORT"] = tracker

    with pytest.raises(PublicProtocolError, match="connection closed"):
        asyncio.run(
            runtime._handle_message(
                FakePublicClient(),
                {"method": "connection_error", "params": {"reason": "closed"}},
            )
        )

    assert runtime.causal_seq == 1
    assert tracker.detector_state is DetectorState.UNKNOWN


def test_public_only_runtime_composes_and_cleanly_writes_empty_scope_summary(
    tmp_path: Path, policy_factory: PolicyFactory
) -> None:
    exact, digest = policy_factory()
    policy = load_policy_bytes(exact, digest)
    writer = EvidenceWriter(
        tmp_path,
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity=digest,
    )
    runtime = LiveRadarRuntime(
        policy=policy,
        code_identity="a" * 40,
        evidence_writer=writer,
        runtime_identity="runtime",
    )
    client = FakePublicClient()
    stop = asyncio.Event()
    stop.set()
    summary_path = asyncio.run(runtime.run(client, stop))
    assert summary_path.name == "radar-run-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    validate_run_summary(summary)
    coverage = summary["coverage"]
    assert isinstance(coverage, dict)
    assert coverage["coverage_partition_error_ms"] == 0
    assert coverage["observation_interval_ms"] >= 0
    assert coverage["unknown_ms"] == coverage["observation_interval_ms"]
    operational = summary["operational_constants"]
    assert isinstance(operational, dict)
    assert operational["notification_queue_lag_limit_ms"] == 1_000
    assert summary["max_notification_queue_lag_ms"] == 0
    assert all(method.startswith("public/") for method in client.calls)
    assert not any(tmp_path.glob("*market*"))
    assert not any(tmp_path.glob("*no-anomaly*"))


def test_scope_evaluation_records_one_joint_aggregate_witness(
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
    now = time.monotonic_ns() // 1_000_000
    server_ms = 1_000_000
    runtime.clock = TrustedClock.from_response(server_ms, now, now)
    runtime.platform.acknowledge(("platform_state", "platform_state.public_methods_state"))
    runtime.platform.status_usable = True
    runtime.platform.post_status_bootstrap_complete = True
    runtime.platform.maintenance = False
    runtime.platform.public_methods_allowed = True
    runtime.option_catalog.complete = True
    expiry_ms = server_ms + 60 * 60 * 1_000
    for name, strike in (("FIRST", "110"), ("SECOND", "120")):
        runtime.options[name] = OptionInstrument(
            name,
            expiry_ms,
            Decimal(strike),
            OptionType.CALL,
            AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
        )
        runtime.trackers[name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=digest,
            instrument_name=name,
        )

    def known_result(**kwargs: object) -> CurrentEvaluation:
        instrument = kwargs["instrument"]
        assert isinstance(instrument, OptionInstrument)
        return CurrentEvaluation(
            disposition=CurrentDisposition.KNOWN_INELIGIBLE,
            reason="TEST_KNOWN",
            known_evaluation=True,
            full_formula_evaluation=instrument.instrument_name == "FIRST",
            band_id=policy.tte_bands[0].band_id,
        )

    monkeypatch.setattr(runtime_module, "calculate_current_evaluation", known_result)
    asyncio.run(runtime._evaluate_all(FakePublicClient()))

    scope = runtime._scope_counter(OptionType.CALL, policy.tte_bands[0].band_id)
    assert scope.known_per_instrument_detector_evaluation_count == 2
    assert scope.complete_aggregate_detector_evaluation_count == 1
    assert scope.complete_aggregate_with_full_formula_evaluation_count == 1


def test_stale_index_tail_invalidates_full_formula_until_fresh_warmup(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    runtime._coverage = CoverageLedger(0)
    minute_ms = 60_000
    server_ms = 6 * minute_ms
    runtime.clock = TrustedClock.from_response(server_ms, 0, 0)
    runtime.platform.acknowledge(PLATFORM_CHANNELS)
    runtime.platform.status_usable = True
    runtime.platform.post_status_bootstrap_complete = True
    runtime.platform.maintenance = False
    runtime.platform.public_methods_allowed = True
    runtime.option_catalog.complete = True

    expiry_ms = server_ms + 60 * minute_ms
    strike = Decimal("100.01")
    total_volatility = 0.5 * math.sqrt(60 / (365 * 24 * 60))
    bid_price = Decimal(str(black_price(100, float(strike), total_volatility, OptionType.CALL)))
    instrument = OptionInstrument(
        "SHORT",
        expiry_ms,
        strike,
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    runtime.catalog_options["SHORT"] = instrument
    runtime.options["SHORT"] = instrument
    runtime.trackers["SHORT"] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )
    book = runtime.option_books["SHORT"] = ContinuousOrderBook("SHORT")
    book.apply(
        {
            "type": "snapshot",
            "timestamp": server_ms,
            "instrument_name": "SHORT",
            "change_id": 1,
            "bids": [["new", bid_price, "0.1"]],
            "asks": [],
        },
        0,
    )
    runtime.tickers["SHORT"] = TickerState(Decimal(100), "index_price", server_ms)
    runtime.index.start_continuous_coverage(0)
    for sequence in range(1, 8):
        timestamp = 1 if sequence == 1 else (sequence - 1) * minute_ms
        runtime.index.accept_tick(
            source_timestamp_ms=timestamp,
            price=100 + sequence,
            causal_seq=sequence,
        )
        runtime.index.seal_ready(timestamp)
    runtime.causal_seq = 10
    client = FakePublicClient()
    client.subscriptions.append(INDEX_CHANNEL)

    asyncio.run(runtime._evaluate_all(client, evaluation_monotonic_ms=0))
    assert runtime.results["SHORT"].full_formula_evaluation

    runtime.clock = TrustedClock.from_response(
        server_ms + minute_ms,
        minute_ms,
        minute_ms,
    )
    asyncio.run(
        runtime._handle_book(
            client,
            "SHORT",
            {
                "type": "change",
                "timestamp": server_ms + minute_ms,
                "instrument_name": "SHORT",
                "change_id": 2,
                "prev_change_id": 1,
                "bids": [["change", bid_price, "0.2"]],
                "asks": [],
            },
            received_monotonic_ms=minute_ms + 1,
        )
    )

    assert runtime.results["SHORT"].reason == "INDEX_BASELINE_STALE"
    assert runtime.trackers["SHORT"].detector_state is DetectorState.UNKNOWN
    assert runtime.index.sealed == ()

    asyncio.run(runtime._evaluate_all(client, evaluation_monotonic_ms=minute_ms + 2))
    assert runtime.results["SHORT"].reason == "INDEX_BASELINE_WARMUP"


def test_combo_catalog_failure_is_local_to_atomic_availability(
    tmp_path: Path, policy_factory: PolicyFactory
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    instrument = OptionInstrument(
        "SHORT",
        10_000_000,
        Decimal(110),
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name=instrument.instrument_name,
    )
    tracker.observe(
        DetectorObservation(
            causal_seq=1,
            trusted_time=TimeInterval(0, 0),
            band_id=policy.tte_bands[0].band_id,
            richness=DecimalInterval(Decimal("2"), Decimal("2")),
        ),
        policy.tte_bands[0].option_rules[OptionType.CALL],
    )
    assert tracker.detector_state is DetectorState.ANOMALY_ACTIVE
    runtime.options[instrument.instrument_name] = instrument
    runtime.trackers[instrument.instrument_name] = tracker
    runtime.combo_catalog.complete = True

    client = FakePublicClient()

    async def invalid_combo_result(
        method: str,
        params: dict[str, object],
        *,
        responding_to_test_request: bool = False,
    ) -> object:
        del params, responding_to_test_request
        assert method == "public/get_combos"
        return {"not": "an array"}

    client.request = invalid_combo_result  # type: ignore[method-assign]
    asyncio.run(runtime._refresh_combo_catalog(client))

    assert tracker.detector_state is DetectorState.ANOMALY_ACTIVE
    assert not runtime.combo_catalog.complete
    episode_id = tracker.episode_id
    assert episode_id is not None
    assert runtime.atomic_states[episode_id] is PublicAtomicQuoteState.UNKNOWN


def test_combo_subscribe_request_failure_keeps_layer_one_episode_active(
    tmp_path: Path, policy_factory: PolicyFactory
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    amount = AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1"))
    short = OptionInstrument("SHORT", 10_000_000, Decimal(100), OptionType.CALL, amount)
    long = OptionInstrument("LONG", 10_000_000, Decimal(110), OptionType.CALL, amount)
    tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )
    tracker.observe(
        DetectorObservation(
            causal_seq=1,
            trusted_time=TimeInterval(0, 0),
            band_id=policy.tte_bands[0].band_id,
            richness=DecimalInterval(Decimal("2"), Decimal("2")),
        ),
        policy.tte_bands[0].option_rules[OptionType.CALL],
    )
    episode_id = tracker.episode_id
    assert episode_id is not None
    runtime.options = {"SHORT": short, "LONG": long}
    runtime.trackers["SHORT"] = tracker
    runtime.combos["COMBO"] = ComboInstrument(
        "COMBO",
        "active",
        (ComboLeg("SHORT", Decimal(-1)), ComboLeg("LONG", Decimal(1))),
        amount,
    )
    runtime.combo_catalog.complete = True

    class FailingComboClient(FakePublicClient):
        async def subscribe(self, channels: tuple[str, ...] | list[str]) -> None:
            del channels
            raise PublicRequestError("combo subscription rejected")

    asyncio.run(runtime._sync_combo_subscriptions(FailingComboClient()))

    assert tracker.detector_state is DetectorState.ANOMALY_ACTIVE
    assert tracker.episode_id == episode_id
    assert runtime.atomic_states[episode_id] is PublicAtomicQuoteState.UNKNOWN
    assert runtime._subscribed_combo_names == set()


def test_session_failure_is_not_swallowed_as_combo_layer_failure(
    tmp_path: Path, policy_factory: PolicyFactory
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    amount = AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1"))
    short = OptionInstrument("SHORT", 10_000_000, Decimal(100), OptionType.CALL, amount)
    long = OptionInstrument("LONG", 10_000_000, Decimal(110), OptionType.CALL, amount)
    tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )
    tracker.observe(
        DetectorObservation(
            causal_seq=1,
            trusted_time=TimeInterval(0, 0),
            band_id=policy.tte_bands[0].band_id,
            richness=DecimalInterval(Decimal("2"), Decimal("2")),
        ),
        policy.tte_bands[0].option_rules[OptionType.CALL],
    )
    runtime.options = {"SHORT": short, "LONG": long}
    runtime.trackers["SHORT"] = tracker
    runtime.combos["COMBO"] = ComboInstrument(
        "COMBO",
        "active",
        (ComboLeg("SHORT", Decimal(-1)), ComboLeg("LONG", Decimal(1))),
        amount,
    )

    class ClosedSessionClient(FakePublicClient):
        async def subscribe(self, channels: tuple[str, ...] | list[str]) -> None:
            del channels
            raise PublicSessionError("connection closed")

    with pytest.raises(PublicSessionError, match="connection closed"):
        asyncio.run(runtime._sync_combo_subscriptions(ClosedSessionClient()))
    assert tracker.detector_state is DetectorState.ANOMALY_ACTIVE


def test_combo_lifecycle_burst_coalesces_one_inflight_catalog_refresh(
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

    class BlockingComboClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.refresh_count = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            del params, responding_to_test_request
            if method == "public/get_combos":
                self.refresh_count += 1
                self.started.set()
                await self.release.wait()
                return []
            return await super().request(method, {})

        async def next_notification(
            self, timeout_seconds: float | None = None
        ) -> dict[str, object]:
            await asyncio.sleep(timeout_seconds or 0)
            raise TimeoutError

    async def scenario() -> int:
        client = BlockingComboClient()
        first = asyncio.create_task(runtime._coalesced_combo_refresh(client))
        await client.started.wait()
        second = asyncio.create_task(runtime._coalesced_combo_refresh(client))
        await asyncio.sleep(0)
        client.release.set()
        await asyncio.gather(first, second)
        return client.refresh_count

    assert asyncio.run(scenario()) == 1


def test_unchanged_combo_catalog_reuses_existing_metadata(
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
    amount = AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1"))
    runtime.options = {
        "SHORT": OptionInstrument("SHORT", 10_000_000, Decimal(110), OptionType.CALL, amount),
        "LONG": OptionInstrument("LONG", 10_000_000, Decimal(120), OptionType.CALL, amount),
    }
    combo_summary = {
        "id": "COMBO",
        "state": "active",
        "legs": [
            {"instrument_name": "SHORT", "amount": -1},
            {"instrument_name": "LONG", "amount": 1},
        ],
    }

    class CountingMetadataClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.metadata_count = 0

        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            del responding_to_test_request
            if method == "public/get_combos":
                return [combo_summary]
            if method == "public/get_instrument":
                self.metadata_count += 1
                return {
                    "instrument_name": params["instrument_name"],
                    "kind": "option_combo",
                    "base_currency": "BTC",
                    "quote_currency": "USDC",
                    "settlement_currency": "USDC",
                    "counter_currency": "USDC",
                    "instrument_type": "linear",
                    "contract_size": 1,
                    "min_trade_amount": 0.1,
                    "qty_tick_size": 0.1,
                }
            return await super().request(method, params)

    client = CountingMetadataClient()
    asyncio.run(runtime._refresh_combo_catalog(client))
    asyncio.run(runtime._refresh_combo_catalog(client))

    assert client.metadata_count == 1
    assert tuple(runtime.combos) == ("COMBO",)


def test_combo_referencing_known_short_and_missing_leg_is_catalog_incomplete(
    tmp_path: Path, policy_factory: PolicyFactory
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
    amount = AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1"))
    runtime.options = {
        "SHORT": OptionInstrument("SHORT", 10_000_000, Decimal(110), OptionType.CALL, amount)
    }
    payload = {
        "id": "COMBO",
        "state": "active",
        "legs": [
            {"instrument_name": "SHORT", "amount": -1},
            {"instrument_name": "MISSING", "amount": 1},
        ],
    }

    complete = asyncio.run(runtime._replace_combos(FakePublicClient(), [payload]))

    assert not complete
    assert runtime.combos == {}


def test_initial_combo_catalog_failure_does_not_abort_layer_one_bootstrap(
    tmp_path: Path, policy_factory: PolicyFactory
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
    client = FakePublicClient()
    original_request = client.request

    async def invalid_initial_combo(
        method: str,
        params: dict[str, object],
        *,
        responding_to_test_request: bool = False,
    ) -> object:
        if method == "public/get_combos":
            return {"not": "an array"}
        return await original_request(
            method,
            params,
            responding_to_test_request=responding_to_test_request,
        )

    client.request = invalid_initial_combo  # type: ignore[method-assign]
    asyncio.run(runtime._bootstrap(client))
    assert runtime.option_catalog.complete
    assert not runtime.combo_catalog.complete


def test_invalid_option_lifecycle_recovers_from_authoritative_snapshot(
    tmp_path: Path, policy_factory: PolicyFactory
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
    now = time.monotonic_ns() // 1_000_000
    runtime.clock = TrustedClock.from_response(1_000_000, now, now)
    runtime.option_catalog.complete = True

    asyncio.run(
        runtime._handle_message(
            FakePublicClient(),
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"malformed": True},
                },
            },
        )
    )
    assert runtime.option_catalog.complete


def test_option_metadata_request_failure_is_local_to_option_catalog(
    tmp_path: Path, policy_factory: PolicyFactory
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
    now = time.monotonic_ns() // 1_000_000
    runtime.clock = TrustedClock.from_response(1_000_000, now, now)
    runtime.option_catalog.complete = True

    class FailedMetadataClient(FakePublicClient):
        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            del params, responding_to_test_request
            assert method == "public/get_instrument"
            raise PublicRequestError("rate limited")

    asyncio.run(
        runtime._apply_option_lifecycle(
            FailedMetadataClient(),
            {"instrument_name": "NEW", "state": "open"},
        )
    )

    assert not runtime.option_catalog.complete
    assert runtime.platform.reason != "SESSION_GAP"


def test_incomplete_option_catalog_is_conditionally_recovered(
    tmp_path: Path, policy_factory: PolicyFactory
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
    now = time.monotonic_ns() // 1_000_000
    runtime.clock = TrustedClock.from_response(1_000_000, now, now)
    runtime.option_catalog.mark_incomplete()

    asyncio.run(runtime._recover_incomplete_catalogs(FakePublicClient()))

    assert runtime.option_catalog.complete


def test_catalog_recovery_applies_membership_loss_before_removing_active_tracker(
    tmp_path: Path, policy_factory: PolicyFactory
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    now = time.monotonic_ns() // 1_000_000
    runtime.clock = TrustedClock.from_response(1_000_000, now, now)
    option = OptionInstrument(
        "SHORT",
        2_000_000,
        Decimal(110),
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name=option.instrument_name,
    )
    tracker.observe(
        DetectorObservation(
            causal_seq=1,
            trusted_time=TimeInterval(0, 0),
            band_id=policy.tte_bands[0].band_id,
            richness=DecimalInterval(Decimal("2"), Decimal("2")),
        ),
        policy.tte_bands[0].option_rules[OptionType.CALL],
    )
    runtime.catalog_options[option.instrument_name] = option
    runtime.options[option.instrument_name] = option
    runtime.trackers[option.instrument_name] = tracker
    runtime.option_books[option.instrument_name] = ContinuousOrderBook(option.instrument_name)
    runtime.option_catalog.complete = True
    client = FakePublicClient()
    client.subscriptions.extend(
        [ticker_channel(option.instrument_name), book_channel(option.instrument_name)]
    )

    asyncio.run(
        runtime._handle_message(
            client,
            {
                "method": "subscription",
                "params": {
                    "channel": "instrument.state.option.USDC",
                    "data": {"malformed": True},
                },
            },
        )
    )

    assert option.instrument_name not in runtime.trackers
    assert runtime._episode_end_counts[EpisodeEndReason.MEMBERSHIP_LOSS.value] == 1


def test_accepted_clock_rpc_facts_receive_distinct_causal_sequences(
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
    runtime._coverage = CoverageLedger(0)
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: 100)
    client = FakePublicClient()

    asyncio.run(runtime._bootstrap_clock(client))
    first = runtime.causal_seq
    asyncio.run(runtime._refresh_clock(client))

    assert first > 0
    assert runtime.causal_seq > first


def test_clock_uses_reader_receive_boundary_not_later_processing_time(
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
    times = iter((0, 100))
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: next(times))

    class StampedClockClient(FakePublicClient):
        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            del params, responding_to_test_request
            assert method == "public/get_time"
            return InboundEnvelope(
                {"jsonrpc": "2.0", "id": 1, "result": 1_000_000},
                ingress_seq=1,
                received_monotonic_ms=10,
            )

    asyncio.run(runtime._bootstrap_clock(StampedClockClient()))

    assert runtime.clock is not None
    assert runtime.clock.base_monotonic_ms == 10


def test_relevant_platform_lock_invalidates_detector_but_unrelated_lock_does_not(
    tmp_path: Path, policy_factory: PolicyFactory
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
    runtime.platform.acknowledge(("platform_state", "platform_state.public_methods_state"))
    runtime.platform.apply_status({"locked": "false"})
    runtime.platform.public_methods_allowed = True
    runtime.platform.prove_operational_from_post_status_public_success()
    runtime.platform.complete_post_status_bootstrap()
    tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )
    tracker.known_ineligible(reason="READY", causal_seq=1)
    runtime.trackers["SHORT"] = tracker

    asyncio.run(
        runtime._handle_message(
            FakePublicClient(),
            {
                "method": "subscription",
                "params": {
                    "channel": "platform_state",
                    "data": {"price_index": "eth_usdc", "locked": True},
                },
            },
        )
    )
    assert tracker.detector_state is DetectorState.NO_ANOMALY

    with pytest.raises(PublicProtocolError, match="platform state"):
        asyncio.run(
            runtime._handle_message(
                FakePublicClient(),
                {
                    "method": "subscription",
                    "params": {
                        "channel": "platform_state",
                        "data": {"price_index": "btc_usdc", "locked": True},
                    },
                },
            )
        )
    assert tracker.state is TrackerState.UNKNOWN


def test_atomic_event_binds_latest_active_detector_evaluation_sequence(
    tmp_path: Path, policy_factory: PolicyFactory
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    amount = AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1"))
    short = OptionInstrument("SHORT", 10_000_000, Decimal(100), OptionType.CALL, amount)
    long = OptionInstrument("LONG", 10_000_000, Decimal(110), OptionType.CALL, amount)
    combo = ComboInstrument(
        "COMBO",
        "active",
        (ComboLeg("SHORT", Decimal(-1)), ComboLeg("LONG", Decimal(1))),
        amount,
    )
    combo_book = ContinuousOrderBook("COMBO")
    combo_book.apply(
        {
            "type": "snapshot",
            "timestamp": 1_000,
            "instrument_name": "COMBO",
            "change_id": 1,
            "bids": [],
            "asks": [["new", "-5", "0.1"]],
        },
        1_000,
    )
    tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )
    tracker.observe(
        DetectorObservation(
            causal_seq=1,
            trusted_time=TimeInterval(0, 0),
            band_id=policy.tte_bands[0].band_id,
            richness=DecimalInterval(Decimal("2"), Decimal("2")),
        ),
        policy.tte_bands[0].option_rules[OptionType.CALL],
    )
    runtime.options = {"SHORT": short, "LONG": long}
    runtime.trackers["SHORT"] = tracker
    runtime.combos["COMBO"] = combo
    runtime.combo_books["COMBO"] = combo_book
    runtime.combo_catalog.complete = True
    runtime.causal_seq = 10
    runtime._last_detector_causal_seq = {"SHORT": 7}

    asyncio.run(runtime._evaluate_atomic(tracker))

    path = next(tmp_path.glob("public-atomic-quote-*.json"))
    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["detector_causal_seq"] == 7
    assert event["quote_causal_seq"] == 10

    combo_book.apply(
        {
            "type": "change",
            "timestamp": 1_001,
            "instrument_name": "COMBO",
            "change_id": 2,
            "prev_change_id": 1,
            "bids": [],
            "asks": [["change", "-5", "0.2"]],
        },
        1_001,
    )
    runtime.causal_seq = 11
    asyncio.run(runtime._evaluate_atomic(tracker))

    combo_book.invalidate("TEST_FLICKER")
    asyncio.run(runtime._evaluate_atomic(tracker))
    replacement = ContinuousOrderBook("COMBO")
    replacement.apply(
        {
            "type": "snapshot",
            "timestamp": 1_002,
            "instrument_name": "COMBO",
            "change_id": 3,
            "bids": [],
            "asks": [["new", "-6", "0.1"]],
        },
        1_002,
    )
    runtime.combo_books["COMBO"] = replacement
    runtime.causal_seq = 12
    asyncio.run(runtime._evaluate_atomic(tracker))

    assert len(tuple(tmp_path.glob("public-atomic-quote-*.json"))) == 1

    second_combo = ComboInstrument(
        "COMBO-2",
        "active",
        (ComboLeg("SHORT", Decimal(-1)), ComboLeg("LONG", Decimal(1))),
        amount,
    )
    second_book = ContinuousOrderBook("COMBO-2")
    second_book.apply(
        {
            "type": "snapshot",
            "timestamp": 1_003,
            "instrument_name": "COMBO-2",
            "change_id": 1,
            "bids": [],
            "asks": [["new", "-7", "0.1"]],
        },
        1_003,
    )
    runtime.combos["COMBO-2"] = second_combo
    runtime.combo_books["COMBO-2"] = second_book
    asyncio.run(runtime._evaluate_atomic(tracker))
    assert len(tuple(tmp_path.glob("public-atomic-quote-*.json"))) == 2

    next_tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )
    next_tracker.observe(
        DetectorObservation(
            causal_seq=20,
            trusted_time=TimeInterval(0, 0),
            band_id=policy.tte_bands[0].band_id,
            richness=DecimalInterval(Decimal("2"), Decimal("2")),
        ),
        policy.tte_bands[0].option_rules[OptionType.CALL],
    )
    runtime.trackers["SHORT"] = next_tracker
    asyncio.run(runtime._evaluate_atomic(next_tracker))
    assert len(tuple(tmp_path.glob("public-atomic-quote-*.json"))) == 4


def test_gap_episode_duration_stops_at_last_trusted_active_boundary(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )
    tracker.observe(
        DetectorObservation(
            causal_seq=1,
            trusted_time=TimeInterval(0, 0),
            band_id=policy.tte_bands[0].band_id,
            richness=DecimalInterval(Decimal("2"), Decimal("2")),
        ),
        policy.tte_bands[0].option_rules[OptionType.CALL],
    )
    episode_id = tracker.episode_id
    assert episode_id is not None
    runtime._episode_active_segment_started_ms[episode_id] = 100
    runtime._episode_active_accumulated_ms[episode_id] = 0
    runtime._episode_last_trusted_boundary_ms = {episode_id: 200}
    runtime._episode_option_types[episode_id] = OptionType.CALL
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: 1_000)

    ended = tracker.unknown(
        reason="OPTION_BOOK_GAP",
        causal_seq=2,
        continuity_gap=True,
    ).ended_episode
    runtime._record_episode_end(ended)

    assert runtime._known_active_duration_ms[EpisodeEndReason.UNKNOWN_AT_GAP.value] == 100


def test_platform_bootstrap_does_not_make_one_missing_option_a_global_barrier(
    tmp_path: Path, policy_factory: PolicyFactory
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
    monotonic_ms = time.monotonic_ns() // 1_000_000
    server_ms = 1_000_000
    runtime.clock = TrustedClock.from_response(server_ms, monotonic_ms, monotonic_ms)
    runtime.platform.acknowledge(("platform_state", "platform_state.public_methods_state"))
    runtime.platform.apply_status({"locked": False, "locked_indices": [], "locked_currencies": []})
    runtime.platform.public_methods_allowed = True
    runtime.platform.prove_operational_from_post_status_public_success()
    runtime.index.start_continuous_coverage(server_ms)
    runtime.index.accept_tick(
        source_timestamp_ms=server_ms,
        price=100,
        causal_seq=1,
    )
    name = "BTC_USDC-TEST-110000-C"
    runtime.options[name] = OptionInstrument(
        name,
        server_ms + 60 * 60 * 1_000,
        Decimal(110_000),
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    runtime.trackers[name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name=name,
    )
    runtime.option_books[name] = ContinuousOrderBook(name)
    client = FakePublicClient()
    asyncio.run(runtime._maybe_complete_post_status_bootstrap(client))
    assert runtime.platform.usable
    assert runtime.results[name].reason == "OPTION_BOOK_UNKNOWN"

    runtime.option_books[name].apply(
        {
            "type": "snapshot",
            "timestamp": server_ms,
            "instrument_name": name,
            "change_id": 1,
            "bids": [],
            "asks": [],
        },
        monotonic_ms,
    )
    runtime.tickers[name] = TickerState(
        Decimal(100),
        "index_price",
        server_ms,
    )
    asyncio.run(runtime._maybe_complete_post_status_bootstrap(client))
    assert runtime.platform.usable

    runtime.prepare_reconnect("CONNECTION_CLOSED")
    assert not runtime.platform.usable
    assert runtime.option_books[name].reason == "SESSION_GAP"
    runtime._reset_session_state()
    assert runtime.clock is None
    assert runtime.options == {}
    assert runtime.option_books == {}


def test_direct_gap_paths_record_unknown_transitions_once_per_reason(
    tmp_path: Path, policy_factory: PolicyFactory
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
    runtime.trackers["SHORT"] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )

    runtime._invalidate_all("CONNECTION_CLOSED")
    runtime._invalidate_all("CONNECTION_CLOSED")
    runtime._invalidate_all("CLOCK_GAP")

    assert runtime._unknown_counts == {
        "SESSION_GAP": 1,
        "CLOCK_GAP": 1,
    }


def test_one_session_root_records_one_canonical_unknown_reason(
    tmp_path: Path, policy_factory: PolicyFactory
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
    runtime.trackers["SHORT"] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )

    with pytest.raises(PublicSessionError):
        asyncio.run(
            runtime._handle_message(
                FakePublicClient(),
                {"method": "connection_error", "params": {"reason": "closed"}},
            )
        )
    runtime.prepare_reconnect("SESSION_RECONNECT:PublicSessionError")

    assert runtime._unknown_counts == {"SESSION_GAP": 1}


def test_heartbeat_test_request_uses_only_guarded_public_test(
    tmp_path: Path, policy_factory: PolicyFactory
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
    client = FakePublicClient()
    asyncio.run(
        runtime._handle_heartbeat(
            client,
            {"params": {"type": "test_request"}},
        )
    )
    assert client.calls == ["public/test"]


def test_heartbeat_response_does_not_apply_or_fail_on_queued_economic_fact(
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

    class ControlClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.queued: dict[str, object] | None = InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option.USDC",
                        "data": {"instrument_name": "ECONOMIC", "state": "closed"},
                    },
                },
                ingress_seq=1,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                channel="instrument.state.option.USDC",
                subscription_generation=1,
            )

        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            del params
            assert method == "public/test"
            assert responding_to_test_request
            return InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"version": "2.1.1"},
                },
                ingress_seq=2,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )

        def drain_notifications(self) -> tuple[dict[str, object], ...]:
            if self.queued is None:
                return ()
            queued, self.queued = self.queued, None
            return (queued,)

    runtime._economic_reducer_depth = 1
    result = asyncio.run(
        runtime._request_public(
            ControlClient(),
            "public/test",
            {},
            responding_to_test_request=True,
        )
    )

    assert result == {"version": "2.1.1"}
    assert runtime._last_applied_ingress_seq == 0
    assert [item["params"] for item in runtime._deferred_notifications] == [
        {
            "channel": "instrument.state.option.USDC",
            "data": {"instrument_name": "ECONOMIC", "state": "closed"},
        }
    ]


def test_heartbeat_rejects_non_official_public_test_result(
    tmp_path: Path, policy_factory: PolicyFactory
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
    client = FakePublicClient()

    async def invalid_request(
        method: str,
        params: dict[str, object],
        *,
        responding_to_test_request: bool = False,
    ) -> object:
        assert method == "public/test"
        assert responding_to_test_request
        return "ok"

    client.request = invalid_request  # type: ignore[method-assign]
    with pytest.raises(PublicProtocolError, match="version") as exc_info:
        asyncio.run(
            runtime._handle_heartbeat(
                client,
                {"params": {"type": "test_request"}},
            )
        )
    assert type(exc_info.value).__name__ == "PublicProtocolIncompatibility"


def test_transient_reconnect_delay_is_exponential_capped_and_jittered() -> None:
    delay = runtime_module.reconnect_delay_seconds

    assert delay(0, jitter_fraction=0) == pytest.approx(0.8)
    assert delay(1, jitter_fraction=0.5) == pytest.approx(2.0)
    assert delay(10, jitter_fraction=1) == pytest.approx(36.0)


def test_option_book_gap_ends_episode_and_forces_fresh_snapshot_subscription(
    tmp_path: Path, policy_factory: PolicyFactory
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    name = "BTC_USDC-TEST-110000-C"
    runtime.options[name] = OptionInstrument(
        name,
        10_000_000,
        Decimal(110_000),
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    tracker = runtime.trackers[name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name=name,
    )
    rule = policy.tte_bands[0].option_rules[OptionType.CALL]
    tracker.observe(
        DetectorObservation(
            1,
            TimeInterval(1_000, 1_000),
            policy.tte_bands[0].band_id,
            DecimalInterval(Decimal("1.3"), Decimal("1.3")),
        ),
        rule,
    )
    book = runtime.option_books[name] = ContinuousOrderBook(name)
    book.apply(
        {
            "type": "snapshot",
            "timestamp": 1_000,
            "instrument_name": name,
            "change_id": 10,
            "bids": [["new", 1, "0.1"]],
            "asks": [["new", 2, "0.1"]],
        },
        1,
    )
    client = FakePublicClient()
    client.subscriptions.append(book_channel(name))
    asyncio.run(
        runtime._handle_book(
            client,
            name,
            {
                "type": "change",
                "timestamp": 1_001,
                "instrument_name": name,
                "change_id": 12,
                "prev_change_id": 9,
                "bids": [],
                "asks": [],
            },
        )
    )
    assert runtime.option_books[name] is not book
    assert runtime.option_books[name].reason == "SNAPSHOT_REQUIRED"
    assert tracker.episode_id is None
    assert runtime._episode_end_counts[EpisodeEndReason.UNKNOWN_AT_GAP.value] == 1
    assert client.subscriptions == [book_channel(name)]


def test_catalog_option_enters_dynamic_subscription_at_seventy_two_hours(
    tmp_path: Path, policy_factory: PolicyFactory
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
    monotonic_ms = time.monotonic_ns() // 1_000_000
    server_ms = 1_000_000
    runtime.clock = TrustedClock.from_response(server_ms, monotonic_ms, monotonic_ms)
    name = "BTC_USDC-TEST-110000-C"
    amount = AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1"))
    runtime.catalog_options[name] = OptionInstrument(
        name,
        server_ms + 72 * 60 * 60 * 1_000 + 60_000,
        Decimal(110_000),
        OptionType.CALL,
        amount,
    )
    client = FakePublicClient()
    assert not asyncio.run(runtime._sync_option_membership(client))
    runtime.catalog_options[name] = OptionInstrument(
        name,
        server_ms + 72 * 60 * 60 * 1_000,
        Decimal(110_000),
        OptionType.CALL,
        amount,
    )
    assert asyncio.run(runtime._sync_option_membership(client))
    assert client.subscriptions == [ticker_channel(name), book_channel(name)]


def test_new_unknown_member_switches_coverage_before_subscribe_await(
    tmp_path: Path,
    policy_factory: PolicyFactory,
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
    now = time.monotonic_ns() // 1_000_000
    server_ms = 1_000_000
    runtime.clock = TrustedClock.from_response(server_ms, now, now)
    runtime.platform.acknowledge(PLATFORM_CHANNELS)
    runtime.platform.status_usable = True
    runtime.platform.post_status_bootstrap_complete = True
    runtime.platform.maintenance = False
    runtime.platform.public_methods_allowed = True
    runtime.option_catalog.complete = True
    name = "NEW"
    runtime.catalog_options[name] = OptionInstrument(
        name,
        server_ms + 60 * 60_000,
        Decimal(110),
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    runtime._coverage = CoverageLedger(now - 10)
    runtime._coverage.transition(CoverageState.NO_APPLICABLE_SCOPE, now - 5)

    class CoverageAssertingClient(FakePublicClient):
        async def subscribe(self, channels: tuple[str, ...] | list[str]) -> None:
            assert runtime._coverage._current_state is CoverageState.UNKNOWN
            await super().subscribe(channels)

    asyncio.run(runtime._sync_option_membership(CoverageAssertingClient()))


def test_last_scope_removal_and_membership_loss_switch_coverage_before_unsubscribe(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    now = time.monotonic_ns() // 1_000_000
    runtime.clock = TrustedClock.from_response(1_000_000, now, now)
    runtime.platform.acknowledge(PLATFORM_CHANNELS)
    runtime.platform.status_usable = True
    runtime.platform.post_status_bootstrap_complete = True
    runtime.platform.maintenance = False
    runtime.platform.public_methods_allowed = True
    runtime.option_catalog.complete = True
    name = "LEAVING"
    instrument = OptionInstrument(
        name,
        1_000_000 + 60 * 60_000,
        Decimal(110),
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    runtime.options[name] = instrument
    runtime.option_books[name] = ContinuousOrderBook(name)
    tracker = runtime.trackers[name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name=name,
    )
    tracker.observe(
        DetectorObservation(
            causal_seq=1,
            trusted_time=TimeInterval(1_000_000, 1_000_000),
            band_id=policy.tte_bands[0].band_id,
            richness=DecimalInterval(Decimal(2), Decimal(2)),
        ),
        policy.tte_bands[0].option_rules[OptionType.CALL],
    )
    runtime._coverage = CoverageLedger(now - 10)
    runtime._coverage.transition(CoverageState.KNOWN_COMPLETE, now - 5)

    class CoverageAssertingClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.subscriptions.extend([ticker_channel(name), book_channel(name)])

        async def unsubscribe(self, channels: tuple[str, ...] | list[str]) -> None:
            assert runtime._coverage._current_state is CoverageState.NO_APPLICABLE_SCOPE
            assert runtime._episode_end_counts[EpisodeEndReason.MEMBERSHIP_LOSS.value] == 1
            await super().unsubscribe(channels)

    asyncio.run(runtime._sync_option_membership(CoverageAssertingClient()))


def test_ticker_timestamp_regression_resubscribes_only_affected_ticker(
    tmp_path: Path, policy_factory: PolicyFactory
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
    name = "BTC_USDC-TEST-110000-C"
    client = FakePublicClient()
    client.subscriptions.append(ticker_channel(name))

    async def apply_tickers() -> None:
        for timestamp in (2, 1):
            await runtime._handle_message(
                client,
                {
                    "method": "subscription",
                    "params": {
                        "channel": ticker_channel(name),
                        "data": {
                            "instrument_name": name,
                            "timestamp": timestamp,
                            "underlying_price": 100,
                            "underlying_index": "index_price",
                        },
                    },
                },
            )

    asyncio.run(apply_tickers())
    assert name not in runtime.tickers
    assert client.subscriptions == [ticker_channel(name)]


def test_open_close_metadata_response_cannot_resurrect_option(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: Any,
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
    now = time.monotonic_ns() // 1_000_000
    runtime.clock = TrustedClock.from_response(1_000_000, now, now)
    runtime.option_catalog.complete = True

    class RacingMetadataClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.metadata_started = asyncio.Event()
            self.metadata_release = asyncio.Event()
            self.close_sent = False

        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            if method == "public/get_instrument":
                self.metadata_started.set()
                await self.metadata_release.wait()
                return InboundEnvelope(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": option_payload_factory(
                            name=str(params["instrument_name"]),
                            expiry=2_000_000,
                        ),
                    },
                    ingress_seq=3,
                    received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                )
            return await super().request(
                method,
                params,
                responding_to_test_request=responding_to_test_request,
            )

        async def next_notification(
            self, timeout_seconds: float | None = None
        ) -> dict[str, object]:
            await self.metadata_started.wait()
            if self.close_sent:
                await asyncio.sleep(timeout_seconds or 0)
                raise TimeoutError
            self.close_sent = True
            self.metadata_release.set()
            return StampedMessage(
                {
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option.USDC",
                        "data": {"instrument_name": "RACE", "state": "closed"},
                    },
                },
                ingress_seq=2,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )

    async def scenario() -> None:
        client = RacingMetadataClient()
        await runtime._handle_message(
            client,
            StampedMessage(
                {
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option.USDC",
                        "data": {"instrument_name": "RACE", "state": "open"},
                    },
                },
                ingress_seq=1,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            ),
        )

    asyncio.run(scenario())

    assert "RACE" not in runtime.catalog_options
    assert "RACE" not in runtime.options
    assert runtime._max_economic_reducer_depth == 1


def test_close_during_option_snapshot_pending_is_reconciled_after_snapshot(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: Any,
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
    now = time.monotonic_ns() // 1_000_000
    runtime.clock = TrustedClock.from_response(1_000_000, now, now)
    runtime.option_catalog.complete = False

    class RacingSnapshotClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.snapshot_started = asyncio.Event()
            self.snapshot_release = asyncio.Event()
            self.close_sent = False
            self.later_lifecycle_drained = False

        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            if method == "public/get_instruments":
                self.snapshot_started.set()
                await self.snapshot_release.wait()
                return InboundEnvelope(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": [option_payload_factory(name="SNAPSHOT", expiry=2_000_000)],
                    },
                    ingress_seq=2,
                    received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                )
            return await super().request(
                method,
                params,
                responding_to_test_request=responding_to_test_request,
            )

        async def next_notification(
            self, timeout_seconds: float | None = None
        ) -> dict[str, object]:
            await self.snapshot_started.wait()
            if self.close_sent:
                await asyncio.sleep(timeout_seconds or 0)
                raise TimeoutError
            self.close_sent = True
            self.snapshot_release.set()
            return StampedMessage(
                {
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option.USDC",
                        "data": {"instrument_name": "SNAPSHOT", "state": "closed"},
                    },
                },
                ingress_seq=1,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )

        def drain_notifications(self) -> tuple[dict[str, object], ...]:
            if self.later_lifecycle_drained:
                return ()
            self.later_lifecycle_drained = True
            return (
                StampedMessage(
                    {
                        "method": "subscription",
                        "params": {
                            "channel": "instrument.state.option.USDC",
                            "data": {"instrument_name": "UNRELATED", "state": "closed"},
                        },
                    },
                    ingress_seq=3,
                    received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                ),
            )

    asyncio.run(runtime._recover_option_catalog(RacingSnapshotClient()))

    assert "SNAPSHOT" not in runtime.catalog_options
    assert "SNAPSHOT" not in runtime.options


def test_combo_lifecycle_during_refresh_requests_one_trailing_refresh(
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

    class LifecycleDuringRefreshClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.refresh_count = 0
            self.first_started = asyncio.Event()
            self.first_release = asyncio.Event()
            self.lifecycle_sent = False

        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            if method == "public/get_combos":
                self.refresh_count += 1
                if self.refresh_count == 1:
                    self.first_started.set()
                    await self.first_release.wait()
                return InboundEnvelope(
                    {"jsonrpc": "2.0", "id": self.refresh_count, "result": []},
                    ingress_seq=self.refresh_count + 1,
                    received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                )
            return await super().request(
                method,
                params,
                responding_to_test_request=responding_to_test_request,
            )

        async def next_notification(
            self, timeout_seconds: float | None = None
        ) -> dict[str, object]:
            await self.first_started.wait()
            if self.lifecycle_sent:
                await asyncio.sleep(timeout_seconds or 0)
                raise TimeoutError
            self.lifecycle_sent = True
            self.first_release.set()
            return StampedMessage(
                {
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option_combo.USDC",
                        "data": {"instrument_name": "COMBO", "state": "created"},
                    },
                },
                ingress_seq=1,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )

    client = LifecycleDuringRefreshClient()
    asyncio.run(runtime._coalesced_combo_refresh(client))

    assert client.refresh_count == 2


def test_bootstrap_reconciliation_retains_lifecycle_arriving_during_metadata(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    option_payload_factory: Any,
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

    class BootstrapLifecycleClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.notifications: asyncio.Queue[dict[str, object]] = asyncio.Queue()
            self.snapshot_started = asyncio.Event()
            self.snapshot_release = asyncio.Event()
            self.metadata_started = asyncio.Event()
            self.metadata_release = asyncio.Event()

        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            if method == "public/get_instruments":
                self.snapshot_started.set()
                await self.snapshot_release.wait()
                return InboundEnvelope(
                    {"jsonrpc": "2.0", "id": 1, "result": []},
                    ingress_seq=2,
                    received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                )
            if method == "public/get_instrument":
                self.metadata_started.set()
                await self.metadata_release.wait()
                return InboundEnvelope(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": option_payload_factory(
                            name=str(params["instrument_name"]),
                            expiry=2_000_000,
                        ),
                    },
                    ingress_seq=4,
                    received_monotonic_ms=time.monotonic_ns() // 1_000_000,
                )
            return await super().request(
                method,
                params,
                responding_to_test_request=responding_to_test_request,
            )

        async def next_notification(
            self, timeout_seconds: float | None = None
        ) -> dict[str, object]:
            if timeout_seconds is None:
                return await self.notifications.get()
            return await asyncio.wait_for(self.notifications.get(), timeout_seconds)

        def drain_notifications(self) -> tuple[dict[str, object], ...]:
            drained: list[dict[str, object]] = []
            while True:
                try:
                    drained.append(self.notifications.get_nowait())
                except asyncio.QueueEmpty:
                    return tuple(drained)

    async def scenario() -> None:
        client = BootstrapLifecycleClient()
        bootstrap = asyncio.create_task(runtime._bootstrap(client))
        await client.snapshot_started.wait()
        await client.notifications.put(
            StampedMessage(
                {
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option.USDC",
                        "data": {"instrument_name": "BOOT", "state": "open"},
                    },
                },
                ingress_seq=1,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )
        )
        await asyncio.sleep(0)
        client.snapshot_release.set()
        await client.metadata_started.wait()
        await client.notifications.put(
            StampedMessage(
                {
                    "method": "subscription",
                    "params": {
                        "channel": "instrument.state.option.USDC",
                        "data": {"instrument_name": "BOOT", "state": "closed"},
                    },
                },
                ingress_seq=3,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )
        )
        await asyncio.sleep(0)
        client.metadata_release.set()
        await bootstrap

    asyncio.run(scenario())

    assert "BOOT" not in runtime.catalog_options
    assert "BOOT" not in runtime.options


@pytest.mark.parametrize("operation", ["subscribe", "unsubscribe"])
def test_blocked_channel_change_still_services_test_request(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    operation: str,
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
    now = time.monotonic_ns() // 1_000_000
    server_ms = 1_000_000
    runtime.clock = TrustedClock.from_response(server_ms, now, now)
    name = "CHANNEL"
    instrument = OptionInstrument(
        name,
        server_ms + 60 * 60_000,
        Decimal(110),
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    if operation == "subscribe":
        runtime.catalog_options[name] = instrument
    else:
        runtime.options[name] = instrument
        runtime.option_books[name] = ContinuousOrderBook(name)
        runtime.trackers[name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=digest,
            instrument_name=name,
        )

    class BlockingChannelClient(FakePublicClient):
        def __init__(self) -> None:
            super().__init__()
            self.notifications: asyncio.Queue[dict[str, object]] = asyncio.Queue()
            self.change_started = asyncio.Event()
            self.change_release = asyncio.Event()
            self.test_answered = asyncio.Event()
            if operation == "unsubscribe":
                self.subscriptions.extend([ticker_channel(name), book_channel(name)])

        async def subscribe(self, channels: tuple[str, ...] | list[str]) -> None:
            self.change_started.set()
            await self.change_release.wait()
            await super().subscribe(channels)

        async def unsubscribe(self, channels: tuple[str, ...] | list[str]) -> None:
            self.change_started.set()
            await self.change_release.wait()
            await super().unsubscribe(channels)

        async def request(
            self,
            method: str,
            params: dict[str, object],
            *,
            responding_to_test_request: bool = False,
        ) -> object:
            if method == "public/test":
                assert responding_to_test_request
                self.test_answered.set()
                return {"version": "2.1.1"}
            return await super().request(
                method,
                params,
                responding_to_test_request=responding_to_test_request,
            )

        async def next_notification(
            self, timeout_seconds: float | None = None
        ) -> dict[str, object]:
            if timeout_seconds is None:
                return await self.notifications.get()
            return await asyncio.wait_for(self.notifications.get(), timeout_seconds)

        def drain_notifications(self) -> tuple[dict[str, object], ...]:
            return ()

    async def scenario() -> bool:
        client = BlockingChannelClient()
        change = asyncio.create_task(runtime._sync_option_membership(client))
        await client.change_started.wait()
        await client.notifications.put(
            StampedMessage(
                {
                    "method": "heartbeat",
                    "params": {"type": "test_request"},
                },
                ingress_seq=1,
                received_monotonic_ms=time.monotonic_ns() // 1_000_000,
            )
        )
        try:
            await asyncio.wait_for(client.test_answered.wait(), timeout=0.1)
            answered = True
        except TimeoutError:
            answered = False
        finally:
            client.change_release.set()
            await change
        return answered

    assert asyncio.run(scenario())
    assert runtime._noted_notification_ids == set()


@pytest.mark.parametrize(
    ("amount", "expected_state", "expected_end"),
    [
        (None, DetectorState.UNKNOWN, EpisodeEndReason.UNKNOWN_DETECTOR),
        (
            AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.3")),
            DetectorState.NO_ANOMALY,
            EpisodeEndReason.KNOWN_INELIGIBLE,
        ),
    ],
)
def test_amount_loss_ends_episode_and_stops_layer_two_in_same_scope_snapshot(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    amount: AmountMetadata | None,
    expected_state: DetectorState,
    expected_end: EpisodeEndReason,
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    now = time.monotonic_ns() // 1_000_000
    server_ms = 1_000_000
    runtime.clock = TrustedClock.from_response(server_ms, now, now)
    runtime.platform.acknowledge(PLATFORM_CHANNELS)
    runtime.platform.status_usable = True
    runtime.platform.post_status_bootstrap_complete = True
    runtime.platform.maintenance = False
    runtime.platform.public_methods_allowed = True
    runtime.option_catalog.complete = True
    name = "AMOUNT"
    runtime.options[name] = OptionInstrument(
        name,
        server_ms + 60 * 60_000,
        Decimal(110),
        OptionType.CALL,
        amount,
    )
    tracker = runtime.trackers[name] = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name=name,
    )
    tracker.observe(
        DetectorObservation(
            causal_seq=1,
            trusted_time=TimeInterval(server_ms, server_ms),
            band_id=policy.tte_bands[0].band_id,
            richness=DecimalInterval(Decimal(2), Decimal(2)),
        ),
        policy.tte_bands[0].option_rules[OptionType.CALL],
    )
    episode_id = tracker.episode_id
    assert episode_id is not None
    runtime.atomic_states[episode_id] = PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE
    book = runtime.option_books[name] = ContinuousOrderBook(name)
    book.apply(
        {
            "type": "snapshot",
            "timestamp": server_ms,
            "instrument_name": name,
            "change_id": 1,
            "bids": [["new", 1, "0.1"]],
            "asks": [],
        },
        now,
    )

    asyncio.run(
        runtime._evaluate_one(
            FakePublicClient(),
            name,
            evaluation_monotonic_ms=now,
            boundary_observation_eligible=False,
            observation_reason="METADATA_ONLY",
        )
    )

    assert tracker.detector_state is expected_state
    assert tracker.episode_id is None
    assert episode_id not in runtime.atomic_states
    assert runtime._episode_end_counts[expected_end.value] == 1


def test_global_index_gap_changes_every_instrument_in_scope_in_one_pass(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    now = time.monotonic_ns() // 1_000_000
    server_ms = 1_000_000
    runtime.clock = TrustedClock.from_response(server_ms, now, now)
    runtime.platform.acknowledge(PLATFORM_CHANNELS)
    runtime.platform.status_usable = True
    runtime.platform.post_status_bootstrap_complete = True
    runtime.platform.maintenance = False
    runtime.platform.public_methods_allowed = True
    runtime.option_catalog.complete = True
    amount = AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1"))
    for name, strike in (("FIRST", Decimal(110)), ("SECOND", Decimal(120))):
        runtime.options[name] = OptionInstrument(
            name,
            server_ms + 60 * 60_000,
            strike,
            OptionType.CALL,
            amount,
        )
        tracker = runtime.trackers[name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=digest,
            instrument_name=name,
        )
        tracker.observe(
            DetectorObservation(
                causal_seq=1,
                trusted_time=TimeInterval(server_ms, server_ms),
                band_id=policy.tte_bands[0].band_id,
                richness=DecimalInterval(Decimal(2), Decimal(2)),
            ),
            policy.tte_bands[0].option_rules[OptionType.CALL],
        )
    monkeypatch.setattr(
        runtime.index,
        "current_window",
        lambda *_args, **_kwargs: IndexWindow(None, "INDEX_BASELINE_GAP"),
    )
    client = FakePublicClient()
    client.subscriptions.append(INDEX_CHANNEL)

    asyncio.run(runtime._evaluate_one(client, "FIRST", evaluation_monotonic_ms=now))

    assert set(runtime.results) == {"FIRST", "SECOND"}
    assert {result.reason for result in runtime.results.values()} == {"INDEX_BASELINE_GAP"}
    assert all(
        tracker.detector_state is DetectorState.UNKNOWN for tracker in runtime.trackers.values()
    )
    assert runtime._episode_end_counts[EpisodeEndReason.UNKNOWN_AT_GAP.value] == 2


def test_final_window_timer_boundary_ends_entire_scope_without_market_update(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    now = time.monotonic_ns() // 1_000_000
    server_ms = 1_000_000
    runtime.clock = TrustedClock.from_response(server_ms, now, now)
    runtime.platform.acknowledge(PLATFORM_CHANNELS)
    runtime.platform.status_usable = True
    runtime.platform.post_status_bootstrap_complete = True
    runtime.platform.maintenance = False
    runtime.platform.public_methods_allowed = True
    runtime.option_catalog.complete = True
    amount = AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1"))
    episode_ids: list[str] = []
    for name, strike in (("FIRST", Decimal(110)), ("SECOND", Decimal(120))):
        runtime.options[name] = OptionInstrument(
            name,
            server_ms + 30 * 60_000,
            strike,
            OptionType.CALL,
            amount,
        )
        tracker = runtime.trackers[name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=digest,
            instrument_name=name,
        )
        tracker.observe(
            DetectorObservation(
                causal_seq=1,
                trusted_time=TimeInterval(server_ms - 1, server_ms - 1),
                band_id=policy.tte_bands[0].band_id,
                richness=DecimalInterval(Decimal(2), Decimal(2)),
            ),
            policy.tte_bands[0].option_rules[OptionType.CALL],
        )
        assert tracker.episode_id is not None
        episode_ids.append(tracker.episode_id)
        runtime.atomic_states[tracker.episode_id] = PublicAtomicQuoteState.UNKNOWN

    asyncio.run(
        runtime._evaluate_all(
            FakePublicClient(),
            evaluation_monotonic_ms=now,
            boundary_observation_eligible=False,
            observation_reason="CLOCK_ONLY",
        )
    )

    assert all(tracker.episode_id is None for tracker in runtime.trackers.values())
    assert runtime._episode_end_counts[EpisodeEndReason.OUT_OF_BASELINE_SCOPE.value] == 2
    assert all(episode_id not in runtime.atomic_states for episode_id in episode_ids)
    assert runtime._coverage._current_state is CoverageState.NO_APPLICABLE_SCOPE


def test_policy_gap_timer_boundary_ends_entire_scope_without_market_update(
    tmp_path: Path,
) -> None:
    document = policy_document(activation_count=1, separation_ms=0)
    bands = document["tte_bands"]
    assert isinstance(bands, list)
    first_band, second_band = bands
    assert isinstance(first_band, dict)
    assert isinstance(second_band, dict)
    first_band["upper_bound_minutes"] = 330
    second_band["lower_bound_minutes"] = 390
    exact, digest = encode_policy(document)
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
    now = time.monotonic_ns() // 1_000_000
    server_ms = 1_000_000
    runtime.clock = TrustedClock.from_response(server_ms, now, now)
    runtime.platform.acknowledge(PLATFORM_CHANNELS)
    runtime.platform.status_usable = True
    runtime.platform.post_status_bootstrap_complete = True
    runtime.platform.maintenance = False
    runtime.platform.public_methods_allowed = True
    runtime.option_catalog.complete = True
    amount = AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1"))
    episode_ids: list[str] = []
    for name, strike in (("FIRST", Decimal(110)), ("SECOND", Decimal(120))):
        runtime.options[name] = OptionInstrument(
            name,
            server_ms + 360 * 60_000,
            strike,
            OptionType.CALL,
            amount,
        )
        tracker = runtime.trackers[name] = EpisodeTracker(
            runtime_identity="runtime",
            policy_identity=digest,
            instrument_name=name,
        )
        tracker.observe(
            DetectorObservation(
                causal_seq=1,
                trusted_time=TimeInterval(server_ms - 1, server_ms - 1),
                band_id=policy.tte_bands[0].band_id,
                richness=DecimalInterval(Decimal(2), Decimal(2)),
            ),
            policy.tte_bands[0].option_rules[OptionType.CALL],
        )
        assert tracker.episode_id is not None
        episode_ids.append(tracker.episode_id)
        runtime.atomic_states[tracker.episode_id] = PublicAtomicQuoteState.UNKNOWN

    asyncio.run(
        runtime._evaluate_all(
            FakePublicClient(),
            evaluation_monotonic_ms=now,
            boundary_observation_eligible=False,
            observation_reason="CLOCK_ONLY",
        )
    )

    assert all(tracker.episode_id is None for tracker in runtime.trackers.values())
    assert runtime._episode_end_counts[EpisodeEndReason.OUT_OF_BASELINE_SCOPE.value] == 2
    assert all(episode_id not in runtime.atomic_states for episode_id in episode_ids)
    assert runtime._coverage._current_state is CoverageState.NO_APPLICABLE_SCOPE


def test_band_suspension_pauses_known_active_duration(
    tmp_path: Path, policy_factory: PolicyFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    exact, digest = policy_factory(activation_count=1, separation_ms=0)
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
    tracker = EpisodeTracker(
        runtime_identity="runtime",
        policy_identity=digest,
        instrument_name="SHORT",
    )
    rule = policy.tte_bands[0].option_rules[OptionType.CALL]
    tracker.observe(
        DetectorObservation(
            1,
            TimeInterval(0, 0),
            policy.tte_bands[0].band_id,
            DecimalInterval(Decimal("1.3"), Decimal("1.3")),
        ),
        rule,
    )
    episode_id = tracker.episode_id
    assert episode_id is not None
    runtime.options["SHORT"] = OptionInstrument(
        "SHORT",
        10_000_000,
        Decimal(110_000),
        OptionType.CALL,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )
    runtime._episode_active_segment_started_ms[episode_id] = 100
    runtime._episode_active_accumulated_ms[episode_id] = 0
    runtime._episode_option_types[episode_id] = OptionType.CALL
    runtime.atomic_states[episode_id] = PublicAtomicQuoteState.UNKNOWN

    monotonic = iter((200, 500, 700))
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: next(monotonic))
    previous_state = tracker.state
    tracker.suspend_for_band_boundary()
    runtime._record_band_timing(
        previous_state=previous_state,
        previous_episode_id=episode_id,
        tracker=tracker,
    )
    runtime._record_atomic_transition(
        tracker,
        PublicAtomicQuoteState.NOT_EVALUATED,
        band_id=policy.tte_bands[0].band_id,
    )
    assert tracker.state is TrackerState.BAND_SUSPENDED

    previous_state = tracker.state
    tracker.resume_after_band_boundary()
    runtime._record_band_timing(
        previous_state=previous_state,
        previous_episode_id=episode_id,
        tracker=tracker,
    )
    ended = tracker.stop(causal_seq=2).ended_episode
    runtime._record_episode_end(ended)

    assert runtime._band_suspended_duration_ms == 300
    assert runtime._known_active_duration_ms[EpisodeEndReason.CENSORED_AT_STOP.value] == 300
    scope = runtime._scope_counter(OptionType.CALL, policy.tte_bands[0].band_id)
    assert scope.anomaly_end_count_by_reason[EpisodeEndReason.CENSORED_AT_STOP.value] == 1
    assert (
        scope.known_active_duration_ms_sum_by_end_reason[EpisodeEndReason.CENSORED_AT_STOP.value]
        == 300
    )
    assert (
        scope.public_atomic_quote_state_transition_count[PublicAtomicQuoteState.NOT_EVALUATED.value]
        == 1
    )


def test_no_forbidden_later_stage_or_replay_modules_exist(repository_root: Path) -> None:
    source_paths = tuple((repository_root / "packages").rglob("*.py")) + tuple(
        (repository_root / "apps").rglob("*.py")
    )
    path_text = "\n".join(path.relative_to(repository_root).as_posix() for path in source_paths)
    for forbidden in (
        "replay",
        "recompute",
        "provenance",
        "candidate",
        "shadow",
        "position",
        "outcome",
        "maker",
        "account",
    ):
        assert forbidden not in path_text.lower()
    assert not any(path.name.endswith(".sqlite") for path in repository_root.rglob("*"))
