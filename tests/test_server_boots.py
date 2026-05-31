"""Smoke test: the MCP server must boot over stdio and advertise its tools.

This catches the class of bug where a tool registers in-process but fails to
serialize to the wire `tools/list` (which happened once during development). It
launches the actual server as a subprocess, does the JSON-RPC handshake, and
asserts the tool catalog is served. No HacknPlan key needed (no API calls).
"""
import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
SERVER = os.path.join(ROOT, "server", "hacknplan_server.py")

# tools that MUST be present (the headline surface — guards against silent drops)
REQUIRED = {
    "hacknplan_whoami", "list_projects", "create_work_item", "update_work_item",
    "create_stage", "create_design_element", "add_dependency", "log_work",
    "migrate_preview", "migrate_execute", "portfolio_overview", "schedule_overview",
}


def _list_tools_over_stdio():
    handshake = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "t", "version": "1"}}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]) + "\n"
    env = dict(os.environ, HACKNPLAN_API_KEY="x")
    proc = subprocess.run([sys.executable, SERVER], input=handshake,
                          capture_output=True, text=True, timeout=60, env=env)
    names = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 2 and "result" in msg:
            names = [t["name"] for t in msg["result"]["tools"]]
            break
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
