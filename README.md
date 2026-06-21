# AI Job Application Assistant

A portfolio-grade generative-AI project that helps navigate the Australian AI engineering job market. An agent searches AU AI engineering roles, matches them against a resume, identifies skill gaps, suggests portfolio projects to close those gaps, and generates tailored interview questions.

Beyond the functional product, every architectural choice is deliberately picked to demonstrate the full breadth of skills expected of a current GenAI engineering role: **agentic AI (LangGraph)**, **MCP (Model Context Protocol)**, **RAG (hybrid retrieval + reranking)**, and **LLMOps (Langfuse, Promptfoo, GitHub Actions prompt-regression gates)**.

> 🤖 **Co-built with [Claude Code](https://www.anthropic.com/claude-code)** — architecture, scaffolding, and walkthroughs developed in collaboration with Anthropic's Claude. Arun is the lead developer; Claude advises on what to build and reviews.

## Project plan & architecture

- [PROJECT_PLAN.md](PROJECT_PLAN.md) — phased build plan (A → H) and locked decisions
- [docs/architecture.md](docs/architecture.md) — system diagram and tech stack
- [docs/phase-a.md](docs/phase-a.md) — Phase A walkthrough (foundation + Langfuse)
- [docs/phase-a-theory.md](docs/phase-a-theory.md) — Phase A theory & concepts (observability/LLMOps, tracing model, config cascade, OLTP/OLAP, container orchestration)
- [docs/phase-b.md](docs/phase-b.md) — Phase B walkthrough (hybrid retrieval + eval gate)
- [docs/phase-b-theory.md](docs/phase-b-theory.md) — Phase B theory & concepts (RAG, BM25, embeddings, RRF, reranking, eval metrics)
- [docs/phase-c.md](docs/phase-c.md) — Phase C walkthrough (tool implementations: Adzuna, gap analyzer, project suggester, interview generator)
- [docs/phase-c-theory.md](docs/phase-c-theory.md) — Phase C theory & concepts (caching, untrusted input, structured output, prompt injection & guardrails)

## Quick start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env: set OPENAI_API_KEY, ADZUNA_* (optional), leave LANGFUSE_* empty for now

# 2. Bring the stack up (FastAPI + Langfuse v3 stack)
docker compose -f docker/docker-compose.yml --env-file .env up -d

# 3. Wait ~90 seconds, then verify
curl http://localhost:8000/health        # FastAPI
open http://localhost:3000               # Langfuse UI (dev@example.com / dev-password-change-me)

# 4. Generate Langfuse API keys in the UI, paste into .env, then:
docker compose -f docker/docker-compose.yml up -d --force-recreate app

# 5. Send a smoke-test LLM trace
docker compose -f docker/docker-compose.yml exec app python3 scripts/smoke_trace.py
```

### RAG: index a resume and run the retrieval eval (Phase B)

```bash
# Drop a resume PDF in data/uploads/, then index it (prints the chunk_ids)
docker compose -f docker/docker-compose.yml exec app \
  python3 -m scripts.index_resume "data/uploads/<your_resume>.pdf"

# Run the hybrid-retrieval quality gate (recall@k / MRR; non-zero exit below baseline)
docker compose -f docker/docker-compose.yml exec app \
  python3 -m evals.run_retrieval_eval
```

### Run the full pipeline end to end (Phase C)

Once a resume is indexed, `run_pipeline.py` drives all four Phase C tools in
sequence — **search a live Adzuna job → analyze the resume-vs-job skill gap →
suggest portfolio projects → generate tailored interview questions** (the
LangGraph agent that automates this orchestration is Phase D):

```bash
# Defaults: what="AI engineer", where="Australia", analyze the first result
docker compose -f docker/docker-compose.yml exec app \
  python3 -m scripts.run_pipeline

# Customize the search and which result to analyze
docker compose -f docker/docker-compose.yml exec app \
  python3 -m scripts.run_pipeline --what "machine learning engineer" --where Melbourne --pick 2 --results 8
```

| Flag | Default | Meaning |
|---|---|---|
| `--what` | `AI engineer` | Job search keywords |
| `--where` | `Australia` | Location |
| `--pick` | `0` | Index of the search result to analyze (0-based) |
| `--results` | `5` | Number of jobs to fetch |

Steps 3–5 make real OpenAI calls; the Adzuna search is served from the SQLite
cache on repeat queries. Each tool call is traced in Langfuse.

Individual tools can also be exercised on their own via the opt-in smoke scripts
(`scripts/smoke_adzuna_search.py`, `smoke_gap_analyzer.py`,
`smoke_project_suggester.py`, `smoke_interview_generator.py`).

## Status

| Phase | Description | Status |
|---|---|---|
| A | Foundation + Langfuse tracing | ✅ Complete |
| B | RAG capability (Chroma + hybrid + rerank) | ✅ Complete |
| C | Tool implementations (Adzuna, gap analysis, project suggester, interview gen) | ✅ Complete |
| D | LangGraph agent orchestration | ⏳ Pending |
| E | MCP server + Claude Desktop demo | ⏳ Pending |
| F | Evals + CI prompt-regression gate | ⏳ Pending |
| G | Streamlit UI | ⏳ Pending |
| H | (Optional) LoRA fine-tuning | ⏳ Pending |
