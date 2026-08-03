from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from conftest import PolicyFactory
from radar_runtime.deribit_public import (
    InboundEnvelope,
    SendControlEvent,
    SendControlKind,
    SendFailureKind,
)
from radar_runtime.runtime import (
    CausalCause,
    CausalCommit,
    FactBoundary,
    FailureScope,
    RadarReducer,
    RpcPurpose,
    RpcState,
    ShadowRpcIntent,
)
from short_vol_radar.evidence import RadarEventSink
from short_vol_radar.policy import load_policy_bytes


@dataclass
class RecordingShadowAdapter:
    schedule_on_settle: bool = False
    required_combo_instrument_names: tuple[str, ...] = ()
    settled: list[CausalCommit] = field(default_factory=list)
    sent: list[tuple[int, FactBoundary]] = field(default_factory=list)
    failed: list[tuple[int, RpcState, FactBoundary]] = field(default_factory=list)
    responses: list[tuple[int, object, FactBoundary, FactBoundary]] = field(default_factory=list)
    terminals: list[tuple[str, FactBoundary]] = field(default_factory=list)

    def on_settled_transaction(
        self,
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
    ) -> tuple[ShadowRpcIntent, ...]:
        self.settled.append(commit)
        if not self.schedule_on_settle:
            return ()
        self.schedule_on_settle = False
        return (
            ShadowRpcIntent(
                request_id=reducer.allocate_shadow_request_id(),
                purpose=RpcPurpose.ADMISSION_REFRESH,
                method="public/get_order_book",
                params={"instrument_name": "BTC-COMBO", "depth": 10000},
                scope="sha256:" + "a" * 64,
                origin_boundary=commit.boundary,
                send_budget_ms=7,
                response_budget_ms=11,
            ),
        )

    def next_time_boundary_monotonic_ms(
        self,
        *,
        reducer: RadarReducer,
        after_monotonic_ms: int,
    ) -> int | None:
        del reducer, after_monotonic_ms
        return None

    def on_request_sent(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        self.sent.append((request_id, boundary))
        return ()

    def realize_runtime_start(
        self,
        *,
        reducer: RadarReducer,
        boundary: FactBoundary,
    ) -> None:
        del reducer, boundary

    def realize_enrollment_cutoff(
        self,
        *,
        reducer: RadarReducer,
        boundary: FactBoundary,
    ) -> None:
        del reducer, boundary

    def on_request_failure(
        self,
        *,
        request_id: int,
        terminal_state: RpcState,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        self.failed.append((request_id, terminal_state, boundary))
        return ()

    def on_rpc_response(
        self,
        *,
        request_id: int,
        result: object,
        sent_boundary: FactBoundary,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        self.responses.append((request_id, result, sent_boundary, boundary))
        return ()

    def terminate(self, *, source: str, boundary: FactBoundary) -> None:
        self.terminals.append((source, boundary))


def _reducer(
    tmp_path: Path,
    policy_factory: PolicyFactory,
    *,
    adapter: RecordingShadowAdapter | None,
) -> RadarReducer:
    exact, digest = policy_factory()
    return RadarReducer(
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


def _commit(monotonic_ms: int) -> CausalCommit:
    return CausalCommit(
        boundary=FactBoundary(1, 0, monotonic_ms, 1),
        cause=CausalCause.RUNTIME_START,
        failure_domain=FailureScope.SESSION,
        affected_scopes=("GLOBAL",),
    )


def test_optional_adapter_receives_each_successful_settled_transaction_once(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    adapter = RecordingShadowAdapter()
    reducer = _reducer(tmp_path, policy_factory, adapter=adapter)
    monotonic_ms = reducer._coverage._current_start_ms + 10
    commit = _commit(monotonic_ms)

    reducer._settle_fact(
        commit=commit,
        affected_instruments=(),
        countable=False,
    )

    assert adapter.settled == [commit]


def test_shadow_rpc_uses_global_request_id_specific_budgets_and_typed_route(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    adapter = RecordingShadowAdapter(schedule_on_settle=True)
    reducer = _reducer(tmp_path, policy_factory, adapter=adapter)
    started_ms = reducer._coverage._current_start_ms + 10
    (radar_request,) = reducer.begin_session(
        session_epoch=1,
        monotonic_ms=started_ms,
    )
    monotonic_ms = started_ms + 10
    reducer._causal_seq = 1

    reducer._settle_fact(
        commit=_commit(monotonic_ms),
        affected_instruments=(),
        countable=False,
    )
    (request,) = reducer._take_commands()

    assert radar_request.request_id == 1
    assert request.request_id == 2
    assert request.purpose is RpcPurpose.ADMISSION_REFRESH
    assert request.send_deadline_monotonic_ms == monotonic_ms + 7
    assert request.response_budget_ms == 11

    sent = InboundEnvelope(
        {},
        session_epoch=1,
        ingress_seq=1,
        received_monotonic_ms=monotonic_ms + 5,
        control_event=SendControlEvent(
            kind=SendControlKind.SEND_COMPLETED,
            request_id=request.request_id,
            boundary_monotonic_ms=monotonic_ms + 5,
        ),
    )
    reducer.reduce(sent, processed_monotonic_ms=monotonic_ms + 5)
    response = InboundEnvelope(
        {"jsonrpc": "2.0", "id": request.request_id, "result": {"change_id": 9}},
        session_epoch=1,
        ingress_seq=2,
        received_monotonic_ms=monotonic_ms + 15,
    )
    reducer.reduce(response, processed_monotonic_ms=monotonic_ms + 15)

    assert adapter.sent == [(2, FactBoundary(1, 1, monotonic_ms + 5, 2))]
    assert adapter.responses == [
        (
            2,
            {"change_id": 9},
            FactBoundary(1, 1, monotonic_ms + 5, 2),
            FactBoundary(1, 2, monotonic_ms + 15, 3),
        )
    ]


def test_shadow_subscription_requirement_is_unioned_with_radar_requirement(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    adapter = RecordingShadowAdapter(
        required_combo_instrument_names=("BTC-COMBO",),
    )
    reducer = _reducer(tmp_path, policy_factory, adapter=adapter)
    reducer._session_epoch = 1

    reducer._sync_combo_subscriptions(FactBoundary(1, 0, 1_000, 1))
    (request,) = reducer._take_commands()

    assert request.purpose is RpcPurpose.SUBSCRIBE_CHANNELS
    assert request.params == {"channels": ["book.BTC-COMBO.100ms"]}


def test_shadow_send_failure_uses_typed_failure_route(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    adapter = RecordingShadowAdapter(schedule_on_settle=True)
    reducer = _reducer(tmp_path, policy_factory, adapter=adapter)
    reducer._session_epoch = 1
    monotonic_ms = reducer._coverage._current_start_ms + 10
    reducer._causal_seq = 1
    reducer._settle_fact(
        commit=_commit(monotonic_ms),
        affected_instruments=(),
        countable=False,
    )
    (request,) = reducer._take_commands()
    failed = InboundEnvelope(
        {},
        session_epoch=1,
        ingress_seq=1,
        received_monotonic_ms=monotonic_ms + 5,
        control_event=SendControlEvent(
            kind=SendControlKind.SEND_FAILED,
            request_id=request.request_id,
            boundary_monotonic_ms=monotonic_ms + 5,
            failure=SendFailureKind.ERROR,
        ),
    )

    reducer.reduce(failed, processed_monotonic_ms=monotonic_ms + 5)

    assert adapter.failed == [
        (
            request.request_id,
            RpcState.ERROR,
            FactBoundary(1, 1, monotonic_ms + 5, 2),
        )
    ]


def test_shadow_terminal_is_idempotent_for_clean_stop(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    adapter = RecordingShadowAdapter()
    reducer = _reducer(tmp_path, policy_factory, adapter=adapter)

    reducer.clean_stop(reducer._coverage._current_start_ms + 10)

    assert len(adapter.terminals) == 1
    assert adapter.terminals[0][0] == "STOP"
    assert all(commit.cause is not CausalCause.CLEAN_STOP for commit in adapter.settled)


def test_shadow_terminal_is_idempotent_for_failure(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    adapter = RecordingShadowAdapter()
    reducer = _reducer(tmp_path, policy_factory, adapter=adapter)
    monotonic_ms = reducer._coverage._current_start_ms + 10

    reducer.finalize_shadow_failure(monotonic_ms)
    reducer.finalize_shadow_failure(monotonic_ms + 1)

    assert adapter.terminals == [
        ("FAILURE", FactBoundary(1, 0, monotonic_ms, 1)),
    ]


def test_no_adapter_preserves_existing_reducer_surface(
    tmp_path: Path,
    policy_factory: PolicyFactory,
) -> None:
    reducer = _reducer(tmp_path, policy_factory, adapter=None)

    assert reducer.shadow_adapter is None
    assert reducer.business_fingerprint()[0] is None
