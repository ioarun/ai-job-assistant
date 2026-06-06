from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, create_engine
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
