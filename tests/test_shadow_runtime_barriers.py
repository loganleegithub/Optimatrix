from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import radar_runtime.runtime as runtime_module
from market_monitor import TrustedClock
from radar_runtime.deribit_public import (
    InboundEnvelope,
    PublicSessionError,
    SendControlEvent,
    SendControlKind,
    SendFailureKind,
)
from radar_runtime.runtime import (
    CausalCommit,
    FactBoundary,
    LiveRadarRuntime,
    RadarReducer,
    RpcPurpose,
    RpcState,
    ShadowRpcIntent,
)
from short_vol_radar.evidence import EvidenceWriter
from short_vol_radar.policy import load_policy_bytes


class RecordingShadowAdapter:
    def __init__(self) -> None:
        self.failures: list[tuple[int, RpcState, FactBoundary]] = []
        self.responses: list[int] = []
        self.terminals: list[str] = []
        self.supervisor_boundaries: list[tuple[str, FactBoundary]] = []
        self.settled: list[CausalCommit] = []
        self.order: list[str] = []
        self.finalized = 0

    @property
    def required_combo_instrument_names(self) -> tuple[str, ...]:
        return ()

    def on_settled_transaction(
        self,
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
    ) -> tuple[ShadowRpcIntent, ...]:
        del reducer
        self.settled.append(commit)
        return ()

    def next_time_boundary_monotonic_ms(
        self,
        *,
        reducer: RadarReducer,
        after_monotonic_ms: int,
    ) -> int | None:
        del reducer, after_monotonic_ms
        return None

    def realize_runtime_start(
        self,
        *,
        reducer: RadarReducer,
        boundary: FactBoundary,
    ) -> None:
        del reducer
        self.supervisor_boundaries.append(("RUNTIME_START", boundary))
        self.order.append("RUNTIME_START")

    def realize_enrollment_cutoff(
        self,
        *,
        reducer: RadarReducer,
        boundary: FactBoundary,
    ) -> None:
        del reducer
        self.supervisor_boundaries.append(("ENROLLMENT_CUTOFF", boundary))
        self.order.append("ENROLLMENT_CUTOFF")

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
        self.failures.append((request_id, terminal_state, boundary))
        return ()

    def on_rpc_response(
        self,
        *,
        request_id: int,
        result: object,
        sent_boundary: FactBoundary,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        del result, sent_boundary, boundary
        self.responses.append(request_id)
        return ()

    def terminate(self, *, source: str, boundary: FactBoundary) -> None:
        del boundary
        self.terminals.append(source)

    def finalize_terminal(self) -> None:
        self.finalized += 1


def _runtime(
    tmp_path: Path,
    policy_factory: Any,
    adapter: RecordingShadowAdapter,
) -> LiveRadarRuntime:
    exact, digest = policy_factory()
    return LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        evidence_writer=EvidenceWriter(
            tmp_path,
            code_identity="a" * 40,
            runtime_identity="runtime",
            policy_identity=digest,
        ),
        runtime_identity="runtime",
        shadow_adapter=adapter,
    )


def _schedule_shadow_request(
    reducer: RadarReducer,
    *,
    monotonic_ms: int,
    purpose: RpcPurpose = RpcPurpose.ADMISSION_REFRESH,
) -> int:
    session_epoch = reducer._session_epoch
    assert session_epoch is not None
    request_id = reducer.allocate_shadow_request_id()
    boundary = FactBoundary(
        session_epoch,
        reducer._last_ingress_seq,
        monotonic_ms,
        reducer.causal_seq,
    )
    reducer._schedule_shadow_intents(
        (
            ShadowRpcIntent(
                request_id=request_id,
                purpose=purpose,
                method="public/get_order_book",
                params={"instrument_name": "BTC-COMBO", "depth": 10000},
                scope=(
                    "CANDIDATE:candidate"
                    if purpose is RpcPurpose.ADMISSION_REFRESH
                    else "POSITION:position"
                ),
                origin_boundary=boundary,
                send_budget_ms=100,
                response_budget_ms=100,
            ),
        )
    )
    return request_id


class _BufferedFailureClient:
    session_epoch = 1
    queue_high_water_frames = 2
    overflow_count = 0
    received_frame_count = 1
    enqueued_envelope_count = 2

    def __init__(self) -> None:
        self.events: deque[InboundEnvelope] = deque()

    async def send_request(self, **_kwargs: object) -> None:
        raise AssertionError("the failure fixture returns no outbound commands")

    async def next_envelope(
        self,
        timeout_seconds: float | None = None,
    ) -> InboundEnvelope:
        del timeout_seconds
        if self.events:
            return self.events.popleft()
        raise PublicSessionError("fixture session exhausted")

    def drain_envelopes(self) -> tuple[InboundEnvelope, ...]:
        drained = tuple(self.events)
        self.events.clear()
        return drained

    async def stop_intake(self) -> None:
        return None

    def enqueue_send_control(self, event: SendControlEvent) -> None:
        raise AssertionError(f"the fixture sender unexpectedly emitted {event}")


def _install_send_failure_then_connection(
    runtime: LiveRadarRuntime,
    client: _BufferedFailureClient,
) -> int:
    original = runtime.reducer.begin_session
    request_id = -1

    def begin_session(
        *,
        session_epoch: int,
        monotonic_ms: int,
    ) -> tuple[runtime_module.PendingRpc, ...]:
        nonlocal request_id
        original(session_epoch=session_epoch, monotonic_ms=monotonic_ms)
        request_id = _schedule_shadow_request(
            runtime.reducer,
            monotonic_ms=monotonic_ms,
        )
        client.events.extend(
            (
                InboundEnvelope(
                    {},
                    session_epoch=1,
                    ingress_seq=1,
                    received_monotonic_ms=monotonic_ms,
                    control_event=SendControlEvent(
                        kind=SendControlKind.SEND_FAILED,
                        request_id=request_id,
                        boundary_monotonic_ms=monotonic_ms,
                        failure=SendFailureKind.ERROR,
                    ),
                ),
                InboundEnvelope(
                    {
                        "jsonrpc": "2.0",
                        "method": "connection_error",
                        "params": {
                            "kind": "SESSION_FAILURE",
                            "reason": "TRANSPORT_READ_FAILURE",
                            "close_code": "1006",
                            "close_disposition": "ABNORMAL",
                            "exception_class": "OSError",
                        },
                    },
                    session_epoch=1,
                    ingress_seq=2,
                    received_monotonic_ms=monotonic_ms,
                ),
            )
        )
        return ()

    runtime.reducer.begin_session = begin_session  # type: ignore[method-assign]
    return request_id


def test_fatal_terminal_follows_every_barrier_accepted_shadow_failure(
    tmp_path: Path,
    policy_factory: Any,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    client = _BufferedFailureClient()
    _install_send_failure_then_connection(runtime, client)

    with pytest.raises(PublicSessionError, match="connection"):
        asyncio.run(runtime.run(client, asyncio.Event()))

    assert len(adapter.failures) == 1
    assert adapter.failures[0][1] is RpcState.ERROR
    assert adapter.terminals == []

    runtime.reducer.finalize_shadow_failure(runtime.reducer._last_boundary_monotonic_ms + 1)
    assert adapter.terminals == ["FAILURE"]
    assert adapter.finalized == 1


def test_recoverable_reconnect_drains_without_terminalizing_and_next_session_works(
    tmp_path: Path,
    policy_factory: Any,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    client = _BufferedFailureClient()
    _install_send_failure_then_connection(runtime, client)

    with pytest.raises(PublicSessionError):
        asyncio.run(runtime.run(client, asyncio.Event()))

    assert [state for _, state, _ in adapter.failures] == [RpcState.ERROR]
    assert adapter.terminals == []

    resumed_ms = runtime.reducer._last_boundary_monotonic_ms + 1
    runtime.reducer.begin_session(session_epoch=2, monotonic_ms=resumed_ms)
    request_id = _schedule_shadow_request(runtime.reducer, monotonic_ms=resumed_ms)
    runtime.reducer.reduce(
        InboundEnvelope(
            {},
            session_epoch=2,
            ingress_seq=1,
            received_monotonic_ms=resumed_ms + 1,
            control_event=SendControlEvent(
                kind=SendControlKind.SEND_COMPLETED,
                request_id=request_id,
                boundary_monotonic_ms=resumed_ms + 1,
            ),
        ),
        processed_monotonic_ms=resumed_ms + 1,
    )
    runtime.reducer.reduce(
        InboundEnvelope(
            {"jsonrpc": "2.0", "id": request_id, "result": {"change_id": 1}},
            session_epoch=2,
            ingress_seq=2,
            received_monotonic_ms=resumed_ms + 2,
        ),
        processed_monotonic_ms=resumed_ms + 2,
    )

    assert adapter.responses == [request_id]
    assert adapter.terminals == []


@pytest.mark.parametrize(
    "purpose",
    (RpcPurpose.ADMISSION_REFRESH, RpcPurpose.POST_CLOSE_REFRESH),
)
def test_pre_sent_shadow_response_is_orphan_and_request_expires_normally(
    tmp_path: Path,
    policy_factory: Any,
    purpose: RpcPurpose,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    request_id = _schedule_shadow_request(
        runtime.reducer,
        monotonic_ms=1_000,
        purpose=purpose,
    )
    early_response = InboundEnvelope(
        {"jsonrpc": "2.0", "id": request_id, "result": {"change_id": 1}},
        session_epoch=1,
        ingress_seq=1,
        received_monotonic_ms=1_001,
    )

    runtime.reducer.reduce(early_response, processed_monotonic_ms=1_001)
    runtime.reducer.reduce(
        InboundEnvelope(
            {},
            session_epoch=1,
            ingress_seq=2,
            received_monotonic_ms=1_002,
            control_event=SendControlEvent(
                kind=SendControlKind.SEND_COMPLETED,
                request_id=request_id,
                boundary_monotonic_ms=1_002,
            ),
        ),
        processed_monotonic_ms=1_002,
    )

    assert early_response.ingress_seq == 1
    assert early_response.received_monotonic_ms == 1_001
    assert runtime.reducer._rpc_lifecycles[request_id].state is RpcState.SENT
    assert adapter.responses == []
    assert runtime.reducer.diagnostics.rpc_orphan_late_wire_count == 1

    runtime.reducer.advance_time(1_102)
    assert runtime.reducer._rpc_lifecycles[request_id].state is RpcState.SENT
    runtime.reducer.advance_time(1_103)
    assert runtime.reducer._rpc_lifecycles[request_id].state is RpcState.DEADLINE_LATE
    assert [state for _, state, _ in adapter.failures] == [RpcState.DEADLINE_LATE]


def test_barrier_cancellation_is_not_an_ordinary_error_and_retires_typed(
    tmp_path: Path,
    policy_factory: Any,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    request_id = _schedule_shadow_request(runtime.reducer, monotonic_ms=1_000)

    runtime.reducer.begin_runtime_barrier(1_001)
    runtime.reducer.reduce(
        InboundEnvelope(
            {},
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=1_002,
            control_event=SendControlEvent(
                kind=SendControlKind.SEND_FAILED,
                request_id=request_id,
                boundary_monotonic_ms=1_002,
                failure=SendFailureKind.CANCELLED,
            ),
        ),
        processed_monotonic_ms=1_002,
    )

    assert adapter.failures == []
    runtime.reducer.prepare_reconnect("TRANSPORT_READ_FAILURE")
    assert [state for _, state, _ in adapter.failures] == [RpcState.RETIRED]


def test_barrier_settles_deadline_that_was_expired_when_barrier_opened(
    tmp_path: Path,
    policy_factory: Any,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    request_id = _schedule_shadow_request(runtime.reducer, monotonic_ms=1_000)

    runtime.reducer.begin_runtime_barrier(1_101)
    runtime.reducer.settle_barrier_deadlines(1_101)

    assert adapter.failures == [
        (
            request_id,
            RpcState.DEADLINE_LATE,
            FactBoundary(1, 0, 1_101, 1),
        )
    ]


def test_barrier_discards_new_shadow_intents_without_enrollment(
    tmp_path: Path,
    policy_factory: Any,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    runtime.reducer.begin_runtime_barrier(1_001, terminal=True)

    request_id = _schedule_shadow_request(runtime.reducer, monotonic_ms=1_001)

    assert request_id not in runtime.reducer.pending_rpcs
    assert request_id not in runtime.reducer._rpc_lifecycles


def test_start_and_cutoff_are_distinct_reducer_owned_control_boundaries(
    tmp_path: Path,
    policy_factory: Any,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)

    start = runtime.commit_shadow_supervisor_control(
        runtime_module.ShadowSupervisorControlKind.RUNTIME_START,
        monotonic_ms=1_100,
    )
    cutoff = runtime.commit_shadow_supervisor_control(
        runtime_module.ShadowSupervisorControlKind.ENROLLMENT_CUTOFF,
        monotonic_ms=1_100,
    )

    assert start == FactBoundary(1, 0, 1_100, 1)
    assert cutoff == FactBoundary(1, 0, 1_100, 2)
    assert adapter.supervisor_boundaries == [
        ("RUNTIME_START", start),
        ("ENROLLMENT_CUTOFF", cutoff),
    ]


class _IdleClient:
    session_epoch = 1
    queue_high_water_frames = 0
    overflow_count = 0
    received_frame_count = 0
    enqueued_envelope_count = 0

    async def send_request(self, **_kwargs: object) -> None:
        raise AssertionError("stopped fixture must not send")

    async def next_envelope(
        self,
        timeout_seconds: float | None = None,
    ) -> InboundEnvelope:
        del timeout_seconds
        raise AssertionError("stopped fixture must not await transport")

    def drain_envelopes(self) -> tuple[InboundEnvelope, ...]:
        return ()

    async def stop_intake(self) -> None:
        return None

    def enqueue_send_control(self, event: SendControlEvent) -> None:
        raise AssertionError(f"stopped fixture unexpectedly emitted {event}")


class _TerminalStopEvent(asyncio.Event):
    def __init__(self, terminal_monotonic_ms: int) -> None:
        super().__init__()
        self.terminal_monotonic_ms = terminal_monotonic_ms
        self.set()


class _RequestableTerminalStopEvent(asyncio.Event):
    def __init__(self) -> None:
        super().__init__()
        self.terminal_monotonic_ms: int | None = None

    def request(self, *, terminal_monotonic_ms: int) -> None:
        self.terminal_monotonic_ms = terminal_monotonic_ms
        self.set()


def test_initial_stop_realizes_overdue_start_and_cutoff_before_terminal(
    tmp_path: Path,
    policy_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: 1_000)

    summary_path = asyncio.run(
        runtime.run(
            _IdleClient(),
            _TerminalStopEvent(1_000),
            shadow_supervisor_triggers=runtime_module.ShadowSupervisorTriggers(
                runtime_start_monotonic_ms=900,
                enrollment_cutoff_monotonic_ms=950,
            ),
        )
    )

    assert summary_path.exists()
    assert adapter.order == ["RUNTIME_START", "ENROLLMENT_CUTOFF"]
    start = adapter.supervisor_boundaries[0][1]
    cutoff = adapter.supervisor_boundaries[1][1]
    assert start.received_monotonic_ms == cutoff.received_monotonic_ms == 1_000
    assert cutoff.causal_seq == start.causal_seq + 1
    assert adapter.terminals == ["STOP"]


class _BufferedSupervisorClient(_IdleClient):
    received_frame_count = 3
    enqueued_envelope_count = 3

    def __init__(self) -> None:
        self._drained = False
        self._events = (
            InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "method": "heartbeat",
                    "params": {"type": "heartbeat"},
                },
                session_epoch=1,
                ingress_seq=1,
                received_monotonic_ms=900,
            ),
            InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "method": "heartbeat",
                    "params": {"type": "heartbeat"},
                },
                session_epoch=1,
                ingress_seq=2,
                received_monotonic_ms=960,
            ),
            InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "method": "heartbeat",
                    "params": {"type": "heartbeat"},
                },
                session_epoch=1,
                ingress_seq=3,
                received_monotonic_ms=1_000,
            ),
        )

    def drain_envelopes(self) -> tuple[InboundEnvelope, ...]:
        if self._drained:
            return ()
        self._drained = True
        return self._events


class _FinalBarrierRecordingShadowAdapter(RecordingShadowAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.created_intent_boundaries: list[FactBoundary] = []

    def on_settled_transaction(
        self,
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
    ) -> tuple[ShadowRpcIntent, ...]:
        super().on_settled_transaction(reducer=reducer, commit=commit)
        if (
            commit.cause is runtime_module.CausalCause.PLATFORM_FACT
            and commit.boundary.ingress_seq >= 3
        ):
            self.created_intent_boundaries.append(commit.boundary)
            return (
                ShadowRpcIntent(
                    request_id=reducer.allocate_shadow_request_id(),
                    purpose=RpcPurpose.ADMISSION_REFRESH,
                    method="public/get_order_book",
                    params={"instrument_name": "BTC-COMBO", "depth": 10000},
                    scope="CANDIDATE:terminal-boundary",
                    origin_boundary=commit.boundary,
                    send_budget_ms=100,
                    response_budget_ms=100,
                ),
            )
        return ()


class _BufferedFinalStopClient(_IdleClient):
    received_frame_count = 4
    enqueued_envelope_count = 4

    def __init__(self) -> None:
        self._drained = False
        self._events = tuple(
            InboundEnvelope(
                {
                    "jsonrpc": "2.0",
                    "method": "subscription",
                    "params": {
                        "channel": "platform_state",
                        "data": {"maintenance": maintenance},
                    },
                },
                session_epoch=1,
                ingress_seq=ingress_seq,
                received_monotonic_ms=received_monotonic_ms,
            )
            for ingress_seq, received_monotonic_ms, maintenance in (
                (1, 900, False),
                (2, 960, False),
                (3, 1_000, False),
                (4, 1_001, True),
            )
        )

    def drain_envelopes(self) -> tuple[InboundEnvelope, ...]:
        if self._drained:
            return ()
        self._drained = True
        return self._events


def test_buffered_pretrigger_event_reduces_before_each_due_supervisor_control(
    tmp_path: Path,
    policy_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    stop_event = asyncio.Event()
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: 1_000)
    original_begin_session = runtime.reducer.begin_session
    original_reduce = runtime.reducer.reduce

    def begin_without_outbound(
        *,
        session_epoch: int,
        monotonic_ms: int,
    ) -> tuple[runtime_module.PendingRpc, ...]:
        original_begin_session(
            session_epoch=session_epoch,
            monotonic_ms=monotonic_ms,
        )
        return ()

    def tracked_reduce(
        envelope: InboundEnvelope,
        *,
        processed_monotonic_ms: int,
    ) -> tuple[runtime_module.PendingRpc, ...]:
        adapter.order.append(f"EVENT_{envelope.ingress_seq}")
        result = original_reduce(
            envelope,
            processed_monotonic_ms=processed_monotonic_ms,
        )
        if envelope.ingress_seq == 3:
            stop_event.set()
        return result

    monkeypatch.setattr(runtime.reducer, "begin_session", begin_without_outbound)
    monkeypatch.setattr(runtime.reducer, "reduce", tracked_reduce)

    asyncio.run(
        runtime.run(
            _BufferedSupervisorClient(),
            stop_event,
            shadow_supervisor_triggers=runtime_module.ShadowSupervisorTriggers(
                runtime_start_monotonic_ms=950,
                enrollment_cutoff_monotonic_ms=1_000,
            ),
        )
    )

    assert adapter.order[:5] == [
        "EVENT_1",
        "RUNTIME_START",
        "EVENT_2",
        "ENROLLMENT_CUTOFF",
        "EVENT_3",
    ]


def test_final_stop_opens_barrier_before_reducing_trigger_or_later_facts(
    tmp_path: Path,
    policy_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _FinalBarrierRecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    stop_event = _RequestableTerminalStopEvent()
    monkeypatch.setattr(runtime_module, "_monotonic_ms", lambda: 1_000)
    original_begin_session = runtime.reducer.begin_session
    original_reduce = runtime.reducer.reduce

    def begin_without_outbound(
        *,
        session_epoch: int,
        monotonic_ms: int,
    ) -> tuple[runtime_module.PendingRpc, ...]:
        original_begin_session(
            session_epoch=session_epoch,
            monotonic_ms=monotonic_ms,
        )
        runtime.reducer._channels["platform_state"] = runtime_module._ChannelSlot(
            state=runtime_module.ChannelState.ACKNOWLEDGED,
            generation=1,
            desired_subscribed=True,
        )
        runtime.reducer._update_subscription_peaks()
        return ()

    def tracked_reduce(
        envelope: InboundEnvelope,
        *,
        processed_monotonic_ms: int,
    ) -> tuple[runtime_module.PendingRpc, ...]:
        adapter.order.append(f"EVENT_{envelope.ingress_seq}")
        return original_reduce(
            envelope,
            processed_monotonic_ms=processed_monotonic_ms,
        )

    def realize_terminal_gate(monotonic_ms: int) -> None:
        adapter.order.append("FINAL_STOP")
        runtime.configure_shadow_terminal_control(
            terminal_disposition="PLANNED_CLEAN_STOP",
            terminal_source={"control_monotonic_ms": monotonic_ms},
        )
        stop_event.request(terminal_monotonic_ms=monotonic_ms)

    monkeypatch.setattr(runtime.reducer, "begin_session", begin_without_outbound)
    monkeypatch.setattr(runtime.reducer, "reduce", tracked_reduce)

    asyncio.run(
        runtime.run(
            _BufferedFinalStopClient(),
            stop_event,
            shadow_supervisor_triggers=runtime_module.ShadowSupervisorTriggers(
                runtime_start_monotonic_ms=800,
                enrollment_cutoff_monotonic_ms=850,
                final_stop_monotonic_ms=960,
            ),
            shadow_terminal_gate=realize_terminal_gate,
        )
    )

    assert adapter.order == [
        "RUNTIME_START",
        "ENROLLMENT_CUTOFF",
        "EVENT_1",
        "FINAL_STOP",
        "EVENT_2",
        "EVENT_3",
        "EVENT_4",
    ]
    platform_commits = [
        commit
        for commit in adapter.settled
        if commit.cause is runtime_module.CausalCause.PLATFORM_FACT
    ]
    assert [commit.boundary.ingress_seq for commit in platform_commits] == [1, 2]
    assert adapter.created_intent_boundaries == []
    assert not runtime.reducer.platform.maintenance_guard
    assert runtime.reducer.diagnostics.retired_epoch_frame_count == 2
    assert adapter.terminals == ["STOP"]


def test_radar_summary_writer_failure_does_not_skip_downstream_terminal(
    tmp_path: Path,
    policy_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)

    def fail_summary(_summary: dict[str, object]) -> Path:
        raise OSError("injected Radar summary failure")

    monkeypatch.setattr(runtime.reducer.writer, "write_summary", fail_summary)

    with pytest.raises(OSError, match="Radar summary"):
        runtime.reducer.clean_stop(1_100)

    assert adapter.terminals == ["FAILURE"]
    assert adapter.finalized == 1


def _set_platform_usable(reducer: RadarReducer) -> None:
    reducer.platform.platform_subscription_acknowledged = True
    reducer.platform.public_methods_subscription_acknowledged = True
    reducer.platform.lock_snapshot = False
    reducer.platform.status_usable = True
    reducer.platform.maintenance_guard = False
    reducer.platform.public_method_guard = True
    reducer.platform.post_status_probe = True
    reducer.platform.fresh_index_coverage = True


def test_platform_continuity_receipt_uses_only_successful_wire_envelopes(
    tmp_path: Path,
    policy_factory: Any,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    heartbeat = runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)[0]
    _set_platform_usable(runtime.reducer)

    runtime.reducer.reduce(
        InboundEnvelope(
            {
                "jsonrpc": "2.0",
                "method": "heartbeat",
                "params": {"type": "heartbeat"},
            },
            session_epoch=1,
            ingress_seq=1,
            received_monotonic_ms=1_001,
        ),
        processed_monotonic_ms=1_001,
    )
    accepted = FactBoundary(1, 1, 1_001, runtime.reducer.causal_seq)
    assert runtime.reducer.accepted_platform_continuity_boundary == accepted

    runtime.reducer.advance_time(1_002)
    assert runtime.reducer.accepted_platform_continuity_boundary == accepted
    runtime.reducer.reduce(
        InboundEnvelope(
            {},
            session_epoch=1,
            ingress_seq=2,
            received_monotonic_ms=1_003,
            control_event=SendControlEvent(
                kind=SendControlKind.SEND_COMPLETED,
                request_id=heartbeat.request_id,
                boundary_monotonic_ms=1_003,
            ),
        ),
        processed_monotonic_ms=1_003,
    )
    assert runtime.reducer.accepted_platform_continuity_boundary == accepted

    runtime.reducer.prepare_reconnect("TRANSPORT_READ_FAILURE")
    assert runtime.reducer.accepted_platform_continuity_boundary is None


def test_ahead_index_candidate_does_not_overwrite_downstream_receipt(
    tmp_path: Path,
    policy_factory: Any,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)
    runtime.reducer.index.start_continuous_coverage(2_000, generation=1)
    runtime.reducer.clock = TrustedClock.from_response(
        2_000,
        1_000,
        1_000,
        stale_deadline_ms=10_000,
    )
    runtime.reducer._causal_seq = 1
    first_boundary = FactBoundary(1, 1, 1_030, 1)
    assert runtime.reducer._apply_index(
        {
            "index_name": "btc_usdc",
            "timestamp": 2_000,
            "price": "100000.25",
        },
        first_boundary,
    )
    accepted = runtime.reducer.accepted_index_receipt
    assert accepted is not None
    assert accepted.price_usdc_per_btc == Decimal("100000.25")

    ahead_boundary = FactBoundary(1, 2, 1_031, 2)
    trusted_upper = runtime.reducer.clock.interval_at(ahead_boundary.received_monotonic_ms).upper_ms
    assert runtime.reducer._apply_index(
        {
            "index_name": "btc_usdc",
            "timestamp": trusted_upper + 1,
            "price": "999999.00",
        },
        ahead_boundary,
    )
    assert runtime.reducer.accepted_index_receipt == accepted
