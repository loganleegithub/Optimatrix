# Optimatrix Current Stage

**Status:** D1 AI LAB SESSION REVIEW — IMPLEMENTED OFFLINE; REAL SESSION UNVERIFIED

**Current maturity:** `D1_AI_LAB_SESSION_REVIEW`

**Product Authority:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Frozen Base Policy identity:**
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Current task kind:** `NONE`

**Sole authorized closure:** `NONE`

## Current permissions

No validation, deployment, or live-action permission is implied by the implemented maturity.

**Offline checks and simulation:** existing deterministic tests and synthetic demonstrations only;
opening a real ObservationLedger requires a new exact read-only validation task

**Public market calls:** `NONE_AUTHORIZED`

**Stable ObservationLedger root:** the existing
`/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2` remains owned by
the deployed B3 runtime. AI Lab has not opened or mutated it.

**Stable CaseJournal root:** the same v2 root remains owned by B3. AI Lab is not a CaseJournal writer
and has not opened or mutated it.

**Continuous runtime:** the existing B3 launchd job remains unchanged. AI Lab adds no daemon,
scheduler, listener, runtime owner, restart, replacement, or deployment.

**AI Lab durable root:** default
`/Users/logan/Library/Application Support/Optimatrix/ai-lab`; it is a separate append-only research
root and must never be used as an ObservationLedger, CaseJournal, account, or runtime root

**Codex CLI:** no real invocation is currently authorized. The implemented optional adapter uses a
bounded deterministic fact bundle, `--ephemeral`, `--sandbox read-only`, a temporary working
directory, and a strict output schema; Codex cannot own the Session verdict or promotion.

**Private read-only account permission:** `NONE`

**Orders, capital, and deployment:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Implemented D1 truth

- `AI Lab` now lives inside the modular monolith at `src/optimatrix/ai_lab/`; `Challenger` remains
  only the role name of a later Base-versus-Challenger experiment.
- Every selected ended Session is reconstructed against its exact `96` pre-registered Windows.
  Missing Decision, causal observation, continuous future path, or matching official settlement
  keeps the Session `UNKNOWN`.
- The content-addressed `UNFILTERED_CONDOR` control uses decision-time public Shadow facts and
  preserves legal four-leg geometry, full-amount price evaluability, standard Combo fees, boundary
  loss, fee-burden, and Session USD-risk limits. It removes only the named strategy filters.
- Complete zero-success evidence returns `NO_OPPORTUNITY` and stops before Codex, even when Base had
  emitted an unconfirmed Candidate. A positive control result missed by Base returns
  `MISSED_OPPORTUNITY` with actual, threshold, unit, and signed margin where quantifiable.
- Only `BASE_FOUND_OPPORTUNITY` with complete `96/96` evidence can unlock a separately frozen
  Challenger comparison. Actual-path experiments fail closed without matching eligible Session
  Review identities, Base Policy identity, and Window coverage.
- Session Reviews and optional Codex analyses use separate append-only hash chains. Memory exposes
  recurring verdicts, Base blockers, and falsifiable hypothesis keys; it does not retain raw chat,
  self-modify code or Policy, or promote anything automatically.
- JSON and Chinese trader-readable Markdown reports show the Session verdict, exact opportunity
  definition, evidence funnel, every Window, successful structures, short-strike breaches,
  quantitative Base attribution, prior-memory summary, and permanent evidence limits.
- The Codex prompt is bounded to all `96` Window summaries, deterministic gate aggregates, and at
  most `48` representative opportunities. The complete opportunity population remains in the
  sealed Review/report rather than being silently discarded.

## Verification state

- `36` direct AI Lab tests cover the four verdict branches, incomplete evidence, Base false
  positives stopping as no-opportunity, quantitative missed-opportunity attribution, append-only
  tamper detection, path isolation, bounded/cited Codex output, actual-path experiment gating, and
  CLI-to-report closure.
- Repository gate: `272 passed`, `52 subtests passed`, and all `8` deterministic business scenarios
  passed, with Ruff format, Ruff lint, strict mypy, and compileall green.
- `real_session_review=NOT_YET_MEASURED`: no production ObservationLedger Session has been opened or
  adjudicated by AI Lab.
- `real_codex_analysis=NOT_YET_RUN`: the Codex adapter is verified only with a fake process boundary.
- `B3_PIPELINE_CAPABILITY_ACCEPTED` remains prior mechanism evidence; this branch neither changes
  nor re-accepts it. `natural_chain=NOT_YET_OBSERVED`,
  `policy_reachability=COMPLETED_SESSION_LOCAL_RESPONSIBILITY_MEASURED`,
  `policy_qualification=NONE`, and `edge_claim=NONE` remain unchanged evidence boundaries.
- The existing Workbench assets and schema remain untouched. AI Lab's visible surface is its
  content-addressed Markdown/JSON report until a separate UI task is authorized.

**Primary blocker:** `FIRST_REAL_ENDED_SESSION_AI_LAB_REVIEW_UNVERIFIED` — implementation and
synthetic mechanism closure do not establish that the existing production Ledger contains one
complete `96/96` Session suitable for this adjudication. A later validation-only task may open one
exact root read-only, emit its first report under the separate AI Lab root, and report `UNKNOWN`
rather than infer missing facts.
