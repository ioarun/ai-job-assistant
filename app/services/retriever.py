import logging
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from app.core.config import get_settings
from app.services.vector_store import get_chroma_client

log = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A chunk retrieved from the vector store."""
    chunk_id: str
    content: str
    score: float
    metadata: dict
    source_file: str
    chunk_index: int


class HybridRetriever:
    """Hybrid retriever combining BM25 + dense search + reranking."""

    def __init__(self):
        self.settings = get_settings()
        self.chroma = get_chroma_client()
        self.reranker = CrossEncoder(self.settings.reranker_model)
        self._bm25_index = None
        self._bm25_docs = []

    def _build_bm25_index(self) -> None:
        """Build BM25 index from Chroma collection."""
        try:
            collection = self.chroma._collection
            docs = collection.get()

            if not docs or not docs.get("documents"):
                log.warning("No documents in Chroma collection for BM25 indexing")
                return

            self._bm25_docs = docs["documents"]
            tokenized_docs = [doc.lower().split() for doc in self._bm25_docs]
            self._bm25_index = BM25Okapi(tokenized_docs)

            log.debug("BM25 index built", extra={"doc_count": len(self._bm25_docs)})

        except Exception as e:
            log.warning("Failed to build BM25 index", extra={"error": str(e)})
            self._bm25_index = None

    def _bm25_search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        """
        BM25 lexical search.

        Returns:
            List of (doc_index, score) tuples
        """
        if self._bm25_index is None:
            self._build_bm25_index()

        if self._bm25_index is None:
            return []

        tokenized_query = query.lower().split()
        scores = self._bm25_index.get_scores(tokenized_query)

        # Get top-k by score
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]

    def _dense_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """
        Dense semantic search from Chroma.

        Returns:
            List of (doc_id, score) tuples
        """
        try:
            results = self.chroma.similarity_search_with_scores(query, k=top_k)

            retrieved = []
            for doc, score in results:
                doc_id = doc.metadata.get("chunk_id") or f"{doc.metadata.get('source_file')}#{doc.metadata.get('chunk_index')}"
                retrieved.append((doc_id, score))

            return retrieved

        except Exception as e:
            log.warning("Dense search failed", extra={"error": str(e)})
            return []

    def _reciprocal_rank_fusion(
        self,
        bm25_results: list[tuple],
        dense_results: list[tuple],
        k: int = 60
    ) -> dict[str, float]:
        """
        Fuse BM25 and dense results using Reciprocal Rank Fusion (RRF).

        RRF formula: RRF(d) = sum over sources (1 / (k + rank(d)))
        """
        fused_scores = {}

        # BM25 scores (using indices from _bm25_docs)
        for rank, (doc_idx, bm25_score) in enumerate(bm25_results):
            if doc_idx < len(self._bm25_docs):
                doc_id = f"bm25_{doc_idx}"
                rrf_score = 1.0 / (k + rank + 1)
                fused_scores[doc_id] = fused_scores.get(doc_id, 0) + rrf_score

        # Dense scores (already have doc_ids)
        for rank, (doc_id, dense_score) in enumerate(dense_results):
            rrf_score = 1.0 / (k + rank + 1)
            fused_scores[doc_id] = fused_scores.get(doc_id, 0) + rrf_score

        # Sort by fused score
        ranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
        return dict(ranked)

    def _rerank_results(
        self,
        query: str,
        results: list[RetrievedChunk],
        top_k: int
    ) -> list[RetrievedChunk]:
        """
        Rerank results using cross-encoder.

        Args:
            query: Search query
            results: Retrieved chunks to rerank
            top_k: Number of results to return

        Returns:
            Reranked top-k results
        """
        if not results:
            return []

        try:
            # Prepare pairs for cross-encoder
            pairs = [(query, chunk.content) for chunk in results]

            # Get reranker scores
            scores = self.reranker.predict(pairs)

            # Update scores and sort
            for i, chunk in enumerate(results):
                chunk.score = float(scores[i])

            reranked = sorted(results, key=lambda x: x.score, reverse=True)
            return reranked[:top_k]

        except Exception as e:
            log.warning("Reranking failed, returning unranked results", extra={"error": str(e)})
            return results[:top_k]

    async def retrieve(
        self,
        query: str,
        top_k: int = None,
        with_reranking: bool = True
    ) -> list[RetrievedChunk]:
        """
        Retrieve chunks using hybrid search + optional reranking.

        Args:
            query: Search query
            top_k: Number of results to return (uses config default if None)
            with_reranking: Whether to apply cross-encoder reranking

        Returns:
            List of retrieved chunks, ranked by relevance
        """
        if top_k is None:
            top_k = self.settings.top_k_retrieval

        log.info("Retrieving chunks", extra={
            "query": query[:100],
            "top_k": top_k,
            "with_reranking": with_reranking
        })

        try:
            # Hybrid search
            bm25_results = self._bm25_search(query, top_k=top_k)
            dense_results = self._dense_search(query, top_k=top_k)

            # Fuse results
            fused = self._reciprocal_rank_fusion(bm25_results, dense_results)

            # Get full documents from Chroma for top fused results
            retrieved_chunks = []
            for doc_id, fusion_score in list(fused.items())[:top_k * 2]:
                try:
                    results = self.chroma.similarity_search_with_scores(query, k=1, filter={"source_file": doc_id.split("#")[0]})
                    if results:
                        doc, score = results[0]
                        chunk = RetrievedChunk(
                            chunk_id=doc_id,
                            content=doc.page_content,
                            score=fusion_score,
                            metadata=doc.metadata,
                            source_file=doc.metadata.get("source_file", ""),
                            chunk_index=doc.metadata.get("chunk_index", 0)
                        )
                        retrieved_chunks.append(chunk)
                except Exception as e:
                    log.debug("Failed to retrieve document", extra={"doc_id": doc_id, "error": str(e)})
                    continue

            # Rerank if requested
            if with_reranking and retrieved_chunks:
                reranker_top_k = self.settings.reranker_top_k
                retrieved_chunks = self._rerank_results(query, retrieved_chunks, reranker_top_k)

            log.info("Retrieval complete", extra={
                "query": query[:100],
                "results_count": len(retrieved_chunks)
            })

            return retrieved_chunks

        except Exception as e:
            log.error("Retrieval failed", extra={"error": str(e), "query": query})
            return []


# Lazy singleton
_retriever = None


async def get_retriever() -> HybridRetriever:
    """Get the shared retriever instance."""
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever
