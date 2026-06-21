"""Phase C tools, wrapped for the LangGraph agent.

Each wrapper is `async (state) -> partial update`: it pulls its inputs from the
shared AgentState, calls the underlying Phase C tool, and returns just the state
keys it produced. tool_executor dispatches by name via TOOL_FNS; the HITL gate on
a live Adzuna call lives in the executor (see nodes.py), not here, so these stay
pure "given state, run the tool" functions.

search_jobs is synchronous (httpx + SQLite); the graph runs async, so we bridge it
with asyncio.to_thread to avoid blocking the event loop.
"""
import asyncio
import logging

from app.agent.state import AgentState
from app.services.adzuna_client import search_jobs
from app.services.gap_analyzer import analyze_gap
from app.services.interview_generator import generate_interview_questions
from app.services.project_suggester import suggest_projects

log = logging.getLogger(__name__)


async def run_search_jobs(state: AgentState) -> dict:
    """search_jobs (sync, bridged). Selects the top result as the default job."""
    jobs = await asyncio.to_thread(
        search_jobs,
        state["what"],
        state.get("where", "Australia"),
        results_per_page=state.get("results_per_page", 5),
    )
    return {"jobs": jobs, "selected_job": jobs[0] if jobs else None}


async def run_analyze_gap(state: AgentState) -> dict:
    job = state["selected_job"]
    gap = await analyze_gap(job.title, job.description or "")
    return {"gap": gap}


async def run_suggest_projects(state: AgentState) -> dict:
    return {"projects": await suggest_projects(state["gap"])}


async def run_generate_interview(state: AgentState) -> dict:
    return {"interview": await generate_interview_questions(state["gap"])}


# name -> wrapper. The planner may only emit keys from this registry; the
# tool_router walks the plan and dispatches here.
TOOL_FNS = {
    "search_jobs": run_search_jobs,
    "analyze_gap": run_analyze_gap,
    "suggest_projects": run_suggest_projects,
    "generate_interview_questions": run_generate_interview,
}

VALID_TOOLS = list(TOOL_FNS)

# Tools whose inputs aren't in state until an earlier tool ran — used by the
# router/reflector to keep the plan ordered and to give clear errors.
TOOL_DEPENDENCIES = {
    "analyze_gap": "selected_job",
    "suggest_projects": "gap",
    "generate_interview_questions": "gap",
}