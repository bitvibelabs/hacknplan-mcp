# Migrating from Trello to HacknPlan

This server can lift an entire Trello account into HacknPlan — boards, lists,
cards, descriptions, due dates, labels, checklists, and comments — faithfully and
idempotently. This guide covers the full mapping, the options, and the caveats
that come from real HacknPlan API behaviour.

## Setup

You need three credentials in the environment:

| Var | Where |
|---|---|
| `HACKNPLAN_API_KEY` | HacknPlan → avatar → Settings → API → Create (tick all scopes) |
| `TRELLO_API_KEY` | https://trello.com/power-ups/admin → your Power-Up → API key |
| `TRELLO_TOKEN` | the "Token" link next to that key (grants read access to your boards) |

The migration only ever **reads** from Trello and **writes** to HacknPlan.

## The three-step flow

### 1. Preview (writes nothing)

```
migrate_preview(scope="all", checklist_mode="userstory")
```

Returns the full plan: for every board it would create as a project — the stages
it would derive from your lists, the tags from your labels, and the counts of
work items / checklist items per board. It also flags any board already migrated.
Read it before touching anything.

`scope` can be:
- `all` — every open board on the account
- `workspace:<name>` — every board in one Trello workspace
- `board:<name or id>` — a single board

### 2. Migrate one board, eyeball it

```
migrate_execute(scope="board:Roadmap", checklist_mode="userstory")
```

Then open that project in HacknPlan and check it against the Trello board — stages
in the right order, cards in the right stages, due dates intact. Confidence before
scale.

### 3. Migrate the rest

```
migrate_execute(scope="all", checklist_mode="userstory")
```

This is **idempotent**. A ledger (`~/.claude/state/hacknplan_migration_ledger.json`)
records every created id, so re-running skips everything already migrated and only
creates what's new. That makes it safe to re-run as a periodic **sync** — add cards
in Trello, run it again, and only the new cards land in HacknPlan.

## The mapping

| Trello | HacknPlan | Notes |
|---|---|---|
| Account | (set of projects) | HacknPlan has no workspace tier |
| Board | **Project** | costMetric defaults to Hours |
| List | **Stage** (kanban column), 1:1 | status inferred from the name (see below) |
| Card | **Work item** | created, then moved to the matching stage |
| Card description | Work-item description | a backlink to the Trello card is appended |
| Card due date | Native work-item **dueDate** | |
| Label | **Tag** | Trello colour mapped to a hex |
| Checklist | depends on `checklist_mode` | see below |
| Comment | **Comment** | author + date preserved in the text |
| Archived card | skipped | pass `include_archived=true` to include |

### Stage status inference

HacknPlan stages carry a status of `created`, `started`, or `closed`, which drives
metrics. The migrator infers it from the list name:

- contains *done / complete / closed / shipped / ✅* → **closed**
- contains *doing / progress / wip / review / testing / blocked / ⏸ / 🚧* → **started**
- everything else (inbox, backlog, to-do, this week, …) → **created**

A Trello "Blocked" list becomes its own stage (HacknPlan's `isBlocked` flag is
dependency-derived and can't be set directly, so a stage is the honest representation).

### `checklist_mode` — how Trello checklists map

HacknPlan models sub-items differently from Trello, so you choose:

- **`userstory`** *(default, most faithful)* — a card that has checklists becomes a
  HacknPlan **user story**, and each checklist item becomes a **child work item**.
  Each item is independently trackable.
- **`subtasks`** — each checklist item becomes a native HacknPlan **sub-task**
  (its checked state is preserved). Keeps one card = one work item.
- **`markdown`** — checklist items are appended to the work-item description as a
  `- [ ] / - [x]` markdown list. Simplest, lossless to read.

## What does NOT migrate (and why)

- **Trello members / assignees.** HacknPlan can't auto-invite people, and a solo
  account has one user — so assignees aren't carried over.
- **Card attachments.** The API supports attachments, but re-uploading binary
  files from Trello is out of scope for the migration (the card backlink lets you
  find the originals).
- **Board backgrounds, Power-Ups, stickers.** No HacknPlan equivalent.

## Checking fidelity afterwards

Use the read tools to compare against Trello:

```
get_project(<id>)                       # stages, categories, boards in one call
list_work_items(<id>, format="detailed")
migration_status()                      # the ledger: what mapped to what
```

## Keeping in sync

Because the migrator is idempotent, the simplest ongoing sync is just to re-run
`migrate_execute(scope="all")` whenever you've added cards in Trello. Existing
work items are left untouched; only genuinely new cards are created.

> Note: this is a one-directional Trello → HacknPlan sync of *new* cards. It does
> not propagate edits, moves, or deletions back and forth — it's a migration and
> top-up tool, not a two-way mirror.
