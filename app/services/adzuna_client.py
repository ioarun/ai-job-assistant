"""Adzuna job-search client with a SQLite cache.

Adzuna's free developer tier has a low quota, so every search is cached: a
`JobSearchCache` row keyed by a hash of the search params records which jobs a
query returned and when. Repeat queries within the freshness window are served
from the `jobs` table without touching the live API. This is the v1 job source
the Phase D agent calls as a tool, so `search_jobs` is wrapped in a Langfuse
span and shows up as `tool.adzuna.search` in traces.
"""
import hashlib
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterator

import httpx

from app.core.config import get_settings
from app.db.models import Job, JobSearchCache
from app.db.session import get_sync_session, init_db
from app.observability.langfuse_client import get_langfuse

log = logging.getLogger(__name__)

ADZUNA_BASE = "https://api.adzuna.com/v1/api"
_DB_READY = False


# ── Langfuse span helper ───────────────────────────────────────────────
@contextmanager
def _span(name: str, **inputs) -> Iterator[object]:
    """Yield a Langfuse span (or None when Langfuse is disabled).

    Lets `search_jobs` trace itself as a tool call without branching the body.
    """
    lf = get_langfuse()
    if lf is None:
        yield None
        return
    # Langfuse v4: observations are created via start_as_current_observation;
    # as_type="tool" tags this as a tool call in the trace tree.
    with lf.start_as_current_observation(name=name, as_type="tool", input=inputs) as span:
        yield span


# ── Internals ──────────────────────────────────────────────────────────
def _normalize_params(what: str, where: str, page: int, results_per_page: int) -> dict:
    """The result-affecting params, normalized for hashing and storage."""
    settings = get_settings()
    return {
        "country": (settings.adzuna_country or "au").lower(),
        "what": what.strip().lower(),
        "where": where.strip().lower(),
        "page": page,
        "results_per_page": results_per_page,
    }


def _query_hash(params: dict) -> str:
    """Stable sha256 of the normalized params."""
    blob = json.dumps(params, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _fetch_live(params: dict) -> dict:
    """One live Adzuna search call. Raises on missing creds or non-200."""
    settings = get_settings()
    if not settings.adzuna_app_id or not settings.adzuna_api_key:
        raise RuntimeError(
            "Adzuna credentials missing — set ADZUNA_APP_ID / ADZUNA_API_KEY in .env "
            "and recreate the app container."
        )

    url = f"{ADZUNA_BASE}/jobs/{params['country']}/search/{params['page']}"
    query = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_api_key,
        "results_per_page": params["results_per_page"],
        "what": params["what"],
        "where": params["where"],
        "content-type": "application/json",
    }

    log.info("Calling Adzuna (live)", extra={k: params[k] for k in ("country", "what", "where", "page")})
    resp = httpx.get(url, params=query, timeout=20.0)
    if resp.status_code != 200:
        raise RuntimeError(f"Adzuna returned {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _normalize_result(r: dict) -> dict:
    """Map one raw Adzuna result to `Job` column values."""
    return {
        "adzuna_id": str(r.get("id")),
        "title": r.get("title"),
        "company": (r.get("company") or {}).get("display_name"),
        "location": (r.get("location") or {}).get("display_name"),
        "description": r.get("description"),
        "salary_min": r.get("salary_min"),
        "salary_max": r.get("salary_max"),
        "category": (r.get("category") or {}).get("label"),
        "contract_type": r.get("contract_type"),
        "created": r.get("created"),
        "redirect_url": r.get("redirect_url"),
        "raw_json": json.dumps(r),
    }


def _upsert_job(session, fields: dict) -> Job:
    """Insert a job, or refresh the existing row with the same adzuna_id."""
    job = session.query(Job).filter_by(adzuna_id=fields["adzuna_id"]).one_or_none()
    if job is None:
        job = Job(**fields)
        session.add(job)
    else:
        for key, value in fields.items():
            if key != "adzuna_id":
                setattr(job, key, value)
    session.flush()  # assign PK / make the row queryable within this session
    return job


# ── Public API ─────────────────────────────────────────────────────────
def is_search_cached(
    what: str,
    where: str = "Australia",
    page: int = 1,
    results_per_page: int = 20,
    max_age_hours: int = 24,
) -> bool:
    """Return True if this exact search is in the cache and still fresh.

    Lets the Phase D agent decide whether `search_jobs` would hit the live Adzuna
    API (a quota-burning cache MISS) and pause for human approval first — without
    actually fetching. Same normalization/hashing as `search_jobs`, so the verdict
    matches what `search_jobs` will subsequently do.
    """
    global _DB_READY
    if not _DB_READY:
        init_db()
        _DB_READY = True

    params = _normalize_params(what, where, page, results_per_page)
    qhash = _query_hash(params)
    fresh_after = datetime.utcnow() - timedelta(hours=max_age_hours)

    with get_sync_session() as session:
        cached = session.query(JobSearchCache).filter_by(query_hash=qhash).one_or_none()
        return cached is not None and cached.fetched_at >= fresh_after


def search_jobs(
    what: str,
    where: str = "Australia",
    page: int = 1,
    results_per_page: int = 20,
    max_age_hours: int = 24,
) -> list[Job]:
    """Search Adzuna for jobs, serving from the SQLite cache when fresh.

    Args:
        what: Search keywords, e.g. "AI engineer".
        where: Location, e.g. "Australia" or "Melbourne".
        page: Adzuna result page (1-based).
        results_per_page: Results to request per page.
        max_age_hours: Serve from cache if the query was fetched within this
            window; otherwise re-fetch live.

    Returns:
        A list of `Job` rows (detached from the session) in result order.
    """
    global _DB_READY
    if not _DB_READY:
        init_db()
        _DB_READY = True

    params = _normalize_params(what, where, page, results_per_page)
    qhash = _query_hash(params)

    with _span("tool.adzuna.search", **params, max_age_hours=max_age_hours) as span:
        with get_sync_session() as session:
            cached = session.query(JobSearchCache).filter_by(query_hash=qhash).one_or_none()
            fresh_after = datetime.utcnow() - timedelta(hours=max_age_hours)

            cache_hit = cached is not None and cached.fetched_at >= fresh_after
            if cache_hit:
                ids = json.loads(cached.result_adzuna_ids)
                by_id = {j.adzuna_id: j for j in session.query(Job).filter(Job.adzuna_id.in_(ids)).all()}
                jobs = [by_id[i] for i in ids if i in by_id]
                log.info("Adzuna cache hit", extra={"query_hash": qhash[:12], "jobs": len(jobs)})
            else:
                data = _fetch_live(params)
                results = data.get("results", [])
                jobs = [_upsert_job(session, _normalize_result(r)) for r in results]
                result_ids = [j.adzuna_id for j in jobs]

                if cached is None:
                    cached = JobSearchCache(query_hash=qhash)
                    session.add(cached)
                cached.params_json = json.dumps(params)
                cached.total_count = data.get("count", len(jobs))
                cached.result_adzuna_ids = json.dumps(result_ids)
                cached.fetched_at = datetime.utcnow()
                log.info("Adzuna live fetch", extra={"query_hash": qhash[:12], "jobs": len(jobs)})

            session.flush()        # INSERT the pending cache row before we detach it
            session.expunge_all()  # detach so callers can read attrs after the session closes

        if span is not None:
            span.update(output={"count": len(jobs), "cache_hit": cache_hit})

    return jobs
