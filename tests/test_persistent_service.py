from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import FrozenInstanceError, dataclass, field
from pathlib import Path
from typing import NoReturn, cast

import pytest
import radar_runtime.service as service_module
from conftest import PolicyFactory
from radar_runtime.deribit_public import InboundEnvelope, SendControlEvent
from radar_runtime.runtime import (
    CausalCause,
    CausalCommit,
    FactBoundary,
    FailureScope,
    PublicClient,
    RadarReducer,
    RpcState,
    ShadowRpcIntent,
    ShadowRuntimeIntegrityError,
)
from radar_runtime.service import (
    PersistentServiceComposition,
    PersistentServiceStartup,
    PersistentServiceStartupError,
    PersistentStopEvent,
    SingleInstanceLease,
    build_persistent_service_composition,
    generate_runtime_identity,
    prepare_persistent_service_startup,
    run_persistent_service_composition,
)
from radar_runtime.service_evidence import (
    PERSISTENT_SERVICE_CONTRACT_DIGEST,
    DataState,
    PersistentServiceBindings,
    PersistentServiceEvidenceError,
    ServicePhase,
    ServiceStatus,
    read_complete_persistent_service_evidence,
    read_current_persistent_service_evidence,
)
from short_vol_radar.evidence import EvidenceWriter
from short_vol_radar.policy import load_policy_bytes

ROOT = Path(__file__).resolve().parents[1]
CODE = "a" * 40


def _startup(tmp_path: Path, *, nonce: str = "nonce-a") -> PersistentServiceStartup:
    return prepare_persistent_service_startup(
        state_root=(tmp_path / "state").resolve(),
        process_cwd=ROOT,
        workbench_host="127.0.0.1",
        workbench_port=0,
        code_identity=CODE,
        startup_monotonic_ms=100,
        process_id=123,
        nonce_factory=lambda: nonce,
    )


def _run_pre_latched(
    tmp_path: Path,
) -> tuple[PersistentServiceStartup, PersistentServiceComposition, Path]:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    event = PersistentStopEvent()
    assert event.request(terminal_monotonic_ms=1_000, reason="TEST_STOP") is True
    client_calls = 0

    def forbidden_client(**_: object) -> NoReturn:
        nonlocal client_calls
        client_calls += 1
        raise AssertionError("pre-latched stop must not construct a market client")

    summary = asyncio.run(
        run_persistent_service_composition(
            composition,
            stop_event=event,
            client_factory=forbidden_client,
            monotonic_ms=lambda: 1_000,
            signal_registrar=lambda _signal, _callback: None,
            start_workbench=False,
        )
    )
    assert client_calls == 0
    return startup, composition, summary


def test_service_contract_digest_binds_exact_repository_bytes() -> None:
    contract = ROOT / "docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md"
    assert PERSISTENT_SERVICE_CONTRACT_DIGEST == (
        f"sha256:{hashlib.sha256(contract.read_bytes()).hexdigest()}"
    )


def test_single_instance_lease_rejects_duplicate_and_releases(tmp_path: Path) -> None:
    state_root = (tmp_path / "state").resolve()
    first = SingleInstanceLease(state_root)
    second = SingleInstanceLease(state_root)

    first.acquire()
    assert first.acquired is True
    with pytest.raises(PersistentServiceStartupError, match="another persistent service"):
        second.acquire()

    first.release()
    second.acquire()
    assert second.acquired is True
    second.release()


def test_runtime_identity_changes_each_start_and_is_canonical() -> None:
    first = generate_runtime_identity(
        code_identity=CODE,
        startup_monotonic_ms=100,
        process_id=123,
        nonce="first",
    )
    second = generate_runtime_identity(
        code_identity=CODE,
        startup_monotonic_ms=100,
        process_id=123,
        nonce="second",
    )

    assert first.startswith("sha256:") and len(first) == 71
    assert second.startswith("sha256:") and len(second) == 71
    assert first != second
    with pytest.raises(ValueError):
        generate_runtime_identity(
            code_identity="not-a-commit",
            startup_monotonic_ms=100,
            process_id=123,
            nonce="invalid",
        )


def test_startup_freezes_one_shared_policy_chain(tmp_path: Path) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    try:
        assert composition.owner.policies is startup.policies
        assert composition.runtime.policy is startup.policies.radar
        assert composition.adapter.owner is composition.owner
        with pytest.raises(FrozenInstanceError):
            startup.policies.radar.identity = "sha256:" + "f" * 64  # type: ignore[misc]
    finally:
        composition.workbench.close()


def test_stop_event_preserves_first_boundary_and_returns_transition() -> None:
    event = PersistentStopEvent()

    assert event.request(terminal_monotonic_ms=100, reason="FIRST") is True
    assert event.request(terminal_monotonic_ms=200, reason="SECOND") is False
    assert event.terminal_monotonic_ms == 100
    assert event.reason == "FIRST"
    assert event.is_set()


def test_service_writer_rejects_backward_lifecycle_time(tmp_path: Path) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    try:
        with pytest.raises(PersistentServiceEvidenceError, match="moved backward"):
            composition.service_writer.write_event(
                ServiceStatus(
                    ServicePhase.CONNECTING,
                    DataState.UNKNOWN,
                    True,
                    False,
                    False,
                    "BACKWARD",
                    99,
                )
            )
    finally:
        composition.workbench.close()


def test_pre_latched_stop_opens_no_client_and_writes_exact_terminal(
    tmp_path: Path,
) -> None:
    startup, composition, summary = _run_pre_latched(tmp_path)
    try:
        assert summary == startup.radar_directory / "radar-run-summary.json"
        assert summary.is_file()
        evidence = read_complete_persistent_service_evidence(
            startup.run_directory,
            bindings=startup.service_bindings,
            downstream_bindings=startup.downstream_bindings,
        )
        assert evidence.terminal is not None
        assert evidence.events[0]["recorded_monotonic_ms"] == 100
        assert evidence.terminal["terminal_disposition"] == "CLEAN_STOP"
        assert evidence.terminal["radar_evidence_status"] == "COMPLETE_CLEAN_STOP"
        assert evidence.terminal["forward_cohort_summary_emitted"] is False
        assert evidence.terminal["radar_object_count"] == 1
        assert evidence.terminal["downstream_object_count"] == 0
        assert str(evidence.terminal["radar_inventory_identity"]).startswith("sha256:")
        assert str(evidence.terminal["lifecycle_inventory_identity"]).startswith("sha256:")
        underwriting_rates = cast(Mapping[str, object], evidence.terminal["underwriting_rates"])
        cohort_rates = cast(Mapping[str, object], evidence.terminal["cohort_rates"])
        assert all(value is None for value in underwriting_rates.values())
        assert all(value is None for value in cohort_rates.values())
        downstream_files = tuple(startup.downstream_directory.rglob("*.json"))
        assert not any("SUMMARY" in path.as_posix() for path in downstream_files)
        before = sorted(startup.service_directory.rglob("*.json"))
        composition.adapter.finalize_terminal()
        after = sorted(startup.service_directory.rglob("*.json"))
        assert after == before
    finally:
        composition.workbench.close()


def test_process_failure_terminal_is_complete_without_radar_summary(tmp_path: Path) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    try:
        composition.runtime.finalize_shadow_failure(1_000)
        composition.runtime.finalize_shadow_failure(1_001)
        evidence = read_complete_persistent_service_evidence(
            startup.run_directory,
            bindings=startup.service_bindings,
            downstream_bindings=startup.downstream_bindings,
        )
        assert evidence.terminal is not None
        assert evidence.terminal["terminal_disposition"] == "PROCESS_FAILURE"
        assert evidence.terminal["radar_evidence_status"] == "INCOMPLETE_PROCESS_FAILURE"
        assert evidence.terminal["radar_object_count"] == 0
        assert not (startup.radar_directory / "radar-run-summary.json").exists()
    finally:
        composition.workbench.close()


def test_process_failure_reader_rejects_corrupt_partial_radar_inventory(
    tmp_path: Path,
) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    try:
        composition.runtime.finalize_shadow_failure(1_000)
        corrupt = startup.radar_directory / "short-vol-anomaly-corrupt.json"
        corrupt.write_text('{"object_kind":"SHORT_VOL_ANOMALY_EVENT"}\n')

        with pytest.raises(PersistentServiceEvidenceError):
            read_complete_persistent_service_evidence(
                startup.run_directory,
                bindings=startup.service_bindings,
                downstream_bindings=startup.downstream_bindings,
            )
    finally:
        composition.workbench.close()


def test_process_failure_writer_rejects_corrupt_partial_radar_inventory(
    tmp_path: Path,
) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    try:
        corrupt = startup.radar_directory / "unexpected.json"
        corrupt.write_text('{"object_kind":"UNKNOWN"}\n')

        with pytest.raises(ShadowRuntimeIntegrityError, match="terminal evidence finalize"):
            composition.runtime.finalize_shadow_failure(1_000)
        assert not (startup.service_directory / "terminal.json").exists()
        terminal_event_count = len(composition.service_writer.events)
        with pytest.raises(PersistentServiceEvidenceError, match="requires terminal"):
            read_complete_persistent_service_evidence(
                startup.run_directory,
                bindings=startup.service_bindings,
                downstream_bindings=startup.downstream_bindings,
            )

        corrupt.unlink()
        composition.adapter.finalize_terminal()
        assert len(composition.service_writer.events) == terminal_event_count
        repaired = read_complete_persistent_service_evidence(
            startup.run_directory,
            bindings=startup.service_bindings,
            downstream_bindings=startup.downstream_bindings,
        )
        assert repaired.terminal is not None
    finally:
        composition.workbench.close()


def test_service_reader_fails_closed_on_missing_corrupt_or_mixed_evidence(
    tmp_path: Path,
) -> None:
    startup, composition, _summary = _run_pre_latched(tmp_path)
    try:
        terminal_path = startup.service_directory / "terminal.json"
        exact = terminal_path.read_bytes()
        terminal_path.unlink()
        current = read_current_persistent_service_evidence(
            startup.run_directory,
            bindings=startup.service_bindings,
            downstream_bindings=startup.downstream_bindings,
        )
        assert current.terminal is None
        with pytest.raises(PersistentServiceEvidenceError, match="requires terminal"):
            read_complete_persistent_service_evidence(
                startup.run_directory,
                bindings=startup.service_bindings,
                downstream_bindings=startup.downstream_bindings,
            )
        terminal_path.write_bytes(exact.replace(b'"CLEAN_STOP"', b'"BROKEN_STOP"', 1))
        with pytest.raises(PersistentServiceEvidenceError):
            read_current_persistent_service_evidence(
                startup.run_directory,
                bindings=startup.service_bindings,
                downstream_bindings=startup.downstream_bindings,
            )
        terminal_path.write_bytes(exact)
        mixed = PersistentServiceBindings(
            code_identity=CODE,
            runtime_identity="sha256:" + "f" * 64,
            radar_policy_identity=startup.service_bindings.radar_policy_identity,
            underwriting_policy_identity=(startup.service_bindings.underwriting_policy_identity),
            position_policy_identity=startup.service_bindings.position_policy_identity,
        )
        with pytest.raises(PersistentServiceEvidenceError, match="binding mismatch"):
            read_current_persistent_service_evidence(
                startup.run_directory,
                bindings=mixed,
                downstream_bindings=startup.downstream_bindings,
            )
    finally:
        composition.workbench.close()


class _WaitingClient:
    session_epoch = 1
    queue_high_water_frames = 0
    overflow_count = 0
    received_frame_count = 0
    enqueued_envelope_count = 0

    async def send_request(self, **_kwargs: object) -> None:
        return None

    async def next_envelope(self, timeout_seconds: float | None = None) -> InboundEnvelope:
        del timeout_seconds
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    def enqueue_send_control(self, _event: SendControlEvent) -> None:
        return None

    def drain_envelopes(self) -> tuple[InboundEnvelope, ...]:
        return ()

    async def stop_intake(self) -> None:
        return None


class _WaitingClientContext(AbstractAsyncContextManager[_WaitingClient]):
    def __init__(self, client: _WaitingClient) -> None:
        self.client = client

    async def __aenter__(self) -> _WaitingClient:
        return self.client

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool | None:
        del exc_type, exc_value, traceback
        return None


def test_active_stop_publishes_stopping_before_exact_terminal(tmp_path: Path) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    event = PersistentStopEvent()
    client = _WaitingClient()

    def client_factory(
        *,
        session_epoch: int,
        rpc_deadline_ms: int,
    ) -> AbstractAsyncContextManager[PublicClient]:
        assert session_epoch == 1
        assert rpc_deadline_ms > 0
        return _WaitingClientContext(client)

    async def scenario() -> Path:
        task = asyncio.create_task(
            run_persistent_service_composition(
                composition,
                stop_event=event,
                client_factory=client_factory,
                signal_registrar=lambda _signal, _callback: None,
                start_workbench=False,
            )
        )
        for _ in range(100):
            if composition.publisher.status.phase is ServicePhase.RUNNING:
                break
            await asyncio.sleep(0)
        assert composition.publisher.status.phase is ServicePhase.RUNNING
        assert event.request(
            terminal_monotonic_ms=service_module._monotonic_ms(),
            reason="TEST_ACTIVE_STOP",
        )
        return await task

    try:
        summary = asyncio.run(scenario())
        assert summary.is_file()
        evidence = read_complete_persistent_service_evidence(
            startup.run_directory,
            bindings=startup.service_bindings,
            downstream_bindings=startup.downstream_bindings,
        )
        phases = [str(value["service_phase"]) for value in evidence.events]
        assert phases[-2:] == ["STOPPING", "STOPPED"]
        assert evidence.events[-2]["reason"] == "TEST_ACTIVE_STOP"
    finally:
        composition.workbench.close()


def test_post_stop_drain_snapshot_cannot_move_lifecycle_time_backward(tmp_path: Path) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    try:
        reducer = composition.runtime.reducer
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
        composition.publisher.update_status(
            ServiceStatus(
                ServicePhase.STOPPING,
                DataState.UNKNOWN,
                True,
                False,
                False,
                "TEST_STOP",
                2_000,
            )
        )

        composition.publisher.publish_settled(
            reducer=reducer,
            commit=CausalCommit(
                boundary=FactBoundary(1, 1, 1_500, 1),
                cause=CausalCause.TIME_BOUNDARY,
                failure_domain=FailureScope.CLOCK_INDEX,
                affected_scopes=("GLOBAL",),
            ),
        )

        recorded = [
            cast(int, value["recorded_monotonic_ms"]) for value in composition.service_writer.events
        ]
        assert recorded == sorted(recorded)
        assert recorded[-1] == 2_000
        assert composition.publisher.status.phase is ServicePhase.STOPPING
    finally:
        composition.workbench.close()


def test_stop_between_sessions_does_not_create_a_synthetic_reconnect(tmp_path: Path) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    try:
        reducer = composition.runtime.reducer
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
        composition.runtime.prepare_reconnect("SESSION_GAP")
        assert reducer.current_session_epoch == 1
        assert reducer.diagnostics.reconnect_count == 0
        event = PersistentStopEvent()
        assert event.request(terminal_monotonic_ms=2_000, reason="TEST_STOP") is True

        summary = service_module._stop_without_client(
            composition,
            event=event,
            session_epoch=1,
            monotonic_ms=lambda: 2_000,
        )

        assert summary.is_file()
        assert reducer.current_session_epoch == 1
        assert reducer.diagnostics.reconnect_count == 0
        evidence = read_complete_persistent_service_evidence(
            startup.run_directory,
            bindings=startup.service_bindings,
            downstream_bindings=startup.downstream_bindings,
        )
        assert evidence.terminal is not None
        assert evidence.terminal["terminal_disposition"] == "CLEAN_STOP"
    finally:
        composition.workbench.close()


def test_reconnect_increments_session_epoch_without_replacing_owner(tmp_path: Path) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    try:
        owner = composition.owner
        runtime_identity = composition.runtime.runtime_identity
        composition.runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
        composition.runtime.prepare_reconnect("SESSION_GAP")
        composition.runtime.reducer.begin_session(session_epoch=2, monotonic_ms=2_000)

        assert composition.runtime.runtime_identity == runtime_identity
        assert composition.adapter.owner is owner
        assert composition.runtime.reducer.current_session_epoch == 2
        assert composition.runtime.reducer.diagnostics.reconnect_count == 1
        body = json.loads(composition.snapshot_store.read().workbench_body)
        assert body["service"]["data_state"] in {"INTERRUPTED", "UNKNOWN"}
        assert body["runtime_identity"] == runtime_identity
    finally:
        composition.workbench.close()


@dataclass
class _OrderingAdapter:
    order: list[str]
    required_combo_instrument_names: tuple[str, ...] = ()

    def on_settled_transaction(
        self,
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
    ) -> tuple[ShadowRpcIntent, ...]:
        del reducer, commit
        self.order.append("shadow")
        return ()

    def next_time_boundary_monotonic_ms(
        self,
        *,
        reducer: RadarReducer,
        after_monotonic_ms: int,
    ) -> int | None:
        del reducer, after_monotonic_ms
        return None

    def realize_runtime_start(self, *, reducer: RadarReducer, boundary: FactBoundary) -> None:
        del reducer, boundary

    def realize_enrollment_cutoff(self, *, reducer: RadarReducer, boundary: FactBoundary) -> None:
        del reducer, boundary

    def configure_terminal_control(
        self,
        *,
        terminal_disposition: str,
        terminal_source: Mapping[str, object],
    ) -> None:
        del terminal_disposition, terminal_source

    def on_request_sent(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        del request_id, boundary
        return ()

    def on_request_failure(
        self,
        *,
        request_id: int,
        terminal_state: RpcState,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        del request_id, terminal_state, boundary
        return ()

    def on_rpc_response(
        self,
        *,
        request_id: int,
        result: object,
        sent_boundary: FactBoundary,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        del request_id, result, sent_boundary, boundary
        return ()

    def terminate(self, *, source: str, boundary: FactBoundary) -> None:
        del source, boundary

    def finalize_terminal(self) -> None:
        return None


@dataclass
class _OrderingPublisher:
    order: list[str]
    snapshots: list[CausalCommit] = field(default_factory=list)

    def publish_settled(self, *, reducer: RadarReducer, commit: CausalCommit) -> None:
        del reducer
        assert self.order == ["shadow"]
        self.order.append("snapshot")
        self.snapshots.append(commit)


def test_runtime_publishes_snapshot_only_after_shadow_settlement(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    order: list[str] = []
    adapter = _OrderingAdapter(order)
    publisher = _OrderingPublisher(order)
    reducer = RadarReducer(
        policy=load_policy_bytes(exact, digest),
        code_identity=CODE,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity=CODE,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
        shadow_adapter=adapter,
        snapshot_publisher=publisher,
    )
    monotonic_ms = reducer._coverage._current_start_ms + 10
    commit = CausalCommit(
        boundary=FactBoundary(1, 0, monotonic_ms, 1),
        cause=CausalCause.RUNTIME_START,
        failure_domain=FailureScope.SESSION,
        affected_scopes=("GLOBAL",),
    )

    reducer._settle_fact(commit=commit, affected_instruments=(), countable=False)

    assert order == ["shadow", "snapshot"]
    assert publisher.snapshots == [commit]
