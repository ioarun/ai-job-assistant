"""Tests for the interview generator (Phase C, tool #4).

LLM mocked; offline and deterministic. Assert the wiring and that the prompt is
built from the GapAnalysis (strengths to probe, gaps to explore).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.interview_generator as ig
from app.models.analysis import (
    GapAnalysis,
    InterviewKit,
    InterviewQuestion,
    SkillAssessment,
)


def _gap() -> GapAnalysis:
    return GapAnalysis(
        job_title="AI Engineer",
        assessments=[
            SkillAssessment(skill="Python", status="matched", evidence="built APIs"),
            SkillAssessment(skill="RAG systems", status="missing"),
            SkillAssessment(skill="Docker", status="partial", evidence="some CI"),
        ],
        fit_score=45,
        summary="Strong Python, lacks RAG.",
    )


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setattr(ig, "get_langchain_callback", lambda: None)  # Langfuse off

    preset = InterviewKit(
        job_title="(model-echoed title)",
        questions=[
            InterviewQuestion(
                question="Walk me through a production Python API you built.",
                category="technical",
                targets_skill="Python",
                what_to_look_for="Concrete design decisions, error handling, testing.",
            )
        ],
    )
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=preset)
    llm_instance = MagicMock()
    llm_instance.with_structured_output.return_value = structured
    monkeypatch.setattr(ig, "ChatOpenAI", MagicMock(return_value=llm_instance))
    return {"structured": structured, "preset": preset}


def _human_message(mock_llm) -> str:
    return mock_llm["structured"].ainvoke.call_args.args[0][1][1]


@pytest.mark.asyncio
async def test_returns_validated_kit_with_real_title(mock_llm):
    result = await ig.generate_interview_questions(_gap())
    assert isinstance(result, InterviewKit)
    assert result.job_title == "AI Engineer"  # authoritative, not model-echoed
    assert result.questions[0].category == "technical"


@pytest.mark.asyncio
async def test_prompt_includes_matched_and_missing(mock_llm):
    await ig.generate_interview_questions(_gap())
    human = _human_message(mock_llm)
    assert "Python" in human        # matched (probe for depth)
    assert "RAG systems" in human   # missing (gap-probing)
    assert "Docker" in human        # partial


@pytest.mark.asyncio
async def test_handles_no_missing_skills(mock_llm):
    gap = GapAnalysis(
        job_title="X",
        assessments=[SkillAssessment(skill="Python", status="matched", evidence="yes")],
        fit_score=90,
        summary="Great fit.",
    )
    await ig.generate_interview_questions(gap)
    assert "(none)" in _human_message(mock_llm)  # empty missing-skills placeholder