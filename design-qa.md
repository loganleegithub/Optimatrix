# Workbench Design QA

## Comparison target

- Source visual truth: `/Users/logan/.codex/generated_images/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/exec-c06aff4b-6def-4ec0-ab06-4c64e021f7e3.png`
- Source pixels: `1487 × 1058`; normalized to `1440 × 1024` for comparison.
- CSS viewport: `1440 × 1024`; browser density: `deviceScaleFactor 1`.
- Implementation captures:
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/ledger-final-flat.png`
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/product-final-flat.png`
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/review-final-flat.png`
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/tablet-review.png`
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/mobile-review.png`
- Combined comparison evidence:
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/comparison-ledger-final.png`
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/comparison-product-final.png`
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/comparison-review-flat-final.png`
- Focused regions were checked in the product-detail capture: four-leg table, payoff boundary, management timeline and terminal responsibility panel are readable at 1440px; no separate crop was required.

## State and browser verification

- Offline deterministic raw-Deribit four-leg tape with `96/96` DecisionRecords, `96/96` WindowOutcomes and a terminal whole-product-exit Case.
- Product ledger, product detail, review route, evidence drawer and reserved-channel notice were exercised in the Codex in-app browser.
- Browser console errors checked: none.
- Primary interactions tested: ledger → Case detail; detail/review navigation; evidence drawer open/close; reserved BTC Long Gamma boundary notice.
- A separate contract-settlement tape also passed automated rendering tests.
- Responsive browser checks: `1024 × 768` and `390 × 844`; no document-level horizontal overflow. The four-channel switcher intentionally scrolls horizontally on mobile.
- Live runtime check at `127.0.0.1:8765`: HTTP 200, `RUNNING`, 22/22 public books and the current no-candidate business state rendered without inventing a Position or zero-valued reserved channels.
- Final same-root runtime captures after two graceful recovery deployments:
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/runtime-final-ledger-gap.png`
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/runtime-final-review-1440.png`
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/runtime-final-mobile-review.png`
  - `/Users/logan/.codex/visualizations/2026/08/13/019ffb6a-d20a-7d91-89e4-5138cb6ce01e/workbench-implementation/runtime-final-datahealth-unknown.png`

## Required fidelity surfaces

- Fonts and typography: Chinese-native system stack, compact trader-terminal scale, restrained weights and tabular numerics match the source's dense research-console hierarchy. Long identities are truncated in operational surfaces and remain available in the evidence drawer.
- Spacing and layout rhythm: the same dark full-canvas composition, thin dividers, small radii, dense metric ribbons and persistent top navigation are preserved. The implementation intentionally expands the selected visual into three connected routes instead of placing all three products on one canvas.
- Colors and visual tokens: deep navy background, cool blue borders, cyan information, amber decision/waiting, green completed/eligible, purple Challenger and red responsibility states follow the source visual truth. No decorative gradients remain.
- Image quality and asset fidelity: the target contains no photographic or illustrative assets required by the product UI. The implementation uses native text, borders and actual business data; no placeholder imagery, handcrafted SVG or emoji substitutions are present.
- Copy and content: Chinese trader-facing terms are used throughout: 铁鹰、看跌期权、看涨期权、行权价、权利金、组合订单（Combo）、到期交割、完整组合估价 and Shadow result. Public Shadow non-claims remain persistent.
- Icons: the source's decorative crypto badges and tiny glyphs were not recreated because no repository brand/icon assets exist and text labels are clearer at this density. No functional affordance depends on a missing icon.
- Responsiveness and accessibility: desktop, tablet and mobile CSS breakpoints avoid clipping; semantic headings, tables, buttons, focus rings, keyboard Escape for the drawer and reduced-motion handling are present.

## Findings and comparison history

### Iteration 1

- [P1] Old 10-second meta refresh reset Case detail and review back to the ledger.
  - Fix: removed document-level refresh and added data-script polling that reloads only after the exported document identity changes.
  - Post-fix evidence: detail and review hashes remain stable during interaction testing.
- [P1] Old single-page technical-state hierarchy survived in the initial checkout after a shared-worktree rollback.
  - Fix: restored the three-route product model and replaced the old static page, style sheet and renderer.
  - Post-fix evidence: all three final screenshots and combined comparisons above.
- [P2] Backend enum and blocker codes leaked into trader-facing cards.
  - Fix: added Chinese presentation labels for lifecycle state, runtime state, market phase and current snapshot boundary while preserving exact codes in the evidence drawer.
  - Post-fix evidence: `ledger-final.png` shows trader-facing phase and blocker language.

### Iteration 2

- [P2] Challenger chart styling used a gradient grid and could imply measured data.
  - Fix: replaced it with a flat evidence-empty surface and explicit `D1 尚未授权 / NOT_YET_MEASURED` copy.
  - Post-fix evidence: `review-final.png`; no fake curves, distribution or numeric comparison is shown.
- [P2] Reserved channels risked looking like healthy zero-population products.
  - Fix: every reserved cell now says `当前 Authority 未授权 / 无运行时`; navigation produces a boundary notice instead of fake counts.
  - Post-fix evidence: `ledger-final.png` and tested reserved-channel interaction.

### Iteration 3

- [P2] The first live runtime cut exposed `NO_POLICY_ELIGIBLE_FOUR_LEG_STRUCTURE` as a backend code, hiding the business reason from the trader.
  - Fix: translated it to `已有合法且可估价结构，但没有符合当前 Policy 的候选` and added Legal / Price-evaluable / Policy-eligible facts to the current Window card. Counts not owned by the projection remain `UNKNOWN`; Policy-eligible is shown as zero only when that blocker is explicit.
  - Post-fix evidence: focused automated projection assertions and the same-root runtime browser recapture above.
- [P2] At 1280px the four-channel switcher collided with the Session block, and recovery states leaked English backend codes.
  - Fix: top navigation now wraps below 1360px; Recovery Gap, Public Market Gap and interrupted causal-cut states have Chinese trader-facing labels while exact codes remain in the evidence drawer.
  - Post-fix evidence: `runtime-final-ledger-gap.png`; measured topbar overflow is zero, and the recovery responsibility reads `公开行情切面不完整，本窗口无法判断`.
- [P2] Later live Windows exposed unmapped no-structure and DataHealth codes after the network path changed.
  - Fix: lifecycle subtitles now translate component-wise, and legal-structure, price-evaluability, VRP, event, Delta, stale/future timestamps, span, universe and deadline blockers have Chinese trader-facing copy.
  - Post-fix evidence: `runtime-final-datahealth-unknown.png`; the page says `行情源时间落后于当前因果边界，本窗口无法判断`, keeps population counts unknown and continues to show runtime liveness separately.

## Remaining differences

- P3: the reference's dense flow visual contains synthetic illustrative curves and distributions. The implementation omits any value that the current B3 projection does not own, so live/empty populations appear visually quieter. This is an intentional truth-boundary constraint, not an incomplete state.
- P3: crypto coin icons are omitted because there is no owned icon asset in the repository; ticker text preserves the hierarchy without introducing approximate artwork.

No actionable P0/P1/P2 findings remain. Final browser checks covered 1440, 1280, 1024 and 390px, all three routes, the evidence drawer, keyboard focus return, reserved-channel notice, 10-second data polling, console warnings/errors and live recovery truth.

final result: passed
