#!/usr/bin/env python3
"""Live end-to-end smoke test of the cached Adzuna client.

Unlike the unit tests (which mock HTTP), this makes ONE real Adzuna call to
prove the client works against your actual credentials, then repeats the same
query to show it is served from the SQLite cache (no second API call). Opt-in
so it doesn't run in CI and burn quota.

Usage:
    python -m scripts.smoke_adzuna_search
    python -m scripts.smoke_adzuna_search --what "machine learning engineer" --where Melbourne
"""
import argparse
import logging
import sys

from app.core.logging import configure_logging
from app.services.adzuna_client import search_jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="Live smoke test of the cached Adzuna client.")
    parser.add_argument("--what", default="AI engineer", help="Job search keywords")
    parser.add_argument("--where", default="Australia", help="Location")
    parser.add_argument("--results", type=int, default=5, help="Results per page")
    args = parser.parse_args()

    configure_logging()
    log = logging.getLogger(__name__)

    log.info("Call 1 — expect a live fetch")
    jobs = search_jobs(args.what, args.where, results_per_page=args.results)

    if not jobs:
        log.error("No jobs returned — check credentials / query.")
        return 1

    print("\n" + "=" * 60)
    print(f"Adzuna client OK ✅  ({len(jobs)} jobs for what='{args.what}' where='{args.where}')")
    for j in jobs:
        print(f"  [{j.adzuna_id}] {j.title} @ {j.company} ({j.location})")
    print("=" * 60)

    log.info("Call 2 — identical query, expect a cache hit (no live fetch)")
    jobs2 = search_jobs(args.what, args.where, results_per_page=args.results)

    same = [j.adzuna_id for j in jobs2] == [j.adzuna_id for j in jobs]
    print(f"\nCache repeat returned the same {len(jobs2)} jobs: {same}")
    print("Check the logs above: call 2 should show 'Adzuna cache hit', not 'Calling Adzuna (live)'.")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())