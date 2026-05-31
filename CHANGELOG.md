# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com); versions follow
[SemVer](https://semver.org).

## [Unreleased]

### Added
- `schedule_overview` tool + a "Schedule" section in the HTML dashboard — every
  dated work item across all projects, bucketed by horizon (Overdue / This week /
  Next 2 weeks / This month / Later) with a live days-left countdown (**62 tools**).
- `examples/horizon_boards.py` — create dated This Week / Next 2 Weeks / Later
  boards in every project and auto-file each card by its due date.
- `examples/portfolio_board.py` — build an in-HacknPlan portfolio hub (one card
  per project, live %done + flags).
- `tests/` — pure-logic unit tests + a stdio boot smoke test; GitHub Actions CI
  across Python 3.10–3.13.
- `SECURITY.md` — threat model (stdio server) + honest triage of dependency
  advisories; `.env.example`; a pre-commit secret-guard hook.

## [0.1.0] — 2026-05-31

First public release.

### Added
- MCP server over the HacknPlan v0 API with **61 tools** covering projects, work
  items, stages, categories, tags, importance levels, sub-tasks, dependencies,
  milestones, boards, work logs, comments, the Game Design Model, users,
  attachments, and metrics.
- **Trello → HacknPlan migration engine** (`migrate_preview` / `migrate_execute` /
  `migration_status`) — idempotent, ledger-backed, with three checklist-handling
  modes (user-story, native sub-tasks, embedded markdown).
- **Cross-project portfolio view** — `portfolio_overview` tool plus
  `examples/dashboard.py`, a standalone color-coded HTML dashboard. Optional
  project grouping via `HACKNPLAN_GROUPS`.
- Async HTTP client with a global 5 req/s rate-limit throttle and 429/5xx retry.
- Claude Code plugin packaging (`.claude-plugin/plugin.json`, `.mcp.json`).
- `docs/API_REFERENCE.md` documenting the verified HacknPlan v0 behaviour,
  including the costMetric-string, stage-requires-icon, and read-only-isBlocked
  quirks.

### Known limitations (HacknPlan API, not this server)
- Design-element **nesting** doesn't work via the API — `parentId` is accepted in
  the schema but ignored, so the design model is flat through the API.
- **Workspaces are read-only** in the API and a Personal/Personal-Plus account
  reports an empty workspace list.
- **Work logs** can only be edited within ~1 hour of creation (HacknPlan rule).
