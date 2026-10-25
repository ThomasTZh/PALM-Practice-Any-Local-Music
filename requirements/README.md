# Requirements archive

These documents answer **what the product must do**. They are not an
execution plan. The current order of work, acceptance evidence, and release
gates live in [`EXECUTION_PLAN.md`](../EXECUTION_PLAN.md).

## Layout

| Path | Meaning |
|---|---|
| `product/basseparate_project_plan.md` | Original product specification and milestone intent |
| `milestones/milestone0.md` … `milestone8.md` | Milestone requirements (M0–M2 delivered, M3 partially delivered, M4–M8 future) |
| `archive/work-packages/` | Historical per-package implementation plans (M1–M3). Kept for traceability; not maintained |
| `archive/plan_edit_changelog.md`, `archive/plan_edits.diff`, `archive/system-inventory.txt` | Historical planning artifacts |

## How to use these documents

1. Read `GOALS.md` first for the end-product outcome.
2. Read the relevant milestone file for required behaviour and boundaries.
3. Read `EXECUTION_PLAN.md` for the current vertical slice, its acceptance
   evidence, and the keep/adapt/replace decision for existing subsystems.
4. Do not treat a historical work-package plan as current. If a requirement
   conflicts with the execution plan, the execution plan controls sequencing;
   the milestone requirement controls product behaviour.

The old implementation ledger is archived at
`../docs/archive/implementation-status-2026-10-24.md`. The current resume point
is `../docs/implementation-status.md`.
