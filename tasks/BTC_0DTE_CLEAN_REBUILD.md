# Task — BTC 0DTE clean rebuild

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED — at most one bounded read-only Deribit current-session snapshot after offline gates pass

**Base commit:** `13902c53e972f12721d2ef9d17de866fbda288a7`

**Target branch/PR:** `codex/btc-0dte-clean-rebuild`; Draft PR pending because remote reachability is `UNVERIFIED`

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/DELIVERY_CONTRACT.md`, `docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`,
and `docs/contracts/SHADOW_LIFECYCLE.md`

## Product movement

**Current funnel node:** `FOUR_LEG_STRUCTURE_REVIEWABLE`

**Baseline:** `0 / 1` canonical repository product paths produce a current-Deribit-session,
four-leg Iron Condor; the only path at the base commit produces one single-side Credit Vertical.

**Primary blocker:** `WRONG_CANONICAL_STRATEGY_OBJECT` on `1 / 1` implemented product paths.

**Expected user-visible delta:** the repository's only enabled product, CLI, bounded public snapshot,
and read-only Workbench present one joint Put-plus-Call Iron Condor decision with exact four-leg,
session, risk, acquisition, and lifecycle blockers; no single-side strategy can be selected.

**Durable-data effect:** a new schema-v1 Decision journal may be written only beneath an explicitly
provided new Case root. The legacy V2 root is never read, written, migrated, relabelled, or counted
as Iron Condor evidence.

**Complexity added:** one modular `optimatrix` package, one fixed Iron Condor Policy, one bounded
public-snapshot adapter, one append-only journal, and one minimal read-only Workbench projection.

**Complexity deleted:** the legacy single-option Radar, single-side Candidate/Underwriting/Position
chain, three V2 Policies, schema-v5 runtime/Case path, old service owner graph, and strategy-bound
Workbench projection.

## Business closure

**Given:** the base repository's only product selects one Call or Put Vertical, while the human-selected
product is same-session, two-sided, defined-risk BTC 0DTE premium sale.

**When:** the Pro candidate is adopted as the isolated product core, its acquisition-residue risk is
made fail-closed, the inherited product-funnel Authority is restored, and only audited product-neutral
assets are transplanted.

**Then:** exactly one enabled product path evaluates a four-leg Iron Condor; `FULL_ENTRY` alone enters
normal carry, partial short exposure enters bounded remediation, and every current funnel loss is
reported with a numerator, denominator, and blocker.

**Valid zero/UNKNOWN:** zero current-session instruments, zero jointly reviewable structures, or any
missing/stale required public fact is a truthful funnel result and cannot create a Decision Case or
normal Position. It satisfies honesty but not this closure unless its exact blocker is visible.

**Cheapest falsification:** direct Authority checks, fixed four-leg fixtures, partial-acquisition
remediation tests, one deterministic full business simulation, and at most one bounded public snapshot.

## Change declarations

**Market/Decision input contract change:** current-session four-leg public facts replace the rolling
0–72h single-option input object.

**Decision Policy change:** one fixed `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1` Policy replaces the V2
single-side three-Policy chain.

**Outcome/evaluation contract change:** Decision, acquisition conversion, partial-risk remediation,
full-condor economics, short-risk-flat, terminality, and eligibility are separate facts.

**Stage/authorization change:** isolated local rebuild and bounded public read-only validation only;
no deployment, private API, capital, legacy-root access, migration, qualification, or Edge claim.

## Scope

**In:** root Authority and task governance; Pro candidate source; acquisition remediation and
four-leg coherence; new-product tests; audited CI, design tokens, and read-only Web presentation.

**Out:** old runtime compatibility, legacy Case translation, actual execution, private APIs,
automatic Policy promotion, ETH, Long Gamma, generic N-leg infrastructure, and process commissioning.

**Owning module:** `src/optimatrix`

## Validation

- focused tests: `.venv/bin/python -m pytest tests/test_lifecycle.py tests/test_product_funnel.py`;
- repository gate: `make check`;
- public observation: one `optimatrix-shadow snapshot` call after offline gates, or `UNVERIFIED` with
  the exact external error;
- no manifest, receipt, commissioning, or broad evidence package.

## Definition of done

The default product object is one current-session four-leg Iron Condor; normal carry is unreachable
from partial acquisition; the Workbench explains the same product and exact blocker; the legacy
single-side runtime and Policies are physically absent from the branch; before/after is recorded as
`0 / 1` to `1 / 1` canonical paths; focused and repository checks pass; and the remaining primary
live-market blocker is reported. Tests alone do not satisfy the task.

## Observed result

**After:** `1 / 1` canonical repository product paths now select and present one current-Session
four-leg Iron Condor; `0 / 1` selectable paths use the legacy single-side product identity.

**Blocker movement:** `WRONG_CANONICAL_STRATEGY_OBJECT` moved from `1 / 1` paths to `0 / 1`.
Partial short exposure is created as `EXIT_REQUIRED`, survives restart with the frozen remediation
duty, and is excluded from the `IRON_CONDOR_STRATEGY` Outcome population.

**Trader-visible result:** the installed CLI emits one canonical funnel and exports a static
four-leg `PUBLIC SHADOW - READ ONLY` Workbench whose browser performs no strategy calculation.

**Remaining primary live-market blocker:** `BOUNDED_PUBLIC_SNAPSHOT_REACHABILITY_UNVERIFIED`.
The task-authorized single public attempt ended with
`http.client.IncompleteRead(677343 bytes read)` while reading Deribit instruments. The source owner
now maps that transport failure to `DeribitSourceError` under a deterministic fixture, but the live
command was not retried because the one-attempt authorization was consumed.

**Supporting checks:** repository gate passed with 59 tests and 18/18 deterministic business
scenarios; editable install, wheel build, console entry point, and packaged static assets passed.
These checks support the observed product replacement; they are not themselves the product delta.
