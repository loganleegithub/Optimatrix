from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from market_monitor import BookState, ContinuityGap, PriceLevel, TimeInterval, TrustedClock
from options_domain import (
    AmountState,
    ComboInstrument,
    ComponentBookQuoteKind,
    ComponentBookVerticalQuote,
    OptionInstrument,
    check_target_amount,
    evaluate_component_book_vertical,
    is_protective_vertical,
)
from options_domain.quotes import walk_target_depth
from short_vol_radar.atomic import (
    AtomicQuote,
    PublicAtomicQuoteState,
)
from short_vol_radar.radar import TickerState
from short_vol_radar.review import LeggedReferenceState, ReviewContext, build_review_contexts
from short_vol_radar.score import ScoreBand
from short_vol_underwriting import (
    CloseAtomicAvailability,
    CloseBookAvailability,
    CloseOptionAvailability,
    CloseQuoteFacts,
    ComponentBookPairWitness,
    ComponentLegRole,
    FixedContractShadowOwner,
    PositionFacts,
    PostCloseAttemptStatus,
    PredicateTruth,
    RpcAdmissionRefreshWitness,
    RpcComponentLegRefreshWitness,
    SourceFact,
    SubscriptionAdmissionRefreshWitness,
    TerminalSource,
    UnderwritingComponentCandidate,
    UnderwritingComponentSelection,
    UnderwritingFacts,
    canonical_identity,
    component_pair_witness,
    compute_component_entry_economics,
    select_underwriting_component,
)
from short_vol_underwriting import (
    FactBoundary as DownstreamFactBoundary,
)
from short_vol_underwriting.admission import RpcRequestIntent
from short_vol_underwriting.case_store import RecoverableShadowEntry, ShadowCaseStore
from short_vol_underwriting.constants import ADMISSION_CUTOFF_LEAD_MS
from short_vol_underwriting.owner import (
    COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE,
    COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN,
    NO_PROTECTIVE_COMPONENT,
    NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE,
    OwnerTransition,
)

from radar_runtime.runtime import (
    AtomicScopeSnapshot,
    CausalCause,
    CausalCommit,
    FactBoundary,
    RadarReducer,
    RpcPurpose,
    RpcState,
    ShadowRpcIntent,
)

_POSITION_COMPONENT_SOURCE_CAUSES = frozenset(
    {
        CausalCause.OPTION_BOOK_FACT,
        CausalCause.OPTION_BOOK_CHANGED,
        CausalCause.OPTION_BOOK_GAP,
    }
)
_POSITION_IRRELEVANT_COMBO_BOOK_CAUSES = frozenset(
    {
        CausalCause.COMBO_BOOK_FACT,
        CausalCause.COMBO_BOOK_CHANGED,
        CausalCause.COMBO_BOOK_GAP,
    }
)


@dataclass(frozen=True)
class _OptionSource:
    instrument: OptionInstrument
    semantic_identity: str
    source: SourceFact


@dataclass(frozen=True)
class _ComboSource:
    instrument: ComboInstrument
    semantic_identity: str
    source: SourceFact


@dataclass(frozen=True)
class _TickerSource:
    value: TickerState
    source: SourceFact


@dataclass(frozen=True)
class _Anchor:
    anchor_identity: str
    entry_boundary: DownstreamFactBoundary
    short_leg_identity: str
    long_leg_identity: str
    short_instrument_name: str
    long_instrument_name: str
    target_quantity_btc: Decimal


@dataclass(frozen=True)
class _RequestContext:
    purpose: str
    owner_identity: str
    instrument_name: str
    origin_boundary: DownstreamFactBoundary
    role: ComponentLegRole | None = None


@dataclass(frozen=True)
class _RestBook:
    instrument_name: str
    state: str | None
    change_id: int
    source_timestamp_ms: int
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    well_formed: bool


@dataclass(frozen=True)
class _ComponentRestResponse:
    witness: RpcComponentLegRefreshWitness
    book: _RestBook


class FixedContractShadowRuntimeAdapter:
    """Pure synchronous projection from one settled Radar reducer into one owner."""

    def __init__(
        self,
        *,
        owner: FixedContractShadowOwner,
        case_store: ShadowCaseStore | None = None,
        recoverables: Sequence[RecoverableShadowEntry] = (),
    ) -> None:
        if recoverables and case_store is None:
            raise ValueError("recovered Entries require their stable Shadow Case store")
        self.owner = owner
        self._case_store = case_store
        self._staged_recoveries = tuple(recoverables)
        self._session_epoch: int | None = None
        self._option_sources: dict[str, _OptionSource] = {}
        self._options_by_identity: dict[str, _OptionSource] = {}
        self._combo_sources: dict[str, _ComboSource] = {}
        self._combos_by_identity: dict[str, _ComboSource] = {}
        self._ticker_sources: dict[str, _TickerSource] = {}
        self._underwriting_by_scope: dict[str, UnderwritingFacts] = {}
        self._workbench_underwriting_metadata_by_scope: dict[str, Mapping[str, object]] = {}
        self._workbench_underwriting_metadata: tuple[Mapping[str, object], ...] = ()
        self._candidate_origins: dict[str, UnderwritingFacts] = {}
        self._decision_control_origins: dict[str, UnderwritingFacts] = {}
        self._anchors: dict[str, _Anchor] = {}
        self._requests: dict[int, _RequestContext] = {}
        self._paired_responses: dict[
            tuple[str, str], dict[ComponentLegRole, _ComponentRestResponse]
        ] = {}
        self._frozen_component_by_episode: dict[str, UnderwritingComponentSelection] = {}
        self._last_reducer: RadarReducer | None = None

    def bind_reducer(self, reducer: RadarReducer) -> None:
        if self._last_reducer is not None and self._last_reducer is not reducer:
            raise ValueError("adapter reducer binding is immutable")
        self._require_bindings(reducer)
        self._last_reducer = reducer

    @property
    def required_combo_instrument_names(self) -> tuple[str, ...]:
        return self.owner.required_combo_instrument_names

    @property
    def required_option_instrument_names(self) -> tuple[str, ...]:
        names = set(self.owner.required_option_instrument_names)
        for recovery in self._staged_recoveries:
            names.update(recovery.required_option_instrument_names)
        return tuple(sorted(names))

    @property
    def retained_state_counts(self) -> Mapping[str, int]:
        return {
            "current_option_sources": len(self._option_sources),
            "retained_option_identities": len(self._options_by_identity),
            "current_combo_sources": len(self._combo_sources),
            "retained_combo_identities": len(self._combos_by_identity),
            "current_ticker_sources": len(self._ticker_sources),
            "underwriting_scopes": len(self._underwriting_by_scope),
            "candidate_origins": len(self._candidate_origins),
            "decision_control_origins": len(self._decision_control_origins),
            "active_anchors": len(self._anchors),
            "request_contexts": len(self._requests),
        }

    def workbench_option_metadata(self) -> tuple[Mapping[str, object], ...]:
        """Copy settled option identity metadata for the in-process read-only projection."""
        return tuple(
            {
                "semantic_identity": identity,
                "instrument_name": source.instrument.instrument_name,
                "expiration_timestamp_ms": source.instrument.expiration_timestamp_ms,
                "option_type": source.instrument.option_type.value,
                "strike_usdc_per_btc": str(source.instrument.strike),
                "product_spec_identity": source.instrument.product.identity,
                "product_name": source.instrument.product.name.value,
                "native_premium_currency": source.instrument.product.native_premium_currency,
            }
            for identity, source in sorted(self._options_by_identity.items())
        )

    def workbench_underwriting_metadata(self) -> tuple[Mapping[str, object], ...]:
        """Copy display-only structure facts from the settled Underwriting projection."""
        return self._workbench_underwriting_metadata

    def _underwriting_display_metadata(
        self,
        scope_identity: str,
        facts: UnderwritingFacts,
    ) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "radar_scope_identity": scope_identity,
                "short_leg_instrument_name": facts.short_leg_instrument_name,
                "long_leg_instrument_name": facts.long_leg_instrument_name,
                "execution_model": (
                    facts.component_quote.execution_model
                    if facts.component_quote is not None
                    else self.owner.policies.underwriting.execution_model
                ),
                "component_state": facts.component_state,
                "component_blockers": list(facts.component_blockers),
                "atomic_state_diagnostic": facts.atomic_state,
                "combo_instrument_name": facts.combo_instrument_name,
                "expiry_timestamp_ms": facts.expiry_ms,
                "option_type": facts.option_type,
                "short_strike_usdc_per_btc": (
                    str(facts.short_strike_usdc_per_btc)
                    if facts.short_strike_usdc_per_btc is not None
                    else None
                ),
                "long_strike_usdc_per_btc": (
                    str(facts.long_strike_usdc_per_btc)
                    if facts.long_strike_usdc_per_btc is not None
                    else None
                ),
                "target_quantity_btc": str(facts.target_quantity_btc),
            }
        )

    def next_time_boundary_monotonic_ms(
        self,
        *,
        reducer: RadarReducer,
        after_monotonic_ms: int,
    ) -> int | None:
        self._require_bindings(reducer)
        clock = reducer.clock
        if clock is None:
            return None
        crossings = [
            crossing
            for target in self.owner.pending_trusted_time_boundaries
            if (
                crossing := _first_trusted_time_crossing(
                    clock=clock,
                    market_time_ms=target.market_time_ms,
                    bound=target.bound,
                    clock_currentness_budget_ms=target.clock_currentness_budget_ms,
                    after_monotonic_ms=after_monotonic_ms,
                )
            )
            is not None
        ]
        for facts in self._underwriting_by_scope.values():
            if _radar_anchor_identity(facts) is None or facts.expiry_ms is None:
                continue
            crossing = _first_trusted_time_crossing(
                clock=clock,
                market_time_ms=facts.expiry_ms - ADMISSION_CUTOFF_LEAD_MS,
                bound="UPPER",
                clock_currentness_budget_ms=(
                    self.owner.policies.underwriting.clock_currentness_budget_ms
                ),
                after_monotonic_ms=after_monotonic_ms,
            )
            if crossing is not None:
                crossings.append(crossing)
        active_underwriting = tuple(
            facts
            for facts in self._underwriting_by_scope.values()
            if _radar_anchor_identity(facts) is not None
        )
        if active_underwriting:
            crossings.extend(
                self._currentness_crossings(
                    reducer=reducer,
                    clock=clock,
                    after_monotonic_ms=after_monotonic_ms,
                    clock_budget_ms=(self.owner.policies.underwriting.clock_currentness_budget_ms),
                    platform_budget_ms=(
                        self.owner.policies.underwriting.platform_currentness_budget_ms
                    ),
                    index_budget_ms=(self.owner.policies.underwriting.index_currentness_budget_ms),
                    ticker_budget_ms=(
                        self.owner.policies.underwriting.option_ticker_currentness_budget_ms
                    ),
                    ticker_instrument_names=tuple(
                        sorted(
                            {
                                facts.short_leg_instrument_name
                                for facts in active_underwriting
                                if facts.short_leg_instrument_name is not None
                            }
                        )
                    ),
                )
            )
        pending_position_names = self.required_option_instrument_names
        if pending_position_names:
            crossings.extend(
                self._currentness_crossings(
                    reducer=reducer,
                    clock=clock,
                    after_monotonic_ms=after_monotonic_ms,
                    clock_budget_ms=self.owner.policies.position.clock_currentness_budget_ms,
                    platform_budget_ms=(
                        self.owner.policies.position.platform_currentness_budget_ms
                    ),
                    index_budget_ms=self.owner.policies.position.index_currentness_budget_ms,
                    ticker_budget_ms=(
                        self.owner.policies.position.option_ticker_currentness_budget_ms
                    ),
                    ticker_instrument_names=pending_position_names,
                )
            )
        return min(crossings) if crossings else None

    def _currentness_crossings(
        self,
        *,
        reducer: RadarReducer,
        clock: TrustedClock,
        after_monotonic_ms: int,
        clock_budget_ms: int,
        platform_budget_ms: int,
        index_budget_ms: int,
        ticker_budget_ms: int,
        ticker_instrument_names: tuple[str, ...],
    ) -> tuple[int, ...]:
        crossings: list[int] = []
        clock_crossing = _first_clock_currentness_expiry(
            clock=clock,
            clock_currentness_budget_ms=clock_budget_ms,
            after_monotonic_ms=after_monotonic_ms,
        )
        if clock_crossing is not None:
            crossings.append(clock_crossing)
        platform_crossing = _first_platform_currentness_expiry(
            session_epoch=self._session_epoch,
            platform_usable=reducer.platform.usable,
            receipt=reducer.accepted_platform_continuity_boundary,
            platform_currentness_budget_ms=platform_budget_ms,
            after_monotonic_ms=after_monotonic_ms,
        )
        if platform_crossing is not None:
            crossings.append(platform_crossing)
        index_receipt = reducer.accepted_index_receipt
        if index_receipt is not None:
            index_crossing = _first_source_currentness_expiry(
                clock=clock,
                source_timestamp_ms=index_receipt.source_timestamp_ms,
                source_currentness_budget_ms=index_budget_ms,
                clock_currentness_budget_ms=clock_budget_ms,
                after_monotonic_ms=after_monotonic_ms,
            )
            if index_crossing is not None:
                crossings.append(index_crossing)
        for instrument_name in ticker_instrument_names:
            ticker = self._ticker_sources.get(instrument_name)
            if ticker is None:
                continue
            ticker_crossing = _first_source_currentness_expiry(
                clock=clock,
                source_timestamp_ms=ticker.value.source_timestamp_ms,
                source_currentness_budget_ms=ticker_budget_ms,
                clock_currentness_budget_ms=clock_budget_ms,
                after_monotonic_ms=after_monotonic_ms,
            )
            if ticker_crossing is not None:
                crossings.append(ticker_crossing)
        return tuple(crossings)

    def on_settled_transaction(
        self,
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
    ) -> tuple[ShadowRpcIntent, ...]:
        boundary = self._boundary(reducer, commit.boundary)
        self._require_bindings(reducer)
        self._last_reducer = reducer
        self._refresh_sources(reducer, boundary)
        self._activate_staged_recoveries(boundary)

        projected, scope_retirements, episode_retirements = self._project_underwriting(
            reducer,
            commit,
            boundary,
        )
        transition = self.owner.settle_underwriting(
            projected,
            allocate_request_id=reducer.allocate_shadow_request_id,
        )
        intents = list(self._consume_transition(transition, projected))
        intents.extend(
            self._retire_underwriting_scopes(
                scope_retirements,
                episode_retirements,
                boundary=boundary,
            )
        )

        for anchor in self._position_anchors_for_commit(reducer=reducer, commit=commit):
            if not boundary.is_strictly_after(anchor.entry_boundary):
                continue
            facts = self._project_position(
                reducer=reducer,
                anchor=anchor,
                boundary=boundary,
            )
            position_transition = self.owner.settle_position(
                anchor_identity=anchor.anchor_identity,
                facts=facts,
                allocate_request_id=reducer.allocate_shadow_request_id,
            )
            intents.extend(self._consume_transition(position_transition, projected))
        return tuple(intents)

    def _position_anchors_for_commit(
        self,
        *,
        reducer: RadarReducer,
        commit: CausalCommit,
    ) -> tuple[_Anchor, ...]:
        anchors = tuple(self._anchors.values())
        if not anchors or reducer.clock is None:
            return anchors
        if commit.cause in _POSITION_IRRELEVANT_COMBO_BOOK_CAUSES:
            return ()
        if (
            commit.cause not in _POSITION_COMPONENT_SOURCE_CAUSES
            and commit.cause is not CausalCause.TICKER_APPLIED
        ):
            return anchors
        scopes = commit.transaction_affected_scopes
        if "GLOBAL" in scopes or "OPTION_LOCAL" in scopes:
            return anchors
        instrument_names = {
            scope.removeprefix("OPTION:") for scope in scopes if scope.startswith("OPTION:")
        }
        if len(instrument_names) != len(scopes):
            return anchors
        if commit.cause is CausalCause.TICKER_APPLIED:
            return tuple(
                anchor for anchor in anchors if anchor.short_instrument_name in instrument_names
            )
        return tuple(
            anchor
            for anchor in anchors
            if anchor.short_instrument_name in instrument_names
            or anchor.long_instrument_name in instrument_names
        )

    def on_request_sent(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        reducer = self._require_reducer()
        downstream = self._boundary(reducer, boundary)
        transition = self.owner.note_request_sent(
            request_id=request_id,
            boundary=downstream,
        )
        return self._consume_ordinary_post_close_terminal(
            reducer=reducer,
            request_id=request_id,
            boundary=downstream,
            transition=transition,
        )

    def on_request_failure(
        self,
        *,
        request_id: int,
        terminal_state: RpcState,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        try:
            terminal_status = {
                RpcState.ERROR: PostCloseAttemptStatus.ERROR,
                RpcState.DEADLINE_LATE: PostCloseAttemptStatus.DEADLINE_LATE,
                RpcState.RETIRED: PostCloseAttemptStatus.RETIRED,
            }[terminal_state]
        except KeyError as exc:
            raise ValueError("Shadow RPC terminal state is not an ordinary failure") from exc
        reducer = self._require_reducer()
        downstream = self._boundary(reducer, boundary)
        transition = self.owner.note_request_failure(
            request_id=request_id,
            boundary=downstream,
            terminal_status=terminal_status,
        )
        return self._consume_ordinary_post_close_terminal(
            reducer=reducer,
            request_id=request_id,
            boundary=downstream,
            transition=transition,
        )

    def on_rpc_response(
        self,
        *,
        request_id: int,
        result: object,
        sent_boundary: FactBoundary,
        boundary: FactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        reducer = self._require_reducer()
        context = self._requests.get(request_id)
        if context is None:
            return ()
        accepted_boundary = self._boundary(reducer, boundary)
        downstream_sent = self._boundary(reducer, sent_boundary)
        parsed = _parse_rest_book(result, expected_name=context.instrument_name)
        if parsed is None:
            transition = self.owner.note_request_failure(
                request_id=request_id,
                boundary=accepted_boundary,
                terminal_status=PostCloseAttemptStatus.ERROR,
            )
            return self._consume_ordinary_post_close_terminal(
                reducer=reducer,
                request_id=request_id,
                boundary=accepted_boundary,
                transition=transition,
            )
        if context.role is not None:
            return self._on_component_rpc_response(
                reducer=reducer,
                request_id=request_id,
                context=context,
                parsed=parsed,
                sent_boundary=downstream_sent,
                accepted_boundary=accepted_boundary,
            )
        combo = self._combo_sources.get(context.instrument_name)
        combo_identity = combo.semantic_identity if combo is not None else None
        if combo_identity is None:
            transition = self.owner.note_request_failure(
                request_id=request_id,
                boundary=accepted_boundary,
                terminal_status=PostCloseAttemptStatus.ERROR,
            )
            return self._consume_ordinary_post_close_terminal(
                reducer=reducer,
                request_id=request_id,
                boundary=accepted_boundary,
                transition=transition,
            )
        frontier = reducer.accepted_book_receipts.get(context.instrument_name)
        frontier_book = reducer.combo_books.get(context.instrument_name)
        frontier_depth_matches = (
            frontier_book is not None
            and frontier_book.state is BookState.USABLE
            and parsed.well_formed
            and parsed.state == "open"
            and parsed.bids == frontier_book.levels("bid")
            and parsed.asks == frontier_book.levels("ask")
        )
        frontier_matches = (
            frontier is not None
            and frontier.session_epoch == accepted_boundary.session_epoch
            and frontier.change_id == parsed.change_id
            and frontier_depth_matches
        )
        market_frontier_change_id = frontier.change_id if frontier is not None else parsed.change_id
        market_frontier_session_epoch = (
            frontier.session_epoch if frontier is not None else accepted_boundary.session_epoch
        )
        side, target = self._request_side_and_quantity(context)
        walk = (
            walk_target_depth(parsed.asks if side == "ask" else parsed.bids, target)
            if parsed.well_formed and parsed.state == "open"
            else None
        )
        covers_full_quantity = walk is not None
        witness_identity = canonical_identity(
            "RpcAdmissionRefreshSourceIdentity",
            accepted_boundary.runtime_identity,
            request_id,
            "public/get_order_book",
            combo_identity,
            {"instrument_name": context.instrument_name, "depth": 10000},
            context.origin_boundary.as_object(),
            downstream_sent.as_object(),
            parsed.change_id,
            parsed.source_timestamp_ms,
            accepted_boundary.as_object(),
        )
        witness = RpcAdmissionRefreshWitness(
            source_identity=witness_identity,
            boundary=accepted_boundary,
            canonical_combo_identity=combo_identity,
            instrument_name=context.instrument_name,
            request_params={
                "instrument_name": context.instrument_name,
                "depth": 10000,
            },
            change_id=parsed.change_id,
            source_timestamp_ms=parsed.source_timestamp_ms,
            request_id=request_id,
            candidate_origin_boundary=context.origin_boundary,
            sent_boundary=downstream_sent,
            market_frontier_change_id=market_frontier_change_id,
            market_frontier_session_epoch=market_frontier_session_epoch,
            response_matches_frontier=frontier_matches,
            response_covers_full_quantity=covers_full_quantity,
            payload_matches_request=parsed.instrument_name == context.instrument_name,
            payload_well_formed=parsed.well_formed and parsed.state == "open",
        )
        if context.purpose == "ADMISSION_REFRESH":
            origin = self._candidate_origins.get(context.owner_identity)
            if origin is None:
                self._requests.pop(request_id, None)
                return ()
            self._refresh_sources(reducer, accepted_boundary)
            refreshed = self._refresh_admission_facts(
                reducer=reducer,
                origin=origin,
                boundary=accepted_boundary,
                witness=witness,
                levels=(
                    tuple((level.price, level.amount) for level in walk.consumed)
                    if walk is not None
                    else ()
                ),
                quote_known=walk is not None,
            )
            transition = self.owner.settle_admission(
                candidate_identity=context.owner_identity,
                refreshed_facts=refreshed,
                refresh_witness=witness,
            )
            result_intents = self._consume_transition(transition, (refreshed,))
            self._requests.pop(request_id, None)
            return result_intents

        anchor = self._anchor_for_owner_identity(context.owner_identity)
        if anchor is None:
            self._requests.pop(request_id, None)
            return ()
        facts = self._project_position(
            reducer=reducer,
            anchor=anchor,
            boundary=accepted_boundary,
            rpc_witness=witness,
            rpc_levels=(
                tuple((level.price, level.amount) for level in walk.consumed)
                if walk is not None
                else ()
            ),
            rpc_quote_known=walk is not None,
        )
        transition = self.owner.accept_post_close_response(
            anchor_identity=anchor.anchor_identity,
            refreshed_facts=facts,
            refresh_witness=witness,
        )
        result_intents = self._consume_transition(transition, ())
        self._requests.pop(request_id, None)
        return result_intents

    def _on_component_rpc_response(
        self,
        *,
        reducer: RadarReducer,
        request_id: int,
        context: _RequestContext,
        parsed: _RestBook,
        sent_boundary: DownstreamFactBoundary,
        accepted_boundary: DownstreamFactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        role = context.role
        option = self._option_sources.get(context.instrument_name)
        if role is None or option is None:
            return self._fail_component_response(
                reducer=reducer,
                request_id=request_id,
                boundary=accepted_boundary,
            )
        side, target = self._component_request_side_and_quantity(context)
        levels = parsed.asks if side == "ask" else parsed.bids
        walk = (
            walk_target_depth(levels, target)
            if parsed.well_formed and parsed.state == "open"
            else None
        )
        source_identity = canonical_identity(
            "RpcComponentLegRefreshSourceIdentity",
            accepted_boundary.runtime_identity,
            request_id,
            role.value,
            "public/get_order_book",
            option.semantic_identity,
            {"instrument_name": context.instrument_name, "depth": 10000},
            context.origin_boundary.as_object(),
            sent_boundary.as_object(),
            reducer.current_global_continuity_epoch,
            parsed.change_id,
            parsed.source_timestamp_ms,
            accepted_boundary.as_object(),
        )
        witness = RpcComponentLegRefreshWitness(
            source_identity=source_identity,
            boundary=accepted_boundary,
            role=role,
            canonical_option_identity=option.semantic_identity,
            instrument_name=context.instrument_name,
            request_params={"instrument_name": context.instrument_name, "depth": 10000},
            change_id=parsed.change_id,
            source_timestamp_ms=parsed.source_timestamp_ms,
            request_id=request_id,
            owner_origin_boundary=context.origin_boundary,
            sent_boundary=sent_boundary,
            global_continuity_epoch=reducer.current_global_continuity_epoch,
            response_covers_full_quantity=walk is not None,
            payload_matches_request=parsed.instrument_name == context.instrument_name,
            payload_well_formed=parsed.well_formed and parsed.state == "open",
        )
        family = self._component_request_family(context.purpose)
        key = (family, context.owner_identity)
        members = self._paired_responses.setdefault(key, {})
        members[role] = _ComponentRestResponse(witness=witness, book=parsed)
        if set(members) != {ComponentLegRole.SHORT, ComponentLegRole.LONG}:
            return ()
        short_response = members[ComponentLegRole.SHORT]
        long_response = members[ComponentLegRole.LONG]
        pair = component_pair_witness(
            short=short_response.witness,
            long=long_response.witness,
        )
        self._refresh_sources(reducer, pair.boundary)
        if family == "COMPONENT_ADMISSION":
            origin = self._candidate_origins.get(context.owner_identity)
            if origin is None:
                self._retire_component_response_pair(key)
                return ()
            refreshed = self._refresh_component_admission_facts(
                reducer=reducer,
                origin=origin,
                pair=pair,
                short_book=short_response.book,
                long_book=long_response.book,
            )
            transition = self.owner.settle_component_admission(
                candidate_identity=context.owner_identity,
                refreshed_facts=refreshed,
                pair_witness=pair,
            )
            intents = self._consume_transition(transition, (refreshed,))
        elif family == "COMPONENT_DECISION_CONTROL":
            origin = self._decision_control_origins.get(context.owner_identity)
            if origin is None:
                self._retire_component_response_pair(key)
                return ()
            refreshed = self._refresh_component_admission_facts(
                reducer=reducer,
                origin=origin,
                pair=pair,
                short_book=short_response.book,
                long_book=long_response.book,
            )
            transition = self.owner.settle_component_decision_control(
                selection_identity=context.owner_identity,
                refreshed_facts=refreshed,
                pair_witness=pair,
            )
            intents = self._consume_transition(transition, (refreshed,))
        else:
            anchor = self._anchor_for_owner_identity(context.owner_identity)
            if anchor is None:
                self._retire_component_response_pair(key)
                return ()
            quote = self._component_quote_from_rest_pair(
                reducer=reducer,
                anchor=anchor,
                kind=ComponentBookQuoteKind.CLOSE,
                short_book=short_response.book,
                long_book=long_response.book,
                boundary=pair.boundary,
            )
            facts = self._project_position(
                reducer=reducer,
                anchor=anchor,
                boundary=pair.boundary,
                component_pair=pair,
                component_quote=quote,
                component_short_quote_source=SourceFact(
                    pair.short.source_identity,
                    pair.short.boundary,
                ),
                component_long_quote_source=SourceFact(
                    pair.long.source_identity,
                    pair.long.boundary,
                ),
            )
            transition = self.owner.accept_component_post_close_response(
                anchor_identity=anchor.anchor_identity,
                refreshed_facts=facts,
                pair_witness=pair,
            )
            intents = self._consume_transition(transition, ())
        self._retire_component_response_pair(key)
        return intents

    def _fail_component_response(
        self,
        *,
        reducer: RadarReducer,
        request_id: int,
        boundary: DownstreamFactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        transition = self.owner.note_request_failure(
            request_id=request_id,
            boundary=boundary,
            terminal_status=PostCloseAttemptStatus.ERROR,
        )
        return self._consume_ordinary_post_close_terminal(
            reducer=reducer,
            request_id=request_id,
            boundary=boundary,
            transition=transition,
        )

    @staticmethod
    def _component_request_family(purpose: str) -> str:
        if purpose.startswith("COMPONENT_ADMISSION_"):
            return "COMPONENT_ADMISSION"
        if purpose.startswith("COMPONENT_DECISION_CONTROL_"):
            return "COMPONENT_DECISION_CONTROL"
        if purpose.startswith("COMPONENT_POST_CLOSE_"):
            return "COMPONENT_POST_CLOSE"
        raise ValueError("component request purpose is outside the bounded route")

    def _retire_component_response_pair(self, key: tuple[str, str]) -> None:
        members = self._paired_responses.pop(key, {})
        for member in members.values():
            self._requests.pop(member.witness.request_id, None)

    def _refresh_component_admission_facts(
        self,
        *,
        reducer: RadarReducer,
        origin: UnderwritingFacts,
        pair: ComponentBookPairWitness,
        short_book: _RestBook,
        long_book: _RestBook,
    ) -> UnderwritingFacts:
        short_name = origin.short_leg_instrument_name
        long_name = origin.long_leg_instrument_name
        short = self._option_sources.get(short_name) if short_name is not None else None
        long = self._option_sources.get(long_name) if long_name is not None else None
        origin_anchor = _radar_anchor_identity(origin)
        refresh_packet = (
            reducer.active_radar_score_packet(
                episode_identity=origin_anchor,
                boundary=FactBoundary(
                    session_epoch=pair.boundary.session_epoch,
                    ingress_seq=pair.boundary.ingress_seq,
                    received_monotonic_ms=pair.boundary.received_monotonic_ms,
                    causal_seq=pair.boundary.causal_seq,
                ),
            )
            if origin_anchor is not None
            else None
        )
        active_episode = origin.active_episode_identity if refresh_packet is not None else None
        active_research_review = (
            origin.radar_research_review_identity if refresh_packet is not None else None
        )
        trusted = self._trusted_interval(
            reducer,
            pair.boundary,
            budget_ms=self.owner.policies.underwriting.clock_currentness_budget_ms,
        )
        index, index_source = self._current_index(
            reducer,
            trusted,
            budget_ms=self.owner.policies.underwriting.index_currentness_budget_ms,
        )
        ticker, ticker_source = self._current_ticker(
            short_name or "",
            trusted,
            budget_ms=self.owner.policies.underwriting.option_ticker_currentness_budget_ms,
        )
        platform_current = self._platform_currentness(
            reducer,
            pair.boundary,
            budget_ms=self.owner.policies.underwriting.platform_currentness_budget_ms,
        )
        catalog_complete = reducer.option_catalog.complete and bool(
            getattr(reducer, "_option_positive_scope_safe", False)
        )
        quote: ComponentBookVerticalQuote | None = None
        quote_reasons: tuple[str, ...] = ()
        if short is not None and long is not None and index is not None:
            quote, quote_reasons = evaluate_component_book_vertical(
                kind=ComponentBookQuoteKind.ENTRY,
                short_instrument=short.instrument,
                long_instrument=long.instrument,
                short_side_levels=short_book.bids,
                long_side_levels=long_book.asks,
                index_usdc_per_btc=index,
                target_quantity_btc=origin.target_quantity_btc,
                fee_rate_index_fraction=self.owner.policies.underwriting.fee_rate_index_fraction,
            )
        pair_unknown_reasons = pair.timing_unknown_reasons(
            maximum_source_skew_ms=(
                self.owner.policies.underwriting.maximum_component_pair_source_skew_ms
            ),
            maximum_receive_skew_ms=(
                self.owner.policies.underwriting.maximum_component_pair_receive_skew_ms
            ),
        )
        unknown: list[str] = list(pair_unknown_reasons)
        for condition, reason in (
            (refresh_packet is None, "RADAR_EPISODE_NOT_ACTIVE"),
            (not catalog_complete, "OPTION_CATALOG_INCOMPLETE"),
            (short is None, "SHORT_OPTION_METADATA_UNKNOWN"),
            (long is None, "LONG_OPTION_METADATA_UNKNOWN"),
            (platform_current is None, "PLATFORM_CURRENTNESS_UNKNOWN"),
            (trusted is None, "TRUSTED_TIME_UNKNOWN"),
            (index is None, "INDEX_UNKNOWN"),
            (ticker is None, "SHORT_TICKER_UNKNOWN"),
            (
                not pair.short.payload_well_formed or not pair.long.payload_well_formed,
                "COMPONENT_RPC_PAYLOAD_UNKNOWN",
            ),
        ):
            if condition:
                unknown.append(reason)
        if quote is not None and not unknown:
            component_state = COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE
        elif quote_reasons and not unknown:
            component_state = NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE
        else:
            component_state = COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN
            unknown.extend(quote_reasons)
        short_instrument = short.instrument if short is not None else None
        long_instrument = long.instrument if long is not None else None
        return replace(
            origin,
            boundary=pair.boundary,
            active_episode_identity=active_episode,
            anomaly_activation_seq=(
                origin.anomaly_activation_seq if active_episode is not None else None
            ),
            radar_research_review_identity=active_research_review,
            radar_research_activation_seq=(
                origin.radar_research_activation_seq if active_research_review is not None else None
            ),
            radar_score_packet=refresh_packet,
            short_leg_identity=(
                short.semantic_identity if short is not None else origin.short_leg_identity
            ),
            long_leg_identity=(
                long.semantic_identity if long is not None else origin.long_leg_identity
            ),
            option_type=(
                short_instrument.option_type.value if short_instrument is not None else None
            ),
            short_strike_usdc_per_btc=(
                short_instrument.strike if short_instrument is not None else None
            ),
            long_strike_usdc_per_btc=(
                long_instrument.strike if long_instrument is not None else None
            ),
            expiry_ms=(
                short_instrument.expiration_timestamp_ms if short_instrument is not None else None
            ),
            short_leg_state=(
                short_instrument.lifecycle_state.value if short_instrument is not None else None
            ),
            long_leg_state=(
                long_instrument.lifecycle_state.value if long_instrument is not None else None
            ),
            short_leg_active=(short_instrument.is_active if short_instrument is not None else None),
            long_leg_active=(long_instrument.is_active if long_instrument is not None else None),
            option_amounts_aligned=_both_amounts_aligned(
                short_instrument,
                long_instrument,
                origin.target_quantity_btc,
            ),
            platform_usable=platform_current,
            trusted_time_lower_ms=(trusted.lower_ms if trusted is not None else None),
            trusted_time_upper_ms=(trusted.upper_ms if trusted is not None else None),
            short_leg_taker_commission_fraction=(
                short_instrument.taker_commission if short_instrument is not None else None
            ),
            long_leg_taker_commission_fraction=(
                long_instrument.taker_commission if long_instrument is not None else None
            ),
            index_usdc_per_btc=index,
            short_delta=(ticker.signed_delta if ticker is not None else None),
            short_mark_iv_fraction=(ticker.mark_iv_fraction if ticker is not None else None),
            short_instrument_source=(short.source if short is not None else None),
            long_instrument_source=(long.source if long is not None else None),
            index_source=index_source,
            ticker_source=ticker_source,
            quote_source=None,
            quote_refresh_witness=None,
            unknown_reasons=tuple(sorted(set(unknown))),
            component_state=component_state,
            component_blockers=tuple(sorted((*quote_reasons, *pair_unknown_reasons))),
            component_quote=quote,
            component_short_quote_source=SourceFact(
                pair.short.source_identity,
                pair.short.boundary,
            ),
            component_long_quote_source=SourceFact(
                pair.long.source_identity,
                pair.long.boundary,
            ),
            component_pair_witness=pair,
        )

    def _component_quote_from_rest_pair(
        self,
        *,
        reducer: RadarReducer,
        anchor: _Anchor,
        kind: ComponentBookQuoteKind,
        short_book: _RestBook,
        long_book: _RestBook,
        boundary: DownstreamFactBoundary,
    ) -> ComponentBookVerticalQuote | None:
        short = self._options_by_identity.get(anchor.short_leg_identity)
        long = self._options_by_identity.get(anchor.long_leg_identity)
        trusted = self._trusted_interval(
            reducer,
            boundary,
            budget_ms=self.owner.policies.position.clock_currentness_budget_ms,
        )
        index, _ = self._current_index(
            reducer,
            trusted,
            budget_ms=self.owner.policies.position.index_currentness_budget_ms,
        )
        if (
            short is None
            or long is None
            or index is None
            or not short_book.well_formed
            or not long_book.well_formed
            or short_book.state != "open"
            or long_book.state != "open"
        ):
            return None
        quote, _ = evaluate_component_book_vertical(
            kind=kind,
            short_instrument=short.instrument,
            long_instrument=long.instrument,
            short_side_levels=(
                short_book.bids if kind is ComponentBookQuoteKind.ENTRY else short_book.asks
            ),
            long_side_levels=(
                long_book.asks if kind is ComponentBookQuoteKind.ENTRY else long_book.bids
            ),
            index_usdc_per_btc=index,
            target_quantity_btc=anchor.target_quantity_btc,
            fee_rate_index_fraction=self.owner.policies.position.fee_rate_index_fraction,
        )
        return quote

    def _refresh_admission_facts(
        self,
        *,
        reducer: RadarReducer,
        origin: UnderwritingFacts,
        boundary: DownstreamFactBoundary,
        witness: RpcAdmissionRefreshWitness,
        levels: tuple[tuple[Decimal, Decimal], ...],
        quote_known: bool,
    ) -> UnderwritingFacts:
        short_name = origin.short_leg_instrument_name
        long_name = origin.long_leg_instrument_name
        combo_name = origin.combo_instrument_name
        short = self._option_sources.get(short_name) if short_name is not None else None
        long = self._option_sources.get(long_name) if long_name is not None else None
        combo = self._combo_sources.get(combo_name) if combo_name is not None else None
        origin_anchor = _radar_anchor_identity(origin)
        refresh_packet = (
            reducer.active_radar_score_packet(
                episode_identity=origin_anchor,
                boundary=FactBoundary(
                    session_epoch=boundary.session_epoch,
                    ingress_seq=boundary.ingress_seq,
                    received_monotonic_ms=boundary.received_monotonic_ms,
                    causal_seq=boundary.causal_seq,
                ),
            )
            if origin_anchor is not None
            else None
        )
        active_episode = origin.active_episode_identity if refresh_packet is not None else None
        active_research_review = (
            origin.radar_research_review_identity if refresh_packet is not None else None
        )
        trusted = self._trusted_interval(
            reducer,
            boundary,
            budget_ms=self.owner.policies.underwriting.clock_currentness_budget_ms,
        )
        index, index_source = self._current_index(
            reducer,
            trusted,
            budget_ms=self.owner.policies.underwriting.index_currentness_budget_ms,
        )
        ticker, ticker_source = self._current_ticker(
            short_name or "",
            trusted,
            budget_ms=self.owner.policies.underwriting.option_ticker_currentness_budget_ms,
        )
        short_instrument = short.instrument if short is not None else None
        long_instrument = long.instrument if long is not None else None
        combo_instrument = combo.instrument if combo is not None else None
        platform_current = self._platform_currentness(
            reducer,
            boundary,
            budget_ms=self.owner.policies.underwriting.platform_currentness_budget_ms,
        )
        catalog_complete = reducer.option_catalog.complete and bool(
            getattr(reducer, "_option_positive_scope_safe", False)
        )
        combo_catalog_complete = reducer.combo_catalog.complete
        complete_quote = (
            quote_known
            and active_episode is not None
            and catalog_complete
            and combo_catalog_complete
            and short is not None
            and long is not None
            and combo is not None
        )
        unknown: list[str] = []
        for condition, reason in (
            (not quote_known, "RPC_REFRESH_UNKNOWN"),
            (refresh_packet is None, "RADAR_EPISODE_NOT_ACTIVE"),
            (not catalog_complete, "OPTION_CATALOG_INCOMPLETE"),
            (not combo_catalog_complete, "COMBO_CATALOG_INCOMPLETE"),
            (short is None, "SHORT_OPTION_METADATA_UNKNOWN"),
            (long is None, "LONG_OPTION_METADATA_UNKNOWN"),
            (combo is None, "COMBO_METADATA_UNKNOWN"),
            (platform_current is None, "PLATFORM_CURRENTNESS_UNKNOWN"),
            (trusted is None, "TRUSTED_TIME_UNKNOWN"),
            (index is None, "INDEX_UNKNOWN"),
            (ticker is None, "SHORT_TICKER_UNKNOWN"),
        ):
            if condition:
                unknown.append(reason)
        return replace(
            origin,
            boundary=boundary,
            active_episode_identity=active_episode,
            anomaly_activation_seq=(
                origin.anomaly_activation_seq if active_episode is not None else None
            ),
            radar_research_review_identity=active_research_review,
            radar_research_activation_seq=(
                origin.radar_research_activation_seq if active_research_review is not None else None
            ),
            radar_score_packet=refresh_packet,
            short_leg_identity=(
                short.semantic_identity if short is not None else origin.short_leg_identity
            ),
            long_leg_identity=(
                long.semantic_identity if long is not None else origin.long_leg_identity
            ),
            canonical_combo_identity=(
                combo.semantic_identity if combo is not None else origin.canonical_combo_identity
            ),
            option_type=(
                short_instrument.option_type.value if short_instrument is not None else None
            ),
            short_strike_usdc_per_btc=(
                short_instrument.strike if short_instrument is not None else None
            ),
            long_strike_usdc_per_btc=(
                long_instrument.strike if long_instrument is not None else None
            ),
            expiry_ms=(
                short_instrument.expiration_timestamp_ms if short_instrument is not None else None
            ),
            entry_consumed_levels=levels,
            atomic_state=(
                PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE.value
                if complete_quote
                else PublicAtomicQuoteState.UNKNOWN.value
            ),
            option_catalog_complete=catalog_complete,
            combo_catalog_complete=combo_catalog_complete,
            short_leg_state=(
                short_instrument.lifecycle_state.value if short_instrument is not None else None
            ),
            long_leg_state=(
                long_instrument.lifecycle_state.value if long_instrument is not None else None
            ),
            short_leg_active=(short_instrument.is_active if short_instrument is not None else None),
            long_leg_active=(long_instrument.is_active if long_instrument is not None else None),
            option_amounts_aligned=_both_amounts_aligned(
                short_instrument,
                long_instrument,
                origin.target_quantity_btc,
            ),
            combo_state=("open" if combo_instrument is not None else None),
            combo_active=(True if combo_instrument is not None else None),
            combo_amount_aligned=_amount_aligned(
                combo_instrument,
                origin.target_quantity_btc,
            ),
            platform_usable=platform_current,
            trusted_time_lower_ms=(trusted.lower_ms if trusted is not None else None),
            trusted_time_upper_ms=(trusted.upper_ms if trusted is not None else None),
            short_leg_taker_commission_fraction=(
                short_instrument.taker_commission if short_instrument is not None else None
            ),
            long_leg_taker_commission_fraction=(
                long_instrument.taker_commission if long_instrument is not None else None
            ),
            index_usdc_per_btc=index,
            short_delta=(ticker.signed_delta if ticker is not None else None),
            short_mark_iv_fraction=(ticker.mark_iv_fraction if ticker is not None else None),
            quote_source=SourceFact(witness.source_identity, witness.boundary),
            quote_refresh_witness=witness,
            short_instrument_source=(short.source if short is not None else None),
            long_instrument_source=(long.source if long is not None else None),
            index_source=index_source,
            ticker_source=ticker_source,
            unknown_reasons=tuple(sorted(unknown)),
        )

    def terminate(self, *, source: str, boundary: FactBoundary) -> None:
        reducer = self._require_reducer()
        downstream = self._boundary(reducer, boundary)
        if source == "STOP":
            terminal_kind = TerminalSource.STOP
            disposition = "CLEAN_STOP"
        elif source == "FAILURE":
            terminal_kind = TerminalSource.FAILURE
            disposition = "PROCESS_FAILURE"
        else:
            raise ValueError("terminal source must be STOP or FAILURE")
        terminal_identity = canonical_identity(
            "PublicShadowRuntimeTerminalSourceIdentity",
            self.owner.bindings.runtime_identity,
            disposition,
            downstream.as_object(),
        )
        transition = self.owner.terminate(
            boundary=downstream,
            terminal_source_identity=terminal_identity,
            terminal_source=terminal_kind,
        )
        self._consume_transition(transition, ())
        if self._case_store is not None:
            self._case_store.close_active_admitted_segments(
                boundary=downstream,
                terminal_state=("CENSORED_AT_STOP" if source == "STOP" else "CENSORED_AT_FAILURE"),
            )

    def _activate_staged_recoveries(
        self,
        boundary: DownstreamFactBoundary,
    ) -> None:
        if not self._staged_recoveries:
            return
        case_store = self._case_store
        if case_store is None:
            raise RuntimeError("recovered Entries lost their stable Shadow Case store")
        recovered = tuple(
            case_store.open_recovery_segment(
                seed.case_id,
                adoption_fact_boundary=boundary,
            )
            for seed in self._staged_recoveries
        )
        self.owner.activate_recovered_entries(recovered)
        for entry in recovered:
            value = self.owner.state_store.get_object(
                "SHADOW_ENTRY",
                entry.shadow_entry_identity,
            )
            if value is None:
                raise RuntimeError("recovered Shadow Entry lacks its current projection")
            self._remember_anchor(value)
        self._staged_recoveries = ()

    def _refresh_sources(
        self,
        reducer: RadarReducer,
        boundary: DownstreamFactBoundary,
    ) -> None:
        session_epoch = boundary.session_epoch
        if self._session_epoch != session_epoch:
            self._session_epoch = session_epoch
            self._option_sources.clear()
            self._combo_sources.clear()
            self._ticker_sources.clear()
        current_options = dict(reducer.catalog_options)
        current_options.update(reducer.options)
        lifecycle_states = getattr(reducer, "_option_lifecycle_state", {})
        for name, state in lifecycle_states.items():
            existing = current_options.get(name)
            previous = self._option_sources.get(name) or next(
                (
                    source
                    for source in self._options_by_identity.values()
                    if source.instrument.instrument_name == name
                ),
                None,
            )
            if existing is None and previous is not None:
                try:
                    existing = replace(
                        previous.instrument,
                        lifecycle_state=type(previous.instrument.lifecycle_state)(state),
                    )
                except ValueError:
                    existing = None
            if existing is not None:
                current_options[name] = existing
        for name, option_instrument in current_options.items():
            option_prior = self._option_sources.get(name)
            if option_prior is not None and option_prior.instrument == option_instrument:
                continue
            semantic_identity = _option_identity(option_instrument)
            source = SourceFact(
                canonical_identity(
                    "OptionInstrumentSourceIdentity",
                    semantic_identity,
                    option_instrument.lifecycle_state.value,
                    option_instrument.is_active,
                    option_instrument.taker_commission,
                    boundary.as_object(),
                ),
                boundary,
            )
            option_value = _OptionSource(option_instrument, semantic_identity, source)
            self._option_sources[name] = option_value
            self._options_by_identity[semantic_identity] = option_value
        live_option_names = set(current_options)
        for name in set(self._option_sources) - live_option_names:
            self._option_sources.pop(name, None)

        for name, combo_instrument in reducer.combos.items():
            combo_prior = self._combo_sources.get(name)
            if combo_prior is not None and combo_prior.instrument == combo_instrument:
                continue
            semantic_identity = _combo_identity(combo_instrument)
            source = SourceFact(
                canonical_identity(
                    "ComboInstrumentSourceIdentity",
                    semantic_identity,
                    combo_instrument.state,
                    boundary.as_object(),
                ),
                boundary,
            )
            combo_value = _ComboSource(combo_instrument, semantic_identity, source)
            self._combo_sources[name] = combo_value
            self._combos_by_identity[semantic_identity] = combo_value
        for name in set(self._combo_sources) - set(reducer.combos):
            self._combo_sources.pop(name, None)

        for name, ticker in reducer.tickers.items():
            ticker_prior = self._ticker_sources.get(name)
            if ticker_prior is not None and ticker_prior.value == ticker:
                continue
            self._ticker_sources[name] = _TickerSource(
                ticker,
                SourceFact(
                    canonical_identity(
                        "OptionTickerSourceIdentity",
                        name,
                        ticker.source_timestamp_ms,
                        ticker.signed_delta,
                        ticker.mark_iv_fraction,
                        boundary.as_object(),
                    ),
                    boundary,
                ),
            )
        for name in set(self._ticker_sources) - set(reducer.tickers):
            self._ticker_sources.pop(name, None)
        self._prune_semantic_sources()

    def _project_underwriting(
        self,
        reducer: RadarReducer,
        commit: CausalCommit,
        boundary: DownstreamFactBoundary,
    ) -> tuple[tuple[UnderwritingFacts, ...], tuple[str, ...], tuple[str, ...]]:
        current: dict[str, UnderwritingFacts] = {}
        scope_retirements: list[str] = []
        episode_retirements: set[str] = set()
        snapshots = list(reducer.active_radar_scope_snapshots(commit=commit))
        for snapshot in snapshots:
            self._require_episode_snapshot_binding(reducer, snapshot)
        by_episode = {snapshot.episode_identity: snapshot for snapshot in snapshots}
        unresolved_component_selection = any(
            snapshot.episode_identity not in self._frozen_component_by_episode
            for snapshot in snapshots
        )
        review_contexts = self._review_contexts(reducer) if unresolved_component_selection else {}
        for snapshot in snapshots:
            context = review_contexts.get(snapshot.short_leg.instrument_name)
            facts = self._underwriting_component(
                reducer=reducer,
                snapshot=snapshot,
                context=context,
                boundary=boundary,
            )
            current[facts.radar_scope_identity] = facts
        for scope, prior in self._underwriting_by_scope.items():
            if scope in current:
                continue
            prior_anchor = _radar_anchor_identity(prior)
            if prior_anchor is None:
                continue
            episode_still_active = prior_anchor in by_episode
            trusted = self._trusted_interval(
                reducer,
                boundary,
                budget_ms=self.owner.policies.underwriting.clock_currentness_budget_ms,
            )
            current[scope] = replace(
                prior,
                boundary=boundary,
                active_episode_identity=None,
                anomaly_activation_seq=None,
                radar_research_review_identity=None,
                radar_research_activation_seq=None,
                radar_score_packet=None,
                atomic_state=PublicAtomicQuoteState.NOT_EVALUATED.value,
                entry_consumed_levels=(),
                trusted_time_lower_ms=(trusted.lower_ms if trusted is not None else None),
                trusted_time_upper_ms=(trusted.upper_ms if trusted is not None else None),
                quote_source=None,
                quote_refresh_witness=None,
                component_state=COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN,
                component_blockers=(
                    "RADAR_SCOPE_NOT_CURRENT"
                    if episode_still_active
                    else "RADAR_EPISODE_NOT_ACTIVE",
                ),
                component_quote=None,
                component_short_quote_source=None,
                component_long_quote_source=None,
                component_pair_witness=None,
                unknown_reasons=(
                    "RADAR_SCOPE_NOT_CURRENT"
                    if episode_still_active
                    else "RADAR_EPISODE_NOT_ACTIVE",
                ),
            )
            scope_retirements.append(scope)
            if not episode_still_active:
                episode_retirements.add(prior_anchor)
                self._frozen_component_by_episode.pop(prior_anchor, None)
        metadata_changed = False
        for scope, facts in current.items():
            self._underwriting_by_scope[scope] = facts
            metadata = self._underwriting_display_metadata(scope, facts)
            if self._workbench_underwriting_metadata_by_scope.get(scope) != metadata:
                self._workbench_underwriting_metadata_by_scope[scope] = metadata
                metadata_changed = True
        if metadata_changed:
            self._workbench_underwriting_metadata = tuple(
                self._workbench_underwriting_metadata_by_scope[key]
                for key in sorted(self._workbench_underwriting_metadata_by_scope)
            )
        return (
            tuple(current[key] for key in sorted(current)),
            tuple(sorted(scope_retirements)),
            tuple(sorted(episode_retirements)),
        )

    def _review_contexts(self, reducer: RadarReducer) -> dict[str, ReviewContext]:
        calculations = {
            name: result.calculation
            for name, result in reducer.results.items()
            if result.calculation is not None
        }
        return build_review_contexts(
            options=reducer.options,
            calculations=calculations,
            detector_states={
                name: result.detector_state for name, result in reducer.results.items()
            },
            detector_reasons={name: result.reason for name, result in reducer.results.items()},
            tickers=reducer.current_diagnostic_tickers,
            option_books=reducer.option_books,
            option_catalog_complete=reducer.option_catalog.complete,
            index_usdc_per_btc=reducer.current_index_price_usdc_per_btc,
            target_quantity_btc=self.owner.policies.underwriting.target_base_quantity_btc,
            fee_rate_index_fraction=self.owner.policies.underwriting.fee_rate_index_fraction,
        )

    def _underwriting_component(
        self,
        *,
        reducer: RadarReducer,
        snapshot: AtomicScopeSnapshot,
        context: ReviewContext | None,
        boundary: DownstreamFactBoundary,
    ) -> UnderwritingFacts:
        short_name = snapshot.short_leg.instrument_name
        short = self._option_sources.get(short_name)
        trusted = self._trusted_interval(
            reducer,
            boundary,
            budget_ms=self.owner.policies.underwriting.clock_currentness_budget_ms,
        )
        index, index_source = self._current_index(
            reducer,
            trusted,
            budget_ms=self.owner.policies.underwriting.index_currentness_budget_ms,
        )
        catalog_complete = reducer.option_catalog.complete and bool(
            getattr(reducer, "_option_positive_scope_safe", False)
        )
        frozen_selection = self._frozen_component_by_episode.get(snapshot.episode_identity)
        selection_unknown_reasons: tuple[str, ...] = ()
        if (
            frozen_selection is None
            and catalog_complete
            and short is not None
            and index is not None
        ):
            frozen_selection, selection_unknown_reasons = self._select_underwriting_component_long(
                reducer=reducer,
                short=short,
                index_usdc_per_btc=index,
            )
            if frozen_selection is not None:
                self._frozen_component_by_episode[snapshot.episode_identity] = frozen_selection
        frozen_long_name = (
            frozen_selection.candidate.long_instrument_name
            if frozen_selection is not None
            else None
        )
        long = self._option_sources.get(frozen_long_name) if frozen_long_name is not None else None
        short_identity = short.semantic_identity if short is not None else None
        long_identity = long.semantic_identity if long is not None else None
        scope_identity = canonical_identity(
            "RadarComponentUnderwritingScopeIdentity",
            self.owner.bindings.runtime_identity,
            self.owner.bindings.radar_policy_identity,
            snapshot.episode_identity,
            short_identity,
            long_identity or "NO_FROZEN_PROTECTIVE_COMPONENT",
        )
        ticker, ticker_source = self._current_ticker(
            short_name,
            trusted,
            budget_ms=self.owner.policies.underwriting.option_ticker_currentness_budget_ms,
        )
        platform_current = self._platform_currentness(
            reducer,
            boundary,
            budget_ms=self.owner.policies.underwriting.platform_currentness_budget_ms,
        )
        short_book = reducer.option_books.get(short_name)
        long_book = (
            reducer.option_books.get(frozen_long_name) if frozen_long_name is not None else None
        )
        short_book_source = self._option_book_source(
            reducer,
            short_name,
            short_identity,
        )
        long_book_source = (
            self._option_book_source(reducer, frozen_long_name, long_identity)
            if frozen_long_name is not None
            else None
        )
        component_state = COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN
        component_blockers: list[str] = []
        quote: ComponentBookVerticalQuote | None = None
        if frozen_long_name is None:
            legged_state = context.legged_structure.state if context is not None else None
            if selection_unknown_reasons:
                component_blockers.extend(selection_unknown_reasons)
            elif legged_state is LeggedReferenceState.NO_PROTECTIVE_LEG:
                component_state = NO_PROTECTIVE_COMPONENT
                component_blockers.append(NO_PROTECTIVE_COMPONENT)
            elif legged_state is LeggedReferenceState.NO_TARGET_SIZE_REFERENCE:
                component_state = NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE
                component_blockers.append(NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE)
            else:
                component_blockers.extend(
                    context.legged_structure.missing_reasons
                    if context is not None
                    else ("REVIEW_CONTEXT_UNKNOWN",)
                )
        else:
            component_blockers.extend(
                self._component_quote_prerequisite_reasons(
                    catalog_complete=catalog_complete,
                    platform_current=platform_current,
                    trusted=trusted,
                    index=index,
                    short=short,
                    long=long,
                    short_book=short_book,
                    long_book=long_book,
                    short_book_source=short_book_source,
                    long_book_source=long_book_source,
                )
            )
            if not component_blockers:
                assert short is not None
                assert long is not None
                assert short_book is not None
                assert long_book is not None
                assert index is not None
                quote, quote_reasons = evaluate_component_book_vertical(
                    kind=ComponentBookQuoteKind.ENTRY,
                    short_instrument=short.instrument,
                    long_instrument=long.instrument,
                    short_side_levels=short_book.levels("bid"),
                    long_side_levels=long_book.levels("ask"),
                    index_usdc_per_btc=index,
                    target_quantity_btc=(self.owner.policies.underwriting.target_base_quantity_btc),
                    fee_rate_index_fraction=(
                        self.owner.policies.underwriting.fee_rate_index_fraction
                    ),
                )
                if quote is not None:
                    component_state = COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE
                elif any(
                    reason.endswith("METADATA_UNKNOWN")
                    or reason == "SHORT_STRESSED_PRICE_NON_POSITIVE"
                    or reason == "LONG_STRESSED_PRICE_NON_POSITIVE"
                    for reason in quote_reasons
                ):
                    component_blockers.extend(quote_reasons)
                elif any(
                    reason
                    in {
                        "NOT_A_PROTECTIVE_VERTICAL",
                        "SHORT_LEG_NOT_OPEN_ACTIVE",
                        "LONG_LEG_NOT_OPEN_ACTIVE",
                        "SHORT_TARGET_AMOUNT_INELIGIBLE",
                        "LONG_TARGET_AMOUNT_INELIGIBLE",
                    }
                    for reason in quote_reasons
                ):
                    component_state = NO_PROTECTIVE_COMPONENT
                    component_blockers.extend(quote_reasons)
                else:
                    component_state = NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE
                    component_blockers.extend(quote_reasons)

        unknown: list[str] = []
        for condition, reason in (
            (not catalog_complete, "OPTION_CATALOG_INCOMPLETE"),
            (short is None, "SHORT_OPTION_METADATA_UNKNOWN"),
            (
                frozen_long_name is not None and long is None,
                "LONG_OPTION_METADATA_UNKNOWN",
            ),
            (platform_current is None, "PLATFORM_CURRENTNESS_UNKNOWN"),
            (trusted is None, "TRUSTED_TIME_UNKNOWN"),
            (index is None, "INDEX_UNKNOWN"),
            (ticker is None, "SHORT_TICKER_UNKNOWN"),
        ):
            if condition:
                unknown.append(reason)
        if component_state == COMPONENT_BOOK_COUNTERFACTUAL_UNKNOWN:
            unknown.extend(component_blockers)
        short_instrument = short.instrument if short is not None else None
        long_instrument = long.instrument if long is not None else None
        is_high_episode = snapshot.score_band is ScoreBand.HIGH
        return UnderwritingFacts(
            boundary=boundary,
            radar_scope_identity=scope_identity,
            active_episode_identity=(snapshot.episode_identity if is_high_episode else None),
            anomaly_activation_seq=(snapshot.anomaly_activation_seq if is_high_episode else None),
            short_leg_identity=short_identity,
            long_leg_identity=long_identity,
            canonical_combo_identity=None,
            combo_instrument_name=None,
            option_type=(
                short_instrument.option_type.value if short_instrument is not None else None
            ),
            short_strike_usdc_per_btc=(
                short_instrument.strike if short_instrument is not None else None
            ),
            long_strike_usdc_per_btc=(
                long_instrument.strike if long_instrument is not None else None
            ),
            expiry_ms=(
                short_instrument.expiration_timestamp_ms if short_instrument is not None else None
            ),
            target_quantity_btc=self.owner.policies.underwriting.target_base_quantity_btc,
            entry_direction="SELL" if frozen_long_name is not None else None,
            entry_consumed_levels=(),
            atomic_state=snapshot.result.state.value,
            option_catalog_complete=catalog_complete,
            combo_catalog_complete=snapshot.combo_catalog_complete,
            short_leg_state=(
                short_instrument.lifecycle_state.value if short_instrument is not None else None
            ),
            long_leg_state=(
                long_instrument.lifecycle_state.value if long_instrument is not None else None
            ),
            short_leg_active=(short_instrument.is_active if short_instrument is not None else None),
            long_leg_active=(long_instrument.is_active if long_instrument is not None else None),
            option_amounts_aligned=_both_amounts_aligned(
                short_instrument,
                long_instrument,
                self.owner.policies.underwriting.target_base_quantity_btc,
            ),
            combo_state=None,
            combo_active=None,
            combo_amount_aligned=None,
            platform_usable=platform_current,
            trusted_time_lower_ms=(trusted.lower_ms if trusted is not None else None),
            trusted_time_upper_ms=(trusted.upper_ms if trusted is not None else None),
            short_leg_taker_commission_fraction=(
                short_instrument.taker_commission if short_instrument is not None else None
            ),
            long_leg_taker_commission_fraction=(
                long_instrument.taker_commission if long_instrument is not None else None
            ),
            index_usdc_per_btc=index,
            short_delta=(ticker.signed_delta if ticker is not None else None),
            short_mark_iv_fraction=(ticker.mark_iv_fraction if ticker is not None else None),
            quote_source=None,
            quote_refresh_witness=None,
            short_instrument_source=(short.source if short is not None else None),
            long_instrument_source=(long.source if long is not None else None),
            index_source=index_source,
            ticker_source=ticker_source,
            short_leg_instrument_name=short_name,
            long_leg_instrument_name=frozen_long_name,
            radar_score_packet=snapshot.radar_score_packet,
            radar_research_review_identity=(None if is_high_episode else snapshot.episode_identity),
            radar_research_activation_seq=(
                None if is_high_episode else snapshot.anomaly_activation_seq
            ),
            unknown_reasons=tuple(sorted(set(unknown))),
            component_state=component_state,
            component_blockers=tuple(sorted(set(component_blockers))),
            component_quote=quote,
            component_short_quote_source=short_book_source,
            component_long_quote_source=long_book_source,
            component_pair_witness=None,
            protective_leg_selection_rule_identity=(
                frozen_selection.selection_rule_identity if frozen_selection is not None else None
            ),
            candidate_protective_leg_count=(
                frozen_selection.candidate_protective_leg_count
                if frozen_selection is not None
                else None
            ),
        )

    def _select_underwriting_component_long(
        self,
        *,
        reducer: RadarReducer,
        short: _OptionSource,
        index_usdc_per_btc: Decimal,
    ) -> tuple[UnderwritingComponentSelection | None, tuple[str, ...]]:
        """Compose every evaluable legal leg into the sole Underwriting selector."""
        short_name = short.instrument.instrument_name
        target_quantity = self.owner.policies.underwriting.target_base_quantity_btc
        if (
            short.instrument.lifecycle_state.value != "open"
            or not short.instrument.is_active
            or (
                short.instrument.amount is not None
                and check_target_amount(target_quantity, short.instrument.amount).state
                is AmountState.INELIGIBLE
            )
        ):
            return None, ()
        short_metadata_unknown = self._selection_metadata_unknown_reasons(short)
        if short_metadata_unknown:
            return None, short_metadata_unknown
        short_book = reducer.option_books.get(short_name)
        short_source = self._option_book_source(
            reducer,
            short_name,
            short.semantic_identity,
        )
        if short_book is None or short_book.state is not BookState.USABLE:
            return None, (f"{short_name}:BOOK_UNKNOWN",)
        if short_source is None:
            return None, (f"{short_name}:BOOK_SOURCE_UNKNOWN",)
        candidates: list[UnderwritingComponentCandidate] = []
        unknown_reasons: list[str] = []
        for long in sorted(
            self._option_sources.values(),
            key=lambda value: value.instrument.instrument_name,
        ):
            if not is_protective_vertical(short.instrument, long.instrument):
                continue
            long_name = long.instrument.instrument_name
            if (
                long.instrument.lifecycle_state.value != "open"
                or not long.instrument.is_active
                or (
                    long.instrument.amount is not None
                    and check_target_amount(target_quantity, long.instrument.amount).state
                    is AmountState.INELIGIBLE
                )
            ):
                continue
            metadata_unknown = self._selection_metadata_unknown_reasons(long)
            if metadata_unknown:
                unknown_reasons.extend(metadata_unknown)
                continue
            long_book = reducer.option_books.get(long_name)
            long_source = self._option_book_source(
                reducer,
                long_name,
                long.semantic_identity,
            )
            if long_book is None or long_book.state is not BookState.USABLE:
                unknown_reasons.append(f"{long_name}:BOOK_UNKNOWN")
                continue
            if long_source is None:
                unknown_reasons.append(f"{long_name}:BOOK_SOURCE_UNKNOWN")
                continue
            quote, quote_reasons = evaluate_component_book_vertical(
                kind=ComponentBookQuoteKind.ENTRY,
                short_instrument=short.instrument,
                long_instrument=long.instrument,
                short_side_levels=short_book.levels("bid"),
                long_side_levels=long_book.levels("ask"),
                index_usdc_per_btc=index_usdc_per_btc,
                target_quantity_btc=target_quantity,
                fee_rate_index_fraction=(self.owner.policies.underwriting.fee_rate_index_fraction),
            )
            if quote is None:
                for reason in quote_reasons:
                    if reason.endswith("METADATA_UNKNOWN") or reason.endswith(
                        "STRESSED_PRICE_NON_POSITIVE"
                    ):
                        instrument_name = short_name if reason.startswith("SHORT_") else long_name
                        unknown_reasons.append(f"{instrument_name}:{reason}")
                continue
            candidates.append(
                UnderwritingComponentCandidate(
                    long_instrument_name=long_name,
                    economics=compute_component_entry_economics(
                        quote=quote,
                        future_cost_reserve_usdc=(
                            self.owner.policies.underwriting.future_cost_reserve_usdc
                        ),
                    ),
                    consumed_level_count=quote.consumed_level_count,
                )
            )
        if unknown_reasons:
            return None, tuple(sorted(set(unknown_reasons)))
        policy = self.owner.policies.underwriting
        selection = select_underwriting_component(
            candidates,
            maximum_underwriting_reserved_loss_usdc=(
                policy.maximum_underwriting_reserved_loss_usdc
            ),
            minimum_net_entry_credit_usdc=policy.minimum_net_entry_credit_usdc,
            minimum_net_credit_to_payoff_cap_fraction=(
                policy.minimum_net_credit_to_payoff_cap_fraction
            ),
            maximum_entry_consumed_level_count=policy.maximum_entry_consumed_level_count,
        )
        return selection, ()

    @staticmethod
    def _selection_metadata_unknown_reasons(source: _OptionSource) -> tuple[str, ...]:
        reasons: list[str] = []
        if source.instrument.amount is None:
            reasons.append(f"{source.instrument.instrument_name}:AMOUNT_METADATA_UNKNOWN")
        if source.instrument.price_tick is None:
            reasons.append(f"{source.instrument.instrument_name}:PRICE_TICK_METADATA_UNKNOWN")
        return tuple(reasons)

    @staticmethod
    def _component_quote_prerequisite_reasons(
        *,
        catalog_complete: bool,
        platform_current: bool | None,
        trusted: TimeInterval | None,
        index: Decimal | None,
        short: _OptionSource | None,
        long: _OptionSource | None,
        short_book: object,
        long_book: object,
        short_book_source: SourceFact | None,
        long_book_source: SourceFact | None,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        for condition, reason in (
            (not catalog_complete, "OPTION_CATALOG_INCOMPLETE"),
            (platform_current is None, "PLATFORM_CURRENTNESS_UNKNOWN"),
            (trusted is None, "TRUSTED_TIME_UNKNOWN"),
            (index is None, "INDEX_UNKNOWN"),
            (short is None, "SHORT_OPTION_METADATA_UNKNOWN"),
            (long is None, "LONG_OPTION_METADATA_UNKNOWN"),
            (
                short_book is None
                or getattr(short_book, "state", None) is not BookState.USABLE
                or short_book_source is None,
                "SHORT_OPTION_BOOK_UNKNOWN",
            ),
            (
                long_book is None
                or getattr(long_book, "state", None) is not BookState.USABLE
                or long_book_source is None,
                "LONG_OPTION_BOOK_UNKNOWN",
            ),
        ):
            if condition:
                reasons.append(reason)
        return tuple(reasons)

    def _underwriting_quote(
        self,
        reducer: RadarReducer,
        snapshot: AtomicScopeSnapshot,
        quote: AtomicQuote,
        boundary: DownstreamFactBoundary,
    ) -> UnderwritingFacts:
        short = self._option_sources.get(snapshot.short_leg.instrument_name)
        long = self._option_sources.get(quote.match.long_instrument_name)
        combo = self._combo_sources.get(quote.match.combo_instrument_name)
        short_identity = short.semantic_identity if short is not None else None
        long_identity = long.semantic_identity if long is not None else None
        combo_identity = combo.semantic_identity if combo is not None else None
        scope_identity = canonical_identity(
            "RadarUnderwritingScopeIdentity",
            self.owner.bindings.runtime_identity,
            self.owner.bindings.radar_policy_identity,
            snapshot.episode_identity,
            short_identity,
            combo_identity,
        )
        witness = (
            self._subscription_witness(
                reducer,
                quote.match.combo_instrument_name,
                combo_identity,
            )
            if combo_identity is not None
            else None
        )
        trusted = self._trusted_interval(
            reducer,
            boundary,
            budget_ms=self.owner.policies.underwriting.clock_currentness_budget_ms,
        )
        index, index_source = self._current_index(
            reducer,
            trusted,
            budget_ms=self.owner.policies.underwriting.index_currentness_budget_ms,
        )
        ticker, ticker_source = self._current_ticker(
            snapshot.short_leg.instrument_name,
            trusted,
            budget_ms=self.owner.policies.underwriting.option_ticker_currentness_budget_ms,
        )
        platform_current = self._platform_currentness(
            reducer,
            boundary,
            budget_ms=self.owner.policies.underwriting.platform_currentness_budget_ms,
        )
        unknown: list[str] = []
        for condition, reason in (
            (short is None, "SHORT_OPTION_METADATA_UNKNOWN"),
            (long is None, "LONG_OPTION_METADATA_UNKNOWN"),
            (combo is None, "COMBO_METADATA_UNKNOWN"),
            (witness is None, "COMBO_QUOTE_RECEIPT_UNKNOWN"),
            (platform_current is None, "PLATFORM_CURRENTNESS_UNKNOWN"),
            (trusted is None, "TRUSTED_TIME_UNKNOWN"),
            (index is None, "INDEX_UNKNOWN"),
            (ticker is None, "SHORT_TICKER_UNKNOWN"),
        ):
            if condition:
                unknown.append(reason)
        short_instrument = short.instrument if short is not None else None
        long_instrument = long.instrument if long is not None else None
        combo_instrument = combo.instrument if combo is not None else None
        is_high_episode = snapshot.score_band is ScoreBand.HIGH
        return UnderwritingFacts(
            boundary=boundary,
            radar_scope_identity=scope_identity,
            active_episode_identity=(snapshot.episode_identity if is_high_episode else None),
            anomaly_activation_seq=(snapshot.anomaly_activation_seq if is_high_episode else None),
            short_leg_identity=short_identity,
            long_leg_identity=long_identity,
            canonical_combo_identity=combo_identity,
            combo_instrument_name=quote.match.combo_instrument_name,
            option_type=(
                short_instrument.option_type.value if short_instrument is not None else None
            ),
            short_strike_usdc_per_btc=(
                short_instrument.strike if short_instrument is not None else None
            ),
            long_strike_usdc_per_btc=(
                long_instrument.strike if long_instrument is not None else None
            ),
            expiry_ms=(
                short_instrument.expiration_timestamp_ms if short_instrument is not None else None
            ),
            target_quantity_btc=self.owner.policies.underwriting.target_base_quantity_btc,
            entry_direction=quote.match.direction.value,
            entry_consumed_levels=tuple(
                (level.price, level.amount) for level in quote.consumed_levels
            ),
            atomic_state=snapshot.result.state.value,
            option_catalog_complete=snapshot.option_catalog_complete,
            combo_catalog_complete=snapshot.combo_catalog_complete,
            short_leg_state=(
                short_instrument.lifecycle_state.value if short_instrument is not None else None
            ),
            long_leg_state=(
                long_instrument.lifecycle_state.value if long_instrument is not None else None
            ),
            short_leg_active=(short_instrument.is_active if short_instrument is not None else None),
            long_leg_active=(long_instrument.is_active if long_instrument is not None else None),
            option_amounts_aligned=_both_amounts_aligned(
                short_instrument,
                long_instrument,
                self.owner.policies.underwriting.target_base_quantity_btc,
            ),
            combo_state=("open" if combo_instrument is not None else None),
            combo_active=(True if combo_instrument is not None else None),
            combo_amount_aligned=_amount_aligned(
                combo_instrument,
                self.owner.policies.underwriting.target_base_quantity_btc,
            ),
            platform_usable=platform_current,
            trusted_time_lower_ms=(trusted.lower_ms if trusted is not None else None),
            trusted_time_upper_ms=(trusted.upper_ms if trusted is not None else None),
            short_leg_taker_commission_fraction=(
                short_instrument.taker_commission if short_instrument is not None else None
            ),
            long_leg_taker_commission_fraction=(
                long_instrument.taker_commission if long_instrument is not None else None
            ),
            index_usdc_per_btc=index,
            short_delta=(ticker.signed_delta if ticker is not None else None),
            short_mark_iv_fraction=(ticker.mark_iv_fraction if ticker is not None else None),
            quote_source=(
                SourceFact(witness.source_identity, witness.boundary)
                if witness is not None
                else None
            ),
            quote_refresh_witness=witness,
            short_instrument_source=(short.source if short is not None else None),
            long_instrument_source=(long.source if long is not None else None),
            index_source=index_source,
            ticker_source=ticker_source,
            short_leg_instrument_name=(snapshot.short_leg.instrument_name),
            long_leg_instrument_name=(
                long_instrument.instrument_name if long_instrument is not None else None
            ),
            radar_score_packet=snapshot.radar_score_packet,
            radar_research_review_identity=(None if is_high_episode else snapshot.episode_identity),
            radar_research_activation_seq=(
                None if is_high_episode else snapshot.anomaly_activation_seq
            ),
            unknown_reasons=tuple(sorted(unknown)),
        )

    def _underwriting_unknown(
        self,
        reducer: RadarReducer,
        snapshot: AtomicScopeSnapshot,
        boundary: DownstreamFactBoundary,
    ) -> UnderwritingFacts:
        short = self._option_sources.get(snapshot.short_leg.instrument_name)
        short_identity = short.semantic_identity if short is not None else None
        platform_current = self._platform_currentness(
            reducer,
            boundary,
            budget_ms=self.owner.policies.underwriting.platform_currentness_budget_ms,
        )
        is_high_episode = snapshot.score_band is ScoreBand.HIGH
        return UnderwritingFacts(
            boundary=boundary,
            radar_scope_identity=canonical_identity(
                "RadarUnderwritingScopeIdentity",
                self.owner.bindings.runtime_identity,
                self.owner.bindings.radar_policy_identity,
                snapshot.episode_identity,
                short_identity,
                "NO_COMBO",
            ),
            active_episode_identity=(snapshot.episode_identity if is_high_episode else None),
            anomaly_activation_seq=(snapshot.anomaly_activation_seq if is_high_episode else None),
            short_leg_identity=short_identity,
            long_leg_identity=None,
            canonical_combo_identity=None,
            combo_instrument_name=None,
            option_type=(short.instrument.option_type.value if short is not None else None),
            short_strike_usdc_per_btc=(short.instrument.strike if short is not None else None),
            long_strike_usdc_per_btc=None,
            expiry_ms=(short.instrument.expiration_timestamp_ms if short is not None else None),
            target_quantity_btc=self.owner.policies.underwriting.target_base_quantity_btc,
            entry_direction=None,
            entry_consumed_levels=(),
            atomic_state=snapshot.result.state.value,
            option_catalog_complete=snapshot.option_catalog_complete,
            combo_catalog_complete=snapshot.combo_catalog_complete,
            short_leg_state=(short.instrument.lifecycle_state.value if short is not None else None),
            long_leg_state=None,
            short_leg_active=(short.instrument.is_active if short is not None else None),
            long_leg_active=None,
            option_amounts_aligned=None,
            combo_state=None,
            combo_active=None,
            combo_amount_aligned=None,
            platform_usable=platform_current,
            trusted_time_lower_ms=None,
            trusted_time_upper_ms=None,
            short_leg_taker_commission_fraction=(
                short.instrument.taker_commission if short is not None else None
            ),
            long_leg_taker_commission_fraction=None,
            index_usdc_per_btc=None,
            short_delta=None,
            short_mark_iv_fraction=None,
            quote_source=None,
            quote_refresh_witness=None,
            short_instrument_source=(short.source if short is not None else None),
            long_instrument_source=None,
            index_source=None,
            ticker_source=None,
            short_leg_instrument_name=(snapshot.short_leg.instrument_name),
            long_leg_instrument_name=None,
            radar_score_packet=snapshot.radar_score_packet,
            radar_research_review_identity=(None if is_high_episode else snapshot.episode_identity),
            radar_research_activation_seq=(
                None if is_high_episode else snapshot.anomaly_activation_seq
            ),
            unknown_reasons=tuple(snapshot.result.unknown_reasons)
            or ("ATOMIC_SCOPE_NOT_EVALUABLE",),
        )

    @staticmethod
    def _require_episode_snapshot_binding(
        reducer: RadarReducer,
        snapshot: AtomicScopeSnapshot,
    ) -> None:
        episode = next(
            (
                tracker.episode
                for tracker in reducer.bucket_trackers.values()
                if tracker.episode is not None
                and tracker.episode.episode_identity == snapshot.episode_identity
            ),
            None,
        )
        if (
            episode is None
            or episode.leader_instrument_name != snapshot.short_leg.instrument_name
            or episode.activation_causal_seq != snapshot.anomaly_activation_seq
            or episode.score_band is not snapshot.score_band
            or snapshot.radar_score_packet.policy_identity != reducer.policy.identity
            or snapshot.radar_score_packet.leader_instrument_name
            != snapshot.short_leg.instrument_name
        ):
            raise ValueError("Radar bucket episode is not bound to its atomic scope snapshot")

    def _replace_unknown_underwriting(
        self,
        reducer: RadarReducer,
        prior: UnderwritingFacts,
        snapshot: AtomicScopeSnapshot,
        boundary: DownstreamFactBoundary,
    ) -> UnderwritingFacts:
        platform_current = self._platform_currentness(
            reducer,
            boundary,
            budget_ms=self.owner.policies.underwriting.platform_currentness_budget_ms,
        )
        return replace(
            prior,
            boundary=boundary,
            atomic_state=snapshot.result.state.value,
            option_catalog_complete=snapshot.option_catalog_complete,
            combo_catalog_complete=snapshot.combo_catalog_complete,
            platform_usable=platform_current,
            quote_refresh_witness=None,
            unknown_reasons=tuple(snapshot.result.unknown_reasons)
            or ("ATOMIC_SCOPE_NOT_EVALUABLE",),
        )

    def _project_position(
        self,
        *,
        reducer: RadarReducer,
        anchor: _Anchor,
        boundary: DownstreamFactBoundary,
        rpc_witness: RpcAdmissionRefreshWitness | None = None,
        rpc_levels: tuple[tuple[Decimal, Decimal], ...] = (),
        rpc_quote_known: bool = False,
        component_pair: ComponentBookPairWitness | None = None,
        component_quote: ComponentBookVerticalQuote | None = None,
        component_short_quote_source: SourceFact | None = None,
        component_long_quote_source: SourceFact | None = None,
    ) -> PositionFacts:
        short = self._options_by_identity.get(anchor.short_leg_identity)
        long = self._options_by_identity.get(anchor.long_leg_identity)
        short_live = (
            self._option_sources.get(short.instrument.instrument_name)
            if short is not None
            else None
        )
        long_live = (
            self._option_sources.get(long.instrument.instrument_name) if long is not None else None
        )
        structure_values: tuple[bool | None, ...] = (
            (
                short_live.semantic_identity == anchor.short_leg_identity
                if short_live is not None
                else None
            ),
            (
                long_live.semantic_identity == anchor.long_leg_identity
                if long_live is not None
                else None
            ),
        )
        canonical_structure = (
            True
            if all(value is True for value in structure_values)
            else (False if any(value is False for value in structure_values) else None)
        )
        trusted = self._trusted_interval(
            reducer,
            boundary,
            budget_ms=self.owner.policies.position.clock_currentness_budget_ms,
        )
        natural_terminal_boundary_reached = any(
            member is not None
            and member.instrument.lifecycle_state.value in {"settlement", "delivered", "archivized"}
            for member in (short_live, long_live)
        ) or (
            trusted is not None
            and any(
                member is not None and trusted.lower_ms >= member.instrument.expiration_timestamp_ms
                for member in (short, long)
            )
        )
        index, index_source = self._current_index(
            reducer,
            trusted,
            budget_ms=self.owner.policies.position.index_currentness_budget_ms,
        )
        ticker, ticker_source = self._current_ticker(
            short.instrument.instrument_name if short is not None else "",
            trusted,
            budget_ms=self.owner.policies.position.option_ticker_currentness_budget_ms,
        )
        close_direction = "BUY"
        option_availability = _option_availability(
            short_live,
            long_live,
            anchor.target_quantity_btc,
        )
        atomic_availability = (
            CloseAtomicAvailability.KNOWN_UNAVAILABLE
            if reducer.combo_catalog.complete
            else CloseAtomicAvailability.UNKNOWN
        )
        short_book = (
            reducer.option_books.get(short.instrument.instrument_name)
            if short is not None
            else None
        )
        long_book = (
            reducer.option_books.get(long.instrument.instrument_name) if long is not None else None
        )
        if component_pair is None:
            component_short_quote_source = (
                self._option_book_source(
                    reducer,
                    short.instrument.instrument_name,
                    anchor.short_leg_identity,
                )
                if short is not None
                else None
            )
            component_long_quote_source = (
                self._option_book_source(
                    reducer,
                    long.instrument.instrument_name,
                    anchor.long_leg_identity,
                )
                if long is not None
                else None
            )
            if (
                component_quote is None
                and short is not None
                and long is not None
                and short_book is not None
                and long_book is not None
                and short_book.state is BookState.USABLE
                and long_book.state is BookState.USABLE
                and component_short_quote_source is not None
                and component_long_quote_source is not None
                and index is not None
            ):
                component_quote, _ = evaluate_component_book_vertical(
                    kind=ComponentBookQuoteKind.CLOSE,
                    short_instrument=short.instrument,
                    long_instrument=long.instrument,
                    short_side_levels=short_book.levels("ask"),
                    long_side_levels=long_book.levels("bid"),
                    index_usdc_per_btc=index,
                    target_quantity_btc=anchor.target_quantity_btc,
                    fee_rate_index_fraction=self.owner.policies.position.fee_rate_index_fraction,
                )
        component_pair_unknown_reasons = (
            component_pair.timing_unknown_reasons(
                maximum_source_skew_ms=(
                    self.owner.policies.position.maximum_component_pair_source_skew_ms
                ),
                maximum_receive_skew_ms=(
                    self.owner.policies.position.maximum_component_pair_receive_skew_ms
                ),
            )
            if component_pair is not None
            else ()
        )
        if component_pair_unknown_reasons:
            component_quote = None
        component_books_known = (
            (
                component_pair.short.payload_well_formed
                and component_pair.long.payload_well_formed
                and not component_pair_unknown_reasons
            )
            if component_pair is not None
            else (
                short_book is not None
                and long_book is not None
                and short_book.state is BookState.USABLE
                and long_book.state is BookState.USABLE
                and component_short_quote_source is not None
                and component_long_quote_source is not None
            )
        )
        if component_quote is not None:
            component_reference = PredicateTruth.TRUE
            book_availability = CloseBookAvailability.FULL_QUANTITY
        elif component_books_known:
            component_reference = PredicateTruth.FALSE
            book_availability = CloseBookAvailability.INSUFFICIENT
        else:
            component_reference = PredicateTruth.UNKNOWN
            book_availability = CloseBookAvailability.UNKNOWN
        platform_current = self._platform_currentness(
            reducer,
            boundary,
            budget_ms=self.owner.policies.position.platform_currentness_budget_ms,
        )
        required_sources = _required_component_sources_continuous(
            platform_current=platform_current,
            trusted=trusted,
            index=index,
            ticker=ticker,
            short=short_live,
            long=long_live,
            natural_terminal_boundary_reached=natural_terminal_boundary_reached,
        )
        return PositionFacts(
            boundary=boundary,
            trusted_time_lower_ms=(trusted.lower_ms if trusted is not None else None),
            trusted_time_upper_ms=(trusted.upper_ms if trusted is not None else None),
            platform_continuous=platform_current,
            required_sources_continuous=required_sources,
            canonical_structure_intact=canonical_structure,
            short_leg_state=(
                short_live.instrument.lifecycle_state.value if short_live is not None else None
            ),
            long_leg_state=(
                long_live.instrument.lifecycle_state.value if long_live is not None else None
            ),
            short_leg_active=(short_live.instrument.is_active if short_live is not None else None),
            long_leg_active=(long_live.instrument.is_active if long_live is not None else None),
            current_index_usdc_per_btc=index,
            current_short_delta=(ticker.signed_delta if ticker is not None else None),
            current_short_mark_iv_fraction=(
                ticker.mark_iv_fraction if ticker is not None else None
            ),
            close_quote_facts=CloseQuoteFacts(
                option_availability=option_availability,
                atomic_availability=atomic_availability,
                component_reference=component_reference,
                book_availability=book_availability,
                consumed_levels=(),
                component_quote=component_quote,
            ),
            close_direction=close_direction,
            quote_source=None,
            quote_refresh_witness=None,
            short_leg_taker_commission_fraction=(
                short_live.instrument.taker_commission if short_live is not None else None
            ),
            long_leg_taker_commission_fraction=(
                long_live.instrument.taker_commission if long_live is not None else None
            ),
            short_commission_source=(short_live.source if short_live is not None else None),
            long_commission_source=(long_live.source if long_live is not None else None),
            index_source=index_source,
            ticker_source=ticker_source,
            current_combo_subscription_witness=None,
            lifecycle_short_source=(
                short_live.source
                if short_live is not None
                and short_live.instrument.lifecycle_state.value in {"delivered", "archivized"}
                else None
            ),
            lifecycle_long_source=(
                long_live.source
                if long_live is not None
                and long_live.instrument.lifecycle_state.value in {"delivered", "archivized"}
                else None
            ),
            component_quote=component_quote,
            component_short_quote_source=component_short_quote_source,
            component_long_quote_source=component_long_quote_source,
            component_pair_witness=component_pair,
            component_pair_unknown_reasons=component_pair_unknown_reasons,
        )

    def _consume_transition(
        self,
        transition: OwnerTransition,
        facts: Sequence[UnderwritingFacts],
    ) -> tuple[ShadowRpcIntent, ...]:
        reducer = self._require_reducer()
        for retirement in transition.rpc_retirements:
            reducer.retire_shadow_rpc(
                request_id=retirement.request_id,
                boundary=FactBoundary(
                    session_epoch=retirement.boundary.session_epoch,
                    ingress_seq=retirement.boundary.ingress_seq,
                    received_monotonic_ms=retirement.boundary.received_monotonic_ms,
                    causal_seq=retirement.boundary.causal_seq,
                ),
            )
            retired_context = self._requests.pop(retirement.request_id, None)
            if retired_context is not None and retired_context.role is not None:
                self._paired_responses.pop(
                    (
                        self._component_request_family(retired_context.purpose),
                        retired_context.owner_identity,
                    ),
                    None,
                )
        facts_by_slot = {
            canonical_identity(
                "UnderwritingPositionSlotKeyIdentity",
                self.owner.bindings.runtime_identity,
                self.owner.bindings.radar_policy_identity,
                _radar_anchor_identity(fact),
                fact.short_leg_identity,
                fact.target_quantity_btc,
            ): fact
            for fact in facts
            if _radar_anchor_identity(fact) is not None and fact.short_leg_identity is not None
        }
        for emitted in transition.emitted:
            value = self.owner.state_store.get_object(
                emitted.object_kind,
                emitted.object_identity,
            )
            payload = value.get("payload") if value is not None else None
            if emitted.object_kind == "CANDIDATE_ACTIVATION" and isinstance(payload, Mapping):
                slot = payload.get("underwriting_position_slot_key_identity")
                if isinstance(slot, str) and slot in facts_by_slot:
                    self._candidate_origins[emitted.object_identity] = facts_by_slot[slot]
            elif emitted.object_kind == "SHADOW_ENTRY" and value is not None:
                self._remember_anchor(value)
            elif emitted.object_kind == "SELECTED_UNDERWRITING_DECISION" and isinstance(
                payload, Mapping
            ):
                slot = payload.get("underwriting_position_slot_key_identity")
                if isinstance(slot, str) and slot in facts_by_slot:
                    self._decision_control_origins[emitted.object_identity] = facts_by_slot[slot]
            elif (
                emitted.object_kind == "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN"
                and value is not None
            ):
                self._remember_anchor(value)
        result: list[ShadowRpcIntent] = []
        for intent in transition.request_intents:
            role = (
                ComponentLegRole.SHORT
                if "_SHORT_" in intent.purpose
                else (ComponentLegRole.LONG if "_LONG_" in intent.purpose else None)
            )
            context = _RequestContext(
                purpose=intent.purpose,
                owner_identity=intent.owner_identity,
                instrument_name=str(intent.params["instrument_name"]),
                origin_boundary=intent.origin_boundary,
                role=role,
            )
            self._requests[intent.request_id] = context
            result.append(self._shadow_intent(intent))
        self._prune_owner_refs()
        self._prune_semantic_sources()
        return tuple(result)

    def _consume_ordinary_post_close_terminal(
        self,
        *,
        reducer: RadarReducer,
        request_id: int,
        boundary: DownstreamFactBoundary,
        transition: OwnerTransition,
    ) -> tuple[ShadowRpcIntent, ...]:
        context = self._requests.get(request_id)
        intents = list(self._consume_transition(transition, ()))
        terminal_kinds = {
            emitted.object_kind
            for emitted in transition.emitted
            if emitted.object_kind in {"ADMISSION_ATTEMPT_TERMINAL", "POST_CLOSE_ATTEMPT_TERMINAL"}
        }
        if context is None or not terminal_kinds:
            return tuple(intents)
        if context.role is not None:
            self._paired_responses.pop(
                (
                    self._component_request_family(context.purpose),
                    context.owner_identity,
                ),
                None,
            )
        self._requests.pop(request_id, None)
        is_post_close = context.purpose == "POST_CLOSE_QUOTE" or context.purpose.startswith(
            "COMPONENT_POST_CLOSE_"
        )
        if not is_post_close or "POST_CLOSE_ATTEMPT_TERMINAL" not in terminal_kinds:
            return tuple(intents)
        anchor = self._anchors.get(context.owner_identity)
        if anchor is None:
            return tuple(intents)
        self._refresh_sources(reducer, boundary)
        facts = self._project_position(
            reducer=reducer,
            anchor=anchor,
            boundary=boundary,
        )

        def reject_second_attempt() -> int:
            raise RuntimeError("ordinary post-CLOSE terminal cannot schedule another attempt")

        settlement = self.owner.settle_position(
            anchor_identity=anchor.anchor_identity,
            facts=facts,
            allocate_request_id=reject_second_attempt,
        )
        intents.extend(self._consume_transition(settlement, ()))
        return tuple(intents)

    def _shadow_intent(self, intent: RpcRequestIntent) -> ShadowRpcIntent:
        if intent.purpose in {
            "ADMISSION_REFRESH",
            "COMPONENT_ADMISSION_SHORT_REFRESH",
            "COMPONENT_ADMISSION_LONG_REFRESH",
            "COMPONENT_DECISION_CONTROL_SHORT_REFRESH",
            "COMPONENT_DECISION_CONTROL_LONG_REFRESH",
        }:
            purpose = RpcPurpose.ADMISSION_REFRESH
            send_budget = self.owner.policies.underwriting.component_book_snapshot_send_budget_ms
            response_budget = (
                self.owner.policies.underwriting.component_book_snapshot_response_budget_ms
            )
        elif intent.purpose in {
            "POST_CLOSE_QUOTE",
            "COMPONENT_POST_CLOSE_SHORT_REFRESH",
            "COMPONENT_POST_CLOSE_LONG_REFRESH",
        }:
            purpose = RpcPurpose.POST_CLOSE_REFRESH
            send_budget = self.owner.policies.position.component_book_snapshot_send_budget_ms
            response_budget = (
                self.owner.policies.position.component_book_snapshot_response_budget_ms
            )
        else:
            raise ValueError("owner returned an unknown typed request purpose")
        return ShadowRpcIntent(
            request_id=intent.request_id,
            purpose=purpose,
            method=intent.method,
            params=intent.params,
            scope=intent.owner_identity,
            origin_boundary=FactBoundary(
                session_epoch=intent.origin_boundary.session_epoch,
                ingress_seq=intent.origin_boundary.ingress_seq,
                received_monotonic_ms=intent.origin_boundary.received_monotonic_ms,
                causal_seq=intent.origin_boundary.causal_seq,
            ),
            send_budget_ms=send_budget,
            response_budget_ms=response_budget,
        )

    def _remember_anchor(self, value: Mapping[str, object]) -> None:
        identity = str(value["object_identity"])
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise RuntimeError("Shadow Entry payload must be a mapping")
        leg_ids = payload.get("canonical_leg_identities")
        if not isinstance(leg_ids, list) or len(leg_ids) != 2:
            raise RuntimeError("Shadow Entry requires exact canonical leg identities")
        self._anchors[identity] = _Anchor(
            anchor_identity=identity,
            entry_boundary=DownstreamFactBoundary.from_object(value["fact_boundary"]),
            short_leg_identity=str(leg_ids[0]),
            long_leg_identity=str(leg_ids[1]),
            short_instrument_name=str(payload["short_leg_instrument_name"]),
            long_instrument_name=str(payload["long_leg_instrument_name"]),
            target_quantity_btc=_decimal(payload["full_quantity_btc"]),
        )

    def _retire_underwriting_scopes(
        self,
        scope_retirements: Sequence[str],
        episode_retirements: Sequence[str],
        *,
        boundary: DownstreamFactBoundary,
    ) -> tuple[ShadowRpcIntent, ...]:
        if not scope_retirements and not episode_retirements:
            return ()
        intents: list[ShadowRpcIntent] = []
        for scope_identity in scope_retirements:
            self._underwriting_by_scope.pop(scope_identity, None)
            self._workbench_underwriting_metadata_by_scope.pop(scope_identity, None)
            self.owner.retire_underwriting_scope(scope_identity)
        for episode_identity in episode_retirements:
            transition = self.owner.retire_radar_episode(
                episode_identity,
                boundary=boundary,
            )
            intents.extend(self._consume_transition(transition, ()))
            self._frozen_component_by_episode.pop(episode_identity, None)
        self._rebuild_underwriting_metadata()
        self._prune_owner_refs()
        self._prune_semantic_sources()
        return tuple(intents)

    def _rebuild_underwriting_metadata(self) -> None:
        self._workbench_underwriting_metadata = tuple(
            self._workbench_underwriting_metadata_by_scope[key]
            for key in sorted(self._workbench_underwriting_metadata_by_scope)
        )

    def _prune_owner_refs(self) -> None:
        active_candidates = self.owner.active_candidate_identities
        for candidate_identity in tuple(self._candidate_origins):
            if candidate_identity not in active_candidates:
                self._candidate_origins.pop(candidate_identity, None)
        active_controls = self.owner.active_decision_control_identities
        for selection_identity in tuple(self._decision_control_origins):
            if selection_identity not in active_controls:
                self._decision_control_origins.pop(selection_identity, None)
        active_trades = self.owner.active_trade_identities
        for anchor_identity in tuple(self._anchors):
            if anchor_identity not in active_trades:
                self._anchors.pop(anchor_identity, None)
        for request_id, context in tuple(self._requests.items()):
            owners = (
                active_candidates
                if context.purpose == "ADMISSION_REFRESH"
                or context.purpose.startswith("COMPONENT_ADMISSION_")
                else active_controls
                if context.purpose.startswith("COMPONENT_DECISION_CONTROL_")
                else active_trades
            )
            if context.owner_identity not in owners:
                self._requests.pop(request_id, None)
        for key in tuple(self._paired_responses):
            family, owner_identity = key
            owners = (
                active_candidates
                if family == "COMPONENT_ADMISSION"
                else active_controls
                if family == "COMPONENT_DECISION_CONTROL"
                else active_trades
            )
            if owner_identity not in owners:
                self._paired_responses.pop(key, None)

    def _prune_semantic_sources(self) -> None:
        retained_option_ids = {source.semantic_identity for source in self._option_sources.values()}
        retained_combo_ids = {source.semantic_identity for source in self._combo_sources.values()}
        for anchor in self._anchors.values():
            retained_option_ids.update({anchor.short_leg_identity, anchor.long_leg_identity})
        self._options_by_identity = {
            identity: source
            for identity, source in self._options_by_identity.items()
            if identity in retained_option_ids
        }
        self._combos_by_identity = {
            identity: source
            for identity, source in self._combos_by_identity.items()
            if identity in retained_combo_ids
        }

    def _anchor_for_owner_identity(self, owner_identity: str) -> _Anchor | None:
        return self._anchors.get(owner_identity)

    def _subscription_witness(
        self,
        reducer: RadarReducer,
        instrument_name: str,
        combo_identity: str | None,
    ) -> SubscriptionAdmissionRefreshWitness | None:
        if combo_identity is None:
            return None
        receipt = reducer.accepted_book_receipts.get(instrument_name)
        book = reducer.combo_books.get(instrument_name)
        if (
            receipt is None
            or book is None
            or book.state is not BookState.USABLE
            or receipt.session_epoch != self._session_epoch
        ):
            return None
        boundary = self._boundary(reducer, receipt.boundary)
        source_identity = canonical_identity(
            "SubscriptionAdmissionRefreshSourceIdentity",
            boundary.runtime_identity,
            receipt.session_epoch,
            receipt.subscription_generation,
            combo_identity,
            receipt.snapshot_kind,
            receipt.prev_change_id,
            receipt.change_id,
            receipt.source_timestamp_ms,
            boundary.as_object(),
        )
        return SubscriptionAdmissionRefreshWitness(
            source_identity=source_identity,
            boundary=boundary,
            canonical_combo_identity=combo_identity,
            instrument_name=instrument_name,
            change_id=receipt.change_id,
            source_timestamp_ms=receipt.source_timestamp_ms,
            snapshot_kind=receipt.snapshot_kind,
            session_epoch=receipt.session_epoch,
            subscription_generation=receipt.subscription_generation,
            prev_change_id=receipt.prev_change_id,
        )

    def _option_book_source(
        self,
        reducer: RadarReducer,
        instrument_name: str,
        option_identity: str | None,
    ) -> SourceFact | None:
        if option_identity is None:
            return None
        receipt = reducer.accepted_book_receipts.get(instrument_name)
        book = reducer.option_books.get(instrument_name)
        if (
            receipt is None
            or book is None
            or book.state is not BookState.USABLE
            or receipt.session_epoch != self._session_epoch
        ):
            return None
        boundary = self._boundary(reducer, receipt.boundary)
        return SourceFact(
            canonical_identity(
                "OptionBookSourceIdentity",
                option_identity,
                receipt.session_epoch,
                receipt.subscription_generation,
                receipt.snapshot_kind,
                receipt.prev_change_id,
                receipt.change_id,
                receipt.source_timestamp_ms,
                boundary.as_object(),
            ),
            boundary,
        )

    def _trusted_interval(
        self,
        reducer: RadarReducer,
        boundary: DownstreamFactBoundary,
        *,
        budget_ms: int,
    ) -> TimeInterval | None:
        clock = reducer.clock
        if clock is None:
            return None
        age = boundary.received_monotonic_ms - clock.last_refresh_monotonic_ms
        if age < 0 or age > budget_ms:
            return None
        try:
            return clock.interval_at(boundary.received_monotonic_ms)
        except ContinuityGap:
            return None

    @staticmethod
    def _platform_currentness(
        reducer: RadarReducer,
        boundary: DownstreamFactBoundary,
        *,
        budget_ms: int,
    ) -> bool | None:
        if not reducer.platform.usable:
            return False
        receipt = reducer.accepted_platform_continuity_boundary
        if receipt is None or receipt.session_epoch != boundary.session_epoch:
            return None
        age_ms = boundary.received_monotonic_ms - receipt.received_monotonic_ms
        return True if 0 <= age_ms <= budget_ms else None

    def _current_index(
        self,
        reducer: RadarReducer,
        trusted: TimeInterval | None,
        *,
        budget_ms: int,
    ) -> tuple[Decimal | None, SourceFact | None]:
        receipt = reducer.accepted_index_receipt
        if receipt is None or trusted is None:
            return None, None
        upper = trusted.upper_ms
        if not (receipt.source_timestamp_ms <= upper <= receipt.source_timestamp_ms + budget_ms):
            return None, None
        boundary = self._boundary(reducer, receipt.boundary)
        return (
            receipt.price_usdc_per_btc,
            SourceFact(
                canonical_identity(
                    "IndexSourceIdentity",
                    reducer.product.price_index,
                    receipt.source_timestamp_ms,
                    receipt.price_usdc_per_btc,
                    boundary.as_object(),
                ),
                boundary,
            ),
        )

    def _current_ticker(
        self,
        instrument_name: str,
        trusted: TimeInterval | None,
        *,
        budget_ms: int,
    ) -> tuple[TickerState | None, SourceFact | None]:
        source = self._ticker_sources.get(instrument_name)
        if source is None or trusted is None:
            return None, None
        timestamp = source.value.source_timestamp_ms
        upper = trusted.upper_ms
        if not timestamp <= upper <= timestamp + budget_ms:
            return None, None
        return source.value, source.source

    def _request_side_and_quantity(
        self,
        context: _RequestContext,
    ) -> tuple[str, Decimal]:
        if context.purpose == "ADMISSION_REFRESH":
            facts = self._candidate_origins.get(context.owner_identity)
            if facts is None or facts.entry_direction is None:
                return "ask", self.owner.policies.underwriting.target_base_quantity_btc
            return (
                "ask" if facts.entry_direction == "BUY" else "bid",
                facts.target_quantity_btc,
            )
        anchor = self._anchor_for_owner_identity(context.owner_identity)
        if anchor is None:
            return "ask", self.owner.policies.position.target_base_quantity_btc
        return "ask", anchor.target_quantity_btc

    def _component_request_side_and_quantity(
        self,
        context: _RequestContext,
    ) -> tuple[str, Decimal]:
        role = context.role
        if role is None:
            raise ValueError("component request context lacks a leg role")
        if context.purpose.startswith("COMPONENT_ADMISSION_"):
            origin = self._candidate_origins.get(context.owner_identity)
            target = (
                origin.target_quantity_btc
                if origin is not None
                else self.owner.policies.underwriting.target_base_quantity_btc
            )
            return (
                "bid" if role is ComponentLegRole.SHORT else "ask",
                target,
            )
        if context.purpose.startswith("COMPONENT_DECISION_CONTROL_"):
            origin = self._decision_control_origins.get(context.owner_identity)
            target = (
                origin.target_quantity_btc
                if origin is not None
                else self.owner.policies.underwriting.target_base_quantity_btc
            )
            return (
                "bid" if role is ComponentLegRole.SHORT else "ask",
                target,
            )
        anchor = self._anchor_for_owner_identity(context.owner_identity)
        target = (
            anchor.target_quantity_btc
            if anchor is not None
            else self.owner.policies.position.target_base_quantity_btc
        )
        return (
            "ask" if role is ComponentLegRole.SHORT else "bid",
            target,
        )

    def _require_bindings(self, reducer: RadarReducer) -> None:
        if (
            reducer.code_identity != self.owner.bindings.code_identity
            or reducer.runtime_identity != self.owner.bindings.runtime_identity
            or reducer.policy.identity != self.owner.bindings.radar_policy_identity
            or reducer.product.identity != reducer.policy.product_spec_identity
        ):
            raise ValueError("Radar reducer and fixed-contract owner identities differ")

    def _boundary(
        self,
        reducer: RadarReducer,
        boundary: FactBoundary,
    ) -> DownstreamFactBoundary:
        return DownstreamFactBoundary(
            code_identity=reducer.code_identity,
            runtime_identity=reducer.runtime_identity,
            session_epoch=boundary.session_epoch,
            ingress_seq=boundary.ingress_seq,
            received_monotonic_ms=boundary.received_monotonic_ms,
            causal_seq=boundary.causal_seq,
        )

    def _require_reducer(self) -> RadarReducer:
        if self._last_reducer is None:
            raise RuntimeError("Shadow callback arrived before a settled Radar reducer")
        return self._last_reducer


def _option_identity(instrument: OptionInstrument) -> str:
    amount = instrument.amount
    return canonical_identity(
        "CanonicalOptionInstrumentIdentity",
        instrument.product.identity,
        instrument.instrument_name,
        instrument.expiration_timestamp_ms,
        instrument.strike,
        instrument.option_type.value,
        (
            None
            if amount is None
            else {
                "contract_size": amount.contract_size,
                "min_trade_amount": amount.min_trade_amount,
                "qty_tick_size": amount.qty_tick_size,
            }
        ),
    )


def _combo_identity(instrument: ComboInstrument) -> str:
    return canonical_identity(
        "CanonicalComboInstrumentIdentity",
        instrument.product.identity,
        instrument.instrument_name,
        [
            {
                "instrument_name": leg.instrument_name,
                "amount": leg.amount,
            }
            for leg in instrument.legs
        ],
    )


def _amount_aligned(
    instrument: ComboInstrument | None,
    target: Decimal,
) -> bool | None:
    if instrument is None or instrument.amount is None:
        return None
    return check_target_amount(target, instrument.amount).state is AmountState.ELIGIBLE


def _both_amounts_aligned(
    short: OptionInstrument | None,
    long: OptionInstrument | None,
    target: Decimal,
) -> bool | None:
    if short is None or long is None or short.amount is None or long.amount is None:
        return None
    return (
        check_target_amount(target, short.amount).state is AmountState.ELIGIBLE
        and check_target_amount(target, long.amount).state is AmountState.ELIGIBLE
    )


def _option_availability(
    short: _OptionSource | None,
    long: _OptionSource | None,
    target: Decimal,
) -> CloseOptionAvailability:
    if short is None or long is None:
        return CloseOptionAvailability.UNKNOWN
    for member in (short.instrument, long.instrument):
        if member.lifecycle_state.value != "open" or not member.is_active:
            return CloseOptionAvailability.UNEXECUTABLE
    if short.instrument.amount is None or long.instrument.amount is None:
        return CloseOptionAvailability.UNKNOWN
    for member in (short.instrument, long.instrument):
        assert member.amount is not None
        if check_target_amount(target, member.amount).state is AmountState.INELIGIBLE:
            return CloseOptionAvailability.UNEXECUTABLE
    return CloseOptionAvailability.TRADEABLE


def _atomic_availability(
    reducer: RadarReducer,
    combo: _ComboSource | None,
    witness: SubscriptionAdmissionRefreshWitness | None,
    target: Decimal,
) -> CloseAtomicAvailability:
    if combo is None:
        return (
            CloseAtomicAvailability.KNOWN_UNAVAILABLE
            if reducer.combo_catalog.complete
            else CloseAtomicAvailability.UNKNOWN
        )
    if combo.instrument.state in {
        "inactive",
        "settlement",
        "delivered",
        "archivized",
        "locked",
        "halted",
    }:
        return CloseAtomicAvailability.KNOWN_UNAVAILABLE
    if combo.instrument.state != "active":
        return CloseAtomicAvailability.UNKNOWN
    if combo.instrument.amount is None:
        return CloseAtomicAvailability.UNKNOWN
    if check_target_amount(target, combo.instrument.amount).state is AmountState.INELIGIBLE:
        return CloseAtomicAvailability.KNOWN_UNAVAILABLE
    if witness is None:
        return CloseAtomicAvailability.UNKNOWN
    return CloseAtomicAvailability.ACTIVE


def _component_reference(
    reducer: RadarReducer,
    short: _OptionSource | None,
    long: _OptionSource | None,
    target: Decimal,
) -> PredicateTruth:
    if short is None or long is None:
        return PredicateTruth.UNKNOWN
    short_book = reducer.option_books.get(short.instrument.instrument_name)
    long_book = reducer.option_books.get(long.instrument.instrument_name)
    if short_book is None or long_book is None:
        return PredicateTruth.UNKNOWN
    if short_book.state is not BookState.USABLE or long_book.state is not BookState.USABLE:
        return PredicateTruth.UNKNOWN
    short_walk = walk_target_depth(short_book.levels("ask"), target)
    long_walk = walk_target_depth(long_book.levels("bid"), target)
    return (
        PredicateTruth.TRUE
        if short_walk is not None and long_walk is not None
        else PredicateTruth.FALSE
    )


def _required_sources_continuous(
    *,
    platform_current: bool | None,
    trusted: TimeInterval | None,
    index: Decimal | None,
    ticker: TickerState | None,
    short: _OptionSource | None,
    long: _OptionSource | None,
    combo: _ComboSource | None,
    witness: SubscriptionAdmissionRefreshWitness | None,
    atomic_availability: CloseAtomicAvailability,
    previously_accepted_combo_quote: bool,
    previously_accepted_index: bool,
    previously_accepted_ticker: bool,
    natural_terminal_boundary_reached: bool = False,
) -> bool | None:
    if platform_current is False:
        return False
    if index is None and previously_accepted_index:
        return False
    if ticker is None and previously_accepted_ticker:
        return False
    if (
        platform_current is None
        or trusted is None
        or index is None
        or ticker is None
        or short is None
        or long is None
    ):
        if not natural_terminal_boundary_reached:
            return None
    if combo is not None and combo.instrument.state in {"locked", "halted"}:
        return False
    if atomic_availability is CloseAtomicAvailability.KNOWN_UNAVAILABLE:
        return True
    if (
        atomic_availability is CloseAtomicAvailability.ACTIVE
        and combo is not None
        and witness is not None
    ):
        return True
    if previously_accepted_combo_quote and combo is not None:
        return False
    if natural_terminal_boundary_reached:
        if platform_current is None or short is None or long is None:
            return None
        return True
    return None


def _required_component_sources_continuous(
    *,
    platform_current: bool | None,
    trusted: TimeInterval | None,
    index: Decimal | None,
    ticker: TickerState | None,
    short: _OptionSource | None,
    long: _OptionSource | None,
    natural_terminal_boundary_reached: bool = False,
) -> bool | None:
    if platform_current is False or index is None or ticker is None:
        return False
    if platform_current is None or trusted is None or short is None or long is None:
        if not natural_terminal_boundary_reached:
            return None
    if natural_terminal_boundary_reached:
        if platform_current is None or short is None or long is None:
            return None
    return True


def _first_trusted_time_crossing(
    *,
    clock: TrustedClock,
    market_time_ms: int,
    bound: str,
    clock_currentness_budget_ms: int,
    after_monotonic_ms: int,
) -> int | None:
    if bound not in {"LOWER", "UPPER"}:
        raise ValueError("trusted-time crossing requires LOWER or UPPER")
    if after_monotonic_ms < clock.base_monotonic_ms:
        return None
    try:
        current = clock.interval_at(after_monotonic_ms)
    except ContinuityGap:
        return None
    current_value = current.lower_ms if bound == "LOWER" else current.upper_ms
    if current_value >= market_time_ms:
        return None
    latest_monotonic_ms = min(
        clock.last_refresh_monotonic_ms + clock_currentness_budget_ms,
        clock.last_refresh_monotonic_ms + clock.stale_deadline_ms - 1,
    )
    first_monotonic_ms = after_monotonic_ms + 1
    if first_monotonic_ms > latest_monotonic_ms:
        return None
    latest = clock.interval_at(latest_monotonic_ms)
    latest_value = latest.lower_ms if bound == "LOWER" else latest.upper_ms
    if latest_value < market_time_ms:
        return None
    low = first_monotonic_ms
    high = latest_monotonic_ms
    while low < high:
        middle = (low + high) // 2
        interval = clock.interval_at(middle)
        value = interval.lower_ms if bound == "LOWER" else interval.upper_ms
        if value >= market_time_ms:
            high = middle
        else:
            low = middle + 1
    return low


def _first_clock_currentness_expiry(
    *,
    clock: TrustedClock,
    clock_currentness_budget_ms: int,
    after_monotonic_ms: int,
) -> int | None:
    if after_monotonic_ms < clock.base_monotonic_ms:
        return None
    age_ms = after_monotonic_ms - clock.last_refresh_monotonic_ms
    if age_ms < 0 or age_ms > clock_currentness_budget_ms:
        return None
    try:
        clock.interval_at(after_monotonic_ms)
    except ContinuityGap:
        return None
    crossing = min(
        clock.last_refresh_monotonic_ms + clock_currentness_budget_ms + 1,
        clock.last_refresh_monotonic_ms + clock.stale_deadline_ms,
    )
    return crossing if crossing > after_monotonic_ms else None


def _first_platform_currentness_expiry(
    *,
    session_epoch: int | None,
    platform_usable: bool,
    receipt: FactBoundary | None,
    platform_currentness_budget_ms: int,
    after_monotonic_ms: int,
) -> int | None:
    if not platform_usable or receipt is None or receipt.session_epoch != session_epoch:
        return None
    age_ms = after_monotonic_ms - receipt.received_monotonic_ms
    if age_ms < 0 or age_ms > platform_currentness_budget_ms:
        return None
    crossing = receipt.received_monotonic_ms + platform_currentness_budget_ms + 1
    return crossing if crossing > after_monotonic_ms else None


def _first_source_currentness_expiry(
    *,
    clock: TrustedClock,
    source_timestamp_ms: int,
    source_currentness_budget_ms: int,
    clock_currentness_budget_ms: int,
    after_monotonic_ms: int,
) -> int | None:
    try:
        current = clock.interval_at(after_monotonic_ms)
    except (ContinuityGap, ValueError):
        return None
    source_deadline_ms = source_timestamp_ms + source_currentness_budget_ms
    if not source_timestamp_ms <= current.upper_ms <= source_deadline_ms:
        return None
    return _first_trusted_time_crossing(
        clock=clock,
        market_time_ms=source_deadline_ms + 1,
        bound="UPPER",
        clock_currentness_budget_ms=clock_currentness_budget_ms,
        after_monotonic_ms=after_monotonic_ms,
    )


def _parse_rest_book(
    value: object,
    *,
    expected_name: str,
) -> _RestBook | None:
    if not isinstance(value, Mapping):
        return None
    instrument_name = value.get("instrument_name")
    change_id = value.get("change_id")
    timestamp = value.get("timestamp")
    if (
        not isinstance(instrument_name, str)
        or instrument_name != expected_name
        or isinstance(change_id, bool)
        or not isinstance(change_id, int)
        or change_id < 0
        or isinstance(timestamp, bool)
        or not isinstance(timestamp, int)
        or timestamp < 0
    ):
        return None
    bids = _rest_levels(value.get("bids"), reverse=True)
    asks = _rest_levels(value.get("asks"), reverse=False)
    return _RestBook(
        instrument_name=instrument_name,
        state=(value.get("state") if isinstance(value.get("state"), str) else None),
        change_id=change_id,
        source_timestamp_ms=timestamp,
        bids=bids or (),
        asks=asks or (),
        well_formed=bids is not None and asks is not None,
    )


def _rest_levels(value: object, *, reverse: bool) -> tuple[PriceLevel, ...] | None:
    if not isinstance(value, list):
        return None
    result: list[PriceLevel] = []
    for raw in value:
        if not isinstance(raw, list) or len(raw) != 2:
            return None
        try:
            price = _decimal(raw[0])
            amount = _decimal(raw[1])
        except ValueError:
            return None
        if not price.is_finite() or not amount.is_finite() or price <= 0 or amount <= 0:
            return None
        result.append(PriceLevel(price, amount))
    result.sort(key=lambda level: level.price, reverse=reverse)
    return tuple(result)


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean is not a Decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid Decimal") from exc
    if not parsed.is_finite():
        raise ValueError("Decimal must be finite")
    return parsed


def _radar_anchor_identity(facts: UnderwritingFacts) -> str | None:
    return facts.active_episode_identity or facts.radar_research_review_identity
