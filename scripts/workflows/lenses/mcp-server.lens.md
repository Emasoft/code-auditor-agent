# mcp-server lens

## key
mcp-server

## fire-when
MCP server tool implementations. Content markers: `@server.tool`, `mcp.tool()`, `@mcp.tool`, `Server(` / `McpServer(`, `FastMCP(`, `@app.list_tools`, `@app.call_tool`, imports of `mcp.server` / `@modelcontextprotocol/sdk` / `modelcontextprotocol`. Files: `*server*.py`, `*mcp*.py/.ts/.js`, `*.mcp.json`, tool-handler/tool-registration modules. Skip if no MCP tool registration or handler present (single-user dev tools are partially exempt for auth only).

## checklist
- **Tool registration allowlist** — new tools registered via `@server.tool` / `mcp.tool()` must route through an explicit registry; NO dynamic reflection-based registration of arbitrary functions. Dynamic registration = MUST-FIX. (Category: registration)
- **Parameter schema validation** — each tool declares a schema (zod / Pydantic / JSON Schema) AND the server validates incoming params against it BEFORE dispatch. Missing schema or missing pre-dispatch validation = MUST-FIX. (Category: schema)
- **Command injection in tool wrappers** — any tool that shells out (`subprocess`, `child_process`, `os.system`) must pass user args via parameterised invocation (`args=[...]`, never `shell=True` with interpolation). `shell=True` with user-interpolated args = MUST-FIX. (Category: command-injection)
- **Path traversal** — tools touching the filesystem must validate paths against an allowlist root (`Path.resolve()` + `is_relative_to`). Unvalidated user-controlled path = MUST-FIX. (Category: path-traversal)
- **Resource exhaustion guards** — tools that loop / allocate / spawn processes must cap input size, iteration count, and process count. Missing cap on user-controlled iteration/allocation/spawn = SHOULD-FIX. (Category: resource-exhaustion)
- **Secrets in tool echo** — tool responses must NOT echo back secrets the server received (env vars, API keys, file contents the caller couldn't already read). Echoing such secrets = MUST-FIX. (Category: secret-echo)
- **Tool-call auth** — in a multi-tenant or shared context, each tool must verify the caller is authorised for the targeted resource. Missing authz = MUST-FIX. Single-user dev tools are EXEMPT from this check only. (Category: auth)
- **Idempotency / side-effect contracts** — tools that mutate state must document idempotency in the tool description; non-idempotent mutating tools should accept an `Idempotency-Key`-style argument. Undocumented/unguarded non-idempotent mutation = SHOULD-FIX. (Category: idempotency)
- **Combined fatal pattern** — `shell=True` with user-interpolated args + missing schema validation + secret echo together = MUST-FIX, no exceptions.
- Severities: MUST-FIX | SHOULD-FIX | NIT. Confidence: HIGH | MEDIUM | LOW. Layer is always `structural`. Scope is MCP-specific only; general prompt-injection is out of scope (a separate lens covers it).
