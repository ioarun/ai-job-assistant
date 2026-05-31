# AI Job Application Assistant

A portfolio-grade generative-AI project that helps navigate the Australian AI engineering job market. An agent searches AU AI engineering roles, matches them against a resume, identifies skill gaps, suggests portfolio projects to close those gaps, and generates tailored interview questions.

Beyond the functional product, every architectural choice is deliberately picked to demonstrate the full breadth of skills expected of a current GenAI engineering role: **agentic AI (LangGraph)**, **MCP (Model Context Protocol)**, **RAG (hybrid retrieval + reranking)**, and **LLMOps (Langfuse, Promptfoo, GitHub Actions prompt-regression gates)**.

> 🤖 **Co-built with [Claude Code](https://www.anthropic.com/claude-code)** — architecture, scaffolding, and walkthroughs developed in collaboration with Anthropic's Claude. Arun is the lead developer; Claude advises on what to build and reviews.

## Project plan & architecture

- [PROJECT_PLAN.md](PROJECT_PLAN.md) — phased build plan (A → H) and locked decisions
- [docs/architecture.md](docs/architecture.md) — system diagram and tech stack
- [docs/phase-a.md](docs/phase-a.md) — Phase A walkthrough (foundation + Langfuse)

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

## Status

| Phase | Description | Status |
|---|---|---|
| A | Foundation + Langfuse tracing | ✅ Complete |
| B | RAG capability (Chroma + hybrid + rerank) | 🛠 In progress |
| C | Tool implementations (Adzuna, gap analysis, etc.) | ⏳ Pending |
| D | LangGraph agent orchestration | ⏳ Pending |
| E | MCP server + Claude Desktop demo | ⏳ Pending |
| F | Evals + CI prompt-regression gate | ⏳ Pending |
| G | Streamlit UI | ⏳ Pending |
| H | (Optional) LoRA fine-tuning | ⏳ Pending |
