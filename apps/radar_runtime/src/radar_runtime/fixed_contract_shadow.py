from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

from market_monitor import BookState, ContinuityGap, PriceLevel, TimeInterval, TrustedClock
from options_domain import (
    AmountState,
    ComboInstrument,
    OptionInstrument,
    check_target_amount,
)
from options_domain.quotes import walk_target_depth
from short_vol_radar.atomic import (
    AtomicQuote,
    PublicAtomicQuoteState,
)
from short_vol_radar.radar import TickerState
from short_vol_underwriting import (
    CloseAtomicAvailability,
    CloseBookAvailability,
    CloseOptionAvailability,
    CloseQuoteFacts,
    FixedContractShadowOwner,
    PositionFacts,
    PostCloseAttemptStatus,
    PredicateTruth,
    RpcAdmissionRefreshWitness,
    SourceFact,
    SubscriptionAdmissionRefreshWitness,
    TerminalSource,
    UnderwritingFacts,
    ValidatedManifest,
    canonical_identity,
)
from short_vol_underwriting import (
    FactBoundary as DownstreamFactBoundary,
)
from short_vol_underwriting.admission import RpcRequestIntent
from short_vol_underwriting.constants import ADMISSION_CUTOFF_LEAD_MS
from short_vol_underwriting.owner import OwnerTransition

from radar_runtime.runtime import (
    AtomicScopeSnapshot,
    CausalCommit,
    FactBoundary,
    RadarReducer,
    RpcPurpose,
    RpcState,
    ShadowRpcIntent,
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
    canonical_combo_identity: str
    short_leg_identity: str
    long_leg_identity: str
    entry_direction: str
    target_quantity_btc: Decimal


@dataclass(frozen=True)
class _RequestContext:
    purpose: str
    owner_identity: str
    instrument_name: str
    origin_boundary: DownstreamFactBoundary


@dataclass(frozen=True)
class _RestBook:
    instrument_name: str
    state: str | None
    change_id: int
    source_timestamp_ms: int
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    well_formed: bool


class FixedContractShadowRuntimeAdapter:
    """Pure synchronous projection from one settled Radar reducer into one owner."""

    def __init__(
        self,
        *,
        owner: FixedContractShadowOwner,
        manifest: ValidatedManifest | None = None,
    ) -> None:
        self.owner = owner
        self.manifest = manifest
        self._session_epoch: int | None = None
        self._option_sources: dict[str, _OptionSource] = {}
        self._options_by_identity: dict[str, _OptionSource] = {}
        self._combo_sources: dict[str, _ComboSource] = {}
        self._combos_by_identity: dict[str, _ComboSource] = {}
        self._ticker_sources: dict[str, _TickerSource] = {}
        self._underwriting_by_scope: dict[str, UnderwritingFacts] = {}
        self._candidate_origins: dict[str, UnderwritingFacts] = {}
        self._anchors: dict[str, _Anchor] = {}
        self._anchors_by_observation: dict[str, _Anchor] = {}
        self._requests: dict[int, _RequestContext] = {}
        self._last_reducer: RadarReducer | None = None
        self._enrollment_opened = False
        self._enrollment_closed = False
        self._terminal_disposition: str | None = None
        self._terminal_source: Mapping[str, object] | None = None
        self._configured_terminal_control: (
            tuple[
                str,
                Mapping[str, object],
            ]
            | None
        ) = None

    @property
    def required_combo_instrument_names(self) -> tuple[str, ...]:
        return self.owner.required_combo_instrument_names

    @property
    def required_option_instrument_names(self) -> tuple[str, ...]:
        return self.owner.required_option_instrument_names

    def workbench_option_metadata(self) -> tuple[Mapping[str, object], ...]:
        """Copy settled option identity metadata for the in-process read-only projection."""
        return tuple(
            {
                "semantic_identity": identity,
                "instrument_name": source.instrument.instrument_name,
                "expiration_timestamp_ms": source.instrument.expiration_timestamp_ms,
                "option_type": source.instrument.option_type.value,
                "strike_usdc_per_btc": str(source.instrument.strike),
            }
            for identity, source in sorted(self._options_by_identity.items())
        )

    def workbench_underwriting_metadata(self) -> tuple[Mapping[str, object], ...]:
        """Copy display-only structure facts from the settled Underwriting projection."""
        return tuple(
            {
                "radar_scope_identity": scope_identity,
                "short_leg_instrument_name": facts.short_leg_instrument_name,
                "long_leg_instrument_name": facts.long_leg_instrument_name,
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
            for scope_identity, facts in sorted(self._underwriting_by_scope.items())
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
            if facts.active_episode_identity is None or facts.expiry_ms is None:
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
            if facts.active_episode_identity is not None
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
        pending_position_names = self.owner.required_option_instrument_names
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

        projected = self._project_underwriting(reducer, commit, boundary)
        transition = self.owner.settle_underwriting(
            projected,
            allocate_request_id=reducer.allocate_shadow_request_id,
        )
        intents = list(self._consume_transition(transition, projected))

        self._discover_anchors()
        for anchor in tuple(self._anchors.values()):
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

    def realize_runtime_start(
        self,
        *,
        reducer: RadarReducer,
        boundary: FactBoundary,
    ) -> None:
        """Consume one supervisor-owned global causal boundary for runtime start."""
        downstream = self._boundary(reducer, boundary)
        self._require_bindings(reducer)
        self._last_reducer = reducer
        if self.manifest is None:
            raise RuntimeError("runtime-start control requires the validated manifest")
        if self._enrollment_opened:
            raise ValueError("runtime-start control is immutable")
        if downstream.received_monotonic_ms < _manifest_monotonic(
            self.manifest,
            "runtime_start_trigger",
        ):
            raise ValueError("runtime-start control precedes its prebound trigger")
        self.owner.open_enrollment(downstream)
        self._enrollment_opened = True

    def realize_enrollment_cutoff(
        self,
        *,
        reducer: RadarReducer,
        boundary: FactBoundary,
    ) -> None:
        """Consume a distinct supervisor-owned global causal boundary for cutoff."""
        downstream = self._boundary(reducer, boundary)
        self._require_bindings(reducer)
        self._last_reducer = reducer
        if self.manifest is None:
            raise RuntimeError("enrollment-cutoff control requires the validated manifest")
        if not self._enrollment_opened:
            raise ValueError("enrollment cutoff requires an earlier runtime-start control")
        if self._enrollment_closed:
            raise ValueError("enrollment-cutoff control is immutable")
        if downstream.received_monotonic_ms < _manifest_monotonic(
            self.manifest,
            "enrollment_cutoff_trigger",
        ):
            raise ValueError("enrollment cutoff precedes its prebound trigger")
        self.owner.close_enrollment(downstream)
        self._enrollment_closed = True

    def configure_terminal_control(
        self,
        *,
        terminal_disposition: str,
        terminal_source: Mapping[str, object],
    ) -> None:
        """Bind the typed supervisor control before the terminal reducer boundary."""
        if terminal_disposition not in {
            "PLANNED_CLEAN_STOP",
            "AUTHORIZED_EMERGENCY_STOP",
            "PROCESS_FAILURE",
        }:
            raise ValueError("terminal disposition is invalid")
        if self._terminal_disposition is not None:
            raise ValueError("terminal supervisor control is immutable after termination")
        configured = self._configured_terminal_control
        if configured is not None:
            prior_disposition, _prior_source = configured
            if terminal_disposition != "PROCESS_FAILURE" or prior_disposition == "PROCESS_FAILURE":
                raise ValueError("only fatal failure may supersede a pending stop control")
        self._configured_terminal_control = (
            terminal_disposition,
            dict(terminal_source),
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
            self._discover_anchors()
            return result_intents

        anchor = self._anchor_for_owner_identity(context.owner_identity)
        if anchor is None:
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
        return self._consume_transition(transition, ())

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
        tracker = reducer.trackers.get(short_name) if short_name is not None else None
        active_episode = (
            tracker.episode_id
            if tracker is not None and tracker.episode_id == origin.active_episode_identity
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
            (active_episode is None, "RADAR_EPISODE_NOT_ACTIVE"),
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
        terminal_kind = TerminalSource.STOP if source == "STOP" else TerminalSource.FAILURE
        terminal_disposition, terminal_source, terminal_identity = self._terminal_control(
            source=source,
            boundary=downstream,
        )
        transition = self.owner.terminate(
            boundary=downstream,
            terminal_source_identity=terminal_identity,
            terminal_source=terminal_kind,
        )
        self._consume_transition(transition, ())
        self._terminal_disposition = terminal_disposition
        self._terminal_source = terminal_source

    def finalize_terminal(self) -> None:
        if (
            self.manifest is None
            or self._terminal_disposition is None
            or self._terminal_source is None
        ):
            raise RuntimeError("Shadow terminal summary requires its validated manifest/control")
        self.owner.finalize_terminal(
            manifest=self.manifest,
            terminal_disposition=self._terminal_disposition,
            terminal_source=self._terminal_source,
        )

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

    def _project_underwriting(
        self,
        reducer: RadarReducer,
        commit: CausalCommit,
        boundary: DownstreamFactBoundary,
    ) -> tuple[UnderwritingFacts, ...]:
        current: dict[str, UnderwritingFacts] = {}
        snapshots: list[AtomicScopeSnapshot] = []
        for tracker in reducer.trackers.values():
            snapshot = reducer._freeze_atomic_scope_snapshot(tracker, commit=commit)
            if snapshot is not None:
                self._require_episode_snapshot_binding(reducer, snapshot)
                snapshots.append(snapshot)
        by_episode = {snapshot.episode_identity: snapshot for snapshot in snapshots}
        for snapshot in snapshots:
            if snapshot.result.quotes:
                for quote in snapshot.result.quotes:
                    facts = self._underwriting_quote(reducer, snapshot, quote, boundary)
                    current[facts.radar_scope_identity] = facts
            else:
                matching_prior = tuple(
                    facts
                    for facts in self._underwriting_by_scope.values()
                    if facts.active_episode_identity == snapshot.episode_identity
                )
                if matching_prior:
                    for prior in matching_prior:
                        facts = self._replace_unknown_underwriting(
                            reducer,
                            prior,
                            snapshot,
                            boundary,
                        )
                        current[facts.radar_scope_identity] = facts
                else:
                    facts = self._underwriting_unknown(reducer, snapshot, boundary)
                    current[facts.radar_scope_identity] = facts
        for scope, prior in self._underwriting_by_scope.items():
            if scope in current:
                continue
            if prior.active_episode_identity in by_episode:
                continue
            trusted = self._trusted_interval(
                reducer,
                boundary,
                budget_ms=self.owner.policies.underwriting.clock_currentness_budget_ms,
            )
            current[scope] = replace(
                prior,
                boundary=boundary,
                active_episode_identity=None,
                atomic_state=PublicAtomicQuoteState.NOT_EVALUATED.value,
                trusted_time_lower_ms=(trusted.lower_ms if trusted is not None else None),
                trusted_time_upper_ms=(trusted.upper_ms if trusted is not None else None),
                quote_refresh_witness=None,
                unknown_reasons=("RADAR_EPISODE_NOT_ACTIVE",),
            )
        self._underwriting_by_scope.update(current)
        return tuple(current[key] for key in sorted(current))

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
        return UnderwritingFacts(
            boundary=boundary,
            radar_scope_identity=scope_identity,
            active_episode_identity=snapshot.episode_identity,
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
            active_episode_identity=snapshot.episode_identity,
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
            unknown_reasons=tuple(snapshot.result.unknown_reasons)
            or ("ATOMIC_SCOPE_NOT_EVALUABLE",),
        )

    @staticmethod
    def _require_episode_snapshot_binding(
        reducer: RadarReducer,
        snapshot: AtomicScopeSnapshot,
    ) -> None:
        expected = (
            f"{reducer.runtime_identity}:{reducer.policy.identity}:"
            f"{snapshot.short_leg.instrument_name}:{snapshot.anomaly_activation_seq}"
        )
        if snapshot.episode_identity != expected:
            raise ValueError("Radar episode identity is not bound to its atomic scope snapshot")

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
    ) -> PositionFacts:
        short = self._options_by_identity.get(anchor.short_leg_identity)
        long = self._options_by_identity.get(anchor.long_leg_identity)
        combo = self._combos_by_identity.get(anchor.canonical_combo_identity)
        short_live = (
            self._option_sources.get(short.instrument.instrument_name)
            if short is not None
            else None
        )
        long_live = (
            self._option_sources.get(long.instrument.instrument_name) if long is not None else None
        )
        combo_live = (
            self._combo_sources.get(combo.instrument.instrument_name) if combo is not None else None
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
            (
                combo_live.semantic_identity == anchor.canonical_combo_identity
                if combo_live is not None
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
        close_direction = "BUY" if anchor.entry_direction == "SELL" else "SELL"
        retained_witness = (
            self._subscription_witness(
                reducer,
                combo.instrument.instrument_name,
                anchor.canonical_combo_identity,
            )
            if combo is not None
            else None
        )
        fresh_witness: SubscriptionAdmissionRefreshWitness | RpcAdmissionRefreshWitness | None = (
            retained_witness
            if retained_witness is not None and retained_witness.boundary == boundary
            else None
        )
        quote_source = (
            SourceFact(retained_witness.source_identity, retained_witness.boundary)
            if retained_witness is not None
            else None
        )
        if rpc_witness is not None:
            fresh_witness = rpc_witness
            quote_source = SourceFact(rpc_witness.source_identity, rpc_witness.boundary)
        option_availability = _option_availability(
            short_live,
            long_live,
            anchor.target_quantity_btc,
        )
        atomic_availability = _atomic_availability(
            reducer,
            combo_live,
            retained_witness,
            anchor.target_quantity_btc,
        )
        levels: tuple[tuple[Decimal, Decimal], ...] = ()
        book_availability = CloseBookAvailability.UNKNOWN
        if rpc_witness is not None:
            if rpc_quote_known:
                atomic_availability = CloseAtomicAvailability.ACTIVE
                levels = rpc_levels
                book_availability = CloseBookAvailability.FULL_QUANTITY
            else:
                atomic_availability = CloseAtomicAvailability.UNKNOWN
        elif (
            atomic_availability is CloseAtomicAvailability.ACTIVE
            and combo is not None
            and (book := reducer.combo_books.get(combo.instrument.instrument_name)) is not None
            and book.state is BookState.USABLE
        ):
            walk = walk_target_depth(
                book.levels("ask" if close_direction == "BUY" else "bid"),
                anchor.target_quantity_btc,
            )
            if walk is None:
                book_availability = CloseBookAvailability.INSUFFICIENT
            else:
                levels = tuple((level.price, level.amount) for level in walk.consumed)
                book_availability = CloseBookAvailability.FULL_QUANTITY
        component_reference = _component_reference(
            reducer,
            short_live,
            long_live,
            anchor.target_quantity_btc,
        )
        platform_current = self._platform_currentness(
            reducer,
            boundary,
            budget_ms=self.owner.policies.position.platform_currentness_budget_ms,
        )
        required_sources = _required_sources_continuous(
            platform_current=platform_current,
            trusted=trusted,
            index=index,
            ticker=ticker,
            short=short_live,
            long=long_live,
            combo=combo_live,
            witness=retained_witness,
            atomic_availability=atomic_availability,
            previously_accepted_combo_quote=True,
            previously_accepted_index=True,
            previously_accepted_ticker=True,
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
                consumed_levels=levels,
            ),
            close_direction=close_direction,
            quote_source=quote_source,
            quote_refresh_witness=fresh_witness,
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
            current_combo_subscription_witness=retained_witness,
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
            self._requests.pop(retirement.request_id, None)
        facts_by_slot = {
            canonical_identity(
                "UnderwritingPositionSlotKeyIdentity",
                self.owner.bindings.runtime_identity,
                self.owner.bindings.radar_policy_identity,
                fact.active_episode_identity,
                fact.short_leg_identity,
                fact.target_quantity_btc,
            ): fact
            for fact in facts
            if fact.active_episode_identity is not None and fact.short_leg_identity is not None
        }
        candidate_payloads = {
            str(value["object_identity"]): value["payload"]
            for value in self.owner.writer.objects
            if value["object_kind"] == "CANDIDATE_ACTIVATION"
        }
        for emitted in transition.emitted:
            if emitted.object_kind != "CANDIDATE_ACTIVATION":
                continue
            payload = candidate_payloads.get(emitted.object_identity)
            if isinstance(payload, Mapping):
                slot = payload.get("underwriting_position_slot_key_identity")
                if isinstance(slot, str) and slot in facts_by_slot:
                    self._candidate_origins[emitted.object_identity] = facts_by_slot[slot]
        result: list[ShadowRpcIntent] = []
        for intent in transition.request_intents:
            context = _RequestContext(
                purpose=intent.purpose,
                owner_identity=intent.owner_identity,
                instrument_name=str(intent.params["instrument_name"]),
                origin_boundary=intent.origin_boundary,
            )
            self._requests[intent.request_id] = context
            result.append(self._shadow_intent(intent))
        return tuple(result)

    def _consume_ordinary_post_close_terminal(
        self,
        *,
        reducer: RadarReducer,
        request_id: int,
        boundary: DownstreamFactBoundary,
        transition: OwnerTransition,
    ) -> tuple[ShadowRpcIntent, ...]:
        intents = list(self._consume_transition(transition, ()))
        context = self._requests.get(request_id)
        if (
            context is None
            or context.purpose != "POST_CLOSE_QUOTE"
            or not any(
                emitted.object_kind
                in {
                    "POST_CLOSE_ATTEMPT_TERMINAL",
                    "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION",
                }
                for emitted in transition.emitted
            )
        ):
            return tuple(intents)
        anchor = self._anchor_for_owner_identity(context.owner_identity)
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
        if intent.purpose == "ADMISSION_REFRESH":
            purpose = RpcPurpose.ADMISSION_REFRESH
            send_budget = self.owner.policies.underwriting.combo_snapshot_send_budget_ms
            response_budget = self.owner.policies.underwriting.combo_snapshot_response_budget_ms
        elif intent.purpose == "POST_CLOSE_QUOTE":
            purpose = RpcPurpose.POST_CLOSE_REFRESH
            send_budget = self.owner.policies.position.combo_snapshot_send_budget_ms
            response_budget = self.owner.policies.position.combo_snapshot_response_budget_ms
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

    def _discover_anchors(self) -> None:
        for value in self.owner.writer.objects:
            kind = value["object_kind"]
            if kind not in {"SHADOW_ENTRY", "REJECTED_COUNTERFACTUAL_ANCHOR"}:
                continue
            identity = str(value["object_identity"])
            if identity in self._anchors:
                continue
            payload = value["payload"]
            if not isinstance(payload, Mapping):
                raise RuntimeError("anchor payload must be a mapping")
            leg_ids = payload["canonical_leg_identities"]
            if not isinstance(leg_ids, list) or len(leg_ids) != 2:
                raise RuntimeError("anchor requires exact canonical leg identities")
            self._anchors[identity] = _Anchor(
                anchor_identity=identity,
                entry_boundary=DownstreamFactBoundary.from_object(value["fact_boundary"]),
                canonical_combo_identity=str(payload["canonical_combo_identity"]),
                short_leg_identity=str(leg_ids[0]),
                long_leg_identity=str(leg_ids[1]),
                entry_direction=str(payload["entry_direction"]),
                target_quantity_btc=_decimal(payload["full_quantity_btc"]),
            )
        for value in self.owner.writer.objects:
            if value["object_kind"] not in {
                "SHADOW_OUTCOME_OBSERVATION",
                "REJECTED_COUNTERFACTUAL_OBSERVATION",
            }:
                continue
            payload = value["payload"]
            if not isinstance(payload, Mapping):
                raise RuntimeError("observation payload must be a mapping")
            anchor_field = (
                "rejected_anchor_identity"
                if value["object_kind"] == "REJECTED_COUNTERFACTUAL_OBSERVATION"
                else "shadow_entry_identity"
            )
            anchor = self._anchors.get(str(payload[anchor_field]))
            if anchor is not None:
                self._anchors_by_observation[str(value["object_identity"])] = anchor

    def _anchor_for_owner_identity(self, owner_identity: str) -> _Anchor | None:
        return self._anchors.get(owner_identity) or self._anchors_by_observation.get(owner_identity)

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
                    "btc_usdc",
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
        close_direction = "BUY" if anchor.entry_direction == "SELL" else "SELL"
        return (
            "ask" if close_direction == "BUY" else "bid",
            anchor.target_quantity_btc,
        )

    def _terminal_control(
        self,
        *,
        source: str,
        boundary: DownstreamFactBoundary,
    ) -> tuple[str, Mapping[str, object], str]:
        if source not in {"STOP", "FAILURE"}:
            raise ValueError("terminal source must be STOP or FAILURE")
        if self.manifest is None:
            raise RuntimeError("terminal control requires the validated manifest")
        configured = self._configured_terminal_control
        if configured is not None:
            disposition, control = configured
            if source == "FAILURE" and disposition != "PROCESS_FAILURE":
                raise ValueError("failure boundary requires PROCESS_FAILURE control")
            if source == "STOP" and disposition == "PROCESS_FAILURE":
                raise ValueError("stop boundary cannot consume PROCESS_FAILURE control")
            value = dict(control)
            label = {
                "PLANNED_CLEAN_STOP": "PreboundSupervisorTriggerIdentity",
                "AUTHORIZED_EMERGENCY_STOP": "AuthorizedEmergencyStopControlIdentity",
                "PROCESS_FAILURE": "FatalFailureControlIdentity",
            }[disposition]
            return disposition, value, canonical_identity(label, value)
        if source == "STOP":
            raw_control = self.manifest.value["final_stop_trigger"]
            if not isinstance(raw_control, Mapping):
                raise RuntimeError("validated final stop trigger must be a mapping")
            value = dict(raw_control)
            trigger_ms = value.get("trigger_monotonic_ms")
            if (
                isinstance(trigger_ms, bool)
                or not isinstance(trigger_ms, int)
                or boundary.received_monotonic_ms < trigger_ms
            ):
                raise RuntimeError("pre-final STOP requires an authorized typed emergency control")
            return (
                "PLANNED_CLEAN_STOP",
                value,
                canonical_identity("PreboundSupervisorTriggerIdentity", value),
            )
        failure_identity = canonical_identity(
            "RadarRuntimeFailureSourceIdentity",
            boundary.as_object(),
        )
        value = {
            "runtime_identity": self.manifest.runtime_identity,
            "supervisor_clock_identity": self.manifest.supervisor_clock_identity,
            "failure_source_identity": failure_identity,
            "control_monotonic_ms": boundary.received_monotonic_ms,
            "control_kind": "PROCESS_FAILURE",
            "failure_kind": "FATAL_RUNTIME",
        }
        return (
            "PROCESS_FAILURE",
            value,
            canonical_identity("FatalFailureControlIdentity", value),
        )

    def _require_bindings(self, reducer: RadarReducer) -> None:
        if (
            reducer.code_identity != self.owner.bindings.code_identity
            or reducer.runtime_identity != self.owner.bindings.runtime_identity
            or reducer.policy.identity != self.owner.bindings.radar_policy_identity
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


def _manifest_monotonic(manifest: ValidatedManifest, field: str) -> int:
    value = manifest.value[field]
    if not isinstance(value, Mapping):
        raise RuntimeError(f"validated manifest {field} must be a mapping")
    monotonic_ms = value["trigger_monotonic_ms"]
    if isinstance(monotonic_ms, bool) or not isinstance(monotonic_ms, int):
        raise RuntimeError(f"validated manifest {field} monotonic time must be an integer")
    return monotonic_ms
