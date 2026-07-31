from __future__ import annotations

import asyncio
import fcntl
import os
import signal
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from market_monitor import ContinuityGap
from market_monitor.types import SourceDataError
from short_vol_radar.evidence import EvidenceWriter
from short_vol_underwriting.constants import (
    OUTCOME_CONTRACT_DIGEST,
    POSITION_POLICY_IDENTITY,
    RADAR_POLICY_IDENTITY,
    UNDERWRITING_POLICY_IDENTITY,
    UNDERWRITING_POSITION_CONTRACT_DIGEST,
)
from short_vol_underwriting.evidence import DownstreamEvidenceWriter, RuntimeBindings
from short_vol_underwriting.identity import canonical_identity, require_code_identity
from short_vol_underwriting.model import FactBoundary as DownstreamFactBoundary
from short_vol_underwriting.model import TerminalSource
from short_vol_underwriting.owner import FixedContractShadowOwner
from short_vol_underwriting.policy import PolicyChain, load_policy_chain
from websockets.exceptions import WebSocketException

from radar_runtime.deribit_public import (
    DeribitPublicClient,
    PublicProtocolError,
    PublicProtocolIncompatibility,
    PublicSessionError,
)
from radar_runtime.fixed_contract_shadow import FixedContractShadowRuntimeAdapter
from radar_runtime.identity import clean_code_identity, git_repository_root
from radar_runtime.runtime import (
    FactBoundary,
    LiveRadarRuntime,
    PublicClient,
    RadarReducer,
    reconnect_delay_seconds,
)
from radar_runtime.service_evidence import (
    DataState,
    PersistentServiceBindings,
    PersistentServiceEvidenceWriter,
    ServicePhase,
    ServiceStatus,
)
from radar_runtime.workbench import (
    LoopbackWorkbenchServer,
    SnapshotStore,
    WorkbenchPublisher,
    initial_workbench_document,
    validate_loopback_endpoint,
)

MonotonicClock = Callable[[], int]
AsyncSleep = Callable[[float], Awaitable[None]]
SignalRegistrar = Callable[[signal.Signals, Callable[[], None]], None]
NonceFactory = Callable[[], str]
StopListener = Callable[[int, str], None]


class PersistentClientFactory(Protocol):
    def __call__(
        self,
        *,
        session_epoch: int,
        rpc_deadline_ms: int,
    ) -> AbstractAsyncContextManager[PublicClient]: ...


class PersistentServiceStartupError(RuntimeError):
    """Persistent service startup is not one closed immutable graph."""


class SingleInstanceLease:
    """Non-blocking process lease for one configured service state root."""

    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self.path = state_root / "service.lock"
        self._descriptor: int | None = None

    @property
    def acquired(self) -> bool:
        return self._descriptor is not None

    def acquire(self) -> None:
        if self._descriptor is not None:
            raise RuntimeError("single-instance lease is already acquired")
        self.state_root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"pid={os.getpid()}\n".encode())
            os.fsync(descriptor)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise PersistentServiceStartupError(
                "another persistent service owns this state root"
            ) from exc
        except OSError:
            os.close(descriptor)
            raise
        self._descriptor = descriptor

    def release(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
            self._descriptor = None

    def __enter__(self) -> SingleInstanceLease:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.release()


class PersistentStopEvent(asyncio.Event):
    """Latch the first exact stop boundary and report whether the request won."""

    def __init__(self) -> None:
        super().__init__()
        self._terminal_monotonic_ms: int | None = None
        self._reason: str | None = None
        self._listeners: list[StopListener] = []

    @property
    def terminal_monotonic_ms(self) -> int | None:
        return self._terminal_monotonic_ms

    @property
    def reason(self) -> str | None:
        return self._reason

    def add_listener(self, listener: StopListener) -> None:
        if listener in self._listeners:
            return
        self._listeners.append(listener)
        if self._terminal_monotonic_ms is not None and self._reason is not None:
            listener(self._terminal_monotonic_ms, self._reason)

    def request(self, *, terminal_monotonic_ms: int, reason: str) -> bool:
        _require_monotonic_ms(terminal_monotonic_ms)
        if not reason:
            raise ValueError("persistent stop reason must be non-empty")
        if self._terminal_monotonic_ms is not None:
            return False
        self._terminal_monotonic_ms = terminal_monotonic_ms
        self._reason = reason
        self.set()
        for listener in tuple(self._listeners):
            listener(terminal_monotonic_ms, reason)
        return True


@dataclass(frozen=True)
class PersistentServiceStartup:
    repository: Path
    state_root: Path
    run_directory: Path
    radar_directory: Path
    downstream_directory: Path
    service_directory: Path
    code_identity: str
    runtime_identity: str
    startup_monotonic_ms: int
    policies: PolicyChain
    downstream_bindings: RuntimeBindings
    service_bindings: PersistentServiceBindings
    workbench_host: str
    workbench_port: int


@dataclass(frozen=True)
class PersistentServiceComposition:
    startup: PersistentServiceStartup
    downstream_writer: DownstreamEvidenceWriter
    owner: FixedContractShadowOwner
    service_writer: PersistentServiceEvidenceWriter
    adapter: PersistentShadowRuntimeAdapter
    radar_writer: EvidenceWriter
    snapshot_store: SnapshotStore
    publisher: WorkbenchPublisher
    runtime: LiveRadarRuntime
    workbench: LoopbackWorkbenchServer


class PersistentShadowRuntimeAdapter(FixedContractShadowRuntimeAdapter):
    """Existing fixed-contract owner with non-cohort service terminal semantics."""

    def __init__(
        self,
        *,
        owner: FixedContractShadowOwner,
        service_writer: PersistentServiceEvidenceWriter,
        service_bindings: PersistentServiceBindings,
    ) -> None:
        super().__init__(owner=owner, manifest=None)
        self.service_writer = service_writer
        self.service_bindings = service_bindings
        self._terminal_disposition: str | None = None
        self._terminal_source_identity: str | None = None
        self._terminal_boundary: DownstreamFactBoundary | None = None

    def bind_reducer(self, reducer: RadarReducer) -> None:
        if self._last_reducer is not None and self._last_reducer is not reducer:
            raise ValueError("persistent adapter reducer binding is immutable")
        self._require_bindings(reducer)
        self._last_reducer = reducer

    def configure_terminal_control(
        self,
        *,
        terminal_disposition: str,
        terminal_source: Mapping[str, object],
    ) -> None:
        del terminal_disposition, terminal_source
        raise RuntimeError("persistent service does not consume bounded cohort controls")

    def terminate(self, *, source: str, boundary: FactBoundary) -> None:
        reducer = self._require_reducer()
        downstream = self._boundary(reducer, boundary)
        if source == "STOP":
            disposition = "CLEAN_STOP"
            terminal_kind = TerminalSource.STOP
        elif source == "FAILURE":
            disposition = "PROCESS_FAILURE"
            terminal_kind = TerminalSource.FAILURE
        else:
            raise ValueError("persistent terminal source must be STOP or FAILURE")
        source_identity = canonical_identity(
            "PersistentServiceTerminalSourceIdentity",
            self.service_bindings.contract_identity,
            disposition,
            downstream.as_object(),
        )
        transition = self.owner.terminate(
            boundary=downstream,
            terminal_source_identity=source_identity,
            terminal_source=terminal_kind,
        )
        self._consume_transition(transition, ())
        if self._terminal_boundary is not None and (
            self._terminal_boundary != downstream
            or self._terminal_disposition != disposition
            or self._terminal_source_identity != source_identity
        ):
            raise ValueError("persistent terminal barrier is immutable")
        self._terminal_disposition = disposition
        self._terminal_source_identity = source_identity
        self._terminal_boundary = downstream

    def finalize_terminal(self) -> None:
        if (
            self._terminal_disposition is None
            or self._terminal_source_identity is None
            or self._terminal_boundary is None
        ):
            raise RuntimeError("persistent service terminal requires its owner barrier")
        self.service_writer.finalize(
            terminal_disposition=self._terminal_disposition,
            terminal_source_identity=self._terminal_source_identity,
            terminal_fact_boundary=self._terminal_boundary,
        )


def generate_runtime_identity(
    *,
    code_identity: str,
    startup_monotonic_ms: int,
    process_id: int,
    nonce: str,
) -> str:
    require_code_identity(code_identity)
    _require_monotonic_ms(startup_monotonic_ms)
    if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id <= 0:
        raise ValueError("process id must be positive")
    if not nonce:
        raise ValueError("runtime nonce must be non-empty")
    return canonical_identity(
        "PersistentServiceRuntimeIdentity",
        code_identity,
        startup_monotonic_ms,
        process_id,
        nonce,
    )


def prepare_persistent_service_startup(
    *,
    state_root: Path,
    process_cwd: Path,
    workbench_host: str,
    workbench_port: int,
    code_identity: str | None = None,
    startup_monotonic_ms: int | None = None,
    process_id: int | None = None,
    nonce_factory: NonceFactory | None = None,
) -> PersistentServiceStartup:
    repository = git_repository_root(process_cwd)
    validated_host, validated_port = validate_loopback_endpoint(
        workbench_host,
        workbench_port,
    )
    resolved_state_root = _prepare_state_root(state_root, repository)
    resolved_code_identity = code_identity or clean_code_identity(repository)
    start_ms = _monotonic_ms() if startup_monotonic_ms is None else startup_monotonic_ms
    pid = os.getpid() if process_id is None else process_id
    nonce = (nonce_factory or (lambda: uuid.uuid4().hex))()
    runtime_identity = generate_runtime_identity(
        code_identity=resolved_code_identity,
        startup_monotonic_ms=start_ms,
        process_id=pid,
        nonce=nonce,
    )
    policies = load_policy_chain(
        radar_path=repository / "policies/short-vol-fixed-public-shadow-radar.json",
        underwriting_path=(repository / "policies/short-vol-fixed-public-shadow-underwriting.json"),
        position_path=(repository / "policies/short-vol-fixed-public-shadow-position.json"),
        radar_identity=RADAR_POLICY_IDENTITY,
        underwriting_identity=UNDERWRITING_POLICY_IDENTITY,
        position_identity=POSITION_POLICY_IDENTITY,
    )
    run_directory = resolved_state_root / "runs" / runtime_identity.removeprefix("sha256:")
    try:
        run_directory.mkdir(parents=True, exist_ok=False)
        radar_directory = run_directory / "radar"
        downstream_directory = run_directory / "downstream"
        service_directory = run_directory / "service"
        radar_directory.mkdir()
        downstream_directory.mkdir()
        service_directory.mkdir()
        (service_directory / "events").mkdir()
    except OSError as exc:
        raise PersistentServiceStartupError(
            "cannot create a new persistent runtime directory"
        ) from exc
    downstream_bindings = RuntimeBindings(
        code_identity=resolved_code_identity,
        runtime_identity=runtime_identity,
        radar_policy_identity=policies.radar.identity,
        underwriting_policy_identity=policies.underwriting.identity,
        position_policy_identity=policies.position.identity,
        underwriting_position_contract_digest=UNDERWRITING_POSITION_CONTRACT_DIGEST,
        outcome_contract_digest=OUTCOME_CONTRACT_DIGEST,
    )
    service_bindings = PersistentServiceBindings.from_runtime_bindings(downstream_bindings)
    return PersistentServiceStartup(
        repository=repository,
        state_root=resolved_state_root,
        run_directory=run_directory,
        radar_directory=radar_directory,
        downstream_directory=downstream_directory,
        service_directory=service_directory,
        code_identity=resolved_code_identity,
        runtime_identity=runtime_identity,
        startup_monotonic_ms=start_ms,
        policies=policies,
        downstream_bindings=downstream_bindings,
        service_bindings=service_bindings,
        workbench_host=validated_host,
        workbench_port=validated_port,
    )


def build_persistent_service_composition(
    startup: PersistentServiceStartup,
) -> PersistentServiceComposition:
    downstream_writer = DownstreamEvidenceWriter(
        startup.downstream_directory,
        bindings=startup.downstream_bindings,
    )
    owner = FixedContractShadowOwner(
        policies=startup.policies,
        bindings=startup.downstream_bindings,
        writer=downstream_writer,
    )
    service_writer = PersistentServiceEvidenceWriter(
        startup.service_directory,
        bindings=startup.service_bindings,
        downstream_directory=startup.downstream_directory,
        radar_directory=startup.radar_directory,
        downstream_bindings=startup.downstream_bindings,
    )
    adapter = PersistentShadowRuntimeAdapter(
        owner=owner,
        service_writer=service_writer,
        service_bindings=startup.service_bindings,
    )
    snapshot_store = SnapshotStore(
        initial_workbench_document(
            startup.service_bindings,
            recorded_monotonic_ms=startup.startup_monotonic_ms,
        )
    )
    publisher = WorkbenchPublisher(
        store=snapshot_store,
        bindings=startup.service_bindings,
        policies=startup.policies,
        downstream_writer=downstream_writer,
        shadow_metadata=adapter,
        status_sink=service_writer.write_event,
        initial_recorded_monotonic_ms=startup.startup_monotonic_ms,
    )
    radar_writer = EvidenceWriter(
        startup.radar_directory,
        code_identity=startup.code_identity,
        runtime_identity=startup.runtime_identity,
        policy_identity=startup.policies.radar.identity,
    )
    runtime = LiveRadarRuntime(
        policy=startup.policies.radar,
        code_identity=startup.code_identity,
        evidence_writer=radar_writer,
        runtime_identity=startup.runtime_identity,
        shadow_adapter=adapter,
        snapshot_publisher=publisher,
    )
    adapter.bind_reducer(runtime.reducer)
    workbench = LoopbackWorkbenchServer(
        host=startup.workbench_host,
        port=startup.workbench_port,
        store=snapshot_store,
    )
    publisher.update_status(
        ServiceStatus(
            ServicePhase.STARTING,
            DataState.UNKNOWN,
            True,
            False,
            False,
            "STARTING",
            startup.startup_monotonic_ms,
        )
    )
    return PersistentServiceComposition(
        startup=startup,
        downstream_writer=downstream_writer,
        owner=owner,
        service_writer=service_writer,
        adapter=adapter,
        radar_writer=radar_writer,
        snapshot_store=snapshot_store,
        publisher=publisher,
        runtime=runtime,
        workbench=workbench,
    )


def install_persistent_signal_handlers(
    stop_event: PersistentStopEvent,
    *,
    monotonic_ms: MonotonicClock,
    registrar: SignalRegistrar | None = None,
) -> None:
    register = registrar or asyncio.get_running_loop().add_signal_handler
    reasons = {
        signal.SIGINT: "USER_REQUEST",
        signal.SIGTERM: "EXTERNAL_SAFETY_STOP",
    }
    for signum, reason in reasons.items():

        def handle_signal(
            member_reason: str = reason,
        ) -> None:
            stop_event.request(
                terminal_monotonic_ms=monotonic_ms(),
                reason=member_reason,
            )

        try:
            register(signum, handle_signal)
        except NotImplementedError:
            pass


async def run_persistent_service_composition(
    composition: PersistentServiceComposition,
    *,
    stop_event: PersistentStopEvent | None = None,
    client_factory: PersistentClientFactory | None = None,
    monotonic_ms: MonotonicClock | None = None,
    signal_registrar: SignalRegistrar | None = None,
    sleep: AsyncSleep = asyncio.sleep,
    start_workbench: bool = True,
) -> Path:
    clock = monotonic_ms or _monotonic_ms
    event = stop_event or PersistentStopEvent()
    install_persistent_signal_handlers(
        event,
        monotonic_ms=clock,
        registrar=signal_registrar,
    )

    def publish_stopping(terminal_monotonic_ms: int, reason: str) -> None:
        if composition.publisher.status.phase in {ServicePhase.STOPPED, ServicePhase.FAILED}:
            return
        composition.publisher.update_status(
            ServiceStatus(
                ServicePhase.STOPPING,
                DataState.INTERRUPTED,
                True,
                False,
                False,
                reason,
                terminal_monotonic_ms,
            )
        )

    event.add_listener(publish_stopping)
    create_client = client_factory or _deribit_client_factory
    reconnect_attempt = 0
    session_epoch = 0
    if start_workbench:
        composition.workbench.start()
    try:
        while True:
            if event.is_set():
                return _stop_without_client(
                    composition,
                    event=event,
                    session_epoch=session_epoch,
                    monotonic_ms=clock,
                )
            composition.publisher.update_status(
                ServiceStatus(
                    ServicePhase.CONNECTING,
                    DataState.UNKNOWN,
                    True,
                    False,
                    False,
                    "CONNECTING",
                    clock(),
                )
            )
            completed_summary_path: Path | None = None
            try:
                session_epoch += 1
                async with create_client(
                    session_epoch=session_epoch,
                    rpc_deadline_ms=(
                        composition.startup.policies.radar.runtime_limits.rpc_deadline_ms
                    ),
                ) as client:
                    composition.publisher.update_status(
                        ServiceStatus(
                            ServicePhase.RUNNING,
                            DataState.UNKNOWN,
                            True,
                            False,
                            False,
                            "SESSION_BOOTSTRAP",
                            clock(),
                        )
                    )
                    completed_summary_path = await composition.runtime.run(client, event)
                composition.publisher.update_status(
                    ServiceStatus(
                        ServicePhase.STOPPED,
                        DataState.STOPPED,
                        False,
                        False,
                        False,
                        "CLEAN_STOP",
                        _terminal_ms(event, clock()),
                    ),
                    persist=False,
                )
                return completed_summary_path
            except (
                ContinuityGap,
                SourceDataError,
                TimeoutError,
                ConnectionError,
                OSError,
                PublicSessionError,
                WebSocketException,
            ) as exc:
                if completed_summary_path is not None and event.is_set():
                    return completed_summary_path
                if event.is_set():
                    _finalize_failure(composition, failure=exc, monotonic_ms=clock())
                    raise
                composition.publisher.update_status(
                    ServiceStatus(
                        ServicePhase.RECONNECTING,
                        DataState.INTERRUPTED,
                        True,
                        False,
                        False,
                        type(exc).__name__,
                        clock(),
                    )
                )
                if composition.runtime.session_established:
                    reconnect_attempt = 0
                await _sleep_or_stop(
                    event,
                    seconds=reconnect_delay_seconds(
                        reconnect_attempt,
                        base_delay_ms=(
                            composition.startup.policies.radar.runtime_limits.time_boundary_poll_interval_ms
                        ),
                        maximum_delay_ms=(
                            composition.startup.policies.radar.runtime_limits.rpc_deadline_ms
                        ),
                    ),
                    sleep=sleep,
                )
                reconnect_attempt += 1
            except (PublicProtocolIncompatibility, PublicProtocolError) as exc:
                _finalize_failure(composition, failure=exc, monotonic_ms=clock())
                raise
            except Exception as exc:
                _finalize_failure(composition, failure=exc, monotonic_ms=clock())
                raise
    finally:
        if start_workbench:
            composition.workbench.close()


async def run_persistent_service(
    *,
    state_root: Path,
    process_cwd: Path,
    workbench_host: str,
    workbench_port: int,
) -> tuple[PersistentServiceStartup, Path]:
    repository = git_repository_root(process_cwd)
    resolved_state_root = _prepare_state_root(state_root, repository)
    lease = SingleInstanceLease(resolved_state_root)
    with lease:
        startup = prepare_persistent_service_startup(
            state_root=resolved_state_root,
            process_cwd=repository,
            workbench_host=workbench_host,
            workbench_port=workbench_port,
        )
        composition = build_persistent_service_composition(startup)
        summary = await run_persistent_service_composition(composition)
        return startup, summary


def _stop_without_client(
    composition: PersistentServiceComposition,
    *,
    event: PersistentStopEvent,
    session_epoch: int,
    monotonic_ms: MonotonicClock,
) -> Path:
    terminal_ms = _terminal_ms(event, monotonic_ms())
    composition.publisher.update_status(
        ServiceStatus(
            ServicePhase.STOPPING,
            DataState.INTERRUPTED,
            True,
            False,
            False,
            event.reason or "STOP_REQUESTED",
            terminal_ms,
        )
    )
    current_epoch = composition.runtime.reducer.current_session_epoch
    if current_epoch is None:
        next_epoch = max(session_epoch + 1, 1)
        composition.runtime.reducer.begin_session(
            session_epoch=next_epoch,
            monotonic_ms=terminal_ms,
        )
    summary = composition.runtime.reducer.clean_stop(terminal_ms)
    composition.publisher.update_status(
        ServiceStatus(
            ServicePhase.STOPPED,
            DataState.STOPPED,
            False,
            False,
            False,
            "CLEAN_STOP",
            terminal_ms,
        ),
        persist=False,
    )
    return summary


def _finalize_failure(
    composition: PersistentServiceComposition,
    *,
    failure: Exception,
    monotonic_ms: int,
) -> None:
    if composition.runtime.shadow_terminalized:
        return
    terminal_ms = max(monotonic_ms, composition.runtime.reducer.last_boundary_monotonic_ms)
    composition.publisher.update_status(
        ServiceStatus(
            ServicePhase.STOPPING,
            DataState.INTERRUPTED,
            True,
            False,
            False,
            f"PROCESS_FAILURE:{type(failure).__name__}",
            terminal_ms,
        )
    )
    composition.runtime.finalize_shadow_failure(terminal_ms)
    composition.publisher.update_status(
        ServiceStatus(
            ServicePhase.FAILED,
            DataState.STOPPED,
            False,
            False,
            False,
            "PROCESS_FAILURE",
            terminal_ms,
        ),
        persist=False,
    )


def _prepare_state_root(state_root: Path, repository: Path) -> Path:
    if not state_root.is_absolute():
        raise PersistentServiceStartupError("persistent state root must be absolute")
    if state_root.is_symlink():
        raise PersistentServiceStartupError("persistent state root cannot be a symlink")
    resolved = state_root.resolve()
    repository_resolved = repository.resolve()
    if resolved == repository_resolved or repository_resolved in resolved.parents:
        raise PersistentServiceStartupError(
            "persistent state root must stay outside the Git worktree"
        )
    resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.is_dir():
        raise PersistentServiceStartupError("persistent state root is not a directory")
    (resolved / "runs").mkdir(exist_ok=True)
    return resolved


async def _sleep_or_stop(
    stop_event: PersistentStopEvent,
    *,
    seconds: float,
    sleep: AsyncSleep,
) -> None:
    async def wait_for_stop() -> None:
        await stop_event.wait()

    sleep_task: asyncio.Future[None] = asyncio.ensure_future(sleep(seconds))
    stop_task: asyncio.Future[None] = asyncio.create_task(wait_for_stop())
    tasks: set[asyncio.Future[None]] = {sleep_task, stop_task}
    done, pending = await asyncio.wait(
        tasks,
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    for task in pending:
        try:
            await task
        except asyncio.CancelledError:
            pass
    if sleep_task in done:
        await sleep_task


def _deribit_client_factory(
    *,
    session_epoch: int,
    rpc_deadline_ms: int,
) -> AbstractAsyncContextManager[PublicClient]:
    return cast(
        AbstractAsyncContextManager[PublicClient],
        DeribitPublicClient(
            session_epoch=session_epoch,
            rpc_deadline_ms=rpc_deadline_ms,
        ),
    )


def _terminal_ms(event: PersistentStopEvent, fallback: int) -> int:
    value = event.terminal_monotonic_ms
    return fallback if value is None else value


def _require_monotonic_ms(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("monotonic time must be a non-negative integer")


def _monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


__all__ = [
    "PersistentServiceComposition",
    "PersistentServiceStartup",
    "PersistentServiceStartupError",
    "PersistentShadowRuntimeAdapter",
    "PersistentStopEvent",
    "SingleInstanceLease",
    "build_persistent_service_composition",
    "generate_runtime_identity",
    "prepare_persistent_service_startup",
    "run_persistent_service",
    "run_persistent_service_composition",
]
