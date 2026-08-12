# Design QA — V2 Radar 强信号地图

## Evidence

- Source visual truth: `/Users/logan/.codex/generated_images/019fe4fd-c988-70e2-a10c-07420b474063/exec-956583eb-7f8b-47fb-953a-0e093e845dde.png`
- Browser-rendered implementation: `/private/tmp/optimatrix-radar-implementation-final2.png`
- Combined comparison: `/private/tmp/optimatrix-radar-comparison-final.png`
- Responsive focused capture: `/private/tmp/optimatrix-radar-narrow-pass2.png`
- Source pixels: 1254 × 1254; normalized to 1200 × 1200 for comparison.
- Implementation pixels / CSS viewport: 1200 × 1200 at device scale factor 1.
- Responsive viewport: 800 × 1200.
- State: dark theme, Both, all strong signals, BTC-13AUG26-63000-P selected, concise evidence inspector open.

## Full-view comparison

The final implementation preserves the selected reference hierarchy: system navigation and Runtime strip at the head, a single sparse expiry-by-strike signal map as the primary surface, a selected-signal inspector over the map, and system-context navigation at the tail. The implementation intentionally omits the mock's FWD line because schema 7 exposes no server-owned expiry-level forward for this view. It also reports the exact 4 strong signals against the 128-contract denominator rather than reproducing inconsistent decorative fixture counts.

Required fidelity surfaces:

- Fonts and typography: system sans stack, weights, line height, compact metadata, and strong score hierarchy are visually aligned; long Runtime facts truncate instead of wrapping the head.
- Spacing and layout rhythm: 1:1 frame, four expiry topology lanes, full-height map, floating inspector, toolbar, and footer align without viewport overflow.
- Colors and visual tokens: dark navy surfaces, purple selection/ACTIVE, amber CONFIRMING, green Runtime health, borders, and elevation match the selected direction. The explicit day theme remains available for strong-light use.
- Image quality and assets: this is a data UI with no source photography, illustration, or logo asset to reproduce. All visible marks are native UI states; no raster placeholder is used.
- Copy and content: wording is reduced to trader-facing V2 score, state, expiry/TTE, Delta bucket, Premium Strength, Risk Quality, and the non-trading boundary. Full owner evidence remains behind disclosure.

## Focused region comparison

The selected marker and inspector were compared in the combined 1200 × 1200 image. The responsive drawer was separately captured at 800 × 1200 because its header and modal boundary are not readable from the full-view comparison. The final narrow capture shows the complete header, identity, score facts, metrics, non-claim, evidence control, and close control below the fixed head/toolbars.

## Comparison history

1. Pass 1 findings:
   - [P1] The map grouped only expiries containing a strong signal, leaving a large unused lower region in a 1:1 viewport.
   - [P1] At 800 px width, the drawer began below the topbar but underneath the product toolbar, hiding its header.
   - State normalization: the first capture was in day mode while the selected source is night mode; this was a comparison-state mismatch, not a product defect.
2. Fixes:
   - Retained all current expiry/strike topology lanes while rendering markers only for the exact strong-signal subset; lanes now flex to occupy the map height.
   - Moved the narrow drawer and scrim below both the topbar and product toolbar.
   - Switched to the matching night state and selected the same ACTIVE/high-score signal state for final comparison.
3. Post-fix evidence:
   - `/private/tmp/optimatrix-radar-comparison-final.png`
   - `/private/tmp/optimatrix-radar-narrow-pass2.png`
   - No remaining actionable P0, P1, or P2 finding.

## Primary interactions tested

- Both / Put / Call filtering.
- ACTIVE-only toggle.
- Signal selection and desktop inspector close/reopen.
- Product matrix open/close with four product channels.
- Radar / Shadow navigation and truthful empty Shadow state.
- Full-evidence expand/collapse.
- Day / night theme switching.
- Responsive modal drawer, scrim, and close behavior at 800 px.
- Browser console warnings/errors checked: none.

## Follow-up polish

- [P3] The footer intentionally uses text-first navigation rather than the decorative icon medallions in the mock; an approved icon library could add those later without changing hierarchy.

final result: passed

---

# Design QA — Shadow 到期风险持仓簿

## Evidence

- Selected design direction: `/Users/logan/.codex/generated_images/019ff1a9-c227-7e21-98bd-ef4ecfd890a4/exec-02b69f21-c5d2-4cc0-b574-2f1b57f09e1c.png`
- Browser-rendered desktop implementation: `/private/tmp/optimatrix-design-qa/shadow-scheme2-desktop-final.png`
- Full-view combined comparison: `/private/tmp/optimatrix-design-qa/shadow-scheme2-comparison-final.png`
- Table-focused comparison: `/private/tmp/optimatrix-design-qa/shadow-scheme2-comparison-table-final.png`
- Inspector-focused comparison: `/private/tmp/optimatrix-design-qa/shadow-scheme2-comparison-inspector-final.png`
- Responsive list capture: `/private/tmp/optimatrix-design-qa/shadow-scheme2-narrow-list-final.png`
- Responsive detail capture: `/private/tmp/optimatrix-design-qa/shadow-scheme2-narrow-detail-final.png`
- Source visual and desktop implementation: 1487 × 1058 CSS pixels; responsive viewport: 800 × 1058.
- State: dark theme, Both, first current Shadow position selected, persistent inspector open.
- Data source: an isolated, read-only recovery projection built through `ShadowCaseStore`, `FixedContractShadowOwner`, and the production schema-7 projector. It exposes 21 admitted Shadow Entries and their persisted first-CLOSE facts without opening a Case Segment or mutating durable storage. Current BTC index is one fresh public display fact. This fixture is visual/business acceptance evidence, not a claim that the stable Runtime is healthy.
- Acceptance facts: 21 admitted Shadow Entries, 21 Positions carrying exit acquisition responsibility, 0 monitoring, 0 terminal Outcome, one current admitted expiry (13 AUG). The 12 Control Positions in the Case store remain outside this page.

## Visual fidelity and trader-first hierarchy

The selected “expiry risk book” direction is now reproduced at its owning layout boundaries: a 64 px product toolbar, 1050 px left risk book, 390 px persistent inspector, 40 px leading expiry band, 61 px data rows, and a nine-column trader scan. The table and inspector start at the same 182 px desktop baseline; the page has no horizontal overflow at 1487 × 1058.

The default page shows only what changes a trader decision: frozen spread identity, side, quantity, current index distance, TTE, first CLOSE trigger, present lifecycle responsibility, public close-economics availability, and next duty. The inspector keeps the reference's five-section sequence: structure economics, current risk, close responsibility, deadline, and terminal expectation.

Full Segment, Gap, Cohort, Entry, Position, and Outcome evidence remains available behind one disclosure. Nine raw exit predicates, Control research, underwriting candidates, and raw payloads do not compete with the trader’s default risk scan.

Required fidelity surfaces:

- Fonts and typography: the existing system sans stack, compact metadata hierarchy, 12–13 px scan labels, and 17 px selected-structure title align with the source density.
- Spacing and layout rhythm: full-width runtime/product chrome, fixed left/right split, leading expiry band, table header, row rhythm, and bottom status strip match the reference geometry.
- Colors and state tokens: dark navy surfaces, purple selected outline, amber exit responsibility, green Runtime/positive distance, muted secondary facts, and divider contrast match the selected direction.
- Image quality and assets: the source is a native data UI with no photography or illustration to reproduce. The current dependency set has no approved matching funnel/filter icon set; controls remain text-first instead of drawing fake icons.
- Copy and content: the implementation uses current lifecycle vocabulary (`CLOSE 已锁存`, `退出中`, `持仓责任持续`, `尚不可得`) and does not copy the mock's illustrative prices or lifecycle mix.

## Business-truth acceptance

- Shadow membership is sourced only from `shadow_entries.rows`; underwriting rows and Controls cannot enter the position book.
- Entry/Position/Outcome association uses exact `shadow_entry_identity`; contract names are display facts, never join keys.
- `GAPPED` is rendered as observation quality and does not hide an Entry, terminate a Position, or erase the next exit duty.
- The historical first CLOSE reason remains immutable, including legacy source-discontinuity and liquidity-boundary reasons, while `EXIT_ACQUIRING` continues to show the current obligation to find the first qualified exit fact.
- Unknown exit economics renders as “尚不可得”, never zero. A PnL value appears only from a qualified current close opportunity or a known terminal Outcome.
- `SETTLEMENT_PENDING`, `EXITED_KNOWN`, `SETTLED_KNOWN`, `TERMINAL_UNKNOWN`, missing/duplicate identity, and display-only fact loss are covered by the executable browser-state harness even though the current natural runtime has not produced those terminal states.
- Missing responsibility identity fails closed without deleting Entry; a terminal Position with missing/duplicate/non-final Outcome shows `终端结果待恢复` instead of inferring an exit; missing display-only structure facts do not downgrade a valid Position lifecycle.
- The page states `PUBLIC SHADOW · READ ONLY` and exposes no order, fill, account, margin, or private execution surface.

## Interactions and responsive acceptance

- Both / Put / Call: 21 / 1 / 20 rows; no opposite-type leakage.
- Filter popover exposes lifecycle and expiry controls and truthfully reports `21 / 21` admitted Shadow positions, all carrying exit responsibility.
- Search: `63500-P` returns one matching frozen structure; clearing restores all 21 rows.
- Row selection updates the trader inspector and preserves exact frozen Entry/Position facts.
- Evidence disclosure expands and retains the Gap/Cohort truth boundary.
- At 1487 × 1058, neither the page nor the risk table overflows horizontally; all nine trader columns and the 390 px inspector remain visible.
- At 800 × 1058, the list retains a bounded horizontal table scroller and the selected position opens in a modal drawer below the fixed product chrome. The drawer closes cleanly and restores the list.
- The skip link is surface-neutral; the expiry band precedes the column header as in the source hierarchy.
- Application-origin console warnings/errors: none.

## Comparison history

1. Pass 1 — [P1] the desktop grid was attached to the old queue owner, so the inspector fell below the table. The grid now belongs to the shared workspace shell, producing the source's side-by-side 1050/390 split.
2. Pass 2 — [P2] the expiry band followed the table header and row copy was too verbose. The expiry summary now leads the columns, and row states use compact trader language without dropping the full evidence in the inspector.
3. Pass 3 — [P2] the selected inspector lacked current index, entry net credit, fee-reserved maximum loss, and independent expiry countdown. The schema-7 projection now exposes those existing server-owned facts; no second policy calculator or durable object was added.
4. Pass 4 — [P2] the first recovery fixture showed staged Positions as monitoring and omitted persisted first CLOSE responsibility. Final QA uses the official Case recovery objects and first-CLOSE evidence in a non-mutating projection; all 21 admitted rows correctly render `EXIT_ACQUIRING`.
5. Final comparison — source and implementation were combined at the same 1487 × 1058 state, then rechecked as table- and inspector-focused pairs. No actionable P0, P1, or P2 visual finding remains.

## Residual P3 polish

- The source's funnel/filter glyphs remain text controls because the repository has no approved matching icon library; no ASCII, hand-drawn SVG, or fake asset was introduced.
- The source mock illustrates 10 rows over three expiries and mixed lifecycle states. Current durable admitted data contains 21 rows in one expiry and all have exit responsibility. The implementation intentionally preserves that real distribution.

final result: passed
