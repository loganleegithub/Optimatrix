from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import subprocess
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, cast

from market_monitor import ContinuityGap
from market_monitor.types import SourceDataError
from short_vol_radar.evidence import EvidenceError, EvidenceWriter
from short_vol_underwriting import canonical_identity
from short_vol_underwriting.constants import (
    OUTCOME_CONTRACT_DIGEST,
    UNDERWRITING_POSITION_CONTRACT_DIGEST,
)
from short_vol_underwriting.evidence import (
    DownstreamEvidenceError,
    DownstreamEvidenceWriter,
    RuntimeBindings,
)
from short_vol_underwriting.identity import require_identity
from short_vol_underwriting.manifest import ValidatedManifest, load_manifest_bytes
from short_vol_underwriting.owner import FixedContractShadowOwner
from short_vol_underwriting.policy import (
    PolicyChain,
    PolicyChainError,
    load_policy_chain,
)
from websockets.exceptions import WebSocketException

from radar_runtime.deribit_public import (
    DeribitPublicClient,
    PublicProtocolError,
    PublicProtocolIncompatibility,
    PublicSessionError,
)
from radar_runtime.fixed_contract_shadow import FixedContractShadowRuntimeAdapter
from radar_runtime.identity import StartupGuardError, validate_clean_git_outputs
from radar_runtime.runtime import (
    LiveRadarRuntime,
    PublicClient,
    ShadowRuntimeIntegrityError,
    ShadowSupervisorTriggers,
    reconnect_delay_seconds,
)

GitRunner = Callable[[Path, Sequence[str]], str]
MonotonicClock = Callable[[], int]
SignalRegistrar = Callable[[signal.Signals, Callable[[], None]], None]
AsyncSleep = Callable[[float], Awaitable[None]]


class ShadowClientFactory(Protocol):
    def __call__(
        self,
        *,
        session_epoch: int,
        rpc_deadline_ms: int,
    ) -> AbstractAsyncContextManager[PublicClient]: ...


class ShadowStartupError(StartupGuardError):
    """The fixed-contract Shadow process is not bound to one closed startup graph."""


@dataclass(frozen=True)
class ShadowStartup:
    manifest: ValidatedManifest
    manifest_path: Path
    policy_chain: PolicyChain
    bindings: RuntimeBindings
    repository: Path
    code_identity: str
    runtime_identity: str
    supervisor_clock_identity: str
    outcome_contract_identity: str
    outcome_contract_path: Path
    radar_policy_path: Path
    underwriting_policy_path: Path
    position_policy_path: Path
    downstream_evidence_directory: Path
    radar_evidence_directory: Path
    process_argv: tuple[str, ...]
    process_cwd: Path


@dataclass(frozen=True)
class ShadowComposition:
    startup: ShadowStartup
    manifest_path: Path
    downstream_writer: DownstreamEvidenceWriter
    owner: FixedContractShadowOwner
    adapter: FixedContractShadowRuntimeAdapter
    radar_writer: EvidenceWriter
    runtime: LiveRadarRuntime


@dataclass(frozen=True)
class ShadowTerminalControl:
    disposition: str
    source: Mapping[str, object]


class ShadowStopController:
    """Latch external stop controls without directly committing a business boundary."""

    def __init__(self, manifest: ValidatedManifest) -> None:
        self.manifest = manifest
        self._emergency_reason: str | None = None
        self._fatal_source_identity: str | None = None
        self._fatal_kind: str | None = None

    def latch_signal(self, signum: signal.Signals, *, monotonic_ms: int) -> bool:
        if self._emergency_reason is not None:
            return False
        reasons = {
            signal.SIGINT: "USER_REQUEST",
            signal.SIGTERM: "EXTERNAL_SAFETY_STOP",
        }
        try:
            reason = reasons[signal.Signals(signum)]
        except (KeyError, ValueError) as exc:
            raise ValueError("unsupported Shadow stop signal") from exc
        _require_monotonic_ms(monotonic_ms)
        self._emergency_reason = reason
        return True

    def latch_fatal(
        self,
        *,
        failure_source_identity: str,
        monotonic_ms: int,
        failure_kind: str,
    ) -> bool:
        if self._fatal_source_identity is not None:
            return False
        require_identity(failure_source_identity, "failure_source_identity")
        _require_monotonic_ms(monotonic_ms)
        if failure_kind not in {"FATAL_RUNTIME", "FATAL_EVIDENCE_INTEGRITY"}:
            raise ValueError("unsupported Shadow fatal failure kind")
        self._fatal_source_identity = failure_source_identity
        self._fatal_kind = failure_kind
        return True

    def terminal_control(self, *, monotonic_ms: int) -> ShadowTerminalControl | None:
        _require_monotonic_ms(monotonic_ms)
        if self._fatal_source_identity is not None:
            return ShadowTerminalControl(
                disposition="PROCESS_FAILURE",
                source={
                    "runtime_identity": self.manifest.runtime_identity,
                    "supervisor_clock_identity": self.manifest.supervisor_clock_identity,
                    "failure_source_identity": self._fatal_source_identity,
                    "control_monotonic_ms": monotonic_ms,
                    "control_kind": "PROCESS_FAILURE",
                    "failure_kind": self._fatal_kind,
                },
            )
        if self._emergency_reason is not None:
            return ShadowTerminalControl(
                disposition="AUTHORIZED_EMERGENCY_STOP",
                source={
                    "runtime_identity": self.manifest.runtime_identity,
                    "supervisor_clock_identity": self.manifest.supervisor_clock_identity,
                    "authority_identity": self.manifest.value["emergency_stop_authority"],
                    "control_monotonic_ms": monotonic_ms,
                    "control_kind": "AUTHORIZED_EMERGENCY_STOP",
                    "reason": self._emergency_reason,
                },
            )
        final_trigger = _manifest_mapping(self.manifest, "final_stop_trigger")
        if monotonic_ms < _trigger_monotonic_ms(final_trigger):
            return None
        return ShadowTerminalControl(
            disposition="PLANNED_CLEAN_STOP",
            source=dict(final_trigger),
        )


class ShadowStopEvent(asyncio.Event):
    """Carry the exact already-latched terminal boundary into the runtime drain."""

    def __init__(self) -> None:
        super().__init__()
        self._terminal_monotonic_ms: int | None = None

    @property
    def terminal_monotonic_ms(self) -> int | None:
        return self._terminal_monotonic_ms

    def request(self, *, terminal_monotonic_ms: int) -> None:
        _require_monotonic_ms(terminal_monotonic_ms)
        if self._terminal_monotonic_ms is not None:
            return
        self._terminal_monotonic_ms = terminal_monotonic_ms
        self.set()


@dataclass(frozen=True)
class _LoadedShadowInputs:
    manifest: ValidatedManifest
    manifest_path: Path
    policies: PolicyChain
    bindings: RuntimeBindings
    repository: Path
    outcome_contract_path: Path
    radar_policy_path: Path
    underwriting_policy_path: Path
    position_policy_path: Path
    process_argv: tuple[str, ...]
    process_cwd: Path


def build_shadow_composition(startup: ShadowStartup) -> ShadowComposition:
    """Construct the one-process downstream graph without creating a transport client."""
    manifest_path = publish_shadow_manifest(startup)
    downstream_writer = DownstreamEvidenceWriter(
        startup.downstream_evidence_directory,
        bindings=startup.bindings,
    )
    owner = FixedContractShadowOwner(
        policies=startup.policy_chain,
        bindings=startup.bindings,
        writer=downstream_writer,
    )
    adapter = FixedContractShadowRuntimeAdapter(
        owner=owner,
        manifest=startup.manifest,
    )
    radar_writer = EvidenceWriter(
        startup.radar_evidence_directory,
        code_identity=startup.code_identity,
        runtime_identity=startup.runtime_identity,
        policy_identity=startup.policy_chain.radar.identity,
    )
    runtime = LiveRadarRuntime(
        policy=startup.policy_chain.radar,
        code_identity=startup.code_identity,
        evidence_writer=radar_writer,
        runtime_identity=startup.runtime_identity,
        shadow_adapter=adapter,
    )
    return ShadowComposition(
        startup=startup,
        manifest_path=manifest_path,
        downstream_writer=downstream_writer,
        owner=owner,
        adapter=adapter,
        radar_writer=radar_writer,
        runtime=runtime,
    )


def install_shadow_signal_handlers(
    controller: ShadowStopController,
    *,
    monotonic_ms: MonotonicClock,
    registrar: SignalRegistrar | None = None,
) -> None:
    register = registrar or asyncio.get_running_loop().add_signal_handler
    for signum in (signal.SIGINT, signal.SIGTERM):

        def handle_signal(member: signal.Signals = signum) -> None:
            controller.latch_signal(
                member,
                monotonic_ms=monotonic_ms(),
            )

        try:
            register(signum, handle_signal)
        except NotImplementedError:
            pass


async def observe_shadow(
    composition: ShadowComposition,
    *,
    client_factory: ShadowClientFactory | None = None,
    monotonic_ms: MonotonicClock | None = None,
    signal_registrar: SignalRegistrar | None = None,
    sleep: AsyncSleep = asyncio.sleep,
) -> Path:
    """Drive one fixed-contract Shadow composition without adding another transport."""
    clock = monotonic_ms or _monotonic_ms
    controller = ShadowStopController(composition.startup.manifest)
    install_shadow_signal_handlers(
        controller,
        monotonic_ms=clock,
        registrar=signal_registrar,
    )
    stop_event = ShadowStopEvent()
    triggers = ShadowSupervisorTriggers(
        runtime_start_monotonic_ms=_trigger_monotonic_ms(
            _manifest_mapping(composition.startup.manifest, "runtime_start_trigger")
        ),
        enrollment_cutoff_monotonic_ms=_trigger_monotonic_ms(
            _manifest_mapping(
                composition.startup.manifest,
                "enrollment_cutoff_trigger",
            )
        ),
        final_stop_monotonic_ms=_trigger_monotonic_ms(
            _manifest_mapping(composition.startup.manifest, "final_stop_trigger")
        ),
    )

    def commit_terminal_gate(observed_monotonic_ms: int) -> None:
        _commit_shadow_terminal_gate(
            composition=composition,
            controller=controller,
            stop_event=stop_event,
            observed_monotonic_ms=observed_monotonic_ms,
        )

    supervisor_task = asyncio.create_task(
        _supervise_shadow_terminal(
            composition=composition,
            controller=controller,
            stop_event=stop_event,
            monotonic_ms=clock,
            sleep=sleep,
        ),
        name="fixed-contract-shadow-supervisor",
    )
    create_client = client_factory or _deribit_client_factory
    reconnect_attempt = 0
    session_epoch = 0
    try:
        while True:
            completed_summary_path: Path | None = None
            if stop_event.is_set() and composition.runtime.reducer._session_epoch is None:
                terminal_monotonic_ms = stop_event.terminal_monotonic_ms
                if terminal_monotonic_ms is None:
                    raise RuntimeError("latched Shadow stop lost its exact boundary")
                return composition.runtime.clean_stop_without_transport(
                    session_epoch=max(1, session_epoch),
                    terminal_monotonic_ms=terminal_monotonic_ms,
                    shadow_supervisor_triggers=triggers,
                )
            try:
                if stop_event.is_set() and composition.runtime.reducer._session_epoch is not None:
                    terminal_monotonic_ms = stop_event.terminal_monotonic_ms
                    if terminal_monotonic_ms is None:
                        raise RuntimeError("latched Shadow stop lost its exact boundary")
                    return composition.runtime.reducer.clean_stop(terminal_monotonic_ms)
                session_epoch += 1
                async with create_client(
                    session_epoch=session_epoch,
                    rpc_deadline_ms=(
                        composition.startup.policy_chain.radar.runtime_limits.rpc_deadline_ms
                    ),
                ) as client:
                    run_task = asyncio.create_task(
                        composition.runtime.run(
                            client,
                            stop_event,
                            shadow_supervisor_triggers=triggers,
                            shadow_terminal_gate=commit_terminal_gate,
                        ),
                        name="fixed-contract-shadow-session",
                    )
                    done, _ = await asyncio.wait(
                        (run_task, supervisor_task),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if supervisor_task in done:
                        supervisor_error = supervisor_task.exception()
                        if supervisor_error is not None:
                            run_task.cancel()
                            with suppress(asyncio.CancelledError):
                                await run_task
                            raise supervisor_error
                    completed_summary_path = await run_task
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
                if completed_summary_path is not None and stop_event.is_set():
                    return completed_summary_path
                if stop_event.is_set():
                    _finalize_shadow_failure(
                        composition=composition,
                        controller=controller,
                        stop_event=stop_event,
                        failure=exc,
                        monotonic_ms=clock(),
                    )
                    raise
                if composition.runtime.session_established:
                    reconnect_attempt = 0
                await sleep(
                    reconnect_delay_seconds(
                        reconnect_attempt,
                        base_delay_ms=(
                            composition.startup.policy_chain.radar.runtime_limits.time_boundary_poll_interval_ms
                        ),
                        maximum_delay_ms=(
                            composition.startup.policy_chain.radar.runtime_limits.rpc_deadline_ms
                        ),
                    )
                )
                reconnect_attempt += 1
            except (PublicProtocolIncompatibility, PublicProtocolError) as exc:
                _finalize_shadow_failure(
                    composition=composition,
                    controller=controller,
                    stop_event=stop_event,
                    failure=exc,
                    monotonic_ms=clock(),
                )
                raise
            except Exception as exc:
                _finalize_shadow_failure(
                    composition=composition,
                    controller=controller,
                    stop_event=stop_event,
                    failure=exc,
                    monotonic_ms=clock(),
                )
                raise
    finally:
        if not supervisor_task.done():
            supervisor_task.cancel()
        with suppress(asyncio.CancelledError):
            await supervisor_task


async def _supervise_shadow_terminal(
    *,
    composition: ShadowComposition,
    controller: ShadowStopController,
    stop_event: ShadowStopEvent,
    monotonic_ms: MonotonicClock,
    sleep: AsyncSleep,
) -> None:
    poll_seconds = (
        composition.startup.policy_chain.radar.runtime_limits.time_boundary_poll_interval_ms / 1_000
    )
    while not stop_event.is_set():
        now_ms = monotonic_ms()
        terminal = controller.terminal_control(monotonic_ms=now_ms)
        if terminal is not None:
            _commit_shadow_terminal_gate(
                composition=composition,
                controller=controller,
                stop_event=stop_event,
                observed_monotonic_ms=now_ms,
            )
            return
        await sleep(poll_seconds)


def _commit_shadow_terminal_gate(
    *,
    composition: ShadowComposition,
    controller: ShadowStopController,
    stop_event: ShadowStopEvent,
    observed_monotonic_ms: int,
) -> None:
    _require_monotonic_ms(observed_monotonic_ms)
    if stop_event.is_set():
        return
    terminal = controller.terminal_control(monotonic_ms=observed_monotonic_ms)
    if terminal is None:
        raise RuntimeError("Shadow terminal gate fired before any authorized terminal source")
    composition.runtime.configure_shadow_terminal_control(
        terminal_disposition=terminal.disposition,
        terminal_source=terminal.source,
    )
    stop_event.request(terminal_monotonic_ms=observed_monotonic_ms)


def _finalize_shadow_failure(
    *,
    composition: ShadowComposition,
    controller: ShadowStopController,
    stop_event: ShadowStopEvent,
    failure: Exception,
    monotonic_ms: int,
) -> None:
    _require_monotonic_ms(monotonic_ms)
    if composition.runtime.shadow_terminalized:
        return
    failure_kind = (
        "FATAL_EVIDENCE_INTEGRITY"
        if isinstance(
            failure,
            (
                DownstreamEvidenceError,
                EvidenceError,
                ShadowRuntimeIntegrityError,
            ),
        )
        else "FATAL_RUNTIME"
    )
    controller.latch_fatal(
        failure_source_identity=canonical_identity(
            "RadarRuntimeFailureSourceIdentity",
            {
                "exception_module": type(failure).__module__,
                "exception_class": type(failure).__qualname__,
                "message": str(failure),
            },
        ),
        monotonic_ms=monotonic_ms,
        failure_kind=failure_kind,
    )
    terminal = controller.terminal_control(monotonic_ms=monotonic_ms)
    if terminal is None or terminal.disposition != "PROCESS_FAILURE":
        raise RuntimeError("fatal Shadow failure did not own the terminal control")
    composition.runtime.configure_shadow_terminal_control(
        terminal_disposition=terminal.disposition,
        terminal_source=terminal.source,
    )
    stop_event.request(terminal_monotonic_ms=monotonic_ms)
    composition.runtime.finalize_shadow_failure(monotonic_ms)


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


def prepare_shadow_startup(
    *,
    manifest_path: Path,
    radar_evidence_directory: Path,
    process_argv: Sequence[str],
    process_cwd: Path,
    git_runner: GitRunner | None = None,
) -> ShadowStartup:
    """Validate immutable inputs first, then Git/remote identity and new directories.

    This function does not construct a client or perform any Deribit I/O. The only
    network-capable operation is the required read-only ``git ls-remote`` preflight.
    """

    loaded = _load_shadow_inputs(
        manifest_path=manifest_path,
        process_argv=process_argv,
        process_cwd=process_cwd,
    )
    run_git = git_runner or _run_git
    _validate_repository_identity(loaded, run_git)
    downstream, radar = _prepare_distinct_evidence_directories(
        downstream_directory=loaded.manifest.evidence_directory,
        radar_directory=radar_evidence_directory,
        repository=loaded.repository,
    )
    return ShadowStartup(
        manifest=loaded.manifest,
        manifest_path=loaded.manifest_path,
        policy_chain=loaded.policies,
        bindings=loaded.bindings,
        repository=loaded.repository,
        code_identity=loaded.manifest.candidate_commit,
        runtime_identity=loaded.manifest.runtime_identity,
        supervisor_clock_identity=loaded.manifest.supervisor_clock_identity,
        outcome_contract_identity=loaded.bindings.outcome_contract_identity,
        outcome_contract_path=loaded.outcome_contract_path,
        radar_policy_path=loaded.radar_policy_path,
        underwriting_policy_path=loaded.underwriting_policy_path,
        position_policy_path=loaded.position_policy_path,
        downstream_evidence_directory=downstream,
        radar_evidence_directory=radar,
        process_argv=loaded.process_argv,
        process_cwd=loaded.process_cwd,
    )


def publish_shadow_manifest(startup: ShadowStartup) -> Path:
    """Publish the already validated exact manifest bytes at the evidence root."""
    try:
        exact_bytes = startup.manifest_path.read_bytes()
    except OSError as exc:
        raise ShadowStartupError("cannot reread exact Shadow manifest for publication") from exc
    validated = load_manifest_bytes(exact_bytes)
    if (
        validated.manifest_identity != startup.manifest.manifest_identity
        or validated.value != startup.manifest.value
    ):
        raise ShadowStartupError("Shadow manifest changed after preflight")
    destination = startup.downstream_evidence_directory / "manifest.json"
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        created = True
        view = memoryview(exact_bytes)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short manifest write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        directory_descriptor = os.open(
            startup.downstream_evidence_directory,
            os.O_RDONLY,
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                destination.unlink()
            except OSError:
                pass
        raise ShadowStartupError("cannot exclusively publish manifest.json") from exc
    return destination


def _load_shadow_inputs(
    *,
    manifest_path: Path,
    process_argv: Sequence[str],
    process_cwd: Path,
) -> _LoadedShadowInputs:
    try:
        exact_manifest = manifest_path.read_bytes()
    except OSError as exc:
        raise ShadowStartupError(f"cannot read Shadow manifest: {manifest_path}") from exc
    manifest = load_manifest_bytes(exact_manifest)
    expected_argv = _string_sequence(manifest.value["process_argv"], "manifest process_argv")
    actual_argv = _string_sequence(process_argv, "actual process_argv")
    if actual_argv != expected_argv:
        raise ShadowStartupError("actual process argv does not equal manifest process_argv")
    if not process_cwd.is_absolute() or str(process_cwd) != manifest.value["process_cwd"]:
        raise ShadowStartupError("actual process cwd does not equal manifest process_cwd")

    repository = process_cwd.resolve()
    outcome_contract_path = _exact_repository_file(
        repository,
        _manifest_path(manifest, "outcome_contract_path"),
        "Outcome contract",
    )
    _verify_exact_digest(
        outcome_contract_path,
        OUTCOME_CONTRACT_DIGEST,
        "Outcome contract",
    )
    radar_policy_path = _exact_repository_file(
        repository,
        _manifest_path(manifest, "radar_policy_path"),
        "Radar Policy",
    )
    underwriting_policy_path = _exact_repository_file(
        repository,
        _manifest_path(manifest, "underwriting_policy_path"),
        "Underwriting Policy",
    )
    position_policy_path = _exact_repository_file(
        repository,
        _manifest_path(manifest, "position_policy_path"),
        "Position Policy",
    )
    try:
        policies = load_policy_chain(
            radar_path=radar_policy_path,
            underwriting_path=underwriting_policy_path,
            position_path=position_policy_path,
            radar_identity=_manifest_string(manifest, "radar_policy_identity"),
            underwriting_identity=_manifest_string(
                manifest,
                "underwriting_policy_identity",
            ),
            position_identity=_manifest_string(manifest, "position_policy_identity"),
        )
    except PolicyChainError as exc:
        raise ShadowStartupError(f"Policy preflight failed: {exc}") from exc
    bindings = RuntimeBindings(
        code_identity=manifest.candidate_commit,
        runtime_identity=manifest.runtime_identity,
        radar_policy_identity=policies.radar.identity,
        underwriting_policy_identity=policies.underwriting.identity,
        position_policy_identity=policies.position.identity,
        underwriting_position_contract_digest=UNDERWRITING_POSITION_CONTRACT_DIGEST,
        outcome_contract_digest=OUTCOME_CONTRACT_DIGEST,
    )
    manifest_contract_identity = _manifest_string(manifest, "outcome_contract_identity")
    if bindings.outcome_contract_identity != manifest_contract_identity:
        raise ShadowStartupError("manifest and runtime bindings have mixed Outcome identity")
    return _LoadedShadowInputs(
        manifest=manifest,
        manifest_path=manifest_path.resolve(),
        policies=policies,
        bindings=bindings,
        repository=repository,
        outcome_contract_path=outcome_contract_path,
        radar_policy_path=radar_policy_path,
        underwriting_policy_path=underwriting_policy_path,
        position_policy_path=position_policy_path,
        process_argv=actual_argv,
        process_cwd=process_cwd,
    )


def _validate_repository_identity(
    loaded: _LoadedShadowInputs,
    git_runner: GitRunner,
) -> None:
    repository = loaded.repository
    root_output = git_runner(repository, ("rev-parse", "--show-toplevel")).strip()
    if not root_output or Path(root_output).resolve() != repository:
        raise ShadowStartupError("manifest process cwd must be the exact Git repository root")
    head_output = git_runner(repository, ("rev-parse", "HEAD"))
    status_output = git_runner(
        repository,
        ("status", "--porcelain", "--untracked-files=all"),
    )
    try:
        head = validate_clean_git_outputs(
            head_output=head_output,
            status_output=status_output,
        )
    except StartupGuardError as exc:
        raise ShadowStartupError(str(exc)) from exc
    if head != loaded.manifest.candidate_commit:
        raise ShadowStartupError("Git HEAD does not equal manifest candidate_commit")
    candidate = loaded.manifest.candidate_commit
    git_runner(repository, ("cat-file", "-e", f"{candidate}^{{commit}}"))
    tree = git_runner(repository, ("rev-parse", f"{candidate}^{{tree}}")).strip()
    if tree != loaded.manifest.candidate_tree:
        raise ShadowStartupError("Git candidate tree does not equal manifest candidate_tree")
    intended_ref = loaded.manifest.intended_remote_ref
    remote_output = git_runner(
        repository,
        ("ls-remote", "--exit-code", "origin", intended_ref),
    )
    expected_remote_line = f"{candidate}\t{intended_ref}"
    if remote_output.splitlines() != [expected_remote_line]:
        raise ShadowStartupError("fresh remote ref does not equal manifest verified_remote_ref")


def _prepare_distinct_evidence_directories(
    *,
    downstream_directory: Path,
    radar_directory: Path,
    repository: Path,
) -> tuple[Path, Path]:
    downstream = _validate_new_evidence_path(
        downstream_directory,
        repository,
        "downstream",
    )
    radar = _validate_new_evidence_path(radar_directory, repository, "Radar")
    if downstream == radar or downstream in radar.parents or radar in downstream.parents:
        raise ShadowStartupError(
            "downstream and Radar evidence directories must be distinct and non-overlapping"
        )
    created: list[Path] = []
    try:
        for directory in (downstream, radar):
            directory.mkdir(parents=True, exist_ok=False)
            created.append(directory)
    except OSError as exc:
        for directory in reversed(created):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise ShadowStartupError("cannot create new empty evidence directories") from exc
    return downstream, radar


def _validate_new_evidence_path(
    directory: Path,
    repository: Path,
    label: str,
) -> Path:
    if not directory.is_absolute():
        raise ShadowStartupError(f"{label} evidence directory must be absolute")
    resolved = directory.resolve()
    if resolved == repository or repository in resolved.parents:
        raise ShadowStartupError(f"{label} evidence directory must stay outside the worktree")
    if directory.is_symlink() or directory.exists():
        raise ShadowStartupError(f"{label} evidence directory must be new and empty")
    return resolved


def _exact_repository_file(
    repository: Path,
    relative: PurePosixPath,
    label: str,
) -> Path:
    lexical = repository.joinpath(*relative.parts)
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ShadowStartupError(f"cannot read exact {label} path") from exc
    if resolved != lexical or not resolved.is_file():
        raise ShadowStartupError(f"{label} must use its exact repository path without aliases")
    return resolved


def _verify_exact_digest(path: Path, expected_identity: str, label: str) -> None:
    try:
        exact_bytes = path.read_bytes()
    except OSError as exc:
        raise ShadowStartupError(f"cannot read {label}") from exc
    actual = f"sha256:{hashlib.sha256(exact_bytes).hexdigest()}"
    if actual != expected_identity:
        raise ShadowStartupError(f"{label} digest mismatch")


def _manifest_path(manifest: ValidatedManifest, field: str) -> PurePosixPath:
    return PurePosixPath(_manifest_string(manifest, field))


def _manifest_string(manifest: ValidatedManifest, field: str) -> str:
    value = manifest.value[field]
    if not isinstance(value, str):
        raise ShadowStartupError(f"validated manifest {field} is not a string")
    return value


def _manifest_mapping(
    manifest: ValidatedManifest,
    field: str,
) -> Mapping[str, object]:
    value = manifest.value[field]
    if not isinstance(value, Mapping):
        raise ShadowStartupError(f"validated manifest {field} is not an object")
    return value


def _trigger_monotonic_ms(trigger: Mapping[str, object]) -> int:
    value = trigger.get("trigger_monotonic_ms")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ShadowStartupError("validated manifest trigger time is invalid")
    return value


def _require_monotonic_ms(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("monotonic time must be a non-negative integer")


def _string_sequence(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray, str)):
        raise ShadowStartupError(f"{field} must be a string sequence")
    result = tuple(value)
    if not result or any(not isinstance(member, str) or not member for member in result):
        raise ShadowStartupError(f"{field} must be a non-empty string sequence")
    return result


def _run_git(repository: Path, arguments: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ShadowStartupError(f"Git preflight failed: {' '.join(arguments)}") from exc
    return completed.stdout


def _monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000
