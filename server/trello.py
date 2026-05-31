"""Read-only Trello REST client — the migration SOURCE.

Only GET calls. Pulls the full structure of a board: lists, cards (with desc,
due, labels, members), checklists + check-items, and card comments. Used by
migrate.py to build a HacknPlan project per Trello board.
"""
from __future__ import annotations

import asyncio
import time

import httpx

TRELLO_BASE = "https://api.trello.com/1"
MIN_INTERVAL = 0.11          # Trello allows ~10 req/s per token; stay under it
TIMEOUT = 30.0


class TrelloError(Exception):
    pass


class TrelloClient:
    def __init__(self, api_key: str, token: str):
        if not api_key or not token:
            raise ValueError("TRELLO_API_KEY and TRELLO_TOKEN are required for migration")
        self._key = api_key
        self._token = token
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._client: httpx.AsyncClient | None = None

    async def _ensure(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=TIMEOUT)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, path: str, params: dict | None = None):
        client = await self._ensure()
        p = {"key": self._key, "token": self._token}
        if params:
            p.update(params)
        async with self._lock:
            wait = MIN_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            resp = await client.get(f"{TRELLO_BASE}{path}", params=p)
            self._last = time.monotonic()
        if resp.status_code != 200:
            raise TrelloError(f"GET {path} -> {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def me(self) -> dict:
        return await self._get("/members/me", {"fields": "username,fullName"})

    async def organizations(self) -> list[dict]:
        return await self._get("/members/me/organizations", {"fields": "displayName,name"})

    async def boards(self, include_closed: bool = False) -> list[dict]:
        filt = "all" if include_closed else "open"
        return await self._get("/members/me/boards",
                               {"filter": filt, "fields": "name,idOrganization,closed,desc"})

    async def lists(self, board_id: str) -> list[dict]:
        return await self._get(f"/boards/{board_id}/lists",
                               {"filter": "open", "fields": "name,pos,closed"})

    async def cards(self, board_id: str, include_archived: bool = False) -> list[dict]:
        """All cards on a board with the fields the migration needs, plus nested
        labels/checklists in one shot (Trello supports nested resource expansion)."""
        return await self._get(
            f"/boards/{board_id}/cards/{'all' if include_archived else 'open'}",
            {
                "fields": "name,desc,idList,due,dueComplete,closed,labels,pos,idMembers,shortUrl",
                "checklists": "all",
                "checklist_fields": "name",
                "checkItems": "all",
                "members": "true",
                "member_fields": "fullName,username",
            },
        )

    async def labels(self, board_id: str) -> list[dict]:
        return await self._get(f"/boards/{board_id}/labels",
                               {"fields": "name,color", "limit": "1000"})

    async def comments(self, card_id: str) -> list[dict]:
        """commentCard actions on a card (the card's comments), oldest-first."""
        actions = await self._get(f"/cards/{card_id}/actions",
                                  {"filter": "commentCard", "limit": "1000"})
        out = []
        for a in actions:
            text = (a.get("data") or {}).get("text")
            who = (a.get("memberCreator") or {}).get("fullName") or ""
            when = a.get("date", "")
            if text:
                out.append({"text": text, "author": who, "date": when})
        return list(reversed(out))  # oldest first
