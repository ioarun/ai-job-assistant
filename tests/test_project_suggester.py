"""Tests for the project suggester (Phase C, tool #3).

The LLM is mocked, so these run offline and deterministically. They assert the
wiring and that the prompt is built correctly from the GapAnalysis (missing
skills prioritized, matched skills passed as do-not-target).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.project_suggester as ps
from app.models.analysis import (
    GapAnalysis,
    ProjectSuggestion,
    ProjectSuggestions,
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
    monkeypatch.setattr(ps, "get_langchain_callback", lambda: None)  # Langfuse off

    preset = ProjectSuggestions(
        job_title="(model-echoed title)",
        suggestions=[
            ProjectSuggestion(
                title="RAG over your notes",
                description="Build a retrieval-augmented chatbot over a personal corpus.",
                skills_covered=["RAG systems"],
                difficulty="intermediate",
                key_deliverables=["deployed API", "demo video"],
            )
        ],
    )
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=preset)
    llm_instance = MagicMock()
    llm_instance.with_structured_output.return_value = structured
    monkeypatch.setattr(ps, "ChatOpenAI", MagicMock(return_value=llm_instance))
    return {"structured": structured, "preset": preset}


def _human_message(mock_llm) -> str:
    return mock_llm["structured"].ainvoke.call_args.args[0][1][1]


@pytest.mark.asyncio
async def test_returns_validated_suggestions_with_real_title(mock_llm):
    result = await ps.suggest_projects(_gap())
    assert isinstance(result, ProjectSuggestions)
    assert result.job_title == "AI Engineer"  # authoritative, not model-echoed
    assert result.suggestions[0].skills_covered == ["RAG systems"]


@pytest.mark.asyncio
async def test_prompt_prioritizes_missing_and_includes_matched(mock_llm):
    await ps.suggest_projects(_gap())
    human = _human_message(mock_llm)
    assert "RAG systems" in human   # missing skill present
    assert "Python" in human        # matched skill present (as do-not-target)
    assert "PRIORITIZE" in human    # missing skills are flagged as the priority


@pytest.mark.asyncio
async def test_handles_no_missing_skills(mock_llm):
    gap = GapAnalysis(
        job_title="X",
        assessments=[SkillAssessment(skill="Python", status="matched", evidence="yes")],
        fit_score=90,
        summary="Great fit.",
    )
    await ps.suggest_projects(gap)
    assert "(none)" in _human_message(mock_llm)  # empty missing-skills placeholder