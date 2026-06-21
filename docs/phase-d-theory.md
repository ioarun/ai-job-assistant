# Phase D — Theory & Concepts

> The *why* behind the LangGraph agent. Read this for the concepts; read
> [phase-d.md](phase-d.md) for the file-by-file build walkthrough (written as we build).
> Last updated: 2026-06-21.
>
> **Status: CORE GRAPH BUILT** — `app/agent/{state,tools,nodes,graph}.py` and
> `scripts/run_agent.py` now exist; see [phase-d.md](phase-d.md) for the build
> walkthrough. Resolved forks: HITL gate = **dynamic interrupt on a live Adzuna call**
> (Step 6, first option); planner uses an **explicit plan**, not `bind_tools` (Step 3).
> Still deferred: SSE endpoint (Step 7) and long-term memory (Step 4, long-term half).

---

## The big picture: from a fixed pipeline to an agent

Phase C left us with four clean tools — `search_jobs`, `analyze_gap`,
`suggest_projects`, `generate_interview_questions` — and a hand-wired script
([scripts/run_pipeline.py](../scripts/run_pipeline.py)) that calls them in a
**fixed order**: search → pick → analyze → suggest → interview. That script is a
*pipeline*: the control flow is baked in by the programmer.

Phase D replaces the programmer's fixed order with a **model's decision**. An
**agent** is a system where an LLM, in a loop, looks at the current situation and
*chooses the next action* — which tool to call, with what arguments, or whether
it's done. The same four tools; the difference is **who decides the order**.

> Pipeline: *you* wrote `search() then analyze() then suggest()`.
> Agent: the model reads "find 3 AU AI roles, analyse my gaps for the top one,
> suggest a project" and *works out* that it needs search → analyze → suggest,
> in that order, calling each tool with arguments it picked itself.

**LangGraph** is the framework we use to build that agent. Its core claim: an
agent is best modelled as a **state machine** — a graph of nodes (steps) connected
by edges (transitions) operating on a shared **state** — rather than as one opaque
`while` loop. This doc explains why that framing is powerful and how every piece
of Phase D maps onto it.

### Why a graph instead of just a `while` loop?

You *can* build an agent with a plain loop: "call the LLM; if it asked for a tool,
run the tool, append the result, repeat; else stop." That's the **ReAct loop**, and
LangGraph even ships it prebuilt as `create_react_agent`. So why a graph?

Because the moment you want anything beyond the basic loop, the loop sprouts
`if`-branches that become unmanageable:

- *"Show me the plan and let me approve it before spending money"* → a **human-in-the-loop pause**.
- *"After getting results, reflect on whether they actually answered the question"* → a **reflector step**.
- *"Remember what we discussed last session"* → **persistent memory**.
- *"Stream the agent's progress to the UI as it happens"* → **streaming**.
- *"If this run crashes, resume from where it stopped"* → **durable checkpoints**.

A graph makes each of these a **named node or a property of an edge** instead of
another nested branch. The control flow becomes *data you can inspect, draw, trace,
pause, and resume* — which is exactly the set of things this portfolio is meant to
demonstrate. That's why PROJECT_PLAN.md specifies an explicit
`planner → tool_router → tool_executor → reflector → responder` graph rather than
the one-line prebuilt agent.

---

## Step 1 — State: the one object that flows through everything

A LangGraph agent is organized around a single, **typed, shared state** object.
Every node receives the current state, does its work, and returns a **partial
update** — just the keys it changed. LangGraph merges that update back into the
state and moves on. Think of it as a whiteboard the whole team writes on, not a
chain of function arguments threaded by hand.

For Phase D the state will hold roughly:

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]   # the conversation (see reducers below)
    jobs: list[Job]                            # results from search_jobs
    selected_job: Job | None                   # the one we're analysing
    gap: GapAnalysis | None                    # output of analyze_gap
    projects: ProjectSuggestions | None
    interview: InterviewKit | None
    plan: list[str]                            # the planner's intended tool sequence
    awaiting_approval: bool                    # HITL flag
```

Two things make this more than a plain dict:

### Reducers — how updates *merge*
When a node returns `{"gap": <something>}`, how should that combine with the
existing state? The default rule is **overwrite**. But for `messages` we don't want
overwrite — we want **append** (each turn adds to the history, never replaces it).
That's what `Annotated[list, add_messages]` declares: *"this channel uses the
`add_messages` reducer."* A **reducer** is just the function that says how a node's
output for a key is combined with the current value. Overwrite for scalars, append
for the message log. This is the mechanism that lets the conversation accumulate
naturally and lets parallel nodes write without clobbering each other.

### Channels and the BSP execution model
Each key in the state is a **channel**. LangGraph executes in discrete
**super-steps** (a model borrowed from Google's Pregel / "bulk-synchronous
parallel"): in each super-step the active nodes all run, their updates are applied
to the channels *together at the end of the step*, and then the edges decide which
nodes are active next. The practical payoff: if two branches are active in the same
super-step they run **in parallel**, and their writes are merged by the reducers —
you get safe concurrency without manual locking.

---

## Step 2 — Nodes and edges: the structure of the machine

### Nodes
A **node** is just a function `(state) -> partial update`. It can be sync or async,
can call an LLM, hit a database, or run pure Python. Phase D's nodes:

| Node | Responsibility |
|---|---|
| `planner` | Read the user's request; produce a `plan` (which tools, in what order). |
| `tool_router` | Look at the plan + current state; decide the *next* tool to run (or "done"). |
| `tool_executor` | Actually call the chosen Phase C tool, write its output to state. |
| `reflector` | Inspect results: did we answer the request? Anything missing or to retry? |
| `responder` | Compose the final natural-language answer from the structured state. |

### Edges — where the control flow lives
An **edge** connects nodes. Two kinds:

- **Normal edge** — always go A → B. (`tool_executor → reflector`, say.)
- **Conditional edge** — a small **router function** reads the state and *returns
  the name of the next node*. This is how an agent loops and branches:

```
                    ┌─────────────── (more tools to run) ──────────────┐
                    ▼                                                   │
  START → planner → tool_router ──(plan complete)──► reflector ──(ok)──► responder → END
                    │                                     │
              (needs approval)                       (retry / gap)
                    ▼                                     │
              HITL interrupt                              └──────► tool_router
```

The loop `tool_router → tool_executor → reflector → tool_router` is the agent's
heartbeat: pick a tool, run it, check progress, pick the next — until the plan is
satisfied, then hand off to the responder. `START` and `END` are special sentinels
marking entry and termination. You build all this with `add_node`,
`add_edge(A, B)`, and `add_conditional_edges(source, router_fn, path_map)`, then
`compile()` the graph into a runnable.

> **The router function is where "agency" becomes inspectable.** In a raw `while`
> loop the decision is buried in control flow; here it's a named function whose
> input (state) and output (next node) you can log, trace, and test in isolation.

---

## Step 3 — Tools and tool-calling

How does the model actually *invoke* `analyze_gap`? Through **tool calling** (a.k.a.
function calling). You take a Python function, describe it as a schema (name,
docstring, typed arguments), and **bind** it to the chat model with
`llm.bind_tools([...])`. Now when you call the model, instead of (or as well as)
prose it can emit a structured **tool call**: *"call `analyze_gap` with
`{job_title: ..., job_description: ...}`."* Your code (or a prebuilt **ToolNode**)
executes that call and feeds the result back as a `ToolMessage`. The model sees the
result on the next turn and decides what to do next.

This is the same `with_structured_output` machinery from Phase C, pointed at a
different job: there, structured output constrained the model's *answer*; here, it
constrains the model's *choice of action*. Both are "make the LLM emit typed data
instead of free text."

**The Phase C seam — and one wrinkle.** Our tools are nearly agent-ready by design
(typed in, typed out, independently testable — that was the whole point of Phase
C). Wrapping them as LangChain tools is thin. The one real wrinkle:
`search_jobs` is **synchronous** while `analyze_gap` / `suggest_projects` /
`generate_interview_questions` are **async**. The graph runs async, so the sync tool
needs bridging (run it in a thread executor) to avoid blocking the event loop. We
build the wrappers + registry in `app/agent/tools.py`.

> **Custom graph vs. prebuilt ToolNode.** LangGraph's `create_react_agent` would
> give us the bind-tools-and-loop behaviour for free. We're building the explicit
> graph instead because the *planner* and *reflector* nodes — and the HITL gate —
> are precisely the agentic skills this portfolio exists to show. We may still
> reuse the prebuilt **ToolNode** inside our `tool_executor`; using a building
> block isn't the same as hiding the whole architecture.

---

## Step 4 — Memory: short-term vs long-term

"Memory" is two different problems with two different mechanisms.

### Short-term memory (within a conversation)
This is just **the `messages` channel persisted across turns**. When the user sends
a second message in the same conversation, the agent should see the first exchange.
LangGraph gives this to us through the **checkpointer + `thread_id`** (Step 5): all
the turns of one conversation share a thread, so the accumulated `messages` (via the
`add_messages` reducer) *are* the short-term memory. No extra machinery.

### Long-term memory (across conversations)
This is remembering something from *last week's* session in *today's* — a different
thread entirely. The conversation log won't carry it, so you need an external store
you can **search semantically**: embed a summary of each finished session, store the
vector, and at the start of a new session retrieve the most relevant past memories
to seed context. ("You analysed the Canva ML role last time and were missing MLOps
skills.")

We already own exactly this machinery from Phase B: **Chroma + embeddings**. So
long-term memory for Phase D is a **second Chroma collection** (`sessions`, separate
from `resumes`): write a session summary on completion, retrieve relevant ones on a
new session. (LangGraph also ships a generic `BaseStore` abstraction for this; we
prefer Chroma to reuse infra we've already built and traced.) The shape of the
problem — *content-addressed recall of relevant past context* — is the same RAG
pattern from Phase B, applied to the agent's own history instead of a resume.

| | Short-term | Long-term |
|---|---|---|
| Scope | One conversation (thread) | Across all conversations |
| Mechanism | `messages` + checkpointer | Chroma vector collection |
| Lookup | Just there, in order | Semantic retrieval by relevance |
| Lifetime | The thread | Persistent, curated |

---

## Step 5 — Checkpointers, threads, and persistence

A **checkpointer** saves a snapshot of the graph's state after **every super-step**,
keyed by a **`thread_id`** you pass in the call config
(`{"configurable": {"thread_id": "abc"}}`). This one mechanism underpins three
features at once:

1. **Short-term memory** — resume a thread and the prior `messages` are right there.
2. **Durability / fault-tolerance** — a crashed or interrupted run can resume from
   the last checkpoint instead of starting over.
3. **Human-in-the-loop** — pausing the graph and resuming later (Step 6) *requires*
   somewhere to park the state. The checkpointer is that somewhere.

Checkpointer flavours: `MemorySaver` (in-process, lost on restart — fine for tests),
`SqliteSaver` / `AsyncSqliteSaver` (a file — persists across restarts), `PostgresSaver`
(production). Because this project already uses SQLite, the natural choice is the
**SQLite checkpointer** (`langgraph-checkpoint-sqlite`, an added dependency): state
survives restarts and HITL pauses can be resumed across separate HTTP requests —
which matters once the SSE endpoint and approval step are involved.

> **Why "across separate HTTP requests" is the crux.** The user asks something
> (request 1) → the agent pauses for approval → the user clicks "approve" minutes
> later (request 2). Between those requests the server may have handled a hundred
> others. An in-memory checkpointer in a multi-worker deployment might not even have
> the paused state on the worker that gets request 2. A persistent checkpointer
> keyed by `thread_id` makes resume reliable. This is the real argument for SQLite
> over `MemorySaver` here.

---

## Step 6 — Human-in-the-loop (HITL) via interrupts

Some actions you don't want an autonomous agent to take unsupervised: spending
money, burning a rate-limited quota, anything hard to undo. **HITL** inserts a
checkpoint where the graph **pauses, surfaces what it's about to do, and waits for a
human to approve, edit, or reject** before continuing.

LangGraph offers two ways:

- **Static**: `compile(interrupt_before=["tool_executor"])` — always pause before a
  given node.
- **Dynamic**: call `interrupt(payload)` *inside* a node. The graph halts, the
  checkpointer saves state, and the payload (e.g. "about to run a *live* Adzuna
  search — approve?") is returned to the caller. You resume by invoking again with
  `Command(resume=<the human's answer>)`; execution continues *from that exact
  point*, state intact. Dynamic interrupts are more expressive because the node can
  decide *whether* to pause based on the situation.

**What Phase D should gate** is a genuine design decision (one of the forks I'll ask
about). The two natural candidates:

- **Plan approval** — after `planner`, show the intended tool sequence and let the
  user approve before *any* tools run. (Good UX story, demonstrates the pattern on
  the whole plan.)
- **Expensive-action approval** — pause specifically before a **live** Adzuna fetch
  (a cache *miss* burns quota; a cache *hit* is free, so this gate is conditional —
  a perfect use of a *dynamic* `interrupt`). (Tighter "guard the irreversible/costly
  thing" story, ties back to the Phase C quota lesson.)

Either way, HITL is only *possible* because of the checkpointer — pausing means
persisting state and resuming against it later.

---

## Step 7 — Streaming: showing work as it happens

A multi-tool agent run takes many seconds. Making the user stare at a spinner is
bad; streaming the agent's progress is the expected modern UX (and demonstrates the
FastAPI + SSE engineering skill). LangGraph runs are streamable out of the box via
`.astream(...)` / `.astream_events(...)`, with several **stream modes**:

| `stream_mode` | Emits | Use for |
|---|---|---|
| `"values"` | The full state after each super-step | Debugging / a complete snapshot |
| `"updates"` | Just each node's delta as it finishes | "Searched ✓ … Analysing …" progress |
| `"messages"` | LLM tokens as they're generated | Typewriter-style text streaming |
| `"custom"` | Arbitrary data you emit from a node | Domain-specific progress events |

We'll surface these to the browser as **Server-Sent Events (SSE)** — a one-way
text/event-stream over plain HTTP, simpler than WebSockets and a natural fit for
"server pushes tokens/updates to client." `sse-starlette` (already in
`requirements.txt`) adapts an async generator into an SSE response; the FastAPI
endpoint in `app/api/agent.py` will iterate the graph's event stream and yield SSE
events. For the responder's final answer we'll likely use `"messages"` (token
streaming); for intermediate "ran tool X" beats, `"updates"`.

---

## Step 8 — Observability: tracing a graph

Phase A traced single LLM calls; Phase C traced individual tool calls. An **agent
run** is where tracing earns its keep, because one request fans out into *many*
steps in an order you didn't predetermine. We keep passing the Langfuse callback
through every LLM and tool call (exactly as the Phase C tools already do), and the
trace tree then shows the **whole agent trajectory**: planner → which tools it chose
→ each tool's I/O and token cost → reflector's verdict → final answer. When the
agent does something surprising ("why did it skip the gap analysis?"), the trace is
how you find out. This is the same fan-out-debugging argument from Phase A, now at
full agent scale.

---

## How it all fits: one request, end to end

The "done-when" for Phase D is a multi-turn conversation completing *"find me 3 AU
AI engineering jobs, analyse my gaps for the top match, suggest a project,"* fully
traced. Here's the trajectory through the machine:

```
user message
   │
   ▼
[planner]  ── plans: [search_jobs, analyze_gap, suggest_projects]
   │
   ▼
[tool_router] ─► next = search_jobs
   │
   ▼
[tool_executor] ─► (cache miss → HITL: "run live Adzuna search?") ──pause──► human approves
   │                                                                            │
   ▼  ◄─────────────────────── Command(resume=approve) ────────────────────────┘
 state.jobs = [...]            (state restored from checkpoint, keyed by thread_id)
   │
   ▼
[tool_router] ─► next = analyze_gap (on top job) ─► [tool_executor] ─► state.gap = ...
   │
   ▼
[tool_router] ─► next = suggest_projects ─► [tool_executor] ─► state.projects = ...
   │
   ▼
[reflector] ─► "request satisfied" ─► [responder] ─► streamed final answer ─► END
```

Every arrow is an edge; every box is a node; everything the boxes read and write is
the shared state; the pause-and-resume is the checkpointer + interrupt; the final
arrow streams over SSE; the whole path is one Langfuse trace. That's a LangGraph
agent.

---

## LangGraph vs. the alternatives (and when each is right)

| Approach | What it is | When it's the right call |
|---|---|---|
| **Hand-wired pipeline** (our Phase C script) | You code the fixed tool order | The order never changes; no model decision needed |
| **Raw ReAct `while` loop** | Manual "LLM → tool → repeat" | A throwaway prototype; one tool; no memory/HITL/streaming |
| **`create_react_agent` (prebuilt)** | LangGraph's one-line tool-loop agent | You want a solid tool-calling agent fast and don't need custom planner/reflector/HITL nodes |
| **Custom `StateGraph`** (Phase D) | Explicit nodes, edges, state, checkpointer | You need control: explicit planning, reflection, HITL gates, persistence, streaming — and you want the architecture to be *visible* |

LangChain's older `AgentExecutor` is the predecessor to this; LangGraph is the
current, lower-level, more controllable successor. We choose the **custom
StateGraph** because Phase D's entire purpose is to *demonstrate* the agentic
machinery, not to hide it behind a one-liner.

---

## Glossary (quick reference)

| Term | One-liner |
|---|---|
| **Agent** | A system where an LLM, in a loop, chooses the next action from the current state. |
| **LangGraph** | A framework for building agents as state machines (nodes + edges + shared state). |
| **State** | The single typed object every node reads and writes; the agent's working memory. |
| **Channel** | One key/field of the state; updated independently, merged by its reducer. |
| **Reducer** | The function that merges a node's output into the state (overwrite vs. append). |
| **`add_messages`** | The reducer that *appends* to the conversation log instead of overwriting. |
| **Node** | A step: a function `(state) -> partial update` (LLM call, tool call, or plain code). |
| **Edge** | A transition between nodes; **normal** (always) or **conditional** (router decides). |
| **Router / conditional edge** | A function reading state and returning the next node's name — where branching/looping lives. |
| **START / END** | Sentinel nodes marking the graph's entry and termination. |
| **Compile** | Turning the assembled graph into a runnable (`.invoke/.stream/.astream`). |
| **Super-step (BSP)** | One execution tick: active nodes run, updates apply together, edges pick the next. |
| **Tool calling** | The LLM emitting a structured "call function X with these args" instead of prose. |
| **`bind_tools`** | Attaching tool schemas to a chat model so it can emit tool calls. |
| **ToolNode** | A prebuilt node that executes the tool calls in the latest AI message. |
| **ReAct loop** | The basic "reason → act (tool) → observe → repeat" agent pattern. |
| **`create_react_agent`** | LangGraph's prebuilt one-line ReAct agent. |
| **Checkpointer** | Persists state after each super-step, keyed by `thread_id`. |
| **Thread / `thread_id`** | The identifier grouping all checkpoints of one conversation. |
| **Short-term memory** | The persisted `messages` of the current thread. |
| **Long-term memory** | Cross-thread recall via a searchable store (here, a Chroma `sessions` collection). |
| **HITL** | Human-in-the-loop: pause for approval/edit before a sensitive action. |
| **Interrupt** | The mechanism that pauses a graph (static `interrupt_before` or dynamic `interrupt()`). |
| **`Command(resume=...)`** | How you resume a paused graph, feeding in the human's decision. |
| **Stream mode** | What a streamed run emits: `values` / `updates` / `messages` / `custom`. |
| **SSE** | Server-Sent Events: one-way server→client stream over HTTP; how the UI gets live updates. |

---

## One-paragraph summary for an interview

> *"Phase D turns my four standalone tools into a LangGraph agent. The key idea is
> modelling the agent as a state machine rather than a `while` loop: there's one
> typed, shared state object, and the agent is a graph of nodes —
> planner, a tool router, a tool executor, a reflector, a responder — connected by
> edges, where conditional edges (small router functions reading the state) are
> where the looping and branching live. The LLM drives it through tool calling — I
> bind my Phase C tools to the model so it emits typed 'call this tool with these
> args' actions instead of prose. I chose an explicit custom graph over LangGraph's
> prebuilt `create_react_agent` precisely because the planner, reflector, and a
> human-in-the-loop gate are the agentic skills worth showing. Memory is two things:
> short-term is just the conversation log persisted per-thread by a checkpointer,
> and long-term is semantic recall of past sessions, which I back with a second
> Chroma collection reusing my Phase B RAG infra. The checkpointer — SQLite-backed
> so state survives restarts — is the linchpin: it gives me short-term memory,
> durability, and the ability to pause for human approval before an expensive action
> like a live, quota-burning Adzuna call and resume from the exact checkpoint later.
> I stream the run to the browser over SSE so the user sees progress as it happens,
> and the whole trajectory — every tool the agent chose, its I/O and token cost —
> shows up as a single Langfuse trace, which is what makes a non-deterministic agent
> debuggable."*