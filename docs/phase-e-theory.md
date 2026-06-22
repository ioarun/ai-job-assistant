# Phase E — Theory & Concepts

> The *why* behind the MCP server. Read this for the concepts; read
> [phase-e.md](phase-e.md) for the file-by-file build walkthrough.
> Last updated: 2026-06-23.
>
> **Status: SERVER BUILT** — `app/mcp_server/{server,__main__,__init__}.py` exist and
> expose the four Phase C tools over stdio MCP; see [phase-e.md](phase-e.md). Resolved
> fork: tool scope = **all four Phase C tools** (not just job-search), so the host can
> orchestrate the full chain.

---

## The big picture: from our agent to someone else's agent

Phase D made *our* code the agent: our LLM planned the tool sequence and our graph ran
the tools. Phase E asks a different question — what if a tool we built could be used by
an agent **we didn't write**, like Claude Desktop? For that, the tools need to be
described and called over a shared, language-agnostic contract. That contract is MCP.

## What MCP is

The **Model Context Protocol** is an open standard for connecting LLM applications
("hosts") to external capabilities ("servers"). Think of it as "USB-C for tools": a host
that speaks MCP can plug into any server that speaks MCP, with no bespoke integration per
tool. It standardises three things a server can offer:

- **Tools** — functions the model can call (what we use here).
- **Resources** — readable data/context the host can pull in (we don't use these).
- **Prompts** — reusable prompt templates the host can surface (we don't use these).

We expose only **tools** — the minimal surface for the demo.

## Host vs. server (who does what)

- **Host** (Claude Desktop): runs the model, owns the conversation, *decides* which tools
  to call and in what order, and asks the user for approval. The orchestration brain.
- **Server** (our code): advertises a list of tools with JSON schemas, and *executes* a
  tool when the host calls it. No model of its own — it just runs functions.

This separation is the whole point: in Phase D the brain and the hands were both ours; in
Phase E the brain is the host and we provide the hands.

## Transport — why stdio

MCP messages are JSON-RPC. They can travel over different transports:

- **stdio** — the host launches the server as a subprocess and talks over its
  stdin/stdout. Simplest, local, one client per process. This is what Claude Desktop uses
  for local servers, and what we use.
- **Streamable HTTP / SSE** — for remote servers reachable over the network. Out of scope
  here.

The catch with stdio: **stdout is the message channel.** Anything else written to stdout
(a stray `print`, a log line) corrupts the JSON-RPC stream. So a stdio server must send all
logs to stderr — which is exactly the one-line change we made to `configure_logging`.

## Tool schemas are the contract

The host never sees our Python. All it gets is, per tool: a name, a description, and a JSON
input schema. The model plans entirely from those. Two consequences shape the code:

1. **Docstrings are prompts.** The description the model reads *is* the function docstring,
   so it must say what the tool does, when to use it, and what it returns — written for a
   model deciding among tools, not for a developer reading source.
2. **Types generate the schema.** FastMCP builds the input schema from the parameter type
   hints. Typing `suggest_projects(gap: GapAnalysis)` gives the host a full, precise schema
   for `gap`, so it can pass back the structured `analyze_gap` output verbatim. That typed
   hand-off *is* how the host chains one tool into the next.

## How it fits: one Claude Desktop request, end to end

1. User: "find AI roles in Melbourne, analyse my gaps, suggest projects."
2. Host model reads the four tool schemas and plans: `search_jobs` → `analyze_gap` →
   `suggest_projects`.
3. Host calls `search_jobs` over stdio → our server runs the cached Adzuna client →
   returns job JSON.
4. Host picks a job, calls `analyze_gap` with its title/description → returns a gap dict.
5. Host passes that gap dict into `suggest_projects` → returns project ideas.
6. Host composes the final answer for the user. Each tool call is one MCP request; each of
   our services still emits its Langfuse trace.

## Why this is a strong portfolio signal

It demonstrates **interoperability**, not just capability: the same tools that power our
own agent are now standards-compliant building blocks any MCP host can orchestrate. That
is the direction the ecosystem is moving (tools as portable, model-agnostic services), and
it shows an understanding of the host/server boundary, protocol transports, and designing
tool APIs that a model — not a human — consumes.

## Glossary (quick reference)

- **MCP** — Model Context Protocol; open standard linking LLM hosts to tools/data.
- **Host** — the LLM app (Claude Desktop) that plans and calls tools.
- **Server** — process that advertises and executes tools (our code).
- **stdio transport** — JSON-RPC over a subprocess's stdin/stdout; stdout must stay clean.
- **FastMCP** — the high-level Python MCP server API; turns decorated, type-hinted
  functions into tools with auto-generated schemas.

## One-paragraph summary for an interview

"Phase E publishes the job-assistant's four tools over the Model Context Protocol so an
external host like Claude Desktop can orchestrate them. A `FastMCP` stdio server wraps the
unchanged Phase C services as tools; their docstrings and Pydantic-typed parameters become
the schemas the host's model plans from, so it chains search → gap → projects → interview
itself. It runs via `docker exec` inside the app container to inherit secrets and stay on
the Langfuse network. The key insight is the host/server split — in Phase D our code was
the agent; here we're a standards-compliant tool provider, and the brain is someone else's."