import pytest
from app.services.eval_retrieval import (
    compute_recall_at_k,
    compute_mrr,
)
from app.services.retriever import HybridRetriever, RetrievedChunk


def test_compute_recall_at_k():
    """Test recall@k computation."""
    retrieved = ["doc_1", "doc_2", "doc_3", "doc_4", "doc_5"]
    expected = ["doc_1", "doc_3", "doc_5"]

    # Recall@3: 2 relevant in top-3 / 3 total = 0.67
    recall_3 = compute_recall_at_k(retrieved, expected, k=3)
    assert 0.65 < recall_3 < 0.70

    # Recall@5: 3 relevant in top-5 / 3 total = 1.0
    recall_5 = compute_recall_at_k(retrieved, expected, k=5)
    assert recall_5 == 1.0


def test_compute_recall_at_k_empty():
    """Test recall@k with no expected results."""
    retrieved = ["doc_1", "doc_2"]
    expected = []

    recall = compute_recall_at_k(retrieved, expected, k=5)
    assert recall == 0.0


def test_compute_mrr():
    """Test Mean Reciprocal Rank computation."""
    # First relevant at rank 2 (0-indexed)
    retrieved = ["doc_a", "doc_b", "doc_c"]
    expected = ["doc_b"]

    mrr = compute_mrr(retrieved, expected)
    assert mrr == 0.5  # 1 / (2 + 1) = 0.333... but 1 / (1 + 1) = 0.5 for rank 2

    # Actually: rank is 1 (0-indexed), so MRR = 1 / (1 + 1) = 0.5
    assert mrr == 0.5


def test_compute_mrr_not_found():
    """Test MRR when no relevant doc is found."""
    retrieved = ["doc_a", "doc_b"]
    expected = ["doc_c"]

    mrr = compute_mrr(retrieved, expected)
    assert mrr == 0.0


def test_bm25_search():
    """Test BM25 search ranking."""
    retriever = HybridRetriever()

    # Mock some documents
    retriever._bm25_docs = [
        "Python and FastAPI development",
        "Machine learning with TensorFlow",
        "Docker and Kubernetes",
        "Python data science",
        "Cloud infrastructure"
    ]

    # Manually build index instead of calling _build_bm25_index
    tokenized_docs = [doc.lower().split() for doc in retriever._bm25_docs]
    from rank_bm25 import BM25Okapi
    retriever._bm25_index = BM25Okapi(tokenized_docs)

    # Query should rank Python-related docs higher
    results = retriever._bm25_search("Python development", top_k=3)

    assert len(results) <= 3
    assert len(results) > 0
    # First result should be about Python
    top_doc_idx = results[0][0]
    assert "Python" in retriever._bm25_docs[top_doc_idx]


def test_bm25_search_empty():
    """Test BM25 search with no index."""
    retriever = HybridRetriever()
    retriever._bm25_index = None

    results = retriever._bm25_search("test query", top_k=5)
    assert results == []


def test_reciprocal_rank_fusion():
    """Test RRF fusion of BM25 and dense results."""
    retriever = HybridRetriever()

    bm25_results = [(0, 10.0), (1, 8.0), (2, 5.0)]
    dense_results = [("doc_2", 0.9), ("doc_1", 0.8), ("doc_0", 0.7)]

    fused = retriever._reciprocal_rank_fusion(bm25_results, dense_results, k=60)

    assert len(fused) > 0
    # Top result should have highest combined score
    top_doc = max(fused.items(), key=lambda x: x[1])
    assert top_doc[1] > 0


def test_retrieved_chunk_dataclass():
    """Test RetrievedChunk dataclass."""
    chunk = RetrievedChunk(
        chunk_id="test.pdf#0",
        content="Test content",
        score=0.95,
        metadata={"source": "test"},
        source_file="test.pdf",
        chunk_index=0
    )

    assert chunk.chunk_id == "test.pdf#0"
    assert chunk.content == "Test content"
    assert chunk.score == 0.95
    assert chunk.source_file == "test.pdf"
    assert chunk.chunk_index == 0
