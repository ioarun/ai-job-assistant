# Phase B — Theory & Concepts

> The *why* behind everything Phase B implements. Read this for the concepts;
> read [phase-b.md](phase-b.md) for the file-by-file build walkthrough.
> Last updated: 2026-06-19.

---

## The big picture: RAG (Retrieval-Augmented Generation)

An LLM only knows what was in its training data. **RAG** is the pattern of *fetching relevant external text at query time* and stuffing it into the prompt, so the model answers from *your* documents instead of its memory.

It splits into two halves:
- **Retrieval** — find the most relevant chunks of your data for a given query. (This is all of Phase B.)
- **Generation** — feed those chunks to the LLM to produce an answer. (Now realized in **Phase C**: the gap analyzer reuses this exact retriever to pull resume context, then feeds it to the LLM to assess skill gaps.)

Phase B built the retrieval half against the resume. The quality of a RAG system is **bounded by retrieval** — if you fetch the wrong chunks, no amount of clever prompting saves the answer. That's why retrieval gets its own phase and its own eval gate.

---

## Step 1 — Chunking

You can't retrieve "a whole resume." Retrieval works on **chunks**: small, self-contained passages.

**Why chunk at all?**
1. **Granularity** — a query about "Docker experience" should return the *paragraph* about Docker, not the entire 2-page document.
2. **Embedding limits** — embedding models compress text into a fixed-size vector. Cram a whole document in and the vector becomes a mushy average that matches nothing well. One idea per chunk → one sharp vector.
3. **Context window economy** — you'll later paste chunks into an LLM prompt; smaller relevant chunks = less token cost.

**How we chunked:** `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)`.
- **Recursive** means it tries to split on the *most natural* boundary first and degrades gracefully: paragraph break (`\n\n`) → line break (`\n`) → sentence (`. `) → word (` `) → mid-word (last resort). This keeps semantically-coherent text together.
- **chunk_size=1000** — target ~1000 characters per chunk.
- **chunk_overlap=200** — consecutive chunks share 200 characters. This is the key trick: if "deployed on **Docker** and Kubernetes" straddles a chunk boundary, the overlap ensures the phrase isn't cut in half and orphaned from either chunk.

The resume → **6 chunks** (`#0`–`#5`).

---

## Step 2 — Embeddings & the vector store

### Embeddings
An **embedding** is a list of numbers (a **vector**, e.g. 1536 dimensions) that represents the *meaning* of a piece of text. The model that produces them (`text-embedding-3-small`) is trained so that **texts with similar meaning land close together** in this high-dimensional space, and unrelated texts land far apart.

"Containerization" and "Docker" produce nearby vectors even though they share no letters — because the model learned they're semantically related. That's the superpower embeddings give you over keyword matching.

### Similarity
"Close together" is measured by **cosine similarity** — the cosine of the angle between two vectors. Same direction → cosine ≈ 1 (very similar); perpendicular → 0 (unrelated). It compares *direction*, not magnitude, which is what you want for meaning.

### Vector store (Chroma)
A **vector database** stores chunks alongside their embedding vectors and can answer: "given this query vector, return the *k* nearest chunk vectors." We used **Chroma**, persisted to disk at `data/vector_store`. When you index a chunk, Chroma calls the embedding model, stores `(chunk_id, text, vector, metadata)`, and builds an index for fast nearest-neighbour search.

---

## Step 3 — The two retrieval modalities

The central idea of Phase B: **two fundamentally different ways to find relevant text, each strong where the other is weak.**

### Lexical search — BM25
**BM25** is a classic keyword-ranking algorithm (the math behind search engines for decades). It scores a chunk by **how many query terms it contains, weighted by how rare those terms are**:
- A chunk containing "MobileNet" scores high for the query "MobileNet" because the words literally match.
- **TF (term frequency):** more occurrences → higher score.
- **IDF (inverse document frequency):** rare words (e.g. "TensorRT") count more than common ones (e.g. "and"). A match on a rare, distinctive term is strong evidence.
- BM25 adds **saturation** (the 10th occurrence of a word matters less than the 1st) and **length normalization** (so long chunks don't win just by being long).

**Strength:** exact terminology, names, acronyms, code identifiers.
**Weakness:** zero understanding of meaning. "Containerization" won't match "Docker" — no shared words.

`rank_bm25`'s `BM25Okapi` builds this index over the tokenized chunk text.

### Semantic / dense search
"Dense" because embeddings are **dense vectors** (every dimension has a value), as opposed to BM25's **sparse** representation (a huge vector that's mostly zeros, one slot per vocabulary word).

Dense search embeds the *query* and finds chunks whose vectors are nearest. This catches **paraphrase and synonymy** that BM25 misses.

**Strength:** meaning, synonyms, related concepts.
**Weakness:** can drift — may return something "vibe-similar" while missing an exact rare keyword the user clearly wanted.

### Why both → hybrid retrieval
Lexical nails exact terms; semantic nails meaning. They are **complementary**. Using *both* is called **hybrid retrieval** — and it consistently beats either alone. That's the core architectural choice of Phase B.

---

## Step 4 — Fusion (RRF)

Now you have two ranked lists — BM25's and dense's — with **incompatible scores** (BM25 scores might be 0–15; cosine similarities are 0–1). You can't just add them. How do you merge?

**Reciprocal Rank Fusion (RRF)** solves this elegantly by **ignoring the scores entirely and using only rank position**:

```
RRF(d) = Σ over lists   1 / (k + rank_in_that_list(d))
```

- For each list, a chunk contributes `1 / (k + its_rank)`. Rank 1 → big contribution; rank 50 → tiny.
- A chunk's final score is the **sum** across both lists.
- **k = 60** (the standard constant) is a damping factor: it softens the gap between rank 1 and rank 2 so the very top of one list can't completely dominate.

**Why it works:** a chunk that ranks well in *either* list surfaces; a chunk that ranks well in *both* wins decisively. And because it only uses ranks, it doesn't matter that BM25 and cosine scores live on different scales. Simple, robust, no tuning. This is the de-facto standard for hybrid fusion.

> This is exactly where **bug #3** lived (see [phase-b.md §6](phase-b.md)): BM25 returns *positions* in the corpus (0, 1, 2…), not IDs. We had to map each position back to its real `chunk_id` so both lists fuse in the *same ID space*. Otherwise the BM25 half got silently dropped.

---

## Step 5 — Reranking (the cross-encoder)

After fusion you have a shortlist of, say, 10 candidate chunks. The final stage **rescores them with a much more accurate (but slower) model**: a **cross-encoder**.

To understand why this is a separate stage, you need the **bi-encoder vs cross-encoder** distinction — a favourite interview question:

| | **Bi-encoder** (dense search) | **Cross-encoder** (reranker) |
|---|---|---|
| How | Embeds query and chunk **separately**, compares vectors | Feeds query and chunk **together** into one model, outputs a relevance score |
| Sees interaction? | No — each is encoded in isolation | Yes — the model attends to query↔chunk word interactions |
| Accuracy | Good | **Much better** |
| Speed | Fast — chunk vectors are **precomputed once** at index time | Slow — must run the model fresh for *every* (query, chunk) pair |
| Scales to | Millions of chunks | Only a small shortlist |

So you get the best of both: the **bi-encoder casts a wide cheap net** (search the whole store), then the **cross-encoder does expensive precise scoring** on just the survivors. Running the cross-encoder over your entire corpus would be far too slow; running it over 10 candidates is trivial.

Our reranker: `ms-marco-MiniLM-L-12-v2` — a small cross-encoder trained on the MS MARCO passage-ranking dataset, downloaded from Hugging Face and run locally via `sentence-transformers`. It reads each `(query, chunk)` pair, outputs a relevance score, and we re-sort, keeping the top `reranker_top_k=5`.

The full pipeline shape — **dual retrieval → fuse → rerank** — is the canonical modern RAG retrieval stack.

---

## Step 6 — Measuring quality (the eval)

You can't improve what you don't measure. We need to quantify "did retrieval find the right chunks?" That requires a **golden set**: hand-labeled `(query, expected_chunk_ids)` pairs that encode ground truth. Then two standard **information-retrieval metrics**:

### Recall@k
> Of the chunks that *should* have been retrieved, what fraction appeared in the **top k**?

```
recall@k = |relevant ∩ top-k retrieved| / |relevant|
```

It answers **"did we find the right stuff?"** It's **order-blind** — being in the top-k counts, whether at position 1 or k.

### MRR (Mean Reciprocal Rank)
> How high up was the **first** correct hit? Score = `1 / rank` of the first relevant chunk, averaged over all queries.

First relevant result at rank 1 → 1.0; rank 2 → 0.5; rank 5 → 0.2. It answers **"did we rank the right stuff near the top?"** — it's **order-sensitive**.

### Why both?
They're complementary:
```
retrieved: [Wrong, Right, Right]   expected: {Right, Right}
recall@3 = 2/2 = 1.0   ← found everything
MRR      = 1/2 = 0.5   ← but buried the first hit at rank 2
```
A retriever can have perfect recall but poor MRR (right answers present but ranked low). The **reranker's entire job is to raise MRR**. Tracking both tells you *which stage* to tune: low recall → fix retrieval/fusion; low MRR → fix the reranker.

### The gate
`run_retrieval_eval.py` runs every golden query, averages the metrics, and **exits non-zero if recall@5 < baseline (0.60)**. That non-zero exit is what makes it a **regression gate** — in Phase F it drops into CI so a code change that degrades retrieval *fails the build*. We hit **recall@5 = 1.000** (with the honest caveat: only 6 chunks, so it proves correctness, not yet hard quality). Note this ceiling is **not** lifted by Phase C: jobs are cached in SQLite and the Chroma collection stays resume-only, so making the eval a hard quality signal means **growing the golden set** (more queries, ideally multiple resumes), not ingesting jobs.

---

## Why the bugs were instructive (the meta-concept)

A retrieval pipeline is a **chain of stages that must agree on two things**: the **API surface** and a **single shared ID space**. Three of our four bugs broke one of those silently:
- A swallowed `AttributeError` (`similarity_search_with_scores` vs `…_score`) made the dense stage fail without crashing → "hybrid" was secretly BM25-only.
- Synthetic `bm25_{idx}` IDs broke the shared ID space → BM25 results dropped at fusion.
- Re-fetching by `source_file` filter instead of exact ID returned the wrong chunk.

The lesson worth internalizing: **RAG integration bugs hide behind `try/except` and plausible-looking output.** The system *ran* the whole time — it just ran *wrong*. The only thing that exposed it was pushing real data through and **measuring** with the eval. That's the deeper argument for building the eval harness early.

---

## Glossary (quick reference)

| Term | One-liner |
|---|---|
| **RAG** | Fetch relevant text at query time, feed it to the LLM to ground its answer. |
| **Chunk** | A small, self-contained passage — the unit of retrieval. |
| **Chunk overlap** | Shared characters between consecutive chunks so boundary phrases aren't orphaned. |
| **Embedding** | A vector encoding the *meaning* of text; similar meanings → nearby vectors. |
| **Cosine similarity** | Angle-based closeness measure between two vectors (1 = identical direction). |
| **Vector store** | A DB that finds the *k* nearest vectors to a query vector (here: Chroma). |
| **Dense vector** | Embedding where every dimension has a value (semantic search). |
| **Sparse vector** | Mostly-zero vector, one slot per vocabulary word (lexical / BM25). |
| **BM25** | Classic lexical ranking by term frequency × rarity, with saturation + length norm. |
| **TF / IDF** | Term frequency (how often) / inverse document frequency (how rare = how informative). |
| **Hybrid retrieval** | Combining lexical (BM25) + semantic (dense) retrieval. |
| **RRF** | Reciprocal Rank Fusion — merge ranked lists by rank position, not score. |
| **Bi-encoder** | Encodes query and doc separately; fast, pre-indexable, used for first-stage search. |
| **Cross-encoder** | Encodes query+doc jointly; slower but more accurate, used to rerank a shortlist. |
| **Reranking** | Rescoring a candidate shortlist with a more precise model. |
| **Recall@k** | Fraction of relevant items found in the top-k (order-blind). |
| **MRR** | Mean Reciprocal Rank — `1/rank` of the first relevant hit (order-sensitive). |
| **Golden set** | Hand-labeled (query → expected IDs) ground truth for evaluation. |
| **Regression gate** | A test that fails the build when a metric drops below a baseline. |

---

## One-paragraph summary for an interview

> *"Phase B is a hybrid RAG retriever. I chunk the resume with recursive splitting and overlap, embed the chunks with OpenAI's `text-embedding-3-small` into a Chroma vector store. At query time I run two retrievers in parallel — BM25 for lexical matching and dense vector search for semantic matching — and fuse their ranked lists with Reciprocal Rank Fusion, which is scale-agnostic because it uses only rank position. I then rerank the fused shortlist with a cross-encoder, which jointly encodes query and chunk for higher precision than the bi-encoder used for first-stage retrieval. I measure quality with recall@k and MRR against a golden set, wired as a CI-style gate that fails below a baseline."*
