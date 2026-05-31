# hacknplan-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server for
[HacknPlan](https://hacknplan.com) — the project-management tool built for game
development. It gives an AI assistant (Claude, or any MCP client) **61 tools** to
read and write every part of a HacknPlan project: work items, boards, stages,
categories, tags, importance levels, milestones, dependencies, sub-tasks, work
logs, comments, the Game Design Model, and metrics.

It also ships two things HacknPlan itself doesn't have:

- **A Trello → HacknPlan migration engine** — point it at your Trello account and
  it recreates your boards as HacknPlan projects, faithfully, and idempotently.
- **A cross-project portfolio birds-eye view** — HacknPlan shows one project at a
  time plus a recent-activity feed; this rolls up *all* your projects into one
  status snapshot (a tool for your AI, and a standalone HTML dashboard).

Built and maintained by [BitVibe Labs](https://bitvibelabs.com). MIT licensed.

> **Why this exists.** HacknPlan has a clean REST API but almost no tooling around
> it — no good MCP server, no migration path off Trello, no portfolio view. If
> you're a solo dev or a small studio who likes HacknPlan but lives in an
> AI-assisted workflow, this closes that gap.

---

## Quickstart (60 seconds)

You need Python 3.10+ and a HacknPlan API key
(**HacknPlan → avatar → Settings → API → Create**; tick the scopes you want —
for full use, all of them).

```bash
git clone https://github.com/bitvibelabs/hacknplan-mcp
cd hacknplan-mcp
python3 -m venv .venv
./.venv/bin/python3 -m pip install -r requirements.txt
```

Register it with your MCP client. For **Claude Code**, add to `~/.claude.json`
under `mcpServers` (or use any MCP client's config):

```jsonc
{
  "mcpServers": {
    "hacknplan": {
      "command": "/absolute/path/hacknplan-mcp/.venv/bin/python3",
      "args": ["/absolute/path/hacknplan-mcp/server/hacknplan_server.py"],
      "env": {
        "HACKNPLAN_API_KEY": "your_key_here",
        "TRELLO_API_KEY": "optional — only for migration",
        "TRELLO_TOKEN":   "optional — only for migration"
      }
    }
  }
}
```

Restart your client and ask it: *"call hacknplan_whoami"*. You should see your
HacknPlan account. That's it.

It's also packaged as a **Claude Code plugin** (`.claude-plugin/plugin.json` +
`.mcp.json` using `${CLAUDE_PLUGIN_ROOT}`), so it can be installed from a
marketplace instead of hand-editing config.

---

## What you can do with it

A few real prompts, once it's connected:

- *"List my HacknPlan projects and show me the work items in the one called Website."*
- *"Create a work item 'Fix the login redirect' in project 42, tag it bug, mark it Urgent, put it in the Doing stage."*
- *"Preview migrating my Trello board 'Roadmap' into HacknPlan, then do it."*
- *"Give me a portfolio overview — what's blocked or overdue across everything?"*
- *"Build a feature tree in the design model for project 42: a System node 'Backend' with Module children 'Auth', 'Billing', 'API'."*

---

## The 61 tools

Grouped by what they touch. Read tools are annotated read-only; destructive ones
(`delete_*`) require an explicit `confirm: true`.

**Identity & projects**
`hacknplan_whoami` · `list_workspaces` · `list_projects` · `get_project`
(rolls up stages + categories + importance levels + boards in one call) ·
`create_project` · `update_project` · `delete_project` · `get_project_metrics`

**Work items** (the core task entity = a Trello card)
`list_work_items` (filter by board/stage/category/milestone; paginated;
concise|detailed|json) · `get_work_item` (with sub-tasks + comments) ·
`create_work_item` · `update_work_item` · `delete_work_item`

**Stages** (kanban columns)
`list_stages` · `create_stage` · `update_stage` · `delete_stage`

**Categories** (one mandatory per work item)
`list_categories` · `create_category` · `update_category` · `delete_category`

**Tags** (multi-select labels)
`list_tags` · `create_tag` · `update_tag` · `delete_tag` ·
`attach_tag` · `detach_tag`

**Importance / priority levels**
`list_importance_levels` · `create_importance_level` · `update_importance_level`

**Sub-tasks** (a work item's checklist)
`list_subtasks` · `add_subtask` · `update_subtask` · `delete_subtask`

**Dependencies** (blocking relationships)
`list_dependencies` · `add_dependency` · `remove_dependency`

**Milestones** (release/epic groupings) & **boards** (sprints/iterations)
`list_milestones` · `create_milestone` · `get_milestone_metrics` ·
`list_boards` · `create_board` · `close_board`

**Work logs** (time tracking)
`list_work_logs` · `log_work`

**Game Design Model** (a feature/knowledge tree — repurpose it for anything)
`list_design_element_types` · `create_design_element_type` ·
`list_design_elements` · `get_design_element` · `create_design_element` ·
`update_design_element` · `delete_design_element`

**Users & attachments**
`list_project_users` · `assign_user` · `unassign_user` · `list_attachments`

**Migration & portfolio** (the value-add layer)
`migrate_preview` · `migrate_execute` · `migration_status` · `portfolio_overview`

---

## Migrating from Trello

If you have a Trello account, this server can lift your boards into HacknPlan.
It needs your Trello key + token in the env (`TRELLO_API_KEY`, `TRELLO_TOKEN` —
get them at https://trello.com/power-ups/admin). Then:

1. **Preview first (writes nothing):** `migrate_preview` shows exactly what it
   would create — projects, stages from your lists, tags from your labels, and
   work-item / checklist / comment counts per board.
2. **Do one board to check fidelity:** `migrate_execute(scope="board:Roadmap")`.
3. **Do the rest:** `migrate_execute(scope="all")`. It's **idempotent** — a ledger
   records every created id, so re-running skips what's already migrated and only
   adds what's new. Safe to run repeatedly to keep HacknPlan in sync.

The mapping in brief:

| Trello | HacknPlan |
|---|---|
| Board | Project |
| List | Stage (status inferred: Done→closed, Doing/Blocked→started, else created) |
| Card | Work item (placed in the matching stage) |
| Card description | Work-item description (+ a backlink to the Trello card) |
| Card due date | Native work-item due date |
| Checklist | A user story with child work items, **or** native sub-tasks, **or** embedded markdown (your choice via `checklist_mode`) |
| Label | Tag |
| Comment | Comment |

See [`docs/MIGRATION.md`](docs/MIGRATION.md) for the full mapping, options, and caveats.

---

## The portfolio birds-eye view

HacknPlan has no all-projects dashboard. Two ways to get one here:

- **In your AI client:** the `portfolio_overview` tool returns a ranked, grouped
  status of every project — completion %, open/closed counts, and urgent /
  blocked / due-soon / overdue flags. Ask *"how's everything doing"*.
- **As an HTML page:** `examples/dashboard.py` writes a self-contained,
  color-coded dashboard you open in a browser:

  ```bash
  HACKNPLAN_API_KEY=... python3 examples/dashboard.py portfolio.html
  ```

HacknPlan has no workspace tier, so both let you optionally group projects via a
`HACKNPLAN_GROUPS` env var (JSON: `{"Team A": ["Website","API"], "Personal": ["Notes"]}`).
Without it, everything lands under one "All Projects" group.

---

## Three HacknPlan API quirks this server handles for you

These cost real debugging time against the raw API; the server already deals with
them, and they're documented in full in [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md):

1. **`costMetric` on project creation is the literal string `"Hours"` or `"Points"`** —
   the OpenAPI spec types it as a plain string with no enum, which is misleading.
   Anything else returns a 400.
2. **Creating a stage requires both `color` *and* `icon`** — omit the icon and you
   get a bare HTTP 500 with an empty body. The status enum is lowercase
   `created` / `started` / `closed` (not `completed`).
3. **`isBlocked` on a work item is effectively read-only** — it's derived from
   dependency links, so PATCHing it returns 200 but doesn't stick. Model a
   "Blocked" column as its own stage instead.

Also worth knowing: HacknPlan's API is **read-only for workspaces** (a Personal /
Personal-Plus account returns an empty `/workspaces` list even though the web UI
shows one — that's expected; projects still work and auto-assign). And design-element
**nesting via the API doesn't work** — `parentId` is accepted in the schema but
ignored, so the design model is effectively flat through the API.

---

## Configuration

| Env var | Required | Purpose |
|---|---|---|
| `HACKNPLAN_API_KEY` | yes | `Authorization: ApiKey <key>` for every call |
| `TRELLO_API_KEY` | for migration only | Trello REST key |
| `TRELLO_TOKEN` | for migration only | Trello REST token |
| `HACKNPLAN_GROUPS` | no | JSON grouping for the portfolio view |

The server reads credentials **only** from the environment — nothing is hardcoded
or written to disk.

---

## Project layout

```
hacknplan-mcp/
├── server/
│   ├── hacknplan_server.py   # FastMCP entrypoint — registers all 61 tools
│   ├── client.py             # async HTTP client: auth, rate-limit throttle, retries
│   ├── formatting.py         # JSON vs Markdown / concise vs detailed output
│   ├── migrate.py            # Trello → HacknPlan migration engine
│   ├── trello.py             # read-only Trello REST client (migration source)
│   └── portfolio.py          # cross-project rollup for the birds-eye view
├── examples/
│   ├── dashboard.py          # generate the HTML portfolio dashboard
│   └── README.md
├── docs/
│   ├── API_REFERENCE.md      # ground-truth HacknPlan v0 API notes (every quirk)
│   └── MIGRATION.md          # the full Trello migration guide
├── .claude-plugin/plugin.json   # Claude Code plugin manifest
├── .mcp.json                    # plugin MCP descriptor
├── requirements.txt
└── README.md
```

## Rate limiting & reliability

HacknPlan allows 5 requests/second per IP. The client enforces a global throttle
(~4.5 req/s) and retries `429` / `5xx` with exponential backoff, so bulk
operations (migrating dozens of boards) don't trip the limit. List endpoints
return bare arrays; the work-item search returns a paged envelope — the client
normalizes both.

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). This was built
against HacknPlan API **v0**; if HacknPlan ships v1 (OAuth2 + new endpoints are on
their roadmap), the client is the place to start.

## License

[MIT](LICENSE) © BitVibe Labs.

## Acknowledgements

Built with the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
Not affiliated with or endorsed by HacknPlan.
