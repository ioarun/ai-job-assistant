"""The single shared state object that flows through the Phase D LangGraph agent.

Every node receives the current AgentState and returns a PARTIAL update — just the
keys it changed; LangGraph merges that back in (per each channel's reducer) and moves
to the next node. See docs/phase-d-theory.md (Step 1) for the why.
"""
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel

from app.models.analysis import GapAnalysis, InterviewKit, ProjectSuggestions


class JobView(BaseModel):
    """Serializable view of a Job row — the SQLAlchemy ORM model isn't
    msgpack-serializable, so the checkpointer needs this plain Pydantic form in state."""
    adzuna_id: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    redirect_url: str | None = None

    @classmethod
    def from_orm_job(cls, j) -> "JobView":
        return cls(
            adzuna_id=j.adzuna_id, title=j.title, company=j.company,
            location=j.location, description=j.description,
            salary_min=j.salary_min, salary_max=j.salary_max,
            redirect_url=j.redirect_url,
        )


class AgentState(TypedDict, total=False):
    # The conversation log. `add_messages` APPENDS each turn instead of overwriting —
    # this is the agent's short-term memory once the thread is checkpointed.
    messages: Annotated[list, add_messages]

    # The user's request, parsed by the planner.
    what: str            # search keywords, e.g. "AI engineer"
    where: str           # location, e.g. "Australia"
    results_per_page: int  # how many jobs search_jobs should fetch

    # The planner's intended tool sequence (tool names, in order). The tool_router
    # walks this list; the reflector checks it was satisfied.
    plan: list[str]

    # Tool outputs — each written by tool_executor as the matching step runs.
    jobs: list[JobView]                  # from search_jobs
    selected_job: JobView | None         # the job we analyse (top match by default)
    gap: GapAnalysis | None              # from analyze_gap
    projects: ProjectSuggestions | None  # from suggest_projects
    interview: InterviewKit | None       # from generate_interview_questions

    # Bookkeeping for the router/reflector loop.
    completed: list[str]   # tool names already run (so the router picks the next one)
    final_answer: str      # the responder's composed natural-language reply