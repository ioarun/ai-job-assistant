import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app.models.documents import DocumentMetadata, DocumentChunk, ParsedResume
from app.services.vector_store import (
    _flatten_metadata,
    _transform_chunks_to_documents,
)


@pytest.fixture
def sample_chunks() -> list[DocumentChunk]:
    """Create sample document chunks for testing."""
    metadata = DocumentMetadata(
        source_file="test_resume.pdf",
        parsed_at=datetime.utcnow(),
        page_count=2,
        total_size_bytes=5000
    )

    return [
        DocumentChunk(
            content="Python and FastAPI experience",
            chunk_index=0,
            page_number=1,
            metadata=metadata
        ),
        DocumentChunk(
            content="Machine learning projects with TensorFlow",
            chunk_index=1,
            page_number=1,
            metadata=metadata
        ),
        DocumentChunk(
            content="Kubernetes and Docker deployment",
            chunk_index=2,
            page_number=2,
            metadata=metadata
        ),
    ]


def test_flatten_metadata(sample_chunks):
    """Test metadata flattening for Chroma storage."""
    chunk = sample_chunks[0]
    flattened = _flatten_metadata(chunk, "resume_001")

    assert flattened["source_file"] == "test_resume.pdf"
    assert flattened["chunk_index"] == 0
    assert flattened["page_number"] == 1
    assert flattened["resume_id"] == "resume_001"
    assert "parsed_at" in flattened
    assert isinstance(flattened["parsed_at"], str)  # Should be ISO format


def test_transform_chunks_to_documents(sample_chunks):
    """Test transformation of chunks to LangChain Documents."""
    documents, ids, metadatas = _transform_chunks_to_documents(sample_chunks, "resume_001")

    assert len(documents) == 3
    assert len(ids) == 3
    assert len(metadatas) == 3

    # Check IDs are composite
    assert ids[0] == "test_resume.pdf#0"
    assert ids[1] == "test_resume.pdf#1"
    assert ids[2] == "test_resume.pdf#2"

    # Check document content
    assert documents[0].page_content == "Python and FastAPI experience"
    assert documents[1].page_content == "Machine learning projects with TensorFlow"

    # Check metadata is flattened
    assert all(isinstance(m, dict) for m in metadatas)
    assert all("chunk_index" in m for m in metadatas)


@pytest.mark.asyncio
async def test_index_resume_chunks_empty():
    """Test that indexing with no chunks raises error."""
    from app.services.vector_store import index_resume_chunks

    # Create ParsedResume with no chunks
    parsed_resume = ParsedResume(
        filename="empty.pdf",
        chunks=[],
        total_tokens=0,
        parse_duration_ms=10.0
    )

    with pytest.raises(ValueError, match="no chunks"):
        await index_resume_chunks(parsed_resume, "resume_001")


@pytest.mark.asyncio
async def test_index_resume_chunks_mock(sample_chunks):
    """Test indexing with mocked Chroma client."""
    from app.services.vector_store import index_resume_chunks

    parsed_resume = ParsedResume(
        filename="test_resume.pdf",
        chunks=sample_chunks,
        total_tokens=500,
        parse_duration_ms=25.5
    )

    with patch("app.services.vector_store.get_chroma_client") as mock_chroma:
        mock_client = MagicMock()
        mock_chroma.return_value = mock_client

        collection_id = await index_resume_chunks(parsed_resume, "resume_001")

        assert collection_id == "resumes"  # default collection name
        mock_client.add_documents.assert_called_once()

        # Check that add_documents was called with correct data
        call_args = mock_client.add_documents.call_args
        assert call_args[1]["ids"][0] == "test_resume.pdf#0"
        assert len(call_args[1]["documents"]) == 3
        assert len(call_args[1]["metadatas"]) == 3
