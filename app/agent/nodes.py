"""The Phase D agent's nodes and router.

A node is `(state) -> partial update`; a router is `(state) -> next node name`.
Together with the edges wired in graph.py they form the state machine described in
docs/phase-d-theory.md (Step 2). The loop is:

    planner -> tool_router -> tool_executor -> tool_router -> ... -> reflector -> responder

tool_router is the conditional edge where the looping lives; tool_executor runs one
tool per visit and gates a LIVE Adzuna call behind a dynamic HITL interrupt.
"""
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.agent.state import AgentState
from app.agent.tools import TOOL_DEPENDENCIES, TOOL_FNS, VALID_TOOLS
from app.core.config import get_settings
from app.observability.langfuse_client import get_langchain_callback
from app.services.adzuna_client import is_search_cached

log = logging.getLogger(__name__)


def _llm(**kwargs) -> ChatOpenAI:
    """A traced ChatOpenAI, configured like the Phase C tools."""
    s = get_settings()
    return ChatOpenAI(model=s.openai_model, api_key=s.openai_api_key, temperature=0, **kwargs)


def _callbacks() -> list:
    cb = get_langchain_callback()
    return [cb] if cb else []


def _next_tool(state: AgentState) -> str | None:
    """First planned step not yet completed — the agent's next action (or None)."""
    completed = state.get("completed", [])
    for step in state.get("plan", []):
        if step not in completed:
            return step
    return None


# ── planner ──────────────────────────────────────────────────────────────
class Plan(BaseModel):
    """The planner's structured output: parsed request + ordered tool sequence."""
    what: str = Field(description="Job-search keywords, e.g. 'AI engineer'")
    where: str = Field(default="Australia", description="Location to search")
    results_per_page: int = Field(default=5, description="How many jobs to fetch")
    steps: list[str] = Field(description=f"Ordered subset of: {VALID_TOOLS}")


PLANNER_SYSTEM = f"""You plan how an AI job-search assistant should answer the user.

Available tools (use only these names): {VALID_TOOLS}
- search_jobs: find AU job listings for given keywords/location.
- analyze_gap: score the user's resume against ONE job's requirements (needs a job first).
- suggest_projects: suggest portfolio projects to close skill gaps (needs analyze_gap first).
- generate_interview_questions: produce interview questions (needs analyze_gap first).

Return the ordered list of tool steps needed to satisfy the request, plus the search
keywords (what), location (where), and how many jobs to fetch. Include only the tools
the request actually needs, in dependency order."""


def _normalize_plan(steps: list[str]) -> list[str]:
    """Keep valid steps in order, then prepend any missing prerequisites."""
    steps = [s for s in steps if s in VALID_TOOLS]
    if not steps:
        steps = ["search_jobs"]
    # Ensure dependencies precede their dependents.
    if any(s in ("suggest_projects", "generate_interview_questions") for s in steps) \
            and "analyze_gap" not in steps:
        steps = ["analyze_gap"] + steps
    if any(TOOL_DEPENDENCIES.get(s) in ("selected_job",) or s == "analyze_gap" for s in steps) \
            and "search_jobs" not in steps:
        steps = ["search_jobs"] + steps
    # Stable de-dup preserving first occurrence.
    seen, ordered = set(), []
    for s in steps:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered


async def planner(state: AgentState) -> dict:
    """Parse the user's request into a Plan and seed the search parameters."""
    user_msg = next((m.content for m in reversed(state.get("messages", []))
                     if isinstance(m, HumanMessage)), state.get("what", ""))
    structured = _llm().with_structured_output(Plan)
    plan: Plan = await structured.ainvoke(
        [SystemMessage(content=PLANNER_SYSTEM), HumanMessage(content=user_msg)],
        config={"callbacks": _callbacks(), "run_name": "agent.planner"},
    )
    steps = _normalize_plan(plan.steps)
    log.info("Planned", extra={"steps": steps, "what": plan.what})
    return {
        "what": plan.what,
        "where": plan.where,
        "results_per_page": plan.results_per_page,
        "plan": steps,
        "completed": [],
        "messages": [AIMessage(content=f"Plan: {' → '.join(steps)}")],
    }


# ── tool_router (passthrough node; routing fn below) ───────────────────────
def tool_router(state: AgentState) -> dict:
    """No-op node; exists so the loop has a named hub in the trace. The decision
    is made by route_from_router (the conditional edge)."""
    return {}


def route_from_router(state: AgentState) -> str:
    """Conditional edge: run the next tool, or reflect if the plan is done."""
    return "tool_executor" if _next_tool(state) else "reflector"


# ── tool_executor ──────────────────────────────────────────────────────────
async def tool_executor(state: AgentState) -> dict:
    """Run exactly one tool — the next unrun plan step.

    For search_jobs, if the query is NOT cached the call would burn Adzuna quota, so
    we pause with a dynamic interrupt and wait for human approval (Command(resume=...)).
    """
    tool = _next_tool(state)
    completed = list(state.get("completed", []))

    if tool == "search_jobs" and not is_search_cached(
        state["what"], state.get("where", "Australia"),
        results_per_page=state.get("results_per_page", 5),
    ):
        decision = interrupt({
            "type": "approve_live_search",
            "what": state["what"],
            "where": state.get("where", "Australia"),
            "reason": "Not cached — this will make a live, quota-limited Adzuna API call.",
        })
        approved = decision is True or (isinstance(decision, dict) and decision.get("approved"))
        if not approved:
            completed.append(tool)
            return {"completed": completed, "jobs": [], "selected_job": None,
                    "messages": [AIMessage(content="Live search declined; skipping job search.")]}

    update = await TOOL_FNS[tool](state)
    completed.append(tool)
    update["completed"] = completed
    update["messages"] = [AIMessage(content=f"Ran {tool} ✓")]
    log.info("Executed tool", extra={"tool": tool})
    return update


# ── reflector ──────────────────────────────────────────────────────────────
STATE_KEY_FOR = {
    "search_jobs": "jobs", "analyze_gap": "gap",
    "suggest_projects": "projects", "generate_interview_questions": "interview",
}


def reflector(state: AgentState) -> dict:
    """Cheap deterministic check: did every planned tool produce its output?
    (An LLM-based reflector that judges answer quality is a documented extension.)"""
    missing = [t for t in state.get("plan", []) if not state.get(STATE_KEY_FOR.get(t))]
    verdict = "All planned steps produced results." if not missing \
        else f"Missing outputs for: {missing}."
    return {"messages": [AIMessage(content=f"Reflection: {verdict}")]}


# ── responder ────────────────────────────────────────────────────────────────
RESPONDER_SYSTEM = """You are an AI job-search assistant. Using ONLY the structured
results provided, write a concise, helpful answer for the user. Summarise the jobs
found, the resume fit and key gaps, suggested projects, and interview prep — but only
for the parts that are present. Be specific and don't invent anything."""


async def responder(state: AgentState) -> dict:
    """Compose the final natural-language answer from the structured state."""
    parts = []
    if state.get("jobs"):
        parts.append("JOBS:\n" + "\n".join(
            f"- {j.title} @ {j.company} ({j.location})" for j in state["jobs"]))
    if state.get("gap"):
        g = state["gap"]
        parts.append(f"GAP (fit {g.fit_score}/100): matched={g.matched_skills} "
                     f"missing={g.missing_skills}\n{g.summary}")
    if state.get("projects"):
        parts.append("PROJECTS:\n" + "\n".join(
            f"- {p.title}: {p.description}" for p in state["projects"].suggestions))
    if state.get("interview"):
        parts.append("INTERVIEW QUESTIONS:\n" + "\n".join(
            f"- {q.question}" for q in state["interview"].questions))
    context = "\n\n".join(parts) or "(no results were produced)"

    resp = await _llm().ainvoke(
        [SystemMessage(content=RESPONDER_SYSTEM), HumanMessage(content=context)],
        config={"callbacks": _callbacks(), "run_name": "agent.responder"},
    )
    return {"final_answer": resp.content, "messages": [resp]}