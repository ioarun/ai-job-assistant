import logging
import time
from pathlib import Path
from datetime import datetime

from langchain_community.document_loaders import UnstructuredPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.models.documents import DocumentMetadata, DocumentChunk, ParsedResume

log = logging.getLogger(__name__)


async def parse_resume(file_path: Path) -> ParsedResume:
    """
    Parse a resume PDF, extract text, and chunk it.

    Args:
        file_path: Path to the PDF file

    Returns:
        ParsedResume with chunks and metadata

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is not a valid PDF
    """
    start_time = time.time()
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Resume file not found: {file_path}")

    if file_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected PDF file, got: {file_path.suffix}")

    log.info("Starting resume parse", extra={
        "file": file_path.name,
        "size_bytes": file_path.stat().st_size
    })

    # Extract text from PDF
    text, page_count = await _extract_text_from_pdf(file_path)

    # Create metadata
    metadata = DocumentMetadata(
        source_file=file_path.name,
        parsed_at=datetime.utcnow(),
        page_count=page_count,
        total_size_bytes=file_path.stat().st_size
    )

    # Chunk the text
    chunks = await _chunk_text(text, metadata)

    # Estimate tokens (rough: 1 token per 4 chars)
    total_tokens = len(text) // 4

    duration_ms = (time.time() - start_time) * 1000

    result = ParsedResume(
        filename=file_path.name,
        chunks=chunks,
        total_tokens=total_tokens,
        parse_duration_ms=duration_ms
    )

    log.info("Resume parse complete", extra={
        "file": file_path.name,
        "chunks": len(chunks),
        "tokens": total_tokens,
        "duration_ms": int(duration_ms)
    })

    return result


async def _extract_text_from_pdf(file_path: Path) -> tuple[str, int]:
    """
    Extract text from PDF using UnstructuredPDFLoader.

    Returns:
        Tuple of (extracted_text, page_count)
    """
    try:
        loader = UnstructuredPDFLoader(str(file_path))
        docs = loader.load()

        if not docs:
            raise ValueError("PDF extraction returned no documents")

        text = "\n\n".join([doc.page_content for doc in docs])

        # Try to extract page count from metadata
        page_count = 1
        if docs and hasattr(docs[0], "metadata") and "page" in docs[0].metadata:
            page_count = len(set(d.metadata.get("page", 0) for d in docs))

        log.debug("PDF extraction complete", extra={
            "pages": page_count,
            "text_length": len(text)
        })

        return text, page_count

    except Exception as e:
        log.error("PDF extraction failed", extra={"error": str(e)})
        raise ValueError(f"Failed to extract text from PDF: {e}") from e


async def _chunk_text(text: str, metadata: DocumentMetadata) -> list[DocumentChunk]:
    """
    Split text into chunks using RecursiveCharacterTextSplitter.

    Args:
        text: Extracted text content
        metadata: Document metadata to attach to each chunk

    Returns:
        List of DocumentChunk objects
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ". ", " ", ""]
    )

    text_chunks = splitter.split_text(text)

    chunks = [
        DocumentChunk(
            content=chunk,
            chunk_index=i,
            page_number=None,  # TODO: track from metadata if available
            metadata=metadata
        )
        for i, chunk in enumerate(text_chunks)
    ]

    log.debug("Text chunking complete", extra={
        "chunk_count": len(chunks),
        "avg_chunk_size": sum(len(c.content) for c in chunks) // len(chunks) if chunks else 0
    })

    return chunks
