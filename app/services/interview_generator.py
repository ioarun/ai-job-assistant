"""Interview question generator (Phase C, tool #4).

Takes a GapAnalysis and generates tailored interview questions — probing the
candidate's matched strengths and their missing/partial gaps. The last of the
four Phase C tools; reuses the structured-output + Langfuse patterns.

Input is our own structured data (a GapAnalysis), so injection risk is low; we
rely on structured-output validation (guardrail #1).
"""
import logging

from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.models.analysis import GapAnalysis, InterviewKit
from app.observability.langfuse_client import get_langchain_callback

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an experienced technical interviewer preparing questions for a candidate interviewing for a specific role.

You are given a skill-gap analysis: the job title, overall fit, and which required skills are matched, partial, or missing. Generate a balanced set of interview questions tailored to THIS candidate and THIS role.

Guidelines:
- Mix three categories:
  - technical: probe depth on matched skills — ask about design tradeoffs, failure modes, or production experience, not definitions.
  - behavioral: reference the specific domain (AI/ML systems, deployment, team dynamics in engineering orgs). Avoid generic "tell me about a time" openers — anchor them to the role's context.
  - gap-probing: for missing/partial skills, ask how the candidate would approach or ramp up, gauging self-awareness and learning strategy rather than trying to catch them out.
- Name specific tools and technologies from the skill list in your questions — "how would you debug a LangGraph agent" beats "how would you debug an AI system".
- Each question must be distinct — no two questions probing the same skill.
- For each question, state concisely what a strong answer demonstrates."""

USER_TEMPLATE = """Job title: {job_title}
Overall fit score: {fit_score}/100
Fit summary: {summary}

Matched skills (probe for depth, name the tools in your questions): {matched}
Partial skills (explore how they'd strengthen — be specific about the technology): {partial}
Missing skills (gap-probing — gauge self-awareness and ramp-up approach): {missing}

Generate 6-8 tailored interview questions across the three categories. Each question must name specific technologies or contexts from the skill list above — no generic questions."""


async def generate_interview_questions(gap: GapAnalysis) -> InterviewKit:
    """Generate tailored interview questions from a GapAnalysis.

    Args:
        gap: The gap analysis produced by analyze_gap().

    Returns:
        A validated InterviewKit.
    """
    settings = get_settings()

    callback = get_langchain_callback()
    callbacks = [callback] if callback else []
    llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0.3)
    structured = llm.with_structured_output(InterviewKit)

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

    log.info("Generating interview questions", extra={"job_title": gap.job_title})
    result: InterviewKit = await structured.ainvoke(
        messages, config={"callbacks": callbacks, "run_name": "tool.interview_generator"}
    )
    result.job_title = gap.job_title  # authoritative
    log.info("Interview questions complete", extra={
        "job_title": gap.job_title, "questions": len(result.questions),
    })
    return result