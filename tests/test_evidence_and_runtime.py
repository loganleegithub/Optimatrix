from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from pathlib import Path

import pytest
import radar_runtime.runtime as runtime_module
from conftest import PolicyFactory
from market_monitor import ContinuousOrderBook, PriceLevel, TimeInterval, TrustedClock
from market_monitor.deribit import book_channel, ticker_channel
from options_domain import AmountMetadata, OptionInstrument, OptionType
from radar_runtime.deribit_public import (
    PUBLIC_METHODS,
    DeribitPublicClient,
    PublicProtocolError,
)
from radar_runtime.identity import (
    StartupGuardError,
    prepare_evidence_directory,
    validate_clean_git_outputs,
)
from radar_runtime.runtime import LiveRadarRuntime, ScopeCounts
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
    DetectorObservation,
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
from short_vol_radar.radar import TickerState


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
    writer.write_summary(summary_object())
    objects = validate_evidence_directory(tmp_path)
    assert len(objects) == 3


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
            return "ok"
        if method in {"public/get_instruments", "public/get_combos"}:
            return []
        raise AssertionError(f"unexpected fake request {method} {params}")

    async def subscribe(self, channels: tuple[str, ...] | list[str]) -> None:
        self.calls.append("public/subscribe")
        self.subscriptions.extend(channels)

    async def unsubscribe(self, channels: tuple[str, ...] | list[str]) -> None:
        self.calls.append("public/unsubscribe")
        for channel in channels:
            self.subscriptions.remove(channel)

    async def next_notification(self, timeout_seconds: float | None = None) -> dict[str, object]:
        raise AssertionError(f"unexpected notification wait {timeout_seconds}")

    def drain_notifications(self) -> tuple[dict[str, object], ...]:
        return ()


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
    assert coverage["unknown_ms"] >= 1
    assert all(method.startswith("public/") for method in client.calls)
    assert not any(tmp_path.glob("*market*"))
    assert not any(tmp_path.glob("*no-anomaly*"))


def test_platform_bootstrap_waits_for_initial_index_ticker_and_book(
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
    assert not runtime.platform.usable

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
    assert runtime.option_books[name].reason == "CONNECTION_CLOSED"
    runtime._reset_session_state()
    assert runtime.clock is None
    assert runtime.options == {}
    assert runtime.option_books == {}


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
