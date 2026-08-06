# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current implementation status:** `COMPONENT_BOOK_SHADOW_LIFECYCLE_ACCEPTED`

**Production Short Vol Radar:** `CREDIBLE_CLUE_GENERATOR_FROZEN`

**Persistent service:** `NATURAL_PUBLIC_SHADOW_ACTIVE_NO_DEPLOYMENT`

**Live commands:** `SHORT_PUBLIC_SMOKE_THEN_NATURAL_SHADOW_UNTIL_HUMAN_STOP`

**Sole authorized closure:** `SHORT_VOL_NATURAL_SHADOW_OPERATION`

## Current truth

The fixed 43,200-second production-public observation on code identity
`5cbcfdd31174a63ffe6f39d23017f0d359ae8fea` reached its precommitted terminal boundary. It
observed `84` distinct contract-level Radar Episodes and `84` reviewable protective structures.
It observed zero official atomic quotes: the exact Atomic diagnostic was `NO_ACTIVE_COMBO 84`.
No Candidate reached admission, no Shadow Case opened, and durable Shadow Case files remained zero.

That run was valid evidence about existing Deribit Combo discovery, but its main funnel encoded the
wrong business dependency. `NO_ACTIVE_COMBO` means the exact exchange-managed combo was not already
active; it does not mean the two public option books lacked target-size depth, that a protected
vertical could not be conservatively priced, or that a public-only Shadow counterfactual could not
be enrolled. Treating Combo as the Shadow admission gate therefore censored the product before it
could learn Outcomes.

The active implementation replaces that gate with one frozen component-book counterfactual:

```text
APPLICABLE_MARKET_SCOPE
→ RADAR_KNOWN
→ ANOMALY_ACTIVE
→ STRUCTURE_REVIEWABLE
→ COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE
→ UNDERWRITING_EVALUABLE
→ CANDIDATE
→ SHADOW_CASE_OPENED
→ SHADOW_CASE_OUTCOME
```

For each active Episode, Radar freezes one current protective long and does not switch it later.
At target quantity `0.1 BTC`, the entry counterfactual sells the short from public bid depth stressed
down one official tick and buys the protective long from public ask depth stressed up one official
tick. Both standard Deribit option fees are reserved. Candidate admission requires exactly two
strictly later `public/get_order_book` responses, one for each frozen leg, bound to one causal
owner. One response, stale timing, insufficient depth, malformed facts, or an ordinary RPC failure
cannot open a Case.

After admission, Position uses the same two frozen legs. A known close counterfactual buys back the
short from ask depth stressed up one tick and sells the long from bid depth stressed down one tick,
again at full quantity with both standard fees. A paired close may produce `MATURE_KNOWN`; an
unresolved close at natural maturity is `MATURE_UNKNOWN`. Every Case explicitly states
`NOT_AN_ORDER`, `NOT_A_FILL`, `NOT_AN_ATOMIC_QUOTE`,
`NO_LIQUIDITY_RESERVATION`, and `ATOMIC_EXECUTABILITY_UNPROVEN`.

Existing official Combo discovery remains a parallel diagnostic:

```text
NOT_EVALUATED | UNKNOWN | NO_ACTIVE_COMBO |
NO_TARGET_SIZE_CREDIT_QUOTE | PUBLIC_ATOMIC_QUOTE_AVAILABLE
```

It does not create or veto a component-book Candidate, Entry, Close, or Outcome. Private Combo
creation, RFQ, account state, margin, orders, fills, capital, and actual exposure remain outside the
current permission boundary.

The component-book implementation on code identity
`553f763df77737e15ffe07879ad344070a567111` passed the full repository gate and one bounded
production-public smoke. That smoke reached current public state with all monitored contracts
known, opened no natural Radar Episode or Shadow Case, and preserved zero pre-Case business files.
It established source/runtime reachability only; it did not measure natural Candidate frequency or
Outcome quality.

## Allowed work

- after each committed code identity, run focused tests, the full repository gate, and one short
  production-public read-only smoke of at most `600` seconds before natural Shadow operation;
- if that smoke fails, stop at the failure, repair only the owning business or source boundary
  offline, repeat the gates, and retry the short smoke until it terminates readably;
- after a passing smoke, run one production-public natural Shadow service with the frozen Policy
  chain until a human requests stop or a fatal process failure terminates it;
- inspect its current Workbench facts, funnel movement, admitted Case records, and Outcomes without
  host/PID/resource inspection, automatic restart, or runtime tuning;
- after a fatal failure, preserve any admitted Case truth, diagnose and repair offline, pass the
  same gates and short smoke, then start a new runtime identity;
- preserve zero durable business files whenever no Shadow Case is admitted.

Natural Shadow is ordinary product observation, not a duration-based acceptance ceremony. Zero
Episodes, Candidates, Cases, or Outcomes remains a valid market result and does not authorize
threshold changes.

## Forbidden work

- changing Radar thresholds, benchmark, TTE/Delta universe, target quantity, reserve thresholds, or
  fees to manufacture a Candidate;
- using the smoke result to tune the frozen Policy;
- private/account API, Combo creation, RFQ, orders, fills, margin, balance, capital, or actual
  exposure;
- treating two leg snapshots as an atomic execution, guaranteed simultaneous fill, liquidity
  reservation, or proof of strategy edge;
- database, replay platform, full-feed persistence, ML, SVI/Heston, GEX, microservice split,
  deployment, commissioning, host inspection, or operational control;
- automatic restart, application supervision, or a second concurrent natural Shadow runtime.

## Acceptance boundary

The short smoke must terminate readably before each natural runtime starts. During natural Shadow,
each admitted Case and Outcome must retain the frozen component pair, strictly later paired books,
full-quantity adverse stress, both fees, exact code/Policy identities, and explicit non-claims.
Elapsed runtime is not acceptance. Natural observations cannot by themselves establish fillability,
profitability, Policy edge, qualification, deployment readiness, or private execution permission.
