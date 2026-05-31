#!/usr/bin/env python3
"""Generate a self-contained, color-coded HTML birds-eye dashboard of ALL your
HacknPlan projects — the cross-project portfolio view HacknPlan has no native
equivalent for (it shows per-project boards + a recent-activity feed only).

Pulls live data via the server's portfolio rollup (one request per project, inline)
and writes a single static HTML file you open in a browser. Re-run to refresh.

Usage:
    HACKNPLAN_API_KEY=... python3 examples/dashboard.py [output.html]
    # optional grouping (HacknPlan has no workspaces):
    HACKNPLAN_GROUPS='{"Team A":["Website","API"],"Personal":["Notes"]}' \\
        HACKNPLAN_API_KEY=... python3 examples/dashboard.py

Default output: ./hacknplan-portfolio.html
"""
import asyncio
import datetime as dt
import html
import os
import sys

# Import the server package (sibling dir). Adjust if you relocate this file.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "server"))

from client import HacknPlanClient  # noqa: E402
from portfolio import portfolio  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "hacknplan-portfolio.html"

# stage-name keyword -> color (works with the default Trello-migrated stage names;
# unknown stages fall back to gray, so any naming scheme still renders)
STAGE_COLOR = [
    ("done", "#36B37E"), ("complete", "#36B37E"), ("✅", "#36B37E"),
    ("block", "#DE350B"), ("⏸", "#DE350B"),
    ("review", "#6554C0"), ("\U0001f440", "#6554C0"), ("test", "#6554C0"),
    ("doing", "#FFAB00"), ("progress", "#FFAB00"), ("\U0001f6a7", "#FFAB00"),
    ("week", "#4C9AFF"), ("next", "#4C9AFF"), ("\U0001f3af", "#4C9AFF"),
    ("inbox", "#7A869A"), ("backlog", "#7A869A"), ("todo", "#7A869A"), ("\U0001f4e5", "#7A869A"),
]

# group accent colors, assigned from a palette in first-seen order
_PALETTE = ["#4C9AFF", "#36B37E", "#FF8B00", "#6554C0", "#00B8D9", "#FF5630", "#FFC400", "#7A869A"]
_accent: dict = {}


def accent(group: str) -> str:
    if group not in _accent:
        _accent[group] = _PALETTE[len(_accent) % len(_PALETTE)]
    return _accent[group]


def stage_color(name: str) -> str:
    low = name.lower()
    for kw, col in STAGE_COLOR:
        if kw in low:
            return col
    return "#A5ADBA"


def esc(s):
    return html.escape(str(s))


_STAGE_ORDER = ["inbox", "backlog", "todo", "week", "next", "doing", "progress",
                "review", "test", "block", "done", "complete"]


def _rank(name: str) -> int:
    low = name.lower()
    for i, k in enumerate(_STAGE_ORDER):
        if k in low:
            return i
    return 99


def stage_bar(by_stage: dict, total: int) -> str:
    if not total:
        return '<div class="sbar empty"></div>'
    segs = []
    for name, n in sorted(by_stage.items(), key=lambda kv: _rank(kv[0])):
        pct = 100 * n / total
        segs.append(f'<span style="width:{pct:.1f}%;background:{stage_color(name)}" '
                    f'title="{esc(name)}: {n}"></span>')
    return '<div class="sbar">' + "".join(segs) + "</div>"


def project_card(r: dict) -> str:
    flags = []
    if r["urgent"]:
        flags.append(f'<span class="flag urgent">⚑ {r["urgent"]}</span>')
    if r["blocked"]:
        flags.append(f'<span class="flag blocked">⏸ {r["blocked"]}</span>')
    if r["overdue"]:
        flags.append(f'<span class="flag overdue">\U0001f534 {r["overdue"]}</span>')
    if r["due_soon"]:
        flags.append(f'<span class="flag due">⏰ {r["due_soon"]}</span>')
    cats = "".join(
        f'<span class="cat" title="{esc(c)}: {n}">{esc(c.split("/")[0])} {n}</span>'
        for c, n in sorted(r["by_category"].items(), key=lambda kv: -kv[1])[:4])
    return f'''
    <div class="card">
      <div class="card-h">
        <span class="pname">{esc(r["name"])}</span>
        <span class="pct">{r["pct_done"]}%</span>
      </div>
      <div class="pdesc">{esc(r["description"])}</div>
      {stage_bar(r["by_stage"], r["total"])}
      <div class="meta">
        <span class="count">{r["closed"]}/{r["total"]} done · {r["open"]} open</span>
        <span class="flags">{"".join(flags)}</span>
      </div>
      <div class="cats">{cats}</div>
    </div>'''


def render(data: dict) -> str:
    g = data["grand"]
    gen = dt.datetime.fromisoformat(data["generated_at"]).strftime("%Y-%m-%d %H:%M UTC")
    group_order = sorted(data["groups"], key=lambda w: -data["groups"][w]["total"])
    sections = []
    for grp in group_order:
        rows = [r for r in data["projects"] if r["group"] == grp]
        if not rows:
            continue
        gt = data["groups"][grp]
        acc = accent(grp)
        rows.sort(key=lambda r: (-r["urgent"], -r["blocked"], -r["pct_done"]))
        cards = "".join(project_card(r) for r in rows)
        sections.append(f'''
        <section>
          <h2 style="border-color:{acc}">
            <span class="dot" style="background:{acc}"></span>{esc(grp)}
            <span class="wsum">{gt["pct_done"]}% · {gt["closed"]}/{gt["total"]} · {gt["projects"]} projects</span>
          </h2>
          <div class="grid">{cards}</div>
        </section>''')
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HacknPlan Portfolio</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
          background:#0d1117; color:#e6edf3; padding:28px; }}
  header {{ display:flex; align-items:baseline; gap:18px; flex-wrap:wrap; margin-bottom:6px; }}
  h1 {{ font-size:22px; margin:0; font-weight:700; }}
  .sub {{ color:#8b949e; font-size:13px; }}
  .topstats {{ display:flex; gap:10px; flex-wrap:wrap; margin:14px 0 26px; }}
  .stat {{ background:#161b22; border:1px solid #30363d; border-radius:10px; padding:10px 16px; }}
  .stat b {{ font-size:20px; display:block; }}
  .stat span {{ color:#8b949e; font-size:12px; }}
  section {{ margin-bottom:30px; }}
  h2 {{ font-size:15px; display:flex; align-items:center; gap:9px; border-left:4px solid;
        padding-left:10px; margin:0 0 14px; }}
  h2 .dot {{ width:9px; height:9px; border-radius:50%; }}
  .wsum {{ color:#8b949e; font-weight:400; font-size:12px; margin-left:auto; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(290px,1fr)); gap:14px; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:12px; padding:14px 16px; }}
  .card-h {{ display:flex; justify-content:space-between; align-items:baseline; }}
  .pname {{ font-weight:650; font-size:15px; }}
  .pct {{ font-weight:700; font-size:15px; color:#58a6ff; }}
  .pdesc {{ color:#8b949e; font-size:12px; margin:3px 0 10px; min-height:16px;
            overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .sbar {{ display:flex; height:9px; border-radius:5px; overflow:hidden; background:#21262d; }}
  .sbar span {{ display:block; height:100%; }}
  .sbar.empty {{ opacity:.3; }}
  .meta {{ display:flex; justify-content:space-between; align-items:center; margin-top:9px; gap:8px; }}
  .count {{ color:#8b949e; font-size:12px; }}
  .flags {{ display:flex; gap:5px; }}
  .flag {{ font-size:11px; padding:1px 7px; border-radius:20px; font-weight:600; }}
  .flag.urgent {{ background:#3d1a12; color:#ff9776; }}
  .flag.blocked {{ background:#3d1212; color:#ff7676; }}
  .flag.overdue {{ background:#4a0f0f; color:#ff5c5c; }}
  .flag.due {{ background:#3d3512; color:#ffd866; }}
  .cats {{ display:flex; gap:5px; flex-wrap:wrap; margin-top:9px; }}
  .cat {{ font-size:10px; color:#8b949e; background:#21262d; border-radius:5px; padding:1px 6px; }}
  footer {{ color:#484f58; font-size:11px; margin-top:24px; }}
</style></head>
<body>
  <header>
    <h1>HacknPlan Portfolio</h1>
    <span class="sub">birds-eye across all {g["projects"]} projects · generated {gen}</span>
  </header>
  <div class="topstats">
    <div class="stat"><b>{g["pct_done"]}%</b><span>complete ({g["closed"]}/{g["total"]})</span></div>
    <div class="stat"><b>{g["projects"]}</b><span>projects</span></div>
    <div class="stat"><b>{g["open"]}</b><span>open items</span></div>
    <div class="stat"><b>{g["urgent"]}</b><span>⚑ urgent</span></div>
    <div class="stat"><b>{g["blocked"]}</b><span>⏸ blocked</span></div>
    <div class="stat"><b>{g["overdue"]}</b><span>\U0001f534 overdue</span></div>
  </div>
  {"".join(sections)}
  <footer>Generated by hacknplan-mcp · examples/dashboard.py · HacknPlan has no native cross-project view; this aggregates it.</footer>
</body></html>'''


async def main():
    key = os.environ.get("HACKNPLAN_API_KEY")
    if not key:
        sys.exit("Set HACKNPLAN_API_KEY in the environment.")
    hp = HacknPlanClient(key)
    now = dt.datetime.now(dt.timezone.utc)
    data = await portfolio(hp, now)
    await hp.aclose()
    with open(OUT, "w") as f:
        f.write(render(data))
    print(f"wrote {OUT} ({data['grand']['projects']} projects)")


if __name__ == "__main__":
    asyncio.run(main())
