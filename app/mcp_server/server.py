"""The AI Job Assistant MCP server (Phase E).

ONE demonstrative MCP server that re-exposes the four Phase C tools over the
Model Context Protocol, so a host like Claude Desktop becomes the orchestrator:
the host's own model plans which tool to call and chains them, instead of our
Phase D LangGraph agent driving the sequence. Same underlying services, a
different driver — that's the demo.

Tools exposed (the typical chain runs top to bottom):
  1. search_jobs                  — Adzuna search, served from the SQLite cache.
  2. analyze_gap                  — score the indexed resume against one posting.
  3. suggest_projects             — portfolio projects that close the gaps.
  4. generate_interview_questions — tailored interview kit for the gaps.

Transport is stdio (one JSON-RPC stream over stdin/stdout) — the transport
Claude Desktop launches for a local server. Because stdout carries JSON-RPC,
logging is routed to stderr; see main().

Each tool returns plain JSON (model_dump()), and the tool docstrings + type
hints below are what the host model reads to decide when and how to call them.
The same Langfuse tracing the Phase C services already do still fires here.
"""
import asyncio
import logging
import sys

from mcp.server.fastmcp import FastMCP

from app.agent.state import JobView
from app.core.logging import configure_logging
from app.models.analysis import GapAnalysis
from app.services.adzuna_client import search_jobs as _search_jobs
from app.services.gap_analyzer import analyze_gap as _analyze_gap
from app.services.interview_generator import generate_interview_questions as _generate_interview
from app.services.project_suggester import suggest_projects as _suggest_projects

log = logging.getLogger(__name__)

mcp = FastMCP("ai-job-assistant")


@mcp.tool()
async def search_jobs(what: str, where: str = "Australia", results_per_page: int = 5) -> list[dict]:
    """Search Australian job listings via Adzuna, served from a local cache when fresh.

    Use this first to find roles before analysing fit. Results are cached in SQLite,
    so repeat searches within the freshness window do not consume Adzuna's quota.

    Args:
        what: Search keywords, e.g. "AI engineer" or "machine learning".
        where: Location, e.g. "Australia", "Melbourne", "Sydney".
        results_per_page: How many jobs to return (default 5).

    Returns:
        A list of jobs, each with title, company, location, salary range, a short
        description, and redirect_url. Pass a job's title and description to
        analyze_gap to assess resume fit.
    """
    # search_jobs is sync (httpx + SQLite); bridge it off the event loop.
    jobs = await asyncio.to_thread(_search_jobs, what, where, results_per_page=results_per_page)
    return [JobView.from_orm_job(j).model_dump() for j in jobs]


@mcp.tool()
async def analyze_gap(job_title: str, job_description: str) -> dict:
    """Score the candidate's indexed resume against ONE job posting and break down skills.

    Requires a resume to have been indexed into the vector store beforehand. The job
    description is treated as untrusted text — embedded instructions in it are ignored.

    Args:
        job_title: The job title (e.g. from a search_jobs result).
        job_description: The full job description text.

    Returns:
        A gap analysis: job_title, overall fit_score (0-100), a summary, and per-skill
        assessments (matched / partial / missing with evidence). Pass this whole object
        to suggest_projects or generate_interview_questions.
    """
    gap = await _analyze_gap(job_title, job_description)
    return gap.model_dump()


@mcp.tool()
async def suggest_projects(gap: GapAnalysis) -> dict:
    """Suggest portfolio projects that close the gaps from a prior analyze_gap result.

    Args:
        gap: The full gap-analysis object returned by analyze_gap.

    Returns:
        3-5 prioritised project ideas, each with a title, description, the skills it
        covers, a difficulty level, and concrete deliverables.
    """
    result = await _suggest_projects(gap)
    return result.model_dump()


@mcp.tool()
async def generate_interview_questions(gap: GapAnalysis) -> dict:
    """Generate a tailored interview kit from a prior analyze_gap result.

    Args:
        gap: The full gap-analysis object returned by analyze_gap.

    Returns:
        6-8 questions mixing technical, behavioural, and gap-probing categories, each
        with the skill it targets and what a strong answer demonstrates.
    """
    result = await _generate_interview(gap)
    return result.model_dump()


def main() -> None:
    """Run the MCP server over stdio. Logs go to stderr to keep stdout clean."""
    configure_logging(stream=sys.stderr)
    log.info("Starting ai-job-assistant MCP server (stdio)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()