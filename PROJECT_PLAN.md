# AI Job Assistant — Project Plan

**Status:** Active
**Last updated:** 2026-05-26
**Owner:** Arun
**Supersedes:** [docs/archive/2_DAY_SPRINT_PLAN_superseded_2026-05-26.md](docs/archive/2_DAY_SPRINT_PLAN_superseded_2026-05-26.md)

---

## Purpose

A portfolio-grade generative-AI project that demonstrates the full breadth of skills expected from a current GenAI engineering role. The functional product is an AI agent that helps the user navigate the Australian AI engineering job market.

**Two layers of goal:**
1. **Functional:** an agent that finds AU AI engineering roles, matches them to a resume, identifies skill gaps, suggests portfolio projects to close those gaps, and generates interview questions.
2. **Portfolio:** every architectural choice exists to demonstrate a marketable skill — agentic AI, MCP, RAG, LLMOps, engineering hygiene.

---

## Skills demonstrated by this project

| Skill area | How it shows up |
|---|---|
| **Agentic AI** | LangGraph agent: planner → tool-selection → execution → reflection. Memory, HITL checkpoints, streaming. |
| **MCP (Model Context Protocol)** | One capability (job-search) shipped as an MCP server; demo with Claude Desktop as the client. |
| **RAG** | Resume + job descriptions in Chroma. Hybrid retrieval (BM25 + dense), reranker, multi-query. Retrieval evals (recall@k, MRR). |
| **LLMOps** | Langfuse tracing from day one. Golden-dataset evals via Promptfoo. GitHub Actions prompt-regression gate. Cost & latency dashboards. Prompt versioning. |
| **Engineering** | FastAPI + SSE streaming, Pydantic, async, Docker, structured logging, GitHub Actions CI. |
| **(Optional) Training** | LoRA fine-tune of a small classifier (e.g. job-seniority detector). |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Streamlit UI (streaming + embedded trace links)    │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  FastAPI Gateway                                    │
│  • SSE streaming, request validation, OpenAPI docs  │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  LangGraph Agent (orchestrator)                     │
│  plan → choose-tool → execute → reflect → respond  │
│  + memory (short: conversation; long: vector)       │
│  + HITL checkpoints (approve before applying)       │
└──────────────────────┬──────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        ▼                              ▼
  ┌───────────────────┐         ┌──────────────────┐
  │ MCP server        │         │ Internal tools   │
  │ • job-search      │         │ • db queries     │
  │ (external-ready)  │         │ • parsers        │
  └───────────────────┘         │ • rag-retrieve   │
                                │ • gap-analyzer   │
                                │ • interview-gen  │
                                └──────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  Data layer                                         │
│  • Chroma (resume + job embeddings, hybrid index)   │
│  • SQLite (sessions, jobs cache, eval results)      │
│  • Local FS (uploaded PDFs)                         │
└─────────────────────────────────────────────────────┘

╔═════════════════════════════════════════════════════╗
║  LLMOps (cross-cutting, day-one integration)        ║
║  • Langfuse: traces, costs, eval store              ║
║  • Promptfoo: CI evals on golden dataset            ║
║  • GitHub Actions: prompt regression gate           ║
║  • Cost & latency dashboard (Langfuse views)        ║
╚═════════════════════════════════════════════════════╝
```

---

## Stack (locked)

Aligned with sibling project `pdf-rag` for package reuse.

**Core**
- Python 3.10+
- FastAPI + Uvicorn + Pydantic + pydantic-settings
- Streamlit
- SQLAlchemy + aiosqlite (SQLite for v1)
- Docker (Ubuntu 22.04 + `uv pip install --system`)

**LLM / RAG**
- `langchain` + `langchain-openai` + `langchain-chroma` + `langchain_text_splitters`
- OpenAI `gpt-4o-mini` (LLM) and `text-embedding-3-small` (embeddings)
- `UnstructuredPDFLoader` + `pdfplumber` for PDFs
- Chroma vector store
- BM25 via `rank_bm25`
- Reranker via `sentence-transformers` cross-encoder (e.g. `ms-marco-MiniLM-L-6-v2`)

**Agent**
- `langgraph` (state-machine orchestration, HITL, streaming)

**MCP**
- `mcp` Python SDK (server side)
- Claude Desktop as the demo client

**LLMOps**
- `langfuse` (self-hosted via docker-compose)
- `promptfoo` (CLI, run from GitHub Actions)

**External APIs**
- Adzuna (jobs)
- OpenAI

---

## Phased build plan

Each phase is its own working session. Phase A includes Langfuse so every subsequent phase is traced from the start.

### Phase A — Foundation + observability
- Project skeleton (`app/`, `app/core/`, `app/services/`, `app/models/`, `app/db/`, `streamlit_app/`, `prompts/`, `tests/`, `evals/`, `docs/`)
- `requirements.txt` mirroring pdf-rag + agent + MCP + LLMOps additions
- `app/core/config.py` (pydantic-settings)
- `app/main.py` (FastAPI with `/health`, structured logging)
- `Dockerfile` + `docker-compose.yml` (app + Langfuse + Postgres for Langfuse)
- Langfuse Python client wired so every LLM call is traced
- `.env.example` updated with all required secrets

**Done when:** `docker compose up` runs FastAPI + Langfuse; `/health` is green; a sample LLM call appears as a trace in the Langfuse UI.

### Phase B — RAG capability
- Resume parsing service (PDF → text → chunks)
- Chroma collection bootstrap
- Hybrid retriever: BM25 + dense, fused via Reciprocal Rank Fusion
- Cross-encoder reranker on top-k
- Retrieval evals: small golden set of (query, expected-doc-id) pairs, compute recall@k and MRR

**Done when:** Given a resume PDF, retrieval returns relevant chunks for sample queries; eval script reports recall@5 ≥ baseline.

### Phase C — Tool implementations
Each capability is a clean, individually-testable function/service:
- `adzuna_client.py` — search AU AI engineering roles, cache to SQLite
- `gap_analyzer.py` — given resume + job, return structured skill gaps (Pydantic model)
- `project_suggester.py` — given gaps + interests, return 3-5 project ideas
- `interview_generator.py` — given job + resume, return 5-10 tailored questions + suggested answers

Each is callable directly (unit-testable) AND ready to be wrapped as a tool in Phase D.

**Done when:** Each function can be called from a notebook and returns structured output; each is traced in Langfuse.

### Phase D — LangGraph agent
- Define agent state schema
- Nodes: `planner`, `tool_router`, `tool_executor`, `reflector`, `responder`
- Tools registered from Phase C functions
- Short-term memory (conversation history); long-term memory (Chroma collection of past sessions)
- HITL checkpoint before destructive/expensive actions
- SSE streaming endpoint in FastAPI

**Done when:** A multi-turn conversation can complete an end-to-end task ("find me 3 AU AI engineering jobs, analyse my gaps for the top match, suggest a project") with traces visible in Langfuse.

### Phase E — MCP server
- Refactor `adzuna_client.py` capability into an MCP server using the `mcp` Python SDK
- Define `search_jobs` MCP tool with proper schema
- Connect Claude Desktop to it via config
- Document the integration in README

**Done when:** Claude Desktop can call `search_jobs` and return AU AI engineering jobs.

### Phase F — Evals + CI
- Build golden datasets:
  - Gap analysis: (resume, job) → expected key gaps
  - Interview gen: (resume, job) → expected question categories
  - Retrieval: (query, expected doc IDs)
- Promptfoo configs for each
- GitHub Actions workflow: run evals on PR, fail if scores regress beyond threshold
- Langfuse eval store records every CI run

**Done when:** A PR that degrades prompt quality is auto-blocked by CI.

### Phase G — Streamlit UI
- Multi-page workflow: Upload → Search → Match → Gap → Projects → Interview
- Streaming responses via SSE
- Embedded "View trace in Langfuse" link on each result
- Cost panel summarising token spend per session

**Done when:** End-to-end user flow works in the browser with visible streaming and cost.

### Phase H (optional) — Fine-tuning
- Small LoRA fine-tune of an open model (e.g. classifier for job-seniority levels from descriptions)
- Document training data prep, training run, eval metrics, deployment path

---

## Repository layout (target)

```
ai-job-assistant/
├── app/
│   ├── main.py                       # FastAPI entry
│   ├── api/                          # routes
│   ├── core/                         # config, logging, prompts
│   ├── services/                     # parsers, retrievers, tools
│   ├── agent/                        # LangGraph state, nodes, tools registry
│   ├── mcp_server/                   # standalone MCP server (Phase E)
│   ├── models/                       # Pydantic + SQLAlchemy models
│   ├── db/                           # SQLite setup
│   └── observability/                # Langfuse wiring
├── streamlit_app/
│   ├── app.py
│   └── pages/
├── prompts/                          # versioned prompt templates
├── evals/
│   ├── datasets/                     # golden data
│   ├── promptfoo.yaml
│   └── run_evals.py
├── tests/
├── data/                             # local Chroma + SQLite (gitignored)
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml            # app + langfuse + postgres
├── .github/workflows/
│   ├── lint.yml
│   ├── tests.yml
│   └── evals.yml                     # prompt regression gate
├── docs/
│   ├── archive/
│   └── architecture.md
├── requirements.txt
├── .env.example
├── README.md
└── PROJECT_PLAN.md
```

---

## Working style

- Arun is the main developer; Claude advises what to do next and reviews.
- One phase per session. Phase boundaries are checkpoints — don't run ahead.
- All phases ship to `main` only after their "Done when" criteria are met.
