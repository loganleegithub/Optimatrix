from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from optimatrix.channels import ChannelId
from optimatrix.decision import (
    DecisionRecord,
    DecisionResult,
    DecisionWindow,
    MarketObservation,
    schedule_decision_windows,
    unassessed_decision_record,
)
from optimatrix.identity import canonical_identity
from optimatrix.scenarios import base_chain, current_expiry, market_context
from optimatrix.session import current_deribit_session


def _window_and_observation(policy):
    observed_at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    session = current_deribit_session(observed_at, phase_policy=policy.session)
    windows = schedule_decision_windows(
        session=session,
        channel_id=policy.channel_id,
        policy=policy.window,
    )
    window = next(item for item in windows if item.starts_at <= observed_at < item.ends_at)
    observation = MarketObservation.capture(
        channel_id=policy.channel_id,
        policy=policy.observation,
        context=market_context(observed_at),
        quotes=base_chain(expiry=current_expiry(observed_at), observed_at=observed_at),
    )
    return session, windows, window, observation


def test_schedule_pre_registers_one_complete_session_population(policy) -> None:
    session, windows, _window, _observation = _window_and_observation(policy)

    assert len(windows) == 96
    assert windows[0].starts_at == session.start
    assert windows[-1].ends_at == session.end
    assert all(left.ends_at == right.starts_at for left, right in pairwise(windows))
    assert len({window.identity for window in windows}) == len(windows)


def test_window_identity_excludes_decision_policy_and_observation(policy) -> None:
    _session, _windows, window, observation = _window_and_observation(policy)
    record = unassessed_decision_record(
        window=window,
        decision_policy_id=policy.identity,
        known_at=window.input_deadline,
        observation=observation,
    )

    assert record.window.identity == window.identity
    assert record.observation_id == observation.identity
    assert record.result is DecisionResult.UNKNOWN
    assert record.blockers == ("DECISION_POLICY_NOT_EVALUATED",)
    alternative_policy = canonical_identity("DecisionPolicyV1", "challenger")
    alternative = replace(record, decision_policy_id=alternative_policy)
    assert alternative.window.identity == window.identity
    assert alternative.identity != record.identity


def test_market_observation_identity_is_causal_and_content_addressed(policy) -> None:
    _session, _windows, _window, observation = _window_and_observation(policy)
    changed_quote = replace(
        observation.quotes[0],
        source_timestamp_ms=observation.quotes[0].source_timestamp_ms + 1,
    )
    changed = replace(observation, quotes=(changed_quote, *observation.quotes[1:]))

    assert observation.identity == replace(observation).identity
    assert observation.identity != changed.identity


def test_missing_candidate_readiness_metadata_is_global_unknown(policy) -> None:
    _session, _windows, _window, observation = _window_and_observation(policy)
    context = replace(
        observation.context,
        evidence=replace(
            observation.context.evidence,
            requested_books=tuple(
                sorted((*observation.context.evidence.requested_books, "BTC-X-97000-P"))
            ),
        ),
    )

    malformed = MarketObservation.capture(
        channel_id=policy.channel_id,
        policy=policy.observation,
        context=context,
        quotes=observation.quotes,
    )

    assert malformed.data_health_blockers == ("OPTION_BOOK_READINESS_EVIDENCE_MISMATCH",)


def test_decision_record_embeds_complete_roundtrippable_observation(policy) -> None:
    _session, _windows, window, observation = _window_and_observation(policy)
    record = unassessed_decision_record(
        window=window,
        decision_policy_id=policy.identity,
        known_at=window.input_deadline,
        observation=observation,
    )

    encoded = record.as_object()
    embedded = encoded["observation"]
    assert isinstance(embedded, dict)
    context = embedded["context"]
    quotes = embedded["quotes"]
    expected_context = observation.as_object()["context"]
    assert isinstance(context, dict)
    assert isinstance(expected_context, dict)
    assert context["evidence"] == expected_context["evidence"]
    assert isinstance(quotes, list) and quotes
    first_quote = quotes[0]
    assert isinstance(first_quote, dict)
    assert first_quote["bid"] and first_quote["ask"]
    assert first_quote["tick_schedule"]
    assert first_quote["source_timestamp_ms"] == observation.quotes[0].source_timestamp_ms
    assert first_quote["received_timestamp_ms"] == observation.quotes[0].received_timestamp_ms

    restored = DecisionRecord.from_object(encoded)
    assert restored == record
    assert restored.observation == observation
    assert restored.observation_id == observation.identity


def test_decision_record_codec_rejects_nested_observation_tampering_and_v1_shape(policy) -> None:
    _session, _windows, window, observation = _window_and_observation(policy)
    record = unassessed_decision_record(
        window=window,
        decision_policy_id=policy.identity,
        known_at=window.input_deadline,
        observation=observation,
    )
    tampered = deepcopy(record.as_object())
    embedded = tampered["observation"]
    assert isinstance(embedded, dict)
    quotes = embedded["quotes"]
    assert isinstance(quotes, list) and quotes and isinstance(quotes[0], dict)
    quotes[0]["continuity_epoch"] = observation.quotes[0].continuity_epoch + 1

    with pytest.raises(ValueError, match="MarketObservation identity mismatch"):
        DecisionRecord.from_object(tampered)

    legacy_shape = record.as_object()
    del legacy_shape["observation"]
    with pytest.raises(ValueError, match="fields are invalid"):
        DecisionRecord.from_object(legacy_shape)


def test_stale_and_future_quotes_are_data_health_unknown(policy) -> None:
    _session, _windows, _window, observation = _window_and_observation(policy)
    stale_quotes = tuple(
        replace(
            quote,
            source_timestamp_ms=quote.source_timestamp_ms - 86_400_000,
            received_timestamp_ms=quote.received_timestamp_ms - 86_400_000,
        )
        for quote in observation.quotes
    )
    stale = MarketObservation.capture(
        channel_id=policy.channel_id,
        policy=policy.observation,
        context=observation.context,
        quotes=stale_quotes,
    )
    assert "MARKET_SOURCE_STALE" in stale.data_health_blockers
    assert "MARKET_RECEIPT_STALE" in stale.data_health_blockers

    known_at_ms = int(observation.context.now.timestamp() * 1000)
    future_quotes = tuple(
        replace(
            quote,
            source_timestamp_ms=known_at_ms + 1_000,
            received_timestamp_ms=known_at_ms + 1_050,
        )
        for quote in observation.quotes
    )
    future = MarketObservation.capture(
        channel_id=policy.channel_id,
        policy=policy.observation,
        context=observation.context,
        quotes=future_quotes,
    )
    assert "MARKET_SOURCE_IN_FUTURE" in future.data_health_blockers
    assert "MARKET_RECEIPT_IN_FUTURE" in future.data_health_blockers


def test_missing_and_late_observation_are_unknown_not_negative(policy) -> None:
    _session, _windows, window, _observation = _window_and_observation(policy)
    with pytest.raises(ValueError, match="before the input deadline"):
        unassessed_decision_record(
            window=window,
            decision_policy_id=policy.identity,
            known_at=window.ends_at,
            observation=None,
        )

    missing = unassessed_decision_record(
        window=window,
        decision_policy_id=policy.identity,
        known_at=window.input_deadline + timedelta(minutes=5),
        observation=None,
    )
    late_context = market_context(window.ends_at)
    late_observation = MarketObservation.capture(
        channel_id=policy.channel_id,
        policy=policy.observation,
        context=late_context,
        quotes=base_chain(expiry=current_expiry(window.ends_at), observed_at=window.ends_at),
    )
    late = unassessed_decision_record(
        window=window,
        decision_policy_id=policy.identity,
        known_at=window.input_deadline + timedelta(minutes=5),
        observation=late_observation,
    )

    assert missing.result is DecisionResult.UNKNOWN
    assert missing.blockers == ("NO_OBSERVATION",)
    assert missing.observation is None
    assert missing.as_object()["observation"] is None
    assert DecisionRecord.from_object(missing.as_object()) == missing
    assert late.result is DecisionResult.UNKNOWN
    assert late.blockers == ("OBSERVATION_OUTSIDE_WINDOW",)
    assert late.observation is None
    assert late.observation_id is None


def test_window_codec_rejects_identity_tampering(policy) -> None:
    _session, _windows, window, _observation = _window_and_observation(policy)
    encoded = window.as_object()
    assert DecisionWindow.from_object(encoded) == window
    encoded["channel_id"] = ChannelId.INVERSE_ETH_SHORT_VOL.value
    with pytest.raises(ValueError, match="identity mismatch"):
        DecisionWindow.from_object(encoded)
