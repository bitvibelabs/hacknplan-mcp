"""Smoke test: the MCP server must boot over stdio and advertise its tools.

This catches the class of bug where a tool registers in-process but fails to
serialize to the wire `tools/list` (which happened once during development). It
launches the actual server as a subprocess, does the JSON-RPC handshake, and
asserts the tool catalog is served. No HacknPlan key needed (no API calls).

The handshake keeps stdin OPEN and reads stdout incrementally until the
tools/list response arrives, then terminates the process. Closing stdin up front
(the obvious `subprocess.run(input=...)` approach) lets the MCP stdio server's
EOF-triggered shutdown race ahead of emitting the response on a cold/slow runner
— which made this flaky in CI while passing locally. Reading-then-terminating
removes the race.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time

ROOT = os.path.join(os.path.dirname(__file__), "..")
SERVER = os.path.join(ROOT, "server", "hacknplan_server.py")

# tools that MUST be present (the headline surface — guards against silent drops)
REQUIRED = {
    "hacknplan_whoami", "list_projects", "create_work_item", "update_work_item",
    "create_stage", "create_design_element", "add_dependency", "log_work",
    "migrate_preview", "migrate_execute", "portfolio_overview", "schedule_overview",
}


def _list_tools_over_stdio(deadline_s: float = 30.0):
    """Boot the server, handshake, and return the tool names on the wire.

    Keeps stdin open and reads stdout line-by-line (on a daemon thread, so a
    silent server can't hang the test) until the `id:2` tools/list result lands
    or the deadline passes. Then it tears the process down.
    """
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    payload = "".join(json.dumps(m) + "\n" for m in messages)
    env = dict(os.environ, HACKNPLAN_API_KEY="x")
    proc = subprocess.Popen(
        [sys.executable, SERVER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1, env=env,
    )

    lines: "queue.Queue[str | None]" = queue.Queue()

    def _reader():
        try:
            for raw in proc.stdout:          # yields complete lines until stdout EOF
                lines.put(raw)
        finally:
            lines.put(None)                  # sentinel: stream closed

    threading.Thread(target=_reader, daemon=True).start()

    names: list[str] = []
    try:
        proc.stdin.write(payload)            # do NOT close stdin yet
        proc.stdin.flush()

        end = time.monotonic() + deadline_s
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = lines.get(timeout=remaining)
            except queue.Empty:
                break
            if raw is None:                  # server closed stdout
                break
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == 2 and "result" in msg:
                names = [t["name"] for t in msg["result"]["tools"]]
                break
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return names


def test_server_serves_tools_over_wire():
    names = _list_tools_over_stdio()
    assert names, "server returned no tools/list response over stdio"
    assert len(names) >= 60, f"expected >=60 tools, got {len(names)}"


def test_required_tools_present_on_wire():
    names = set(_list_tools_over_stdio())
    missing = REQUIRED - names
    assert not missing, f"required tools missing from wire tools/list: {sorted(missing)}"


def test_no_duplicate_tool_names():
    names = _list_tools_over_stdio()
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate tool names on the wire: {sorted(dupes)}"
