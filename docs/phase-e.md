# Phase E — One MCP Server + Claude Desktop Demo

> A file-by-file walkthrough of what we built, why, and how the pieces fit together.
> Read alongside the files in the repo. Last updated: 2026-06-23.
>
> For the *concepts* (what MCP is, why a protocol, stdio transport, host vs. server),
> see [phase-e-theory.md](phase-e-theory.md).
>
> **Status: SERVER COMPLETE** — the four Phase C tools are re-exposed over MCP, the
> server registers and lists all four tools with correct schemas (verified, see §5),
> and a Claude Desktop launch config is provided. The live end-to-end Claude Desktop
> demo is run by hand (see §4) — it is deliberately not automated, and the first live
> `search_jobs` there spends one Adzuna quota call.

---

## 1. What Phase E is (and isn't)

**Phase E's goal:** expose the existing tools over the **Model Context Protocol (MCP)**
so a *host* application — Claude Desktop — can discover and call them. The host's own
model becomes the orchestrator: it reads the tool schemas, decides which tool to call,
and chains them. This is the same job the Phase D LangGraph agent does, driven by a
different brain.

| | Phase D | Phase E |
|---|---|---|
| Who plans the tool sequence | our LLM planner node | the Claude Desktop host model |
| Who runs the tools | our `tool_executor` | our MCP server (this code) |
| Transport | in-process Python | MCP JSON-RPC over stdio |
| The tools themselves | the four Phase C services | **the same four services** |

**Scope (locked, with one update on 2026-06-23):** the original decision was "ONE
demonstrative MCP server — refactor *job-search* into MCP, don't MCP-ify everything."
On 2026-06-23 we widened it to expose **all four** Phase C tools, because that lets
Claude Desktop orchestrate the full search → gap → projects → interview chain itself —
a much stronger portfolio demo, still from one server.

**What we did NOT do:** turn every internal function into a tool, add resources/prompts,
or build a remote (HTTP/SSE) MCP server. Local stdio is what Claude Desktop launches and
is enough for the demo.

## 2. The server — `app/mcp_server/server.py`

A single [`FastMCP`](../app/mcp_server/server.py) instance named `ai-job-assistant` with
four `@mcp.tool()`-decorated functions. Each is a thin adapter over a Phase C service:

- **`search_jobs(what, where, results_per_page)`** → list of job dicts. The underlying
  `app.services.adzuna_client.search_jobs` is synchronous (httpx + SQLite), and FastMCP
  runs tools on an event loop, so we bridge it with `asyncio.to_thread` to avoid blocking.
  Returns are `JobView.from_orm_job(j).model_dump()` — the same serializable view the
  Phase D state uses, so detached ORM rows turn into plain JSON.
- **`analyze_gap(job_title, job_description)`** → gap-analysis dict (`model_dump()`).
- **`suggest_projects(gap)`** and **`generate_interview_questions(gap)`** → take a whole
  `GapAnalysis` as the parameter. FastMCP generates the JSON input schema *from the
  Pydantic type hint*, so the host gets a precise schema for `gap` and passes back the
  object it received from `analyze_gap` — that is the tool chaining, made explicit.

**The docstrings are the API.** The host model reads each tool's docstring + type hints
to decide when and how to call it, so they're written for the model (what the tool does,
when to use it, what it returns, what to pass next), not just for humans.

**Tracing still works.** These adapters call the unchanged Phase C services, so the
Langfuse spans/callbacks they already emit (`tool.adzuna.search`, `tool.gap_analyzer`,
etc.) fire here too — provided the server runs on the compose network (see §3).

## 3. Running it — entry point, logging, and the Docker path

- **`app/mcp_server/__main__.py`** makes `python -m app.mcp_server` work.
- **`main()`** calls `configure_logging(stream=sys.stderr)` then `mcp.run(transport="stdio")`.
  This is the one non-obvious correctness point: a stdio MCP server speaks JSON-RPC over
  **stdout**, so any log line on stdout corrupts the stream. We added a `stream` parameter
  to `configure_logging` (default `sys.stdout`, unchanged for everything else) and pass
  `sys.stderr` here.
- **No host venv.** The app runs in Docker (`ai-job-assistant:dev`, `PYTHONPATH=/workspace`),
  and the host's system Python doesn't have `mcp` or our deps. So Claude Desktop launches
  the server *inside the running container* via `docker exec -i aja-app python3 -m app.mcp_server`.
  `exec` inherits the container's `.env` (OpenAI/Adzuna keys) and `LANGFUSE_HOST`, and is on
  the compose network — so tracing reaches `langfuse-web`.

## 4. The Claude Desktop demo (run by hand)

1. Bring the app container up (the Langfuse stack comes with it):
   ```
   docker compose -f docker/docker-compose.yml --env-file .env up -d app
   ```
2. Copy the `ai-job-assistant` block from
   [docker/claude_desktop_config.example.json](../docker/claude_desktop_config.example.json)
   into Claude Desktop's config:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`
3. Fully restart Claude Desktop. The four tools appear under the 🔌 (tools) menu.
4. Prompt it, e.g.: *"Find me 3 AI engineer roles in Melbourne, analyse my resume's gaps
   for the best one, then suggest portfolio projects to close them."* Claude Desktop calls
   `search_jobs` → `analyze_gap` → `suggest_projects` on its own, passing each result into
   the next tool.

> Note: `analyze_gap` requires a resume to already be indexed in the vector store
> (Phase B). The first uncached `search_jobs` spends one Adzuna free-tier quota call;
> repeats within the freshness window are served from the SQLite cache.

## 5. How we verified it

Ran the server module inside the image and listed the registered tools:

```
docker run --rm -e PYTHONPATH=/workspace -v "$PWD/app:/workspace/app" \
  -v "$PWD/data:/workspace/data" -v "$PWD/.env:/workspace/.env:ro" \
  -w /workspace ai-job-assistant:dev python3 -c "..."
```

Result: import OK and all four tools listed with the expected required params —
`search_jobs` → `['what']`, `analyze_gap` → `['job_title','job_description']`,
`suggest_projects` / `generate_interview_questions` → `['gap']`, with `gap` exposed as a
structured object. The live Claude Desktop chain (§4) is the manual acceptance test; we
did not fire a live Adzuna call during verification to preserve quota.

## 6. Skills demonstrated by Phase E

- **MCP / interoperability:** publishing existing capabilities over an open protocol so a
  third-party host (Claude Desktop) can orchestrate them — host-vs-server separation,
  tool schemas as the contract, stdio JSON-RPC transport.
- **API design for models:** tool docstrings + Pydantic-typed parameters written so an LLM
  can plan a multi-tool chain (`analyze_gap` output feeds `suggest_projects` input).
- **Engineering:** clean adapter layer reusing the Phase C services unchanged; sync→async
  bridging; the stdout-purity fix for stdio transport; container-based launch that keeps
  secrets and Langfuse tracing intact.

## 7. What's next

Phase F — evals + a CI prompt-regression gate (Promptfoo/DeepEval golden datasets run on
PR via GitHub Actions).