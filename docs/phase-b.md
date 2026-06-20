# Phase B — RAG Capability

> A complete walkthrough of what we built, why, and how the pieces fit together.
> Read alongside the files in the repo. Last updated: 2026-06-19.
>
> For the *concepts* behind these pieces (RAG, BM25, embeddings, RRF, cross-encoders,
> recall@k / MRR), see [phase-b-theory.md](phase-b-theory.md).

---

## 1. What Phase B is (and isn't)

**Phase B's goal:** turn a resume PDF into something *retrievable*. Parse it, chunk it, embed it into a vector store, and stand up a **hybrid retriever** (lexical + semantic + reranking) that can answer "which parts of this resume are relevant to query X?" — then **prove the retrieval quality with an eval gate**.

This is the first phase that touches the actual product. Phase A was plumbing; Phase B is the first load-bearing capability the agent (Phase D) and tools (Phase C) will lean on.

**Phase B's "Done when" criteria, all met:**
1. ✅ Given a resume PDF, parsing → chunking → indexing runs end-to-end
2. ✅ Hybrid retrieval (BM25 + dense + rerank) returns relevant chunks for sample queries
3. ✅ The eval script reports **recall@5 ≥ baseline** — we hit **recall@5 = 1.000** (baseline 0.60), recall@10 = 1.000, MRR = 1.000 on the real resume

**What's intentionally NOT in Phase B:**
- No job descriptions in the store yet — only the resume (job ingestion is Phase C)
- No multi-query expansion, no HyDE, no metadata filtering by section
- No agent calling the retriever (Phase D); no UI (Phase G)
- No Promptfoo/CI wiring — the eval runner exists and is CI-shaped, but it gets bolted into GitHub Actions in Phase F

**Honest caveat on the eval:** with a single resume the store holds only **6 chunks**, and the eval returns at most 5 results. A perfect 1.000 proves the pipeline *runs correctly and is genuinely hybrid* — it is **not yet a hard test of retrieval quality**. Note the Chroma collection stays **resume-only**: Phase C caches jobs in **SQLite**, and the gap analyzer retrieves *resume* chunks, so job ingestion does **not** lift the 6-chunk ceiling (this corrects an earlier forecast). The gate only becomes discriminating once the **golden set grows** — more queries, and ideally multiple resumes. That's revisited in §8.

---

## 2. The retrieval picture

What happens on a single `retriever.retrieve("Visual Inertial Odometry on a Jetson rover")` call:

```mermaid
flowchart TD
    Q[Query string] --> BM25[BM25 lexical search<br/><i>rank_bm25 over chunk text</i>]
    Q --> DENSE[Dense semantic search<br/><i>Chroma + text-embedding-3-small</i>]

    BM25 -->|doc indices → real chunk_ids| RRF
    DENSE -->|chunk_ids + scores| RRF[Reciprocal Rank Fusion<br/><i>1 / k + rank, k=60</i>]

    RRF -->|top fused chunk_ids| FETCH[Fetch each chunk by exact ID<br/><i>collection.get ids=...</i>]
    FETCH --> RERANK[Cross-encoder rerank<br/><i>ms-marco-MiniLM-L-12-v2</i>]
    RERANK --> TOPK[Top-k RetrievedChunk list]
```

Two retrieval *modalities* run in parallel and get **fused**, then a heavier model **reranks** the survivors:

- **BM25** (lexical): exact-term matching. Great when the query and the resume share vocabulary ("MobileNet", "Azure App Service"). Cheap, no embeddings.
- **Dense** (semantic): embeds the query with `text-embedding-3-small` and finds nearest neighbours in Chroma. Catches paraphrase ("containerization" ≈ "Docker") that BM25 misses.
- **Reciprocal Rank Fusion (RRF)**: combines the two ranked lists without needing their scores to be on the same scale — it only uses *rank position*. A chunk that ranks well in *either* list bubbles up; one that ranks well in *both* wins.
- **Cross-encoder reranker**: a small model that reads `(query, chunk)` *together* (not as separate embeddings) and scores true relevance. Slow per-pair, so it only runs on the fused shortlist, not the whole store.

That four-stage shape — **dual-modality → fuse → rerank** — is the canonical modern RAG retrieval stack. Building it (rather than a single `similarity_search`) is the marketable skill.

---

## 3. File-by-file walkthrough

### 3.1 `app/models/documents.py` — the data contracts

Three Pydantic models that everything else passes around:
- **`DocumentMetadata`** — `source_file`, `parsed_at`, `page_count`, `total_size_bytes`. Travels with every chunk.
- **`DocumentChunk`** — `content`, `chunk_index`, `page_number`, `metadata`. The atom of retrieval.
- **`ParsedResume`** — `filename`, `chunks[]`, `total_tokens`, `parse_duration_ms`. The output of parsing.

Why Pydantic and not dicts: the same fail-fast, typed discipline as Phase A's config. A malformed chunk fails at construction, not three layers deeper inside Chroma.

### 3.2 `app/services/resume_parser.py` — PDF → text → chunks

`parse_resume(file_path) -> ParsedResume` (async). The pipeline:
1. **Guard**: file exists, suffix is `.pdf`.
2. **Extract**: `UnstructuredPDFLoader` (same parser as pdf-rag, chosen in Phase A) pulls text out, handling layout and OCR fallback.
3. **Chunk**: `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)` with a separator cascade `["\n\n", "\n", ". ", " ", ""]` — it tries to split on paragraph boundaries first, degrading to sentences, then words, only cutting mid-word as a last resort. The 200-char overlap means a skill mentioned at a chunk boundary isn't orphaned.
4. **Token estimate**: rough `len(text) // 4` — good enough for logging/cost sanity, not billing.

Our real resume produced **6 chunks** (`#0`–`#5`).

### 3.3 `app/services/vector_store.py` — Chroma bootstrap & indexing

- **`get_chroma_client()`** — `@lru_cache` singleton (same pattern as `get_settings()`). Wires `OpenAIEmbeddings(text-embedding-3-small)` + a persistent Chroma collection named `resumes` at `./data/vector_store`.
- **`index_resume_chunks(parsed_resume, resume_id)`** — transforms chunks into LangChain `Document`s and adds them to Chroma. Embeddings are generated automatically by the collection's embedding function.
- **`get_collection_size(name)`** — used by the eval gate to refuse to run against an empty store.

**The chunk_id scheme** is the linchpin of the whole phase:

```python
chunk_id = f"{chunk.metadata.source_file}#{chunk.chunk_index}"
# → "Arun Kumar - ML Engineer - 2026.pdf#0"
```

This deterministic ID is what the golden eval set references, what RRF fuses on, and what the reranker fetches by. **It has to be stable and shared across every stage** — a recurring theme in the bugs we hit (§6).

### 3.4 `app/services/retriever.py` — the HybridRetriever

The heart of Phase B. A class because it caches expensive state: the loaded cross-encoder model and a lazily-built BM25 index.

- **`_build_bm25_index()`** — pulls all documents *and their IDs* out of Chroma and builds a `BM25Okapi` index over the tokenized text. Stores `_bm25_docs` **and** `_bm25_ids` in parallel so a BM25 hit (which is a *position* in the corpus) can be mapped back to its real `chunk_id`.
- **`_bm25_search(query, top_k)`** — returns `(doc_index, score)` tuples.
- **`_dense_search(query, top_k)`** — `chroma.similarity_search_with_score(...)`, returns `(chunk_id, score)`.
- **`_reciprocal_rank_fusion(bm25, dense, k=60)`** — maps BM25 indices → real `chunk_id`s, then fuses both lists into `{chunk_id: rrf_score}`. The `k=60` constant is the standard RRF damping factor.
- **fetch-by-ID** — for each fused `chunk_id`, `collection.get(ids=[doc_id])` retrieves *exactly that chunk* so the content and the ID always correspond.
- **`_rerank_results(query, chunks, top_k)`** — the cross-encoder scores every `(query, chunk.content)` pair and re-sorts, truncating to `reranker_top_k`.
- **`retrieve(query, top_k, with_reranking=True)`** — orchestrates all of the above. The public entry point.

### 3.5 `app/services/eval_retrieval.py` — the metrics

Pure functions, trivially unit-testable:
- **`compute_recall_at_k(retrieved, expected, k)`** — fraction of the expected (relevant) chunks that appear in the top-k retrieved. "Did we find the right stuff?"
- **`compute_mrr(retrieved, expected)`** — `1 / rank` of the *first* relevant hit. "Did we rank the right stuff near the top?"
- **`run_eval_suite(retriever, golden, k_values)`** — runs every golden query through the retriever and averages the metrics.

Recall and MRR are complementary: recall ignores *order*, MRR is *all about* order. Reporting both is honest.

### 3.6 `evals/datasets/retrieval_golden.json` — the ground truth

8 `(query, expected_doc_ids)` pairs. **Every mapping was derived by reading the actual indexed chunk text**, not guessed — e.g. "MobileNet waste type detection Android application" → `#4`, because chunk `#4` is literally where that project is described. A golden set that doesn't correspond to real chunk content measures nothing.

### 3.7 `scripts/index_resume.py` — the indexing entry point (new)

`python -m scripts.index_resume <pdf>`. Parses + indexes a resume and **prints the real `chunk_id`s** so you can build a golden set against them. Run it once per resume before evaluating.

### 3.8 `evals/run_retrieval_eval.py` — the gate (new)

`python -m evals.run_retrieval_eval`. Loads the golden set, runs the suite, prints recall@5 / recall@10 / MRR, and:
- **guards an empty collection** (exit 2 — "index a resume first")
- **exits non-zero when recall@5 < baseline** (default 0.60)

That non-zero exit is deliberate: this file is already shaped to be dropped into GitHub Actions as the Phase F prompt/retrieval-regression gate. `--baseline` and `--dataset` are CLI-overridable.

---

## 4. Three cross-cutting concepts to keep in your head

### 4.1 Why fuse *and* rerank (they do different jobs)

```
BM25 list  ─┐
            ├─ RRF ─→ shortlist ─→ cross-encoder ─→ final ranking
Dense list ─┘   (cheap, recall)     (expensive, precision)
```

- **RRF maximises recall cheaply** — it casts a wide net by merging two complementary candidate sets, using only rank position so the two score scales never need normalising.
- **The cross-encoder maximises precision expensively** — it actually reads query+chunk together, so it only runs on the ~10-item shortlist, never the whole corpus.

Bi-encoder (dense) embeds query and document *separately*; cross-encoder embeds them *jointly* and is far more accurate but cannot be pre-indexed. Using each where it's strong is the whole point.

### 4.2 The chunk_id is the shared key — keep it stable everywhere

```
parse → "<file>#<index>"        (vector_store builds it)
index → stored as Chroma ID     (same string)
BM25  → corpus position → map back to the same chunk_id
RRF   → fuses on chunk_id
fetch → collection.get(ids=[chunk_id])
eval  → golden set references chunk_id
```

If *any* stage invents its own ID space, fusion silently drops half its inputs or mislabels content. Three of our four bugs (§6) were exactly this failure.

### 4.3 Recall@k vs MRR

```
retrieved: [C, A, B]   expected: {A, B}
recall@3 = 2/2 = 1.0   (both found)        ← order-blind
MRR      = 1/2 = 0.5   (first hit at rank 2) ← order-sensitive
```

A retriever can have perfect recall but mediocre MRR (right answers present, buried). The reranker's whole job is to push MRR up. Tracking both tells you *which* stage to tune.

---

## 5. Key design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Retrieval strategy | Hybrid: BM25 + dense + RRF + rerank | The modern RAG default. Lexical and semantic catch different misses; fusion + rerank is the standard precision/recall trade. |
| Fusion method | Reciprocal Rank Fusion (k=60) | Score-scale agnostic — works across BM25 scores and cosine distances without normalising. The de-facto standard. |
| Reranker | `ms-marco-MiniLM-L-12-v2` cross-encoder | Small, fast, strong on short passages. Local (sentence-transformers), no extra API cost. |
| Embeddings | `text-embedding-3-small` | Cheap, good, matches the locked stack and pdf-rag. |
| Chunking | Recursive, 1000/200 | Paragraph-preferring splits with overlap so boundary skills aren't orphaned. |
| Chunk ID | `<filename>#<index>` | Deterministic, human-readable, stable across stages and runs. The shared key for fusion, fetch, and eval. |
| Eval metrics | recall@k + MRR | Complementary: presence vs ranking. Standard retrieval-quality pair. |
| Eval gate | non-zero exit below baseline | Reusable as-is for the Phase F CI regression gate. |

---

## 6. Bugs we hit getting it working (and how we fixed them)

The Phase B retrieval/index code existed from earlier commits but had **never run end-to-end** — the old smoke test bailed while parsing an empty placeholder PDF, so nothing downstream had ever executed against real data. Running it for the first time surfaced **four latent bugs**, all now fixed:

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | `Chroma.add_texts() got multiple values for argument 'metadatas'` — indexing crashed | `add_documents(documents, ids, metadatas=...)` passed metadata twice: the `Document`s already carry it, and `add_documents` forwards `metadatas` into `add_texts` | Drop the `metadatas=` kwarg; let the `Document` objects carry metadata |
| 2 | `Dense search failed` warning on every query → "hybrid" was silently BM25-only | Called `similarity_search_with_scores` (plural) — the langchain_chroma method is `similarity_search_with_score` (singular); the `AttributeError` was caught and swallowed | Fix the method name |
| 3 | BM25 results contributed nothing to fusion | RRF assigned BM25 hits synthetic IDs `bm25_{idx}`, mixing them with real `chunk_id`s; those fake IDs then failed the downstream fetch and were dropped | Map BM25 corpus indices back to real `chunk_id`s via the new `_bm25_ids` list |
| 4 | Reranker scored the wrong text; content mislabeled | Re-fetch used `similarity_search(query, k=1, filter={source_file})`, which returns the *most-similar* chunk in that file, not the chunk identified by the ID — so with one resume every candidate collapsed to the same chunk | Fetch each chunk by its exact ID: `collection.get(ids=[doc_id])` |

**The pattern across #2–#4:** a retrieval pipeline is a chain of stages that must agree on (a) the API surface and (b) a single ID space. A swallowed `AttributeError` and an inconsistent ID scheme turned a "hybrid + rerank" retriever into "dense-only, then BM25-only, then mislabeled" — and it still *ran*, just wrongly. The lesson: **integration bugs in RAG hide behind try/except and plausible-looking output; you only catch them by running real data through and measuring.**

Two tests had encoded the old buggy contracts and were updated to assert the correct behaviour:
- `test_index_resume_chunks_mock` — was asserting the `metadatas=` kwarg (bug #1); now asserts metadata travels on the `Document`s.
- `test_bm25_search_empty` — assumed an empty Chroma; once a real resume was indexed, `_bm25_search` rebuilt a non-empty index from the live collection. Made the "no usable index" path deterministic instead of DB-dependent.

---

## 7. How to verify everything still works

From the repo root, with the Phase A stack already up:

```bash
# (one-time) index a resume — prints the real chunk_ids
docker compose -f docker/docker-compose.yml exec app \
  python3 -m scripts.index_resume "data/uploads/<your_resume>.pdf"

# run the retrieval-quality gate
docker compose -f docker/docker-compose.yml exec app \
  python3 -m evals.run_retrieval_eval

# run the unit tests
docker compose -f docker/docker-compose.yml exec app \
  python3 -m pytest tests/ -q
```

Expected: the gate prints `RESULT: PASS ✅` with recall@5 ≥ 0.60 and exits 0; all unit tests pass.

> **Note on file ownership:** the container runs as root, so files it writes under `data/` (the Chroma store) are root-owned on the host. If you need host-side access, run `sudo chown -R arun:arun data/`.

---

## 8. What's deliberately missing (and where it lands)

| Missing piece | Lands in |
|---|---|
| Adzuna job search, project suggestions, interview Q&A | Phase C (Adzuna client done; gap analysis underway) |
| The retriever reused by the tools / agent | **Started:** the Phase C gap analyzer now calls `retrieve()` for resume context; full agent orchestration is Phase D |
| Multi-query expansion / HyDE / section-aware filtering | Future (if evals justify it) |
| Promptfoo config + GitHub Actions running this gate on every PR | Phase F |
| A larger golden set across multiple documents | Phase F (alongside gap/interview goldens) |
| Streamlit "upload resume → see retrieved chunks" UI | Phase G |

**Correction to an earlier forecast:** previous versions of this doc predicted Phase C would index job descriptions into the Chroma collection and thereby lift the 6-chunk ceiling. That is **not** what Phase C does — jobs are cached in **SQLite**, and the gap analyzer retrieves *resume* chunks, so the collection stays resume-only. Making this eval a hard quality signal therefore depends on **growing the golden set** (more queries, ideally multiple resumes) — not on job ingestion. Revisit the golden set in Phase F.

---

## 9. Tech stack actually used in Phase B

Builds on the Phase A foundation; adds the RAG-specific pieces.

### Application (Python)

| Component | Package(s) | Role in Phase B |
|---|---|---|
| PDF parsing | `unstructured` (`UnstructuredPDFLoader`) | Extract text from the resume PDF |
| Chunking | `langchain-text-splitters` | Recursive 1000/200 character splitting |
| Vector store | `langchain-chroma`, `chromadb` | Persistent embedding store + similarity search |
| Embeddings | `langchain-openai` (`text-embedding-3-small`) | Dense vectors for semantic search |
| Lexical search | `rank-bm25` (`BM25Okapi`) | Keyword/term retrieval |
| Reranking | `sentence-transformers` (`CrossEncoder`) | `ms-marco-MiniLM-L-12-v2` precision rerank |
| Data contracts | `pydantic` | `DocumentChunk` / `ParsedResume` models |
| Tracing | `langfuse` | Every retrieval/index call traced (free from Phase A) |

### External

| Service | Usage |
|---|---|
| OpenAI API | `text-embedding-3-small` for indexing + dense query embedding |
| Hugging Face Hub | One-time download of the cross-encoder weights |

---

## 10. Skills demonstrated by Phase B

### Retrieval engineering (RAG)
- **Built a full hybrid retrieval pipeline** — BM25 + dense, fused with Reciprocal Rank Fusion, reranked with a cross-encoder. Not a toy `similarity_search`; the modern production shape.
- **Understood *why* each stage exists**: lexical vs semantic recall, RRF's scale-agnostic fusion, bi-encoder vs cross-encoder precision trade-offs, and where each belongs in the latency budget.
- **Designed a stable, shared chunk-ID scheme** as the contract across indexing, fusion, fetch, and evaluation.

### Evaluation & measurement
- **Implemented recall@k and MRR from first principles** and understood what each does (and doesn't) capture.
- **Built a CI-shaped eval gate** with a baseline threshold and non-zero exit — reusable directly as a regression gate.
- **Authored an honest golden set** mapped to real chunk content, and was candid about its current limits (6-chunk ceiling) rather than overselling a 1.000 score.

### Debugging integration failures
- **Diagnosed four interacting bugs** that left a "hybrid" retriever silently running dense-only, then BM25-only, then mislabeling reranked content — none of which threw a visible error.
- **Recognised the meta-lesson**: swallowed exceptions + inconsistent ID spaces produce plausible-but-wrong output that only real-data evaluation exposes.
- **Fixed the tests that encoded the buggy contracts** rather than deleting them — kept the regression coverage.

### Engineering hygiene
- **Clean separation**: parsing, storage, retrieval, and evaluation are independent, individually-testable services.
- **Operational entry points**: a one-command indexer and a one-command gate, both runnable in-container.
- **Fixed the missing `evals/` bind-mount** in docker-compose so the eval runner and dataset are live-editable like every other source dir.

---

## 11. Questions to ask yourself (interview-readiness check)

Can you answer these without looking?

1. Why combine BM25 and dense retrieval instead of using just one?
2. What does Reciprocal Rank Fusion give you that averaging the two score lists wouldn't?
3. What's the difference between a bi-encoder and a cross-encoder, and why does the cross-encoder only run on a shortlist?
4. Why must the `chunk_id` be identical across indexing, fusion, fetch, and the golden set?
5. Recall@5 is 1.000 — why is that *not yet* strong evidence of retrieval quality?
6. What's the practical difference between recall@k and MRR, and which one does the reranker improve?
7. Bug #4: why does `similarity_search(query, k=1, filter={source_file})` return the wrong chunk when a file has many chunks?
8. Why did three of the four bugs hide instead of crashing the app?
9. Why does the eval runner exit non-zero below baseline, and where will that property be used?
10. When job descriptions land in Phase C, what changes about how meaningful this eval is — and what would you do to the golden set?

If any are fuzzy, those are the right things to ask me about next.

---

## 12. Answers (elaborated)

**1. Why combine BM25 and dense retrieval instead of using just one?**
Because they fail in complementary ways. **BM25** is lexical — it matches exact terms weighted by rarity, so it nails names, acronyms, and code identifiers ("MobileNet", "TensorRT") — but has zero understanding of meaning, so "containerization" won't match "Docker". **Dense** (embedding) search is semantic — it matches meaning, catching paraphrase and synonymy BM25 misses — but can drift, returning something vibe-similar while missing an exact rare keyword the user clearly wanted. Using both (hybrid retrieval) means a relevant chunk surfaces whether the match is lexical or semantic, which consistently beats either alone.

**2. What does Reciprocal Rank Fusion give you that averaging the two score lists wouldn't?**
Scale-independence. BM25 scores and cosine similarities live on different, unnormalized scales (≈0–15 vs 0–1), so averaging them is meaningless — one dominates arbitrarily and the result depends on units, not relevance. RRF discards the scores and uses only **rank position**: each list contributes `1/(k+rank)`, summed across lists. A chunk ranked highly in *either* list surfaces; one ranked highly in *both* wins decisively. Being purely ordinal, it sidesteps normalization and needs no tuning — which is why it's the de-facto standard. The `k=60` damping softens the gap between top ranks so one list's #1 can't completely dominate.

**3. What's the difference between a bi-encoder and a cross-encoder, and why does the cross-encoder only run on a shortlist?**
A **bi-encoder** (dense search) embeds query and document *separately* and compares vectors; document vectors are precomputed once at index time, so it's fast and scales to millions of chunks — but it never sees the pair together, missing fine interactions. A **cross-encoder** (the reranker) feeds query and document *together* into one model that attends across both, giving far more accurate relevance — but it can't be precomputed (it needs the specific pair), so it must run fresh for every (query, chunk) pair. Over the whole corpus that's prohibitively slow; over the ~10-item fused shortlist it's trivial. So the cheap bi-encoder casts a wide net (recall) and the expensive cross-encoder precisely re-orders the survivors (precision).

**4. Why must the `chunk_id` be identical across indexing, fusion, fetch, and the golden set?**
Because the pipeline is a chain of stages that must agree on a single ID space, and `chunk_id` is the shared key joining them. Indexing stores each chunk under `"<file>#<index>"`; fusion combines BM25 and dense results by that id; fetch retrieves content by that exact id; the golden set references those ids as ground truth. If any stage invents its own id space the join silently breaks — results get dropped at fusion or mislabeled at fetch, and the eval measures the wrong thing, all without an error. Three of Phase B's four bugs were exactly this. A stable, shared id is what keeps "the chunk I scored" and "the chunk I fetched" the same chunk.

**5. Recall@5 is 1.000 — why is that *not yet* strong evidence of retrieval quality?**
Because the test is trivially easy at current scale. With one resume the store holds only 6 chunks and the eval returns up to 5 — almost any retriever scores near-perfect because there's barely anything to *not* retrieve. A 1.000 proves the pipeline runs end-to-end and is genuinely hybrid, but it doesn't discriminate good retrieval from mediocre: the haystack is the size of the needle. The score becomes meaningful only once the corpus and golden set grow enough that a worse retriever would actually miss things.

**6. What's the practical difference between recall@k and MRR, and which one does the reranker improve?**
**Recall@k** asks "did we *find* the relevant chunks in the top k?" — order-blind; anywhere in the top-k counts equally. **MRR** asks "how *high* was the first relevant hit?" — `1/rank` of the first correct result, so it's all about ordering. They're complementary: you can have perfect recall but poor MRR (right answers present but buried). The **reranker improves MRR** — it adds no new candidates (recall is fixed by retrieval+fusion); it re-orders the shortlist so the most relevant rise to the top. So low recall → fix retrieval/fusion; fine recall but low MRR → fix the reranker.

**7. Bug #4: why does `similarity_search(query, k=1, filter={source_file})` return the wrong chunk when a file has many chunks?**
Because that call asks "of the chunks in this file, return the one most *similar to the query*" — a similarity search constrained to a file, not a lookup by identity. With many chunks sharing the same `source_file`, the filter narrows to the file but `k=1` still picks the most query-similar chunk, which is generally *not* the chunk whose id you wanted. With one resume, every candidate collapsed to whichever chunk best matched the query, so the reranker kept scoring the same wrong text. The fix is to fetch by exact identity — `collection.get(ids=[chunk_id])` — so content and id always correspond.

**8. Why did three of the four bugs hide instead of crashing the app?**
Because they failed *silently* behind `try/except` and produced plausible output. The dense-search bug was a method-name typo whose `AttributeError` was caught and swallowed, so "hybrid" quietly ran BM25-only. The BM25 fusion bug used synthetic ids that contributed nothing, so results were merely poorer. The fetch bug returned a real chunk, just the wrong one — output that looks valid. None threw at the top level; the system ran the whole time, just wrongly. The lesson: RAG integration bugs don't announce themselves with stack traces — they degrade quality invisibly, and only running real data through and *measuring* exposes them.

**9. Why does the eval runner exit non-zero below baseline, and where will that property be used?**
Because a non-zero exit code is the universal "fail" signal CI keys on. The runner computes recall@5 and, if below baseline (0.60), exits non-zero — turning a metric into a pass/fail gate. That's what lets it drop into GitHub Actions in **Phase F** as a regression gate: a PR that degrades retrieval below baseline fails the build and blocks the merge. It also guards an empty collection (exit 2) so you can't "pass" by testing against nothing. The exit code is the contract between measurement and automation.

**10. When job descriptions land in Phase C, what changes about how meaningful this eval is — and what would you do to the golden set?**
*(Answered per the corrected reality — see the §8 correction.)* Originally we expected Phase C to index job descriptions into the Chroma collection, growing the corpus and lifting the 6-chunk ceiling. In reality Phase C stores jobs in **SQLite**, and the gap analyzer retrieves **resume** chunks — nothing new enters the Chroma collection, which stays resume-only. So job ingestion does **not** improve this eval. The lever is the **golden set**, not jobs: add many more `(query → expected_chunk_id)` pairs and, ideally, index **multiple resumes** so the corpus is large enough that a weaker retriever actually misses relevant chunks. That expansion is slated for Phase F. (If we later wanted semantic job *search*, we'd index jobs into Chroma too — but that's a separate capability, not a fix for this eval.)
