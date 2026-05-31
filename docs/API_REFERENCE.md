# HacknPlan API v0 — Ground-Truth Reference

**Verified live against `https://api.hacknplan.com/v0` (Personal Plus tier), 2026-05.** This reflects the
API's actual behaviour, which the published OpenAPI spec is misleading about in several places (noted below).
The full OpenAPI 2.0 spec is fetchable from `https://api.hacknplan.com/swagger/docs/v0` (67 paths, 91 definitions).

## Base + auth
- **Base URL:** `https://api.hacknplan.com/v0`
- **Auth header:** `Authorization: ApiKey <key>` (literal `ApiKey`, space, key)
- **Content-Type:** `application/json` for bodies. Missing it on a POST → **500**.
- **No auth → 401** `{"message":"Authorization has been denied for this request."}`
- **Rate limit:** 5 req/s per IP → 429. Client enforces a global ≥0.22 s spacing + retry on 429/5xx.

## Three traps that cost the most time (READ THIS)

**1. `costMetric` = the STRING `"Hours"` or `"Points"`** (capitalized) on `POST /projects`. The spec
types it as a plain `string` with no enum (misleading) — only those two pass. Else →
`400 {"message":"The request is invalid.","modelState":{"costMetric":["The cost metric is invalid."]}}`.
A *malformed* body gives the terser `400 "Invalid values object."` — send well-formed JSON to get the
useful `modelState` field errors. Response echoes `costMetric` back **lowercased** (`"hours"`).
```jsonc
POST /v0/projects → 201   { "name": "X", "costMetric": "Hours", "hoursPerDay": 8, "description": "..." }
// workspaceId OPTIONAL, auto-assigned (echoed back as 0). Explicit workspaceId → 400 "The workspace is invalid."
```

**2. `POST /stages` REQUIRES both `color` AND `icon`** — omitting `icon` returns a bare **HTTP 500**
(empty body, no hint). Status enum is lowercase **`created` / `started` / `closed`** — `"completed"`
(or `Open`/`InProgress`/`Closed`) → `400`. (The default "Completed" stage reads back as `status:"closed"`.)
```jsonc
POST /v0/projects/{id}/stages → 201
{ "name": "✅ Done", "status": "closed", "isUnblocker": false, "color": "#61bd4f", "icon": "check" }
// icon values verified OK: inbox, wrench, check, circle, calendar, gamepad. MISSING icon = 500.
```

**3. `isBlocked` is effectively read-only** — PATCHing it returns 200 but the value does NOT stick (it's
derived from dependency links). Represent a Trello "⏸ Blocked" column as its own STAGE, not via `isBlocked`.

## Workspaces (READ-ONLY in the API)
`GET /v0/workspaces` returns **`[]` on a Personal/Personal-Plus account** even though the web UI shows a
"Personal workspace". That workspace is real (projects get a workspaceId) but the list endpoint only
surfaces Studio workspaces. `POST /workspaces` → **405** (creation is UI/Studio-only). **Don't block on empty workspaces.**

## Lists return BARE ARRAYS
Collection GETs (`/projects`, `/stages`, `/categories`, `/importancelevels`, `/boards`, `/tags`,
`/milestones`, comments, subtasks) return a **plain JSON array**, NOT a `{items,total}` envelope. Only the
work-item *search* (`GET /workitems`) uses a `{items,totalCount,...}` paged envelope.

## Errors
| Situation | Status | Body |
|---|---|---|
| Bad field values | 400 | `{"message":"The request is invalid.","modelState":{...}}` (use this!) |
| Malformed body | 400 | `"Invalid values object."` (terse, no fields) |
| No auth | 401 | `{"message":"Authorization has been denied..."}` |
| Unknown id | 404 | **empty body** |
| Wrong method on real path | 405 | `{"message":"...does not support http method 'POST'."}` |
| Missing Content-Type on POST | 500 | empty |
| Stage POST without icon | 500 | empty |

## Resource cheat-sheet (verified create bodies)
| Resource | Method + path | Required body | Notable optional |
|---|---|---|---|
| Project | `POST /projects` | `name`, `costMetric`("Hours"\|"Points") | `hoursPerDay`, `description`, `moduleConfig`, `template` |
| Stage | `POST /projects/{p}/stages` | `name`, `status`(created\|started\|closed), `isUnblocker`, **`color`, `icon`** | (icon/color de-facto required) |
| Category | `POST /projects/{p}/categories` | `name` | `color`, `icon` |
| Tag | `POST /projects/{p}/tags` | `name`, `displayIconOnly` | `color`, `icon` |
| Importance | `POST /projects/{p}/importancelevels` | `name` | `color`, `icon`, `isDefault` |
| Milestone | `POST /projects/{p}/milestones` | `name` | `dueDate`, `startDate`, `generalInfo` |
| Board | `POST /projects/{p}/boards` | `name` | `milestoneId`, `startDate`, `dueDate`, `description` |
| Work item | `POST /projects/{p}/workitems` | `title`, `isStory`, `estimatedCost`, `importanceLevelId` | `categoryId`, `description`, `parentId`, `boardId`, `startDate`, `dueDate`, `assignedUserIds[]`, `tagIds[]`, **`subTasks[]`** (string array = checklist), `dependencyIds[]` |
| Sub-task | `POST /workitems/{w}/subtasks` | **plain string** body (the title) | — |
| Comment | `POST /workitems/{w}/comments` | **plain string** body (≤5000, markdown) | — |
| Attach tag | `POST /workitems/{w}/tags` | **plain int** (tagId) | — |
| Assign user | `POST /workitems/{w}/users` | **plain int** (userId) | — |

## Default project scaffolding (auto-created)
- 1 board: **"Sprint 1"** (`isDefault:true`) — work items need `boardId` to show on the kanban.
- 4 stages: Planned(`created`) / In progress(`started`) / Testing(`started`) / Completed(`closed`).
- Categories incl. built-in **"User story"** (`categoryId:-1`) + game-dev set (Programming=1, Art, Design, Audio, Narrative…).
- Importance levels: Urgent(1)/High(2)/Normal(3,default)/Low(4) — required on every work item.
- New work items land in the **first** stage → PATCH `stageId` to move them.

## Checklists = sub-tasks (CONFIRMED — earlier "no checklists" was WRONG)
HacknPlan's "sub-tasks" ARE Trello-style checklists (official Dev Diary 4). Two ways: inline
`"subTasks":["a","b"]` in the work-item create body, or `POST /workitems/{w}/subtasks` with a plain-string
title (one per call). Sub-tasks have `{subTaskId, title, isCompleted, index}`; mark done via
`PATCH /workitems/{w}/subtasks/{s}` `{title, isCompleted:true}`.

## Endpoint inventory (67 paths — see openapi_v0.raw.json)
projects · projects/{p}/{boards,stages,categories,importancelevels,tags,milestones,workitems,
designelements,designelementtypes,users,roles,webhooks,events,files,metrics,storage} ·
workitems/{w}/{subtasks,comments,tags,users,attachments,dependencies,worklogs} · workspaces (GET only) ·
users/me · webhookevents · `/closure` endpoints for projects/boards/milestones.
