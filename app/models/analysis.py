"""Data contracts for the gap analyzer (Phase C, tool #2).

These models double as the LLM's structured-output schema: passing GapAnalysis
to `llm.with_structured_output(...)` forces the model to return data matching
this shape, which is validated by Pydantic before we trust it (guardrail #1).
The Field descriptions are sent to the model as part of the schema, so they're
written to guide generation, not just to document the code.
"""
from typing import Literal

from pydantic import BaseModel, Field


class SkillAssessment(BaseModel):
    """One skill the job requires, assessed against the resume."""

    skill: str = Field(description="A specific skill or requirement named in the job posting.")
    status: Literal["matched", "partial", "missing"] = Field(
        description=(
            "matched = clearly evidenced in the resume excerpts; "
            "partial = adjacent or related evidence; "
            "missing = no supporting evidence in the resume."
        )
    )
    evidence: str = Field(
        default="",
        description=(
            "Brief quote or paraphrase from the resume supporting a 'matched' or "
            "'partial' status. Empty string when status is 'missing'. "
            "Do not invent evidence that is not in the resume excerpts."
        ),
    )


class GapAnalysis(BaseModel):
    """Structured skill-gap analysis of a resume against one job posting."""

    job_title: str = Field(description="The job title being analyzed.")
    assessments: list[SkillAssessment] = Field(
        description="One assessment per key skill/requirement found in the job posting."
    )
    fit_score: int = Field(
        ge=0, le=100,
        description="Overall resume-to-job fit from 0 (no match) to 100 (excellent match).",
    )
    summary: str = Field(
        description="2-3 sentence plain-language summary of overall fit and the biggest gaps."
    )

    @property
    def matched_skills(self) -> list[str]:
        return [a.skill for a in self.assessments if a.status == "matched"]

    @property
    def partial_skills(self) -> list[str]:
        return [a.skill for a in self.assessments if a.status == "partial"]

    @property
    def missing_skills(self) -> list[str]:
        return [a.skill for a in self.assessments if a.status == "missing"]


class ProjectSuggestion(BaseModel):
    """A portfolio project idea that closes one or more skill gaps."""

    title: str = Field(description="Short, concrete project name.")
    description: str = Field(
        description="2-3 sentences: what the project is and what the candidate builds."
    )
    skills_covered: list[str] = Field(
        description="Which of the candidate's missing/partial skills this project demonstrably builds."
    )
    difficulty: Literal["beginner", "intermediate", "advanced"] = Field(
        description="Difficulty relative to the candidate's current background."
    )
    key_deliverables: list[str] = Field(
        description="2-4 concrete artifacts that would prove the skills (e.g. a deployed API, a benchmark, a demo)."
    )


class ProjectSuggestions(BaseModel):
    """A set of portfolio project suggestions targeting a job's skill gaps."""

    job_title: str = Field(description="The job these suggestions target.")
    suggestions: list[ProjectSuggestion] = Field(
        description="3-5 project ideas, prioritized by impact on closing the biggest gaps."
    )


class InterviewQuestion(BaseModel):
    """A single tailored interview question."""

    question: str = Field(description="The interview question, specific to this candidate and role.")
    category: Literal["technical", "behavioral", "gap-probing"] = Field(
        description=(
            "technical = skills/knowledge; behavioral = past experience/teamwork; "
            "gap-probing = targets a missing or partial skill."
        )
    )
    targets_skill: str = Field(description="The specific skill or area this question probes.")
    what_to_look_for: str = Field(
        description="What a strong answer demonstrates — interviewer guidance and candidate prep."
    )


class InterviewKit(BaseModel):
    """A set of tailored interview questions for a candidate and role."""

    job_title: str = Field(description="The job these questions target.")
    questions: list[InterviewQuestion] = Field(
        description="6-8 questions mixing technical, behavioral, and gap-probing categories."
    )