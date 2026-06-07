#!/usr/bin/env python3
"""
Index a resume PDF into Chroma.

Usage:
    python -m scripts.index_resume path/to/resume.pdf [--resume-id ID]

Parses the PDF, chunks it, and indexes the chunks in the Chroma collection.
Chunk IDs are written as "<filename>#<chunk_index>" (e.g. resume.pdf#0),
which is the same scheme the retrieval eval golden set must reference.

Run this before evals/run_retrieval_eval.py.
"""
import argparse
import asyncio
import logging
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.observability.langfuse_client import shutdown_langfuse
from app.services.resume_parser import parse_resume
from app.services.vector_store import index_resume_chunks, get_collection_size


async def index(pdf_path: Path, resume_id: str | None) -> None:
    log = logging.getLogger(__name__)
    settings = get_settings()
    settings.ensure_dirs()

    resume_id = resume_id or pdf_path.name

    log.info("Parsing resume", extra={"file": str(pdf_path)})
    parsed = await parse_resume(pdf_path)
    log.info("Parsed", extra={"chunks": len(parsed.chunks), "tokens": parsed.total_tokens})

    collection = await index_resume_chunks(parsed, resume_id=resume_id)
    size = await get_collection_size(collection)

    print("\n" + "=" * 60)
    print("Indexing complete")
    print(f"  file:          {pdf_path.name}")
    print(f"  resume_id:     {resume_id}")
    print(f"  chunks added:  {len(parsed.chunks)}")
    print(f"  collection:    {collection} (now {size} docs)")
    print("  chunk_ids:     " + ", ".join(
        f"{pdf_path.name}#{c.chunk_index}" for c in parsed.chunks[:6]
    ) + (" ..." if len(parsed.chunks) > 6 else ""))
    print("=" * 60)
    print("\nUse these chunk_ids as expected_doc_ids in")
    print("evals/datasets/retrieval_golden.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Index a resume PDF into Chroma.")
    parser.add_argument("pdf_path", type=Path, help="Path to the resume PDF")
    parser.add_argument("--resume-id", default=None, help="Resume ID (default: filename)")
    args = parser.parse_args()

    configure_logging()

    if not args.pdf_path.exists():
        raise SystemExit(f"File not found: {args.pdf_path}")

    try:
        asyncio.run(index(args.pdf_path, args.resume_id))
    finally:
        shutdown_langfuse()


if __name__ == "__main__":
    main()
