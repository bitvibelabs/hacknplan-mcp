# Contributing to hacknplan-mcp

Thanks for considering a contribution. This is a small, focused project — a clean
MCP server over the HacknPlan v0 API — and the bar is "would a HacknPlan user be
glad this exists." That keeps things simple.

## Ground rules

- **No credentials, ever.** The server reads `HACKNPLAN_API_KEY` and the Trello
  pair from the environment only. Don't hardcode keys in code, tests, or examples.
- **Verify against the live API, not the spec.** HacknPlan's OpenAPI spec is
  misleading in a few places (see `docs/API_REFERENCE.md`). If you add or change a
  tool, confirm the request/response shape against a real account before opening
  the PR, and note what you saw.
- **Keep tools thin and predictable.** Each tool wraps one operation, validates
  inputs, returns either JSON or markdown, and turns errors into actionable
  messages. Destructive operations require `confirm: true`.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install -r requirements.txt
HACKNPLAN_API_KEY=... ./.venv/bin/python3 -c "import sys;sys.path.insert(0,'server');import hacknplan_server"
```

To smoke-test the server boots and lists its tools over stdio:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | HACKNPLAN_API_KEY=x ./.venv/bin/python3 server/hacknplan_server.py
```

## Adding a tool

1. Add the async function in `server/hacknplan_server.py`, decorated with
   `@mcp.tool()`, with a clear docstring (the docstring is what the AI reads to
   decide when and how to call it — make it concrete).
2. Use the shared `hp()` client and the `_err()` helper for error handling.
3. If it's a write that maps to a documented endpoint, add the verified body shape
   to `docs/API_REFERENCE.md`.
4. Bump the tool count in `README.md` and add a `CHANGELOG.md` entry.

## Reporting bugs

Open an issue with: the tool you called, the arguments, the response or error you
got, and (if relevant) the HTTP status. "It returned 500 with an empty body" is a
genuinely useful HacknPlan bug report — that API does it more than you'd expect.

## License

By contributing you agree your work is released under the [MIT License](LICENSE).
