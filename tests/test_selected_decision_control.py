from __future__ import annotations

import pytest
from short_vol_underwriting import (
    ComponentLegRole,
    DecisionControlAttempt,
    DecisionControlAttemptOutcome,
    DecisionControlRefreshClassification,
    FactBoundary,
    RpcComponentLegRefreshWitness,
    RuntimeBindings,
    canonical_identity,
    component_pair_witness,
    designate_selected_decision_episode,
    selected_decision_batch_identity,
    selected_decision_designation_key,
    selected_decision_rule_identity,
)
from short_vol_underwriting.constants import (
    INVERSE_BTC_POSITION_POLICY_IDENTITY,
    INVERSE_BTC_RADAR_POLICY_IDENTITY,
    INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
)


def _boundary(causal_seq: int, monotonic_ms: int) -> FactBoundary:
    return FactBoundary(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        session_epoch=1,
        ingress_seq=causal_seq,
        received_monotonic_ms=monotonic_ms,
        causal_seq=causal_seq,
    )


def _bindings() -> RuntimeBindings:
    return RuntimeBindings(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        radar_policy_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_policy_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_policy_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )


def _witness(
    *,
    role: ComponentLegRole,
    request_id: int,
    option_identity: str,
    instrument_name: str,
    origin: FactBoundary,
    sent: FactBoundary,
    response: FactBoundary,
    source_timestamp_ms: int,
    response_covers_full_quantity: bool = True,
    payload_matches_request: bool = True,
    payload_well_formed: bool = True,
) -> RpcComponentLegRefreshWitness:
    params = {"instrument_name": instrument_name, "depth": 10000}
    source_identity = canonical_identity(
        "RpcComponentLegRefreshSourceIdentity",
        response.runtime_identity,
        request_id,
        role.value,
        "public/get_order_book",
        option_identity,
        params,
        origin.as_object(),
        sent.as_object(),
        1,
        11,
        source_timestamp_ms,
        response.as_object(),
    )
    return RpcComponentLegRefreshWitness(
        source_identity=source_identity,
        boundary=response,
        role=role,
        canonical_option_identity=option_identity,
        instrument_name=instrument_name,
        request_params=params,
        change_id=11,
        source_timestamp_ms=source_timestamp_ms,
        request_id=request_id,
        owner_origin_boundary=origin,
        sent_boundary=sent,
        global_continuity_epoch=1,
        response_covers_full_quantity=response_covers_full_quantity,
        payload_matches_request=payload_matches_request,
        payload_well_formed=payload_well_formed,
    )


def test_selected_decision_rule_batch_and_designation_are_pre_outcome_policy_bound() -> None:
    bindings = _bindings()

    rule = selected_decision_rule_identity(bindings=bindings)
    first = selected_decision_batch_identity(
        bindings=bindings,
        activation_causal_seq=7,
    )
    same = selected_decision_batch_identity(
        bindings=bindings,
        activation_causal_seq=7,
    )
    next_batch = selected_decision_batch_identity(
        bindings=bindings,
        activation_causal_seq=8,
    )
    first_episode = f"{bindings.runtime_identity}:{bindings.radar_policy_identity}:BTC-FIRST:7"
    second_episode = f"{bindings.runtime_identity}:{bindings.radar_policy_identity}:BTC-SECOND:7"
    designation_keys = {
        episode: selected_decision_designation_key(
            bindings=bindings,
            batch_identity=first,
            episode_identity=episode,
        )
        for episode in (first_episode, second_episode)
    }
    designated = designate_selected_decision_episode(
        bindings=bindings,
        batch_identity=first,
        episode_identities=(second_episode, first_episode),
    )
    reordered = designate_selected_decision_episode(
        bindings=bindings,
        batch_identity=first,
        episode_identities=(first_episode, second_episode),
    )

    assert rule.startswith("sha256:")
    assert first == same
    assert next_batch != first
    assert designated == reordered
    assert designated == min(designation_keys, key=designation_keys.__getitem__)


def test_decision_control_attempt_opens_only_from_one_strictly_later_valid_pair() -> None:
    origin = _boundary(1, 100)
    short_identity = "sha256:" + "6" * 64
    long_identity = "sha256:" + "7" * 64
    attempt = DecisionControlAttempt.schedule(
        selection_identity="sha256:" + "5" * 64,
        short_option_identity=short_identity,
        long_option_identity=long_identity,
        short_request_id=41,
        long_request_id=42,
        boundary=origin,
        short_instrument_name="BTC-SHORT",
        long_instrument_name="BTC-LONG",
    )

    intents = attempt.take_request_intents()
    assert [intent.purpose for intent in intents] == [
        "COMPONENT_DECISION_CONTROL_SHORT_REFRESH",
        "COMPONENT_DECISION_CONTROL_LONG_REFRESH",
    ]
    short_sent = _boundary(2, 110)
    long_sent = _boundary(3, 111)
    assert attempt.mark_sent(request_id=41, boundary=short_sent, send_budget_ms=30_000)
    assert attempt.mark_sent(request_id=42, boundary=long_sent, send_budget_ms=30_000)
    pair = component_pair_witness(
        short=_witness(
            role=ComponentLegRole.SHORT,
            request_id=41,
            option_identity=short_identity,
            instrument_name="BTC-SHORT",
            origin=origin,
            sent=short_sent,
            response=_boundary(4, 120),
            source_timestamp_ms=1_000,
        ),
        long=_witness(
            role=ComponentLegRole.LONG,
            request_id=42,
            option_identity=long_identity,
            instrument_name="BTC-LONG",
            origin=origin,
            sent=long_sent,
            response=_boundary(5, 121),
            source_timestamp_ms=1_001,
        ),
    )

    assert attempt.accept_pair(
        witness=pair,
        response_budget_ms=30_000,
        maximum_source_skew_ms=6_000,
        maximum_receive_skew_ms=4_000,
        classification=DecisionControlRefreshClassification.REFRESHED_WATCH_OR_ABSTAIN,
    )
    assert attempt.terminal_outcome is DecisionControlAttemptOutcome.CONTROL_OPENED
    assert attempt.terminal_boundary == pair.boundary
    assert attempt.take_request_intents() == ()


def test_decision_control_attempt_fails_closed_on_pair_skew() -> None:
    origin = _boundary(1, 100)
    short_identity = "sha256:" + "6" * 64
    long_identity = "sha256:" + "7" * 64
    attempt = DecisionControlAttempt.schedule(
        selection_identity="sha256:" + "5" * 64,
        short_option_identity=short_identity,
        long_option_identity=long_identity,
        short_request_id=41,
        long_request_id=42,
        boundary=origin,
        short_instrument_name="BTC-SHORT",
        long_instrument_name="BTC-LONG",
    )
    attempt.take_request_intents()
    short_sent = _boundary(2, 110)
    long_sent = _boundary(3, 111)
    attempt.mark_sent(request_id=41, boundary=short_sent, send_budget_ms=30_000)
    attempt.mark_sent(request_id=42, boundary=long_sent, send_budget_ms=30_000)
    pair = component_pair_witness(
        short=_witness(
            role=ComponentLegRole.SHORT,
            request_id=41,
            option_identity=short_identity,
            instrument_name="BTC-SHORT",
            origin=origin,
            sent=short_sent,
            response=_boundary(4, 120),
            source_timestamp_ms=1_000,
        ),
        long=_witness(
            role=ComponentLegRole.LONG,
            request_id=42,
            option_identity=long_identity,
            instrument_name="BTC-LONG",
            origin=origin,
            sent=long_sent,
            response=_boundary(5, 5_000),
            source_timestamp_ms=8_000,
        ),
    )

    attempt.accept_pair(
        witness=pair,
        response_budget_ms=30_000,
        maximum_source_skew_ms=6_000,
        maximum_receive_skew_ms=4_000,
        classification=DecisionControlRefreshClassification.REFRESHED_WATCH_OR_ABSTAIN,
    )

    assert attempt.terminal_outcome is DecisionControlAttemptOutcome.UNKNOWN_CONSUMED
    assert attempt.terminal_unknown_reasons == (
        "COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED",
        "COMPONENT_PAIR_RECEIVE_SKEW_EXCEEDED",
    )


def test_decision_control_attempt_reports_every_non_timing_pair_blocker() -> None:
    origin = _boundary(1, 100)
    short_identity = "sha256:" + "6" * 64
    long_identity = "sha256:" + "7" * 64
    attempt = DecisionControlAttempt.schedule(
        selection_identity="sha256:" + "5" * 64,
        short_option_identity=short_identity,
        long_option_identity=long_identity,
        short_request_id=41,
        long_request_id=42,
        boundary=origin,
        short_instrument_name="BTC-SHORT",
        long_instrument_name="BTC-LONG",
    )
    attempt.take_request_intents()
    short_sent = _boundary(2, 110)
    long_sent = _boundary(3, 111)
    attempt.mark_sent(request_id=41, boundary=short_sent, send_budget_ms=30_000)
    attempt.mark_sent(request_id=42, boundary=long_sent, send_budget_ms=30_000)
    pair = component_pair_witness(
        short=_witness(
            role=ComponentLegRole.SHORT,
            request_id=41,
            option_identity=short_identity,
            instrument_name="BTC-SHORT",
            origin=origin,
            sent=short_sent,
            response=_boundary(4, 40_120),
            source_timestamp_ms=1_000,
            response_covers_full_quantity=False,
            payload_matches_request=False,
        ),
        long=_witness(
            role=ComponentLegRole.LONG,
            request_id=42,
            option_identity=long_identity,
            instrument_name="BTC-LONG",
            origin=origin,
            sent=long_sent,
            response=_boundary(5, 40_121),
            source_timestamp_ms=1_001,
        ),
    )

    attempt.accept_pair(
        witness=pair,
        response_budget_ms=30_000,
        maximum_source_skew_ms=6_000,
        maximum_receive_skew_ms=4_000,
        classification=DecisionControlRefreshClassification.REFRESHED_WATCH_OR_ABSTAIN,
    )

    assert attempt.terminal_outcome is DecisionControlAttemptOutcome.UNKNOWN_CONSUMED
    assert attempt.terminal_unknown_reasons == (
        "COMPONENT_PAIR_SHORT_PAYLOAD_REQUEST_MISMATCH",
        "COMPONENT_PAIR_SHORT_FULL_QUANTITY_NOT_COVERED",
        "COMPONENT_PAIR_SHORT_RESPONSE_BUDGET_EXCEEDED",
        "COMPONENT_PAIR_LONG_RESPONSE_BUDGET_EXCEEDED",
    )


@pytest.mark.parametrize(
    ("terminal_path", "expected_reason"),
    (
        ("send_budget", "COMPONENT_DECISION_CONTROL_SEND_BUDGET_EXCEEDED"),
        ("request_error", "COMPONENT_DECISION_CONTROL_REQUEST_ERROR"),
    ),
)
def test_decision_control_attempt_unknown_terminal_always_has_exact_reason(
    terminal_path: str,
    expected_reason: str,
) -> None:
    origin = _boundary(1, 100)
    attempt = DecisionControlAttempt.schedule(
        selection_identity="sha256:" + "5" * 64,
        short_option_identity="sha256:" + "6" * 64,
        long_option_identity="sha256:" + "7" * 64,
        short_request_id=41,
        long_request_id=42,
        boundary=origin,
        short_instrument_name="BTC-SHORT",
        long_instrument_name="BTC-LONG",
    )
    attempt.take_request_intents()
    if terminal_path == "send_budget":
        attempt.mark_sent(
            request_id=41,
            boundary=_boundary(2, 30_101),
            send_budget_ms=30_000,
        )
    else:
        attempt.fail_request(
            request_id=41,
            source_identity="sha256:" + "8" * 64,
            boundary=_boundary(2, 101),
            unknown_reason=expected_reason,
        )

    assert attempt.terminal_outcome is DecisionControlAttemptOutcome.UNKNOWN_CONSUMED
    assert attempt.terminal_unknown_reasons == (expected_reason,)
