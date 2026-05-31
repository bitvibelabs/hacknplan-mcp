#!/usr/bin/env python3
"""HacknPlan MCP server (FastMCP).

Wraps the HacknPlan API v0 and bundles a Trello->HacknPlan migration engine.
Reads credentials from the environment:
  HACKNPLAN_API_KEY   (required)  — `Authorization: ApiKey <key>`
  TRELLO_API_KEY      (optional)  — only needed for the migration tools
  TRELLO_TOKEN        (optional)  — only needed for the migration tools

Tool design follows the mcp-builder guidance: workflow-oriented, names-over-ids
where practical, bounded high-signal output, actionable errors. All endpoints &
shapes verified live (see docs/API_REFERENCE.md).
"""
from __future__ import annotations

import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from client import HacknPlanClient, HacknPlanError  # noqa: E402
from formatting import as_json, format_list  # noqa: E402
from migrate import Migrator  # noqa: E402
from portfolio import portfolio as _portfolio, to_markdown as _portfolio_md  # noqa: E402
from trello import TrelloClient  # noqa: E402

mcp = FastMCP("hacknplan")

_hp: Optional[HacknPlanClient] = None
_trello: Optional[TrelloClient] = None


def hp() -> HacknPlanClient:
    global _hp
    if _hp is None:
        _hp = HacknPlanClient(os.environ.get("HACKNPLAN_API_KEY", ""))
    return _hp


def trello() -> TrelloClient:
    global _trello
    if _trello is None:
        _trello = TrelloClient(os.environ.get("TRELLO_API_KEY", ""),
                               os.environ.get("TRELLO_TOKEN", ""))
    return _trello


def _err(e: Exception) -> str:
    """Turn an exception into an actionable, LLM-friendly message."""
    if isinstance(e, HacknPlanError):
        hint = ""
        if e.status == 400:
            hint = (" — body schema mismatch. Note: project costMetric must be the STRING"
                    " 'Hours' or 'Points'; stage status must be 'created'/'started'/'completed'"
                    " (lowercase); work items require title+isStory+estimatedCost+importanceLevelId.")
        elif e.status == 401:
            hint = " — check HACKNPLAN_API_KEY."
        elif e.status == 404:
            hint = " — id not found (404 bodies are empty)."
        elif e.status == 429:
            hint = " — rate limited (5 req/s); retried automatically, still failing."
        return f"HacknPlan API error: {e}{hint}"
    return f"Error: {type(e).__name__}: {e}"


# ===================== READ / INTROSPECT =====================

@mcp.tool()
async def hacknplan_whoami() -> str:
    """Return the authenticated HacknPlan user (id, username, email, name).
    Use first to confirm the API key works."""
    try:
        return as_json(await hp().get("/users/me"))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_workspaces() -> str:
    """List HacknPlan workspaces visible to the API key.
    NOTE: Personal/Personal-Plus accounts return an empty list even though a
    'Personal workspace' exists in the web UI — projects still work and are
    auto-assigned to it. Only Studio workspaces appear here."""
    try:
        return format_list(HacknPlanClient.as_list(await hp().get("/workspaces")), "workspaces")
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_projects(format: str = "concise") -> str:
    """List all HacknPlan projects. format: 'concise' | 'detailed' | 'json'."""
    try:
        return format_list(HacknPlanClient.as_list(await hp().get("/projects")), "projects", format)
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_project(project_id: int) -> str:
    """Get one project with its stages, categories, importance levels and boards
    rolled up — the structural overview you need before creating work items."""
    try:
        base = f"/projects/{project_id}"
        out = {
            "project": await hp().get(base),
            "stages": HacknPlanClient.as_list(await hp().get(f"{base}/stages")),
            "categories": HacknPlanClient.as_list(await hp().get(f"{base}/categories")),
            "importanceLevels": HacknPlanClient.as_list(await hp().get(f"{base}/importancelevels")),
            "boards": HacknPlanClient.as_list(await hp().get(f"{base}/boards")),
        }
        return as_json(out)
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_stages(project_id: int, format: str = "concise") -> str:
    """List a project's stages (kanban columns). status is created|started|completed."""
    try:
        return format_list(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/stages")), "stages", format)
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_categories(project_id: int, format: str = "concise") -> str:
    """List a project's work-item categories."""
    try:
        return format_list(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/categories")), "categories", format)
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_tags(project_id: int, format: str = "concise") -> str:
    """List a project's tags."""
    try:
        return format_list(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/tags")), "tags", format)
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_boards(project_id: int, format: str = "concise") -> str:
    """List a project's boards (sprints/kanban boards). The default is 'Sprint 1'."""
    try:
        return format_list(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/boards")), "boards", format)
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_milestones(project_id: int, format: str = "concise") -> str:
    """List a project's milestones (release/epic groupings)."""
    try:
        return format_list(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/milestones")), "milestones", format)
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_work_items(project_id: int, board_id: Optional[int] = None,
                          stage_id: Optional[int] = None, category_id: Optional[int] = None,
                          milestone_id: Optional[int] = None, limit: int = 50,
                          offset: int = 0, format: str = "concise") -> str:
    """List/search a project's work items. Optional filters: board_id, stage_id,
    category_id, milestone_id. Paginated via limit/offset. format: concise|detailed|json."""
    try:
        params: dict = {"limit": limit, "offset": offset}
        for k, v in (("boardId", board_id), ("stageId", stage_id),
                     ("categoryId", category_id), ("milestoneId", milestone_id)):
            if v is not None:
                params[k] = v
        resp = await hp().get(f"/projects/{project_id}/workitems", params=params)
        return format_list(HacknPlanClient.as_list(resp), "work items", format)
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_work_item(project_id: int, work_item_id: int) -> str:
    """Get one work item with its sub-tasks (checklist) and comments."""
    try:
        base = f"/projects/{project_id}/workitems/{work_item_id}"
        out = {
            "workItem": await hp().get(base),
            "subTasks": HacknPlanClient.as_list(await hp().get(f"{base}/subtasks")),
            "comments": HacknPlanClient.as_list(await hp().get(f"{base}/comments")),
        }
        return as_json(out)
    except Exception as e:
        return _err(e)


# ===================== WRITE / WORKFLOW =====================

@mcp.tool()
async def create_project(name: str, cost_metric: str = "Hours", hours_per_day: float = 8,
                         description: str = "") -> str:
    """Create a project. cost_metric is the STRING "Hours" or "Points" (capitalized;
    any other value -> 400 "The cost metric is invalid."). workspaceId is auto-assigned
    to your personal workspace (echoed back as 0). Returns the new project."""
    try:
        if cost_metric not in ("Hours", "Points"):
            return "Error: cost_metric must be 'Hours' or 'Points'."
        body = {"name": name, "costMetric": cost_metric, "hoursPerDay": hours_per_day}
        if description:
            body["description"] = description
        return as_json(await hp().post("/projects", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def create_stage(project_id: int, name: str, status: str = "created",
                       color: str = "#3498db", is_unblocker: bool = False) -> str:
    """Create a kanban stage. status must be one of (lowercase): created | started | completed."""
    try:
        if status not in ("created", "started", "completed"):
            return "Error: status must be 'created', 'started', or 'completed' (lowercase)."
        body = {"name": name, "status": status, "isUnblocker": is_unblocker, "color": color}
        return as_json(await hp().post(f"/projects/{project_id}/stages", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def create_category(project_id: int, name: str, color: str = "#3498db") -> str:
    """Create a work-item category."""
    try:
        return as_json(await hp().post(f"/projects/{project_id}/categories", {"name": name, "color": color}))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def create_tag(project_id: int, name: str, color: str = "#b3bac5") -> str:
    """Create a tag (label)."""
    try:
        return as_json(await hp().post(f"/projects/{project_id}/tags",
                                       {"name": name, "color": color, "displayIconOnly": False}))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def create_milestone(project_id: int, name: str, due_date: str = "",
                           general_info: str = "") -> str:
    """Create a milestone. due_date is ISO 8601 (e.g. '2026-06-30T00:00:00Z')."""
    try:
        body = {"name": name}
        if due_date:
            body["dueDate"] = due_date
        if general_info:
            body["generalInfo"] = general_info
        return as_json(await hp().post(f"/projects/{project_id}/milestones", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def create_work_item(project_id: int, title: str, importance_level_id: int,
                           category_id: Optional[int] = None, description: str = "",
                           estimated_cost: float = 0, is_story: bool = False,
                           board_id: Optional[int] = None, due_date: str = "",
                           tag_ids: Optional[list[int]] = None,
                           sub_tasks: Optional[list[str]] = None,
                           stage_id: Optional[int] = None) -> str:
    """Create a work item (task or user story).
    Required: title + importance_level_id (get it from get_project/list_* — required by the API).
    category_id is required for tasks (not user stories). sub_tasks is a list of
    checklist item titles (native HacknPlan sub-tasks). due_date is ISO 8601.
    If stage_id is given, the item is moved to that stage after creation
    (the API always creates new items in the default/first stage)."""
    try:
        body: dict = {"title": title, "isStory": is_story, "estimatedCost": estimated_cost,
                      "importanceLevelId": importance_level_id}
        if category_id is not None and not is_story:
            body["categoryId"] = category_id
        if description:
            body["description"] = description
        if board_id is not None:
            body["boardId"] = board_id
        if due_date:
            body["dueDate"] = due_date
        if tag_ids:
            body["tagIds"] = tag_ids
        if sub_tasks:
            body["subTasks"] = sub_tasks
        wi = await hp().post(f"/projects/{project_id}/workitems", body)
        if stage_id is not None:
            wi = await hp().patch(f"/projects/{project_id}/workitems/{wi['workItemId']}",
                                  {"stageId": stage_id})
        return as_json(wi)
    except Exception as e:
        return _err(e)


@mcp.tool()
async def update_work_item(project_id: int, work_item_id: int,
                           stage_id: Optional[int] = None, title: Optional[str] = None,
                           description: Optional[str] = None, due_date: Optional[str] = None,
                           is_blocked: Optional[bool] = None,
                           tag_ids: Optional[list[int]] = None) -> str:
    """Partially update a work item (move stage, retitle, set due date, block, retag)."""
    try:
        body: dict = {}
        for k, v in (("stageId", stage_id), ("title", title), ("description", description),
                     ("dueDate", due_date), ("isBlocked", is_blocked), ("tagIds", tag_ids)):
            if v is not None:
                body[k] = v
        if not body:
            return "Error: provide at least one field to update."
        return as_json(await hp().patch(f"/projects/{project_id}/workitems/{work_item_id}", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def add_subtask(project_id: int, work_item_id: int, title: str) -> str:
    """Add one sub-task (checklist item) to a work item."""
    try:
        return as_json(await hp().post(f"/projects/{project_id}/workitems/{work_item_id}/subtasks", title))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def add_comment(project_id: int, work_item_id: int, text: str) -> str:
    """Add a comment to a work item (markdown supported, max 5000 chars)."""
    try:
        return as_json(await hp().post(f"/projects/{project_id}/workitems/{work_item_id}/comments", text[:5000]))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def delete_work_item(project_id: int, work_item_id: int, confirm: bool = False) -> str:
    """Delete a work item. Destructive — set confirm=true to proceed."""
    if not confirm:
        return "Refused: deletion is destructive. Re-call with confirm=true to delete."
    try:
        await hp().delete(f"/projects/{project_id}/workitems/{work_item_id}")
        return f"Deleted work item {work_item_id}."
    except Exception as e:
        return _err(e)


@mcp.tool()
async def delete_project(project_id: int, confirm: bool = False) -> str:
    """Delete an ENTIRE project and everything in it. Destructive — set confirm=true."""
    if not confirm:
        return "Refused: deleting a project removes ALL its work items, stages, etc. Re-call with confirm=true."
    try:
        await hp().delete(f"/projects/{project_id}")
        return f"Deleted project {project_id}."
    except Exception as e:
        return _err(e)


# ===================== MIGRATION WORKFLOW =====================

@mcp.tool()
async def migrate_preview(scope: str = "all", include_archived: bool = False,
                          checklist_mode: str = "userstory") -> str:
    """DRY RUN (zero writes). Preview a Trello->HacknPlan migration.
    scope: 'all' | 'workspace:<name>' | 'board:<name or id>'.
    checklist_mode: 'userstory' (card->user story, each item a child work item) |
                    'subtasks' (native HacknPlan checklist, preserves checked state) |
                    'markdown' (items appended to the description).
    Returns the full plan: per board the projects/stages/tags/work-item/checklist
    counts and which boards are already migrated. Run this first."""
    try:
        return as_json(await Migrator(hp(), trello()).preview(scope, include_archived, checklist_mode))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def migrate_execute(scope: str = "all", include_archived: bool = False,
                          checklist_mode: str = "userstory",
                          board_limit: Optional[int] = None) -> str:
    """EXECUTE a Trello->HacknPlan migration. Idempotent (a ledger skips already-
    migrated boards/cards, so re-running is safe and resumes). Start with a single
    board (scope='board:<name>') to validate, then scope='all'. board_limit caps
    how many boards this call processes. See migrate_preview for the mapping/options."""
    try:
        return as_json(await Migrator(hp(), trello()).execute(scope, include_archived, checklist_mode, board_limit))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def migration_status() -> str:
    """Show the migration ledger: which Trello boards have been migrated to which
    HacknPlan projects, and how many stages/tags/cards were created."""
    try:
        return as_json(Migrator(hp(), trello()).status())
    except Exception as e:
        return _err(e)


# ===================== MASTER DATA: UPDATE / DELETE =====================

@mcp.tool()
async def update_stage(project_id: int, stage_id: int, name: str, status: str,
                       is_unblocker: bool = False, color: Optional[str] = None,
                       icon: Optional[str] = None) -> str:
    """Update a kanban stage (re-name / re-color / re-icon / change status).
    status: created | started | closed (lowercase). color is hex; icon is a
    HacknPlan icon name (e.g. inbox, wrench, check, rocket, eye, ban)."""
    try:
        if status not in ("created", "started", "closed"):
            return "Error: status must be 'created', 'started', or 'closed'."
        body = {"name": name, "status": status, "isUnblocker": is_unblocker}
        if color:
            body["color"] = color
        if icon:
            body["icon"] = icon
        return as_json(await hp().patch(f"/projects/{project_id}/stages/{stage_id}", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def delete_stage(project_id: int, stage_id: int, confirm: bool = False) -> str:
    """Delete a stage. Destructive (a project needs >=3 stages, one per status). confirm=true required."""
    if not confirm:
        return "Refused: deleting a stage is destructive. Re-call with confirm=true."
    try:
        await hp().delete(f"/projects/{project_id}/stages/{stage_id}")
        return f"Deleted stage {stage_id}."
    except Exception as e:
        return _err(e)


@mcp.tool()
async def update_category(project_id: int, category_id: int, name: str,
                          color: Optional[str] = None, icon: Optional[str] = None) -> str:
    """Update a work-item category (re-name / re-color / re-icon)."""
    try:
        body = {"name": name}
        if color:
            body["color"] = color
        if icon:
            body["icon"] = icon
        return as_json(await hp().patch(f"/projects/{project_id}/categories/{category_id}", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def delete_category(project_id: int, category_id: int, confirm: bool = False) -> str:
    """Delete a work-item category. Destructive. confirm=true required.
    (Useful to remove the game-dev defaults — Audio, Narrative, etc.)"""
    if not confirm:
        return "Refused: deleting a category is destructive. Re-call with confirm=true."
    try:
        await hp().delete(f"/projects/{project_id}/categories/{category_id}")
        return f"Deleted category {category_id}."
    except Exception as e:
        return _err(e)


@mcp.tool()
async def update_tag(project_id: int, tag_id: int, name: str, color: Optional[str] = None,
                     display_icon_only: bool = False, icon: Optional[str] = None) -> str:
    """Update a tag (re-name / re-color / re-icon / toggle icon-only display)."""
    try:
        body = {"name": name, "displayIconOnly": display_icon_only}
        if color:
            body["color"] = color
        if icon:
            body["icon"] = icon
        return as_json(await hp().patch(f"/projects/{project_id}/tags/{tag_id}", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def delete_tag(project_id: int, tag_id: int, confirm: bool = False) -> str:
    """Delete a tag. Destructive (removes it from all work items). confirm=true required."""
    if not confirm:
        return "Refused: deleting a tag is destructive. Re-call with confirm=true."
    try:
        await hp().delete(f"/projects/{project_id}/tags/{tag_id}")
        return f"Deleted tag {tag_id}."
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_importance_levels(project_id: int, format: str = "concise") -> str:
    """List a project's importance/priority levels (Urgent/High/Normal/Low by default)."""
    try:
        return format_list(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/importancelevels")), "importanceLevels", format)
    except Exception as e:
        return _err(e)


@mcp.tool()
async def create_importance_level(project_id: int, name: str, color: Optional[str] = None,
                                  icon: Optional[str] = None, is_default: bool = False) -> str:
    """Create an importance/priority level (color+icon)."""
    try:
        body = {"name": name, "isDefault": is_default}
        if color:
            body["color"] = color
        if icon:
            body["icon"] = icon
        return as_json(await hp().post(f"/projects/{project_id}/importancelevels", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def update_importance_level(project_id: int, importance_level_id: int, name: str,
                                  color: Optional[str] = None, icon: Optional[str] = None,
                                  is_default: bool = False) -> str:
    """Update an importance level (re-name / re-color / re-icon / set default)."""
    try:
        body = {"name": name, "isDefault": is_default}
        if color:
            body["color"] = color
        if icon:
            body["icon"] = icon
        return as_json(await hp().patch(f"/projects/{project_id}/importancelevels/{importance_level_id}", body))
    except Exception as e:
        return _err(e)


# ===================== TAGS / USERS ON A WORK ITEM =====================

@mcp.tool()
async def attach_tag(project_id: int, work_item_id: int, tag_id: int) -> str:
    """Attach an existing tag to a work item."""
    try:
        await hp().post(f"/projects/{project_id}/workitems/{work_item_id}/tags", tag_id)
        return f"Attached tag {tag_id} to work item {work_item_id}."
    except Exception as e:
        return _err(e)


@mcp.tool()
async def detach_tag(project_id: int, work_item_id: int, tag_id: int) -> str:
    """Remove a tag from a work item."""
    try:
        await hp().delete(f"/projects/{project_id}/workitems/{work_item_id}/tags/{tag_id}")
        return f"Detached tag {tag_id} from work item {work_item_id}."
    except Exception as e:
        return _err(e)


@mcp.tool()
async def assign_user(project_id: int, work_item_id: int, user_id: int) -> str:
    """Assign a project user to a work item."""
    try:
        await hp().post(f"/projects/{project_id}/workitems/{work_item_id}/users", user_id)
        return f"Assigned user {user_id} to work item {work_item_id}."
    except Exception as e:
        return _err(e)


@mcp.tool()
async def unassign_user(project_id: int, work_item_id: int, user_id: int) -> str:
    """Remove a user assignment from a work item."""
    try:
        await hp().delete(f"/projects/{project_id}/workitems/{work_item_id}/users/{user_id}")
        return f"Unassigned user {user_id} from work item {work_item_id}."
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_project_users(project_id: int) -> str:
    """List the members of a project (id, username)."""
    try:
        return as_json(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/users")))
    except Exception as e:
        return _err(e)


# ===================== SUB-TASKS (checklist) =====================

@mcp.tool()
async def list_subtasks(project_id: int, work_item_id: int) -> str:
    """List a work item's sub-tasks (its checklist), with completion state."""
    try:
        return as_json(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/workitems/{work_item_id}/subtasks")))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def update_subtask(project_id: int, work_item_id: int, subtask_id: int,
                         title: str, is_completed: Optional[bool] = None) -> str:
    """Update a sub-task (rename and/or mark complete/incomplete)."""
    try:
        body = {"title": title}
        if is_completed is not None:
            body["isCompleted"] = is_completed
        return as_json(await hp().patch(f"/projects/{project_id}/workitems/{work_item_id}/subtasks/{subtask_id}", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def delete_subtask(project_id: int, work_item_id: int, subtask_id: int, confirm: bool = False) -> str:
    """Delete a sub-task. confirm=true required."""
    if not confirm:
        return "Refused: re-call with confirm=true."
    try:
        await hp().delete(f"/projects/{project_id}/workitems/{work_item_id}/subtasks/{subtask_id}")
        return f"Deleted sub-task {subtask_id}."
    except Exception as e:
        return _err(e)


# ===================== DEPENDENCIES =====================

@mcp.tool()
async def list_dependencies(project_id: int, work_item_id: int) -> str:
    """List a work item's dependencies (the predecessors that block it)."""
    try:
        return as_json(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/workitems/{work_item_id}/dependencies")))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def add_dependency(project_id: int, work_item_id: int, predecessor_id: int) -> str:
    """Make work_item_id depend on (be blocked by) predecessor_id. The successor
    can't be completed until the predecessor is done."""
    try:
        return as_json(await hp().post(f"/projects/{project_id}/workitems/{work_item_id}/dependencies", predecessor_id))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def remove_dependency(project_id: int, work_item_id: int, dependency_id: int, confirm: bool = False) -> str:
    """Remove a dependency from a work item. confirm=true required."""
    if not confirm:
        return "Refused: re-call with confirm=true."
    try:
        await hp().delete(f"/projects/{project_id}/workitems/{work_item_id}/dependencies/{dependency_id}")
        return f"Removed dependency {dependency_id}."
    except Exception as e:
        return _err(e)


# ===================== WORK LOGS (time tracking) =====================

@mcp.tool()
async def list_work_logs(project_id: int, work_item_id: int) -> str:
    """List the work logs (time entries) on a work item."""
    try:
        return as_json(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/workitems/{work_item_id}/worklogs")))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def log_work(project_id: int, work_item_id: int, value: float, comment: str = "") -> str:
    """Log time/effort on a work item. value = amount worked, in the project's
    costMetric unit (hours or points). comment is an optional note. Logs can only
    be edited within ~1 hour of creation."""
    try:
        body = {"value": value}
        if comment:
            body["comment"] = comment
        return as_json(await hp().post(f"/projects/{project_id}/workitems/{work_item_id}/worklogs", body))
    except Exception as e:
        return _err(e)


# ===================== DESIGN MODEL (feature/knowledge tree) =====================

@mcp.tool()
async def list_design_element_types(project_id: int) -> str:
    """List the design-element TYPES (node categories of the design model, e.g.
    System / Module / Feature). Repurpose as a feature-tree taxonomy."""
    try:
        return as_json(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/designelementtypes")))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def create_design_element_type(project_id: int, name: str, color: Optional[str] = None,
                                     icon: Optional[str] = None) -> str:
    """Create a design-element type (a node category for the design/feature tree)."""
    try:
        body = {"name": name}
        if color:
            body["color"] = color
        if icon:
            body["icon"] = icon
        return as_json(await hp().post(f"/projects/{project_id}/designelementtypes", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_design_elements(project_id: int, type_id: Optional[int] = None) -> str:
    """List design elements (nodes of the design/feature/knowledge tree).
    Optionally filter by type_id."""
    try:
        path = f"/projects/{project_id}/designelements"
        if type_id is not None:
            path += f"?typeId={type_id}"
        return as_json(HacknPlanClient.as_list(await hp().get(path)))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_design_element(project_id: int, element_id: int) -> str:
    """Get one design element (with its documentation/description)."""
    try:
        return as_json(await hp().get(f"/projects/{project_id}/designelements/{element_id}"))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def create_design_element(project_id: int, type_id: int, name: str,
                                parent_id: Optional[int] = None, description: str = "") -> str:
    """Create a design element (a node in the design/feature tree). type_id is a
    design-element type id; parent_id nests it under another element (omit for a
    root). Link work items to it via create_work_item(design_element_id=...) or
    update_work_item — progress then rolls up the tree."""
    try:
        body = {"designElementTypeId": type_id, "name": name}
        if parent_id is not None:
            body["parentId"] = parent_id
        if description:
            body["description"] = description
        return as_json(await hp().post(f"/projects/{project_id}/designelements", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def update_design_element(project_id: int, element_id: int, type_id: int, name: str,
                               description: Optional[str] = None,
                               parent_id: Optional[int] = None) -> str:
    """Update a design element (rename, edit documentation, re-parent, change type).
    type_id and name are required by the API; pass the element's current values to
    keep them. Use get_design_element first to read them."""
    try:
        body = {"designElementTypeId": type_id, "name": name}
        if description is not None:
            body["description"] = description
        if parent_id is not None:
            body["parentId"] = parent_id
        return as_json(await hp().put(f"/projects/{project_id}/designelements/{element_id}", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def delete_design_element(project_id: int, element_id: int, confirm: bool = False) -> str:
    """Delete a design element (and its sub-tree). Destructive. confirm=true required."""
    if not confirm:
        return "Refused: deleting a design element removes its sub-tree. Re-call with confirm=true."
    try:
        await hp().delete(f"/projects/{project_id}/designelements/{element_id}")
        return f"Deleted design element {element_id}."
    except Exception as e:
        return _err(e)


# ===================== BOARDS / PROJECT / METRICS =====================

@mcp.tool()
async def create_board(project_id: int, name: str, milestone_id: Optional[int] = None,
                       start_date: str = "", due_date: str = "", description: str = "") -> str:
    """Create a board (sprint/iteration). Optionally nest under a milestone and set start/due dates (ISO 8601)."""
    try:
        body = {"name": name}
        if milestone_id is not None:
            body["milestoneId"] = milestone_id
        if start_date:
            body["startDate"] = start_date
        if due_date:
            body["dueDate"] = due_date
        if description:
            body["description"] = description
        return as_json(await hp().post(f"/projects/{project_id}/boards", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def close_board(project_id: int, board_id: int) -> str:
    """Close (end) a board/sprint."""
    try:
        await hp().post(f"/projects/{project_id}/boards/{board_id}/closure", {})
        return f"Closed board {board_id}."
    except Exception as e:
        return _err(e)


@mcp.tool()
async def update_project(project_id: int, name: Optional[str] = None,
                         description: Optional[str] = None,
                         cost_metric: Optional[str] = None) -> str:
    """Update a project's name / description / cost metric ("Hours" or "Points")."""
    try:
        body = {}
        for k, v in (("name", name), ("description", description), ("costMetric", cost_metric)):
            if v is not None:
                body[k] = v
        if not body:
            return "Error: provide at least one field."
        if "costMetric" in body and body["costMetric"] not in ("Hours", "Points"):
            return "Error: cost_metric must be 'Hours' or 'Points'."
        return as_json(await hp().patch(f"/projects/{project_id}", body))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_project_metrics(project_id: int) -> str:
    """Get a project's metrics (completion %, totals) — analytics Trello lacks."""
    try:
        return as_json(await hp().get(f"/projects/{project_id}/metrics"))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def get_milestone_metrics(project_id: int, milestone_id: int) -> str:
    """Get a milestone's metrics (burndown / completion)."""
    try:
        return as_json(await hp().get(f"/projects/{project_id}/milestones/{milestone_id}/metrics"))
    except Exception as e:
        return _err(e)


@mcp.tool()
async def list_attachments(project_id: int, work_item_id: int) -> str:
    """List the attachments on a work item."""
    try:
        return as_json(HacknPlanClient.as_list(await hp().get(f"/projects/{project_id}/workitems/{work_item_id}/attachments")))
    except Exception as e:
        return _err(e)


if __name__ == "__main__":
    mcp.run()


# ===================== PORTFOLIO BIRDS-EYE (cross-project) =====================

@mcp.tool()
async def portfolio_overview(format: str = "markdown") -> str:
    """ALL-PROJECTS birds-eye view -- the cross-project portfolio dashboard HacknPlan
    has no native equivalent for. Rolls up every project: completion %, open/closed
    counts, and urgent / blocked / due-soon / overdue flags, grouped by workspace
    (Personal / BitVibe / Projects). Use for 'how's everything doing', 'what's on
    fire across all projects', 'portfolio status'. format: 'markdown' | 'json'."""
    try:
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc)
        data = await _portfolio(hp(), now)
        if format == "json":
            return as_json(data)
        return _portfolio_md(data)
    except Exception as e:
        return _err(e)


if __name__ == "__main__":
    mcp.run()
