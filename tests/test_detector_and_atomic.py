from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import PolicyFactory
from market_monitor import ContinuousOrderBook, TimeInterval
from options_domain import AmountMetadata, ComboInstrument, ComboLeg, OptionInstrument, OptionType
from short_vol_radar.atomic import (
    ComboOrderDirection,
    PublicAtomicQuoteState,
    classify_atomic_quotes,
    match_vertical_combo,
)
from short_vol_radar.black import DecimalInterval
from short_vol_radar.detector import (
    AggregateApplicability,
    DetectorCoverage,
    DetectorObservation,
    DetectorState,
    EpisodeEndReason,
    EpisodeTracker,
    NumericalBoundaryUnresolved,
    TrackerState,
    aggregate_detector,
    classify_observation,
    delta_is_eligible,
)
from short_vol_radar.policy import OptionRule, load_policy_bytes


def observation(
    causal_seq: int,
    lower_time: int,
    upper_time: int,
    richness: str,
    *,
    band_id: str = "band",
) -> DetectorObservation:
    value = Decimal(richness)
    return DetectorObservation(
        causal_seq,
        TimeInterval(lower_time, upper_time),
        band_id,
        DecimalInterval(value, value),
    )


def activated_tracker(policy_factory: PolicyFactory) -> tuple[EpisodeTracker, OptionRule]:
    exact, digest = policy_factory(activation_count=1, clear_count=1, separation_ms=0)
    rule = load_policy_bytes(exact, digest).tte_bands[0].option_rules[OptionType.CALL]
    tracker = EpisodeTracker(
        runtime_identity="run", policy_identity=digest, instrument_name="SHORT"
    )
    transition = tracker.observe(observation(1, 1_000, 1_001, "1.3"), rule)
    assert transition.activated_episode_id is not None
    return tracker, rule


def test_activation_separation_equality_overlap_and_interruption(
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=2, separation_ms=1_000)
    rule = load_policy_bytes(exact, digest).tte_bands[0].option_rules[OptionType.CALL]
    tracker = EpisodeTracker(
        runtime_identity="run", policy_identity=digest, instrument_name="SHORT"
    )
    assert tracker.observe(observation(1, 1_000, 1_010, "1.3"), rule).activated_episode_id is None
    assert tracker.observe(observation(2, 2_009, 2_009, "1.3"), rule).activated_episode_id is None
    activated = tracker.observe(observation(3, 2_010, 2_011, "1.3"), rule)
    assert activated.activated_episode_id is not None
    assert tracker.detector_state is DetectorState.ANOMALY_ACTIVE

    tracker = EpisodeTracker(
        runtime_identity="run", policy_identity=digest, instrument_name="RESET"
    )
    tracker.observe(observation(1, 1_000, 1_000, "1.3"), rule)
    tracker.observe(observation(2, 1_100, 1_100, "1.0"), rule)
    assert tracker.observe(observation(3, 3_000, 3_000, "1.3"), rule).activated_episode_id is None


def test_clear_rearm_gap_and_fresh_episode_identity(
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory(activation_count=1, clear_count=2, separation_ms=1_000)
    rule = load_policy_bytes(exact, digest).tte_bands[0].option_rules[OptionType.CALL]
    tracker = EpisodeTracker(
        runtime_identity="run", policy_identity=digest, instrument_name="SHORT"
    )
    first = tracker.observe(observation(1, 0, 0, "1.3"), rule).activated_episode_id
    tracker.observe(observation(2, 1_000, 1_000, "0.8"), rule)
    assert tracker.state.value == TrackerState.CLEARING.value
    tracker.observe(observation(3, 1_500, 1_500, "1.0"), rule)
    assert tracker.state.value == TrackerState.ACTIVE.value
    tracker.observe(observation(4, 3_000, 3_000, "0.8"), rule)
    ended = tracker.observe(observation(5, 4_000, 4_000, "0.8"), rule).ended_episode
    assert ended is not None and ended.reason is EpisodeEndReason.CLEAR
    assert tracker.detector_state.value == DetectorState.NO_ANOMALY.value

    second = tracker.observe(observation(6, 5_000, 5_000, "1.3"), rule).activated_episode_id
    assert second is not None and second != first
    gap_end = tracker.unknown(reason="BOOK_GAP", causal_seq=7, continuity_gap=True).ended_episode
    assert gap_end is not None and gap_end.reason is EpisodeEndReason.UNKNOWN_AT_GAP
    assert tracker.detector_state.value == DetectorState.UNKNOWN.value
    third = tracker.observe(observation(8, 6_000, 6_000, "1.3"), rule).activated_episode_id
    assert third is not None and third not in {first, second}


@pytest.mark.parametrize(
    ("method", "reason"),
    [
        ("known_ineligible", EpisodeEndReason.KNOWN_INELIGIBLE),
        ("out_of_baseline_scope", EpisodeEndReason.OUT_OF_BASELINE_SCOPE),
        ("membership_loss", EpisodeEndReason.MEMBERSHIP_LOSS),
        ("unknown", EpisodeEndReason.UNKNOWN_DETECTOR),
        ("stop", EpisodeEndReason.CENSORED_AT_STOP),
    ],
)
def test_every_immediate_episode_end_reason(
    method: str, reason: EpisodeEndReason, policy_factory: PolicyFactory
) -> None:
    tracker, _rule = activated_tracker(policy_factory)
    if method == "known_ineligible":
        transition = tracker.known_ineligible(reason="DEPTH", causal_seq=2)
    elif method == "unknown":
        transition = tracker.unknown(reason="MISSING", causal_seq=2)
    else:
        transition = getattr(tracker, method)(causal_seq=2)
    assert transition.ended_episode is not None
    assert transition.ended_episode.reason is reason


def test_adjacent_band_suspend_resume_preserves_episode_identity(
    policy_factory: PolicyFactory,
) -> None:
    tracker, _rule = activated_tracker(policy_factory)
    episode_id = tracker.episode_id
    tracker.suspend_for_band_boundary()
    assert tracker.state.value == TrackerState.BAND_SUSPENDED.value
    assert tracker.detector_state is DetectorState.UNKNOWN
    tracker.resume_after_band_boundary()
    assert tracker.state.value == TrackerState.ACTIVE.value
    assert tracker.episode_id == episode_id


def test_interval_boundaries_fail_closed_instead_of_selecting_a_point(
    policy_factory: PolicyFactory,
) -> None:
    exact, digest = policy_factory()
    rule = load_policy_bytes(exact, digest).tte_bands[0].option_rules[OptionType.CALL]
    assert classify_observation(DecimalInterval(Decimal("1.2"), Decimal("1.2")), rule).value == (
        "ACTIVATE"
    )
    assert classify_observation(DecimalInterval(Decimal("0.9"), Decimal("0.9")), rule).value == (
        "CLEAR"
    )
    with pytest.raises(NumericalBoundaryUnresolved):
        classify_observation(DecimalInterval(Decimal("1.19"), Decimal("1.21")), rule)
    assert delta_is_eligible(DecimalInterval(Decimal("0.1"), Decimal("0.2")), rule)
    with pytest.raises(NumericalBoundaryUnresolved):
        delta_is_eligible(DecimalInterval(Decimal("0.04"), Decimal("0.06")), rule)


def test_non_vacuous_completeness_aware_aggregate_truth_table() -> None:
    empty = aggregate_detector((), catalog_complete=True, has_applicable_scope=False)
    assert empty.applicability is AggregateApplicability.NO_APPLICABLE_SCOPE
    assert empty.state is None and empty.coverage is None

    complete = aggregate_detector(
        (DetectorState.NO_ANOMALY, DetectorState.NO_ANOMALY),
        catalog_complete=True,
        has_applicable_scope=True,
    )
    assert complete.state is DetectorState.NO_ANOMALY
    assert complete.coverage is DetectorCoverage.COMPLETE

    unknown = aggregate_detector(
        (DetectorState.NO_ANOMALY, DetectorState.UNKNOWN),
        catalog_complete=True,
        has_applicable_scope=True,
    )
    assert unknown.state is DetectorState.UNKNOWN

    positive = aggregate_detector(
        (DetectorState.ANOMALY_ACTIVE, DetectorState.UNKNOWN),
        catalog_complete=True,
        has_applicable_scope=True,
    )
    assert positive.state is DetectorState.ANOMALY_ACTIVE
    assert positive.coverage is DetectorCoverage.DEGRADED


def make_option(name: str, strike: str, option_type: OptionType) -> OptionInstrument:
    return OptionInstrument(
        name,
        10_000_000,
        Decimal(strike),
        option_type,
        AmountMetadata(Decimal(1), Decimal("0.1"), Decimal("0.1")),
    )


def make_combo(
    name: str,
    first: tuple[str, str],
    second: tuple[str, str],
    *,
    step: Decimal | None = Decimal("0.1"),
) -> ComboInstrument:
    return ComboInstrument(
        name,
        "active",
        (
            ComboLeg(first[0], Decimal(first[1])),
            ComboLeg(second[0], Decimal(second[1])),
        ),
        AmountMetadata(Decimal(1), Decimal("0.1"), step),
    )


def combo_book(
    name: str,
    *,
    bids: tuple[tuple[str, str], ...] = (),
    asks: tuple[tuple[str, str], ...] = (),
) -> ContinuousOrderBook:
    book = ContinuousOrderBook(name)
    book.apply(
        {
            "type": "snapshot",
            "timestamp": 1_000,
            "instrument_name": name,
            "change_id": 1,
            "bids": [["new", price, amount] for price, amount in bids],
            "asks": [["new", price, amount] for price, amount in asks],
        },
        1,
    )
    return book


@pytest.mark.parametrize(
    ("option_type", "short_strike", "long_strike"),
    [
        (OptionType.CALL, "100", "110"),
        (OptionType.PUT, "100", "90"),
    ],
)
def test_official_vertical_direction_and_signed_credit(
    option_type: OptionType, short_strike: str, long_strike: str
) -> None:
    short = make_option("SHORT", short_strike, option_type)
    long = make_option("LONG", long_strike, option_type)
    combo = make_combo("COMBO", ("SHORT", "-1"), ("LONG", "1"))
    match = match_vertical_combo(
        short_leg=short,
        options_by_name={"SHORT": short, "LONG": long},
        combo=combo,
        target_btc=Decimal("0.1"),
    )
    assert match is not None and match.direction is ComboOrderDirection.BUY
    result = classify_atomic_quotes(
        anomaly_active=True,
        combo_catalog_complete=True,
        short_leg=short,
        options_by_name={"SHORT": short, "LONG": long},
        combos=(combo,),
        combo_books={"COMBO": combo_book("COMBO", asks=(("-5", "0.1"),))},
        target_btc=Decimal("0.1"),
    )
    assert result.state is PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE
    assert result.quotes[0].gross_entry_credit_usdc == Decimal("0.5")

    incomplete_positive = classify_atomic_quotes(
        anomaly_active=True,
        combo_catalog_complete=False,
        short_leg=short,
        options_by_name={"SHORT": short, "LONG": long},
        combos=(combo,),
        combo_books={"COMBO": combo_book("COMBO", asks=(("-5", "0.1"),))},
        target_btc=Decimal("0.1"),
    )
    assert incomplete_positive.state is PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE

    debit = classify_atomic_quotes(
        anomaly_active=True,
        combo_catalog_complete=True,
        short_leg=short,
        options_by_name={"SHORT": short, "LONG": long},
        combos=(combo,),
        combo_books={"COMBO": combo_book("COMBO", asks=(("5", "0.1"),))},
        target_btc=Decimal("0.1"),
    )
    assert debit.state is PublicAtomicQuoteState.NO_TARGET_SIZE_CREDIT_QUOTE


def test_combo_sell_direction_uses_bids_and_no_absolute_value() -> None:
    short = make_option("SHORT", "100", OptionType.CALL)
    long = make_option("LONG", "110", OptionType.CALL)
    combo = make_combo("COMBO", ("SHORT", "1"), ("LONG", "-1"))
    result = classify_atomic_quotes(
        anomaly_active=True,
        combo_catalog_complete=True,
        short_leg=short,
        options_by_name={"SHORT": short, "LONG": long},
        combos=(combo,),
        combo_books={"COMBO": combo_book("COMBO", bids=(("5", "0.1"),))},
        target_btc=Decimal("0.1"),
    )
    assert result.quotes[0].match.direction is ComboOrderDirection.SELL
    assert result.quotes[0].gross_entry_credit_usdc == Decimal("0.5")


def test_atomic_negative_claims_require_complete_relevant_scope() -> None:
    short = make_option("SHORT", "100", OptionType.CALL)
    long = make_option("LONG", "110", OptionType.CALL)
    combo = make_combo("COMBO", ("SHORT", "-1"), ("LONG", "1"))
    options = {"SHORT": short, "LONG": long}
    assert (
        classify_atomic_quotes(
            anomaly_active=False,
            combo_catalog_complete=False,
            short_leg=short,
            options_by_name=options,
            combos=(),
            combo_books={},
            target_btc=Decimal("0.1"),
        ).state
        is PublicAtomicQuoteState.NOT_EVALUATED
    )
    assert (
        classify_atomic_quotes(
            anomaly_active=True,
            combo_catalog_complete=False,
            short_leg=short,
            options_by_name=options,
            combos=(),
            combo_books={},
            target_btc=Decimal("0.1"),
        ).state
        is PublicAtomicQuoteState.UNKNOWN
    )

    unknown_amount_combo = ComboInstrument(
        combo.instrument_name,
        combo.state,
        combo.legs,
        None,
    )
    insufficient_known = classify_atomic_quotes(
        anomaly_active=True,
        combo_catalog_complete=True,
        short_leg=short,
        options_by_name=options,
        combos=(unknown_amount_combo,),
        combo_books={"COMBO": combo_book("COMBO", asks=(("-5", "0.05"),))},
        target_btc=Decimal("0.1"),
    )
    assert insufficient_known.state is PublicAtomicQuoteState.NO_TARGET_SIZE_CREDIT_QUOTE
    enough_depth_unknown = classify_atomic_quotes(
        anomaly_active=True,
        combo_catalog_complete=True,
        short_leg=short,
        options_by_name=options,
        combos=(unknown_amount_combo,),
        combo_books={"COMBO": combo_book("COMBO", asks=(("-5", "0.1"),))},
        target_btc=Decimal("0.1"),
    )
    assert enough_depth_unknown.state is PublicAtomicQuoteState.UNKNOWN
    assert (
        classify_atomic_quotes(
            anomaly_active=True,
            combo_catalog_complete=True,
            short_leg=short,
            options_by_name=options,
            combos=(),
            combo_books={},
            target_btc=Decimal("0.1"),
        ).state
        is PublicAtomicQuoteState.NO_ACTIVE_COMBO
    )
    assert (
        classify_atomic_quotes(
            anomaly_active=True,
            combo_catalog_complete=True,
            short_leg=short,
            options_by_name=options,
            combos=(combo,),
            combo_books={},
            target_btc=Decimal("0.1"),
        ).state
        is PublicAtomicQuoteState.UNKNOWN
    )


def test_wrong_ratio_expiry_type_and_grid_do_not_create_atomic_quote() -> None:
    short = make_option("SHORT", "100", OptionType.CALL)
    long = make_option("LONG", "110", OptionType.CALL)
    wrong_ratio = make_combo("RATIO", ("SHORT", "-2"), ("LONG", "2"))
    assert (
        match_vertical_combo(
            short_leg=short,
            options_by_name={"SHORT": short, "LONG": long},
            combo=wrong_ratio,
            target_btc=Decimal("0.1"),
        )
        is None
    )
    wrong_type = make_option("LONG", "90", OptionType.PUT)
    combo = make_combo("TYPE", ("SHORT", "-1"), ("LONG", "1"))
    assert (
        match_vertical_combo(
            short_leg=short,
            options_by_name={"SHORT": short, "LONG": wrong_type},
            combo=combo,
            target_btc=Decimal("0.1"),
        )
        is None
    )
    off_grid = make_combo("GRID", ("SHORT", "-1"), ("LONG", "1"), step=Decimal("0.2"))
    result = classify_atomic_quotes(
        anomaly_active=True,
        combo_catalog_complete=True,
        short_leg=short,
        options_by_name={"SHORT": short, "LONG": long},
        combos=(off_grid,),
        combo_books={"GRID": combo_book("GRID", asks=(("-5", "1"),))},
        target_btc=Decimal("0.1"),
    )
    assert result.state is PublicAtomicQuoteState.NO_TARGET_SIZE_CREDIT_QUOTE


def test_combo_state_never_changes_detector_truth(
    policy_factory: PolicyFactory,
) -> None:
    tracker, _rule = activated_tracker(policy_factory)
    short = make_option("SHORT", "100", OptionType.CALL)
    before = tracker.detector_state
    result = classify_atomic_quotes(
        anomaly_active=True,
        combo_catalog_complete=True,
        short_leg=short,
        options_by_name={"SHORT": short},
        combos=(),
        combo_books={},
        target_btc=Decimal("0.1"),
    )
    assert result.state is PublicAtomicQuoteState.NO_ACTIVE_COMBO
    assert tracker.detector_state is before is DetectorState.ANOMALY_ACTIVE
