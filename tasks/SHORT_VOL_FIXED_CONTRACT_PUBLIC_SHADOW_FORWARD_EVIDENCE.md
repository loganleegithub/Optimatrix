# Task — SHORT_VOL_FIXED_CONTRACT_PUBLIC_SHADOW_FORWARD_EVIDENCE

**Status:** ACTIVE

**Task kind:** `EVIDENCE_ONLY`

**Runtime implementation:** FORBIDDEN

**Live commands:** REQUIRED

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contracts:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md) /
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md) /
[`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`](../docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md)

**Base commit:** `6207d59763e1aab7c455854169cd9dde6b0f940f`

**Base tree:** `31406d7cf3762ac286677497b52d0d0bbf463332`

**Target branch/PR:** `codex/short-vol-fixed-contract-public-shadow-runtime`; Draft PR #5

## Business closure

**Given:** the exact repaired fixed-contract public Shadow runtime has passed direct, focused,
full, scope, immutable-digest, and three independent reviews, while no production-public Shadow
interval or downstream forward evidence exists.

**When:** after the fee effective-time gate, one and only one result-independent production-public
invocation runs from a clean exact candidate whose local HEAD, tree, remote branch, PR head,
contracts, three-Policy chain, manifest, process argv/cwd, two new evidence directories, and
pre-bound start/cutoff/stop controls all match.

**Then:** the run terminates at its pre-bound stop or an earlier safety failure and leaves one
strictly readable Radar/downstream evidence set that reports exactly the natural public-market
facts, including honest zero and `UNKNOWN` results.

**Independent verification:** Codex re-reads the sealed manifest and both evidence directories on
the exact remote-equal candidate, re-runs strict current/complete readers and conservation, and
checks the terminal source, stop/failure path, duplicates, summaries, null rates, and zero
private/account/order/fill/capital activity.

**Valid zero/no-hit/UNKNOWN result:** zero natural anomaly/Candidate/Entry/Position/Outcome is a
valid result for this result-independent observation. It can prove that the bounded public runtime
and evidence lifecycle completed honestly; it cannot establish a usable cohort, strategy quality,
edge, profitability, or qualification. Missing, stale, incomplete, or contaminated evidence stays
`UNKNOWN`, never zero or calm.

**Upstream prerequisite:** exact accepted repair commit
`6207d59763e1aab7c455854169cd9dde6b0f940f` and its tree above.

## Change declarations

**Market/Decision input contract change:** `NONE` — source families, known-at/currentness,
official atomic combo meaning, request timing, and missingness are unchanged.

**Decision Policy change:** `NONE` — all three Policy bytes, identities, quantities, fees,
thresholds, admission decisions, Position actions, and hard-close total order are unchanged.

**Outcome/evaluation contract change:** `NONE` — Outcome states, causal-first exit, rejected path,
aligned pair, denominators, conservation, compatibility, and non-claims are unchanged.

**Stage/authorization change:** `APPROVED` — authorize exactly this one bounded
production-public Shadow evidence run after every preflight and effective-time gate. This grants no
private/account/order/fill/capital, execution, qualification, promotion, persistent deployment,
or second-run authority.

## Product operating behavior

One existing `radar_runtime observe-shadow` process owns the public Deribit WebSocket client, the
Radar reducer, fixed three-Policy Underwriting/Admission/Position owner, request-id allocator,
downstream writer, and result-independent stop controller. It may use only production-public
market methods, including the frozen positive-id `public/get_order_book` attempts. Component-leg
prices never replace an official combo and public quotes never become fills.

The process starts only after `2026-08-01T00:00:00Z`, when the immutable chain's
`FEE_TIER_CHANGES_EFFECTIVE_2026-08-01` schedule is in force. Its manifest pre-binds runtime start,
enrollment cutoff exactly 30 minutes after runtime start, and final stop exactly 60 minutes after
runtime start. The stop does not depend on anomaly, Candidate, Entry, Position, Outcome, PnL,
coverage, or likelihood of passing. Emergency stop remains safety-only.

No standalone market probe, synthetic event, replay, Policy change, quiet-book retry, second
process, or second live invocation is authorized. A preflight or runtime failure is recorded and
not retried under this task. Later natural subscription facts may only follow the already frozen
runtime semantics.

## Validation harness

Before the process exists, verify a clean exact candidate and fresh remote ref, run focused and
full checks, validate the manifest bytes with the repository reader, and prove both planned
evidence directories are absolute, external to the repository, mutually non-overlapping, and do
not exist. The manifest is created only after the activation commit is remotely visible and binds
that exact commit/tree/ref and the actual process argv/cwd.

After the result-independent terminal, validate both summaries and all objects using the exact
repository readers. Inspect writer/reader round trips, duplicate and orphan rejection, Admission
and post-CLOSE terminal matrices, `UNKNOWN`/null/zero denominators, natural stop/failure
censoring, Outcome/conservation, and Radar regressions. Duration is only the observation control;
it does not become product cadence, opportunity identity, or holding duration.

## Evidence boundary

**Proves:** one exact remotely bound fixed-contract runtime completed or truthfully failed one
pre-registered production-public interval; its public source, control, Radar, downstream,
terminal, and conservation evidence is internally strict for the facts actually observed.

**Does not prove:** a natural anomaly, Candidate, Entry, Position, close opportunity, mature
Outcome, usable cohort, market completeness outside the interval, indefinite uptime, Policy
quality, edge, profitability, fillability, account fees, actual exposure, execution,
qualification, promotion, or persistent deployment.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | REQUIRED |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | REQUIRED |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE / FORBIDDEN |

## Scope

**In:** one activation authority transition; one post-publication exact manifest; one bounded
production-public Shadow invocation; the existing Radar/downstream durable evidence; exact reader,
conservation, terminal, Git, remote, PR-head, and zero-private verification; one final terminal
record and truthful limitations.

**Out:** runtime/package/schema changes, contract or Policy changes, dependencies, locks, replay,
synthetic events, Policy tuning, private/account methods, credentials, balances, margin, positions,
orders, fills, settlement, capital, execution, qualification, promotion, persistent service, a
second run, `main`, merge, rebase, force-push, and history rewriting.

**Owning module/artifact:** permission routing in `CURRENT_STAGE.md`; external exact manifest,
Radar evidence directory, downstream evidence directory, log, and final terminal record. Runtime
source is read-only.

**Exact allowed files:**

```text
README.md
docs/authority/CURRENT_STAGE.md
docs/authority/SYSTEM_ARCHITECTURE.md
tasks/SHORT_VOL_FIXED_CONTRACT_PUBLIC_SHADOW_FORWARD_EVIDENCE.md
tasks/SHORT_VOL_SHADOW_ATTEMPT_EVIDENCE_INTEGRITY.md
tests/test_authority_and_architecture.py
```

## Contract

**Inputs and known-at rule:** exact public events known at or before each decision
`capture_seq`; outcome facts strictly after Entry; currentness, frontier, continuity, official
combo, and attempt rules are unchanged. No historical atomic event refreshes admission.

**Durable output and identity:** one exact external manifest plus repository-owned Radar summary
and downstream envelopes/objects/summaries, all bound to the post-publication candidate,
runtime/clock, contracts, Policies, absolute directories, causal boundaries, and terminal source.

**Missing/invalid/UNKNOWN semantics:** any pre-run identity/path/digest/remote/cleanliness/time
failure blocks startup. Runtime missingness remains `UNKNOWN`. A process failure uses the frozen
failure terminal and censoring path; partial bytes are not promoted to complete evidence.

**Persisted meaning and compatibility:** `COMPATIBLE`; no content schema, unit, identity formula,
reader, Policy, or accepted business meaning changes.

**Business denominators:** unchanged contract-defined Candidate, admission, Entry, Position,
opportunity, Outcome, pair, and cohort units. Zero or unknown denominators serialize rates as
`null`, never `0`; runtime duration and file counts are not business denominators.

## Acceptance

### Direct behavior

1. The post-publication candidate commit/tree equals local HEAD, remote tracking, fresh
   `ls-remote`, and Draft PR #5 head; the worktree is clean and all six immutable identities match.
2. The manifest binds exact argv/cwd/ref/candidate, 30-minute cutoff, 60-minute result-independent
   stop, forbidden capabilities, and two distinct new external directories; malformed or stale
   state fails before Deribit I/O.
3. Exactly one live process starts after the effective-time gate and stops without result-based
   extension or retry. Clean stop and failure both preserve terminal evidence.
4. Strict readers accept the final complete set, conservation is `MET`, all duplicates/orphans and
   impossible attempt/Outcome relations remain rejected, and `UNKNOWN`/null/zero remain truthful.
5. Network and evidence inspection finds zero private/account/order/fill/capital activity.

### Required commands

- `make sync`
- focused tests: authority, Shadow preflight/manifest/runtime, complete downstream evidence,
  Underwriting/Position owner, and Radar regressions
- `make check`
- `git diff --check`
- production-public command: exactly one `.venv/bin/python -m radar_runtime observe-shadow`
  invocation with the manifest and Radar evidence directory frozen below
- independent recomputation or reconstruction command: strict repository readers only; replay and
  synthetic reconstruction are forbidden

### Real evidence

**Required:** YES

**Environment and stopping condition:** production-public Deribit only. The manifest pre-binds
cutoff 30 minutes after runtime start and final stop 60 minutes after runtime start. A safety
failure may stop earlier. No market or strategy result may extend, shorten, retry, or select the
window.

**Required report:** for each activation or final authority-record publication, exact commit, tree,
parent, remote branch tip, full compare range, and tests; manifest identity/path/hash;
runtime/clock and actual start/cutoff/stop/failure boundaries; Radar/downstream summary and ordered
file hashes; counts/rates/conservation; all `UNKNOWN`/null/zero and natural business objects;
reader/round-trip results; terminal disposition/source; remote equality; limitations and
non-claims; zero private/account/order/fill/capital activity.

**Private API:** FORBIDDEN.

## Frozen external paths

All five exact targets must be absent when preparation begins. After the activation commit is
remotely verified, Codex creates and validates the manifest before the one process invocation;
both evidence directories, the process log, and the terminal record must still be absent then. The
runtime exclusively creates both evidence directories, the runner creates the log for that sole
invocation, and Codex creates the terminal record only after the process reaches a terminal.

- Manifest: `/Users/logan/Optimatrix-shadow/manifests/public-shadow-forward-001.json`
- Downstream evidence:
  `/Users/logan/Optimatrix-shadow/evidence/public-shadow-forward-001-downstream`
- Radar evidence: `/Users/logan/Optimatrix-shadow/evidence/public-shadow-forward-001-radar`
- Process log: `/Users/logan/Optimatrix-shadow/logs/public-shadow-forward-001.log`
- Final terminal record:
  `/Users/logan/Optimatrix-shadow/receipts/public-shadow-forward-001-terminal-record.json`

## Immutable identities

- Radar contract:
  `sha256:b9733ad0c90837338b88fb5b6eb66ad8eed448cce6372a3f527988395087b3fe`
- Underwriting/Position contract:
  `sha256:9cbaecf57fb1db0dedf782a4ab002b655e43319a1ad7c5880db3d7b4682d4b03`
- Outcome/cohort contract:
  `sha256:61a032fe0fe265d66a38bcbb1a3c8498409664fedbda2c8bd0a245180581a695`
- Radar Policy:
  `sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4`
- Underwriting Policy:
  `sha256:be056d7fad71668954103e1e383372c3b03db9b27b8d03ce0a030d39285629af`
- Position Policy:
  `sha256:498a298be50cb356f43886ae7ba02d1f6da065233ae9b2b52e9a230cf7f9c439`

## Artifacts and delivery report

**Artifact paths and digests:** the five frozen external paths above. The final report records
SHA-256 for every authoritative artifact and an ordered absolute-path file manifest. An artifact
does not amend authority, contract, Policy, or acceptance.

**Policy/contract identities:** the six immutable identities above must remain byte-identical.

**Commit/PR:** append-only activation and later final authority-record commits on the existing task
branch and Draft PR #5. Before each publication, the remote branch tip must equal that
publication's expected parent. Prefer connector Git Database `create_blob` / `create_tree` /
`create_commit` / `update_ref(force=false)` actions; local `git push` is fallback only if those
write actions are unavailable. After each publication, report the exact commit, tree, parent,
remote branch tip, full compare range, and tests. The terminal record itself stays at its frozen
external path. The activation file cannot contain its own future commit hash; the external
manifest binds it only after publication. No new branch, merge, rebase, or history rewrite.

**Unknowns and non-claims:** all natural market/business results are unknown until the run. Even a
complete non-zero cohort is not qualification; zero/no-hit is not failure of the bounded runtime
but leaves business usefulness unproved. No account, fill, exposure, PnL, execution, promotion, or
deployment claim is permitted.

## Definition of done

One and only one remotely bound post-effective-time process reaches its frozen clean-stop or
truthful failure terminal; strict readers and conservation accept exactly what exists; manifest,
evidence, log, hashes, terminal record, Git, remote, and PR head are independently reconciled; no
forbidden capability or second run occurred; and the final authority transition records only the
result actually proved.
