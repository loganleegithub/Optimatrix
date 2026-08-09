from __future__ import annotations

import asyncio
import json
from argparse import Namespace
from collections.abc import Iterator, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import FrozenInstanceError, dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import pytest
import radar_runtime.__main__ as runtime_cli
import radar_runtime.service as service_module
import radar_runtime.workbench as workbench_module
import test_shadow_case_store as shadow_case_fixture
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
    RpcPurpose,
    RpcState,
    ShadowRpcIntent,
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


@dataclass(frozen=True)
class _RestartedEntryCompositions:
    first: PersistentServiceComposition
    second: PersistentServiceComposition
    workspace: Path
    entry_identity: str
    case_directory: Path
    opened_record: bytes


@pytest.fixture
def restarted_entry_compositions(tmp_path: Path) -> Iterator[_RestartedEntryCompositions]:
    first_startup = _startup(tmp_path, nonce="process-a")
    first_bindings = replace(
        first_startup.runtime_bindings,
        runtime_identity=shadow_case_fixture.RUNTIME,
    )
    first_startup = replace(
        first_startup,
        runtime_identity=first_bindings.runtime_identity,
        runtime_bindings=first_bindings,
    )
    first = build_persistent_service_composition(first_startup)
    second: PersistentServiceComposition | None = None
    try:
        _availability, _action, candidate_identity = shadow_case_fixture._seed_pre_shadow(
            first.shadow_state
        )
        entry_identity = shadow_case_fixture._open_case(
            first.shadow_state,
            candidate_identity,
        )
        case_id = first.case_store.case_id_for_entry(entry_identity)
        assert case_id is not None
        first.adapter.terminate(
            source="STOP",
            boundary=FactBoundary(1, 5, 105, 5),
        )
        case_directory = first.startup.cases_directory / case_id.removeprefix("sha256:")
        opened_record = (case_directory / "opened.json").read_bytes()

        second = build_persistent_service_composition(_startup(tmp_path, nonce="process-b"))
        yield _RestartedEntryCompositions(
            first=first,
            second=second,
            workspace=tmp_path,
            entry_identity=entry_identity,
            case_directory=case_directory,
            opened_record=opened_record,
        )
    finally:
        if second is not None:
            second.workbench.close()
        first.workbench.close()


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


def test_offline_migration_uses_a_stopped_source_and_stable_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_root = (tmp_path / "legacy-state").resolve()
    source_cases = source_root / "runs" / "legacy-runtime" / "cases"
    source_cases.mkdir(parents=True)
    source_lock = source_root / "service.lock"
    source_lock.write_bytes(b"legacy-service-lock\n")
    destination_root = (tmp_path / "stable-state").resolve()
    seen: dict[str, object] = {}
    product = SimpleNamespace(name=SimpleNamespace(value="inverse-btc"))
    policies = object()

    monkeypatch.setattr(runtime_cli, "git_repository_root", lambda _cwd: ROOT)
    monkeypatch.setattr(runtime_cli, "clean_code_identity", lambda _repository: CODE)
    monkeypatch.setattr(
        runtime_cli,
        "load_persistent_product_policies",
        lambda _repository, _product: (product, policies),
    )

    def migrate(source: Path, destination: Path, *, policies: object) -> tuple[object, ...]:
        seen.update(source=source, destination=destination, policies=policies)
        return (object(), object())

    monkeypatch.setattr(runtime_cli, "migrate_legacy_admitted_cases", migrate)
    arguments = Namespace(
        source_state_root=source_root,
        source_cases=source_cases,
        destination_state_root=destination_root,
        product="inverse-btc",
    )

    with SingleInstanceLease(source_root):
        with pytest.raises(PersistentServiceStartupError, match="another persistent service"):
            runtime_cli._run_legacy_migration(arguments)

    source_lock.write_bytes(b"legacy-service-lock\n")
    source_lock_bytes = source_lock.read_bytes()
    source_lock_mtime_ns = source_lock.stat().st_mtime_ns

    for overlapping_destination in (source_root / "child", source_root.parent):
        arguments.destination_state_root = overlapping_destination
        with pytest.raises(PersistentServiceStartupError, match="cannot overlap"):
            runtime_cli._run_legacy_migration(arguments)
    assert not (source_root / "child").exists()

    arguments.destination_state_root = destination_root
    assert runtime_cli._run_legacy_migration(arguments) == 0
    assert seen == {
        "source": source_cases,
        "destination": destination_root / "cases",
        "policies": policies,
    }
    assert source_lock.read_bytes() == source_lock_bytes
    assert source_lock.stat().st_mtime_ns == source_lock_mtime_ns
    assert "migrated_entries=2" in capsys.readouterr().out

    missing_root = (tmp_path / "missing-legacy-lock").resolve()
    missing_cases = missing_root / "runs" / "legacy-runtime" / "cases"
    missing_cases.mkdir(parents=True)
    arguments.source_state_root = missing_root
    arguments.source_cases = missing_cases
    arguments.destination_state_root = (tmp_path / "unused-destination").resolve()
    with pytest.raises(PersistentServiceStartupError, match="regular non-symlink file"):
        runtime_cli._run_legacy_migration(arguments)
    assert not (missing_root / "service.lock").exists()
    assert not arguments.destination_state_root.exists()


def test_startup_builds_one_business_owner_graph_without_service_ledger(tmp_path: Path) -> None:
    startup = _startup(tmp_path)
    composition = build_persistent_service_composition(startup)
    try:
        assert startup.cases_directory.is_dir()
        assert startup.cases_directory == startup.state_root / "cases"
        assert not (startup.state_root / "runs").exists()
        assert composition.owner.policies is startup.policies
        assert composition.runtime.policy is startup.policies.radar
        assert composition.adapter.owner is composition.owner
        assert composition.publisher.bindings is startup.runtime_bindings
        with pytest.raises(FrozenInstanceError):
            startup.policies.radar.identity = "sha256:" + "f" * 64  # type: ignore[misc]
    finally:
        composition.workbench.close()


def test_restarts_reuse_one_business_case_repository_with_new_runtime_identity(
    tmp_path: Path,
) -> None:
    first = _startup(tmp_path, nonce="process-a")
    second = _startup(tmp_path, nonce="process-b")

    assert first.runtime_identity != second.runtime_identity
    assert first.cases_directory == second.cases_directory
    assert first.cases_directory == first.state_root / "cases"
    assert sorted(path.name for path in first.state_root.iterdir()) == ["cases"]


def test_restart_stages_entry_legs_before_first_commit_and_adopts_without_replay(
    restarted_entry_compositions: _RestartedEntryCompositions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = restarted_entry_compositions
    composition = fixture.second

    assert composition.owner.active_trade_identities == frozenset()
    assert composition.adapter.required_option_instrument_names == (
        "BTC_USDC-8AUG26-100000-C",
        "BTC_USDC-8AUG26-102000-C",
    )
    staged_objects: tuple[Mapping[str, object], ...] = composition.shadow_state.objects
    assert {value["object_kind"] for value in staged_objects} == {
        "SHADOW_ENTRY",
        "SHADOW_OUTCOME_OBSERVATION",
    }
    staged_entry = next(value for value in staged_objects if value["object_kind"] == "SHADOW_ENTRY")
    staged_payload = staged_entry["payload"]
    assert isinstance(staged_payload, Mapping)
    assert staged_payload["tracking_state"] == "RECOVERING"
    assert staged_payload["current_segment_identity"] is None
    assert staged_payload["current_segment_sequence"] is None
    initial_document = json.loads(composition.snapshot_store.read().workbench_body)
    assert initial_document["service"]["phase"] == "STARTING"
    assert initial_document["service"]["data_state"] == "UNKNOWN"
    assert len(initial_document["shadow_entries"]["rows"]) == 1
    assert initial_document["shadow_entries"]["rows"][0]["tracking_state"] == "RECOVERING"
    assert len(initial_document["positions"]["rows"]) == 1
    assert initial_document["positions"]["rows"][0]["position_action"] == "UNKNOWN"

    reducer = composition.runtime.reducer
    reducer.begin_session(session_epoch=1, monotonic_ms=1_000)

    def forbidden_position_settlement(**_kwargs: object) -> NoReturn:
        raise AssertionError("the recovery adoption commit is not a Position fact boundary")

    monkeypatch.setattr(composition.owner, "settle_position", forbidden_position_settlement)
    commit = CausalCommit(
        boundary=FactBoundary(1, 0, 1_010, 1),
        cause=CausalCause.RUNTIME_START,
        failure_domain=FailureScope.SESSION,
        affected_scopes=("GLOBAL",),
    )
    reducer._settle_fact(commit=commit, affected_instruments=(), countable=False)

    current_objects: tuple[Mapping[str, object], ...] = composition.shadow_state.objects
    current_kinds = {value["object_kind"] for value in current_objects}
    assert current_kinds == {"SHADOW_ENTRY", "SHADOW_OUTCOME_OBSERVATION"}
    assert composition.shadow_state.take_pending_records() == ()
    assert composition.owner.active_candidate_identities == frozenset()
    assert composition.owner.active_trade_identities == frozenset({fixture.entry_identity})
    assert composition.adapter.retained_state_counts["active_anchors"] == 1
    assert all(
        request.purpose not in {RpcPurpose.ADMISSION_REFRESH, RpcPurpose.POST_CLOSE_REFRESH}
        for request in composition.runtime.reducer.pending_rpcs.values()
    )
    assert (fixture.case_directory / "opened.json").read_bytes() == fixture.opened_record
    assert sorted(path.name for path in (fixture.case_directory / "segments").iterdir()) == [
        "0",
        "1",
    ]
    assert not (fixture.case_directory / "outcome.json").exists()

    composition.adapter.terminate(
        source="STOP",
        boundary=FactBoundary(1, 1, 1_020, 2),
    )
    case = composition.case_store.read_case(
        composition.case_store.case_id_for_entry(fixture.entry_identity) or ""
    )
    assert case.outcome is None
    assert case.segments[-1].status.value == "CENSORED_AT_STOP"

    third = build_persistent_service_composition(_startup(fixture.workspace, nonce="process-c"))
    try:
        assert third.startup.runtime_identity != composition.startup.runtime_identity
        assert third.owner.active_trade_identities == frozenset()
        assert third.adapter.required_option_instrument_names == (
            "BTC_USDC-8AUG26-100000-C",
            "BTC_USDC-8AUG26-102000-C",
        )
        third_staged = third.shadow_state.objects
        assert {value["object_kind"] for value in third_staged} == {
            "SHADOW_ENTRY",
            "SHADOW_OUTCOME_OBSERVATION",
        }
        third_initial = json.loads(third.snapshot_store.read().workbench_body)
        assert len(third_initial["shadow_entries"]["rows"]) == 1
        assert third_initial["shadow_entries"]["rows"][0]["tracking_state"] == "RECOVERING"

        third_reducer = third.runtime.reducer
        third_reducer.begin_session(session_epoch=1, monotonic_ms=2_000)
        monkeypatch.setattr(third.owner, "settle_position", forbidden_position_settlement)
        third_commit = CausalCommit(
            boundary=FactBoundary(1, 0, 2_010, 1),
            cause=CausalCause.RUNTIME_START,
            failure_domain=FailureScope.SESSION,
            affected_scopes=("GLOBAL",),
        )
        third_reducer._settle_fact(
            commit=third_commit,
            affected_instruments=(),
            countable=False,
        )

        assert third.owner.active_candidate_identities == frozenset()
        assert third.owner.active_trade_identities == frozenset({fixture.entry_identity})
        assert third.shadow_state.take_pending_records() == ()
        third_objects: tuple[Mapping[str, object], ...] = third.shadow_state.objects
        assert {value["object_kind"] for value in third_objects} == {
            "SHADOW_ENTRY",
            "SHADOW_OUTCOME_OBSERVATION",
        }
        assert third.adapter.retained_state_counts["active_anchors"] == 1
        assert (fixture.case_directory / "opened.json").read_bytes() == fixture.opened_record
        assert sorted(path.name for path in (fixture.case_directory / "segments").iterdir()) == [
            "0",
            "1",
            "2",
        ]
        third_case_id = third.case_store.case_id_for_entry(fixture.entry_identity)
        assert third_case_id is not None
        third_case = third.case_store.read_case(third_case_id, runtime_active=True)
        assert third_case.opened["shadow_entry_identity"] == fixture.entry_identity
        assert third_case.outcome is None
        assert third_case.segments[-1].opened["observation_quality"] == "GAPPED"
        assert third_case.segments[-1].opened["gap_count"] == 2

        third.adapter.terminate(
            source="STOP",
            boundary=FactBoundary(1, 1, 2_020, 2),
        )
        final_case = third.case_store.read_case(third_case_id)
        assert final_case.outcome is None
        assert final_case.segments[-1].status.value == "CENSORED_AT_STOP"
    finally:
        third.workbench.close()


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
        assert sorted(path.name for path in startup.state_root.iterdir()) == ["cases"]
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
