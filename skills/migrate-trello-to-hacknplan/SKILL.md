---
name: migrate-trello-to-hacknplan
description: Use ONLY when the user explicitly invokes `/migrate-trello-to-hacknplan` or clearly asks to migrate / import / move their Trello boards into HacknPlan (e.g. "migrate my Trello to HacknPlan", "import board X into HacknPlan", "copy my Trello cards over"). This is an EXPLICIT-OPT-IN skill — do NOT auto-trigger on generic mentions of Trello or HacknPlan. When triggered, run a preview first, then execute the migration board-by-board using the hacknplan MCP tools.
---

# Migrate Trello → HacknPlan

Drives the `hacknplan` MCP server's migration tools to copy Trello boards into
HacknPlan. Always **preview before execute**, and migrate **one board first** to
let the user eyeball fidelity before doing the rest.

## Mapping (what becomes what)

| Trello | HacknPlan |
|---|---|
| Board | Project (`costMetric="Hours"`) |
| List | Stage (status inferred: Done→completed, Doing/Blocked→started, else created) |
| Label | Tag |
| Card | Work item (in the matching stage, on the default board) |
| Card due date | Native work-item `dueDate` |
| "⏸ Blocked" list | Work item `isBlocked=true` |
| Checklist | Per `checklist_mode` (below) |
| Comment | Work-item comment |

`checklist_mode`:
- **`userstory`** (default for this user) — a card with checklists becomes a HacknPlan
  *user story*, and each checklist item becomes a child work item (most faithful, trackable).
- **`subtasks`** — each checklist item becomes a native HacknPlan sub-task (1:1, preserves checked state).
- **`markdown`** — checklist items appended to the work item description as `- [ ]`/`- [x]`.

## Procedure

1. **Confirm scope + mode.** Ask which boards (`all`, `workspace:<name>`, or `board:<name>`)
   and which `checklist_mode` if not stated. This user's default is `userstory`.
2. **Preview** with `migrate_preview(scope, checklist_mode)`. Show the user the plan:
   projects to create, stages per board, tag + work-item + checklist counts, and which
   boards are already migrated. This writes nothing.
3. **Validate one board** with `migrate_execute(scope="board:<one>")`, then `get_project`
   + `list_work_items(format="detailed")` so the user can verify fidelity in the HacknPlan UI.
4. **Run the rest** with `migrate_execute(scope="all")` (or per workspace). It is **idempotent**
   — already-migrated boards/cards are skipped via the ledger, so it's safe to resume/re-run.
   For a large run, do it in the background and report progress (it's rate-limited to 5 req/s).
5. **Report** with `migration_status()` — a per-board ✅ ledger (project id, stages, tags, cards).

## Notes
- HacknPlan `/workspaces` is empty on Personal/Personal-Plus accounts — that's normal; projects
  auto-assign to the personal workspace. Don't block on it.
- Trello members can't be auto-invited; assignees aren't migrated (single-user HacknPlan account).
- The ledger lives at `~/.claude/state/hacknplan_migration_ledger.json`.
