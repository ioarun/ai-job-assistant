#!/usr/bin/env python3
"""End-to-end demo of the AI Job Assistant pipeline (Phase C).

Runs the full product flow with the four Phase C tools, chained by hand (the
LangGraph agent that automates this is Phase D):

    1. search Adzuna for jobs (cached to SQLite)
    2. pick one job
    3. analyze the resume-vs-job skill gap
    4. suggest portfolio projects to close the gaps
    5. generate tailored interview questions

Requires the stack up and a resume indexed (see scripts/index_resume.py).
Steps 3-5 make real OpenAI calls.

Usage:
    python -m scripts.run_pipeline
    python -m scripts.run_pipeline --what "machine learning engineer" --where Melbourne
    python -m scripts.run_pipeline --pick 2 --results 8
"""
import argparse
import asyncio
import logging
import sys

from app.core.logging import configure_logging
from app.observability.langfuse_client import shutdown_langfuse
from app.services.adzuna_client import search_jobs
from app.services.gap_analyzer import analyze_gap
from app.services.interview_generator import generate_interview_questions
from app.services.project_suggester import suggest_projects

RULE = "=" * 70


def _section(title: str) -> None:
    print("\n" + RULE)
    print(title)
    print(RULE)


async def run(what: str, where: str, pick: int, results: int) -> int:
    log = logging.getLogger(__name__)

    # 1. Search Adzuna (served from the SQLite cache on repeat queries).
    _section(f"STEP 1 — Searching Adzuna: what='{what}' where='{where}'")
    jobs = search_jobs(what, where, results_per_page=results)
    if not jobs:
        log.error("No jobs returned — check Adzuna credentials / query.")
        return 1
    for i, j in enumerate(jobs):
        marker = "  <-- selected" if i == pick else ""
        print(f"  [{i}] {j.title} @ {j.company} ({j.location}){marker}")

    if not 0 <= pick < len(jobs):
        log.error("--pick %d is out of range (0..%d)", pick, len(jobs) - 1)
        return 1
    job = jobs[pick]

    # 2. Show the selected job.
    _section(f"STEP 2 — Selected job: {job.title} @ {job.company}")
    desc = job.description or ""
    print(desc[:500] + ("..." if len(desc) > 500 else ""))
    if job.redirect_url:
        print(f"\n  link: {job.redirect_url}")

    # 3. Gap analysis (tool #2) — resume vs this job.
    gap = await analyze_gap(job.title, desc)
    _section(f"STEP 3 — Gap analysis: fit {gap.fit_score}/100")
    print(f"  matched: {gap.matched_skills}")
    print(f"  partial: {gap.partial_skills}")
    print(f"  missing: {gap.missing_skills}")
    print(f"\n  {gap.summary}")

    # 4. Project suggestions (tool #3) — chained off the GapAnalysis.
    projs = await suggest_projects(gap)
    _section(f"STEP 4 — Project suggestions ({len(projs.suggestions)})")
    for i, p in enumerate(projs.suggestions, 1):
        print(f"\n  {i}. {p.title}  [{p.difficulty}]")
        print(f"     {p.description}")
        print(f"     covers: {', '.join(p.skills_covered)}")
        print(f"     deliverables: {', '.join(p.key_deliverables)}")

    # 5. Interview questions (tool #4) — also chained off the GapAnalysis.
    kit = await generate_interview_questions(gap)
    _section(f"STEP 5 — Interview questions ({len(kit.questions)})")
    for i, q in enumerate(kit.questions, 1):
        print(f"\n  {i}. [{q.category}] (targets: {q.targets_skill})")
        print(f"     Q: {q.question}")
        print(f"     look for: {q.what_to_look_for}")

    _section("Done. Open http://localhost:3000 (Langfuse) to see the traced tool calls.")
    shutdown_langfuse()  # flush traces before exit
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full AI Job Assistant pipeline end to end."
    )
    parser.add_argument("--what", default="AI engineer", help="Job search keywords")
    parser.add_argument("--where", default="Australia", help="Location")
    parser.add_argument("--pick", type=int, default=0, help="Index of the job to analyze (0-based)")
    parser.add_argument("--results", type=int, default=5, help="Number of jobs to fetch")
    args = parser.parse_args()

    configure_logging()
    sys.exit(asyncio.run(run(args.what, args.where, args.pick, args.results)))


if __name__ == "__main__":
    main()