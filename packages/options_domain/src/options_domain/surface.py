"""Internal-fit-free observed surface summaries."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from market_tape import OptionKind

from options_domain.contracts import OptionQuote, SurfaceExpirySummary, SurfaceSummary

SECONDS_PER_YEAR = Decimal(365 * 24 * 60 * 60)


def _nearest(
    quotes: tuple[OptionQuote, ...],
    kind: OptionKind,
    target_delta: Decimal,
) -> OptionQuote | None:
    matching = tuple(
        quote for quote in quotes if quote.option_kind is kind and quote.delta is not None
    )
    if not matching:
        return None
    return min(
        matching,
        key=lambda quote: (
            abs(abs(quote.delta or Decimal("0")) - target_delta),
            quote.quote_age_ms,
            quote.instrument_name,
        ),
    )


def _average(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    return sum(present, Decimal("0")) / Decimal(len(present))


def _descriptive_mid_iv(quote: OptionQuote | None) -> Decimal | None:
    if quote is None:
        return None
    if quote.bid_iv is not None and quote.ask_iv is not None:
        return (quote.bid_iv + quote.ask_iv) / Decimal("2")
    return quote.mark_iv


def build_surface_summary(
    quotes: tuple[OptionQuote, ...],
    *,
    as_of: datetime,
) -> SurfaceSummary:
    grouped: dict[datetime, list[OptionQuote]] = defaultdict(list)
    for quote in quotes:
        if quote.fresh:
            grouped[quote.expiry].append(quote)
    raw: list[SurfaceExpirySummary] = []
    for expiry in sorted(grouped):
        expiry_quotes = tuple(grouped[expiry])
        atm_candidates = tuple(
            item
            for item in (
                _nearest(expiry_quotes, OptionKind.CALL, Decimal("0.50")),
                _nearest(expiry_quotes, OptionKind.PUT, Decimal("0.50")),
            )
            if item is not None
        )
        atm_bid = _average(tuple(item.bid_iv for item in atm_candidates))
        atm_ask = _average(tuple(item.ask_iv for item in atm_candidates))
        atm_mark = _average(tuple(item.mark_iv for item in atm_candidates))
        call_25 = _descriptive_mid_iv(_nearest(expiry_quotes, OptionKind.CALL, Decimal("0.25")))
        put_25 = _descriptive_mid_iv(_nearest(expiry_quotes, OptionKind.PUT, Decimal("0.25")))
        atm_mid = (
            (atm_bid + atm_ask) / Decimal("2")
            if atm_bid is not None and atm_ask is not None
            else atm_mark
        )
        risk_reversal = call_25 - put_25 if call_25 is not None and put_25 is not None else None
        butterfly = (
            (call_25 + put_25) / Decimal("2") - atm_mid
            if call_25 is not None and put_25 is not None and atm_mid is not None
            else None
        )
        ages = tuple(item.quote_age_ms for item in expiry_quotes)
        raw.append(
            SurfaceExpirySummary(
                expiry=expiry,
                atm_bid_iv=atm_bid,
                atm_ask_iv=atm_ask,
                atm_mark_iv=atm_mark,
                risk_reversal_25d=risk_reversal,
                butterfly_25d=butterfly,
                adjacent_expiry_total_variance_slope=None,
                minimum_quote_age_ms=min(ages),
                maximum_quote_age_ms=max(ages),
                quote_count=len(expiry_quotes),
            )
        )
    summaries: list[SurfaceExpirySummary] = []
    for index, item in enumerate(raw):
        slope: Decimal | None = None
        if index + 1 < len(raw):
            next_item = raw[index + 1]
            current_iv = item.atm_mark_iv or (
                (item.atm_bid_iv + item.atm_ask_iv) / Decimal("2")
                if item.atm_bid_iv is not None and item.atm_ask_iv is not None
                else None
            )
            next_iv = next_item.atm_mark_iv or (
                (next_item.atm_bid_iv + next_item.atm_ask_iv) / Decimal("2")
                if next_item.atm_bid_iv is not None and next_item.atm_ask_iv is not None
                else None
            )
            if current_iv is not None and next_iv is not None:
                current_t = (
                    Decimal(max(1, int((item.expiry - as_of).total_seconds()))) / SECONDS_PER_YEAR
                )
                next_t = (
                    Decimal(max(1, int((next_item.expiry - as_of).total_seconds())))
                    / SECONDS_PER_YEAR
                )
                if next_t > current_t:
                    slope = (
                        (next_iv / Decimal("100")) ** 2 * next_t
                        - (current_iv / Decimal("100")) ** 2 * current_t
                    ) / (next_t - current_t)
        summaries.append(
            SurfaceExpirySummary(
                expiry=item.expiry,
                atm_bid_iv=item.atm_bid_iv,
                atm_ask_iv=item.atm_ask_iv,
                atm_mark_iv=item.atm_mark_iv,
                risk_reversal_25d=item.risk_reversal_25d,
                butterfly_25d=item.butterfly_25d,
                adjacent_expiry_total_variance_slope=slope,
                minimum_quote_age_ms=item.minimum_quote_age_ms,
                maximum_quote_age_ms=item.maximum_quote_age_ms,
                quote_count=item.quote_count,
            )
        )
    all_ages = tuple(quote.quote_age_ms for quote in quotes if quote.fresh)
    return SurfaceSummary(
        expiries=tuple(summaries),
        quote_age_dispersion_ms=(max(all_ages) - min(all_ages) if all_ages else None),
        source_capture_seqs=tuple(
            sorted({capture_seq for quote in quotes for capture_seq in quote.source_capture_seqs})
        ),
    )
