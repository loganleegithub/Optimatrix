# Reuse and deletion map

**Baseline:** `main@13902c53e972f12721d2ef9d17de866fbda288a7`

**Target:** isolated `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1` local-validation candidate

Reuse means transplanting a product-neutral invariant under the new Authority and tests. It does
not mean importing the legacy runtime, preserving V2 strategy semantics, adopting legacy identities,
or reading the legacy Case root.

## Reused product-neutral invariants

| Audited invariant | New owner | Retention rule |
| --- | --- | --- |
| Inverse BTC native premium versus USD-equivalent boundary valuation | `products.py`, `pricing.py` | quantities remain distinctly labelled |
| amount grid and full target-depth walking | `products.py`, `pricing.py` | four legs must each satisfy quantity |
| official legal-tick adverse stress | `market.py`, `pricing.py` | stress before joint economics |
| premium-capped public fees | `pricing.py` | reserve all four leg fees |
| component Vertical pricing | `pricing.py` | side component only, never product identity |
| official delivery-price settlement arithmetic | `pricing.py`, `engine.py` | product-owned terminal calculator |
| canonical identity and strict Decimal encoding | `identity.py`, owning codecs | no float identity preimages |
| process-independent lifecycle duty | `lifecycle.py`, `persistence.py` | restart cannot erase short/residual-wing duty |
| UNKNOWN and known-zero distinction | Authority and owners | no neutral fabrication |
| one validator/calculator per invariant | module ownership | no duplicate truth |
| funnel baseline/blocker/task governance | root Authority and `tasks/` | tests are supporting evidence only |
| no application commissioning or host acceptance | Authority | operations remain external |

## Deliberately replaced product semantics

| Legacy semantic | New product rule |
| --- | --- |
| rolling `0–72h` option universe | current Deribit `08:00–08:00 UTC` Session expiry only |
| one option/Vertical as canonical Short Vol object | one joint asymmetric four-leg Iron Condor |
| Calls and Puts ranked independently | one bounded joint structure score |
| V2 Radar/Underwriting/Position three-Policy identities | one new content-identified Decision Policy family |
| admitted trade Entry required paired two-leg witness | future-blind Decision Case precedes four-leg attempt result |
| two frozen legs and V2 score packet | four selected legs, SessionDecisionUnit, joint score, attempt contract |
| full-pair close acquisition | side-specific short-risk flattening and residual-wing duty |
| V2 funnel and blocker vocabulary | canonical same-Session four-leg funnel |
| strategy-specific Workbench projection | new-product read-only projection from one owner |

The legacy system was not success-only: it also contained selected no-trade Controls. Gapped Cases
were not globally unusable: they could retain research and terminal-economics value while losing
strict continuous-path eligibility. This rebuild changes the product object; it does not rewrite
those historical facts.

## Deleted or forbidden paths

- legacy single-option Radar and protective-Vertical selector;
- legacy single-side Candidate/Underwriting/Position product path;
- legacy three V2 Policy files and schema-v5 online Case codec in the new product;
- old continuous-service owner graph and V2 strategy-bound Workbench;
- parallel legacy/new product selector, fallback, translator, symlink, or shared root;
- generic N-leg framework, dynamic Channel plugin system, database, message bus, replay platform,
  commissioning controller, and browser-side strategy formula.

## Legacy isolation

The historical baseline remains in Git and the existing external legacy environment. The new
product has zero authority to read, write, translate, migrate, relabel, recover, or count:

```text
/Users/logan/Optimatrix-runtime
/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9
legacy V2 Policies, schema-v5 Cases, and their 92 Case identities
```

Legacy Cases remain evidence only for their original V2 product and Policies. They are not an Iron
Condor baseline, control, migration input, or product-funnel denominator.
