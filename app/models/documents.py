from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class DocumentMetadata(BaseModel):
    """Metadata about the source document."""
    source_file: str
    parsed_at: datetime
    page_count: int
    total_size_bytes: int


class DocumentChunk(BaseModel):
    """A unit of parsed document text with metadata."""
    content: str
    chunk_index: int
    page_number: Optional[int] = None
    metadata: DocumentMetadata


class ParsedResume(BaseModel):
    """Result of parsing a resume."""
    filename: str
    chunks: list[DocumentChunk]
    total_tokens: int
    parse_duration_ms: float
