"""Tests for the cached Adzuna client.

All HTTP is mocked via a saved sample payload (`fixtures/adzuna_sample.json`)
so the suite never touches the live API or burns quota. Each test runs against
a throwaway temp-file SQLite DB, and Langfuse is disabled, so nothing leaks
between tests or out to the network. These lock in the three behaviours the
first live smoke run exposed bugs in: cache hit/miss, dedupe, and staleness.
"""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.adzuna_client as ac
from app.db.models import Base, Job, JobSearchCache

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "adzuna_sample.json").read_text())


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the client at an isolated temp DB and disable Langfuse.

    Returns a session factory so tests can inspect the DB after a call.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @contextmanager
    def _session():
        s = TestSession()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(ac, "get_sync_session", _session)
    monkeypatch.setattr(ac, "init_db", lambda: None)
    monkeypatch.setattr(ac, "_DB_READY", True)
    monkeypatch.setattr(ac, "get_langfuse", lambda: None)  # span becomes a no-op
    return _session


# ── Pure functions (no DB) ───────────────────────────────────────────────
def test_normalize_result_maps_nested_fields():
    fields = ac._normalize_result(FIXTURE["results"][0])
    assert fields["adzuna_id"] == "4900000001"
    assert fields["title"] == "AI Engineer"
    assert fields["company"] == "Acme AI"          # from nested company.display_name
    assert fields["location"] == "Sydney NSW"      # from nested location.display_name
    assert fields["category"] == "IT Jobs"         # from nested category.label
    assert fields["salary_min"] == 130000.0
    assert json.loads(fields["raw_json"])["id"] == "4900000001"  # original payload kept


def test_query_hash_is_case_normalized_and_param_sensitive():
    base = ac._normalize_params("AI engineer", "Australia", 1, 20)
    same = ac._normalize_params("  ai ENGINEER ", "australia", 1, 20)  # case/space-insensitive
    diff = ac._normalize_params("ML engineer", "Australia", 1, 20)
    assert ac._query_hash(base) == ac._query_hash(same)
    assert ac._query_hash(base) != ac._query_hash(diff)


# ── Cache behaviour ──────────────────────────────────────────────────────
def test_cache_miss_then_hit(temp_db):
    calls = []

    def fake_fetch(params):
        calls.append(params)
        return FIXTURE

    with patch.object(ac, "_fetch_live", fake_fetch):
        jobs1 = ac.search_jobs("AI engineer", "Australia")
        assert len(jobs1) == 2
        assert len(calls) == 1  # first call fetched live

        jobs2 = ac.search_jobs("AI engineer", "Australia")
        assert len(calls) == 1  # identical call served from cache — no live fetch
        assert [j.adzuna_id for j in jobs2] == [j.adzuna_id for j in jobs1]


def test_dedupe_jobs_across_queries(temp_db):
    session = temp_db
    with patch.object(ac, "_fetch_live", lambda params: FIXTURE):
        ac.search_jobs("AI engineer", "Australia")
        ac.search_jobs("ML engineer", "Melbourne")  # different query, same jobs in fixture

    with session() as s:
        assert s.query(Job).count() == 2             # deduped on adzuna_id
        assert s.query(JobSearchCache).count() == 2  # two distinct queries cached


def test_stale_cache_triggers_refetch(temp_db):
    session = temp_db
    calls = []

    def fake_fetch(params):
        calls.append(params)
        return FIXTURE

    with patch.object(ac, "_fetch_live", fake_fetch):
        ac.search_jobs("AI engineer", "Australia", max_age_hours=24)
        assert len(calls) == 1

        # backdate the cached query past the freshness window
        with session() as s:
            row = s.query(JobSearchCache).one()
            row.fetched_at = datetime.utcnow() - timedelta(hours=48)

        ac.search_jobs("AI engineer", "Australia", max_age_hours=24)
        assert len(calls) == 2  # stale → refetched live