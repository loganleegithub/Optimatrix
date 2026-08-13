from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self

from optimatrix.channels import ChannelId
from optimatrix.identity import canonical_identity, canonical_value, require_identity
from optimatrix.market import MarketContext, OptionQuote
from optimatrix.policy import ObservationPolicy, WindowSchedulePolicy
from optimatrix.session import DeribitSession


class DecisionResult(StrEnum):
    UNKNOWN = "UNKNOWN"
    ABSTAIN = "ABSTAIN"
    REVIEW = "REVIEW"
    CANDIDATE = "CANDIDATE"


@dataclass(frozen=True)
class DecisionWindow:
    channel_id: ChannelId
    market_session_id: str
    schedule_policy_id: str
    starts_at: datetime
    ends_at: datetime
    input_deadline: datetime

    def __post_init__(self) -> None:
        require_identity(self.schedule_policy_id, "schedule_policy_id")
        starts_at = _utc(self.starts_at, "starts_at")
        ends_at = _utc(self.ends_at, "ends_at")
        input_deadline = _utc(self.input_deadline, "input_deadline")
        if not self.market_session_id:
            raise ValueError("market_session_id must be non-empty")
        if starts_at >= ends_at or ends_at > input_deadline:
            raise ValueError("DecisionWindow boundaries are invalid")

    @property
    def identity(self) -> str:
        return canonical_identity(
            "DecisionWindowV1",
            self.channel_id,
            self.market_session_id,
            self.schedule_policy_id,
            self.starts_at,
            self.ends_at,
        )

    def as_object(self) -> dict[str, object]:
        return {
            "decision_window_id": self.identity,
            "channel_id": self.channel_id.value,
            "market_session_id": self.market_session_id,
            "schedule_policy_id": self.schedule_policy_id,
            "starts_at": _iso(self.starts_at),
            "ends_at": _iso(self.ends_at),
            "input_deadline": _iso(self.input_deadline),
        }

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "decision_window")
        window = cls(
            channel_id=ChannelId(_text(item, "channel_id")),
            market_session_id=_text(item, "market_session_id"),
            schedule_policy_id=_text(item, "schedule_policy_id"),
            starts_at=_datetime(item, "starts_at"),
            ends_at=_datetime(item, "ends_at"),
            input_deadline=_datetime(item, "input_deadline"),
        )
        if _text(item, "decision_window_id") != window.identity:
            raise ValueError("DecisionWindow identity mismatch")
        return window


def schedule_decision_windows(
    *,
    session: DeribitSession,
    channel_id: ChannelId,
    policy: WindowSchedulePolicy,
) -> tuple[DecisionWindow, ...]:
    step = timedelta(minutes=policy.cadence_minutes)
    grace = timedelta(seconds=policy.input_grace_seconds)
    cursor = session.start
    windows: list[DecisionWindow] = []
    while cursor < session.end:
        end = min(cursor + step, session.end)
        windows.append(
            DecisionWindow(
                channel_id=channel_id,
                market_session_id=session.session_id,
                schedule_policy_id=policy.identity,
                starts_at=cursor,
                ends_at=end,
                input_deadline=end + grace,
            )
        )
        cursor = end
    return tuple(windows)


@dataclass(frozen=True)
class MarketObservation:
    channel_id: ChannelId
    data_health_policy_id: str
    observed_at: datetime
    known_at: datetime
    context: MarketContext
    quotes: tuple[OptionQuote, ...]
    data_health_blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        require_identity(self.data_health_policy_id, "data_health_policy_id")
        observed_at = _utc(self.observed_at, "observed_at")
        known_at = _utc(self.known_at, "known_at")
        if observed_at > known_at:
            raise ValueError("observation cannot be known before it is observed")
        if self.context.now != self.observed_at:
            raise ValueError("MarketObservation boundary must match MarketContext")
        context_blockers = self.context.evidence_blockers
        if self.data_health_blockers[: len(context_blockers)] != context_blockers:
            raise ValueError("MarketObservation DataHealth does not match MarketContext")
        if len({quote.instrument_name for quote in self.quotes}) != len(self.quotes):
            raise ValueError("MarketObservation quotes must have unique instruments")

    @property
    def identity(self) -> str:
        return canonical_identity(
            "MarketObservationV1",
            self.channel_id,
            self.data_health_policy_id,
            self.observed_at,
            self.known_at,
            self.context,
            tuple(sorted(self.quotes, key=lambda quote: quote.instrument_name)),
            self.data_health_blockers,
        )

    @classmethod
    def capture(
        cls,
        *,
        channel_id: ChannelId,
        policy: ObservationPolicy,
        context: MarketContext,
        quotes: tuple[OptionQuote, ...],
    ) -> Self:
        blockers = list(context.evidence_blockers)
        quote_names = {quote.instrument_name for quote in quotes}
        if quote_names != set(context.evidence.usable_books):
            blockers.append("OBSERVATION_UNIVERSE_MISMATCH")
        if context.evidence.maximum_market_age_ms != policy.maximum_age_ms:
            blockers.append("DATA_HEALTH_POLICY_AGE_MISMATCH")
        if not quotes:
            blockers.append("NO_OPTION_QUOTES")
        if len({quote.continuity_epoch for quote in quotes}) > 1:
            blockers.append("MULTIPLE_CONTINUITY_EPOCHS")
        if quotes:
            known_at_ms = int(context.now.timestamp() * 1000)
            source_span = max(quote.source_timestamp_ms for quote in quotes) - min(
                quote.source_timestamp_ms for quote in quotes
            )
            receive_span = max(quote.received_timestamp_ms for quote in quotes) - min(
                quote.received_timestamp_ms for quote in quotes
            )
            if source_span > policy.maximum_source_span_ms:
                blockers.append("MARKET_SOURCE_SPAN_EXCEEDED")
            if receive_span > policy.maximum_receive_span_ms:
                blockers.append("MARKET_RECEIVE_SPAN_EXCEEDED")
            if any(quote.source_timestamp_ms > quote.received_timestamp_ms for quote in quotes):
                blockers.append("MARKET_SOURCE_AFTER_RECEIPT")
            if any(quote.source_timestamp_ms > known_at_ms for quote in quotes):
                blockers.append("MARKET_SOURCE_IN_FUTURE")
            if any(quote.received_timestamp_ms > known_at_ms for quote in quotes):
                blockers.append("MARKET_RECEIPT_IN_FUTURE")
            if any(
                known_at_ms - quote.source_timestamp_ms > policy.maximum_age_ms for quote in quotes
            ):
                blockers.append("MARKET_SOURCE_STALE")
            if any(
                known_at_ms - quote.received_timestamp_ms > policy.maximum_age_ms
                for quote in quotes
            ):
                blockers.append("MARKET_RECEIPT_STALE")
        return cls(
            channel_id=channel_id,
            data_health_policy_id=policy.identity,
            observed_at=context.now,
            known_at=context.now,
            context=context,
            quotes=quotes,
            data_health_blockers=tuple(dict.fromkeys(blockers)),
        )


@dataclass(frozen=True)
class DecisionRecord:
    window: DecisionWindow
    decision_policy_id: str
    known_at: datetime
    observation_id: str | None
    result: DecisionResult
    blockers: tuple[str, ...]
    selected_structure_id: str | None = None
    risk_allocation_id: str | None = None
    selected_structure_json: str | None = None
    risk_allocation_json: str | None = None

    def __post_init__(self) -> None:
        require_identity(self.decision_policy_id, "decision_policy_id")
        _utc(self.known_at, "known_at")
        if self.observation_id is not None:
            require_identity(self.observation_id, "observation_id")
        if self.selected_structure_id is not None:
            require_identity(self.selected_structure_id, "selected_structure_id")
        if self.risk_allocation_id is not None:
            require_identity(self.risk_allocation_id, "risk_allocation_id")
        if (self.selected_structure_id is None) != (self.selected_structure_json is None):
            raise ValueError("selected structure identity and payload must appear together")
        if (self.risk_allocation_id is None) != (self.risk_allocation_json is None):
            raise ValueError("risk allocation identity and payload must appear together")
        if self.risk_allocation_id is not None and self.selected_structure_id is None:
            raise ValueError("risk allocation requires a selected structure")
        if len(set(self.blockers)) != len(self.blockers) or any(not item for item in self.blockers):
            raise ValueError("DecisionRecord blockers must be unique non-empty strings")
        if self.result is DecisionResult.UNKNOWN and not self.blockers:
            raise ValueError("UNKNOWN DecisionRecord requires a blocker")
        if self.result is DecisionResult.CANDIDATE and (
            self.blockers
            or self.observation_id is None
            or self.selected_structure_id is None
            or self.risk_allocation_id is None
            or self.selected_structure_json is None
            or self.risk_allocation_json is None
        ):
            raise ValueError(
                "CANDIDATE requires observation, structure, allocation, and no blockers"
            )
        if self.selected_structure is not None:
            candidate_id = self.selected_structure.get("candidate_id")
            if candidate_id != self.selected_structure_id:
                raise ValueError("selected structure payload does not match its identity")
        if self.risk_allocation is not None:
            allocation_id = self.risk_allocation.get("allocation_id")
            candidate_id = self.risk_allocation.get("candidate_id")
            if allocation_id != self.risk_allocation_id:
                raise ValueError("risk allocation payload does not match its identity")
            if candidate_id != self.selected_structure_id:
                raise ValueError("risk allocation does not bind the selected structure")

    @property
    def selected_structure(self) -> dict[str, object] | None:
        return _payload_mapping(self.selected_structure_json, "selected_structure")

    @property
    def risk_allocation(self) -> dict[str, object] | None:
        return _payload_mapping(self.risk_allocation_json, "risk_allocation")

    @property
    def identity(self) -> str:
        return canonical_identity(
            "DecisionRecordV1",
            self.window.identity,
            self.decision_policy_id,
            self.known_at,
            self.observation_id,
            self.result,
            self.blockers,
            self.selected_structure_id,
            self.risk_allocation_id,
            self.selected_structure_json,
            self.risk_allocation_json,
        )

    @property
    def earliest_blocker(self) -> str | None:
        return self.blockers[0] if self.blockers else None

    def as_object(self) -> dict[str, object]:
        return {
            "decision_record_id": self.identity,
            "window": self.window.as_object(),
            "decision_policy_id": self.decision_policy_id,
            "known_at": _iso(self.known_at),
            "observation_id": self.observation_id,
            "result": self.result.value,
            "blockers": list(self.blockers),
            "selected_structure_id": self.selected_structure_id,
            "risk_allocation_id": self.risk_allocation_id,
            "selected_structure": self.selected_structure,
            "risk_allocation": self.risk_allocation,
        }

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "decision_record")
        blockers = item.get("blockers")
        if not isinstance(blockers, list) or not all(isinstance(value, str) for value in blockers):
            raise ValueError("decision_record.blockers must be an array of strings")
        observation_id = item.get("observation_id")
        if observation_id is not None and not isinstance(observation_id, str):
            raise ValueError("decision_record.observation_id must be text or null")
        selected_structure_id = _optional_text(item, "selected_structure_id")
        risk_allocation_id = _optional_text(item, "risk_allocation_id")
        selected_structure = _optional_mapping(item, "selected_structure")
        risk_allocation = _optional_mapping(item, "risk_allocation")
        record = cls(
            window=DecisionWindow.from_object(item.get("window")),
            decision_policy_id=_text(item, "decision_policy_id"),
            known_at=_datetime(item, "known_at"),
            observation_id=observation_id,
            result=DecisionResult(_text(item, "result")),
            blockers=tuple(blockers),
            selected_structure_id=selected_structure_id,
            risk_allocation_id=risk_allocation_id,
            selected_structure_json=_payload_text(selected_structure),
            risk_allocation_json=_payload_text(risk_allocation),
        )
        if _text(item, "decision_record_id") != record.identity:
            raise ValueError("DecisionRecord identity mismatch")
        return record


def unassessed_decision_record(
    *,
    window: DecisionWindow,
    decision_policy_id: str,
    known_at: datetime,
    observation: MarketObservation | None,
) -> DecisionRecord:
    boundary = _utc(known_at, "known_at")
    if boundary < window.input_deadline:
        raise ValueError("DecisionRecord cannot be finalized before the input deadline")
    observation_id: str | None = None
    blockers: tuple[str, ...]
    if observation is None:
        blockers = ("NO_OBSERVATION",)
    elif observation.channel_id is not window.channel_id:
        blockers = ("OBSERVATION_CHANNEL_MISMATCH",)
    elif not window.starts_at <= observation.observed_at < window.ends_at:
        blockers = ("OBSERVATION_OUTSIDE_WINDOW",)
    elif observation.known_at > window.input_deadline:
        blockers = ("OBSERVATION_AFTER_INPUT_DEADLINE",)
    else:
        observation_id = observation.identity
        blockers = observation.data_health_blockers or ("DECISION_POLICY_NOT_EVALUATED",)
    return DecisionRecord(
        window=window,
        decision_policy_id=decision_policy_id,
        known_at=window.input_deadline,
        observation_id=observation_id,
        result=DecisionResult.UNKNOWN,
        blockers=blockers,
        selected_structure_id=None,
        risk_allocation_id=None,
        selected_structure_json=None,
        risk_allocation_json=None,
    )


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value, "datetime").isoformat().replace("+00:00", "Z")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return value


def _text(value: dict[str, object], field: str) -> str:
    member = value.get(field)
    if not isinstance(member, str) or not member:
        raise ValueError(f"{field} must be non-empty text")
    return member


def _optional_text(value: dict[str, object], field: str) -> str | None:
    member = value.get(field)
    if member is None:
        return None
    if not isinstance(member, str) or not member:
        raise ValueError(f"{field} must be non-empty text or null")
    return member


def _optional_mapping(value: dict[str, object], field: str) -> dict[str, object] | None:
    member = value.get(field)
    if member is None:
        return None
    return _mapping(member, field)


def _payload_text(value: dict[str, object] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _payload_mapping(value: str | None, field: str) -> dict[str, object] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} payload is invalid canonical JSON") from exc
    return _mapping(decoded, field)


def _datetime(value: dict[str, object], field: str) -> datetime:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 datetime") from exc
    return _utc(parsed, field)
