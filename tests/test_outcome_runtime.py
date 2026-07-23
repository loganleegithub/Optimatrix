from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from market_tape import CanonicalEvent, EventKind, canonical_digest, write_capture
from radar_runtime.deribit_public import (
    CAPTURE_RECEIPT_TYPE,
    LIVE_CAPTURE_EVIDENCE,
    WEBSOCKET_URL,
    _event_summary,
    build_decision_receipt,
    decision_receipt_payload,
    inspect_payload,
    project_events,
    projection_payload,
)
from radar_runtime.outcome_bundle import (
    create_outcome_evidence_bundle,
    verify_outcome_evidence_bundle,
)
from radar_runtime.outcome_identity import outcome_runtime_source_identity
from radar_runtime.outcome_runtime import (
    FUTURE_PLATFORM_PROBE_ID,
    PUBLIC_COLLECTOR_ENTRYPOINT_ID,
    PUBLIC_EVIDENCE_CLASS,
    PUBLIC_INVOCATION_RECEIPT_TYPE,
    _compose,
    _DeadlineConnection,
    _future_platform_barrier_capture_seqs,
    _OutcomeLiveSession,
    _persist_composition,
    _record_connection_attempt_failure,
    _refresh_outcome_platform_barrier,
    _validate_future_platform_barrier_capture_seqs,
    build_synthetic_outcome_events,
    reconstruct_outcome,
    replay_outcome,
    run_public_outcome_capture,
    run_synthetic_outcome,
)
from radar_runtime.outcome_seal import decision_cutoff, read_sealed_capture, seal_capture
from radar_runtime.runtime_identity import runtime_source_identity
from websockets.sync.connection import Connection


def _object(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _payload(event: CanonicalEvent) -> dict[str, object]:
    value: object = json.loads(event.raw_payload)
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _without_candidate(
    events: tuple[CanonicalEvent, ...],
) -> tuple[CanonicalEvent, ...]:
    cutoff = decision_cutoff(events)
    changed: list[CanonicalEvent] = []
    for event in events:
        if (
            event.capture_seq <= cutoff.capture_seq
            and event.event_kind is EventKind.TICKER
            and event.instrument_name is not None
            and event.instrument_name != "BTC_USDC-PERPETUAL"
        ):
            payload = _payload(event)
            payload["best_bid_price"] = "1"
            payload["best_ask_price"] = "2"
            event = replace(
                event,
                raw_payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            )
        changed.append(event)
    return tuple(changed)


def _without_schedule(
    events: tuple[CanonicalEvent, ...],
) -> tuple[CanonicalEvent, ...]:
    return tuple(
        replace(
            event,
            event_kind=EventKind.HEARTBEAT,
            channel="heartbeat",
            raw_payload="{}",
        )
        if event.event_kind is EventKind.SCHEDULED_BLOCK_STATE
        else event
        for event in events
    )


def _write_composed_run(
    output: Path,
    events: tuple[CanonicalEvent, ...],
    *,
    provenance: str,
    duration_seconds: int,
) -> dict[str, object]:
    output.mkdir()
    full = output / "_full-capture" / "capture"
    write_capture(full, events, complete=True)
    seal_capture(full, output / "facts")
    decision_identity = runtime_source_identity(require_clean=False)
    outcome_identity = outcome_runtime_source_identity(require_clean=False)
    collector_invocation_digest: str | None = None
    if provenance == "production_public":
        invocation = _write_mock_public_collector_artifacts(
            output,
            git_commit_sha=outcome_identity.git_commit_sha,
        )
        raw_invocation_digest = invocation["invocation_digest"]
        assert isinstance(raw_invocation_digest, str)
        collector_invocation_digest = raw_invocation_digest
    composition = _compose(
        output / "facts",
        fact_provenance=provenance,
        evidence_class=(
            PUBLIC_EVIDENCE_CLASS if provenance == "production_public" else "SYNTHETIC_LOGIC"
        ),
        duration_seconds=duration_seconds,
        decision_identity=decision_identity,
        outcome_identity=outcome_identity,
        evidence_git_commit_sha=outcome_identity.git_commit_sha,
        collector_invocation_digest=collector_invocation_digest,
    )
    _persist_composition(output, composition)
    shutil.rmtree(output / "_full-capture")
    return composition.result


def _rewrite_result(path: Path, updates: dict[str, object]) -> None:
    payload = _object(path)
    payload.update(updates)
    payload.pop("result_digest", None)
    payload["result_digest"] = canonical_digest(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _public_zero_events() -> tuple[CanonicalEvent, ...]:
    events = _without_candidate(build_synthetic_outcome_events())
    cutoff = decision_cutoff(events)
    suffix_elapsed = (
        cutoff.target_elapsed_ms + 1,
        cutoff.target_elapsed_ms + 2,
        cutoff.target_elapsed_ms + 1_000,
        cutoff.target_elapsed_ms + 2_000,
        cutoff.target_elapsed_ms + 3_000,
        cutoff.target_elapsed_ms + 5_000,
    )
    return tuple(
        replace(event, collector_elapsed_ms=suffix_elapsed[event.capture_seq - 145])
        if event.capture_seq > cutoff.capture_seq
        else event
        for event in events
    )


def _write_mock_public_collector_artifacts(
    run: Path,
    *,
    git_commit_sha: str,
) -> dict[str, object]:
    _seal, manifest, events, _prefix_manifest, _prefix_events = read_sealed_capture(run / "facts")
    identity = runtime_source_identity(require_clean=False)
    projection = project_events(events)
    outcome_identity = outcome_runtime_source_identity(require_clean=False)
    decision = build_decision_receipt(
        manifest,
        projection,
        source_identity=identity,
        receipt_git_commit_sha=git_commit_sha,
    )
    decision_payload = decision_receipt_payload(decision)
    live = {
        "receipt_type": CAPTURE_RECEIPT_TYPE,
        "environment": "production_public",
        "duration_seconds": 3_665,
        **_event_summary(manifest, events),
        **projection_payload(projection),
        "decision_receipt_digest": decision.digest,
        "git_commit_sha": git_commit_sha,
        "runtime_source_id": identity.runtime_source_id,
        "runtime_source_digest": identity.runtime_source_digest,
        "evidence_class": LIVE_CAPTURE_EVIDENCE,
    }
    inspected = inspect_payload(manifest, events, source_identity=identity)
    for name, payload in (
        ("collector-live.json", live),
        ("collector-decision.json", decision_payload),
        ("collector-inspect.json", inspected),
    ):
        (run / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    invocation = {
        "receipt_type": PUBLIC_INVOCATION_RECEIPT_TYPE,
        "environment": "production_public",
        "transport_endpoint": WEBSOCKET_URL,
        "collector_entrypoint_id": PUBLIC_COLLECTOR_ENTRYPOINT_ID,
        "future_platform_probe_id": FUTURE_PLATFORM_PROBE_ID,
        "requested_duration_seconds": 3_665,
        "invocation_started_at": "2026-07-20T00:00:00+00:00",
        "invocation_finished_at": "2026-07-20T01:01:05+00:00",
        "invocation_elapsed_ms": max(3_665_000, events[-1].collector_elapsed_ms + 1),
        "records": manifest.record_count,
        "capture_digest": manifest.content_sha256,
        "capture_manifest_digest": manifest.digest,
        "future_platform_subscription_capture_seq": (
            _future_platform_barrier_capture_seqs(events)[0]
        ),
        "future_platform_status_capture_seq": _future_platform_barrier_capture_seqs(events)[1],
        "collector_live_sha256": hashlib.sha256(
            (run / "collector-live.json").read_bytes()
        ).hexdigest(),
        "collector_decision_sha256": hashlib.sha256(
            (run / "collector-decision.json").read_bytes()
        ).hexdigest(),
        "collector_inspect_sha256": hashlib.sha256(
            (run / "collector-inspect.json").read_bytes()
        ).hexdigest(),
        "git_commit_sha": git_commit_sha,
        "runtime_source_id": identity.runtime_source_id,
        "runtime_source_digest": identity.runtime_source_digest,
        "outcome_runtime_source_id": outcome_identity.runtime_source_id,
        "outcome_runtime_source_digest": outcome_identity.runtime_source_digest,
    }
    invocation["invocation_digest"] = canonical_digest(invocation)
    (run / "collector-invocation.json").write_text(
        json.dumps(invocation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return invocation


def test_cutoff_is_fixed_to_initial_subscriptions_and_does_not_retry() -> None:
    events = build_synthetic_outcome_events()
    expected = decision_cutoff(events)
    assert expected.capture_seq == 144
    assert expected.required_subscription_capture_seqs == (1, 2, 4)

    reconnect = replace(events[20], event_kind=EventKind.RECONNECT, raw_payload="{}")
    reconnected = (*events[:20], reconnect, *events[21:])
    assert decision_cutoff(reconnected) == expected

    early_reconnect = replace(events[2], event_kind=EventKind.RECONNECT, raw_payload="{}")
    incomplete_initial = (*events[:2], early_reconnect, *events[3:])
    with pytest.raises(ValueError, match="initial connection ended"):
        decision_cutoff(incomplete_initial)


def test_outcome_platform_probe_records_an_accepted_strict_future_barrier() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self.responses = [
                {"jsonrpc": "2.0", "id": 10, "result": ["platform_state"]},
                {"jsonrpc": "2.0", "id": 11, "result": {"locked": False}},
            ]

        def send(self, value: str) -> None:
            decoded: object = json.loads(value)
            assert isinstance(decoded, dict)
            self.sent.append(cast(dict[str, object], decoded))

        def recv(self, *, timeout: float) -> str:
            assert timeout > 0
            return json.dumps(self.responses.pop(0))

    session = _OutcomeLiveSession()
    session.record_heartbeat({}, received_at_ms=1, elapsed_ms=0)
    fake = FakeConnection()
    (
        next_request_id,
        _test_request_id,
        subscription_capture_seq,
        status_capture_seq,
    ) = _refresh_outcome_platform_barrier(
        cast(Connection, fake),
        session,
        cutoff_capture_seq=1,
        request_id=10,
        test_request_id=1_000,
    )

    assert next_request_id == 12
    assert (subscription_capture_seq, status_capture_seq) == (2, 3)
    assert [item["method"] for item in fake.sent] == [
        "public/subscribe",
        "public/status",
    ]
    assert session.events[-2].event_kind is EventKind.SUBSCRIPTION_START
    assert session.events[-1].event_kind is EventKind.PLATFORM_STATE
    platform = session.projector.reducer.snapshot().platform_state
    assert platform is not None
    assert platform.state == "OPEN"
    assert platform.source_capture_seqs == (2, 3)


def test_outcome_platform_probe_starts_a_fresh_control_generation() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.responses = [
                {"jsonrpc": "2.0", "id": 10, "result": ["platform_state"]},
                {"jsonrpc": "2.0", "id": 11, "result": {"locked": False}},
            ]

        def send(self, value: str) -> None:
            assert isinstance(json.loads(value), dict)

        def recv(self, *, timeout: float) -> str:
            assert timeout > 0
            return json.dumps(self.responses.pop(0))

    session = _OutcomeLiveSession()
    session.record_subscription_start(received_at_ms=1, elapsed_ms=0)
    session.record_platform(
        {"locked": False},
        channel="public/status",
        received_at_ms=2,
        elapsed_ms=0,
    )
    session.record_platform(
        {"maintenance": False},
        channel="platform_state",
        received_at_ms=3,
        elapsed_ms=0,
    )
    old_platform_sources = session.projector.reducer.snapshot().platform_state
    assert old_platform_sources is not None
    assert old_platform_sources.source_capture_seqs == (3, 4, 5)

    _, _, subscription_capture_seq, status_capture_seq = _refresh_outcome_platform_barrier(
        cast(Connection, FakeConnection()),
        session,
        cutoff_capture_seq=5,
        request_id=10,
        test_request_id=1_000,
    )
    platform = session.projector.reducer.snapshot().platform_state
    assert platform is not None

    assert (subscription_capture_seq, status_capture_seq) == (6, 7)
    assert platform.state == "OPEN"
    assert platform.source_capture_seqs == (6, 7)


def test_outcome_platform_probe_has_one_absolute_receive_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class IrrelevantConnection:
        def send(self, value: str) -> None:
            assert isinstance(json.loads(value), dict)

        def recv(self, *, timeout: float) -> str:
            assert timeout > 0
            return json.dumps({"jsonrpc": "2.0", "id": 999, "result": "irrelevant"})

    ticks = iter((0.0, 2.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    guarded = _DeadlineConnection(cast(Connection, IrrelevantConnection()), deadline=1.0)
    session = _OutcomeLiveSession()
    session.record_heartbeat({}, received_at_ms=1, elapsed_ms=0)

    with pytest.raises(TimeoutError, match="deadline elapsed"):
        _refresh_outcome_platform_barrier(
            cast(Connection, guarded),
            session,
            cutoff_capture_seq=1,
            request_id=10,
            test_request_id=1_000,
        )


def test_future_platform_barrier_cannot_pair_across_reconnect() -> None:
    events = list(build_synthetic_outcome_events())
    original_status = events[145]
    events[145] = replace(
        original_status,
        event_kind=EventKind.RECONNECT,
        channel="control",
        raw_payload='{"reason":"test"}',
    )
    events[146] = replace(
        original_status,
        capture_seq=147,
        raw_payload=json.dumps(
            {"locked": False, "state": "OPEN", "status_capture_seq": 147},
            sort_keys=True,
            separators=(",", ":"),
        ),
    )

    with pytest.raises(ValueError, match="no strict-future platform barrier"):
        _future_platform_barrier_capture_seqs(tuple(events))


def test_future_platform_barrier_rejects_old_or_incomplete_lineage() -> None:
    events = build_synthetic_outcome_events()
    _validate_future_platform_barrier_capture_seqs(
        events,
        subscription_capture_seq=145,
        status_capture_seq=146,
    )
    status_payload = _payload(events[145])
    status_payload["source_capture_seqs"] = [3, 145]
    contaminated = (
        *events[:145],
        replace(
            events[145],
            raw_payload=json.dumps(status_payload, sort_keys=True, separators=(",", ":")),
        ),
        *events[146:],
    )

    with pytest.raises(ValueError, match="barrier generation is invalid"):
        _validate_future_platform_barrier_capture_seqs(
            contaminated,
            subscription_capture_seq=145,
            status_capture_seq=146,
        )
    unknown_payload = _payload(events[145])
    unknown_payload.update({"state": "UNKNOWN", "locked": None})
    unknown_status = (
        *events[:145],
        replace(
            events[145],
            raw_payload=json.dumps(unknown_payload, sort_keys=True, separators=(",", ":")),
        ),
        *events[146:],
    )
    with pytest.raises(ValueError, match="barrier generation is invalid"):
        _validate_future_platform_barrier_capture_seqs(
            unknown_status,
            subscription_capture_seq=145,
            status_capture_seq=146,
        )


def test_failed_reconnect_attempt_with_facts_gets_its_own_boundary() -> None:
    session = _OutcomeLiveSession()
    session.record_reconnect("first", received_at_ms=1, elapsed_ms=0)
    attempt_start = len(session.events)
    session.record_heartbeat({}, received_at_ms=2, elapsed_ms=0)

    recorded = _record_connection_attempt_failure(
        session,
        attempt_start_event_count=attempt_start,
        active_connection=False,
        error=TimeoutError(),
    )
    empty_attempt_start = len(session.events)
    not_recorded = _record_connection_attempt_failure(
        session,
        attempt_start_event_count=empty_attempt_start,
        active_connection=False,
        error=TimeoutError(),
    )

    assert recorded is True
    assert not_recorded is False
    assert [event.event_kind for event in session.events] == [
        EventKind.RECONNECT,
        EventKind.HEARTBEAT,
        EventKind.RECONNECT,
    ]


@pytest.mark.parametrize(
    ("responses", "message"),
    (
        (
            [{"jsonrpc": "2.0", "id": 10, "result": []}],
            "subscription refresh was not accepted",
        ),
        (
            [
                {"jsonrpc": "2.0", "id": 10, "result": ["platform_state"]},
                {"jsonrpc": "2.0", "id": 11, "error": {"code": 10_000}},
            ],
            "Deribit WebSocket error",
        ),
    ),
)
def test_outcome_platform_probe_fails_closed_on_ack_or_status_failure(
    responses: list[dict[str, object]],
    message: str,
) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.responses = list(responses)

        def send(self, value: str) -> None:
            assert isinstance(json.loads(value), dict)

        def recv(self, *, timeout: float) -> str:
            assert timeout > 0
            return json.dumps(self.responses.pop(0))

    session = _OutcomeLiveSession()
    session.record_heartbeat({}, received_at_ms=1, elapsed_ms=0)
    with pytest.raises(RuntimeError, match=message):
        _refresh_outcome_platform_barrier(
            cast(Connection, FakeConnection()),
            session,
            cutoff_capture_seq=1,
            request_id=10,
            test_request_id=1_000,
        )
    assert not any(event.event_kind is EventKind.PLATFORM_STATE for event in session.events)


def test_seal_reconstructs_exact_bytes_and_rejects_suffix_tamper(tmp_path: Path) -> None:
    events = build_synthetic_outcome_events()
    full = tmp_path / "full"
    write_capture(full, events, complete=True)
    seal = seal_capture(full, tmp_path / "facts")

    reconstructed, manifest, replayed, prefix_manifest, prefix = read_sealed_capture(
        tmp_path / "facts"
    )
    assert reconstructed == seal
    assert replayed == events
    assert manifest.content_sha256 == seal.combined_capture_sha256
    assert prefix_manifest.record_count == seal.cutoff.capture_seq == len(prefix)

    suffix = tmp_path / "facts/future-suffix.jsonl"
    suffix.write_bytes(suffix.read_bytes() + b" ")
    with pytest.raises(ValueError, match="suffix digest changed"):
        read_sealed_capture(tmp_path / "facts")


def test_synthetic_run_and_fresh_process_replay_are_exact(tmp_path: Path) -> None:
    run = tmp_path / "synthetic"
    result = run_synthetic_outcome(run)

    assert result["decision_cutoff_capture_seq"] == 144
    assert result["decision_action"] == "RESEARCH_CANDIDATE"
    assert result["admission_status"] == "ADMITTED"
    assert result["entry_count"] == result["outcome_count"] == 1
    assert result["outcome_status"] == "CLOSED"
    assert result["counterfactual_point_count"] == 1
    assert result["decision_runtime_source_digest"] == (
        "eed711f1c924c73a0a61b562da5154873b40713f5b5e44c482882eecf7aee29c"
    )
    assert not (run / "_full-capture").exists()
    outcome = _object(run / "outcome.json")
    sources = outcome["outcome_source_capture_seqs"]
    assert isinstance(sources, list)
    assert all(isinstance(item, int) and item > 144 for item in sources)

    replay = tmp_path / "fresh-replay"
    completed = subprocess.run(
        (
            sys.executable,
            "-c",
            "from radar_runtime.outcome_cli import main; raise SystemExit(main())",
            "replay",
            str(run),
            "--output",
            str(replay),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    replayed: object = json.loads(completed.stdout)
    assert isinstance(replayed, dict)
    assert replayed["replay_verified"] is True
    assert replayed["decision_drift_count"] == 0
    assert replayed["entry_drift_count"] == 0
    assert replayed["outcome_drift_count"] == 0
    assert replayed["strict_future_violation_count"] == 0
    assert replayed["computation_reconstructed"] is True
    assert replayed["collector_witness_verified"] is False
    assert replayed["external_source_attested"] is False


def test_transient_executable_option_tick_is_the_first_causal_exit(tmp_path: Path) -> None:
    base = build_synthetic_outcome_events()
    prefix = base[:146]
    short_tick, long_tick, reference_tick, counterfactual = base[146:]
    reference_first = replace(reference_tick, capture_seq=147)
    short_after_reference = replace(short_tick, capture_seq=148)
    long_after_reference = replace(long_tick, capture_seq=149)
    deteriorated_payload = _payload(short_tick)
    deteriorated_at_ms = short_tick.collector_received_at_ms + 1
    deteriorated_payload["timestamp"] = deteriorated_at_ms
    deteriorated_payload["best_ask_price"] = "800"
    deteriorated = replace(
        short_tick,
        capture_seq=150,
        collector_received_at_ms=deteriorated_at_ms,
        collector_elapsed_ms=short_tick.collector_elapsed_ms + 1,
        exchange_timestamp_ms=deteriorated_at_ms,
        raw_payload=json.dumps(
            deteriorated_payload,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    later_counterfactual = replace(counterfactual, capture_seq=151)
    events = (
        *prefix,
        reference_first,
        short_after_reference,
        long_after_reference,
        deteriorated,
        later_counterfactual,
    )

    run = tmp_path / "transient"
    result = _write_composed_run(
        run,
        events,
        provenance="synthetic",
        duration_seconds=7_200,
    )
    outcome = _object(run / "outcome.json")
    observed = outcome["observed_outcome"]
    assert isinstance(observed, dict)

    assert result["outcome_status"] == "CLOSED"
    assert observed["exit_capture_seq"] == 149
    assert observed["exit_reason"] == "PROFIT_TARGET"
    assert result["counterfactual_point_count"] == 2


def test_runtime_keeps_horizon_armed_until_later_executable_quote(tmp_path: Path) -> None:
    base = build_synthetic_outcome_events()
    cutoff = decision_cutoff(base)
    projection = project_events(base[: cutoff.capture_seq])
    horizon_seconds = projection.decision.horizon_seconds
    assert horizon_seconds is not None
    prefix_and_barrier = base[:146]
    short_tick, long_tick, reference_tick, post_exit = base[146:]
    horizon_elapsed_ms = cutoff.observed_elapsed_ms + horizon_seconds * 1_000
    horizon_wall_ms = base[cutoff.capture_seq - 1].collector_received_at_ms + (
        horizon_seconds * 1_000
    )
    heartbeat = replace(
        post_exit,
        capture_seq=147,
        collector_received_at_ms=horizon_wall_ms,
        collector_elapsed_ms=horizon_elapsed_ms,
        exchange_timestamp_ms=None,
        event_kind=EventKind.HEARTBEAT,
        channel="heartbeat",
        instrument_name=None,
        raw_payload="{}",
    )

    def moved_tick(
        event: CanonicalEvent,
        *,
        capture_seq: int,
        wall_ms: int,
        payload_updates: dict[str, object],
    ) -> CanonicalEvent:
        payload = _payload(event)
        payload.update(payload_updates)
        payload["timestamp"] = wall_ms
        return replace(
            event,
            capture_seq=capture_seq,
            collector_received_at_ms=wall_ms,
            collector_elapsed_ms=horizon_elapsed_ms + 60_000,
            exchange_timestamp_ms=wall_ms,
            raw_payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )

    close_wall_ms = horizon_wall_ms + 60_000
    moved_short = moved_tick(
        short_tick,
        capture_seq=148,
        wall_ms=close_wall_ms,
        payload_updates={"best_ask_price": "715"},
    )
    moved_long = moved_tick(
        long_tick,
        capture_seq=149,
        wall_ms=close_wall_ms,
        payload_updates={"best_bid_price": "100"},
    )
    moved_reference = moved_tick(
        reference_tick,
        capture_seq=150,
        wall_ms=close_wall_ms,
        payload_updates={"index_price": "100010", "last_price": "100010"},
    )
    post_exit_wall_ms = horizon_wall_ms + 120_000
    moved_post_exit = moved_tick(
        post_exit,
        capture_seq=151,
        wall_ms=post_exit_wall_ms,
        payload_updates={"index_price": "97000", "last_price": "97000"},
    )
    moved_post_exit = replace(
        moved_post_exit,
        collector_elapsed_ms=horizon_elapsed_ms + 120_000,
    )
    result = _write_composed_run(
        tmp_path / "horizon-recovery",
        (
            *prefix_and_barrier,
            heartbeat,
            moved_short,
            moved_long,
            moved_reference,
            moved_post_exit,
        ),
        provenance="synthetic",
        duration_seconds=(horizon_elapsed_ms + 120_000) // 1_000,
    )
    outcome = _object(tmp_path / "horizon-recovery/outcome.json")
    observed = outcome["observed_outcome"]
    assert isinstance(observed, dict)

    assert result["outcome_status"] == "CLOSED"
    assert result["outcome_exit_reason"] == "HORIZON"
    assert observed["exit_capture_seq"] == 150
    assert observed["evaluation_capture_seq"] == 150
    assert result["counterfactual_point_count"] == 1


def test_runtime_final_fact_reassesses_stale_horizon_evidence(tmp_path: Path) -> None:
    base = build_synthetic_outcome_events()
    cutoff = decision_cutoff(base)
    projection = project_events(base[: cutoff.capture_seq])
    horizon_seconds = projection.decision.horizon_seconds
    assert horizon_seconds is not None
    horizon_elapsed_ms = cutoff.observed_elapsed_ms + horizon_seconds * 1_000
    horizon_wall_ms = base[cutoff.capture_seq - 1].collector_received_at_ms + (
        horizon_seconds * 1_000
    )
    prefix_and_barrier = base[:146]
    short_tick, long_tick, reference_tick, post_exit = base[146:]
    short_payload = _payload(short_tick)
    short_payload["best_ask_amount"] = "0.01"
    short_payload["timestamp"] = horizon_wall_ms
    long_payload = _payload(long_tick)
    long_payload["best_bid_amount"] = "0.01"
    long_payload["timestamp"] = horizon_wall_ms
    reference_payload = _payload(reference_tick)
    reference_payload["timestamp"] = horizon_wall_ms
    insufficient_short = replace(
        short_tick,
        collector_received_at_ms=horizon_wall_ms,
        collector_elapsed_ms=horizon_elapsed_ms,
        exchange_timestamp_ms=horizon_wall_ms,
        raw_payload=json.dumps(short_payload, sort_keys=True, separators=(",", ":")),
    )
    insufficient_long = replace(
        long_tick,
        collector_received_at_ms=horizon_wall_ms,
        collector_elapsed_ms=horizon_elapsed_ms,
        exchange_timestamp_ms=horizon_wall_ms,
        raw_payload=json.dumps(long_payload, sort_keys=True, separators=(",", ":")),
    )
    horizon_reference = replace(
        reference_tick,
        collector_received_at_ms=horizon_wall_ms,
        collector_elapsed_ms=horizon_elapsed_ms,
        exchange_timestamp_ms=horizon_wall_ms,
        raw_payload=json.dumps(reference_payload, sort_keys=True, separators=(",", ":")),
    )
    final_heartbeat = replace(
        post_exit,
        event_kind=EventKind.HEARTBEAT,
        channel="heartbeat",
        instrument_name=None,
        exchange_timestamp_ms=None,
        collector_received_at_ms=horizon_wall_ms + 10_000,
        collector_elapsed_ms=horizon_elapsed_ms + 10_000,
        raw_payload="{}",
    )
    result = _write_composed_run(
        tmp_path / "final-stale",
        (
            *prefix_and_barrier,
            insufficient_short,
            insufficient_long,
            horizon_reference,
            final_heartbeat,
        ),
        provenance="synthetic",
        duration_seconds=horizon_seconds + 10,
    )
    outcome = _object(tmp_path / "final-stale/outcome.json")
    observed = outcome["observed_outcome"]
    assert isinstance(observed, dict)

    assert result["outcome_status"] == "UNKNOWN"
    assert observed["evaluation_capture_seq"] == 150
    assert observed["exit_capture_seq"] is None
    unknown_reasons = result["unknown_reasons"]
    assert isinstance(unknown_reasons, list)
    assert "FUTURE_REFERENCE_UNKNOWN" in unknown_reasons


def test_replay_rejects_runtime_source_and_receipt_tamper(tmp_path: Path) -> None:
    original = tmp_path / "original"
    run_synthetic_outcome(original)

    source_tamper = tmp_path / "source-tamper"
    shutil.copytree(original, source_tamper)
    _rewrite_result(
        source_tamper / "result.json",
        {"outcome_runtime_source_digest": "0" * 64},
    )
    with pytest.raises(ValueError, match="runtime source identity mismatch"):
        reconstruct_outcome(source_tamper)

    receipt_tamper = tmp_path / "receipt-tamper"
    shutil.copytree(original, receipt_tamper)
    entry = _object(receipt_tamper / "shadow-entry.json")
    entry["frame_digest"] = "0" * 64
    (receipt_tamper / "shadow-entry.json").write_text(
        json.dumps(entry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"entry\.frame_digest"):
        reconstruct_outcome(receipt_tamper)

    decision_tamper = tmp_path / "decision-tamper"
    shutil.copytree(original, decision_tamper)
    decision = _object(decision_tamper / "decision.json")
    decision["frame_digest"] = "0" * 64
    (decision_tamper / "decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"decision\.frame_digest"):
        reconstruct_outcome(decision_tamper)

    outcome_tamper = tmp_path / "outcome-tamper"
    shutil.copytree(original, outcome_tamper)
    outcome = _object(outcome_tamper / "outcome.json")
    outcome["receipt_digest"] = "0" * 64
    (outcome_tamper / "outcome.json").write_text(
        json.dumps(outcome, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"outcome\.receipt_digest"):
        reconstruct_outcome(outcome_tamper)

    metadata_tamper = tmp_path / "metadata-tamper"
    shutil.copytree(original, metadata_tamper)
    _rewrite_result(
        metadata_tamper / "result.json",
        {"evidence_class": "UNBOUND", "duration_seconds": 1},
    )
    with pytest.raises(ValueError, match="replay metadata changed"):
        reconstruct_outcome(metadata_tamper)


def test_complete_zero_and_incomplete_unknown_emit_no_false_receipts(tmp_path: Path) -> None:
    base = build_synthetic_outcome_events()
    no_entry = _write_composed_run(
        tmp_path / "no-entry",
        _without_candidate(base),
        provenance="production_public",
        duration_seconds=3_665,
    )
    assert no_entry["decision_frame_complete"] is True
    assert no_entry["decision_action"] == "ABSTAIN"
    assert no_entry["admission_status"] == "NO_ENTRY"
    assert no_entry["entry_count"] == no_entry["outcome_count"] == 0
    assert no_entry["entry_receipt_digest"] is None
    assert no_entry["outcome_receipt_digest"] is None
    assert not (tmp_path / "no-entry/shadow-entry.json").exists()
    assert not (tmp_path / "no-entry/outcome.json").exists()

    unknown = _write_composed_run(
        tmp_path / "unknown",
        _without_schedule(base),
        provenance="production_public",
        duration_seconds=3_665,
    )
    assert unknown["decision_frame_complete"] is False
    assert unknown["admission_status"] == "UNKNOWN"
    assert unknown["entry_count"] == unknown["outcome_count"] == 0
    assert unknown["unknown_reasons"]
    assert not (tmp_path / "unknown/shadow-entry.json").exists()
    assert not (tmp_path / "unknown/outcome.json").exists()


def test_public_collector_witness_rejects_invalid_timestamps_and_numeric_types(
    tmp_path: Path,
) -> None:
    original = tmp_path / "public"
    _write_composed_run(
        original,
        _public_zero_events(),
        provenance="production_public",
        duration_seconds=3_665,
    )
    source_invocation = _object(original / "collector-invocation.json")
    invalid_values: tuple[tuple[str, object], ...] = (
        ("invocation_started_at", "not-a-time"),
        ("requested_duration_seconds", 3_665.0),
        ("records", float(cast(int, source_invocation["records"]))),
        (
            "future_platform_subscription_capture_seq",
            float(cast(int, source_invocation["future_platform_subscription_capture_seq"])),
        ),
        ("external_source_attested", True),
    )
    for field, invalid_value in invalid_values:
        tampered = tmp_path / f"invalid-{field}"
        shutil.copytree(original, tampered)
        invocation = _object(tampered / "collector-invocation.json")
        invocation[field] = invalid_value
        invocation.pop("invocation_digest")
        invocation["invocation_digest"] = canonical_digest(invocation)
        (tampered / "collector-invocation.json").write_text(
            json.dumps(invocation, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _rewrite_result(
            tampered / "result.json",
            {"collector_invocation_digest": invocation["invocation_digest"]},
        )

        with pytest.raises(ValueError, match="witness is invalid"):
            reconstruct_outcome(tampered)


def test_bundle_reconstructs_both_cases_and_rejects_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic = tmp_path / "synthetic"
    synthetic_replay = tmp_path / "synthetic-replay"
    run_synthetic_outcome(synthetic)
    replay_outcome(synthetic, synthetic_replay)

    public = tmp_path / "public"
    public_replay = tmp_path / "public-replay"
    public_result = _write_composed_run(
        public,
        _public_zero_events(),
        provenance="production_public",
        duration_seconds=3_665,
    )
    assert public_result["admission_status"] == "NO_ENTRY"
    public_event_span = public_result["collector_elapsed_span_ms"]
    assert isinstance(public_event_span, int) and not isinstance(public_event_span, bool)
    assert public_event_span < 3_665_000
    public_replayed = replay_outcome(public, public_replay)
    assert public_replayed["collector_witness_verified"] is True
    assert public_replayed["external_source_attested"] is False
    unbound_public = tmp_path / "unbound-public"
    shutil.copytree(public, unbound_public)
    for name in (
        "collector-live.json",
        "collector-decision.json",
        "collector-inspect.json",
        "collector-invocation.json",
    ):
        (unbound_public / name).unlink()
    with pytest.raises(ValueError, match="missing bounded collector artifacts"):
        reconstruct_outcome(unbound_public)
    with pytest.raises(ValueError, match="missing bounded collector artifacts"):
        create_outcome_evidence_bundle(
            synthetic_run=synthetic,
            synthetic_replay=synthetic_replay,
            public_run=unbound_public,
            public_replay=public_replay,
            output=tmp_path / "unbound-bundle",
        )

    collector_tamper = tmp_path / "collector-tamper"
    shutil.copytree(public, collector_tamper)
    decision = _object(collector_tamper / "collector-decision.json")
    evaluation = decision["evaluation"]
    assert isinstance(evaluation, dict)
    decision_summary = evaluation["decision"]
    assert isinstance(decision_summary, dict)
    decision_summary["reason"] = "TAMPERED_BUT_REHASHED"
    decision.pop("receipt_digest")
    tampered_digest = canonical_digest(decision)
    decision["receipt_digest"] = tampered_digest
    live = _object(collector_tamper / "collector-live.json")
    live["decision_receipt_digest"] = tampered_digest
    inspected = _object(collector_tamper / "collector-inspect.json")
    inspected["decision_receipt_digest"] = tampered_digest
    for name, payload in (
        ("collector-decision.json", decision),
        ("collector-live.json", live),
        ("collector-inspect.json", inspected),
    ):
        (collector_tamper / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    invocation = _object(collector_tamper / "collector-invocation.json")
    invocation["collector_live_sha256"] = hashlib.sha256(
        (collector_tamper / "collector-live.json").read_bytes()
    ).hexdigest()
    invocation["collector_decision_sha256"] = hashlib.sha256(
        (collector_tamper / "collector-decision.json").read_bytes()
    ).hexdigest()
    invocation["collector_inspect_sha256"] = hashlib.sha256(
        (collector_tamper / "collector-inspect.json").read_bytes()
    ).hexdigest()
    invocation.pop("invocation_digest")
    invocation["invocation_digest"] = canonical_digest(invocation)
    (collector_tamper / "collector-invocation.json").write_text(
        json.dumps(invocation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rewrite_result(
        collector_tamper / "result.json",
        {"collector_invocation_digest": invocation["invocation_digest"]},
    )
    with pytest.raises(ValueError, match="Decision receipt is not reconstructed"):
        reconstruct_outcome(collector_tamper)

    invalid_git_replay = tmp_path / "invalid-git-replay"
    shutil.copytree(public_replay, invalid_git_replay)
    invalid_git_payload = _object(invalid_git_replay / "replay.json")
    invalid_git_payload["replay_git_commit_sha"] = "not-a-commit"
    (invalid_git_replay / "replay.json").write_text(
        json.dumps(invalid_git_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="verifier Git identity is invalid"):
        create_outcome_evidence_bundle(
            synthetic_run=synthetic,
            synthetic_replay=synthetic_replay,
            public_run=public,
            public_replay=invalid_git_replay,
            output=tmp_path / "invalid-git-bundle",
        )

    for label, invalid_count in (("one", 1), ("bool", False), ("float", 0.0)):
        result_drift_replay = tmp_path / f"result-drift-replay-{label}"
        shutil.copytree(public_replay, result_drift_replay)
        drifted_replay = _object(result_drift_replay / "replay.json")
        drifted_replay["result_drift_count"] = invalid_count
        (result_drift_replay / "replay.json").write_text(
            json.dumps(drifted_replay, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="nonzero result_drift_count"):
            create_outcome_evidence_bundle(
                synthetic_run=synthetic,
                synthetic_replay=synthetic_replay,
                public_run=public,
                public_replay=result_drift_replay,
                output=tmp_path / f"result-drift-bundle-{label}",
            )

    bundle = tmp_path / "bundle"
    created = create_outcome_evidence_bundle(
        synthetic_run=synthetic,
        synthetic_replay=synthetic_replay,
        public_run=public,
        public_replay=public_replay,
        output=bundle,
    )
    archive = Path(str(bundle.with_suffix(".tar.gz")))
    assert created["bundle_verified"] is True
    assert verify_outcome_evidence_bundle(bundle, archive=archive)["bundle_verified"] is True
    active_identity = outcome_runtime_source_identity(require_clean=False)
    active_decision_identity = runtime_source_identity(require_clean=False)
    monkeypatch.setattr(
        "radar_runtime.outcome_runtime.outcome_runtime_source_identity",
        lambda *, require_clean: replace(
            active_identity,
            git_commit_sha="f" * 40,
            dirty_paths=(" M same-content-mode-only",),
        ),
    )
    monkeypatch.setattr(
        "radar_runtime.outcome_runtime.runtime_source_identity",
        lambda *, require_clean: replace(
            active_decision_identity,
            git_commit_sha="f" * 40,
            dirty_paths=(" M same-content-mode-only",),
        ),
    )
    assert verify_outcome_evidence_bundle(bundle, archive=archive)["bundle_verified"] is True

    duplicate_archive = tmp_path / "duplicate.tar.gz"
    members: list[tuple[str, bytes]] = []
    with tarfile.open(archive, mode="r:gz") as source:
        for member in source.getmembers():
            handle = source.extractfile(member)
            assert handle is not None
            members.append((member.name, handle.read()))
    with tarfile.open(duplicate_archive, mode="w:gz") as target:
        for name, data in (*members, members[0]):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            target.addfile(info, io.BytesIO(data))
    with pytest.raises(ValueError, match="unsafe or duplicate"):
        verify_outcome_evidence_bundle(bundle, archive=duplicate_archive)
    report = (bundle / "ACCEPTANCE.zh-CN.md").read_text(encoding="utf-8")
    assert "environment / capture format / duration" in report
    assert "Decision / Entry / Outcome / Result" in report
    assert "decision reason=" in report
    assert "exit reason=`PROFIT_TARGET`" in report
    assert "external_source_attested=`False`" in report
    assert "不证明真实 fill" in report

    report_tamper = tmp_path / "report-tamper"
    shutil.copytree(bundle, report_tamper)
    tampered_report = report_tamper / "ACCEPTANCE.zh-CN.md"
    tampered_report.write_text("# 已证明真实 fill 和盈利\n", encoding="utf-8")
    manifest = _object(report_tamper / "BUNDLE_MANIFEST.json")
    artifacts = manifest["artifacts"]
    assert isinstance(artifacts, list)
    report_artifact = next(
        item
        for item in artifacts
        if isinstance(item, dict) and item.get("path") == "ACCEPTANCE.zh-CN.md"
    )
    report_artifact["bytes"] = tampered_report.stat().st_size
    report_artifact["sha256"] = hashlib.sha256(tampered_report.read_bytes()).hexdigest()
    (report_tamper / "BUNDLE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksum_paths = tuple(
        sorted(
            item.relative_to(report_tamper).as_posix()
            for item in report_tamper.rglob("*")
            if item.is_file() and item.name != "SHA256SUMS"
        )
    )
    (report_tamper / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256((report_tamper / relative).read_bytes()).hexdigest()}  {relative}\n"
            for relative in checksum_paths
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="acceptance report changed"):
        verify_outcome_evidence_bundle(report_tamper)

    result = bundle / "production-public/run/result.json"
    result.write_bytes(result.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_outcome_evidence_bundle(bundle)


def test_public_capture_rejects_non_authorized_duration_before_writing(tmp_path: Path) -> None:
    output = tmp_path / "public"
    with pytest.raises(ValueError, match="exactly 3665"):
        run_public_outcome_capture(output, 60)
    assert not output.exists()
