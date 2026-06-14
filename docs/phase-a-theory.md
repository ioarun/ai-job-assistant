# Phase A — Theory & Concepts

> The *why* behind everything Phase A implements. Read this for the concepts;
> read [phase-a.md](phase-a.md) for the file-by-file build walkthrough.
> Last updated: 2026-06-14.

---

## The big picture: observability-first LLM engineering (LLMOps)

A traditional web app is mostly **deterministic**: the same request produces the same response, and when something breaks there's a stack trace pointing at the line. LLM applications are different in three ways that change how you have to build them:

1. **They're non-deterministic.** The same prompt can give different answers. "It gave a bad answer" has no stack trace.
2. **They're expensive and slow.** Every call costs tokens (money) and hundreds of milliseconds to seconds. You need to *see* where the cost and latency go.
3. **They fan out.** A single user request in Phase D will trigger an agent that calls 5+ tools, each making its own LLM calls. The "execution" is a *tree*, not a line.

**Observability** is the discipline of making a running system's internal behaviour visible from the outside. **LLMOps** is observability (plus evaluation, prompt management, and cost tracking) applied specifically to LLM systems. The central Phase A decision is to wire this in **from the very first request**, not bolt it on after the product works.

**Why first, not later?** Because the alternative is debugging a non-deterministic, fanned-out, expensive system *blind*. If you add tracing only after Phase D's agent is misbehaving, you have no record of *what it did*. Build the instrument before you build the engine, and every later phase is debuggable, costable, and evaluable *for free*.

Phase A ships no product features. It's the **load-bearing foundation**: typed config, structured logging, request correlation, and a full LLM-tracing stack — the runway every later phase lands on.

---

## Step 1 — Configuration as code (typed, fail-fast, layered)

An app needs runtime values it shouldn't hardcode: API keys, model names, file paths, hosts. The naive approach is `os.getenv("OPENAI_API_KEY")` scattered everywhere. Three problems:

1. **No types.** `os.getenv` always returns a string. `DEBUG="true"` is the string `"true"`, which is *truthy even when it says "false"*. You hand-coerce every value, every time.
2. **Late failure.** A missing key blows up at *request time*, deep in a handler, maybe in production, maybe at 3am — not at startup.
3. **No single source of truth.** Which vars exist? What are their defaults? You'd have to grep the whole codebase.

**The pattern: a typed settings object** (`pydantic-settings`). You declare config once as a class with types and defaults:

```python
openai_api_key: str            # no default → app refuses to start without it
openai_model: str = "gpt-4o-mini"   # default → optional
```

- **Type coercion is automatic and validated** — `"true"` → `True`, a path string → `Path`, a non-integer where an int is expected → a startup error.
- **Fail-fast** — a required field with no default means the process won't even boot without it. You learn at second 0, not at request 10,000.
- **One source of truth with IDE autocomplete** — `settings.openai_model` everywhere; no magic strings.

### The configuration cascade
Config values come from multiple places with a **precedence order** (lowest to highest):

```
class defaults  →  .env file  →  process environment  →  docker-compose environment:
```

This layering is what lets the *same* `.env` work on your laptop and inside Docker. Example: `LANGFUSE_HOST` is `http://localhost:3000` in `.env` (so host-side scripts reach it), but the compose file *overrides* it to `http://langfuse-web:3000` inside the container (so the app reaches the service by its network name). One config, two environments, no edits. This is the **12-factor "config in the environment"** principle: the same build artifact runs anywhere; only the environment differs.

> **Secret hygiene** rides along here: `.env` is gitignored (secrets never enter version control), `.env.example` is committed (documents *which* vars exist, with placeholders), and `.dockerignore` keeps `.env` out of image layers (so secrets aren't baked into a shareable image).

---

## Step 2 — Structured logging & correlation IDs

### Why *structured* logs
A human-readable log line — `User 42 searched for AI jobs in 120ms` — is fine for one developer reading a terminal. It's useless to a machine: you can't query "all requests slower than 500ms" from prose. **Structured logging** emits each line as a machine-parseable object instead:

```json
{"ts": "...", "level": "INFO", "msg": "search complete", "user": 42, "duration_ms": 120, "request_id": "a1b2"}
```

Now a log aggregator (CloudWatch, Datadog, Loki) can filter, group, and alert on *fields*. Phase A picks the format by environment: **JSON in prod** (for aggregators), **pretty single-line in dev** (so your terminal isn't a wall of braces). Same call sites, different formatter — chosen once at startup.

### Why correlation IDs, and why a `ContextVar`
When Phase D's agent fans out to many tool calls, each emits log lines. Interleaved in the output, they're an unreadable jumble — *which* lines belong to *which* user request? A **correlation ID** (here, `request_id`) is a unique token minted per request and **attached to every log line produced while handling it**. Filter by that ID and you reconstruct one request's entire story.

The subtle part is *how* you make "the current request's ID" available to every log call without threading it through every function signature. The classic answer is a **thread-local** — a variable whose value is private to each OS thread. But **async code breaks thread-locals**: a single thread juggles many concurrent requests by switching between them at every `await`, so a thread-local would leak request A's ID into request B's logs.

The async-correct tool is a **`ContextVar`** (`contextvars`). It's like a thread-local, but the runtime carries its value across `await` boundaries *per logical task*, not per thread. Set it once in middleware at the start of a request, and every log call within that request — across every `await` — sees the right ID, with no cross-talk between concurrent requests.

### Why stdlib logging, not a fancier library
Logs here are the **unhappy-path fallback** — the heavy observability load (the request tree, costs, prompt/response payloads) is carried by Langfuse traces. So plain stdlib `logging` with two custom formatters is enough, and keeps the dependency list lean. *Pick the lightest tool that covers the job it's actually doing.*

---

## Step 3 — The tracing data model (traces, spans, observations)

This is the conceptual heart of Phase A. A **trace** is the record of one end-to-end operation (e.g. one agent run). Inside it, **spans** (Langfuse calls the general unit an **observation**) are nested timed segments representing sub-steps. The result is a **tree**:

```
TRACE: "find jobs for resume"                 ← root, total latency
├─ SPAN: retrieve resume chunks               ← a step (Phase B retriever)
├─ SPAN: adzuna.search                        ← a tool call (Phase C)
└─ GENERATION: rank job fit (LLM call)        ← a special span: model, tokens, cost
   ├─ input:  prompt
   └─ output: completion + token usage
```

Key ideas:

- **Spans nest.** A parent span's duration contains its children's. This is what turns "the request took 4 seconds" into "...of which 3.1s was one slow LLM call" — you can *see* where time and money went.
- **A "generation" is a span with extra fields.** LLM calls record the model, the prompt, the completion, and token counts — which is how Langfuse computes **cost** per call and per trace.
- **Context propagation.** For spans to nest correctly, each one must know its parent. The tracing SDK carries this "current span" through the call stack — conceptually the same context-propagation problem the correlation ID solves, one layer up.

### How traces get captured: the CallbackHandler
You don't want to hand-write span code around every LLM call. LangChain exposes **callbacks** — hooks fired on events like "chain started", "LLM call ended". Langfuse ships a **`CallbackHandler`** that listens to these and emits the matching spans automatically. You pass it once via `config={"callbacks": [handler]}` and the entire Runnable's execution becomes a trace tree, no manual instrumentation. (When we *don't* have a LangChain Runnable — like the Adzuna client, a plain HTTP call — we wrap it in an explicit span instead. Same data model, manual hook.)

### A design rule worth its own paragraph: `None`, not a no-op stub
`get_langfuse()` returns `None` when keys are absent — not a fake object that silently swallows calls. Why does this matter conceptually? A **null-object stub** that pretends to work *hides* the fact that tracing is off; you'd think you're recording and discover at debug time that nothing was captured. Returning `None` forces callers to write `if handler: ...` — making "tracing might be disabled" an *explicit, visible* branch in the code rather than a silent lie. **Fail loudly over failing silently** is the same principle as fail-fast config.

---

## Step 4 — Asynchronous telemetry & the flush problem

Sending a trace over the network takes time. If your app *waited* for each span to be acknowledged by the tracing server before continuing, you'd add latency to every user request just for bookkeeping — unacceptable. So telemetry is **asynchronous and batched**: the SDK buffers events in memory and ships them in the background, and your code returns immediately.

This buys low latency but creates one classic hazard: **the tail-loss problem.** If the process exits while events are still buffered — exactly what happens with a short-lived script like `smoke_trace.py` — those last traces are lost. The fix is an explicit **flush** on shutdown: `shutdown_langfuse()` (called from FastAPI's lifespan teardown) blocks just long enough to drain the buffer before the process dies.

The general lesson: **asynchronous I/O trades immediate delivery for throughput, so you need an explicit "drain before exit" step.** Any batched, fire-and-forget pipeline has this same requirement.

---

## Step 5 — Why the observability backend is a distributed system

Langfuse v3 runs as **six** services (web, worker, Postgres, ClickHouse, Redis, MinIO). That seems like a lot to "just store some traces." Each piece exists for a real architectural reason, and understanding why is a transferable systems-design lesson:

| Service | Role | *Why a separate piece* |
|---|---|---|
| **langfuse-web** | UI + ingestion API | The front door — receives traces, serves the dashboard. |
| **langfuse-worker** | Async trace processor | Heavy write-processing is pulled *off* the request path so ingestion stays fast. |
| **Postgres** | Structured metadata (users, projects, prompts, eval runs) | **OLTP** workload: many small transactional reads/writes, relational integrity. |
| **ClickHouse** | Trace/observation storage | **OLAP** workload: huge volume of append-only events, analytical scans ("p95 latency this week"). A columnar store crushes this; Postgres would buckle. |
| **Redis** | Ingestion queue | A **buffer** decoupling spiky inbound traffic from steady-rate processing. Producer and consumer run at their own pace. |
| **MinIO** | S3-compatible blob store | Large payloads (long prompts, images) don't belong in a database row; blob storage holds them, the DB holds a pointer. |

The two ideas worth internalizing:

- **OLTP vs OLAP.** Transactional data (who, what, relationships) and analytical data (billions of timestamped events you scan and aggregate) have *opposite* access patterns and want *different databases*. Splitting them is a standard data-architecture move — here, Postgres + ClickHouse.
- **Queue-based load levelling.** Putting Redis between "traces arriving" and "traces being written" means a sudden burst doesn't overwhelm the writer or block the sender — the queue absorbs the spike and the worker drains it at a sustainable rate. (This is the *same* producer/consumer-with-a-buffer pattern Phase A's async flushing uses, scaled up to infrastructure.)

Running this locally via Docker Compose is a real exercise of the architecture that Langfuse Cloud runs at scale — same shape, one machine.

---

## Step 6 — Containerization & orchestration concepts

Phase A's whole stack is defined in code (`Dockerfile` + `docker-compose.yml`). The concepts behind that:

### Image vs container
A **Docker image** is a frozen, layered snapshot of a filesystem + a startup command — a *recipe*. A **container** is a running instance of an image — a *cake baked from it*. One image → many identical containers. The point is **reproducibility**: the image bundles the OS libraries, Python, and dependencies, so "works on my machine" becomes "works in the image, everywhere."

### Layer caching
An image is built in **layers**, one per build step, and Docker caches each. If a layer's inputs haven't changed, it's reused. This is *why* dependencies are installed **before** application code is copied: editing your Python source invalidates only the cheap final layer, not the expensive multi-gigabyte dependency-install layer. **Order your build steps from least- to most-frequently-changing** to keep rebuilds fast.

### Bind-mount vs named volume
Both share data between host and container, for opposite purposes:
- **Bind-mount** (host directory → container path): edit code on your laptop, the container sees it instantly. Used for `app/`, `scripts/`, `evals/` to get **hot reload** in dev.
- **Named volume** (Docker-managed storage): **persists** across `docker compose down` and isn't tied to a host path. Used for Postgres/ClickHouse/MinIO data so restarting the stack doesn't wipe your traces. (Lost only on `down -v`.)

### Dependency ordering & health checks
Services depend on each other (`depends_on`), but "started" and "ready" differ:
- **`service_started`** — the container process has launched.
- **`service_healthy`** — a defined **health check** command passes (the service is actually *ready* to serve).

Phase A's app uses `service_started` (not `_healthy`) for Langfuse, deliberately: Langfuse takes 90s+ to migrate its databases on first boot, and the app already handles "Langfuse missing" gracefully (it returns `None`). Gating the app's boot on a strict health check would just block startup for no benefit. **Choose the dependency condition to match how the dependent actually behaves** — not reflexively the strictest one.

### The init-container pattern
Some setup must run **once, before** the main services — here, creating the MinIO bucket Langfuse writes to. A short-lived **init container** (`minio-init`) does that one job and exits. The pattern: *one-shot bootstrap work belongs in its own ephemeral container, not stuffed into a long-running service's startup.*

---

## Step 7 — The request lifecycle (middleware & lifespan)

Two FastAPI mechanisms encode "when does code run":

- **Lifespan** — a context manager whose pre-`yield` block runs **once at startup** and post-`yield` block runs **once at shutdown**. It's where you initialise shared resources (logging, the Langfuse client) and tear them down (flush telemetry). It replaces the deprecated `@app.on_event` hooks and cleanly shares state between the two ends of the process's life.

- **Middleware** — code that wraps **every request**, running before the route handler and after it returns. Phase A's `request_id` middleware mints/propagates the correlation ID here: it's the one place guaranteed to run for *every* request, so it's where cross-cutting concerns (request IDs, timing, auth) belong. Conceptually it's an **onion**: the request passes inward through each middleware layer to the handler, and the response passes back outward through them.

The `reset(token)` in the middleware's `finally` block is the subtle bit: it un-sets the `ContextVar` after the request so its value can't leak into an unrelated task that reuses the context. **Set-and-reset around the work** is the correct discipline for any context-scoped value.

---

## Step 8 — Singletons & lazy initialisation

`get_settings()` and `get_langfuse()` are both wrapped in `@lru_cache(maxsize=1)`. The concept: **memoise a zero-argument factory so the expensive object is built once and shared.** The first call constructs it (reads `.env`, opens the Langfuse HTTP session); every subsequent call returns the *same* instance from cache. This is dependency-injection-by-import — a lightweight **singleton** without a framework. Why it matters: you want *one* settings object (consistent config) and *one* Langfuse client (one HTTP session, one shared event buffer), not a fresh one per call site.

---

## Glossary (quick reference)

| Term | One-liner |
|---|---|
| **Observability** | Making a running system's internal behaviour visible from the outside (logs, traces, metrics). |
| **LLMOps** | Observability + evaluation + prompt/cost management applied to LLM systems. |
| **Trace** | The full record of one end-to-end operation, as a tree of spans. |
| **Span / observation** | A timed, nestable segment within a trace representing a sub-step. |
| **Generation** | A span specialised for an LLM call — records model, prompt, completion, tokens, cost. |
| **Context propagation** | Carrying "the current request/span" implicitly through the call stack. |
| **Correlation / request ID** | A unique token per request, attached to every log line it produces, to stitch them together. |
| **ContextVar** | Async-safe per-task variable; survives `await` boundaries where thread-locals leak. |
| **Structured logging** | Emitting logs as machine-parseable objects (JSON) rather than prose. |
| **CallbackHandler** | LangChain hook Langfuse uses to auto-emit spans for a Runnable's execution. |
| **Flush** | Draining a buffered/async pipeline before exit so the tail isn't lost. |
| **Fail-fast** | Surface a misconfiguration at startup, not at request time. |
| **Config cascade** | Precedence: class defaults → `.env` → process env → compose `environment:`. |
| **12-factor config** | Same build artifact everywhere; only the environment differs. |
| **OLTP / OLAP** | Transactional (small relational read/writes) vs analytical (bulk append + scan) workloads → different DBs. |
| **Queue-based load levelling** | A buffer (Redis) decoupling spiky producers from steady consumers. |
| **Image vs container** | Frozen filesystem recipe vs a running instance of it. |
| **Layer caching** | Reusing unchanged build layers; install deps before copying code to exploit it. |
| **Bind-mount** | Host dir mapped into a container (hot reload). |
| **Named volume** | Docker-managed persistent storage (survives `down`). |
| **`service_started` vs `service_healthy`** | Process launched vs health-check-passing-and-ready. |
| **Init container** | One-shot ephemeral container for pre-start bootstrap work. |
| **Lifespan** | FastAPI startup/shutdown context manager. |
| **Middleware** | Code wrapping every request (before handler + after response). |
| **Singleton via `lru_cache`** | Memoised factory so one shared instance is built once and reused. |

---

## One-paragraph summary for an interview

> *"Phase A is the observability-first foundation. I stood up a self-hosted Langfuse v3 stack — six services (web, worker, Postgres for OLTP metadata, ClickHouse for high-volume OLAP trace storage, Redis as an ingestion queue, MinIO for blob payloads) — and wired tracing in from the first request via LangChain's CallbackHandler, so every LLM call in every later phase is captured as a span in a trace tree with token cost attached. The app is FastAPI with a lifespan-managed startup/shutdown, typed fail-fast config via pydantic-settings using the standard config cascade so one `.env` works locally and in Docker, structured logging with per-request correlation IDs carried in an async-safe ContextVar, and a flush-on-shutdown so short-lived processes don't lose buffered traces. The whole stack is reproducible through a Dockerfile and Compose file that use layer caching, bind-mounts for hot reload, named volumes for persistence, and deliberate `service_started`-vs-`service_healthy` dependency ordering."*
