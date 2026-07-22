# Optimatrix engineering map

## Purpose

`AGENTS.md` routes work; it is not a second constitution, task log, or evidence archive. Turn one
explicitly approved business closure into the smallest coherent change, verify it independently,
and report only what the evidence proves.

## Authority

```text
PRODUCT_CONSTITUTION
├── CURRENT_STAGE          permission authority
├── SYSTEM_ARCHITECTURE    structural authority
└── DELIVERY_CONTRACT      development and evidence authority
        ↓
implementation contract(s)
        ↓
one active task
```

The three authorities below the Product Constitution are orthogonal; none overrides another.
Implementation contracts and tasks may narrow but never widen them. Conflicts require an
explicitly approved amendment to the owning authority; code, tests, commits, and receipts never
amend authority by implication.

## Read route

Before every task, read completely:

1. [`docs/authority/PRODUCT_CONSTITUTION.md`](docs/authority/PRODUCT_CONSTITUTION.md)
2. [`docs/authority/CURRENT_STAGE.md`](docs/authority/CURRENT_STAGE.md)
3. [`docs/authority/DELIVERY_CONTRACT.md`](docs/authority/DELIVERY_CONTRACT.md)
4. the one active semantic task under `tasks/`, when present

Before changing code, dependencies, modules, or artifacts, also read
[`docs/authority/SYSTEM_ARCHITECTURE.md`](docs/authority/SYSTEM_ARCHITECTURE.md). Before changing
Short Vol behavior or market semantics, read
[`docs/contracts/SHORT_VOL_RADAR.md`](docs/contracts/SHORT_VOL_RADAR.md).

If no task represents the explicit user request, create one from
[`tasks/TEMPLATE.md`](tasks/TEMPLATE.md) before changing code, product behavior, or contracts, then
read it completely. Name it for the business closure, never a sequence number. Completed tasks do
not accumulate on `main`; Git and durable evidence are the archive.

## Runtime truths

- Decision facts are known at or before their decision `capture_seq`.
- Outcome facts are strictly after entry; actual exposure ends at exit.
- Missing, stale, incomplete, or contaminated evidence is `UNKNOWN`, never zero or calm.
- Executable economics use visible bid/ask, a visible combo, or future actual fills—not mark/mid.
- Current permissions come only from `CURRENT_STAGE.md`; implementation presence grants nothing.

## Change declarations

Every active task declares `NONE` or one exact approved change for each axis:

1. Market/Decision input contract
2. Decision Policy
3. Outcome/evaluation contract
4. Stage/authorization

Input-truth repair is not Policy tuning. Capture, replay, provenance, storage, or reporting may not
hide effects on any axis. Definitions and evidence rules live in the Delivery Contract.

## Execution

Inspect branch, HEAD, remote refs, task anchors, and worktree before editing. Preserve unrelated
human work. Use one bounded branch and run `make sync` after checkout. Work only in the owning
module; add direct behavior tests; do not add infrastructure for a queued closure.

Before completion, run focused tests, `make check`, and every task-required live/replay/Outcome
check. Inspect durable artifacts and staged scope. Report evidence, zero activity, `UNKNOWN`s,
non-claims, Git state, and remote state. Live/replay equality proves reconstruction—not data
completeness, Policy quality, or fills.

## Git and upkeep

Never reset, clean, overwrite, stage, or delete unrelated human work. Protect `main`; do not rewrite
or delete remote state without explicit authorization. Verify all authorized remote operations.
Update `CURRENT_STAGE.md` only when capability, permission, blockers, or the sole next closure
changes.
