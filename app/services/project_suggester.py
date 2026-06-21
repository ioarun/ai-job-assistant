"""Portfolio project suggester (Phase C, tool #3).

Takes a GapAnalysis (from the gap analyzer) and proposes concrete portfolio
projects that would close the candidate's missing/partial skills. An LLM tool
reusing the structured-output + Langfuse patterns from the gap analyzer.

Input here is mostly our own structured data (skill strings from a GapAnalysis,
already produced under the gap analyzer's injection hardening), so injection risk
is low; we rely on structured-output validation (guardrail #1).
"""
import logging

from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.models.analysis import GapAnalysis, ProjectSuggestions
from app.observability.langfuse_client import get_langchain_callback

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior engineering mentor advising a candidate on what to build to become a strong fit for a specific role.

You are given a skill-gap analysis: the job title, the candidate's overall fit, and which required skills are matched, partial, or missing. Propose concrete, portfolio-worthy PROJECTS the candidate could build to close the most important gaps.

Guidelines:
- Prioritize the missing skills, then the partial ones. Do NOT propose projects for skills already matched.
- Each project must be realistic for a motivated individual and produce demonstrable artifacts (a deployed app, a benchmark, a repo, a demo).
- A single project may cover several related gaps — prefer a few high-impact projects over many trivial ones.
- Be specific and concrete; avoid vague advice like "learn cloud"."""

USER_TEMPLATE = """Job title: {job_title}
Overall fit score: {fit_score}/100
Fit summary: {summary}

Matched skills (already strong — do NOT target these): {matched}
Partial skills (some evidence — could strengthen): {partial}
Missing skills (no evidence — PRIORITIZE these): {missing}

Suggest 3-5 portfolio projects, prioritized by how much they close the missing skills."""


async def suggest_projects(gap: GapAnalysis) -> ProjectSuggestions:
    """Suggest portfolio projects that close the gaps in a GapAnalysis.

    Args:
        gap: The gap analysis produced by analyze_gap().

    Returns:
        A validated ProjectSuggestions.
    """
    settings = get_settings()

    callback = get_langchain_callback()
    callbacks = [callback] if callback else []
    llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0.3)
    structured = llm.with_structured_output(ProjectSuggestions)

    messages = [
        ("system", SYSTEM_PROMPT),
        ("human", USER_TEMPLATE.format(
            job_title=gap.job_title,
            fit_score=gap.fit_score,
            summary=gap.summary,
            matched=", ".join(gap.matched_skills) or "(none)",
            partial=", ".join(gap.partial_skills) or "(none)",
            missing=", ".join(gap.missing_skills) or "(none)",
        )),
    ]

    log.info("Suggesting projects", extra={"job_title": gap.job_title, "missing": len(gap.missing_skills)})
    result: ProjectSuggestions = await structured.ainvoke(
        messages, config={"callbacks": callbacks, "run_name": "tool.project_suggester"}
    )
    result.job_title = gap.job_title  # authoritative
    log.info("Project suggestions complete", extra={
        "job_title": gap.job_title, "suggestions": len(result.suggestions),
    })
    return result