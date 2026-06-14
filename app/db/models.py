from datetime import datetime
from sqlalchemy import Column, Integer, Float, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Resume(Base):
    """SQLAlchemy model for storing resume metadata."""
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable=False)
    file_hash = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    file_size_bytes = Column(Integer)
    page_count = Column(Integer)
    total_chunks = Column(Integer)
    chroma_collection_id = Column(String, nullable=True)


class Job(Base):
    """A single job posting normalized from an Adzuna search result.

    Deduped on `adzuna_id`: the same job returned by multiple queries is
    stored once. `raw_json` keeps the original payload so we can extract
    more fields later without re-fetching.
    """
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    adzuna_id = Column(String, unique=True, nullable=False, index=True)
    title = Column(String)
    company = Column(String)
    location = Column(String)
    description = Column(Text)
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    category = Column(String, nullable=True)
    contract_type = Column(String, nullable=True)
    created = Column(String, nullable=True)        # Adzuna's posting timestamp (ISO string)
    redirect_url = Column(String, nullable=True)
    raw_json = Column(Text)                          # original Adzuna result, json.dumps'd
    first_seen_at = Column(DateTime, default=datetime.utcnow)


class JobSearchCache(Base):
    """Query-keyed cache of an Adzuna search.

    `query_hash` is a sha256 of the normalized search params; a row records
    when the query was last fetched and which `Job.adzuna_id`s it returned
    (ordered). `search_jobs` serves from here when `fetched_at` is within
    its freshness window, so repeat queries never hit the live API.
    """
    __tablename__ = "job_search_cache"

    id = Column(Integer, primary_key=True)
    query_hash = Column(String, unique=True, nullable=False, index=True)
    params_json = Column(Text)                       # normalized params, json.dumps'd
    total_count = Column(Integer)                     # Adzuna's reported total match count
    result_adzuna_ids = Column(Text)                 # ordered list of adzuna_ids, json.dumps'd
    fetched_at = Column(DateTime, default=datetime.utcnow)
