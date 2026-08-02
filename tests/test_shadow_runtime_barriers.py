from __future__ import annotations

import asyncio
from collections import deque
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
from short_vol_radar.evidence import RadarEventSink
from short_vol_radar.policy import load_policy_bytes


class RecordingShadowAdapter:
    def __init__(self) -> None:
        self.failures: list[tuple[int, RpcState, FactBoundary]] = []
        self.responses: list[int] = []
        self.terminals: list[str] = []
        self.supervisor_boundaries: list[tuple[str, FactBoundary]] = []
        self.settled: list[CausalCommit] = []
        self.order: list[str] = []

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


def _runtime(
    tmp_path: Path,
    policy_factory: Any,
    adapter: RecordingShadowAdapter,
) -> LiveRadarRuntime:
    exact, digest = policy_factory()
    return LiveRadarRuntime(
        policy=load_policy_bytes(exact, digest),
        code_identity="a" * 40,
        event_sink=RadarEventSink(
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


def test_radar_summary_sink_failure_does_not_skip_downstream_terminal(
    tmp_path: Path,
    policy_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = RecordingShadowAdapter()
    runtime = _runtime(tmp_path, policy_factory, adapter)
    runtime.reducer.begin_session(session_epoch=1, monotonic_ms=1_000)

    def fail_summary(_summary: dict[str, object]) -> dict[str, object]:
        raise OSError("injected Radar summary failure")

    monkeypatch.setattr(runtime.reducer.event_sink, "record_summary", fail_summary)

    with pytest.raises(OSError, match="Radar summary"):
        runtime.reducer.clean_stop(1_100)

    assert adapter.terminals == ["FAILURE"]


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
