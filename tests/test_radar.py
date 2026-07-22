from __future__ import annotations

import json
from dataclasses import replace

import pytest
from market_tape import CanonicalEvent, EventKind
from options_domain import ComboQuote, build_surface_summary
from radar_runtime.fixture import build_fixture_events, replay_fixture
from short_vol_radar import (
    DecisionInputContract,
    RadarAction,
    RadarPolicy,
    RadarProjector,
    estimate_path_risk,
    evaluate_radar,
)


def test_fixture_produces_transparent_research_candidate() -> None:
    frame, decision = replay_fixture(build_fixture_events())

    assert decision.action is RadarAction.RESEARCH_CANDIDATE
    assert decision.assessment is not None
    assert decision.assessment.all_passed
    assert decision.assessment.risk.method_id == "OBSERVED_PATH_STRESS_FIXED_PRIOR"
    assert decision.assessment.conservative_margin_usdc > 0
    assert decision.assessment.claim_reserve_usdc >= (
        decision.assessment.stress_intrinsic_payout_usdc
    )
    assert decision.horizon_seconds in {1_800, 3_600, 7_200, 14_400}
    assert decision.frame_digest == frame.digest


def test_unknown_lookback_fails_closed() -> None:
    frame, _ = replay_fixture(build_fixture_events())
    unknown = replace(
        frame,
        windows=tuple(
            replace(
                item,
                coverage=replace(
                    item.coverage,
                    price_complete=False,
                    incomplete_reasons=("PRICE_LOOKBACK_INCOMPLETE",),
                ),
                path=None,
            )
            for item in frame.windows
        ),
    )
    decision = evaluate_radar(unknown)
    assert decision.action is RadarAction.ABSTAIN
    assert decision.reason == "PATH_RISK_UNKNOWN"


def test_one_missing_required_window_makes_risk_unknown() -> None:
    frame, _ = replay_fixture(build_fixture_events())
    first = frame.windows[0]
    incomplete = replace(
        first,
        coverage=replace(
            first.coverage,
            price_complete=False,
            incomplete_reasons=("TEST_MISSING_REQUIRED_WINDOW",),
        ),
        path=None,
    )
    risk = estimate_path_risk(replace(frame, windows=(incomplete, *frame.windows[1:])), 1_800)

    assert not risk.complete
    assert "REQUIRED_PATH_WINDOW_UNKNOWN" in risk.incomplete_reasons


def test_input_contract_and_policy_have_separate_identities() -> None:
    input_contract = DecisionInputContract()
    policy = RadarPolicy()

    assert replace(input_contract, catalog_max_age_ms=420_000).digest != input_contract.digest
    assert RadarPolicy().digest == policy.digest
    assert replace(
        policy, minimum_credit_to_friction=policy.minimum_credit_to_friction * 2
    ).digest != (policy.digest)
    assert DecisionInputContract().digest == input_contract.digest


def test_scheduled_block_cannot_become_candidate() -> None:
    frame, _ = replay_fixture(build_fixture_events())
    blocked = replace(
        frame,
        scheduled_block="FOMC",
        complete=False,
        completeness_reasons=("SCHEDULED_BLOCK",),
    )
    decision = evaluate_radar(blocked)
    assert decision.action is not RadarAction.RESEARCH_CANDIDATE


def test_future_market_changes_do_not_rewrite_entry_decision() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    future_capture_seq = frame.as_of_capture_seq + 100
    changed_quotes = tuple(
        replace(
            item,
            bid_iv=None,
            ask_iv=None,
            mark_iv=None,
            ticker_source_capture_seq=future_capture_seq,
        )
        for item in frame.option_quotes
    )
    assert frame.market_as_of is not None
    future = replace(
        frame,
        as_of_capture_seq=future_capture_seq,
        collector_elapsed_ms=frame.collector_elapsed_ms + 1,
        option_quotes=changed_quotes,
        surface=build_surface_summary(
            changed_quotes,
            as_of=frame.market_as_of,
        ),
        source_capture_seqs=tuple(sorted({*frame.source_capture_seqs, future_capture_seq})),
    )

    assert decision.digest == evaluate_radar(frame).digest
    assert future.digest != frame.digest
    assert decision.frame_capture_seq < future.as_of_capture_seq


def test_reference_dynamics_advance_only_on_new_reference_ticker() -> None:
    events = build_fixture_events()
    projector = RadarProjector()
    for event in events:
        projector.ingest(event)

    prior_reference = events[-1]
    assert prior_reference.event_kind is EventKind.TICKER
    assert prior_reference.exchange_timestamp_ms is not None
    reference_timestamp = prior_reference.exchange_timestamp_ms + 1
    reference_payload = json.loads(prior_reference.raw_payload)
    reference_payload["timestamp"] = reference_timestamp
    reference_payload["funding_8h"] = "0.002"
    reference = replace(
        prior_reference,
        capture_seq=prior_reference.capture_seq + 1,
        collector_received_at_ms=prior_reference.collector_received_at_ms + 1,
        collector_elapsed_ms=prior_reference.collector_elapsed_ms + 1,
        exchange_timestamp_ms=reference_timestamp,
        raw_payload=json.dumps(reference_payload, sort_keys=True, separators=(",", ":")),
    )
    reference_frame = projector.ingest(reference)
    assert reference_frame is not None
    assert (
        reference_frame.reference_dynamics.prior_reference_capture_seq
        == prior_reference.capture_seq
    )

    prior_trade = next(event for event in reversed(events) if event.event_kind is EventKind.TRADE)
    trade_payload = json.loads(prior_trade.raw_payload)
    prior_trades = trade_payload["trades"]
    assert isinstance(prior_trades, list)
    trade = dict(prior_trades[-1])
    trade_timestamp = reference_timestamp + 1
    trade["trade_seq"] = int(str(trade["trade_seq"])) + 1
    trade["timestamp"] = trade_timestamp
    trade_event = CanonicalEvent(
        capture_seq=reference.capture_seq + 1,
        collector_received_at_ms=reference.collector_received_at_ms + 1,
        collector_elapsed_ms=reference.collector_elapsed_ms + 1,
        exchange_timestamp_ms=trade_timestamp,
        channel=prior_trade.channel,
        event_kind=EventKind.TRADE,
        instrument_name=prior_trade.instrument_name,
        raw_payload=json.dumps(
            {"trades": [trade]},
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    trade_frame = projector.ingest(trade_event)
    assert trade_frame is not None
    assert trade_frame.reference_dynamics == reference_frame.reference_dynamics

    option_template = next(
        event
        for event in reversed(events)
        if event.event_kind is EventKind.TICKER
        and event.instrument_name != prior_reference.instrument_name
    )
    option_payload = json.loads(option_template.raw_payload)
    option_timestamp = trade_timestamp + 1
    option_payload["timestamp"] = option_timestamp
    option_event = replace(
        option_template,
        capture_seq=trade_event.capture_seq + 1,
        collector_received_at_ms=trade_event.collector_received_at_ms + 1,
        collector_elapsed_ms=trade_event.collector_elapsed_ms + 1,
        exchange_timestamp_ms=option_timestamp,
        raw_payload=json.dumps(option_payload, sort_keys=True, separators=(",", ":")),
    )
    assert projector.ingest(option_event) is None
    option_frame = projector.finalize()
    assert option_frame.reference_dynamics == reference_frame.reference_dynamics

    heartbeat = CanonicalEvent(
        capture_seq=option_event.capture_seq + 1,
        collector_received_at_ms=option_event.collector_received_at_ms + 1,
        collector_elapsed_ms=option_event.collector_elapsed_ms + 1,
        exchange_timestamp_ms=None,
        channel="heartbeat",
        event_kind=EventKind.HEARTBEAT,
        instrument_name=None,
        raw_payload='{"type":"heartbeat"}',
    )
    assert projector.ingest(heartbeat) is None
    heartbeat_frame = projector.finalize()
    assert heartbeat_frame.reference_dynamics == reference_frame.reference_dynamics
    assert prior_reference.capture_seq in heartbeat_frame.source_capture_seqs


def test_combo_quote_source_must_be_in_decision_frame_lineage() -> None:
    frame, _ = replay_fixture(build_fixture_events())
    assert frame.option_quotes[0].bid_amount is not None
    assert frame.option_quotes[0].ask_amount is not None
    combo = ComboQuote(
        combo_id="combo",
        short_instrument=frame.option_quotes[0].instrument_name,
        long_instrument=frame.option_quotes[1].instrument_name,
        bid=None,
        ask=None,
        bid_amount=frame.option_quotes[0].bid_amount,
        ask_amount=frame.option_quotes[0].ask_amount,
        quote_age_ms=0,
        fresh=True,
        valid=True,
        source_capture_seq=frame.as_of_capture_seq,
    )

    with pytest.raises(ValueError, match="provenance"):
        replace(
            frame,
            combo_quotes=(replace(combo, source_capture_seq=frame.as_of_capture_seq + 1),),
        )

    bound = replace(frame, combo_quotes=(combo,))
    assert combo.source_capture_seq in bound.source_capture_seqs
