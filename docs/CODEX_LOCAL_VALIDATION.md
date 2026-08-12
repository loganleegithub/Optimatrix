# Codex local real-book validation

This tree is a clean replacement candidate. It does not read or migrate the legacy Case root.

## 1. Verify the immutable offline baseline

```bash
make sync
make check
.venv/bin/python -m optimatrix simulate \
  --scenario all \
  --output build/business-acceptance.json \
  --case-root build/simulation-cases
.venv/bin/python -m optimatrix channels --json
```

The synthetic scenarios prove business reachability and arithmetic, not market Edge.

## 2. Run the bounded public HTTP snapshot

Event state is deliberately explicit. The package does not invent an event calendar.

```bash
.venv/bin/python -m optimatrix snapshot \
  --event-state NONE \
  --maximum-books 32 \
  --depth 20 \
  --output build/deribit-current-session-snapshot.json
```

The command uses public methods only:

```text
public/get_index_price
public/get_instruments
public/get_order_book
public/get_index_chart_data
public/get_combos
```

It performs bounded concurrent order-book reads, validates the current 08:00 UTC expiry, checks
quantity/tick/product facts, rejects material index-history gaps, and evaluates one read-only
current-session decision. It does **not** create a durable Decision Case.

The output includes:

- one canonical `SessionDecisionUnit` funnel with stage numerator, denominator, and earliest
  blocker;
- current-session instrument and usable-book denominators;
- Put/Call Vertical and Iron Condor counts;
- exact Session phase;
- same-session implied-variance and physical-variance proxy methodology;
- VRP, Theta, Gamma-safety, range, execution and final score;
- the selected four-leg structure, or precise blockers;
- an exact-leg-set public-combo diagnostic;
- source limitations and warnings.

Render that exact snapshot without adding browser-side business logic:

```bash
.venv/bin/python -m optimatrix workbench \
  --snapshot build/deribit-current-session-snapshot.json \
  --output-dir build/workbench
```

## 3. Inspect the first real-market blockers before changing Policy

At minimum, aggregate repeated snapshots by:

```text
session phase
minutes to expiry
event state
weekday / expiry class
Put and Call Vertical count
Condor count
Radar decision / blocker
four-leg fee burden
body distance
source and receive skew
public combo observed / absent
```

Do not lower thresholds merely to create Candidates. First determine whether loss occurs at:

```text
current-session option coverage
short Delta availability
wing availability
full target depth
quote coherence
four-leg economics
VRP / Theta
Gamma / event / breakout risk
```

## 4. Continuous public-feed integration

Only after the bounded HTTP snapshot matches actual Deribit payloads should Codex add one current
WebSocket translator. It must produce the existing `OptionQuote` and `MarketContext` types and call
the existing business owner. It must not duplicate pricing, score, session, or lifecycle formulas.

A live translator must preserve:

- one Deribit Session identity ending at 08:00 UTC;
- source and receive timestamps for each option snapshot;
- continuity epoch;
- full target quantity and published tick schedule;
- event state from an explicit calendar/human source;
- no private API, RFQ, combo creation, order, fill, account or margin claim.

## 5. Entry and Position validation

Do not start with real durable Cases. First run read-only repeated observations proving:

- full, one-side, cross-side-incoherent, wings-only and no-entry routes are distinguishable;
- every partial short exposure is `EXIT_REQUIRED` immediately and cannot enter normal carry;
- a dangerous short can be bought back without selling a valueless long wing;
- pending exit intent survives unavailable quotes and process restart;
- the in-process retry cadence is respected;
- remaining long wings can be sold or settled;
- native BTC PnL and USD boundary valuations remain distinct.

Only an explicit later cutover may authorize a fresh state root. The legacy root remains outside
this candidate and is not a migration source.
