# Phase D — LangGraph Agent Orchestration

> A file-by-file walkthrough of what we built, why, and how the pieces fit together.
> Read alongside the files in the repo. Last updated: 2026-06-21.
>
> For the *concepts* (state machines, reducers, checkpointers, HITL interrupts,
> streaming, memory), see [phase-d-theory.md](phase-d-theory.md).
>
> **Status: CORE GRAPH COMPLETE** — state, tools, nodes, graph, and a CLI driver are
> built and **live-verified end to end** (a real multi-tool run, plus the HITL pause
> exercised on a cache miss — see §7). SSE streaming endpoint and long-term
> (cross-session) memory are intentionally deferred (see §8).

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
- `jobs` / `selected_job` / `gap` / `projects` / `interview` — the tool outputs. The
  job fields are typed `JobView` — a plain Pydantic *view* of a `Job` row, because the
  SQLAlchemy ORM object isn't msgpack-serializable and the checkpointer serializes the
  whole state (see §7). The rest reuse the Phase C models we already own (`GapAnalysis`,
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
HITL pause fires only on an Adzuna cache **miss**; the first demo run hit the cache, so
the pause didn't fire there. It was then exercised end-to-end in the decline-path
follow-up below — a cache-miss run where the pause fired, the human declined, no live
Adzuna call was made, and the run still completed cleanly.

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

## 9. Skills demonstrated by Phase D

### Agentic AI / orchestration
The core deliverable: four standalone tools become an **agent** that decides *which*
tools to run and *in what order*. Built as an explicit LangGraph `StateGraph` —
planner → tool_router → tool_executor (loop) → reflector → responder — so the
plan/route/reflect machinery is visible structure, not hidden inside a prebuilt
`create_react_agent`. Planning is a structured LLM call (`with_structured_output(Plan)`)
hardened by a deterministic `_normalize_plan` that injects missing prerequisites.

### AI safety / human-in-the-loop
A **dynamic** `interrupt()` gates the one costly, irreversible action — a live,
quota-burning Adzuna call — and *only* that action: a cache hit runs free. The graph
pauses, checkpoints, surfaces an approval payload, and resumes from the exact point via
`Command(resume=...)`. The decline path is handled gracefully (no live call, downstream
tools skipped, a coherent answer still produced) rather than crashing.

### Durable state & memory
One typed `AgentState`; nodes return partial updates merged per-channel by reducers
(`add_messages` appends, everything else overwrites). The `AsyncSqliteSaver`
checkpointer keyed by `thread_id` is the single mechanism behind short-term memory,
durability, and HITL pause/resume — chosen over `MemorySaver` precisely because resume
must survive across separate invocations.

### Engineering
Async graph with a sync tool bridged via `asyncio.to_thread`; a serialization-safe
state (`JobView` + a `JsonPlusSerializer` with registered msgpack types); a streaming
CLI driver (`graph.astream(stream_mode="updates")`) that renders the HITL prompt and
resumes. A real Python-3.10 runtime quirk (contextvar propagation into async nodes) was
diagnosed and worked around rather than papered over.

### LLMOps / observability
The planner and responder LLM calls carry Langfuse callbacks and named runs
(`agent.planner`, `agent.responder`); the Adzuna tool traces as `tool.adzuna.search`.
The whole run shows up as one inspectable trace tree.

---

## 10. Questions to ask yourself (interview-readiness check)

1. Why model the agent as a `StateGraph` instead of a plain `while` loop with `if`s?
2. What is the shared state, and why does each node return a *partial* update?
3. Why does `messages` use the `add_messages` reducer while every other channel overwrites?
4. Why is `JobView` in state instead of the `Job` ORM object?
5. Why an explicit planner emitting a plan, rather than `llm.bind_tools` tool-calling?
6. What does `_normalize_plan` guarantee, and which runtime error does it prevent?
7. `tool_router` returns `{}` — why keep a no-op node, and where does the looping decision actually live?
8. Why gate HITL on a cache **miss**, and why is a *dynamic* interrupt the right tool over a static "approve the plan up front"?
9. How does pause/resume survive across separate invocations — what's the mechanism?
10. Why `AsyncSqliteSaver` instead of `MemorySaver`?
11. Why did `interrupt()` fail on Python 3.10, and what's the workaround?
12. When the user declines the live search, how does the graph avoid crashing on `analyze_gap` with no selected job?
13. Why is the reflector deterministic (no LLM), and what would an LLM reflector add?

---

## 11. Answers (elaborated)

**1. Why model the agent as a `StateGraph` instead of a plain `while` loop with `if`s?**
You *could* write the same control flow as a loop — but the graph buys you three things the loop doesn't. (a) The control flow becomes **inspectable structure**: nodes and edges you can draw, trace, and reason about, rather than logic buried in a function body. (b) You get **checkpointing for free** — LangGraph persists state after every super-step, which is what makes durability, short-term memory, and HITL pause/resume work without you writing any of it. (c) The pause/resume is a first-class primitive (`interrupt()`); doing that by hand in a `while` loop means serializing your own continuation. The graph is the abstraction that makes "an agent that can stop, ask a human, and pick up exactly where it left off" a few lines instead of a framework.

**2. What is the shared state, and why does each node return a *partial* update?**
`AgentState` is one `TypedDict` (`total=False`) that flows through every node — the request params, the plan, each tool's output, the bookkeeping (`completed`), and the final answer. Each node returns **only the keys it changed**, and LangGraph merges that back per each channel's reducer. Partial updates keep nodes decoupled (the planner doesn't need to know or preserve the responder's fields), make the merge semantics explicit per channel, and keep each checkpoint a clean diff. `total=False` is what lets a node legally return a dict with just one or two keys.

**3. Why does `messages` use the `add_messages` reducer while every other channel overwrites?**
Because they model different things. `messages` is a **log** — each node's progress line should *accumulate*, and once the thread is checkpointed that growing list *is* the agent's short-term memory. So it needs an **append** reducer (`add_messages`). Every other channel (`gap`, `plan`, `selected_job`, …) holds the *current* value of one thing — a fresh gap analysis should *replace* the old one, not pile up — so the default **overwrite** reducer is correct. The reducer is how you declare "is this channel a running log or a latest-value slot?"

**4. Why is `JobView` in state instead of the `Job` ORM object?**
Because the checkpointer serializes the **entire state** after every super-step (via msgpack), and a SQLAlchemy `Job` ORM instance isn't msgpack-serializable — it carries session/identity-map machinery, not just data. Putting a `Job` in state crashes the checkpoint. `JobView` is a plain Pydantic mirror of the columns we actually use (`JobView.from_orm_job`), so state stays serializable. We also register the view (and the other Pydantic result models) with a `JsonPlusSerializer(allowed_msgpack_modules=...)` so LangGraph will round-trip them instead of warning about unregistered types. General rule: only put serializable, plain-data objects in agent state.

**5. Why an explicit planner emitting a plan, rather than `llm.bind_tools` tool-calling?**
Two reasons specific to this agent. (a) An explicit `plan` makes the agent's intended trajectory **visible as data** *before* any tool runs — exactly what we want to trace and to gate with HITL; with `bind_tools` the trajectory only emerges step-by-step as the model decides. (b) Our tool arguments come from prior **state** (`selected_job`, `gap`), not from free-form model output, so letting the model invent call arguments buys almost nothing here. The trade-off is real: the agent can't improvise a tool mid-run that wasn't in the plan. For a small fixed toolset that's a good bargain; an open-ended agent with many tools and model-derived arguments would favour `bind_tools`.

**6. What does `_normalize_plan` guarantee, and which runtime error does it prevent?**
It guarantees the plan is **valid and dependency-ordered** regardless of what the LLM emitted. It drops unknown tool names, falls back to `["search_jobs"]` if nothing valid remains, **prepends missing prerequisites** (ask for interview questions alone and you still get `search_jobs → analyze_gap → generate_interview_questions`), and de-dups while preserving order. The error it prevents: a tool running before its input exists — e.g. `analyze_gap` firing with no `selected_job` in state, which would blow up in the wrapper. It turns a sloppy-but-plausible LLM plan into one that can't produce that class of runtime failure. (The executor's prerequisite check in §4 is the second, belt-and-braces guard for the case where a prerequisite tool *ran but produced nothing* — e.g. a declined search.)

**7. `tool_router` returns `{}` — why keep a no-op node, and where does the looping decision actually live?**
The node itself does nothing — it exists so the loop has a **named hub** in the graph and the trace, matching the mental model "after each tool, control returns to the router." The actual decision lives in the **conditional edge** `route_from_router(state)`: it returns `"tool_executor"` if there's an unrun plan step, else `"reflector"`. Separating them means the branching logic is a small, pure, **independently testable** function rather than an `if` hidden inside a node's body — the graph equivalent of factoring the loop condition out where you can see and test it.

**8. Why gate HITL on a cache miss, and why a *dynamic* interrupt over static "approve the plan"?**
Because the thing worth a human's attention is the **costly, irreversible** action — a live Adzuna call burns the rate-limited free-tier quota (the Phase C lesson) — and a cache **hit** is free and instant, so interrupting on it would be pure friction. `is_search_cached()` lets the executor know *before* calling which case it's in. A **dynamic** interrupt (the node decides *whether* to pause based on the live situation) expresses exactly that "pause only when it actually costs something" rule; a **static** "approve the whole plan up front" interrupt can't see runtime state like cache freshness, so it would either over-prompt or under-protect. Gate the irreversible thing, at the moment you know it's irreversible.

**9. How does pause/resume survive across separate invocations — what's the mechanism?**
The checkpointer. When `interrupt()` fires, LangGraph **persists the full state to SQLite keyed by `thread_id`** and halts; the approval payload surfaces to the caller. The process can exit entirely. On the next invocation with the *same* `thread_id` and a `Command(resume={"approved": ...})`, LangGraph loads the checkpoint and continues from the exact super-step that interrupted — the resume value becomes `interrupt()`'s return. There's no in-memory continuation to keep alive; durability *is* the resume mechanism. That's also why the same `thread_id` gives you conversation memory for free.

**10. Why `AsyncSqliteSaver` instead of `MemorySaver`?**
`MemorySaver` keeps checkpoints in process memory — fine for a single uninterrupted run, but it evaporates when the process exits. HITL resume must work **across separate invocations** (today the CLI is re-run to approve; tomorrow it'll be two separate HTTP requests), so the checkpoint has to outlive the process. `AsyncSqliteSaver` persists to a file (`data/agent_checkpoints.sqlite`), so a thread paused in one run resumes in the next. It's also `async` to match the async graph. SQLite specifically because the project already uses it and a single-file store is plenty at this scale.

**11. Why did `interrupt()` fail on Python 3.10, and what's the workaround?**
`interrupt()` reads the run config from a **contextvar**, and LangGraph only propagates that contextvar into **async** nodes on **Python ≥ 3.11** (it relies on `asyncio.create_task(context=...)`, which is 3.11+). The app image runs 3.10, so the first call raised *"Called get_config outside of a runnable context."* The fix: `tool_executor` takes the `config` LangGraph injects into the node and sets the contextvar itself (`var_child_runnable_config.set(config)`) around the `interrupt()` call, resetting it in a `finally`. A future bump to a 3.11+ image makes the workaround unnecessary — it's a runtime quirk, not a design flaw.

**12. When the user declines the live search, how does the graph avoid crashing on `analyze_gap` with no selected job?**
Two cooperating guards. On decline, `tool_executor` marks `search_jobs` completed but writes `jobs: []` / `selected_job: None` — so the loop advances instead of retrying. Then, before running any tool, the executor checks `TOOL_DEPENDENCIES`: if a tool's prerequisite state key is missing (`analyze_gap` needs `selected_job`), it **skips** that tool — also marking it completed so the loop keeps moving — and records a "skipped: prerequisite missing" message. So the plan drains cleanly, the reflector notes the missing outputs, and the responder produces a graceful "no jobs found" answer. Declining is a normal path, not an exception.

**13. Why is the reflector deterministic (no LLM), and what would an LLM reflector add?**
Cost and honesty. Today the reflector answers one cheap, objective question — *did every planned tool produce its output key?* — which needs no model call, so we don't pay tokens to state the obvious. An **LLM** reflector would answer a harder, subjective question — *is this answer actually good / complete / faithful?* — and could route **back** to `tool_router` to retry or fetch more before responding. That's a genuine upgrade (it's the "reflection" that makes agents self-correct), but it's a localized change to one node, so we documented it as a clean extension rather than build it speculatively now.

---

## 12. One-paragraph summary for an interview

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