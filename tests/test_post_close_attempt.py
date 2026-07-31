from __future__ import annotations

from typing import Literal

import pytest
from short_vol_underwriting import (
    FactBoundary,
    PostCloseAttempt,
    PostCloseAttemptOwner,
    PostCloseAttemptStatus,
    RpcAdmissionRefreshWitness,
    SubscriptionAdmissionRefreshWitness,
    canonical_identity,
)

COMBO_IDENTITY = "sha256:" + "3" * 64
INSTRUMENT_NAME = "BTC-CLOSE-COMBO"
REQUEST_ID = 17


def _boundary(causal_seq: int) -> FactBoundary:
    return FactBoundary(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        session_epoch=1,
        ingress_seq=causal_seq,
        received_monotonic_ms=100 + causal_seq,
        causal_seq=causal_seq,
    )


def _subscription_witness(
    *,
    boundary: FactBoundary,
    snapshot_kind: Literal["snapshot", "change"],
    change_id: int,
    prev_change_id: int | None,
) -> SubscriptionAdmissionRefreshWitness:
    return SubscriptionAdmissionRefreshWitness(
        source_identity=canonical_identity(
            "SubscriptionAdmissionRefreshSourceIdentity",
            boundary.runtime_identity,
            boundary.session_epoch,
            1,
            COMBO_IDENTITY,
            snapshot_kind,
            prev_change_id,
            change_id,
            1_000 + change_id,
            boundary.as_object(),
        ),
        boundary=boundary,
        canonical_combo_identity=COMBO_IDENTITY,
        instrument_name=INSTRUMENT_NAME,
        change_id=change_id,
        source_timestamp_ms=1_000 + change_id,
        snapshot_kind=snapshot_kind,
        session_epoch=boundary.session_epoch,
        subscription_generation=1,
        prev_change_id=prev_change_id,
    )


def _scheduled_attempt() -> PostCloseAttempt:
    origin_boundary = _boundary(2)
    return PostCloseAttempt.schedule(
        anchor_identity="sha256:" + "1" * 64,
        first_close_action_identity="sha256:" + "2" * 64,
        canonical_combo_identity=COMBO_IDENTITY,
        request_id=REQUEST_ID,
        boundary=origin_boundary,
        request_instrument_name=INSTRUMENT_NAME,
        origin_quote_witness=_subscription_witness(
            boundary=origin_boundary,
            snapshot_kind="snapshot",
            change_id=10,
            prev_change_id=None,
        ),
    )


def _rpc_witness(
    *,
    payload_matches_request: bool = True,
    payload_well_formed: bool = True,
) -> RpcAdmissionRefreshWitness:
    origin_boundary = _boundary(2)
    sent_boundary = _boundary(3)
    response_boundary = _boundary(4)
    return RpcAdmissionRefreshWitness(
        source_identity=canonical_identity(
            "RpcAdmissionRefreshSourceIdentity",
            response_boundary.runtime_identity,
            REQUEST_ID,
            "public/get_order_book",
            COMBO_IDENTITY,
            {"instrument_name": INSTRUMENT_NAME, "depth": 10000},
            origin_boundary.as_object(),
            sent_boundary.as_object(),
            11,
            200,
            response_boundary.as_object(),
        ),
        boundary=response_boundary,
        canonical_combo_identity=COMBO_IDENTITY,
        instrument_name=INSTRUMENT_NAME,
        request_params={"instrument_name": INSTRUMENT_NAME, "depth": 10000},
        change_id=11,
        source_timestamp_ms=200,
        request_id=REQUEST_ID,
        candidate_origin_boundary=origin_boundary,
        sent_boundary=sent_boundary,
        market_frontier_change_id=11,
        market_frontier_session_epoch=response_boundary.session_epoch,
        response_matches_frontier=True,
        response_covers_full_quantity=True,
        payload_matches_request=payload_matches_request,
        payload_well_formed=payload_well_formed,
    )


@pytest.mark.parametrize(
    "invalid_payload_flag",
    ("payload_matches_request", "payload_well_formed"),
)
def test_post_close_rpc_malformed_payload_terminalizes_unknown(
    invalid_payload_flag: str,
) -> None:
    attempt = _scheduled_attempt()
    assert attempt.mark_sent(
        request_id=REQUEST_ID,
        boundary=_boundary(3),
        send_budget_ms=30,
    )
    flags = {
        "payload_matches_request": True,
        "payload_well_formed": True,
    }
    flags[invalid_payload_flag] = False

    assert attempt.accept_response(
        witness=_rpc_witness(**flags),
        response_budget_ms=30,
    )

    assert attempt.terminal_status is PostCloseAttemptStatus.ERROR
    assert attempt.terminal_owner is PostCloseAttemptOwner.ORDINARY
    assert attempt.matched_response_identity is None


@pytest.mark.parametrize(
    ("snapshot_kind", "change_id", "prev_change_id"),
    (
        ("snapshot", 9, None),
        ("change", 9, 10),
        ("snapshot", 10, None),
        ("change", 10, 10),
    ),
)
def test_post_close_subscription_requires_change_id_after_origin(
    snapshot_kind: Literal["snapshot", "change"],
    change_id: int,
    prev_change_id: int | None,
) -> None:
    attempt = _scheduled_attempt()
    witness = _subscription_witness(
        boundary=_boundary(3),
        snapshot_kind=snapshot_kind,
        change_id=change_id,
        prev_change_id=prev_change_id,
    )

    assert not attempt.accept_subscription(witness=witness)

    assert attempt.terminal_status is None
    assert attempt.matched_response_identity is None
