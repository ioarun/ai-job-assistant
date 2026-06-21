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

You are given a skill-gap analysis: the job title, overall fit, and which required skills are matched, partial, or missing. Generate a balanced set of interview questions tailored to THIS candidate and role.

Guidelines:
- Mix three categories: technical (probe depth on required skills), behavioral (past experience, teamwork, problem-solving), and gap-probing (directly explore missing/partial skills to gauge potential and self-awareness).
- For matched skills, ask questions that let a strong candidate demonstrate real depth — not trivia.
- For missing/partial skills, ask how they'd approach or learn them, not gotchas designed to fail them.
- For each question, state what a strong answer demonstrates.
- Be specific to the role; avoid generic questions that could apply to any job."""

USER_TEMPLATE = """Job title: {job_title}
Overall fit score: {fit_score}/100
Fit summary: {summary}

Matched skills (probe for depth): {matched}
Partial skills (explore how they'd strengthen): {partial}
Missing skills (gap-probing — gauge approach & learning): {missing}

Generate 6-8 tailored interview questions across the three categories."""


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