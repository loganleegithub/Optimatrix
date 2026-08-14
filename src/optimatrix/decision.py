from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Self

from optimatrix.channels import ChannelId
from optimatrix.identity import canonical_identity, canonical_value, require_identity
from optimatrix.market import (
    EventState,
    EventStateSource,
    ImpliedVarianceMethod,
    MarketContext,
    MarketContextEvidence,
    OptionBookUnavailableReason,
    OptionQuote,
    OptionType,
    PriceLevel,
    RealizedVarianceMethod,
    TickSchedule,
    TickStep,
    UnavailableOptionBook,
)
from optimatrix.policy import ObservationPolicy, WindowSchedulePolicy
from optimatrix.pricing import Action
from optimatrix.products import PRODUCTS, ProductId
from optimatrix.route import RouteEvidenceStatus, ShadowRouteEvidence
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
        _require_fields(
            item,
            {
                "decision_window_id",
                "channel_id",
                "market_session_id",
                "schedule_policy_id",
                "starts_at",
                "ends_at",
                "input_deadline",
            },
            "decision_window",
        )
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
    unavailable_books: tuple[UnavailableOptionBook, ...] = ()

    def __post_init__(self) -> None:
        require_identity(self.data_health_policy_id, "data_health_policy_id")
        observed_at = _utc(self.observed_at, "observed_at")
        known_at = _utc(self.known_at, "known_at")
        if observed_at > known_at:
            raise ValueError("observation cannot be known before it is observed")
        if self.context.now != self.observed_at:
            raise ValueError("MarketObservation boundary must match MarketContext")
        context_blockers = self.context.evidence_blockers_at(known_at)
        if self.data_health_blockers[: len(context_blockers)] != context_blockers:
            raise ValueError("MarketObservation DataHealth does not match MarketContext")
        if len({quote.instrument_name for quote in self.quotes}) != len(self.quotes):
            raise ValueError("MarketObservation quotes must have unique instruments")
        quote_names = {quote.instrument_name for quote in self.quotes}
        unavailable_names = tuple(book.instrument_name for book in self.unavailable_books)
        if len(set(unavailable_names)) != len(unavailable_names):
            raise ValueError("MarketObservation unavailable books must have unique instruments")
        readiness_mismatch = set(unavailable_names) != set(
            self.context.evidence.requested_books
        ) - set(self.context.evidence.usable_books) or bool(set(unavailable_names) & quote_names)
        if readiness_mismatch != (
            "OPTION_BOOK_READINESS_EVIDENCE_MISMATCH" in self.data_health_blockers
        ):
            raise ValueError("MarketObservation option-book readiness evidence is incoherent")
        if len(set(self.data_health_blockers)) != len(self.data_health_blockers) or any(
            not blocker for blocker in self.data_health_blockers
        ):
            raise ValueError("MarketObservation blockers must be unique non-empty strings")

    @property
    def identity(self) -> str:
        return canonical_identity(
            "MarketObservationV2",
            self.channel_id,
            self.data_health_policy_id,
            self.observed_at,
            self.known_at,
            self.context,
            tuple(sorted(self.quotes, key=lambda quote: quote.instrument_name)),
            self.data_health_blockers,
            tuple(sorted(self.unavailable_books, key=lambda book: book.instrument_name)),
        )

    @classmethod
    def capture(
        cls,
        *,
        channel_id: ChannelId,
        policy: ObservationPolicy,
        context: MarketContext,
        quotes: tuple[OptionQuote, ...],
        unavailable_books: tuple[UnavailableOptionBook, ...] = (),
        known_at: datetime | None = None,
    ) -> Self:
        causal_known_at = context.now if known_at is None else _utc(known_at, "known_at")
        if context.now > causal_known_at:
            raise ValueError("MarketObservation cannot be known before its market boundary")
        blockers = list(context.evidence_blockers_at(causal_known_at))
        quote_names = {quote.instrument_name for quote in quotes}
        if quote_names != set(context.evidence.usable_books):
            blockers.append("OBSERVATION_UNIVERSE_MISMATCH")
        unavailable_names = {book.instrument_name for book in unavailable_books}
        expected_unavailable_names = set(context.evidence.requested_books) - set(
            context.evidence.usable_books
        )
        if unavailable_names != expected_unavailable_names or unavailable_names & quote_names:
            blockers.append("OPTION_BOOK_READINESS_EVIDENCE_MISMATCH")
        if context.evidence.maximum_market_age_ms != policy.maximum_age_ms:
            blockers.append("DATA_HEALTH_POLICY_AGE_MISMATCH")
        if not quotes:
            blockers.append("NO_OPTION_QUOTES")
        if len({quote.continuity_epoch for quote in quotes}) > 1:
            blockers.append("MULTIPLE_CONTINUITY_EPOCHS")
        if quotes:
            known_at_ms = (
                int(causal_known_at.timestamp()) * 1000 + causal_known_at.microsecond // 1000
            )
            source_span = max(quote.source_timestamp_ms for quote in quotes) - min(
                quote.source_timestamp_ms for quote in quotes
            )
            receive_span = max(quote.received_timestamp_ms for quote in quotes) - min(
                quote.received_timestamp_ms for quote in quotes
            )
            complete_receive_span = (
                context.evidence.market_received_max_ms - context.evidence.market_received_min_ms
                if context.evidence.market_received_min_ms is not None
                and context.evidence.market_received_max_ms is not None
                else None
            )
            if source_span > policy.maximum_source_span_ms:
                blockers.append("MARKET_SOURCE_SPAN_EXCEEDED")
            if receive_span > policy.maximum_receive_span_ms or (
                complete_receive_span is not None
                and complete_receive_span > policy.maximum_receive_span_ms
            ):
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
            known_at=causal_known_at,
            context=context,
            quotes=quotes,
            data_health_blockers=tuple(dict.fromkeys(blockers)),
            unavailable_books=unavailable_books,
        )

    def as_object(self) -> dict[str, object]:
        return {
            "market_observation_id": self.identity,
            "channel_id": self.channel_id.value,
            "data_health_policy_id": self.data_health_policy_id,
            "observed_at": _iso(self.observed_at),
            "known_at": _iso(self.known_at),
            "context": _market_context_object(self.context),
            "quotes": [_option_quote_object(quote) for quote in self.quotes],
            "unavailable_books": [
                _unavailable_option_book_object(book) for book in self.unavailable_books
            ],
            "data_health_blockers": list(self.data_health_blockers),
        }

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "market_observation")
        _require_fields(
            item,
            {
                "market_observation_id",
                "channel_id",
                "data_health_policy_id",
                "observed_at",
                "known_at",
                "context",
                "quotes",
                "unavailable_books",
                "data_health_blockers",
            },
            "market_observation",
        )
        observation = cls(
            channel_id=ChannelId(_text(item, "channel_id")),
            data_health_policy_id=_text(item, "data_health_policy_id"),
            observed_at=_datetime(item, "observed_at"),
            known_at=_datetime(item, "known_at"),
            context=_market_context_from_object(item.get("context")),
            quotes=tuple(_option_quote_from_object(member) for member in _array(item, "quotes")),
            data_health_blockers=_string_tuple(item, "data_health_blockers"),
            unavailable_books=tuple(
                _unavailable_option_book_from_object(member)
                for member in _array(item, "unavailable_books")
            ),
        )
        if _text(item, "market_observation_id") != observation.identity:
            raise ValueError("MarketObservation identity mismatch")
        return observation


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
    route_evidence_id: str | None = None
    route_evidence_json: str | None = None
    observation: MarketObservation | None = None

    def __post_init__(self) -> None:
        require_identity(self.decision_policy_id, "decision_policy_id")
        _utc(self.known_at, "known_at")
        if self.observation_id is not None:
            require_identity(self.observation_id, "observation_id")
        if (self.observation_id is None) != (self.observation is None):
            raise ValueError("observation identity and evidence must appear together")
        if self.observation is not None and self.observation.identity != self.observation_id:
            raise ValueError("observation evidence does not match its identity")
        if self.selected_structure_id is not None:
            require_identity(self.selected_structure_id, "selected_structure_id")
        if self.risk_allocation_id is not None:
            require_identity(self.risk_allocation_id, "risk_allocation_id")
        if self.route_evidence_id is not None:
            require_identity(self.route_evidence_id, "route_evidence_id")
        if (self.selected_structure_id is None) != (self.selected_structure_json is None):
            raise ValueError("selected structure identity and payload must appear together")
        if (self.risk_allocation_id is None) != (self.risk_allocation_json is None):
            raise ValueError("risk allocation identity and payload must appear together")
        if (self.route_evidence_id is None) != (self.route_evidence_json is None):
            raise ValueError("route evidence identity and payload must appear together")
        if self.risk_allocation_id is not None and self.selected_structure_id is None:
            raise ValueError("risk allocation requires a selected structure")
        if self.route_evidence_id is not None and self.selected_structure_id is None:
            raise ValueError("route evidence requires a selected structure")
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
            or self.route_evidence_id is None
            or self.route_evidence_json is None
        ):
            raise ValueError(
                "CANDIDATE requires observation, structure, allocation, route, and no blockers"
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
        route_evidence = self.route_evidence
        if route_evidence is not None:
            if route_evidence.identity != self.route_evidence_id:
                raise ValueError("route evidence payload does not match its identity")
            if (
                route_evidence.status is not RouteEvidenceStatus.EVALUABLE
                or route_evidence.policy_id != self.decision_policy_id
                or route_evidence.selected_structure_id != self.selected_structure_id
                or route_evidence.observation_id != self.observation_id
                or route_evidence.evaluated_at != self.known_at
            ):
                raise ValueError("Candidate route evidence does not bind its Decision")
            if self.observation is None:
                raise ValueError("Candidate route evidence requires its causal observation")
            if (
                route_evidence.observed_at != self.observation.observed_at
                or route_evidence.observation_known_at != self.observation.known_at
            ):
                raise ValueError("Candidate route evidence boundaries do not match its observation")
            quotes = {quote.instrument_name: quote for quote in self.observation.quotes}
            for leg in route_evidence.legs:
                quote = quotes.get(leg.instrument_name)
                if quote is None:
                    raise ValueError("Candidate route evidence references a missing component book")
                levels = quote.ask if leg.action is Action.BUY else quote.bid
                available = sum((level.quantity for level in levels), Decimal(0))
                coverage = min(Decimal(1), available / leg.requested_amount)
                if (leg.available_amount, leg.depth_coverage) != (available, coverage):
                    raise ValueError("Candidate route depth does not match its observation")
            self._validate_route_against_structure(route_evidence)

    @property
    def selected_structure(self) -> dict[str, object] | None:
        return _payload_mapping(self.selected_structure_json, "selected_structure")

    @property
    def risk_allocation(self) -> dict[str, object] | None:
        return _payload_mapping(self.risk_allocation_json, "risk_allocation")

    @property
    def route_evidence(self) -> ShadowRouteEvidence | None:
        return (
            ShadowRouteEvidence.from_object(
                _payload_mapping(self.route_evidence_json, "route_evidence")
            )
            if self.route_evidence_json is not None
            else None
        )

    def _validate_route_against_structure(self, evidence: ShadowRouteEvidence) -> None:
        structure = self.selected_structure
        if structure is None:
            raise ValueError("route evidence requires a selected structure payload")
        legs = _mapping(structure.get("legs"), "selected_structure.legs")
        names = tuple(
            _text(_mapping(legs.get(role), f"selected_structure.legs.{role}"), "instrument_name")
            for role in ("long_put", "short_put", "short_call", "long_call")
        )
        if tuple(leg.instrument_name for leg in evidence.legs) != names:
            raise ValueError("route evidence instruments do not match the selected structure")
        if evidence.target_amount != _decimal(structure, "option_amount"):
            raise ValueError("route evidence amount does not match the selected structure")
        pricing = _mapping(structure.get("pricing"), "selected_structure.pricing")
        expected = (
            _text(pricing, "fee_model_id"),
            _decimal(pricing, "native_gross_credit"),
            _decimal(pricing, "combo_standard_fee_native"),
            _decimal(pricing, "native_net_credit"),
            _decimal(pricing, "boundary_index_price_usd"),
            _decimal(pricing, "boundary_net_credit_usd"),
        )
        actual = (
            evidence.fee_model_id,
            evidence.native_gross_credit,
            evidence.standard_combo_fee_projection_native,
            evidence.native_net_credit,
            evidence.boundary_index_price_usd,
            evidence.boundary_net_credit_usd,
        )
        if actual != expected:
            raise ValueError("route evidence economics do not match the selected structure")

    @property
    def identity(self) -> str:
        return canonical_identity(
            "DecisionRecordV3",
            self.window.identity,
            self.decision_policy_id,
            self.known_at,
            self.observation_id,
            self.observation,
            self.result,
            self.blockers,
            self.selected_structure_id,
            self.risk_allocation_id,
            self.selected_structure_json,
            self.risk_allocation_json,
            self.route_evidence_id,
            self.route_evidence_json,
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
            "observation": self.observation.as_object() if self.observation is not None else None,
            "result": self.result.value,
            "blockers": list(self.blockers),
            "selected_structure_id": self.selected_structure_id,
            "risk_allocation_id": self.risk_allocation_id,
            "route_evidence_id": self.route_evidence_id,
            "selected_structure": self.selected_structure,
            "risk_allocation": self.risk_allocation,
            "route_evidence": (
                self.route_evidence.as_object() if self.route_evidence is not None else None
            ),
        }

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "decision_record")
        _require_fields(
            item,
            {
                "decision_record_id",
                "window",
                "decision_policy_id",
                "known_at",
                "observation_id",
                "observation",
                "result",
                "blockers",
                "selected_structure_id",
                "risk_allocation_id",
                "route_evidence_id",
                "selected_structure",
                "risk_allocation",
                "route_evidence",
            },
            "decision_record",
        )
        blockers = item.get("blockers")
        if not isinstance(blockers, list) or not all(isinstance(value, str) for value in blockers):
            raise ValueError("decision_record.blockers must be an array of strings")
        observation_id = item.get("observation_id")
        if observation_id is not None and not isinstance(observation_id, str):
            raise ValueError("decision_record.observation_id must be text or null")
        selected_structure_id = _optional_text(item, "selected_structure_id")
        risk_allocation_id = _optional_text(item, "risk_allocation_id")
        route_evidence_id = _optional_text(item, "route_evidence_id")
        encoded_observation = item.get("observation")
        observation = (
            None
            if encoded_observation is None
            else MarketObservation.from_object(encoded_observation)
        )
        selected_structure = _optional_mapping(item, "selected_structure")
        risk_allocation = _optional_mapping(item, "risk_allocation")
        route_evidence = _optional_mapping(item, "route_evidence")
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
            route_evidence_id=route_evidence_id,
            route_evidence_json=_payload_text(route_evidence),
            observation=observation,
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
    bound_observation: MarketObservation | None = None
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
        bound_observation = observation
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
        observation=bound_observation,
    )


def _market_context_object(context: MarketContext) -> dict[str, object]:
    return {
        "now": _iso(context.now),
        "index_price": str(context.index_price),
        "forward_price": str(context.forward_price),
        "trailing_realized_variance_proxy": str(context.trailing_realized_variance_proxy),
        "same_session_implied_variance_proxy": str(context.same_session_implied_variance_proxy),
        "rv_acceleration": str(context.rv_acceleration),
        "jump_share": str(context.jump_share),
        "directional_persistence": str(context.directional_persistence),
        "event_state": context.event_state.value,
        "concentrated_strike": (
            str(context.concentrated_strike) if context.concentrated_strike is not None else None
        ),
        "concentration_strength": str(context.concentration_strength),
        "evidence": _market_context_evidence_object(context.evidence),
    }


def _market_context_from_object(value: object) -> MarketContext:
    item = _mapping(value, "market_observation.context")
    _require_fields(
        item,
        {
            "now",
            "index_price",
            "forward_price",
            "trailing_realized_variance_proxy",
            "same_session_implied_variance_proxy",
            "rv_acceleration",
            "jump_share",
            "directional_persistence",
            "event_state",
            "concentrated_strike",
            "concentration_strength",
            "evidence",
        },
        "market_observation.context",
    )
    return MarketContext(
        now=_datetime(item, "now"),
        index_price=_decimal(item, "index_price"),
        forward_price=_decimal(item, "forward_price"),
        trailing_realized_variance_proxy=_decimal(item, "trailing_realized_variance_proxy"),
        same_session_implied_variance_proxy=_decimal(item, "same_session_implied_variance_proxy"),
        rv_acceleration=_decimal(item, "rv_acceleration"),
        jump_share=_decimal(item, "jump_share"),
        directional_persistence=_decimal(item, "directional_persistence"),
        event_state=EventState(_text(item, "event_state")),
        concentrated_strike=_optional_decimal(item, "concentrated_strike"),
        concentration_strength=_decimal(item, "concentration_strength"),
        evidence=_market_context_evidence_from_object(item.get("evidence")),
    )


def _market_context_evidence_object(evidence: MarketContextEvidence) -> dict[str, object]:
    return {
        "realized_variance_method": (
            evidence.realized_variance_method.value
            if evidence.realized_variance_method is not None
            else None
        ),
        "implied_variance_method": (
            evidence.implied_variance_method.value
            if evidence.implied_variance_method is not None
            else None
        ),
        "event_state_source": (
            evidence.event_state_source.value if evidence.event_state_source is not None else None
        ),
        "required_history_start_ms": evidence.required_history_start_ms,
        "history_coverage_start_ms": evidence.history_coverage_start_ms,
        "history_coverage_end_ms": evidence.history_coverage_end_ms,
        "history_cadence_ms": evidence.history_cadence_ms,
        "market_source_min_ms": evidence.market_source_min_ms,
        "market_source_max_ms": evidence.market_source_max_ms,
        "market_received_min_ms": evidence.market_received_min_ms,
        "market_received_max_ms": evidence.market_received_max_ms,
        "event_state_known_at_ms": evidence.event_state_known_at_ms,
        "maximum_market_age_ms": evidence.maximum_market_age_ms,
        "requested_books": list(evidence.requested_books),
        "usable_books": list(evidence.usable_books),
        "declared_blockers": list(evidence.declared_blockers),
    }


def _market_context_evidence_from_object(value: object) -> MarketContextEvidence:
    item = _mapping(value, "market_observation.context.evidence")
    _require_fields(
        item,
        {
            "realized_variance_method",
            "implied_variance_method",
            "event_state_source",
            "required_history_start_ms",
            "history_coverage_start_ms",
            "history_coverage_end_ms",
            "history_cadence_ms",
            "market_source_min_ms",
            "market_source_max_ms",
            "market_received_min_ms",
            "market_received_max_ms",
            "event_state_known_at_ms",
            "maximum_market_age_ms",
            "requested_books",
            "usable_books",
            "declared_blockers",
        },
        "market_observation.context.evidence",
    )
    realized_method = _optional_text(item, "realized_variance_method")
    implied_method = _optional_text(item, "implied_variance_method")
    event_source = _optional_text(item, "event_state_source")
    return MarketContextEvidence(
        realized_variance_method=(
            RealizedVarianceMethod(realized_method) if realized_method is not None else None
        ),
        implied_variance_method=(
            ImpliedVarianceMethod(implied_method) if implied_method is not None else None
        ),
        event_state_source=(EventStateSource(event_source) if event_source is not None else None),
        required_history_start_ms=_optional_integer(item, "required_history_start_ms"),
        history_coverage_start_ms=_optional_integer(item, "history_coverage_start_ms"),
        history_coverage_end_ms=_optional_integer(item, "history_coverage_end_ms"),
        history_cadence_ms=_optional_integer(item, "history_cadence_ms"),
        market_source_min_ms=_optional_integer(item, "market_source_min_ms"),
        market_source_max_ms=_optional_integer(item, "market_source_max_ms"),
        market_received_min_ms=_optional_integer(item, "market_received_min_ms"),
        market_received_max_ms=_optional_integer(item, "market_received_max_ms"),
        event_state_known_at_ms=_optional_integer(item, "event_state_known_at_ms"),
        maximum_market_age_ms=_integer(item, "maximum_market_age_ms"),
        requested_books=_string_tuple(item, "requested_books"),
        usable_books=_string_tuple(item, "usable_books"),
        declared_blockers=_string_tuple(item, "declared_blockers"),
    )


def _option_quote_object(quote: OptionQuote) -> dict[str, object]:
    return {
        "instrument_name": quote.instrument_name,
        "product_id": quote.product.product_id.value,
        "product_spec_id": quote.product.identity,
        "expiry": _iso(quote.expiry),
        "strike": str(quote.strike),
        "option_type": quote.option_type.value,
        "signed_delta": str(quote.signed_delta),
        "mark_iv": str(quote.mark_iv),
        "bid": [_price_level_object(level) for level in quote.bid],
        "ask": [_price_level_object(level) for level in quote.ask],
        "tick_schedule": _tick_schedule_object(quote.tick_schedule),
        "source_timestamp_ms": quote.source_timestamp_ms,
        "received_timestamp_ms": quote.received_timestamp_ms,
        "continuity_epoch": quote.continuity_epoch,
        "delivery_fee_exempt": quote.delivery_fee_exempt,
        "open_interest": str(quote.open_interest),
        "gamma": str(quote.gamma),
    }


def _unavailable_option_book_object(book: UnavailableOptionBook) -> dict[str, object]:
    return {
        "unavailable_book_id": book.identity,
        "instrument_name": book.instrument_name,
        "product_id": book.product.product_id.value,
        "product_spec_id": book.product.identity,
        "expiry": _iso(book.expiry),
        "strike": str(book.strike),
        "option_type": book.option_type.value,
        "reason": book.reason.value,
    }


def _unavailable_option_book_from_object(value: object) -> UnavailableOptionBook:
    item = _mapping(value, "market_observation.unavailable_book")
    _require_fields(
        item,
        {
            "unavailable_book_id",
            "instrument_name",
            "product_id",
            "product_spec_id",
            "expiry",
            "strike",
            "option_type",
            "reason",
        },
        "market_observation.unavailable_book",
    )
    product_id = ProductId(_text(item, "product_id"))
    try:
        product = PRODUCTS[product_id]
    except KeyError as exc:
        raise ValueError("market_observation.unavailable_book product is unsupported") from exc
    if _text(item, "product_spec_id") != product.identity:
        raise ValueError("UnavailableOptionBook product specification identity mismatch")
    book = UnavailableOptionBook(
        instrument_name=_text(item, "instrument_name"),
        product=product,
        expiry=_datetime(item, "expiry"),
        strike=_decimal(item, "strike"),
        option_type=OptionType(_text(item, "option_type")),
        reason=OptionBookUnavailableReason(_text(item, "reason")),
    )
    if _text(item, "unavailable_book_id") != book.identity:
        raise ValueError("UnavailableOptionBook identity mismatch")
    return book


def _option_quote_from_object(value: object) -> OptionQuote:
    item = _mapping(value, "market_observation.quote")
    _require_fields(
        item,
        {
            "instrument_name",
            "product_id",
            "product_spec_id",
            "expiry",
            "strike",
            "option_type",
            "signed_delta",
            "mark_iv",
            "bid",
            "ask",
            "tick_schedule",
            "source_timestamp_ms",
            "received_timestamp_ms",
            "continuity_epoch",
            "delivery_fee_exempt",
            "open_interest",
            "gamma",
        },
        "market_observation.quote",
    )
    product_id = ProductId(_text(item, "product_id"))
    try:
        product = PRODUCTS[product_id]
    except KeyError as exc:
        raise ValueError("market_observation.quote product is unsupported") from exc
    if _text(item, "product_spec_id") != product.identity:
        raise ValueError("OptionQuote product specification identity mismatch")
    return OptionQuote(
        instrument_name=_text(item, "instrument_name"),
        product=product,
        expiry=_datetime(item, "expiry"),
        strike=_decimal(item, "strike"),
        option_type=OptionType(_text(item, "option_type")),
        signed_delta=_decimal(item, "signed_delta"),
        mark_iv=_decimal(item, "mark_iv"),
        bid=_price_levels(item, "bid"),
        ask=_price_levels(item, "ask"),
        tick_schedule=_tick_schedule_from_object(item.get("tick_schedule")),
        source_timestamp_ms=_integer(item, "source_timestamp_ms"),
        received_timestamp_ms=_integer(item, "received_timestamp_ms"),
        continuity_epoch=_integer(item, "continuity_epoch"),
        delivery_fee_exempt=_boolean(item, "delivery_fee_exempt"),
        open_interest=_decimal(item, "open_interest"),
        gamma=_decimal(item, "gamma"),
    )


def _price_level_object(level: PriceLevel) -> dict[str, object]:
    return {"price": str(level.price), "quantity": str(level.quantity)}


def _price_levels(value: dict[str, object], field: str) -> tuple[PriceLevel, ...]:
    levels: list[PriceLevel] = []
    for member in _array(value, field):
        item = _mapping(member, f"market_observation.quote.{field}.level")
        _require_fields(
            item,
            {"price", "quantity"},
            f"market_observation.quote.{field}.level",
        )
        levels.append(
            PriceLevel(
                price=_decimal(item, "price"),
                quantity=_decimal(item, "quantity"),
            )
        )
    return tuple(levels)


def _tick_schedule_object(schedule: TickSchedule) -> dict[str, object]:
    return {
        "base_tick": str(schedule.base_tick),
        "steps": [
            {"above_price": str(step.above_price), "tick_size": str(step.tick_size)}
            for step in schedule.steps
        ],
    }


def _tick_schedule_from_object(value: object) -> TickSchedule:
    item = _mapping(value, "market_observation.quote.tick_schedule")
    _require_fields(
        item,
        {"base_tick", "steps"},
        "market_observation.quote.tick_schedule",
    )
    steps: list[TickStep] = []
    for member in _array(item, "steps"):
        step = _mapping(member, "market_observation.quote.tick_schedule.step")
        _require_fields(
            step,
            {"above_price", "tick_size"},
            "market_observation.quote.tick_schedule.step",
        )
        steps.append(
            TickStep(
                above_price=_decimal(step, "above_price"),
                tick_size=_decimal(step, "tick_size"),
            )
        )
    return TickSchedule(base_tick=_decimal(item, "base_tick"), steps=tuple(steps))


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


def _require_fields(
    value: dict[str, object],
    expected: set[str],
    field: str,
) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing {missing}")
    if unexpected:
        details.append(f"unexpected {unexpected}")
    raise ValueError(f"{field} fields are invalid: {', '.join(details)}")


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


def _array(value: dict[str, object], field: str) -> list[object]:
    member = value.get(field)
    if not isinstance(member, list):
        raise ValueError(f"{field} must be an array")
    return member


def _string_tuple(value: dict[str, object], field: str) -> tuple[str, ...]:
    members = _array(value, field)
    result: list[str] = []
    for member in members:
        if not isinstance(member, str) or not member:
            raise ValueError(f"{field} must be an array of non-empty strings")
        result.append(member)
    return tuple(result)


def _decimal(value: dict[str, object], field: str) -> Decimal:
    member = value.get(field)
    if not isinstance(member, str) or not member:
        raise ValueError(f"{field} must be a decimal string")
    try:
        result = Decimal(member)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal string") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _optional_decimal(value: dict[str, object], field: str) -> Decimal | None:
    if value.get(field) is None:
        return None
    return _decimal(value, field)


def _integer(value: dict[str, object], field: str) -> int:
    member = value.get(field)
    if isinstance(member, bool) or not isinstance(member, int) or member < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return member


def _optional_integer(value: dict[str, object], field: str) -> int | None:
    if value.get(field) is None:
        return None
    return _integer(value, field)


def _boolean(value: dict[str, object], field: str) -> bool:
    member = value.get(field)
    if not isinstance(member, bool):
        raise ValueError(f"{field} must be boolean")
    return member


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
