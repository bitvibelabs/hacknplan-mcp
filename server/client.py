"""Async HTTP client for the HacknPlan API v0.

Encapsulates everything verified live on 2026-05-30 (see docs/API_REFERENCE.md):
- Auth header `Authorization: ApiKey <key>`
- Global rate-limit throttle (5 req/s) + retry on 429/5xx
- Tolerance for BARE-ARRAY list responses (not a {items,total} envelope)
- Empty-body 404 handling and the generic 400 "Invalid values object." message
- Plain-scalar bodies (sub-task title string, tag/user id int) vs JSON-object bodies
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

BASE_URL = "https://api.hacknplan.com/v0"
MIN_INTERVAL = 0.22          # ≥5 req/s headroom (limit is 5/s per IP)
MAX_RETRIES = 4
RETRY_BACKOFF = (0.5, 1.0, 2.0, 4.0)
TIMEOUT = 30.0


class HacknPlanError(Exception):
    """Raised on a non-retryable API error. `.status` + `.body` carry detail."""

    def __init__(self, status: int, body: Any, method: str, path: str):
        self.status = status
        self.body = body
        self.method = method
        self.path = path
        msg = body.get("message") if isinstance(body, dict) else (body or "(empty body)")
        if isinstance(body, dict) and isinstance(body.get("modelState"), dict):
            msg = f"{msg} {json.dumps(body['modelState'])}"
        super().__init__(f"{method} {path} -> HTTP {status}: {msg}")


class HacknPlanClient:
    """Thin async wrapper. One instance per server process; serializes calls
    through a lock so the global rate-limit throttle is honored across tools."""

    def __init__(self, api_key: str, base_url: str = BASE_URL):
        if not api_key:
            raise ValueError("HACKNPLAN_API_KEY is required")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._client: httpx.AsyncClient | None = None

    async def _ensure(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=TIMEOUT,
                headers={"Authorization": f"ApiKey {self._key}", "Accept": "application/json"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _throttle(self) -> None:
        now = time.monotonic()
        wait = MIN_INTERVAL - (now - self._last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = time.monotonic()

    async def request(self, method: str, path: str, *, json_body: Any = None,
                      params: dict | None = None) -> Any:
        """Perform one API call. `json_body` may be a dict/list (JSON object),
        or a bare str/int/bool (HacknPlan uses scalar bodies for sub-tasks,
        comments, tag/user attach). Returns parsed JSON (dict|list) or None for
        an empty 2xx body. Raises HacknPlanError on a non-2xx, non-retryable status."""
        client = await self._ensure()
        url = self._base + path
        content = None
        headers: dict[str, str] = {}
        if json_body is not None:
            content = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            async with self._lock:
                await self._throttle()
                try:
                    resp = await client.request(method, url, content=content,
                                                params=params, headers=headers)
                except httpx.HTTPError as e:
                    last_exc = e
                    resp = None
            if resp is None:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
                    continue
                raise HacknPlanError(0, f"network error: {last_exc}", method, path)

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
                    continue

            if 200 <= resp.status_code < 300:
                text = resp.text
                if not text:
                    return None
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    return text

            body: Any
            try:
                body = resp.json() if resp.text else None
            except json.JSONDecodeError:
                body = resp.text
            raise HacknPlanError(resp.status_code, body, method, path)

        raise HacknPlanError(0, "exhausted retries", method, path)

    async def get(self, path: str, params: dict | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json_body: Any = None) -> Any:
        return await self.request("POST", path, json_body=json_body)

    async def put(self, path: str, json_body: Any = None) -> Any:
        return await self.request("PUT", path, json_body=json_body)

    async def patch(self, path: str, json_body: Any = None) -> Any:
        return await self.request("PATCH", path, json_body=json_body)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)

    @staticmethod
    def as_list(resp: Any) -> list:
        """Normalize a list response that may be a bare array OR a paged
        envelope ({items|results: [...]}) into a plain list."""
        if resp is None:
            return []
        if isinstance(resp, list):
            return resp
        if isinstance(resp, dict):
            for key in ("items", "results", "data"):
                if isinstance(resp.get(key), list):
                    return resp[key]
        return []
