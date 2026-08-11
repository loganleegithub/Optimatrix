# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_INTERRUPTED_TERMINAL_RETIREMENT_REPAIR_LIVE_MONITORING`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_REPAIRED_INTERRUPTED_TERMINAL_RETIREMENT`

**Live commands:** `CONTINUED_BOUNDED_MONITORING`

**Sole authorized closure:**
[`INVERSE_BTC_SHORT_VOL_V2_INDEX_GRID_PHASE_REPAIR`](../../tasks/INVERSE_BTC_SHORT_VOL_V2_INDEX_GRID_PHASE_REPAIR.md)

## Active repair authorization

The source-grid repairs in Draft PR #48 removed both the rotating five-minute phase and the
trusted-time-ahead-of-source race without changing a Policy artifact. Running code identity
`17d94dafb8eb6fb0044df100de3f10b4f8fca24b` subsequently allowed eligible HIGH leaders in the
6-to-24-hour and 24-to-72-hour bands to reach confirmation `2/3` at their Policy-owned 150-second
and 300-second separations.

Live fixed-attribution then established the next blocker. Three consecutive scheduled history
refresh cycles produced processing-lag peaks of `3,045 ms`, `4,032 ms`, and `5,003 ms`. At the
threshold-crossing frame, `queue_lag_currentness_active=true`, the known HIGH leader became
`QUEUE_LAG_CURRENTNESS`, its confirmation changed `2 → 0`, and the runtime-local `CORE_UNKNOWN`
reset count increased by `13`. The session epoch remained `1`, reconnect and protocol-gap counts
remained zero, and current truth recovered about half a second later. The fixed cause is
`ORDERED_QUEUE_LAG_DESTRUCTIVE_PRECONFIRMATION_RESET`: an ordered reducer backlog correctly paused
current evaluation but incorrectly erased earlier accepted observations.

The repair keeps every lagged frame `UNKNOWN`, globally degrades leader coverage, counts no
observation, and permits no Episode, Underwriting admission, Candidate, or Shadow Case. Only an
inactive pre-confirmation tracker retains its previously accepted leader, score band, and count.
After catch-up, the current score is recomputed; a different leader, band, scope, or persistent core
loss still resets normally, and an already-active Episode remains fail-closed. No score threshold,
confirmation count, separation, TTE/Delta rule, Underwriting economics, Position rule, Case schema,
or Policy identity changes.

The now-stopped code identity `6fbcf9fbf4237d6685cbf7ae986dc4dfa4dfee76` ran that repair.
Its first three observed HIGH Episodes reached Underwriting and were known non-Candidates because
entry credit did not exceed the fixed future-cost reserve. One separately selected LOW research
Control then opened normally and exposed `OFFLINE_CASE_DIRECTORY_IDENTITY_MISPARSE`: its store-owned
directory is the bare 64-hex digest, while `report-v2-cases` duplicated the directory scan and
incorrectly required the directory name itself to be a prefixed `sha256:` identity. The durable Case
is valid; the reader boundary was wrong.

The bounded closure makes the CaseStore's directory-name-to-Case-identity conversion public and
reuses it in the offline report. It changes no online decision, Policy, Case bytes, or stable root
and requires no runtime restart. Continued observation remains production-public Shadow only and
cannot claim Edge, profitability, an order, a fill, or actual exposure. The bounded implementation
remains [Draft PR
#48](https://github.com/loganleegithub/Optimatrix/pull/48).

Continued observation then exercised the repaired currentness boundary at `5,011 ms`: the frame was
truthfully `STALE/UNKNOWN`, accepted no observation or admission, recovered `128/128` about one
second later, and added zero destructive `CORE_UNKNOWN` pre-confirmation resets. The cumulative
count then reached seven HIGH Episodes that were fully evaluable by Underwriting; all seven were
known non-Candidates at the fixed future-cost reserve.

Direct policy-aware validation of the current Workbench score-packet projection exposed
`LOSSY_DECIMAL_PACKET_SERIALIZATION`. Baseline path shares are calculated at 50-digit precision,
but score-packet `_decimal_text` called `Decimal.normalize()` under the ambient 28-digit context.
The serialized raw D input could therefore lose trailing significant digits while the stored D
result retained the pre-serialization calculation, producing a one-unit final-decimal mismatch on
reader recomputation. The online score was correct, but a future written Case could become
unreadable after JSON restoration. The repair serializes the existing Decimal coefficient in
fixed-point form without changing calculation, score, band, Policy, schema, or threshold.

The ninth HIGH Episode exercised the defect while opening a selected no-trade Control. The
CaseStore rejected the packet before publication, the runtime converted that durable-boundary
failure to `ShadowRuntimeIntegrityError`, and the process exited fail-closed. No second Case,
Candidate, admitted Entry, or Position was written. The existing Control is still readable and is
truthfully `INCOMPLETE_UNCLEAN_EXIT` while the runtime is stopped.

The one authorized clean start completed on `127.0.0.1:8675` from the checked repair commit, reusing
the unchanged stable Case repository. No Case was copied, rewritten, migrated, or deleted.
The first post-repair write on the former fatal path published decision Control
`sha256:a9e10899eb7b4f2b8e923d77c23ca6b1d6b1caf6c0b52b9b465177fb510c42cf`; the official
policy-aware Case reader restored it as `OPEN` under the new code/runtime identities. It is an
ABSTAIN research Control, not an admitted Shadow Entry, but proves the Decimal packet defect no
longer prevents durable Case publication.

Continued fixed-attribution observation then reached `50` distinct HIGH Episodes and `36`
fully evaluable Underwriting Episodes. The fiftieth Episode produced the runtime's first canonical
Candidate. Its admission refresh became `KNOWN_INVALIDATED_BEFORE_REFRESH`, correctly emitted no
Entry, Position, or durable admitted Case, but the service then exited with
`ended Radar episode still owns an active Candidate`. The exact owner-state reproduction proved
`TERMINAL_ATTEMPT_CANDIDATE_RETIREMENT_GAP`: when the admission attempt was already terminal while
the Candidate lifecycle was still `VALID`, Episode retirement skipped Candidate invalidation
because the attempt could not transition a second time, then failed its bounded-owner invariant.
This is a lifecycle cleanup defect, not a Policy, credit-threshold, score, or market-data failure.

The bounded repair emits an admission terminal only when the attempt first transitions, but always
invalidates a still-valid Candidate when its Episode ends. The pre-repair regression reproduces the
same fatal invariant and the repaired owner retires the Candidate exactly once. No admission rule,
paired-witness requirement, Case schema, or Policy identity changes. The stopped stable repository
contains zero admitted Shadow trades; no Case was created, rewritten, migrated, or deleted by the
failed Candidate.

The authorized clean cutover then started code identity
`21128eb6807cd1403b3b458da1c418c16dcdf099` from the non-temporary checkout
`/Users/logan/Optimatrix-runtime`, reusing the unchanged stable Case repository. The repaired
runtime activated and subsequently retired its first HIGH Episode without an exception or retained
Candidate; that Episode truthfully stopped at `NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE`. This proves the
observed retirement failure is no longer reproduced, but it does not prove future admission,
Policy quality, or uptime.

Continued observation reached seven HIGH Episodes and two simultaneous Candidates before runtime
failure handling retired the current epoch. Candidate cleanup again raised
`ended Radar episode still owns an active Candidate`. The broader reproduction established
`INTERRUPTED_TERMINAL_CANDIDATE_RETIREMENT_GAP`: a prior owner transition can terminalize a
Candidate and then fail before `_finish_transition()` removes it. The next Episode-retirement
transition clears its pending-retirement set, sees a lifecycle that is already non-`VALID`, emits no
duplicate invalidation, but previously failed to remove the terminal Candidate from the active map.
That cleanup exception also masked the earlier failure which initiated reconnect, so the exact
initiating exception remains `UNKNOWN` for the stopped run.

The bounded follow-up marks every Candidate owned by the ending Episode for map retirement after
terminalization, including an already-terminal record left by an interrupted transition. It does
not change admission or Case truth, emit a duplicate terminal, or suppress the initiating failure;
if that earlier failure recurs, the runtime can now report it directly after cleanup.

The authorized follow-up cutover started code identity
`6093cd0825cf6c7352d30270ecb2c5742c81182a`. The repaired runtime reproduced the material pressure
case: six HIGH Episodes became fully Underwriting-evaluable, two became Candidates, and a real
transport reconnect then retired the epoch. Both Candidates became
`ADMISSION_KNOWN_INVALIDATED_BEFORE_REFRESH`, the active Candidate map returned to zero, and the
service recovered to `CURRENT` and `128/128` without the cleanup invariant or another process exit.
The initiating event is therefore identified as a transport reconnect for this new run; the prior
stopped run's masked initiating exception remains unknowable.

## Current online boundary

The current Online Runtime serves `127.0.0.1:8675` from clean Draft PR #48 code identity
`6093cd0825cf6c7352d30270ecb2c5742c81182a` in the non-temporary checkout
`/Users/logan/Optimatrix-runtime`. Its runtime identity is
`sha256:506d0e32ae3e276704fc3dbee85afddbaefd17170e84e02a4ff94895ffcf0173`.
It owns the single-instance lease for the unchanged stable Case repository
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`; no Case root was copied, migrated,
replaced, or deleted during the cutover.

The first accepted live frame reported health, readiness, `RUNNING`, `CURRENT`, `KNOWN_COMPLETE`,
`128/128` current Radar coverage, zero reconnects, and zero protocol gaps. Every projected score
packet in continued one-second sampling passed exact Policy-aware recomputation. The repaired
runtime has observed six fully Underwriting-evaluable HIGH Episodes and two Candidates. A transport
reconnect invalidated both before refresh; the runtime recovered automatically and opened zero
admitted Shadow Entry or Position.
The official active-runtime Case report reads all 13 prior schema-v5 Cases: 11 are non-admitted
Radar-score-band Controls and two are selected-Underwriting decision Controls, all classified
`INCOMPLETE_UNCLEAN_EXIT` across their former runtime boundaries. Admitted Shadow count remains
zero. These are bounded observations, not Policy-quality or future-frequency claims.

Subsequent live fixed attribution crossed queue currentness at `5,005 ms`. The crossing frame was
`UNKNOWN/0`, added no `CORE_UNKNOWN` reset, and recovered to `KNOWN_COMPLETE/128` about 220 ms later;
two unchanged HIGH buckets retained and advanced to confirmation `2/3`. A separate real
`TRANSPORT_READ_FAILURE` changed session epoch `1 → 2`, reconnect and protocol-gap counts `0 → 1`,
and correctly added 13 `CORE_UNKNOWN` resets before automatic recovery. These two causes are not
conflated. Seven HIGH Episodes reached fully evaluable Underwriting after the clean start; all seven
were known non-Candidates first blocked by `CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE`. Admitted Shadow
count remains zero.

## Current product truth

The sole Online Runtime product is `INVERSE_BTC_V1`. Its channel is
`INVERSE_BTC_SHORT_VOL_V2`, Workbench document schema is `7`, and durable Shadow Case family is
schema v5. It consumes Deribit production public BTC options and `btc_usd`, uses BTC-native
premium/fees/settlement/PnL, and labels current valuation as `USD_EQUIVALENT`.

There is no product selector, fallback product, compatibility profile, alternate online schema, or
in-process Policy switch. The repository contains only the three fixed V2 Inverse Policy
artifacts:

```text
product spec identity:        sha256:a7880d3a0b3da12f74438b292ed49d7c034e683d2e1654037229c62474127131
Radar Policy identity:        sha256:fd604c22b6f4a111955f432fe09647e93c38e914e81c4045905ca79b935bdc9d
Underwriting Policy identity: sha256:933dce3e4d9736b465aaca95a352ef8c3196592bfef04cf1f958442afe0f5e7d
Position Policy identity:     sha256:8a00bacc13f5f3f2407ea3ff5060464e12d93c3f336f9d1f9d750a0621fa0ffe
```

The V2 score is an expert ordinal opportunity-ranking hypothesis, not a probability, oracle,
expected return, Edge, or profitability claim. The component-book lifecycle is a public-book
counterfactual, not an order, fill, atomic quote, liquidity reservation, or actual position.

## Permission and non-claims

Permission remains `PUBLIC_SHADOW`: no credential, account, balance, margin, order, fill, capital,
settlement action, actual exposure, or private execution. The accepted smoke and green repository
checks do not establish future uptime, source freshness, fillability, qualification, Edge, or
profitability.

Only continued public-only monitoring declared above is authorized. Any extra restart, state-root
operation, Policy change, or roadmap-channel implementation requires a new explicit task and
permission update under the Delivery Contract.
