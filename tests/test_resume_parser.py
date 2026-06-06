import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock

from app.models.documents import DocumentMetadata, DocumentChunk, ParsedResume
from app.services.resume_parser import parse_resume, _extract_text_from_pdf, _chunk_text


@pytest.mark.asyncio
async def test_parse_resume_basic():
    """Test basic resume parsing with mocked PDF extraction."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Mock the UnstructuredPDFLoader
        mock_doc = MagicMock()
        mock_doc.page_content = "John Doe\n\nExperience: 5 years in Python\n\nSkills: Python, FastAPI"
        mock_doc.metadata = {"page": 0}

        with patch("app.services.resume_parser.UnstructuredPDFLoader") as mock_loader:
            mock_loader.return_value.load.return_value = [mock_doc]

            result = await parse_resume(tmp_path)

            assert isinstance(result, ParsedResume)
            assert result.filename == tmp_path.name
            assert len(result.chunks) > 0
            assert result.total_tokens > 0
            assert result.parse_duration_ms >= 0

    finally:
        tmp_path.unlink()


@pytest.mark.asyncio
async def test_parse_resume_file_not_found():
    """Test error handling for missing file."""
    with pytest.raises(FileNotFoundError):
        await parse_resume(Path("/nonexistent/file.pdf"))


@pytest.mark.asyncio
async def test_parse_resume_not_pdf():
    """Test error handling for non-PDF files."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with pytest.raises(ValueError, match="Expected PDF file"):
            await parse_resume(tmp_path)
    finally:
        tmp_path.unlink()


@pytest.mark.asyncio
async def test_extract_text_from_pdf():
    """Test PDF text extraction."""
    mock_doc = MagicMock()
    mock_doc.page_content = "Sample resume text"
    mock_doc.metadata = {"page": 0}

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with patch("app.services.resume_parser.UnstructuredPDFLoader") as mock_loader:
            mock_loader.return_value.load.return_value = [mock_doc]

            text, page_count = await _extract_text_from_pdf(tmp_path)

            assert isinstance(text, str)
            assert len(text) > 0
            assert page_count >= 1

    finally:
        tmp_path.unlink()


@pytest.mark.asyncio
async def test_extract_text_from_pdf_empty():
    """Test error handling for empty PDF."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with patch("app.services.resume_parser.UnstructuredPDFLoader") as mock_loader:
            mock_loader.return_value.load.return_value = []

            with pytest.raises(ValueError, match="PDF extraction returned no documents"):
                await _extract_text_from_pdf(tmp_path)

    finally:
        tmp_path.unlink()


@pytest.mark.asyncio
async def test_chunk_text_basic():
    """Test text chunking."""
    text = "Section 1: Education\n\nI studied at University.\n\n" * 20
    metadata = DocumentMetadata(
        source_file="test.pdf",
        parsed_at=datetime.utcnow(),
        page_count=1,
        total_size_bytes=1000
    )

    chunks = await _chunk_text(text, metadata)

    assert len(chunks) > 0
    assert all(isinstance(c, DocumentChunk) for c in chunks)
    assert all(c.content for c in chunks)
    assert all(c.chunk_index == i for i, c in enumerate(chunks))
    assert all(c.metadata == metadata for c in chunks)


@pytest.mark.asyncio
async def test_chunk_text_preserves_content():
    """Test that chunking preserves all content."""
    text = "Important content " * 100
    metadata = DocumentMetadata(
        source_file="test.pdf",
        parsed_at=datetime.utcnow(),
        page_count=1,
        total_size_bytes=len(text.encode())
    )

    chunks = await _chunk_text(text, metadata)
    reconstructed = " ".join(c.content for c in chunks)

    # Content should be mostly preserved (may differ due to chunking boundaries)
    assert len(reconstructed) >= len(text) * 0.9


@pytest.mark.asyncio
async def test_document_chunk_structure():
    """Test DocumentChunk pydantic model."""
    metadata = DocumentMetadata(
        source_file="test.pdf",
        parsed_at=datetime.utcnow(),
        page_count=1,
        total_size_bytes=500
    )

    chunk = DocumentChunk(
        content="Test content",
        chunk_index=0,
        page_number=1,
        metadata=metadata
    )

    assert chunk.content == "Test content"
    assert chunk.chunk_index == 0
    assert chunk.page_number == 1
    assert chunk.metadata.source_file == "test.pdf"


@pytest.mark.asyncio
async def test_parsed_resume_structure():
    """Test ParsedResume pydantic model."""
    metadata = DocumentMetadata(
        source_file="test.pdf",
        parsed_at=datetime.utcnow(),
        page_count=1,
        total_size_bytes=500
    )

    chunk = DocumentChunk(
        content="Test",
        chunk_index=0,
        metadata=metadata
    )

    resume = ParsedResume(
        filename="test.pdf",
        chunks=[chunk],
        total_tokens=100,
        parse_duration_ms=50.5
    )

    assert resume.filename == "test.pdf"
    assert len(resume.chunks) == 1
    assert resume.total_tokens == 100
    assert resume.parse_duration_ms == 50.5
