#!/usr/bin/env python3
"""Live smoke test of the interview generator (Phase C, tool #4).

Chains the real pipeline: analyze a job's gaps (tool #2), then generate tailored
interview questions (tool #4). Real OpenAI calls, so opt-in. Requires an indexed
resume.

Usage:
    python -m scripts.smoke_interview_generator
"""
import asyncio
import logging
import sys
from collections import Counter

from app.core.logging import configure_logging
from app.observability.langfuse_client import shutdown_langfuse
from app.services.gap_analyzer import analyze_gap
from app.services.interview_generator import generate_interview_questions

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

    log.info("Step 2: interview questions")
    kit = await generate_interview_questions(gap)
    print("=" * 60)
    print(f"INTERVIEW KIT for {kit.job_title} ({len(kit.questions)} questions):\n")
    for i, q in enumerate(kit.questions, 1):
        print(f"{i}. [{q.category}] (targets: {q.targets_skill})")
        print(f"   Q: {q.question}")
        print(f"   look for: {q.what_to_look_for}\n")
    print("=" * 60)

    counts = Counter(q.category for q in kit.questions)
    print(f"Category mix: {dict(counts)}")

    shutdown_langfuse()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))