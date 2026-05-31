"""Cross-project portfolio rollup — the birds-eye view HacknPlan lacks natively.

HacknPlan has no all-projects dashboard (it shows per-project boards + a recent-
activity feed only). This aggregates every project into one snapshot using the
work-item LIST endpoint, which returns stage / importance / category / isBlocked /
dueDate inline — so a whole project rolls up in ONE request (no N+1 per card).

Used by the `portfolio_overview` MCP tool and the HTML dashboard generator
(examples/dashboard.py).

Optional grouping: HacknPlan has no "workspace" tier, so projects can optionally be
grouped for display via the HACKNPLAN_GROUPS env var — a JSON object mapping a group
label to a list of project names, e.g.

    HACKNPLAN_GROUPS='{"Team A":["Website","API"],"Personal":["Notes"]}'

If unset, every project falls under a single "All Projects" group.
"""
from __future__ import annotations

import datetime as dt
import json
import os

from client import HacknPlanClient

DEFAULT_GROUP = "All Projects"


def _load_groups() -> dict[str, list[str]]:
    raw = os.environ.get("HACKNPLAN_GROUPS", "").strip()
    if not raw:
        return {}
    try:
        g = json.loads(raw)
        return g if isinstance(g, dict) else {}
    except Exception:
        return {}


GROUPS = _load_groups()


def _group_of(name: str) -> str:
    for label, names in GROUPS.items():
        if name in names:
            return label
    return DEFAULT_GROUP


async def project_rollup(hp: HacknPlanClient, project: dict, now: dt.datetime) -> dict:
    """One-request rollup of a single project from its inline work-item list."""
    pid = project["id"]
    items = HacknPlanClient.as_list(
        await hp.get(f"/projects/{pid}/workitems", params={"limit": 100}))

    total = len(items)
    closed = open_ = blocked = urgent = high = due_soon = overdue = stories = 0
    by_stage: dict[str, int] = {}
    by_category: dict[str, int] = {}

    for w in items:
        stage = (w.get("stage") or {})
        sname = stage.get("name", "?")
        sstatus = stage.get("status", "")
        by_stage[sname] = by_stage.get(sname, 0) + 1
        if sstatus == "closed":
            closed += 1
        else:
            open_ += 1
        # "blocked" = a Blocked-named stage OR the derived isBlocked flag. HacknPlan's
        # isBlocked is dependency-derived (usually false), so the stage name is the real
        # signal for a Trello-style "Blocked" column.
        if w.get("isBlocked") or "block" in sname.lower() or "⏸" in sname:
            blocked += 1
        imp = (w.get("importanceLevel") or {}).get("name", "")
        if imp == "Urgent":
            urgent += 1
        elif imp == "High":
            high += 1
        cat = (w.get("category") or {}).get("name")
        if cat:
            by_category[cat] = by_category.get(cat, 0) + 1
        if w.get("isStory"):
            stories += 1
        due = w.get("dueDate")
        if due and sstatus != "closed":
            try:
                d = dt.datetime.fromisoformat(due.replace("Z", "+00:00"))
                days = (d - now).days
                if days < 0:
                    overdue += 1
                elif days <= 7:
                    due_soon += 1
            except Exception:
                pass

    pct = round(100 * closed / total) if total else 0
    return {
        "id": pid, "name": project["name"], "group": _group_of(project["name"]),
        "description": (project.get("description") or "").split("\n")[0][:80],
        "total": total, "open": open_, "closed": closed, "pct_done": pct,
        "blocked": blocked, "urgent": urgent, "high": high,
        "due_soon": due_soon, "overdue": overdue, "stories": stories,
        "by_stage": by_stage, "by_category": by_category,
    }


async def portfolio(hp: HacknPlanClient, now: dt.datetime) -> dict:
    """Roll up ALL projects. `now` is passed in (callers stamp the time; the MCP tool
    may pass a fixed value to stay deterministic)."""
    projects = HacknPlanClient.as_list(await hp.get("/projects"))
    rolled = []
    for p in sorted(projects, key=lambda x: x["name"].lower()):
        rolled.append(await project_rollup(hp, p, now))

    group_totals: dict[str, dict] = {}
    grand = {"projects": len(rolled), "total": 0, "open": 0, "closed": 0,
             "blocked": 0, "urgent": 0, "due_soon": 0, "overdue": 0}
    for r in rolled:
        for k in ("total", "open", "closed", "blocked", "urgent", "due_soon", "overdue"):
            grand[k] += r[k]
        gt = group_totals.setdefault(r["group"],
                                     {"projects": 0, "total": 0, "closed": 0, "blocked": 0, "urgent": 0})
        gt["projects"] += 1
        gt["total"] += r["total"]
        gt["closed"] += r["closed"]
        gt["blocked"] += r["blocked"]
        gt["urgent"] += r["urgent"]
    grand["pct_done"] = round(100 * grand["closed"] / grand["total"]) if grand["total"] else 0
    for gt in group_totals.values():
        gt["pct_done"] = round(100 * gt["closed"] / gt["total"]) if gt["total"] else 0

    return {"generated_at": now.isoformat(), "grand": grand,
            "groups": group_totals, "projects": rolled}


def _group_order(p: dict) -> list[str]:
    """Configured groups first (declaration order), then any others, biggest-first."""
    order = [g for g in GROUPS if g in p["groups"]]
    rest = sorted((g for g in p["groups"] if g not in order),
                  key=lambda g: -p["groups"][g]["total"])
    return order + rest


def to_markdown(p: dict) -> str:
    """Compact markdown birds-eye for the MCP tool / chat."""
    g = p["grand"]
    lines = [
        f"# Portfolio — {g['projects']} projects, {g['pct_done']}% done "
        f"({g['closed']}/{g['total']} items)",
        f"⚑ {g['urgent']} urgent · ⏸ {g['blocked']} blocked · "
        f"⏰ {g['due_soon']} due ≤7d · \U0001f534 {g['overdue']} overdue",
        "",
    ]
    for label in _group_order(p):
        gt = p["groups"][label]
        lines.append(f"## {label} — {gt['pct_done']}% ({gt['closed']}/{gt['total']}), "
                     f"{gt['projects']} projects")
        rows = [r for r in p["projects"] if r["group"] == label]
        rows.sort(key=lambda r: (-r["urgent"], -r["blocked"], -r["pct_done"]))
        for r in rows:
            flags = []
            if r["urgent"]:
                flags.append(f"⚑{r['urgent']}")
            if r["blocked"]:
                flags.append(f"⏸{r['blocked']}")
            if r["overdue"]:
                flags.append(f"\U0001f534{r['overdue']}")
            if r["due_soon"]:
                flags.append(f"⏰{r['due_soon']}")
            lines.append(f"- **{r['name']}** {_bar(r['pct_done'])} {r['pct_done']}%  "
                         f"({r['closed']}/{r['total']})  {' '.join(flags)}")
        lines.append("")
    return "\n".join(lines)


def _bar(pct: int, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)
