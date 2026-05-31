#!/usr/bin/env python3
"""Build an in-HacknPlan 'Portfolio' birds-eye: one work item per project, gathered
inside a single hub project, each card showing that project's live %done +
open/blocked/urgent counts.

HacknPlan has no native all-projects view. This is the closest in-app approximation:
a hub project whose board becomes a glanceable list of every other project. (For a
richer visual, see examples/dashboard.py; for a text rollup, the portfolio_overview
MCP tool.)

Pick the hub by name via HACKNPLAN_HUB_PROJECT (default: "Portfolio"). The hub must
already exist — create it in HacknPlan, or with the create_project MCP tool. Cards
are matched/updated by a `[PF:<projectId>]` marker, so re-running refreshes numbers
in place (idempotent).

Usage:
    HACKNPLAN_API_KEY=... HACKNPLAN_HUB_PROJECT="Portfolio" \
        python3 examples/portfolio_board.py
"""
import asyncio
import datetime as dt
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "server"))
from client import HacknPlanClient  # noqa: E402
from portfolio import project_rollup  # noqa: E402

HUB_NAME = os.environ.get("HACKNPLAN_HUB_PROJECT", "Portfolio")


def bar(pct: int, width: int = 10) -> str:
    f = round(pct / 100 * width)
    return "█" * f + "░" * (width - f)


async def main():
    key = os.environ.get("HACKNPLAN_API_KEY")
    if not key:
        sys.exit("Set HACKNPLAN_API_KEY in the environment.")
    hp = HacknPlanClient(key)
    now = dt.datetime.now(dt.timezone.utc)

    projects = HacknPlanClient.as_list(await hp.get("/projects"))
    hub = next((p for p in projects if p["name"].lower() == HUB_NAME.lower()), None)
    if not hub:
        await hp.aclose()
        sys.exit(f"No project named {HUB_NAME!r}. Create it first "
                 f"(or set HACKNPLAN_HUB_PROJECT to an existing project).")
    hub_id = hub["id"]
    base = f"/projects/{hub_id}"

    # need a default importance level + a category + the default board to create cards
    imps = HacknPlanClient.as_list(await hp.get(f"{base}/importancelevels"))
    imp_id = next((i["importanceLevelId"] for i in imps if i.get("isDefault")),
                  imps[0]["importanceLevelId"] if imps else None)
    cats = HacknPlanClient.as_list(await hp.get(f"{base}/categories"))
    cat_id = cats[0]["categoryId"] if cats else None
    boards = HacknPlanClient.as_list(await hp.get(f"{base}/boards"))
    board_id = next((b["boardId"] for b in boards if b.get("isDefault")),
                    boards[0]["boardId"] if boards else None)

    # existing portfolio cards, matched by marker
    existing = {}
    for w in HacknPlanClient.as_list(await hp.get(f"{base}/workitems", params={"limit": 100})):
        full = await hp.get(f"{base}/workitems/{w['workItemId']}")
        desc = (full or {}).get("description", "") or ""
        if "[PF:" in desc:
            existing[desc.split("[PF:")[1].split("]")[0]] = w["workItemId"]

    created = updated = 0
    for p in sorted(projects, key=lambda x: x["name"].lower()):
        if p["id"] == hub_id:
            continue
        r = await project_rollup(hp, p, now)
        flags = []
        if r["urgent"]:
            flags.append(f"⚑{r['urgent']}")
        if r["blocked"]:
            flags.append(f"⏸{r['blocked']}")
        title = (f"{p['name']} — {r['pct_done']}% {bar(r['pct_done'])} "
                 f"({r['closed']}/{r['total']}) {' '.join(flags)}").strip()
        desc = (f"**{p['name']}**\n\n- progress: {r['pct_done']}%  "
                f"({r['closed']} done / {r['total']} total)\n"
                f"- open: {r['open']} · blocked: {r['blocked']} · urgent: {r['urgent']}\n\n"
                f"_Live rollup. [PF:{p['id']}]_")
        if str(p["id"]) in existing:
            await hp.patch(f"{base}/workitems/{existing[str(p['id'])]}",
                           {"title": title[:255], "description": desc})
            updated += 1
        else:
            body = {"title": title[:255], "isStory": False, "estimatedCost": 0,
                    "importanceLevelId": imp_id, "categoryId": cat_id, "description": desc}
            if board_id:
                body["boardId"] = board_id
            await hp.post(f"{base}/workitems", body)
            created += 1
    await hp.aclose()
    print(f"Portfolio board in {HUB_NAME!r}: {created} created, {updated} updated.")


if __name__ == "__main__":
    asyncio.run(main())
