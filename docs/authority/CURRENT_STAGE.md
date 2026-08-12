# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `NONE`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_LIFECYCLE_V3_AND_SHADOW_RISK_BOOK_LIVE_CURRENT`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_8765_CODE_4E844F0EE6DD9C40574F7C9BA744B729E16543ED`

**Live commands:** `NONE_CONSUMED`

**Sole authorized closure:** `NONE`

## Current online boundary

The sole Online Runtime serves `127.0.0.1:8765` from the clean deployment checkout at code
identity `4e844f0ee6dd9c40574f7c9ba744b729e16543ed` and runtime identity
`sha256:f2d94165c94cabf14690fecd794ec9389aefdcc2b42ef4bd702c873e2f3eabd7`.
Its Python import provenance resolves `radar_runtime`, `short_vol_underwriting`, and
`options_domain` from `/Users/logan/Optimatrix-runtime`. One process owns the loopback listener and
the stable Case root `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`.

PR `#51` merged the version-3 Position lifecycle backend and Shadow expiry-risk Workbench. PR
`#52` corrected the one live browser-gate contradiction between an immutable first-CLOSE reason
and a terminal Position's current responsibility. Both topic branches were deleted locally and
remotely. The application code at `4e844f0` passed focused lifecycle/Workbench tests, `make check`
with 777 tests, and both GitHub repository gates.

Before the first cutover, the stable root held 91 schema-v5 Case directories, 68 immutable
first-CLOSE records, 36 Outcome files, and 646 total files. Every one of those 646 files remained
byte-exact across both cutovers. The 764 files present before the display-only repair cutover also
remained byte-exact. Clean stop and recovery only appended contract-authorized Segment and Outcome
facts; the final accepted observation contained 828 files. No Case was migrated, copied, deleted,
relabeled, or rewritten.

## Accepted lifecycle result

The official version-3 reader accepted all 91 Cases. The final active report derived 36
terminal-economic Cases, 15 strict terminal-sample Cases, 32 pending-open Cases, 67 gapped Cases,
8 inherited incomplete-unclean Cases, and 16 observation-unavailable legacy Cases. Fifteen
version-3 `EXITED_KNOWN/MARKET_EXIT` Outcomes were naturally produced from public Deribit facts;
all retained their terminal fact boundary, exit-acquisition sample identity, selected-exit
identity, and independently recomputable economics.

The strict exit-acquisition Cohort remains zero because these recovered historical first-CLOSE
records did not declare the future acquisition profile. The runtime does not backfill that missing
history or turn terminal-sample integrity into acquisition-window eligibility. Qualification
remains offline and window-specific.

The final current Workbench frame reported schema 7, `RUNNING / CURRENT / ready`,
`KNOWN_COMPLETE 130 / 130`, zero reconnects, zero session gaps, 20 formal Shadow holdings, and 20
continuing exit responsibilities. The active current frame contained no terminal Shadow row;
terminal-row copy is therefore accepted by the executable browser-state regression that proves a
pending source-gap row still says `当前仍承担退出责任` while a terminal row says `持仓责任已终结`.

## Accepted browser result

All six declared GET and HEAD routes returned 200. Served HTML, JavaScript, and CSS matched the
deployment checkout byte-for-byte. Radar Both/Put/Call and ACTIVE filtering, signal selection,
evidence disclosure, the four-channel product matrix, Shadow responsibility/type/expiry/search
filters, exact row/detail association, day/night state, desktop layout, and the 800px responsive
drawer completed without an application console warning or error.

At 800 × 1058, the page had no horizontal overflow, the 940px risk table remained inside its
bounded scroller, and the detail drawer began below the fixed product chrome. Twelve browser
samples over two automatic-refresh windows stayed `RUNNING / CURRENT`, kept connection warnings
hidden, and preserved the current Radar and Shadow rows. Observed queue-processing lag remained
below its 5,000ms threshold and reached approximately 1.3 seconds at maximum. This bounded gate
does not guarantee future uptime or latency.

## Product truth and non-claims

The sole Online Runtime product remains `INVERSE_BTC_V1` under the unchanged fixed Radar,
Underwriting, and Position Policy identities. The current Position Policy identity and all nine
frozen predicate thresholds remain unchanged. No product, schema family, Case root, record kind,
market source, order/fill/account boundary, or private permission changed.

Permission remains `PUBLIC_SHADOW`: production public facts and counterfactual economics only. A
public book or delivery price is not an order, fill, settlement action, actual position, account
PnL, or capital exposure. `PENDING`, `GAPPED`, a responsive Workbench, green tests, or a recovered
Case do not qualify a Policy or prove terminal economics. All task-scoped stop, start, source,
reader, API, and browser commands are consumed. A future restart, live probe, Policy change, or new
roadmap channel requires a new active task and explicit permission update.
