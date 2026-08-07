# Short Vol Shadow Case Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `SHORT_VOL_SHADOW_CASE`

## Purpose

Define the only durable business boundary in the current public-only product. A Shadow Case begins
when one counterfactual is explicitly enrolled before its future path is known: either an admitted
Candidate trade or the one action-blind selected no-trade decision for its causal activation batch.
It preserves the minimum enrollment context, a bounded first-CLOSE transition, and one terminal
result for trader review, AI research, and later offline qualification.

The Online Runtime does not persist qualification Cohorts, aligned pairs, comparison tables,
Challenger features, Radar events, Underwriting events, or unselected/automatic no-trade
counterfactuals.

## Record set

Exactly three record kinds are authorized:

```text
SHADOW_CASE_OPENED               exactly one per Case
SHADOW_CASE_FIRST_CLOSE          zero or one per Case
SHADOW_CASE_OUTCOME              zero or one per Case
```

Each Case directory is:

```text
cases/<case-id>/opened.json
cases/<case-id>/first-close.json    # optional
cases/<case-id>/outcome.json        # optional
```

No other durable file belongs to the product runtime.

## Case identity

`case_id` is a canonical SHA-256 identity derived from:

```text
"ShadowCaseIdentity"
code_identity
runtime_identity
Radar Policy identity
Underwriting Policy identity
Position Policy identity
enrollment identity (`SHADOW_ENTRY` or selected-decision-control open)
opened FactBoundary
```

Policy identities are exact content digests. The code identity is the exact Git commit. Markdown
contract bytes, file paths, host identity, PID, manifest, receipt, directory inventory, and
Workbench publication sequence do not enter the Case identity.

Every record binds the same case, code, runtime, and Policy identities. Boundaries use the same
runtime and strictly increasing causal sequence.

## `SHADOW_CASE_OPENED`

The opened record contains:

- `record_kind`, `schema_version`, and `case_id`;
- exact code/runtime/three-Policy identities;
- `enrollment_kind`, generic enrollment identity, opened/entry and Underwriting decision boundaries;
- Candidate/`SHADOW_ENTRY` identities for admitted trades, or explicit nulls for no-trade controls;
- execution model and two frozen canonical option-leg identities;
- display instrument names, expiry, option type, strikes, entry direction, and full BTC quantity;
- paired component-book source identity, session/continuity epochs, measured source/receive skew,
  consumed Policy skew limits, and exact raw/stressed full-quantity levels for both legs;
- gross credit, entry fee reserve, net credit, payoff cap, future-cost reserve, and reserved loss;
- the minimal consumed Radar state: active episode identity, band, richness interval, component
  state, and official atomic diagnostic;
- the Underwriting action, complete failed-predicate/margin vector, and thresholds actually consumed;
- the protective-leg selector-rule identity and Candidate protective-leg count frozen with the
  selected structure;
- when pre-outcome selected, the selection rule/batch identities plus original and refreshed actions,
  complete predicate-margin vectors, and their strictly ordered boundaries;
- exact non-claims: `NOT_AN_ORDER`, `NOT_A_FILL`, `NOT_AN_ATOMIC_QUOTE`,
  `NO_LIQUIDITY_RESERVATION`, and `ATOMIC_EXECUTABILITY_UNPROVEN`. A no-trade control additionally
  states `NOT_A_CANDIDATE_ACTIVATION`, `NOT_A_SHADOW_ENTRY`, `NOT_AN_ADMITTED_TRADE`, and
  `NO_CAPITAL_EXPOSURE`.

Each entry leg's consumed amounts must sum exactly to the full quantity. Pair session and continuity
epochs must match, measured receive skew must agree with the two receipt boundaries, and both skews
must remain within the stored limits bound to the Underwriting Policy. Stored gross credit, both fee
reserves, net credit, width, payoff cap, loss values, canonical six-predicate margin vector, failed
predicates, and resulting action must conserve against the stored stressed legs and Policy
thresholds. The record may not contain the full option chain or unrelated market state.

## `SHADOW_CASE_FIRST_CLOSE`

The optional first-close record is written only when the Position owner first latches CLOSE. It
contains:

- same Case/code/runtime/Policy identities;
- the exact first Position action identity and boundary;
- primary and ordered latched close reasons;
- the predicate truth vector consumed at that boundary.

Later Position evaluations cannot rewrite it or create another first-close record.

## `SHADOW_CASE_OUTCOME`

The terminal record has one immutable state:

```text
MATURE_KNOWN
MATURE_UNKNOWN
CENSORED_AT_STOP
CENSORED_AT_FAILURE
```

`MATURE_KNOWN` requires the first eligible strictly post-CLOSE paired component-book exit for the
same frozen legs. It stores the pair/source identities, raw/stressed full-quantity levels for both
legs, gross close cashflow, both close fee reserves, net close cashflow, gross PnL, total public fee
reserve, net PnL after reserve, and net loss.

`MATURE_UNKNOWN` means the Case reached its natural terminal condition without an eligible paired
component-book exit under the frozen contract. Component close facts and economic exit/PnL fields
are absent or null.

A handled clean stop or failure that ends a still-pending Case produces the matching censored
state with null outcome economics. Censoring is valid research data, not software success or a
known trading result.

## Unclean process loss

The writer cannot guarantee a terminal record after power loss or an uncatchable process crash. A
reader finding a valid `opened.json` and no `outcome.json` reports:

```text
INCOMPLETE_UNCLEAN_EXIT
```

It does not synthesize an Outcome, delete the Case, migrate it, or resume it in a new runtime.
Cross-runtime recovery requires future explicit authority.

## Minimal writer

The Case writer:

- creates the Case directory without following symlinks;
- writes canonical UTF-8 JSON to a short same-directory temporary file;
- flushes and `fsync`s the file;
- publishes by exclusive hard link or another no-overwrite atomic operation;
- `fsync`s the parent directory;
- accepts an identical duplicate as idempotent and rejects a conflicting duplicate;
- never scans or validates another Case as part of the write.

This is durable-record integrity, not a general evidence or commissioning framework.

## Minimal reader

The product reader validates only the one requested Case:

- exact record key/type shape;
- identity format and same Case/code/runtime/Policy binding;
- opened pair identity/timing/Policy limits, per-leg quantity, stress direction, fee, and economic
  conservation;
- canonical predicate order/unit/sign truth, failed predicates, action, and Policy-bound margins;
- strictly later first-close/outcome boundaries;
- state-specific null/economic requirements;
- recomputable paired component-book PnL arithmetic;
- no conflicting duplicate files.

It returns `OPEN`, `COMPLETE`, or `INCOMPLETE_UNCLEAN_EXIT`. It does not rebuild a repository graph,
validate Git trees, inspect host state, read legacy schemas, or form a qualification Cohort.

## No-trade controls and Cohorts

The current implementation may enroll one no-trade control only when the causal activation batch
designated its Episode before action/future facts, that Episode later produced its first evaluable
decision, and exactly one strictly later paired refresh remained evaluable as WATCH or ABSTAIN.
`UNKNOWN` and invalid pairs write no Case, and the designation has no fallback. The system never
persists every WATCH or ABSTAIN automatically. The no-trade Case reuses Position/Outcome arithmetic
but is not a Candidate, `SHADOW_ENTRY`, admitted trade, order, fill, or causal-effect estimate.
A selected WATCH/ABSTAIN that refreshes to Candidate writes no control Case and reports
`REFRESHED_CANDIDATE_REQUIRES_CANONICAL_ADMISSION`; any later admission requires the ordinary
Candidate lifecycle and another strictly later paired witness.

Qualification Cohorts are later offline views over completed or honestly censored Cases under a
pre-registered evaluator. The Online Runtime never writes Cohort or aligned-pair objects.

## Required verification

Direct tests prove zero pre-enrollment files, exact one-open/one-first-close/one-outcome cardinality,
schema-v3 enrollment discrimination, original/refreshed selection boundary ordering, zero
Candidate/`SHADOW_ENTRY` for controls, atomic file publication, duplicate handling, pair/source
identity and boundary binding, both-leg arithmetic, censoring, and unclean incomplete readback. No
manifest, receipt, full graph, legacy reader, or replay is required.
