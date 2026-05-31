"""Response formatting helpers (mcp-builder principle: high-signal, bounded output).

Tools return either compact JSON (machine-friendly) or Markdown (human-friendly),
with a character cap so a large project never blows the agent's context budget.
"""
from __future__ import annotations

import json
from typing import Any

CHARACTER_LIMIT = 25_000


def cap(text: str, limit: int = CHARACTER_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n…[truncated {len(text) - limit} chars; narrow your query or use format='concise']"


def as_json(obj: Any) -> str:
    return cap(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def project_row(p: dict) -> str:
    return f"- **{p.get('name')}** (id={p.get('id')}, workspace={p.get('workspaceId')}, costMetric={p.get('costMetric')})"


def workitem_line(w: dict, detailed: bool = False) -> str:
    cat = (w.get("category") or {}).get("name") if isinstance(w.get("category"), dict) else None
    stage = (w.get("stage") or {}).get("name") if isinstance(w.get("stage"), dict) else None
    tags = ", ".join(t.get("name", "") for t in (w.get("tags") or []) if isinstance(t, dict))
    bits = [f"#{w.get('workItemId')}", w.get("title", "")]
    meta = []
    if stage:
        meta.append(f"stage={stage}")
    if cat:
        meta.append(f"cat={cat}")
    if w.get("isStory"):
        meta.append("STORY")
    if w.get("isBlocked"):
        meta.append("BLOCKED")
    if tags:
        meta.append(f"tags=[{tags}]")
    line = f"- {' '.join(bits)}" + (f"  ({', '.join(meta)})" if meta else "")
    if detailed and w.get("description"):
        desc = w["description"].strip().replace("\n", " ")
        line += f"\n    {desc[:200]}"
    return line


def format_list(items: list, kind: str, fmt: str = "concise") -> str:
    """fmt: 'json' | 'concise' | 'detailed'."""
    if fmt == "json":
        return as_json(items)
    if not items:
        return f"_No {kind} found._"
    lines = [f"### {len(items)} {kind}"]
    for it in items:
        if kind == "projects":
            lines.append(project_row(it))
        elif kind == "work items":
            lines.append(workitem_line(it, detailed=(fmt == "detailed")))
        else:
            name = it.get("name") or it.get("title") or it.get("text") or str(it)
            ident = (it.get(f"{kind[:-1]}Id") or it.get("id") or it.get("stageId")
                     or it.get("categoryId") or it.get("tagId") or it.get("milestoneId")
                     or it.get("boardId") or it.get("importanceLevelId"))
            extra = f" (id={ident})" if ident is not None else ""
            status = f" [{it['status']}]" if it.get("status") else ""
            lines.append(f"- {name}{extra}{status}")
    return cap("\n".join(lines))
