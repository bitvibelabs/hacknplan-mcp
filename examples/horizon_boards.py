#!/usr/bin/env python3
"""Add dated 'time-horizon' Boards to every HacknPlan project and auto-file each
dated work item into the right one by its due date.

HacknPlan stages are workflow states (a card sits in one); they carry no date.
HacknPlan *Boards* (sprints) DO carry real start/end dates and switch like tabs in
the UI — so they're the right primitive for a time axis. This script creates three
rolling horizons per project and assigns every work item that has a due date:

    📅 This Week        (today .. +7d)
    📅 Next 2 Weeks     (+8d .. +21d)
    📅 Later            (+22d and beyond)

A card keeps its workflow stage; only its board changes. Idempotent — re-run any
time to re-file cards as dates pass (boards matched by name, never duplicated).

Usage:
    HACKNPLAN_API_KEY=... python3 examples/horizon_boards.py
    HACKNPLAN_API_KEY=... python3 examples/horizon_boards.py --dry-run

There is no native "X days left" badge inside HacknPlan; for a live countdown use
the dashboard (examples/dashboard.py) or the schedule_overview MCP tool.
"""
import asyncio
import datetime as dt
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "server"))
from client import HacknPlanClient  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv


def horizons(today: dt.date):
    """(board name, start date, end date or None, predicate on days-until-due)."""
    return [
        ("📅 This Week", today, today + dt.timedelta(days=7), lambda d: d <= 7),
        ("📅 Next 2 Weeks", today + dt.timedelta(days=8), today + dt.timedelta(days=21),
         lambda d: 8 <= d <= 21),
        ("📅 Later", today + dt.timedelta(days=22), None, lambda d: d >= 22),
    ]


def iso(d: dt.date) -> str:
    return d.strftime("%Y-%m-%dT00:00:00Z")


async def main():
    key = os.environ.get("HACKNPLAN_API_KEY")
    if not key:
        sys.exit("Set HACKNPLAN_API_KEY in the environment.")
    hp = HacknPlanClient(key)
    today = dt.datetime.now(dt.timezone.utc).date()
    HZ = horizons(today)

    projects = sorted(HacknPlanClient.as_list(await hp.get("/projects")),
                      key=lambda x: x["name"].lower())
    totals = {"boards_created": 0, "cards_filed": 0}
    for p in projects:
        pid, name = p["id"], p["name"]
        base = f"/projects/{pid}"
        existing = {b["name"]: b["boardId"]
                    for b in HacknPlanClient.as_list(await hp.get(f"{base}/boards"))}
        bid = {}
        for nm, start, end, _pred in HZ:
            if nm in existing:
                bid[nm] = existing[nm]
                continue
            body = {"name": nm, "startDate": iso(start)}
            if end:
                body["dueDate"] = iso(end)
            if DRY_RUN:
                print(f"[dry-run] would create board {nm!r} in {name}")
                continue
            r = await hp.post(f"{base}/boards", body)
            if isinstance(r, dict) and r.get("boardId"):
                bid[nm] = r["boardId"]
                totals["boards_created"] += 1

        items = HacknPlanClient.as_list(await hp.get(f"{base}/workitems", params={"limit": 100}))
        for w in items:
            due = w.get("dueDate")
            if not due:
                continue
            days = (dt.date.fromisoformat(due[:10]) - today).days
            target = next((nm for nm, _s, _e, pred in HZ if pred(days)), None)
            cur = (w.get("board") or {}).get("name")
            if target and target in bid and cur != target:
                if DRY_RUN:
                    print(f"[dry-run] would file '{w.get('title','')[:40]}' -> {target} ({name})")
                else:
                    await hp.patch(f"{base}/workitems/{w['workItemId']}", {"boardId": bid[target]})
                    totals["cards_filed"] += 1
        print(f"{name}: boards={len(bid)}")
    await hp.aclose()
    print(f"\nDone — {totals['boards_created']} boards created, "
          f"{totals['cards_filed']} cards filed by due date"
          + (" (dry run, nothing changed)" if DRY_RUN else ""))


if __name__ == "__main__":
    asyncio.run(main())
