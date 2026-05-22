from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ResumeUpload(BaseModel):
    """Request model for resume upload."""
    file_name: str


class JobSearch(BaseModel):
    """Request model for job search."""
    query: str
    location: Optional[str] = None
    page: int = 1


class Job(BaseModel):
    """Response model for job."""
    id: int
    title: str
    company: str
    location: str
    description: str
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    url: Optional[str] = None


class SkillGapRequest(BaseModel):
    """Request model for skill gap analysis."""
    resume_id: int
    job_id: int


class SkillGapResponse(BaseModel):
    """Response model for skill gap analysis."""
    gap_analysis: str
    timestamp: datetime


class CoverLetterRequest(BaseModel):
    """Request model for cover letter generation."""
    resume_id: int
    job_id: int


class InterviewQuestionsRequest(BaseModel):
    """Request model for interview questions."""
    resume_id: int
    job_id: int


class HealthCheck(BaseModel):
    """Health check response."""
    status: str
    version: str = "0.1.0"
