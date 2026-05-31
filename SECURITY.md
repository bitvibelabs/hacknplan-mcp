# Security

## Reporting a vulnerability

Found something? Email **dev@bitvibelabs.com** or open a private security advisory
on this repo. Please don't file public issues for undisclosed vulnerabilities.

## Threat model — what this server actually does

`hacknplan-mcp` runs as a **local stdio MCP server**. It:

- speaks JSON-RPC over **stdin/stdout** (`mcp.run()` with the default stdio
  transport) — it does **not** start an HTTP server, open a network port, or
  accept remote connections;
- makes **outbound HTTPS** calls to exactly two hosts: `api.hacknplan.com` and
  (only when you use the migration tools) `api.trello.com`;
- reads all credentials from **environment variables** — nothing is hardcoded or
  written to disk.

That shape matters for reading dependency-scanner output (below).

## Dependency advisories — current status (honest assessment)

We dogfood security scanning on our own repo. A scan against the OSV database +
Guarddog surfaces advisories in our transitive dependencies. Here is the honest
triage rather than a dismissal — **most do not apply to a stdio server, and every
flagged package is already at its latest published version, so there is nothing to
upgrade to.**

| Advisory | Package | Applies here? | Why |
|---|---|---|---|
| CVE-2025-66416 — MCP SDK no DNS-rebinding protection by default | `mcp` | **No** | Affects the SDK's **HTTP** transport. We run **stdio** — there is no local HTTP server to rebind against. |
| CVE-2025-53365 — MCP SDK Streamable HTTP DoS | `mcp` | **No** | Streamable-HTTP transport only; we never start it. |
| CVE-2024-53981, CVE-2026-40347, CVE-2026-42561, CVE-2026-24486 — `python-multipart` DoS / arbitrary write | `python-multipart` | **No** | multipart is HTTP form-body parsing. A stdio MCP server parses no multipart input; the package is pulled in transitively by the SDK's HTTP stack, which we don't run. |
| CVE-2026-45409 — IDNA `idna.encode()` bypass | `idna` | **Low** | Reached only via `httpx` when resolving a hostname. We connect to two fixed, trusted hosts (`api.hacknplan.com`, `api.trello.com`) — no attacker-controlled hostnames pass through `idna.encode()`. |
| Guarddog: "shady-links match in mcp 1.27.2" | `mcp` | **No (false positive)** | `mcp` is the **official** Anthropic Model Context Protocol SDK (`modelcontextprotocol/python-sdk`), not a typosquat. Guarddog's heuristic flags URLs present in the package metadata. |

**Why we don't "just upgrade":** as of this writing, `mcp` (1.27.2),
`python-multipart` (0.0.29), and `idna` (3.17) are **already the latest releases on
PyPI** — there is no patched version to pin to. The advisories are open upstream
against current code, in HTTP paths this stdio server does not execute. We track
the upstream SDK and will bump as soon as fixed releases ship.

If you run a fork that exposes an **HTTP transport**, the MCP-SDK HTTP advisories
*do* become relevant to you — pin to a patched `mcp`/`python-multipart` once
available, and enable DNS-rebinding protection.

## What we do on our side

- **No credentials in the repo** — env-only; verified across the full git history.
- A **pre-commit secret-guard** (`.githooks/pre-commit`) blocks API tokens, AWS
  keys, private keys, and 32-char hex from being committed.
- **CI** byte-compiles every module and runs the test suite on each push.

_This file reflects the project's posture at the time of writing; advisory
applicability can change as the dependency tree or upstream fixes evolve._
