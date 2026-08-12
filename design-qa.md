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
- Browser-rendered desktop implementation: `/private/tmp/optimatrix-design-qa/shadow-desktop-dark.png`
- Responsive list capture: `/private/tmp/optimatrix-design-qa/shadow-narrow-list.png`
- Responsive detail capture: `/private/tmp/optimatrix-design-qa/shadow-narrow-detail.png`
- Source visual and desktop implementation: 1487 × 1058 CSS pixels; responsive viewport: 800 × 1058.
- State: dark theme, current runtime facts projected through schema 7 plus an isolated preview-only enrichment of the four new frozen structure fields. The enrichment reconstructs no strategy truth and is not a product dependency.
- Runtime facts at acceptance: 33 official Shadow Entries, 33 positions carrying exit responsibility, 0 monitoring, 0 terminal Outcome, two expiries (13/14 AUG). Control records remain outside this page.

## Trader-first hierarchy

The selected “expiry risk book” direction is preserved: active Shadow positions are grouped by expiry in a dense primary table, with a persistent desktop inspector for the selected position. Default row content is intentionally limited to structure, quantity/entry credit, lifecycle responsibility, triggering/current fact, known close economics, next duty, and observation quality. The right panel limits its default view to frozen entry economics, current risk/exit duty, hard-close horizon, and expected terminal route.

Full Segment, Gap, Cohort, Entry, Position, and Outcome evidence remains available behind one disclosure. Nine raw exit predicates, Control research, underwriting candidates, and raw payloads do not compete with the trader’s default risk scan.

## Business-truth acceptance

- Shadow membership is sourced only from `shadow_entries.rows`; underwriting rows and Controls cannot enter the position book.
- Entry/Position/Outcome association uses exact `shadow_entry_identity`; contract names are display facts, never join keys.
- `GAPPED` is rendered as observation quality and does not hide an Entry, terminate a Position, or erase the next exit duty.
- The historical first CLOSE reason remains immutable, including the legacy source-discontinuity reason, while `EXIT_ACQUIRING` continues to show the current obligation to find the first qualified exit fact.
- Unknown exit economics renders as “尚不可得”, never zero. A PnL value appears only from a qualified current close opportunity or a known terminal Outcome.
- `SETTLEMENT_PENDING`, `EXITED_KNOWN`, `SETTLED_KNOWN`, `TERMINAL_UNKNOWN`, missing/duplicate identity, and display-only fact loss are covered by the executable browser-state harness even though the current natural runtime has not produced those terminal states.
- Missing responsibility identity fails closed without deleting Entry; a terminal Position with missing/duplicate/non-final Outcome shows `终端结果待恢复` instead of inferring an exit; missing display-only structure facts do not downgrade a valid Position lifecycle.
- The page states `PUBLIC SHADOW · READ ONLY` and exposes no order, fill, account, margin, or private execution surface.

## Interactions and responsive acceptance

- Both / Put / Call: 12 Put rows and 21 Call rows; no opposite-type leakage.
- Expiry filter: 14 AUG returns 9 rows and one matching expiry group.
- Search: `65500` returns one exact frozen structure; clearing restores all 33 rows.
- Responsibility filter: all 33 current positions appear under exit responsibility; Monitoring truthfully returns an empty filtered view without changing the 33-position denominator.
- Row selection updates the trader inspector and preserves exact frozen Entry/Position facts.
- Evidence disclosure expands and retains the Gap/Cohort truth boundary.
- At 1487 × 1058, neither the page nor the risk table overflows horizontally; the seven trader columns and right inspector remain visible.
- At 800 × 1058, the list retains a bounded horizontal table scroller and the selected position opens in a modal drawer below the fixed product chrome. The drawer closes cleanly and restores the list.
- Table semantics contain two sibling expiry `rowgroup` elements with no nested rowgroup. The skip link is surface-neutral.
- Application-origin console warnings/errors: none. An unrelated installed translation extension emitted its own version-mismatch errors and was excluded from product findings.

## Comparison findings and fixes

1. The first implementation used a 1190 px table minimum, creating avoidable desktop scrolling beside the persistent inspector. It was reduced to a 940 px trader-density grid without removing any decision field.
2. The first ARIA structure nested expiry rowgroups inside a queue rowgroup. The container role was removed so each expiry owns one valid sibling rowgroup.
3. Migrated Candidate/Underwriting code names and unused detail/economics styles remained after the redesign. They were deleted or renamed to make Shadow lifecycle ownership explicit.
4. Responsibility-association faults and display-only field faults initially shared one warning. They are now separate: only the former fails lifecycle association closed; the latter preserves the server-owned Position responsibility.
5. The global skip label and toolbar region label were Radar-specific. They are now neutral across Radar and Shadow.

No actionable P0, P1, or P2 design finding remains.

final result: passed
