import logging
from functools import lru_cache
from pathlib import Path
from datetime import datetime

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from app.core.config import get_settings
from app.models.documents import DocumentChunk, ParsedResume

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_chroma_client() -> Chroma:
    """
    Return a Chroma vector store client, cached as a singleton.

    Initializes with OpenAI embeddings and persistent storage.
    """
    settings = get_settings()

    log.info("Initializing Chroma client", extra={
        "collection": settings.chroma_collection_name,
        "path": str(settings.chroma_path)
    })

    embeddings = OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=settings.openai_api_key
    )

    client = Chroma(
        collection_name=settings.chroma_collection_name,
        embedding_function=embeddings,
        persist_directory=str(settings.chroma_path)
    )

    return client


def _flatten_metadata(chunk: DocumentChunk, resume_id: str) -> dict:
    """
    Flatten DocumentChunk metadata for Chroma storage.

    Chroma requires flat dict, so we unpack nested structures.
    """
    metadata = chunk.metadata.model_dump()
    metadata.update({
        "chunk_index": chunk.chunk_index,
        "page_number": chunk.page_number,
        "resume_id": resume_id,
        "parsed_at": metadata["parsed_at"].isoformat() if isinstance(metadata.get("parsed_at"), datetime) else metadata.get("parsed_at")
    })
    return metadata


def _transform_chunks_to_documents(
    chunks: list[DocumentChunk],
    resume_id: str
) -> tuple[list[Document], list[str], list[dict]]:
    """
    Transform ParsedResume chunks into LangChain Documents for Chroma.

    Returns:
        Tuple of (documents, ids, metadatas)
    """
    documents = []
    ids = []
    metadatas = []

    for chunk in chunks:
        doc = Document(
            page_content=chunk.content,
            metadata=_flatten_metadata(chunk, resume_id)
        )
        documents.append(doc)

        chunk_id = f"{chunk.metadata.source_file}#{chunk.chunk_index}"
        ids.append(chunk_id)

        metadatas.append(_flatten_metadata(chunk, resume_id))

    log.debug("Transformed chunks to documents", extra={
        "chunk_count": len(chunks),
        "sample_id": ids[0] if ids else None
    })

    return documents, ids, metadatas


async def index_resume_chunks(
    parsed_resume: ParsedResume,
    resume_id: str
) -> str:
    """
    Index parsed resume chunks in Chroma.

    Args:
        parsed_resume: Result from resume_parser.parse_resume()
        resume_id: Unique identifier for this resume (filename or UUID)

    Returns:
        Collection ID (name) for tracking in database

    Raises:
        ValueError: If chunks are empty or indexing fails
    """
    if not parsed_resume.chunks:
        raise ValueError("Cannot index resume with no chunks")

    settings = get_settings()
    collection_name = settings.chroma_collection_name

    try:
        client = get_chroma_client()

        # Transform chunks to LangChain Documents
        documents, ids, metadatas = _transform_chunks_to_documents(
            parsed_resume.chunks,
            resume_id
        )

        log.info("Adding chunks to Chroma", extra={
            "collection": collection_name,
            "chunk_count": len(documents),
            "resume_id": resume_id
        })

        # Add documents to Chroma (embeddings are auto-generated)
        client.add_documents(documents=documents, ids=ids, metadatas=metadatas)

        log.info("Chunks indexed successfully", extra={
            "collection": collection_name,
            "chunk_count": len(documents),
            "resume_id": resume_id
        })

        return collection_name

    except Exception as e:
        log.error("Failed to index chunks in Chroma", extra={
            "error": str(e),
            "resume_id": resume_id,
            "chunk_count": len(parsed_resume.chunks)
        })
        raise ValueError(f"Chroma indexing failed: {e}") from e


async def get_collection_size(collection_name: str) -> int:
    """Get the number of documents in a collection."""
    try:
        client = get_chroma_client()
        collection = client._client.get_collection(name=collection_name)
        return collection.count()
    except Exception as e:
        log.warning("Could not get collection size", extra={"error": str(e)})
        return 0
