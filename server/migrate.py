"""Trello → HacknPlan migration engine.

Maps (verified live 2026-05-30, see docs/API_REFERENCE.md):
  Trello board  -> HacknPlan project (costMetric="Hours")
  Trello list   -> HacknPlan custom STAGE, 1:1, preserving the exact column name +
                   order. (Stage create REQUIRES both `color` AND `icon` — omitting
                   `icon` returns HTTP 500. Status enum lowercase: created/started/
                   completed.) The 4 game-dev default stages are deleted afterward.
  Trello label  -> HacknPlan tag
  Trello card   -> HacknPlan work item (title, desc, native dueDate, tags, stage)
  Trello "⏸ Blocked" list -> its own stage (blocked-ness is represented by the card
                   being in that stage; HacknPlan's `isBlocked` is derived from
                   dependencies and is not settable via PATCH, so we don't use it).
  Trello checklist item -> per checklist_mode:
        'userstory' : card becomes a user story, each item a child work item [default]
        'subtasks'  : native HacknPlan sub-task (1:1, preserves checked state)
        'markdown'  : items appended to the description as - [ ]/- [x]
  Trello comment -> HacknPlan work-item comment

Idempotent via a ledger (~/.claude/state/hacknplan_migration_ledger.json).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from client import HacknPlanClient, HacknPlanError
from trello import TrelloClient

LEDGER_PATH = Path(os.path.expanduser("~/.claude/state/hacknplan_migration_ledger.json"))

ST_CREATED = "created"
ST_STARTED = "started"
ST_COMPLETED = "closed"   # the API's completed-status enum value is literally "closed"

# Per-status stage icon (all verified-acceptable; "icon" is REQUIRED or POST 500s).
STATUS_ICON = {ST_CREATED: "inbox", ST_STARTED: "wrench", ST_COMPLETED: "check"}
STATUS_COLOR = {ST_CREATED: "#42526e", ST_STARTED: "#2780e3", ST_COMPLETED: "#61bd4f"}

TRELLO_COLOR_HEX = {
    "green": "#61bd4f", "yellow": "#f2d600", "orange": "#ff9f1a", "red": "#eb5a46",
    "purple": "#c377e0", "blue": "#0079bf", "sky": "#00c2e0", "lime": "#51e898",
    "pink": "#ff78cb", "black": "#344563", "green_dark": "#519839", "blue_dark": "#055a8c",
    "yellow_dark": "#d9b51c", "orange_dark": "#cd8313", "red_dark": "#b04632",
    "purple_dark": "#89609e", "pink_dark": "#c75b8b", "lime_dark": "#4bbf6b",
    "sky_dark": "#0098b7", None: "#b3bac5", "": "#b3bac5",
}


def infer_status(list_name: str) -> str:
    """HacknPlan stage status for a Trello list name (created|started|completed)."""
    n = list_name.lower()
    if any(k in n for k in ("done", "complete", "closed", "shipped", "✅")):
        return ST_COMPLETED
    if any(k in n for k in ("doing", "progress", "wip", "🚧", "review", "testing",
                            "active", "block", "⏸", "wait", "hold")):
        return ST_STARTED
    return ST_CREATED  # inbox / backlog / todo / this week / 🎯 / 📥


def _load_ledger() -> dict:
    if LEDGER_PATH.exists():
        try:
            return json.loads(LEDGER_PATH.read_text())
        except Exception:
            return {"boards": {}}
    return {"boards": {}}


def _save_ledger(led: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(led, indent=2))


class Migrator:
    def __init__(self, hp: HacknPlanClient, trello: TrelloClient):
        self.hp = hp
        self.trello = trello

    async def _resolve_boards(self, scope: str, include_archived: bool) -> list[dict]:
        boards = await self.trello.boards(include_closed=include_archived)
        orgs = {o["id"]: o.get("displayName", o.get("name", "")) for o in await self.trello.organizations()}
        for b in boards:
            b["_workspace"] = orgs.get(b.get("idOrganization"), "(no workspace)")
        scope = (scope or "all").strip()
        if scope == "all":
            return boards
        if scope.startswith("workspace:"):
            want = scope.split(":", 1)[1].strip().lower()
            return [b for b in boards if b["_workspace"].lower() == want]
        if scope.startswith("board:"):
            want = scope.split(":", 1)[1].strip().lower()
            return [b for b in boards if b["name"].lower() == want or b["id"] == want]
        return [b for b in boards if b["name"].lower() == scope.lower()]

    async def preview(self, scope: str, include_archived: bool, checklist_mode: str) -> dict:
        boards = await self._resolve_boards(scope, include_archived)
        led = _load_ledger()
        plan = {"scope": scope, "checklist_mode": checklist_mode, "projects": [], "totals": {}}
        tot_cards = tot_checks = tot_tags = 0
        for b in boards:
            lists = await self.trello.lists(b["id"])
            cards = await self.trello.cards(b["id"], include_archived=include_archived)
            labels = [l for l in await self.trello.labels(b["id"]) if l.get("name")]
            n_check = sum(len(ci.get("checkItems", [])) for c in cards for ci in c.get("checklists", []))
            already = led["boards"].get(b["id"], {}).get("hacknplan_project_id")
            plan["projects"].append({
                "trello_board": b["name"], "workspace": b["_workspace"],
                "already_migrated_project_id": already,
                "stages_from_lists": [{"list": l["name"], "status": infer_status(l["name"])} for l in lists],
                "tags_from_labels": [l["name"] for l in labels],
                "work_items": len(cards), "checklist_items": n_check})
            tot_cards += len(cards); tot_checks += n_check; tot_tags += len(labels)
        plan["totals"] = {"projects": len(boards), "work_items": tot_cards,
                          "checklist_items": tot_checks, "tags": tot_tags}
        return plan

    async def execute(self, scope: str, include_archived: bool, checklist_mode: str,
                      board_limit: int | None = None) -> dict:
        boards = await self._resolve_boards(scope, include_archived)
        if board_limit:
            boards = boards[:board_limit]
        led = _load_ledger()
        results = []
        for b in boards:
            try:
                results.append(await self._migrate_board(b, include_archived, checklist_mode, led))
            except Exception as e:
                results.append({"board": b["name"], "status": "error", "error": str(e)})
            _save_ledger(led)
        return {"scope": scope, "checklist_mode": checklist_mode, "results": results}

    async def _migrate_board(self, board: dict, include_archived: bool,
                             checklist_mode: str, led: dict) -> dict:
        bid = board["id"]
        entry = led["boards"].setdefault(bid, {"name": board["name"], "stages": {},
                                               "tags": {}, "cards": {}})
        log = {"board": board["name"], "workspace": board.get("_workspace"),
               "created": {"project": False, "stages": 0, "tags": 0, "work_items": 0,
                           "checklist_items": 0, "comments": 0, "default_stages_removed": 0},
               "skipped_cards": 0, "status": "ok"}

        # 1) project
        pid = entry.get("hacknplan_project_id")
        if pid:
            try:
                await self.hp.get(f"/projects/{pid}")
            except HacknPlanError:
                pid = None
        if not pid:
            desc = (board.get("desc") or "")[:1000]
            proj = await self.hp.post("/projects", {
                "name": board["name"], "costMetric": "Hours", "hoursPerDay": 8,
                "description": (f"Migrated from Trello board '{board['name']}'."
                                + (f"\n\n{desc}" if desc else ""))})
            pid = proj["id"]
            entry["hacknplan_project_id"] = pid
            log["created"]["project"] = True

        if "default_board_id" not in entry:
            bh = HacknPlanClient.as_list(await self.hp.get(f"/projects/{pid}/boards"))
            db = next((b for b in bh if b.get("isDefault")), bh[0] if bh else None)
            entry["default_board_id"] = db.get("boardId") if db else None
        board_id = entry["default_board_id"]

        imps = HacknPlanClient.as_list(await self.hp.get(f"/projects/{pid}/importancelevels"))
        imp_id = next((i["importanceLevelId"] for i in imps if i.get("isDefault")),
                      imps[len(imps) // 2]["importanceLevelId"] if imps else None)
        if "category_id" not in entry:
            cat = await self.hp.post(f"/projects/{pid}/categories", {"name": "Task", "color": "#3498db"})
            entry["category_id"] = cat["categoryId"]
        cat_id = entry["category_id"]

        # capture default stage ids to delete after the real ones exist
        default_stage_ids = []
        if not entry.get("defaults_cleared"):
            default_stage_ids = [s["stageId"] for s in
                                 HacknPlanClient.as_list(await self.hp.get(f"/projects/{pid}/stages"))]

        # 2) real custom stages, 1:1 with Trello lists (color+icon REQUIRED)
        lists = await self.trello.lists(bid)
        list_stage: dict[str, int] = {}
        completed_sid = None
        first_sid = None
        for lst in lists:
            status = infer_status(lst["name"])
            if lst["id"] not in entry["stages"]:
                stg = await self.hp.post(f"/projects/{pid}/stages", {
                    "name": lst["name"][:50], "status": status, "isUnblocker": False,
                    "color": STATUS_COLOR[status], "icon": STATUS_ICON[status]})
                entry["stages"][lst["id"]] = stg["stageId"]
                log["created"]["stages"] += 1
            sid = entry["stages"][lst["id"]]
            list_stage[lst["id"]] = sid
            if first_sid is None:
                first_sid = sid
            if status == ST_COMPLETED and completed_sid is None:
                completed_sid = sid

        # 3) tags from labels
        labels = [l for l in await self.trello.labels(bid) if l.get("name")]
        label_to_tag: dict[str, int] = {}
        for lab in labels:
            key = lab["name"]
            if key not in entry["tags"]:
                tag = await self.hp.post(f"/projects/{pid}/tags", {
                    "name": lab["name"], "displayIconOnly": False,
                    "color": TRELLO_COLOR_HEX.get(lab.get("color"), "#b3bac5")})
                entry["tags"][key] = tag["tagId"]
                log["created"]["tags"] += 1
            label_to_tag[lab["name"]] = entry["tags"][key]

        # 4) cards -> work items
        cards = await self.trello.cards(bid, include_archived=include_archived)
        for card in cards:
            if card["id"] in entry["cards"]:
                log["skipped_cards"] += 1
                continue
            wi_id = await self._migrate_card(pid, card, list_stage, label_to_tag,
                                             cat_id, imp_id, board_id, completed_sid,
                                             first_sid, checklist_mode, log)
            entry["cards"][card["id"]] = wi_id

        # 5) delete the 4 game-dev default stages (real Trello stages now cover all
        # statuses, so the min-3 rule holds). Best-effort.
        if default_stage_ids and not entry.get("defaults_cleared"):
            for sid in default_stage_ids:
                try:
                    await self.hp.delete(f"/projects/{pid}/stages/{sid}")
                    log["created"]["default_stages_removed"] += 1
                except HacknPlanError:
                    pass
            entry["defaults_cleared"] = True

        return log

    async def _migrate_card(self, pid: int, card: dict, list_stage: dict, label_to_tag: dict,
                            cat_id: int, imp_id: int, board_id: int | None, completed_sid: int | None,
                            first_sid: int | None, checklist_mode: str, log: dict) -> int:
        stage_id = list_stage.get(card.get("idList"), first_sid)
        tag_ids = [label_to_tag[l["name"]] for l in card.get("labels", []) if l.get("name") in label_to_tag]
        checklists = card.get("checklists", [])
        has_checks = any(cl.get("checkItems") for cl in checklists)
        is_story = checklist_mode == "userstory" and has_checks

        body: dict[str, Any] = {"title": (card["name"] or "(untitled)")[:255], "isStory": is_story,
                                "estimatedCost": 0, "importanceLevelId": imp_id}
        if board_id is not None:
            body["boardId"] = board_id
        desc = card.get("desc") or ""
        if card.get("shortUrl"):
            desc = (desc + f"\n\n_Migrated from Trello: {card['shortUrl']}_").strip()
        if not is_story:
            body["categoryId"] = cat_id
        if card.get("due"):
            body["dueDate"] = card["due"]
        if tag_ids:
            body["tagIds"] = tag_ids
        if has_checks and checklist_mode == "markdown":
            desc = (desc + "\n\n## Checklist\n" + _checklists_md(checklists)).strip()
        if has_checks and checklist_mode == "subtasks":
            body["subTasks"] = [t for t, _ in _flat_checkitems(checklists)]
        if desc:
            body["description"] = desc[:20000]

        wi = await self.hp.post(f"/projects/{pid}/workitems", body)
        wi_id = wi["workItemId"]
        log["created"]["work_items"] += 1

        # move to the right stage (create always lands in the first stage)
        if stage_id and (wi.get("stage") or {}).get("stageId") != stage_id:
            await self.hp.patch(f"/projects/{pid}/workitems/{wi_id}", {"stageId": stage_id})

        if has_checks and checklist_mode == "subtasks":
            subs = HacknPlanClient.as_list(await self.hp.get(f"/projects/{pid}/workitems/{wi_id}/subtasks"))
            done_titles = {t for t, c in _flat_checkitems(checklists) if c}
            for s in subs:
                log["created"]["checklist_items"] += 1
                if s.get("title") in done_titles and not s.get("isCompleted"):
                    await self.hp.patch(f"/projects/{pid}/workitems/{wi_id}/subtasks/{s['subTaskId']}",
                                        {"title": s["title"], "isCompleted": True})

        if is_story:
            for title, completed in _flat_checkitems(checklists):
                cb = {"title": title[:255], "isStory": False, "estimatedCost": 0,
                      "importanceLevelId": imp_id, "categoryId": cat_id, "parentId": wi_id}
                if board_id is not None:
                    cb["boardId"] = board_id
                child = await self.hp.post(f"/projects/{pid}/workitems", cb)
                log["created"]["checklist_items"] += 1
                if completed and completed_sid:
                    await self.hp.patch(f"/projects/{pid}/workitems/{child['workItemId']}",
                                        {"stageId": completed_sid})

        for cm in await self.trello.comments(card["id"]):
            text = cm["text"]
            if cm.get("author") or cm.get("date"):
                text = f"_{cm.get('author','')} · {cm.get('date','')[:10]}_\n\n{text}"
            await self.hp.post(f"/projects/{pid}/workitems/{wi_id}/comments", text[:5000])
            log["created"]["comments"] += 1

        return wi_id

    def status(self) -> dict:
        led = _load_ledger()
        out = []
        for _bid, e in led.get("boards", {}).items():
            out.append({"board": e.get("name"), "project_id": e.get("hacknplan_project_id"),
                        "stages": len(e.get("stages", {})), "tags": len(e.get("tags", {})),
                        "cards_migrated": len(e.get("cards", {}))})
        return {"ledger_path": str(LEDGER_PATH), "boards": out}


def _flat_checkitems(checklists: list) -> list[tuple[str, bool]]:
    out = []
    multi = len([c for c in checklists if c.get("checkItems")]) > 1
    for cl in checklists:
        for it in cl.get("checkItems", []):
            name = it.get("name", "")
            title = f"[{cl.get('name')}] {name}" if multi and cl.get("name") else name
            out.append((title[:255], it.get("state") == "complete"))
    return out


def _checklists_md(checklists: list) -> str:
    lines = []
    multi = len([c for c in checklists if c.get("checkItems")]) > 1
    for cl in checklists:
        if multi and cl.get("name"):
            lines.append(f"**{cl['name']}**")
        for it in cl.get("checkItems", []):
            box = "x" if it.get("state") == "complete" else " "
            lines.append(f"- [{box}] {it.get('name','')}")
    return "\n".join(lines)
