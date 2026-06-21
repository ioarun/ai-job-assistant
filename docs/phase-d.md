# Phase D — LangGraph Agent Orchestration

> A file-by-file walkthrough of what we built, why, and how the pieces fit together.
> Read alongside the files in the repo. Last updated: 2026-06-21.
>
> For the *concepts* (state machines, reducers, checkpointers, HITL interrupts,
> streaming, memory), see [phase-d-theory.md](phase-d-theory.md).
>
> **Status: CORE GRAPH COMPLETE** — state, tools, nodes, graph, and a CLI driver are
> built and wiring-verified. SSE streaming endpoint and long-term (cross-session)
> memory are intentionally deferred (see §8).

---

## 1. What Phase D is (and isn't)

**Phase D's goal:** turn the four standalone Phase C tools into an **agent** — a
LangGraph state machine where an LLM decides *which* tools to run and *in what
order*, instead of the fixed order hard-wired in
[scripts/run_pipeline.py](../scripts/run_pipeline.py). Same tools; the difference
is **who decides the sequence**.

**What we built this session (core graph):**

| # | Piece | File | What it does |
|---|---|---|---|
| 1 | Shared state | [app/agent/state.py](../app/agent/state.py) | The one typed object every node reads/writes |
| 2 | Tool wrappers | [app/agent/tools.py](../app/agent/tools.py) | The 4 Phase C tools as `async (state) -> update` |
| 3 | Nodes + router | [app/agent/nodes.py](../app/agent/nodes.py) | planner, tool_router, tool_executor, reflector, responder |
| 4 | Graph assembly | [app/agent/graph.py](../app/agent/graph.py) | Wire the nodes/edges; compile with a SQLite checkpointer |
| 5 | CLI driver | [scripts/run_agent.py](../scripts/run_agent.py) | Run end-to-end; stream progress; HITL pause/resume |
| — | Cache predicate | [app/services/adzuna_client.py](../app/services/adzuna_client.py) | `is_search_cached()` — lets the agent gate a *live* call |

**Design decisions locked for this phase:**
- **HITL gate = dynamic, on a live Adzuna call.** We pause *only* on a cache **miss**
  (a quota-burning live API call); a cache **hit** runs free. This is a *dynamic*
  `interrupt()` inside `tool_executor` — the node decides *whether* to pause based on
  the situation. (The alternative, static "approve the whole plan up front", was the
  other fork; we chose the tighter "guard the costly/irreversible thing" story that
  ties back to the Phase C quota lesson.)
- **Explicit planner, not `bind_tools`.** The planner LLM emits a structured *plan*
  (an ordered list of tool names); `tool_executor` then calls the Python tool
  directly. We did **not** use model tool-calling (`llm.bind_tools`) here — see §4
  for why, and the trade-off.
- **Custom `StateGraph`, not `create_react_agent`.** The whole point is to *show* the
  planner/reflector/HITL machinery, not hide it behind a one-liner.

**What's intentionally NOT in this phase:**
- **No SSE endpoint yet.** The graph is fully streamable (`.astream`); exposing it
  over Server-Sent Events in `app/api/agent.py` is the deferred follow-up (§8).
- **No long-term memory yet.** Short-term memory (the per-thread conversation, via the
  checkpointer) works now; cross-session recall via a second Chroma collection is
  deferred (§8).
- No MCP server (Phase E), no eval/CI gate (Phase F), no UI (Phase G).

**Done-when (core):** a request like *"find 3 AU AI engineering jobs, analyse my gaps
for the top match, suggest a project"* runs through the graph — planner decides the
tool sequence, the executor runs each tool, a live Adzuna search pauses for approval,
and the responder composes a final answer — all checkpointed and traced.

---

## 2. The shared state — `state.py`

A LangGraph agent is organised around one **typed, shared state**. Every node gets the
current state and returns a **partial update** (just the keys it changed); LangGraph
merges it back per each channel's **reducer**.

[app/agent/state.py](../app/agent/state.py) defines `AgentState` as a `TypedDict`:

- `messages: Annotated[list, add_messages]` — the conversation log. The `add_messages`
  reducer **appends** instead of overwriting, so each node's progress message
  accumulates and (once checkpointed per thread) *becomes* the short-term memory.
- `what` / `where` / `results_per_page` — the search parameters, parsed by the planner.
- `plan: list[str]` — the planner's intended ordered tool sequence.
- `jobs` / `selected_job` / `gap` / `projects` / `interview` — the tool outputs, each
  typed with the Phase C / DB models we already own (`Job`, `GapAnalysis`,
  `ProjectSuggestions`, `InterviewKit`).
- `completed: list[str]` — tool names already run; this is how the router picks the
  *next* unrun step deterministically.
- `final_answer: str` — the responder's composed reply.

`total=False` lets every node return only the keys it touched. Every channel except
`messages` uses the default **overwrite** reducer (a fresh `gap` replaces the old one);
`messages` is the one append-channel.

---

## 3. The tool wrappers — `tools.py`

Phase C's tools were built to be agent-ready (typed in, typed out), so wrapping them is
thin. [app/agent/tools.py](../app/agent/tools.py) exposes each as an
`async (state) -> partial update` function:

- `run_search_jobs` — pulls `what`/`where`/`results_per_page` from state, calls
  `search_jobs`, and sets `jobs` + `selected_job` (top result is the default pick).
- `run_analyze_gap` — uses `selected_job`, returns `{"gap": ...}`.
- `run_suggest_projects` / `run_generate_interview` — both chain off `gap`.

**The one real wrinkle — sync vs async.** `search_jobs` is **synchronous** (httpx +
SQLite); the other three are **async**. The graph runs async, so calling the sync tool
directly would block the event loop. We bridge it with
`asyncio.to_thread(search_jobs, ...)`.

Two registries drive the executor and router:
- `TOOL_FNS` — name → wrapper. The planner may only emit names from here.
- `TOOL_DEPENDENCIES` — which prior state key each tool needs (`analyze_gap` needs
  `selected_job`; the suggesters need `gap`). Used by the planner's normaliser (§4) to
  keep plans in dependency order.

> Note the wrappers stay **pure** "given state, run the tool". The HITL gate is *not*
> here — it lives in `tool_executor`, so the tool functions remain trivially testable.

---

## 4. The nodes and the router — `nodes.py`

This is the heart of the phase. [app/agent/nodes.py](../app/agent/nodes.py) holds the
five nodes plus the routing function and a couple of helpers (`_llm()` builds a traced
`ChatOpenAI` exactly like the Phase C tools; `_next_tool()` returns the first planned
step not yet in `completed`).

### `planner`
An LLM call with **structured output** (`with_structured_output(Plan)`). The `Plan`
schema is `{what, where, results_per_page, steps}`, so a single call both **parses the
request** (keywords, location, count) and **plans the tool sequence**. The system prompt
lists the four tools and their dependencies and asks for an ordered subset.

`_normalize_plan()` then hardens the LLM's choice deterministically: it drops invalid
names, and **prepends missing prerequisites** — ask for interview questions only and
you still get `search_jobs → analyze_gap → generate_interview_questions`. This means a
sloppy plan can't produce a runtime error like "analyze_gap with no selected_job".

> **Why a planner instead of `bind_tools`?** Tool-calling (the model emits "call
> `analyze_gap` with these args") is the other idiomatic approach, and the theory doc
> (Step 3) explains it. We chose an explicit planner because (a) it makes the agent's
> intended trajectory **visible as data** (`state["plan"]`) before any tool runs —
> which is exactly what we can show in a trace and gate with HITL — and (b) our tool
> arguments come from prior *state* (`gap`, `selected_job`), not from free-form model
> output, so letting the model invent arguments buys little. The trade-off: the agent
> can't improvise a tool mid-run that wasn't planned. For this fixed toolset that's a
> fine bargain; a more open-ended agent would favour `bind_tools`.

### `tool_router` (+ `route_from_router`)
`tool_router` is a **no-op node** — it returns `{}`. It exists purely so the loop has a
named hub in the trace (matching the theory-doc diagram). The actual decision is the
**conditional edge** `route_from_router(state)`: return `"tool_executor"` if there's an
unrun step, else `"reflector"`. *This function is where the agent's looping and
branching live* — it's the inspectable, testable equivalent of the `if` buried in a raw
`while` loop.

### `tool_executor` — and the HITL interrupt
Runs **exactly one** tool per visit: the next unrun plan step. The HITL gate lives here:

```
if tool == "search_jobs" and not is_search_cached(...):
    decision = interrupt({...})          # graph PAUSES, state is checkpointed
    approved = decision is True or decision.get("approved")
    if not approved: skip the search
update = await TOOL_FNS[tool](state)     # run it; append to `completed`
```

`is_search_cached()` (added to [adzuna_client.py](../app/services/adzuna_client.py),
reusing the same param-normalisation/hashing as `search_jobs`) tells us *before*
calling whether this query would hit the live API. On a cache miss we call
`interrupt(payload)`: the graph halts, the checkpointer saves state, and the payload
surfaces to the caller. Resuming with `Command(resume={"approved": ...})` continues
execution **from that exact point**. A cache hit skips the gate entirely — that's the
whole point of a *dynamic* interrupt over a static one.

### `reflector`
A **cheap, deterministic** check (no LLM call, to save cost): did every planned tool
produce its output key? It emits a one-line verdict message. An LLM-based reflector that
judges *answer quality* (and could route back to `tool_router` to retry) is a documented
extension, not built here.

### `responder`
Gathers whatever structured results are present (`jobs`, `gap`, `projects`, `interview`)
into a compact context block and makes one LLM call to compose the final
natural-language answer. It writes `final_answer` and appends the message. (When we add
SSE in the follow-up, this is the node we'll token-stream.)

---

## 5. Assembling the graph — `graph.py`

[app/agent/graph.py](../app/agent/graph.py) wires it together:

```
START → planner → tool_router ─(next tool)→ tool_executor ─┐
                       │                                    │ loop
                  (plan done)                               │
                       ▼                                     │
                   reflector → responder → END   ◄───tool_router
```

`build_graph(checkpointer)` calls `add_node` for the five nodes, `add_edge` for the
fixed transitions, and `add_conditional_edges("tool_router", route_from_router, {...})`
for the loop decision. `tool_executor → tool_router` is the edge that closes the loop —
the executor runs one tool, then control returns to the router to pick the next.

`open_graph()` is an async context manager that opens an **`AsyncSqliteSaver`**
(`langgraph-checkpoint-sqlite`) at `data/agent_checkpoints.sqlite` and compiles the
graph with it. We chose SQLite over `MemorySaver` because HITL resume must survive
across separate invocations (and, eventually, separate HTTP requests) — see theory-doc
Step 5. The checkpointer is the single mechanism behind short-term memory, durability,
and HITL pause/resume.

---

## 6. Driving it — `scripts/run_agent.py`

[scripts/run_agent.py](../scripts/run_agent.py) is the CLI demo:

```
python -m scripts.run_agent "find 3 AU AI engineering jobs, analyse my gaps for the top one, suggest a project"
python -m scripts.run_agent "..." --thread demo1 --auto-approve
```

It streams the run with `graph.astream(..., stream_mode="updates")`, printing each
node's progress messages as they finish. When a chunk contains `"__interrupt__"`, it
prints the approval payload, asks on the terminal (or auto-approves with the flag), and
re-invokes with `Command(resume={"approved": ...})` to continue from the checkpoint.
At the end it reads `state.values["final_answer"]` and flushes Langfuse traces.

Because the run is keyed by `--thread`, re-running the same thread reuses both the
conversation history (short-term memory) and the Adzuna cache.

---

## 7. How we verified it

A wiring smoke check (imports + `build_graph().compile()` + `open_graph()`), run inside
the `aja-app` container against `/workspace`, confirmed:
- the graph compiles with all five nodes;
- `_normalize_plan` injects prerequisites correctly
  (`[generate_interview_questions] → [search_jobs, analyze_gap, generate_interview_questions]`,
  `[analyze_gap] → [search_jobs, analyze_gap]`, `[bogus] → [search_jobs]`);
- the `AsyncSqliteSaver` checkpointer wires.

The full end-to-end run then completed live (`scripts/run_agent.py`, real OpenAI calls):
planner → search → analyze_gap (fit 75/100) → suggest_projects → reflector → responder,
producing a coherent final answer. Two issues surfaced and were fixed in the process:

- **`interrupt()` on Python 3.10.** LangGraph's `interrupt()` reads the run config from
  a contextvar that LangGraph only propagates into async nodes on **Python ≥ 3.11**
  (it needs `asyncio.create_task(context=...)`). The app image is 3.10, so the first
  run raised *"Called get_config outside of a runnable context"*. Fix: `tool_executor`
  takes the injected `config` and sets `var_child_runnable_config` itself around the
  `interrupt()` call. (A future image bump to 3.11+ would make this workaround
  unnecessary.)
- **`Job` isn't serializable.** The checkpointer serializes the whole state after every
  super-step via msgpack; the SQLAlchemy `Job` ORM object isn't serializable. Fix: a
  plain Pydantic `JobView` in state (`JobView.from_orm_job`), converted in
  `run_search_jobs`.

Requires a resume indexed (`scripts/index_resume.py`) and the stack configured. The
HITL pause fires only on an Adzuna cache **miss**; the demo run hit the cache, so the
pause wasn't exercised end-to-end (the mechanism is verified separately).

### Follow-ups (resolved)
- **Register msgpack types.** ✅ `open_graph` now builds the saver with a
  `JsonPlusSerializer(allowed_msgpack_modules=[JobView, GapAnalysis, ProjectSuggestions,
  InterviewKit])`, silencing the "unregistered type" warnings and future-proofing the
  checkpoint format.
- **Decline path.** ✅ `tool_executor` now skips any tool whose `TOOL_DEPENDENCIES`
  prerequisite is missing (marking it completed so the loop advances), and the responder
  reports "no jobs found" gracefully. Verified live by declining a cache-miss search:
  the HITL pause fired, the decline made no live Adzuna call, and the run completed
  cleanly with the downstream tools skipped.

---

## 8. What's deferred (and why it's clean to defer)

| Deferred | Where it'll live | Why it slots in cleanly |
|---|---|---|
| **SSE streaming endpoint** | `app/api/agent.py` (`sse-starlette`) | The graph already streams via `.astream`; the endpoint just adapts that generator to SSE. The responder is the node to token-stream. |
| **Long-term memory** | a second Chroma `sessions` collection | Same RAG pattern as Phase B, pointed at the agent's own session summaries; write on completion, retrieve on a new thread. |
| **LLM reflector / retry** | `reflector` node | Today it's a deterministic completeness check; upgrading it to judge answer quality and loop back is a localized change. |

Each is a *named node or endpoint*, not a rewrite — which is the payoff of modelling the
agent as a graph in the first place.

---

## 9. One-paragraph summary for an interview

> *"Phase D turns my four Phase C tools into a LangGraph agent. There's one typed shared
> state; a planner LLM parses the request and emits an ordered plan; a conditional edge
> (`route_from_router`) walks that plan, sending control to a tool_executor that runs one
> tool per visit and loops back until the plan is done, then to a reflector and a
> responder. I chose an explicit planner over model tool-calling so the intended
> trajectory is inspectable data I can gate and trace, and a custom StateGraph over the
> prebuilt ReAct agent so the planner/reflector/HITL machinery is visible. The
> human-in-the-loop gate is a dynamic interrupt that fires only on an Adzuna cache
> miss — a live, quota-burning call — and resumes from the exact checkpoint once
> approved; that pause/resume works because the graph is checkpointed to SQLite keyed by
> thread_id, which also gives me short-term memory for free. The whole run streams and
> shows up as one Langfuse trace."*