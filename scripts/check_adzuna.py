#!/usr/bin/env python3
"""
Verify Adzuna API credentials.

Reads ADZUNA_APP_ID / ADZUNA_API_KEY / ADZUNA_COUNTRY from settings (.env)
and makes one real search call. Confirms the keys authenticate before we
build the Phase C adzuna_client on top of them.

Usage:
    python -m scripts.check_adzuna
    python -m scripts.check_adzuna --what "machine learning engineer" --where Melbourne
"""
import argparse
import logging
import sys

import httpx

from app.core.config import get_settings
from app.core.logging import configure_logging

ADZUNA_BASE = "https://api.adzuna.com/v1/api"


def check(what: str, where: str) -> int:
    log = logging.getLogger(__name__)
    settings = get_settings()

    if not settings.adzuna_app_id or not settings.adzuna_api_key:
        log.error(
            "Adzuna credentials missing. Set ADZUNA_APP_ID and ADZUNA_API_KEY "
            "in .env, then recreate the app container "
            "(docker compose ... up -d --force-recreate app)."
        )
        return 2

    country = settings.adzuna_country or "au"
    url = f"{ADZUNA_BASE}/jobs/{country}/search/1"
    params = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_api_key,
        "results_per_page": 3,
        "what": what,
        "where": where,
        "content-type": "application/json",
    }

    log.info("Calling Adzuna", extra={"country": country, "what": what, "where": where})

    try:
        resp = httpx.get(url, params=params, timeout=20.0)
    except httpx.HTTPError as e:
        log.error("Request failed (network/timeout)", extra={"error": str(e)})
        return 1

    if resp.status_code == 401:
        log.error("401 Unauthorized — app_id / app_key are wrong or not yet active.")
        return 1
    if resp.status_code != 200:
        log.error("Unexpected status", extra={"status": resp.status_code, "body": resp.text[:300]})
        return 1

    data = resp.json()
    total = data.get("count", 0)
    results = data.get("results", [])

    print("\n" + "=" * 60)
    print("Adzuna credentials OK ✅")
    print(f"  country:        {country}")
    print(f"  query:          what='{what}' where='{where}'")
    print(f"  total matches:  {total}")
    print("  sample results:")
    for r in results:
        title = r.get("title", "?")
        company = (r.get("company") or {}).get("display_name", "?")
        loc = (r.get("location") or {}).get("display_name", "?")
        print(f"    - {title} @ {company} ({loc})")
    print("=" * 60)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Adzuna API credentials.")
    parser.add_argument("--what", default="AI engineer", help="Job search keywords")
    parser.add_argument("--where", default="Australia", help="Location")
    args = parser.parse_args()

    configure_logging()
    sys.exit(check(args.what, args.where))


if __name__ == "__main__":
    main()
