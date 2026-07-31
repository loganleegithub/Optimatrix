from __future__ import annotations

import asyncio
import json
import shutil
import signal
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import pytest
import radar_runtime.__main__ as cli_module
import radar_runtime.shadow as shadow_module
from radar_runtime.deribit_public import (
    InboundEnvelope,
    PublicSessionError,
    SendControlEvent,
)
from radar_runtime.runtime import (
    PublicClient,
    ShadowRuntimeIntegrityError,
    ShadowSupervisorControlKind,
    ShadowSupervisorTriggers,
)
from radar_runtime.shadow import (
    ShadowStartup,
    ShadowStartupError,
    ShadowStopController,
    ShadowStopEvent,
    build_shadow_composition,
    install_shadow_signal_handlers,
    observe_shadow,
    prepare_shadow_startup,
    publish_shadow_manifest,
)
from short_vol_underwriting import (
    ManifestError,
    canonical_identity,
    read_current_evidence,
)
from short_vol_underwriting.constants import (
    OUTCOME_CONTRACT_DIGEST,
    POSITION_POLICY_IDENTITY,
    RADAR_POLICY_IDENTITY,
    UNDERWRITING_POLICY_IDENTITY,
)
from short_vol_underwriting.evidence import _read_complete_evidence_with_git_reader

ROOT = Path(__file__).resolve().parents[1]
TASK_REF = "refs/heads/codex/short-vol-fixed-contract-public-shadow-runtime"
CANDIDATE = "a" * 40
TREE = "b" * 40
RUNTIME = "sha256:" + "c" * 64
CLOCK = "sha256:" + "d" * 64


class FakeGit:
    def __init__(
        self,
        *,
        repository: Path,
        status: str = "",
        head: str = CANDIDATE,
        tree: str = TREE,
        remote_commit: str = CANDIDATE,
    ) -> None:
        self.repository = repository.resolve()
        self.status = status
        self.head = head
        self.tree = tree
        self.remote_commit = remote_commit
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, repository: Path, arguments: Sequence[str]) -> str:
        assert repository.resolve() == self.repository
        command = tuple(arguments)
        self.calls.append(command)
        outputs = {
            ("rev-parse", "--show-toplevel"): f"{self.repository}\n",
            ("rev-parse", "HEAD"): f"{self.head}\n",
            ("status", "--porcelain", "--untracked-files=all"): self.status,
            ("cat-file", "-e", f"{CANDIDATE}^{{commit}}"): "",
            ("rev-parse", f"{CANDIDATE}^{{tree}}"): f"{self.tree}\n",
            ("ls-remote", "--exit-code", "origin", TASK_REF): (
                f"{self.remote_commit}\t{TASK_REF}\n"
            ),
        }
        try:
            return outputs[command]
        except KeyError as exc:  # pragma: no cover - makes unexpected subprocess shape obvious
            raise AssertionError(f"unexpected Git command: {command}") from exc


def _trigger(kind: str, at: int) -> dict[str, object]:
    return {
        "runtime_identity": RUNTIME,
        "supervisor_clock_identity": CLOCK,
        "trigger_monotonic_ms": at,
        "trigger_kind": kind,
    }


def _manifest_value(
    *,
    repository: Path,
    downstream_directory: Path,
    process_argv: Sequence[str],
) -> dict[str, object]:
    return {
        "manifest_content_schema_identity": canonical_identity(
            "SHORT_VOL_SHADOW_FORWARD_COHORT_MANIFEST_SCHEMA",
            OUTCOME_CONTRACT_DIGEST,
        ),
        "candidate_commit": CANDIDATE,
        "candidate_tree": TREE,
        "intended_remote_ref": TASK_REF,
        "verified_remote_ref": CANDIDATE,
        "outcome_contract_identity": canonical_identity(
            "OUTCOME_CONTRACT",
            "SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT",
            OUTCOME_CONTRACT_DIGEST,
            CANDIDATE,
            RADAR_POLICY_IDENTITY,
            UNDERWRITING_POLICY_IDENTITY,
            POSITION_POLICY_IDENTITY,
        ),
        "outcome_contract_path": "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md",
        "radar_policy_path": "policies/short-vol-fixed-public-shadow-radar.json",
        "radar_policy_identity": RADAR_POLICY_IDENTITY,
        "underwriting_policy_path": "policies/short-vol-fixed-public-shadow-underwriting.json",
        "underwriting_policy_identity": UNDERWRITING_POLICY_IDENTITY,
        "position_policy_path": "policies/short-vol-fixed-public-shadow-position.json",
        "position_policy_identity": POSITION_POLICY_IDENTITY,
        "evidence_directory": str(downstream_directory),
        "process_argv": list(process_argv),
        "process_cwd": str(repository),
        "required_pre_run_checks": ["make check"],
        "runtime_start_trigger": _trigger("RUNTIME_START", 1),
        "enrollment_cutoff_trigger": _trigger("ENROLLMENT_CUTOFF", 2),
        "final_stop_trigger": _trigger("FINAL_STOP", 3),
        "clean_stop_predicate": "final stop trigger accepted independent of results",
        "emergency_stop_authority": "sha256:" + "e" * 64,
        "forbidden_capabilities": [
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
        ],
        "non_claims": [
            "sha256:" + "3" * 64,
            "sha256:" + "4" * 64,
        ],
    }


def _write_manifest(path: Path, value: dict[str, object]) -> None:
    exact = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    path.write_bytes((exact + "\n").encode())


def _copy_startup_files(repository: Path) -> None:
    for relative in (
        "docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md",
        "policies/short-vol-fixed-public-shadow-radar.json",
        "policies/short-vol-fixed-public-shadow-underwriting.json",
        "policies/short-vol-fixed-public-shadow-position.json",
    ):
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


def _startup(
    tmp_path: Path,
    *,
    process_argv: Sequence[str] = ("python", "-m", "radar_runtime", "observe-shadow"),
) -> ShadowStartup:
    downstream = tmp_path / "downstream"
    radar = tmp_path / "radar"
    manifest_path = tmp_path / "cohort-manifest.json"
    _write_manifest(
        manifest_path,
        _manifest_value(
            repository=ROOT,
            downstream_directory=downstream,
            process_argv=process_argv,
        ),
    )
    return prepare_shadow_startup(
        manifest_path=manifest_path,
        radar_evidence_directory=radar,
        process_argv=process_argv,
        process_cwd=ROOT,
        git_runner=FakeGit(repository=ROOT),
    )


def test_shadow_preflight_binds_exact_manifest_policy_git_and_directories(
    tmp_path: Path,
) -> None:
    downstream = tmp_path / "downstream"
    radar = tmp_path / "radar"
    manifest_path = tmp_path / "cohort-manifest.json"
    argv = (
        "python",
        "-m",
        "radar_runtime",
        "observe-shadow",
        "--manifest",
        str(manifest_path),
        "--radar-evidence-dir",
        str(radar),
    )
    _write_manifest(
        manifest_path,
        _manifest_value(
            repository=ROOT,
            downstream_directory=downstream,
            process_argv=argv,
        ),
    )
    git = FakeGit(repository=ROOT)

    startup = prepare_shadow_startup(
        manifest_path=manifest_path,
        radar_evidence_directory=radar,
        process_argv=argv,
        process_cwd=ROOT,
        git_runner=git,
    )

    assert startup.code_identity == CANDIDATE
    assert startup.runtime_identity == RUNTIME
    assert startup.policy_chain.identities == (
        RADAR_POLICY_IDENTITY,
        UNDERWRITING_POLICY_IDENTITY,
        POSITION_POLICY_IDENTITY,
    )
    assert startup.bindings.outcome_contract_identity == startup.outcome_contract_identity
    assert startup.downstream_evidence_directory == downstream.resolve()
    assert startup.radar_evidence_directory == radar.resolve()
    assert downstream.is_dir()
    assert radar.is_dir()
    assert git.calls[-1] == ("ls-remote", "--exit-code", "origin", TASK_REF)


def test_shadow_manifest_is_published_exactly_once_after_preflight(tmp_path: Path) -> None:
    downstream = tmp_path / "downstream"
    radar = tmp_path / "radar"
    manifest_path = tmp_path / "cohort-manifest.json"
    argv = ("python", "-m", "radar_runtime", "observe-shadow")
    _write_manifest(
        manifest_path,
        _manifest_value(
            repository=ROOT,
            downstream_directory=downstream,
            process_argv=argv,
        ),
    )
    exact_bytes = manifest_path.read_bytes()
    startup = prepare_shadow_startup(
        manifest_path=manifest_path,
        radar_evidence_directory=radar,
        process_argv=argv,
        process_cwd=ROOT,
        git_runner=FakeGit(repository=ROOT),
    )

    published = publish_shadow_manifest(startup)

    assert published == downstream / "manifest.json"
    assert published.read_bytes() == exact_bytes
    with pytest.raises(ShadowStartupError, match="exclusively"):
        publish_shadow_manifest(startup)
    assert published.read_bytes() == exact_bytes


def test_shadow_composition_constructs_every_owner_before_transport_is_possible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup = _startup(tmp_path)
    events: list[str] = []

    class FakeDownstreamWriter:
        def __init__(self, directory: Path, *, bindings: object) -> None:
            events.append("downstream-writer")

    class FakeOwner:
        def __init__(self, *, policies: object, bindings: object, writer: object) -> None:
            events.append("owner")

    class FakeAdapter:
        def __init__(self, *, owner: object, manifest: object) -> None:
            events.append("adapter")

    class FakeRadarWriter:
        def __init__(
            self,
            directory: Path,
            *,
            code_identity: str,
            runtime_identity: str,
            policy_identity: str,
        ) -> None:
            events.append("radar-writer")

    class FakeRuntime:
        def __init__(
            self,
            *,
            policy: object,
            code_identity: str,
            evidence_writer: object,
            runtime_identity: str,
            shadow_adapter: object,
        ) -> None:
            events.append("runtime")

    real_publish = shadow_module.publish_shadow_manifest

    def record_publish(value: ShadowStartup) -> Path:
        events.append("manifest")
        return real_publish(value)

    monkeypatch.setattr(shadow_module, "publish_shadow_manifest", record_publish)
    monkeypatch.setattr(shadow_module, "DownstreamEvidenceWriter", FakeDownstreamWriter)
    monkeypatch.setattr(shadow_module, "FixedContractShadowOwner", FakeOwner)
    monkeypatch.setattr(shadow_module, "FixedContractShadowRuntimeAdapter", FakeAdapter)
    monkeypatch.setattr(shadow_module, "EvidenceWriter", FakeRadarWriter)
    monkeypatch.setattr(shadow_module, "LiveRadarRuntime", FakeRuntime)

    composition = build_shadow_composition(startup)

    assert events == [
        "manifest",
        "downstream-writer",
        "owner",
        "adapter",
        "radar-writer",
        "runtime",
    ]
    assert composition.startup is startup
    assert composition.manifest_path == startup.downstream_evidence_directory / "manifest.json"


@pytest.mark.parametrize(
    ("signum", "reason"),
    [
        (signal.SIGINT, "USER_REQUEST"),
        (signal.SIGTERM, "EXTERNAL_SAFETY_STOP"),
    ],
)
def test_shadow_signal_is_only_a_first_latched_external_control(
    tmp_path: Path,
    signum: signal.Signals,
    reason: str,
) -> None:
    startup = _startup(tmp_path)
    controller = ShadowStopController(startup.manifest)
    registered: dict[signal.Signals, Callable[[], None]] = {}

    install_shadow_signal_handlers(
        controller,
        monotonic_ms=lambda: 7,
        registrar=lambda member, callback: registered.__setitem__(member, callback),
    )

    registered[signum]()
    registered[signal.SIGTERM if signum == signal.SIGINT else signal.SIGINT]()
    terminal = controller.terminal_control(monotonic_ms=8)

    assert set(registered) == {signal.SIGINT, signal.SIGTERM}
    assert terminal is not None
    assert terminal.disposition == "AUTHORIZED_EMERGENCY_STOP"
    assert terminal.source == {
        "runtime_identity": RUNTIME,
        "supervisor_clock_identity": CLOCK,
        "authority_identity": startup.manifest.value["emergency_stop_authority"],
        "control_monotonic_ms": 8,
        "control_kind": "AUTHORIZED_EMERGENCY_STOP",
        "reason": reason,
    }


def test_fatal_control_outranks_emergency_and_planned_stop(tmp_path: Path) -> None:
    startup = _startup(tmp_path)
    controller = ShadowStopController(startup.manifest)
    controller.latch_signal(signal.SIGINT, monotonic_ms=3)
    controller.latch_fatal(
        failure_source_identity="sha256:" + "f" * 64,
        monotonic_ms=3,
        failure_kind="FATAL_RUNTIME",
    )

    terminal = controller.terminal_control(monotonic_ms=30)

    assert terminal is not None
    assert terminal.disposition == "PROCESS_FAILURE"
    assert terminal.source["failure_source_identity"] == "sha256:" + "f" * 64
    assert terminal.source["control_kind"] == "PROCESS_FAILURE"


def test_planned_stop_is_not_available_before_exact_manifest_trigger(
    tmp_path: Path,
) -> None:
    startup = _startup(tmp_path)
    controller = ShadowStopController(startup.manifest)

    assert controller.terminal_control(monotonic_ms=2) is None
    terminal = controller.terminal_control(monotonic_ms=3)

    assert terminal is not None
    assert terminal.disposition == "PLANNED_CLEAN_STOP"
    assert terminal.source == startup.manifest.value["final_stop_trigger"]


def test_observe_shadow_creates_client_last_and_passes_exact_supervisor_triggers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composition = build_shadow_composition(_startup(tmp_path))
    summary_path = tmp_path / "radar-summary.json"
    events: list[str] = []

    class FakeClient:
        session_epoch = 1
        queue_high_water_frames = 0
        overflow_count = 0
        received_frame_count = 0

        async def send_request(
            self,
            *,
            request_id: int,
            method: str,
            params: dict[str, object],
            responding_to_test_request: bool = False,
        ) -> None:
            raise AssertionError("offline coordinator test must not send")

        async def next_envelope(
            self,
            timeout_seconds: float | None = None,
        ) -> InboundEnvelope:
            raise AssertionError("offline coordinator test must not receive")

        def enqueue_send_control(self, event: SendControlEvent) -> None:
            raise AssertionError("offline coordinator test must not enqueue")

    class FakeClientContext:
        async def __aenter__(self) -> PublicClient:
            events.append("client-enter")
            return FakeClient()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            events.append("client-exit")

    def client_factory(
        *,
        session_epoch: int,
        rpc_deadline_ms: int,
    ) -> FakeClientContext:
        events.append("client-factory")
        assert session_epoch == 1
        assert rpc_deadline_ms > 0
        return FakeClientContext()

    async def fake_run(
        client: PublicClient,
        stop_event: asyncio.Event,
        *,
        shadow_supervisor_triggers: ShadowSupervisorTriggers | None = None,
        shadow_terminal_gate: Callable[[int], None] | None = None,
    ) -> Path:
        events.append("runtime")
        assert shadow_supervisor_triggers == ShadowSupervisorTriggers(
            runtime_start_monotonic_ms=1,
            enrollment_cutoff_monotonic_ms=2,
            final_stop_monotonic_ms=3,
        )
        assert shadow_terminal_gate is not None
        shadow_terminal_gate(3)
        await stop_event.wait()
        assert isinstance(stop_event, ShadowStopEvent)
        assert stop_event.terminal_monotonic_ms == 3
        return summary_path

    monkeypatch.setattr(composition.runtime, "run", fake_run)

    result = asyncio.run(
        observe_shadow(
            composition,
            client_factory=client_factory,
            monotonic_ms=lambda: 3,
            signal_registrar=lambda _signum, _callback: None,
            sleep=lambda _seconds: asyncio.sleep(0),
        )
    )

    assert result == summary_path
    assert events == ["client-factory", "client-enter", "runtime", "client-exit"]


def test_observe_shadow_evidence_integrity_failure_terminalizes_once_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup = _startup(tmp_path)
    composition = build_shadow_composition(startup)
    client_count = 0
    run_count = 0

    class FakeClient:
        session_epoch = 1

    class FakeClientContext:
        async def __aenter__(self) -> PublicClient:
            return FakeClient()  # type: ignore[return-value]

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def client_factory(
        *,
        session_epoch: int,
        rpc_deadline_ms: int,
    ) -> FakeClientContext:
        nonlocal client_count
        client_count += 1
        assert session_epoch == 1
        assert rpc_deadline_ms > 0
        return FakeClientContext()

    async def fail_with_evidence_integrity(
        client: PublicClient,
        stop_event: asyncio.Event,
        *,
        shadow_supervisor_triggers: ShadowSupervisorTriggers | None = None,
        shadow_terminal_gate: Callable[[int], None] | None = None,
    ) -> Path:
        nonlocal run_count
        del stop_event, shadow_terminal_gate
        run_count += 1
        assert shadow_supervisor_triggers is not None
        composition.runtime.reducer.begin_session(
            session_epoch=client.session_epoch,
            monotonic_ms=1,
        )
        composition.runtime.commit_shadow_supervisor_control(
            ShadowSupervisorControlKind.RUNTIME_START,
            monotonic_ms=1,
        )
        raise ShadowRuntimeIntegrityError("injected downstream identity failure")

    async def wait_until_cancelled(_seconds: float) -> None:
        task = asyncio.current_task()
        if task is None or task.get_name() != "fixed-contract-shadow-supervisor":
            raise AssertionError("fatal integrity failure must not retry")
        await asyncio.Event().wait()

    def fake_manifest_git_reader(repository: Path, arguments: Sequence[str]) -> bytes:
        assert repository == ROOT
        command = tuple(arguments)
        if command == ("rev-parse", "--show-toplevel"):
            return f"{ROOT}\n".encode()
        if command == ("cat-file", "-e", f"{CANDIDATE}^{{commit}}"):
            return b""
        if command == ("rev-parse", f"{CANDIDATE}^{{tree}}"):
            return f"{TREE}\n".encode()
        if command == ("cat-file", "-e", f"{TREE}^{{tree}}"):
            return b""
        prefix = f"{CANDIDATE}:"
        if (
            len(command) == 3
            and command[:2] == ("cat-file", "blob")
            and command[2].startswith(prefix)
        ):
            return (ROOT / command[2].removeprefix(prefix)).read_bytes()
        raise AssertionError(f"unexpected Git object command: {command}")

    monkeypatch.setattr(composition.runtime, "run", fail_with_evidence_integrity)

    with pytest.raises(
        ShadowRuntimeIntegrityError,
        match="downstream identity failure",
    ):
        asyncio.run(
            observe_shadow(
                composition,
                client_factory=client_factory,
                monotonic_ms=lambda: 2,
                signal_registrar=lambda _signum, _callback: None,
                sleep=wait_until_cancelled,
            )
        )

    assert client_count == 1
    assert run_count == 1
    assert composition.runtime.shadow_terminalized
    current = read_current_evidence(
        startup.downstream_evidence_directory,
        bindings=startup.bindings,
    )
    complete = _read_complete_evidence_with_git_reader(
        startup.downstream_evidence_directory,
        bindings=startup.bindings,
        git_object_reader=fake_manifest_git_reader,
    )
    assert complete == current
    summaries = {str(value["object_kind"]): value["payload"] for value in complete.values()}
    assert set(summaries) == {
        "UNDERWRITING_POSITION_SUMMARY",
        "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY",
    }
    assert all(
        isinstance(payload, dict) and payload["conservation_status"] == "MET"
        for payload in summaries.values()
    )
    cohort = summaries["SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY"]
    assert isinstance(cohort, dict)
    assert cohort["terminal_disposition"] == "PROCESS_FAILURE"
    terminal_source = cohort["terminal_source"]
    assert isinstance(terminal_source, dict)
    assert terminal_source["control_kind"] == "PROCESS_FAILURE"
    assert terminal_source["failure_kind"] == "FATAL_EVIDENCE_INTEGRITY"
    assert not (startup.radar_evidence_directory / "radar-run-summary.json").exists()

    files_before = {
        path.relative_to(startup.downstream_evidence_directory): path.read_bytes()
        for path in startup.downstream_evidence_directory.rglob("*")
        if path.is_file()
    }
    composition.runtime.finalize_shadow_failure(3)
    assert {
        path.relative_to(startup.downstream_evidence_directory): path.read_bytes()
        for path in startup.downstream_evidence_directory.rglob("*")
        if path.is_file()
    } == files_before
    assert client_count == 1
    assert run_count == 1


def test_observe_shadow_reconnect_is_not_terminal_and_first_signal_stops_second_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composition = build_shadow_composition(_startup(tmp_path))
    summary_path = tmp_path / "radar-summary.json"
    registered: dict[signal.Signals, Callable[[], None]] = {}
    run_count = 0
    client_count = 0

    class FakeClient:
        queue_high_water_frames = 0
        overflow_count = 0
        received_frame_count = 0

        def __init__(self, session_epoch: int) -> None:
            self.session_epoch = session_epoch

        async def send_request(
            self,
            *,
            request_id: int,
            method: str,
            params: dict[str, object],
            responding_to_test_request: bool = False,
        ) -> None:
            raise AssertionError("offline coordinator test must not send")

        async def next_envelope(
            self,
            timeout_seconds: float | None = None,
        ) -> InboundEnvelope:
            raise AssertionError("offline coordinator test must not receive")

        def enqueue_send_control(self, event: SendControlEvent) -> None:
            raise AssertionError("offline coordinator test must not enqueue")

    class FakeClientContext:
        def __init__(self, session_epoch: int) -> None:
            self.client = FakeClient(session_epoch)

        async def __aenter__(self) -> PublicClient:
            return self.client

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def client_factory(
        *,
        session_epoch: int,
        rpc_deadline_ms: int,
    ) -> FakeClientContext:
        nonlocal client_count
        client_count += 1
        return FakeClientContext(session_epoch)

    async def fake_run(
        client: PublicClient,
        stop_event: asyncio.Event,
        *,
        shadow_supervisor_triggers: ShadowSupervisorTriggers | None = None,
        shadow_terminal_gate: Callable[[int], None] | None = None,
    ) -> Path:
        nonlocal run_count
        run_count += 1
        if run_count == 1:
            raise PublicSessionError("recoverable")
        registered[signal.SIGINT]()
        assert shadow_terminal_gate is not None
        shadow_terminal_gate(1)
        await stop_event.wait()
        return summary_path

    monkeypatch.setattr(composition.runtime, "run", fake_run)

    result = asyncio.run(
        observe_shadow(
            composition,
            client_factory=client_factory,
            monotonic_ms=lambda: 1,
            signal_registrar=lambda signum, callback: registered.__setitem__(
                signum,
                callback,
            ),
            sleep=lambda _seconds: asyncio.sleep(0),
        )
    )

    assert result == summary_path
    assert run_count == 2
    assert client_count == 2


@pytest.mark.parametrize(
    ("terminal_kind", "terminal_monotonic_ms", "terminal_disposition"),
    (
        ("signal", 2, "AUTHORIZED_EMERGENCY_STOP"),
        ("planned", 3, "PLANNED_CLEAN_STOP"),
    ),
)
def test_observe_shadow_stop_during_reconnect_backoff_closes_retired_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_kind: str,
    terminal_monotonic_ms: int,
    terminal_disposition: str,
) -> None:
    composition = build_shadow_composition(_startup(tmp_path))
    registered: dict[signal.Signals, Callable[[], None]] = {}
    run_count = 0
    client_count = 0
    clock_value = 1
    unexpected_summary_path = tmp_path / "unexpected-second-session-summary.json"

    class FakeClient:
        queue_high_water_frames = 0
        overflow_count = 0
        received_frame_count = 0

        def __init__(self, session_epoch: int) -> None:
            self.session_epoch = session_epoch

        async def send_request(
            self,
            *,
            request_id: int,
            method: str,
            params: dict[str, object],
            responding_to_test_request: bool = False,
        ) -> None:
            raise AssertionError("backoff terminal fixture must not send")

        async def next_envelope(
            self,
            timeout_seconds: float | None = None,
        ) -> InboundEnvelope:
            raise AssertionError("backoff terminal fixture must not receive")

        def enqueue_send_control(self, event: SendControlEvent) -> None:
            raise AssertionError("backoff terminal fixture must not enqueue")

    class FakeClientContext:
        def __init__(self, session_epoch: int) -> None:
            self.client = FakeClient(session_epoch)

        async def __aenter__(self) -> PublicClient:
            return self.client

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def client_factory(
        *,
        session_epoch: int,
        rpc_deadline_ms: int,
    ) -> FakeClientContext:
        nonlocal client_count
        del rpc_deadline_ms
        client_count += 1
        return FakeClientContext(session_epoch)

    async def fake_run(
        client: PublicClient,
        stop_event: asyncio.Event,
        *,
        shadow_supervisor_triggers: ShadowSupervisorTriggers | None = None,
        shadow_terminal_gate: Callable[[int], None] | None = None,
    ) -> Path:
        nonlocal run_count
        del stop_event, shadow_supervisor_triggers, shadow_terminal_gate
        run_count += 1
        if run_count == 1:
            composition.runtime.reducer.begin_session(
                session_epoch=client.session_epoch,
                monotonic_ms=0,
            )
            composition.runtime.commit_shadow_supervisor_control(
                ShadowSupervisorControlKind.RUNTIME_START,
                monotonic_ms=1,
            )
            composition.runtime.commit_shadow_supervisor_control(
                ShadowSupervisorControlKind.ENROLLMENT_CUTOFF,
                monotonic_ms=2,
            )
            composition.runtime.reducer.prepare_reconnect("TRANSPORT_READ_FAILURE")
            raise PublicSessionError("recoverable")
        return unexpected_summary_path

    async def scenario() -> Path:
        supervisor_waiting = asyncio.Event()
        release_supervisor = asyncio.Event()

        async def controlled_sleep(_seconds: float) -> None:
            nonlocal clock_value
            task = asyncio.current_task()
            if task is not None and task.get_name() == "fixed-contract-shadow-supervisor":
                supervisor_waiting.set()
                await release_supervisor.wait()
                return
            await supervisor_waiting.wait()
            clock_value = terminal_monotonic_ms
            if terminal_kind == "signal":
                registered[signal.SIGINT]()
            release_supervisor.set()
            while composition.adapter._configured_terminal_control is None:
                await asyncio.sleep(0)

        return await observe_shadow(
            composition,
            client_factory=client_factory,
            monotonic_ms=lambda: clock_value,
            signal_registrar=lambda signum, callback: registered.__setitem__(
                signum,
                callback,
            ),
            sleep=controlled_sleep,
        )

    monkeypatch.setattr(composition.runtime, "run", fake_run)

    summary_path = asyncio.run(scenario())
    summary = json.loads(summary_path.read_text())

    assert run_count == 1
    assert client_count == 1
    assert composition.runtime.reducer._session_epoch == 1
    assert composition.runtime.shadow_terminalized
    assert summary["clean_stop_monotonic_ms"] == terminal_monotonic_ms
    assert composition.adapter._terminal_disposition == terminal_disposition


@pytest.mark.parametrize(
    ("terminal_kind", "terminal_monotonic_ms", "terminal_disposition"),
    (
        ("signal", 2, "AUTHORIZED_EMERGENCY_STOP"),
        ("planned", 3, "PLANNED_CLEAN_STOP"),
    ),
)
def test_observe_shadow_stop_during_pre_session_backoff_does_not_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_kind: str,
    terminal_monotonic_ms: int,
    terminal_disposition: str,
) -> None:
    composition = build_shadow_composition(_startup(tmp_path))
    registered: dict[signal.Signals, Callable[[], None]] = {}
    client_count = 0
    client_enter_count = 0
    runtime_run_count = 0
    clock_value = 1
    unexpected_summary_path = tmp_path / "unexpected-second-client-summary.json"

    class FakeClient:
        queue_high_water_frames = 0
        overflow_count = 0
        received_frame_count = 0

        def __init__(self, session_epoch: int) -> None:
            self.session_epoch = session_epoch

        async def send_request(
            self,
            *,
            request_id: int,
            method: str,
            params: dict[str, object],
            responding_to_test_request: bool = False,
        ) -> None:
            raise AssertionError("pre-session terminal fixture must not send")

        async def next_envelope(
            self,
            timeout_seconds: float | None = None,
        ) -> InboundEnvelope:
            raise AssertionError("pre-session terminal fixture must not receive")

        def enqueue_send_control(self, event: SendControlEvent) -> None:
            raise AssertionError("pre-session terminal fixture must not enqueue")

    class FakeClientContext:
        def __init__(self, session_epoch: int) -> None:
            self.client = FakeClient(session_epoch)

        async def __aenter__(self) -> PublicClient:
            nonlocal client_enter_count
            client_enter_count += 1
            if client_enter_count == 1:
                raise OSError("pre-session connection failed")
            return self.client

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def client_factory(
        *,
        session_epoch: int,
        rpc_deadline_ms: int,
    ) -> FakeClientContext:
        nonlocal client_count
        del rpc_deadline_ms
        client_count += 1
        return FakeClientContext(session_epoch)

    async def unexpected_run(
        client: PublicClient,
        stop_event: asyncio.Event,
        *,
        shadow_supervisor_triggers: ShadowSupervisorTriggers | None = None,
        shadow_terminal_gate: Callable[[int], None] | None = None,
    ) -> Path:
        nonlocal runtime_run_count
        del client, stop_event, shadow_supervisor_triggers, shadow_terminal_gate
        runtime_run_count += 1
        return unexpected_summary_path

    async def scenario() -> Path:
        supervisor_waiting = asyncio.Event()
        release_supervisor = asyncio.Event()

        async def controlled_sleep(_seconds: float) -> None:
            nonlocal clock_value
            task = asyncio.current_task()
            if task is not None and task.get_name() == "fixed-contract-shadow-supervisor":
                supervisor_waiting.set()
                await release_supervisor.wait()
                return
            await supervisor_waiting.wait()
            clock_value = terminal_monotonic_ms
            if terminal_kind == "signal":
                registered[signal.SIGINT]()
            release_supervisor.set()
            while composition.adapter._configured_terminal_control is None:
                await asyncio.sleep(0)

        return await observe_shadow(
            composition,
            client_factory=client_factory,
            monotonic_ms=lambda: clock_value,
            signal_registrar=lambda signum, callback: registered.__setitem__(
                signum,
                callback,
            ),
            sleep=controlled_sleep,
        )

    monkeypatch.setattr(composition.runtime, "run", unexpected_run)

    summary_path = asyncio.run(scenario())
    summary = json.loads(summary_path.read_text())
    diagnostics = summary["operational_diagnostics"]
    assert isinstance(diagnostics, dict)
    ingress = diagnostics["ingress"]
    assert isinstance(ingress, dict)
    rpc_by_method = diagnostics["rpc_by_method"]
    assert isinstance(rpc_by_method, list)

    assert client_count == 1
    assert client_enter_count == 1
    assert runtime_run_count == 0
    assert composition.runtime.reducer._session_epoch == 1
    assert not composition.runtime.session_established
    assert composition.runtime.shadow_terminalized
    assert summary["clean_stop_monotonic_ms"] == terminal_monotonic_ms
    assert ingress["received_envelope_count"] == 0
    assert ingress["reduced_envelope_count"] == 0
    for row in rpc_by_method:
        assert isinstance(row, dict)
        assert row["sent_count"] == 0
        assert row["success_count"] == 0
    assert composition.adapter._terminal_disposition == terminal_disposition


def test_observe_shadow_pre_runtime_stop_fails_closed_without_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composition = build_shadow_composition(_startup(tmp_path))
    registered: dict[signal.Signals, Callable[[], None]] = {}
    client_count = 0
    runtime_run_count = 0

    class FailingClientContext:
        async def __aenter__(self) -> PublicClient:
            raise OSError("pre-session connection failed")

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def client_factory(
        *,
        session_epoch: int,
        rpc_deadline_ms: int,
    ) -> FailingClientContext:
        nonlocal client_count
        del session_epoch, rpc_deadline_ms
        client_count += 1
        return FailingClientContext()

    async def unexpected_run(
        client: PublicClient,
        stop_event: asyncio.Event,
        *,
        shadow_supervisor_triggers: ShadowSupervisorTriggers | None = None,
        shadow_terminal_gate: Callable[[int], None] | None = None,
    ) -> Path:
        nonlocal runtime_run_count
        del client, stop_event, shadow_supervisor_triggers, shadow_terminal_gate
        runtime_run_count += 1
        raise AssertionError("pre-runtime terminal must not start a runtime")

    async def scenario() -> Path:
        supervisor_waiting = asyncio.Event()
        release_supervisor = asyncio.Event()

        async def controlled_sleep(_seconds: float) -> None:
            task = asyncio.current_task()
            if task is not None and task.get_name() == "fixed-contract-shadow-supervisor":
                supervisor_waiting.set()
                await release_supervisor.wait()
                return
            await supervisor_waiting.wait()
            registered[signal.SIGINT]()
            release_supervisor.set()
            while composition.adapter._configured_terminal_control is None:
                await asyncio.sleep(0)

        return await observe_shadow(
            composition,
            client_factory=client_factory,
            monotonic_ms=lambda: 0,
            signal_registrar=lambda signum, callback: registered.__setitem__(
                signum,
                callback,
            ),
            sleep=controlled_sleep,
        )

    monkeypatch.setattr(composition.runtime, "run", unexpected_run)

    with pytest.raises(
        ShadowRuntimeIntegrityError,
        match="pre-session stop precedes runtime start",
    ):
        asyncio.run(scenario())

    assert client_count == 1
    assert runtime_run_count == 0
    assert composition.runtime.reducer._session_epoch is None
    assert not composition.runtime.shadow_terminalized
    assert composition.adapter._configured_terminal_control is not None
    assert composition.adapter._configured_terminal_control[0] == "AUTHORIZED_EMERGENCY_STOP"
    assert list(composition.startup.radar_evidence_directory.iterdir()) == []


def test_observe_shadow_cli_passes_exact_argv_and_cwd_before_composition_or_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = tmp_path / "manifest.json"
    radar_directory = tmp_path / "radar"
    summary_path = tmp_path / "summary.json"
    exact_argv = (
        "/exact/python-entry",
        "observe-shadow",
        "--manifest",
        str(manifest_path),
        "--radar-evidence-dir",
        str(radar_directory),
    )
    calls: list[str] = []

    @dataclass(frozen=True)
    class FakeManifest:
        manifest_identity: str

    @dataclass(frozen=True)
    class FakeStartup:
        manifest: FakeManifest
        code_identity: str
        runtime_identity: str
        downstream_evidence_directory: Path

    @dataclass(frozen=True)
    class FakeComposition:
        manifest_path: Path

    startup = FakeStartup(
        manifest=FakeManifest("sha256:" + "9" * 64),
        code_identity=CANDIDATE,
        runtime_identity=RUNTIME,
        downstream_evidence_directory=tmp_path / "downstream",
    )
    composition = FakeComposition(manifest_path=tmp_path / "downstream/manifest.json")

    def fake_prepare(
        *,
        manifest_path: Path,
        radar_evidence_directory: Path,
        process_argv: Sequence[str],
        process_cwd: Path,
    ) -> object:
        calls.append("prepare")
        assert manifest_path == Path(exact_argv[3])
        assert radar_evidence_directory == Path(exact_argv[5])
        assert tuple(process_argv) == exact_argv
        assert process_cwd == ROOT
        return startup

    def fake_build(value: object) -> object:
        calls.append("build")
        assert value is startup
        return composition

    async def fake_observe(value: object) -> Path:
        calls.append("observe")
        assert value is composition
        return summary_path

    monkeypatch.setattr(cli_module, "prepare_shadow_startup", fake_prepare)
    monkeypatch.setattr(cli_module, "build_shadow_composition", fake_build)
    monkeypatch.setattr(cli_module, "observe_shadow", fake_observe)
    monkeypatch.setattr(sys, "argv", list(exact_argv))
    monkeypatch.chdir(ROOT)

    assert cli_module.main() == 0

    output = json.loads(capsys.readouterr().out)
    assert calls == ["prepare", "build", "observe"]
    assert output == {
        "code_identity": CANDIDATE,
        "downstream_evidence_directory": str(tmp_path / "downstream"),
        "manifest_identity": "sha256:" + "9" * 64,
        "manifest_path": str(tmp_path / "downstream/manifest.json"),
        "radar_summary_path": str(summary_path),
        "runtime_identity": RUNTIME,
    }


def test_observe_shadow_cli_preflight_failure_never_builds_or_reaches_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = tmp_path / "manifest.json"
    radar_directory = tmp_path / "radar"
    exact_argv = (
        "/exact/python-entry",
        "observe-shadow",
        "--manifest",
        str(manifest_path),
        "--radar-evidence-dir",
        str(radar_directory),
    )
    calls: list[str] = []

    def fail_preflight(**_kwargs: object) -> object:
        calls.append("prepare")
        raise ShadowStartupError("injected pure preflight failure")

    def forbidden_build(_startup: object) -> object:
        calls.append("build")
        raise AssertionError("composition must not run after failed preflight")

    async def forbidden_observe(_composition: object) -> Path:
        calls.append("observe")
        raise AssertionError("client path must not run after failed preflight")

    monkeypatch.setattr(cli_module, "prepare_shadow_startup", fail_preflight)
    monkeypatch.setattr(cli_module, "build_shadow_composition", forbidden_build)
    monkeypatch.setattr(cli_module, "observe_shadow", forbidden_observe)
    monkeypatch.setattr(sys, "argv", list(exact_argv))

    with pytest.raises(ShadowStartupError, match="pure preflight"):
        cli_module.main()

    assert calls == ["prepare"]
    assert capsys.readouterr().out == ""


def test_invalid_manifest_and_policy_fail_before_any_git_or_directory_side_effect(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _copy_startup_files(repository)
    downstream = tmp_path / "downstream"
    radar = tmp_path / "radar"
    manifest_path = tmp_path / "manifest.json"
    argv = ("python", "-m", "radar_runtime", "observe-shadow")
    manifest = _manifest_value(
        repository=repository,
        downstream_directory=downstream,
        process_argv=argv,
    )
    manifest["candidate_commit"] = "not-a-commit"
    _write_manifest(manifest_path, manifest)
    git = FakeGit(repository=repository)

    with pytest.raises(ManifestError, match="candidate_commit"):
        prepare_shadow_startup(
            manifest_path=manifest_path,
            radar_evidence_directory=radar,
            process_argv=argv,
            process_cwd=repository,
            git_runner=git,
        )
    assert git.calls == []
    assert not downstream.exists()
    assert not radar.exists()

    manifest = _manifest_value(
        repository=repository,
        downstream_directory=downstream,
        process_argv=argv,
    )
    _write_manifest(manifest_path, manifest)
    radar_policy = repository / "policies/short-vol-fixed-public-shadow-radar.json"
    radar_policy.write_bytes(radar_policy.read_bytes() + b" ")

    with pytest.raises(ShadowStartupError, match="Policy"):
        prepare_shadow_startup(
            manifest_path=manifest_path,
            radar_evidence_directory=radar,
            process_argv=argv,
            process_cwd=repository,
            git_runner=git,
        )
    assert git.calls == []
    assert not downstream.exists()
    assert not radar.exists()


@pytest.mark.parametrize(
    ("git_kwargs", "match"),
    [
        ({"status": " M tracked.py\n"}, "clean"),
        ({"head": "f" * 40}, "HEAD"),
        ({"tree": "f" * 40}, "tree"),
        ({"remote_commit": "f" * 40}, "remote"),
    ],
)
def test_shadow_preflight_rejects_dirty_or_mixed_git_identity(
    tmp_path: Path,
    git_kwargs: dict[str, str],
    match: str,
) -> None:
    downstream = tmp_path / "downstream"
    radar = tmp_path / "radar"
    manifest_path = tmp_path / "manifest.json"
    argv = ("python", "-m", "radar_runtime", "observe-shadow")
    _write_manifest(
        manifest_path,
        _manifest_value(
            repository=ROOT,
            downstream_directory=downstream,
            process_argv=argv,
        ),
    )

    with pytest.raises(ShadowStartupError, match=match):
        prepare_shadow_startup(
            manifest_path=manifest_path,
            radar_evidence_directory=radar,
            process_argv=argv,
            process_cwd=ROOT,
            git_runner=FakeGit(repository=ROOT, **git_kwargs),
        )
    assert not downstream.exists()
    assert not radar.exists()


def test_shadow_preflight_rejects_argv_cwd_and_directory_aliases(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    downstream = tmp_path / "downstream"
    radar = tmp_path / "radar"
    argv = ("python", "-m", "radar_runtime", "observe-shadow")
    _write_manifest(
        manifest_path,
        _manifest_value(
            repository=ROOT,
            downstream_directory=downstream,
            process_argv=argv,
        ),
    )

    with pytest.raises(ShadowStartupError, match="argv"):
        prepare_shadow_startup(
            manifest_path=manifest_path,
            radar_evidence_directory=radar,
            process_argv=(*argv, "--unexpected"),
            process_cwd=ROOT,
            git_runner=FakeGit(repository=ROOT),
        )
    with pytest.raises(ShadowStartupError, match="cwd"):
        prepare_shadow_startup(
            manifest_path=manifest_path,
            radar_evidence_directory=radar,
            process_argv=argv,
            process_cwd=ROOT / "apps",
            git_runner=FakeGit(repository=ROOT),
        )
    with pytest.raises(ShadowStartupError, match="distinct"):
        prepare_shadow_startup(
            manifest_path=manifest_path,
            radar_evidence_directory=tmp_path / "alias" / ".." / "downstream",
            process_argv=argv,
            process_cwd=ROOT,
            git_runner=FakeGit(repository=ROOT),
        )
    assert not downstream.exists()
    assert not radar.exists()
