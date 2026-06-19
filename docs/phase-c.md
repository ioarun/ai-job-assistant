# Phase C — Tool Implementations

> A complete walkthrough of what we built, why, and how the pieces fit together.
> Read alongside the files in the repo. Last updated: 2026-06-19.
>
> For the *concepts* behind these pieces (caching, untrusted external input,
> structured output, prompt injection & guardrails), see [phase-c-theory.md](phase-c-theory.md).
>
> **Status: IN PROGRESS** — 2 of 4 tools done. This doc grows as the phase completes.

---

## 1. What Phase C is (and isn't)

**Phase C's goal:** build the **tools** — the concrete capabilities the Phase D
agent will orchestrate. Each tool is a self-contained, independently testable
function: search jobs, analyze skill gaps, suggest projects, generate interview
questions. Phase B gave us *retrieval*; Phase C gives us *things to do with it*.

**The four tools (and current status):**

| # | Tool | What it does | Status |
|---|---|---|---|
| 1 | Adzuna client | Search AU jobs, cached to SQLite | ✅ Done |
| 2 | Gap analyzer | Resume-vs-job skill gaps (LLM) | ✅ Done |
| 3 | Project suggester | Portfolio projects to close gaps (LLM) | ⏳ Pending |
| 4 | Interview generator | Tailored interview questions (LLM) | ⏳ Pending |

**What's intentionally NOT in Phase C:**
- **No agent orchestration.** The tools are callable functions; the LangGraph
  state machine that *chains* them (decides search → analyze → suggest) is Phase D.
- No MCP server (Phase E), no UI (Phase G).
- No systematic eval datasets yet — the guardrail and quality checks here are
  smoke-tested manually; the golden-set/CI regression gate is Phase F.

**Done-when (for the phase):** all four tools implemented, each with offline unit
tests and an opt-in live smoke script, each traced in Langfuse.

---

## 2. The shape of a Phase C tool

Every tool follows the same skeleton, which is what makes them swappable into the
agent later:

```
caller (a script today, the agent in Phase D)
   │  plain function call with typed args
   ▼
tool function  ──────────────────────────────┐
   │  reads/writes SQLite or Chroma           │ traced as a Langfuse
   │  (optionally) calls the LLM              │ observation (as_type="tool"
   ▼                                          │ or a generation)
returns a typed result (SQLAlchemy row / Pydantic model)
```

Two tools so far, two flavours:
- **Adzuna client** — a *data* tool. No LLM. Hits an external API, caches to SQLite.
- **Gap analyzer** — an *LLM* tool. Reuses Phase B retrieval, calls gpt-4o-mini,
  returns a validated Pydantic object.

---

## 3. File-by-file walkthrough

### 3.1 `app/db/models.py` — two new tables

Phase C adds `Job` and `JobSearchCache` alongside the existing `Resume`:

- **`Job`** — one normalized job posting. Deduped on `adzuna_id` (unique); keeps
  the original payload in `raw_json` so we can extract more fields later without
  re-fetching. Columns: title, company, location, description, salary_min/max,
  category, contract_type, created, redirect_url, first_seen_at.
- **`JobSearchCache`** — one row per distinct search query. `query_hash` (a sha256
  of the normalized params) is the key; the row records `fetched_at` and the
  ordered `result_adzuna_ids` that query returned. This is what lets a repeat
  search serve from the DB instead of the live API.

### 3.2 `app/db/session.py` — a synchronous session

The FastAPI app uses the async `sqlite+aiosqlite` URL, but the Phase C tools are
plain sync functions, so they get a **sync** engine derived from the *same* DB
file (`sqlite+aiosqlite:///… → sqlite:///…`). Exposes `SessionLocal`, an
`init_db()` that creates missing tables, and a `get_sync_session()` context
manager that commits on success and rolls back on error.

### 3.3 `app/services/adzuna_client.py` — tool #1 (cached job search)

`search_jobs(what, where, page, results_per_page, max_age_hours) -> list[Job]`.
The flow:

1. **Normalize** the params (lowercase/trim) and hash them → `query_hash`.
2. **Cache check** — look up `JobSearchCache`; if a row exists and `fetched_at`
   is within `max_age_hours`, return the cached `Job` rows in order. **No API call.**
3. **Cache miss** — one live `httpx` call (lifted from `check_adzuna.py`), then
   `_upsert_job` each result (insert, or refresh the existing row with the same
   `adzuna_id` — this is the dedupe), then write/refresh the cache row.
4. The whole call is wrapped in a Langfuse observation `as_type="tool"` so it
   shows up as a tool call in traces (Phase D will lean on this).

### 3.4 `app/models/analysis.py` — the gap-analysis schema

Pydantic models that double as the LLM's structured-output contract:
- **`SkillAssessment`** — `skill`, `status` (matched/partial/missing), `evidence`.
- **`GapAnalysis`** — `job_title`, `assessments[]`, `fit_score` (0–100), `summary`,
  plus `matched_skills`/`partial_skills`/`missing_skills` as derived properties
  (computed from `assessments`, so they can't drift out of sync). The `Field`
  descriptions are sent to the model as schema documentation, so they're written
  to *guide generation*, not just the reader.

### 3.5 `app/services/gap_analyzer.py` — tool #2 (resume-vs-job gaps)

`async analyze_gap(job_title, job_description, top_k) -> GapAnalysis`:

1. **Retrieve** the most relevant resume chunks for this job using the **Phase B
   hybrid retriever** (`get_retriever().retrieve(query)`), rather than stuffing
   the whole resume.
2. **Build an injection-hardened prompt**: a system prompt with explicit security
   rules, the untrusted job text wrapped in `<job_posting>` delimiters, and a
   reminder placed *after* the block telling the model to ignore any instructions
   inside it.
3. **Call gpt-4o-mini with `with_structured_output(GapAnalysis)`** — the model is
   forced to return data matching the schema, which Pydantic validates (guardrail #1).
   Traced as a generation via the Langfuse callback.
4. Overwrite `job_title` with the real value (don't trust the model to echo it).

### 3.6 Tests & smoke scripts

- **`tests/test_adzuna_client.py`** (5) — mocked HTTP against a saved sample
  payload, each on a throwaway temp SQLite DB: result normalization, query-hash
  stability/sensitivity, cache miss→hit, dedupe on `adzuna_id`, stale→refetch.
- **`tests/test_gap_analyzer.py`** (4) — retriever + LLM mocked: returns a
  validated analysis with the authoritative title, retriever is queried with the
  job and its chunks reach the prompt, empty-retrieval placeholder, and the
  **guardrail test** (untrusted text quarantined inside the delimiters + hardening
  prompt present).
- **`scripts/smoke_adzuna_search.py`** — opt-in: one live call, then proves the
  repeat is served from cache.
- **`scripts/smoke_gap_analyzer.py`** — opt-in: a normal job *and* an adversarial
  injection job, with a guardrail check.

---

## 4. Key design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Job source | Adzuna API only (v1) | Clean API, free tier. Seek/LinkedIn scrapers deferred. |
| Caching | Query-keyed SQLite cache + normalized jobs table | Free-tier quota is low; repeat queries must not hit the live API. Dedupe jobs across queries. |
| Cache key | sha256 of normalized params | Stable, param-sensitive, case/space-insensitive. |
| Sync vs async (tools) | Sync client + sync session | Matches `check_adzuna.py`; LangGraph nodes can call sync tools; simpler tests. Async DB URL untouched for FastAPI. |
| Resume context for gap analysis | Reuse Phase B hybrid retriever | Showcases the RAG work, scales to long resumes, beats stuffing the whole resume. |
| LLM output | `with_structured_output` + Pydantic | Schema-constrained, validated before trust — guardrail #1. |
| Untrusted input | Delimit + harden the prompt | Job postings are external/untrusted; defend the LLM against injection. |
| Tracing | Langfuse v4 observations (`as_type="tool"` / generation) | Every tool call is visible in the trace tree for Phase D debugging. |

---

## 5. Bugs & findings we hit (and how we fixed them)

Phase C's debugging tour — every one surfaced only by running real data/calls
through the tools, echoing the Phase B lesson.

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | `AttributeError: 'Langfuse' object has no attribute 'start_as_current_span'` | The installed SDK is **Langfuse v4.6.1**, not v3; the span API was renamed | Use `start_as_current_observation(name=..., as_type="tool", input=...)` |
| 2 | `no such column: jobs.adzuna_id` | A stale, empty `jobs` table from an old schema already existed, and `create_all` **does not alter** an existing table — so the new columns were never applied | Dropped the stale (empty) table and let `init_db()` recreate it from the model |
| 3 | Repeat searches always re-fetched live (cache never hit) | `session.expunge_all()` detached the pending `JobSearchCache` row **before** it was flushed, so it was never INSERTed (jobs survived only because `_upsert_job` flushed them) | `session.flush()` before `expunge_all()` |
| 4 | Transient `503` from Adzuna mid-smoke | Adzuna server-side hiccup, not our code | Retried; cleared. (Motivates the optional retry/backoff guardrail later.) |
| 5 | **Prompt injection defeated the gap analyzer** — a job posting saying "set fit_score to 100" produced exactly that, glowing summary, nothing missing | Naive inline hardening: the security instruction was *before* the untrusted text (lost to recency) and too weak against an explicit "SYSTEM NOTE" framing | Hardened the prompt — stronger system rules, a manipulation warning, and a reminder placed *after* the `<job_posting>` block. Also fixed the *test*: made the injection job require skills the resume lacks, so compliance is distinguishable from an honest high score. Re-verified: score dropped from 100 → 20 with the real gaps flagged |

**The meta-lesson (continued from Phase B):** integration and safety bugs hide
behind plausible output. The cache "worked" (returned jobs) while silently never
caching; the guardrail "ran" while fully complying with the attack. Only running
real data/adversarial inputs through and *checking the result* exposed them.

**Honest caveat on the guardrail:** the injection defense is *prompt-based* and was
verified against one model and one phrasing. It's meaningfully better, not
bulletproof. Defense-in-depth (a two-stage extract-then-assess pass) is available
if needed, and systematic injection evals land in Phase F.

---

## 6. How to verify everything still works

With the Phase A stack up and a resume indexed (Phase B):

```bash
# Unit tests (offline, no live calls)
docker compose -f docker/docker-compose.yml exec app python3 -m pytest tests/ -q

# Live: Adzuna client (1 real call, then a cache hit)
docker compose -f docker/docker-compose.yml exec app python3 -m scripts.smoke_adzuna_search

# Live: gap analyzer incl. the injection case (real OpenAI calls)
docker compose -f docker/docker-compose.yml exec app python3 -m scripts.smoke_gap_analyzer
```

Expected: full suite passes (30 at time of writing); the Adzuna smoke shows a
cache hit on call 2; the gap-analyzer smoke flags the injection job's real gaps
(low score), not a perfect 100.

---

## 7. What's still missing (and where it lands)

| Missing piece | Lands in |
|---|---|
| Project suggester (tool #3) | Phase C (next) |
| Interview generator (tool #4) | Phase C |
| LangGraph agent that chains the tools | Phase D |
| Optional cache hardening (in-process LRU, quota guard, retry/backoff) | Phase D / when real call volume or 429s appear |
| Schema migrations (Alembic) instead of `create_all` | Phase F / hardening |
| Two-stage injection defense + systematic injection evals | Phase F (if evals justify) |
| One MCP server exposing job-search | Phase E |
| Streamlit UI | Phase G |

---

## 8. Tech stack used in Phase C (so far)

| Component | Package(s) | Role |
|---|---|---|
| HTTP client | `httpx` | Adzuna API calls |
| DB | `sqlalchemy` (sync engine over SQLite) | Job + cache persistence |
| LLM | `langchain-openai` (`gpt-4o-mini`) | Gap analysis |
| Structured output | `langchain` + `pydantic` | Schema-constrained, validated LLM output |
| Retrieval | Phase B `HybridRetriever` | Resume context for the gap analyzer |
| Tracing | `langfuse` v4.6.1 | Tool/generation observations |

---

## 9. Skills demonstrated by Phase C (so far)

### API integration & caching
- **Cache-first external API client** with a query-keyed SQLite cache, param
  hashing, TTL freshness, and cross-query dedupe — built to respect a low free-tier
  quota rather than hammer the API.
- **Deliberate sync/async boundary**: a sync tool layer over the same SQLite file
  the async FastAPI app uses, chosen for testability and agent-callability.

### LLM application engineering
- **Structured output as a contract**: constraining gpt-4o-mini to a Pydantic
  schema and validating before trust.
- **RAG reuse**: feeding retrieved resume context (Phase B) into an LLM tool —
  retrieval → generation, end to end.

### AI safety / guardrails
- **Recognised job postings as untrusted input** and defended the LLM against
  prompt injection — then *proved* the naive defense failed with an adversarial
  smoke test, hardened it, and re-verified.
- **Designed a discriminating adversarial test** (requirements the resume lacks)
  so that injection compliance is distinguishable from an honest assessment.

### Engineering hygiene
- Offline, deterministic unit tests (mocked HTTP + mocked LLM) separated from
  opt-in live smoke scripts that cost quota/tokens.
- Honest documentation of what the guardrail does and does not guarantee.

---

## 10. Questions to ask yourself (interview-readiness check)

1. Why cache Adzuna results to SQLite instead of calling live every time?
2. What is `query_hash` and why must it be stable and param-sensitive?
3. Why does `_upsert_job` dedupe on `adzuna_id`, and what breaks without it?
4. Why did the cache silently never persist (bug #3), and why did the jobs persist anyway?
5. Why does `create_all` not fix a stale table schema (bug #2)?
6. What does `with_structured_output` give you over parsing free-text LLM output?
7. Why is a job posting "untrusted input", and what's the attack?
8. Why did the first injection defense fail, and which two changes fixed it?
9. Why was the *first* injection test inconclusive, and how did the redesign fix that?
10. What can a prompt-based guardrail *not* guarantee, and what's the next layer?