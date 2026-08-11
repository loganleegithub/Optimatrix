# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_TYPED_ACTIVATION_PACKET_LIVE_VALIDATION`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_WITH_FOUR_RECOVERED_ADMITTED_ENTRIES`

**Live commands:** `CONTINUED_PUBLIC_ONLY_MONITORING`

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

Continued monitoring identified two `REMOTE_CONNECTION_CLOSED` transitions `613,931 ms` apart.
Deribit's official session contract requires `public/test` immediately after `test_request`; the
old application scheduled that response behind the synchronous business queue. This is now the
fixed transport blocker `ORDERED_BUSINESS_QUEUE_HEARTBEAT_TEST_RESPONSE_DELAY`.

The next session then reached `16` HIGH Episodes, `15` fully evaluable Underwriting Episodes, `6`
Candidates, and the first `2` admitted Shadow Cases. Both appeared in the API with non-empty
`shadow_entry_identity` and active Position projections. The following admission stopped
fail-closed because its Candidate lacked the activation packet required to open a Case. The Radar
Episode did own that immutable packet; composition incorrectly looked only in the mutable current
packet cache at the activation boundary. That first observed defect was
`ACTIVATION_PACKET_MUTABLE_PROJECTION_GAP`, not an economic or Policy blocker.

Code identity `3bb90768b43816700f3c0a9222e45a1c949264be` repaired that exact-boundary lookup and moved the
Deribit `public/test` response below the business queue. Its checked recovery start restored the two
existing Entries as GAPPED and subsequently opened two additional admitted Shadow Cases. During
the first `462` seconds of the intended ten-minute transport gate, the runtime remained `128/128`,
reported zero reconnects and zero protocol gaps, and kept observed queue lag below `936 ms`. The
gate was then interrupted by the same fail-closed message, so it is not a completed ten-minute
heartbeat proof.

The repeated run exposed the broader root cause
`EPISODE_ACTIVATION_PACKET_TYPED_HANDOFF_GAP`: an Episode can activate before any complete
Underwriting scope exists. In that path there is no activation-boundary Underwriting fact for the
owner to freeze, and the later first projection carried only the current score packet rather than
the Episode-owned activation packet. Selecting the Episode packet only at the activation boundary
therefore fixed one lookup but not the ownership handoff.

The bounded repair carries the immutable activation packet on every current Episode-owned atomic
snapshot and transient Underwriting fact until the owner validates and freezes it. A retired scope
clears that packet together with its Episode anchor. The current packet is still recomputed at the
current causal boundary, and schema-v5 Case validation is unchanged and remains fail-closed.

The official policy-aware Case reader now validates `4` admitted Cases and returns all four as
recoverable active Entries. All latest Segments were closed `CENSORED_AT_FAILURE`; two original
Entries are `GAPPED` with one prior recovery and the two Entries opened by code identity `3bb9076`
remain `CONTINUOUS`. No Outcome was fabricated and no Case was copied, rewritten, migrated, or
deleted. One checked recovery cutover is authorized after direct and repository gates pass; it must
reuse the stable root and open truthful GAPPED Segments for all four Entries.

Code identity `2739ad26745aca2884ed56f296b8d4d3d07ff9cc` passed the direct and full repository gates,
then performed that checked recovery cutover. Workbench publishes runtime identity
`sha256:9a6d7f937d08118eb13c15e4dd511d67c8b1c8232b2c69560bf8d402fb377688` as
`RUNNING/CURRENT`, `KNOWN_COMPLETE`, and `128/128`, with four Shadow Entry rows and four Position
rows. The official reader independently validates all four latest Segments as `OPEN` under that
runtime identity. The repaired runtime crossed the former approximately `462`-second packet-failure
point without reproducing the error.

At connection age approximately `601` seconds, Deribit then normally closed the public WebSocket.
The reducer recorded one exact `REMOTE_CONNECTION_CLOSED` session incident, retired current truth,
and automatically established session epoch `2`; the next observed frame was again
`RUNNING/CURRENT`, `KNOWN_COMPLETE`, and `128/128` with the same four Entry and Position identities.
This is neither the former packet-integrity failure nor a processing backlog. The intended
zero-reconnect heartbeat gate is therefore falsified as a product acceptance criterion under this
public-only boundary.

The official heartbeat contract is still enforced: `test_request` receives its transport-immediate
`public/test`, and matching responses are consumed below the business queue. A remote normal close
remains an external continuity loss and must stay truthfully GAPPED; suppressing that gap, adding a
second keepalive owner, or claiming continuous qualification would be incorrect. Acceptance is now
the bounded behavior actually owned by this repository: immediate heartbeat response, exact close
attribution, fail-closed retirement, automatic recovery, and no lost durable Case.

## Current online boundary

The Online Runtime on `127.0.0.1:8675` uses clean Draft PR #48 code identity
`2739ad26745aca2884ed56f296b8d4d3d07ff9cc` and runtime identity
`sha256:9a6d7f937d08118eb13c15e4dd511d67c8b1c8232b2c69560bf8d402fb377688`
from `/Users/logan/Optimatrix-runtime`. It owns the unchanged stable-root lease and publishes four
recovered admitted Entries from
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. The latest observed frame was
`RUNNING/CURRENT`, `KNOWN_COMPLETE`, `128/128`, with queue lag `564 ms`, market-event age
`1,089 ms`, reconnect count `1`, and session-gap count `1`.

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
