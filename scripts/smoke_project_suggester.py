#!/usr/bin/env python3
"""Live smoke test of the project suggester (Phase C, tool #3).

Chains the real pipeline: analyze a job's gaps (tool #2), then suggest portfolio
projects to close them (tool #3). Real OpenAI calls, so opt-in. Requires an
indexed resume.

Usage:
    python -m scripts.smoke_project_suggester
"""
import asyncio
import logging
import sys

from app.core.logging import configure_logging
from app.observability.langfuse_client import shutdown_langfuse
from app.services.gap_analyzer import analyze_gap
from app.services.project_suggester import suggest_projects

JOB_TITLE = "AI Engineer"
JOB_DESC = (
    "We need an AI engineer with strong Python, experience building RAG systems "
    "and LLM-powered features, vector databases, Docker, and AWS deployment. "
    "Familiarity with LangChain and prompt engineering is required."
)


async def main() -> int:
    configure_logging()
    log = logging.getLogger(__name__)

    log.info("Step 1: gap analysis")
    gap = await analyze_gap(JOB_TITLE, JOB_DESC)
    print("\n" + "=" * 60)
    print(f"GAP → fit={gap.fit_score}; missing: {gap.missing_skills}")

    log.info("Step 2: project suggestions")
    result = await suggest_projects(gap)
    print("=" * 60)
    print(f"PROJECT SUGGESTIONS for {result.job_title} ({len(result.suggestions)}):\n")
    for i, p in enumerate(result.suggestions, 1):
        print(f"{i}. {p.title}  [{p.difficulty}]")
        print(f"   {p.description}")
        print(f"   covers: {', '.join(p.skills_covered)}")
        print(f"   deliverables: {', '.join(p.key_deliverables)}\n")
    print("=" * 60)

    # Sanity: suggestions should target the gaps, not the matched skills.
    covered = {s.lower() for p in result.suggestions for s in p.skills_covered}
    missing = {s.lower() for s in gap.missing_skills}
    overlap = covered & missing
    print(f"Suggestions touch {len(overlap)}/{len(missing)} of the missing skills: {sorted(overlap)}")

    shutdown_langfuse()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))