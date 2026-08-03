from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import FrozenInstanceError, dataclass, field
from pathlib import Path
from typing import NoReturn

import pytest
import radar_runtime.service as service_module
import radar_runtime.workbench as workbench_module
from conftest import PolicyFactory
from radar_runtime.deribit_public import (
    InboundEnvelope,
    PublicProtocolIncompatibility,
    SendControlEvent,
)
from radar_runtime.runtime import (
    CausalCause,
    CausalCommit,
    FactBoundary,
    FailureScope,
    LiveRadarRuntime,
    PublicClient,
    RadarReducer,
    RpcState,
    ShadowRpcIntent,
)
from radar_runtime.service import (
    PersistentServiceStartup,
    PersistentServiceStartupError,
    PersistentStopEvent,
    SingleInstanceLease,
    build_persistent_service_composition,
    generate_runtime_identity,
    prepare_persistent_service_startup,
    run_persistent_service_composition,
)
from radar_runtime.workbench import DataState, ServicePhase, ServiceStatus
from short_vol_radar.evidence import RadarEventSink
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


def test_single_instance_lease_rejects_duplicate_and_releases(tmp_path: Path) -> None:
    state_root = (tmp_path / "state").resolve()
    first = SingleInstanceLease(state_root)
    second = SingleInstanceLease(state_root)

    first.acquire()
    with pytest.raises(PersistentServiceStartupError, match="another persistent service"):
        second.acquire()
    first.release()

    second.acquire()
    assert second.acquired is True
    second.release()


def test_startup_builds_one_business_owner_graph_without_service_ledger(tmp_path: Path) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    try:
        assert startup.cases_directory.is_dir()
        assert sorted(path.name for path in startup.run_directory.iterdir()) == ["cases"]
        assert composition.owner.policies is startup.policies
        assert composition.runtime.policy is startup.policies.radar
        assert composition.adapter.owner is composition.owner
        assert composition.publisher.bindings is startup.runtime_bindings
        with pytest.raises(FrozenInstanceError):
            startup.policies.radar.identity = "sha256:" + "f" * 64  # type: ignore[misc]
    finally:
        composition.workbench.close()


def test_runtime_identity_changes_each_start() -> None:
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


def test_stop_event_preserves_first_boundary() -> None:
    event = PersistentStopEvent()

    assert event.request(terminal_monotonic_ms=100, reason="FIRST") is True
    assert event.request(terminal_monotonic_ms=200, reason="SECOND") is False
    assert event.terminal_monotonic_ms == 100
    assert event.reason == "FIRST"


class _WaitingClient:
    queue_high_water_frames = 0
    overflow_count = 0
    received_frame_count = 0
    enqueued_envelope_count = 0

    def __init__(self, session_epoch: int = 1) -> None:
        self.session_epoch = session_epoch

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


class _RecoverableFailureClient(_WaitingClient):
    async def next_envelope(self, timeout_seconds: float | None = None) -> InboundEnvelope:
        del timeout_seconds
        raise ConnectionError("test recoverable transport failure")


class _FatalProtocolClient(_WaitingClient):
    async def next_envelope(self, timeout_seconds: float | None = None) -> InboundEnvelope:
        del timeout_seconds
        raise PublicProtocolIncompatibility("test protocol incompatibility")


def test_pre_latched_stop_opens_no_client_and_writes_radar_summary(tmp_path: Path) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    event = PersistentStopEvent()
    terminal_ms = service_module._monotonic_ms() + 1
    event.request(terminal_monotonic_ms=terminal_ms, reason="TEST_STOP")

    def forbidden_client(**_: object) -> NoReturn:
        raise AssertionError("pre-latched stop must not construct a market client")

    try:
        summary = asyncio.run(
            run_persistent_service_composition(
                composition,
                stop_event=event,
                client_factory=forbidden_client,
                monotonic_ms=lambda: terminal_ms,
                signal_registrar=lambda _signal, _callback: None,
                start_workbench=False,
            )
        )
        assert summary["object_kind"] == "RADAR_RUN_SUMMARY"
        assert composition.radar_sink.summary == summary
        assert list(startup.cases_directory.iterdir()) == []
        assert composition.runtime.shadow_terminalized is True
        assert composition.publisher.status.phase is ServicePhase.STOPPED
        assert sorted(path.name for path in startup.run_directory.iterdir()) == ["cases"]
    finally:
        composition.workbench.close()


def test_outer_loop_reconnects_without_replacing_business_owner(tmp_path: Path) -> None:
    composition = build_persistent_service_composition(_startup(tmp_path))
    event = PersistentStopEvent()
    owner = composition.owner
    epochs: list[int] = []

    def client_factory(
        *, session_epoch: int, rpc_deadline_ms: int
    ) -> AbstractAsyncContextManager[PublicClient]:
        assert rpc_deadline_ms > 0
        epochs.append(session_epoch)
        client: _WaitingClient = (
            _RecoverableFailureClient(session_epoch)
            if session_epoch == 1
            else _WaitingClient(session_epoch)
        )
        return _WaitingClientContext(client)

    async def scenario() -> Mapping[str, object]:
        task = asyncio.create_task(
            run_persistent_service_composition(
                composition,
                stop_event=event,
                client_factory=client_factory,
                signal_registrar=lambda _signal, _callback: None,
                sleep=lambda _seconds: asyncio.sleep(0),
                start_workbench=False,
            )
        )
        for _ in range(1_000):
            if (
                composition.runtime.reducer.current_session_epoch == 2
                and composition.publisher.status.phase is ServicePhase.RUNNING
            ):
                break
            await asyncio.sleep(0)
        assert event.request(
            terminal_monotonic_ms=max(
                service_module._monotonic_ms(),
                composition.runtime.reducer.last_boundary_monotonic_ms + 1,
            ),
            reason="TEST_AFTER_RECONNECT",
        )
        return await task

    try:
        summary = asyncio.run(scenario())
        assert summary["object_kind"] == "RADAR_RUN_SUMMARY"
        assert composition.radar_sink.summary == summary
        assert list(composition.startup.cases_directory.iterdir()) == []
        assert epochs == [1, 2]
        assert composition.owner is owner
        assert composition.runtime.reducer.diagnostics.reconnect_count == 1
        assert composition.publisher.status.phase is ServicePhase.STOPPED
    finally:
        composition.workbench.close()


def test_fatal_protocol_failure_terminalizes_owner_and_status(tmp_path: Path) -> None:
    composition = build_persistent_service_composition(_startup(tmp_path))

    def client_factory(
        *, session_epoch: int, rpc_deadline_ms: int
    ) -> AbstractAsyncContextManager[PublicClient]:
        assert rpc_deadline_ms > 0
        return _WaitingClientContext(_FatalProtocolClient(session_epoch))

    try:
        with pytest.raises(PublicProtocolIncompatibility):
            asyncio.run(
                run_persistent_service_composition(
                    composition,
                    client_factory=client_factory,
                    signal_registrar=lambda _signal, _callback: None,
                    start_workbench=False,
                )
            )
        assert composition.runtime.shadow_terminalized is True
        assert composition.publisher.status.phase is ServicePhase.FAILED
        assert composition.radar_sink.summary is None
        assert list(composition.startup.cases_directory.iterdir()) == []
    finally:
        composition.workbench.close()


def test_workbench_coalesces_and_flushes_latest_business_state(tmp_path: Path) -> None:
    composition = build_persistent_service_composition(_startup(tmp_path))
    reducer = composition.runtime.reducer
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    try:
        composition.publisher.update_status(
            workbench_module._settled_status(
                reducer,
                phase=ServicePhase.RUNNING,
                recorded_monotonic_ms=1_000,
            )
        )
        sequence = composition.snapshot_store.read().sequence
        for causal_seq, monotonic_ms in ((1, 1_100), (2, 1_200)):
            composition.publisher.publish_settled(
                reducer=reducer,
                commit=CausalCommit(
                    boundary=FactBoundary(1, causal_seq, monotonic_ms, causal_seq),
                    cause=CausalCause.TIME_BOUNDARY,
                    failure_domain=FailureScope.CLOCK_INDEX,
                    affected_scopes=("GLOBAL",),
                ),
            )
        assert composition.snapshot_store.read().sequence == sequence

        composition.publisher.flush_pending()
        value = json.loads(composition.snapshot_store.read().workbench_body)
        assert value["publication_sequence"] == sequence + 1
        assert value["published_fact_boundary"]["causal_seq"] == 2
    finally:
        composition.workbench.close()


def test_status_change_publishes_pending_business_state_immediately(tmp_path: Path) -> None:
    composition = build_persistent_service_composition(_startup(tmp_path))
    reducer = composition.runtime.reducer
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    try:
        composition.publisher.update_status(
            workbench_module._settled_status(
                reducer,
                phase=ServicePhase.RUNNING,
                recorded_monotonic_ms=1_000,
            )
        )
        sequence = composition.snapshot_store.read().sequence
        composition.publisher.publish_settled(
            reducer=reducer,
            commit=CausalCommit(
                boundary=FactBoundary(1, 1, 1_100, 1),
                cause=CausalCause.TIME_BOUNDARY,
                failure_domain=FailureScope.CLOCK_INDEX,
                affected_scopes=("GLOBAL",),
            ),
        )
        composition.publisher.update_status(
            ServiceStatus(
                ServicePhase.RUNNING,
                DataState.CURRENT,
                True,
                True,
                False,
                "CURRENT",
                1_200,
            )
        )
        value = json.loads(composition.snapshot_store.read().workbench_body)
        assert value["publication_sequence"] == sequence + 1
        assert value["published_fact_boundary"]["causal_seq"] == 1
        assert value["service"]["ready"] is True
    finally:
        composition.workbench.close()


@dataclass
class _OrderingAdapter:
    order: list[str]
    required_combo_instrument_names: tuple[str, ...] = ()

    def on_settled_transaction(
        self, *, reducer: RadarReducer, commit: CausalCommit
    ) -> tuple[ShadowRpcIntent, ...]:
        del reducer, commit
        self.order.append("shadow")
        return ()

    def next_time_boundary_monotonic_ms(
        self, *, reducer: RadarReducer, after_monotonic_ms: int
    ) -> int | None:
        del reducer, after_monotonic_ms
        return None

    def realize_runtime_start(self, *, reducer: RadarReducer, boundary: FactBoundary) -> None:
        del reducer, boundary

    def realize_enrollment_cutoff(self, *, reducer: RadarReducer, boundary: FactBoundary) -> None:
        del reducer, boundary

    def on_request_sent(
        self, *, request_id: int, boundary: FactBoundary
    ) -> tuple[ShadowRpcIntent, ...]:
        del request_id, boundary
        return ()

    def on_request_failure(
        self, *, request_id: int, terminal_state: RpcState, boundary: FactBoundary
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


@dataclass
class _OrderingPublisher:
    order: list[str]
    snapshots: list[CausalCommit] = field(default_factory=list)

    def publish_settled(self, *, reducer: RadarReducer, commit: CausalCommit) -> None:
        del reducer
        assert self.order == ["shadow"]
        self.order.append("snapshot")
        self.snapshots.append(commit)

    def flush_pending(self) -> None:
        self.order.append("flush")


def test_runtime_publishes_snapshot_only_after_shadow_settlement(
    tmp_path: Path, policy_factory: PolicyFactory
) -> None:
    exact, digest = policy_factory()
    order: list[str] = []
    adapter = _OrderingAdapter(order)
    publisher = _OrderingPublisher(order)
    reducer = RadarReducer(
        policy=load_policy_bytes(exact, digest),
        code_identity=CODE,
        event_sink=RadarEventSink(
            code_identity=CODE,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
        shadow_adapter=adapter,
        snapshot_publisher=publisher,
    )
    commit = CausalCommit(
        boundary=FactBoundary(1, 0, reducer._coverage._current_start_ms + 10, 1),
        cause=CausalCause.RUNTIME_START,
        failure_domain=FailureScope.SESSION,
        affected_scopes=("GLOBAL",),
    )

    reducer._settle_fact(commit=commit, affected_instruments=(), countable=False)

    assert order == ["shadow", "snapshot"]
    assert publisher.snapshots == [commit]


def test_runtime_flushes_before_clean_stop_and_reconnect(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, digest = policy_factory()
    policy = load_policy_bytes(exact, digest)

    clean_order: list[str] = []
    clean_evidence = tmp_path / "clean"
    clean_evidence.mkdir()
    clean_runtime = LiveRadarRuntime(
        policy=policy,
        code_identity=CODE,
        event_sink=RadarEventSink(
            code_identity=CODE,
            runtime_identity="clean-runtime",
            policy_identity=digest,
        ),
        runtime_identity="clean-runtime",
        snapshot_publisher=_OrderingPublisher(clean_order),
    )
    original_clean_stop = clean_runtime.reducer.clean_stop

    def ordered_clean_stop(monotonic_ms: int) -> Mapping[str, object]:
        clean_order.append("clean_stop")
        return original_clean_stop(monotonic_ms)

    monkeypatch.setattr(clean_runtime.reducer, "clean_stop", ordered_clean_stop)
    stop_event = asyncio.Event()
    stop_event.set()
    asyncio.run(clean_runtime.run(_WaitingClient(), stop_event))
    assert clean_order[-2:] == ["flush", "clean_stop"]

    reconnect_order: list[str] = []
    reconnect_evidence = tmp_path / "reconnect"
    reconnect_evidence.mkdir()
    reconnect_runtime = LiveRadarRuntime(
        policy=policy,
        code_identity=CODE,
        event_sink=RadarEventSink(
            code_identity=CODE,
            runtime_identity="reconnect-runtime",
            policy_identity=digest,
        ),
        runtime_identity="reconnect-runtime",
        snapshot_publisher=_OrderingPublisher(reconnect_order),
    )
    original_reconnect = reconnect_runtime.reducer.prepare_reconnect

    def ordered_reconnect(reason: str) -> None:
        reconnect_order.append("prepare_reconnect")
        original_reconnect(reason)

    monkeypatch.setattr(reconnect_runtime.reducer, "prepare_reconnect", ordered_reconnect)
    with pytest.raises(ConnectionError, match="test recoverable transport failure"):
        asyncio.run(reconnect_runtime.run(_RecoverableFailureClient(), asyncio.Event()))
    assert reconnect_order[-2:] == ["flush", "prepare_reconnect"]
