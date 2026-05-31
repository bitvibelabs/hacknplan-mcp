# Examples

## `dashboard.py` — portfolio birds-eye HTML

Generates a single self-contained HTML page summarizing **all** your HacknPlan
projects: completion %, a color-coded stage-breakdown bar per project, and
urgent / blocked / due-soon / overdue flags. HacknPlan has no native cross-project
view, so this fills that gap.

```bash
HACKNPLAN_API_KEY=your_key python3 examples/dashboard.py portfolio.html
open portfolio.html        # macOS; use xdg-open on Linux
```

Group your projects (HacknPlan has no workspace tier) by passing a JSON map:

```bash
HACKNPLAN_GROUPS='{"Products":["Website","Mobile App"],"Ops":["Infra","Support"]}' \
HACKNPLAN_API_KEY=your_key \
  python3 examples/dashboard.py
```

Re-run any time to refresh — it pulls live data (one request per project) and
overwrites the file. The same rollup is available to your AI client as the
`portfolio_overview` tool.

## Writing your own enrichment script

The migration gets your data *in*; a "polish" pass makes it *nice* — consistent
color-coded stages, categories, tags, importance levels, and a design-model tree,
applied across every project. That logic is project-specific (it depends on your
own keywords and structure), so it isn't shipped here, but the building blocks are
all MCP tools (`create_stage`, `update_stage`, `create_category`, `create_tag`,
`attach_tag`, `update_importance_level`, `create_design_element`, …).

A minimal pattern, driving the server's tools directly in Python:

```python
import asyncio, os, sys
sys.path.insert(0, "server")
from client import HacknPlanClient

async def main():
    hp = HacknPlanClient(os.environ["HACKNPLAN_API_KEY"])
    projects = HacknPlanClient.as_list(await hp.get("/projects"))
    for p in projects:
        # e.g. re-theme the "Done" stage of every project
        stages = HacknPlanClient.as_list(await hp.get(f"/projects/{p['id']}/stages"))
        for s in stages:
            if "done" in s["name"].lower():
                await hp.patch(f"/projects/{p['id']}/stages/{s['stageId']}", {
                    "name": s["name"], "status": "closed", "isUnblocker": True,
                    "color": "#36B37E", "icon": "check",
                })
    await hp.aclose()

asyncio.run(main())
```

Remember the API quirks (see `../docs/API_REFERENCE.md`): stage creates need both
`color` and `icon`, stage status is lowercase `created`/`started`/`closed`, and a
work item lands in the first stage on creation (PATCH `stageId` to move it).
