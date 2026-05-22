# AI Job Application Assistant - 2-Day Sprint Plan (Full Features)

**Status:** Ready to Build  
**Duration:** 2 days (16-18 hours)  
**Start Date:** 2026-05-22  
**Target Completion:** 2026-05-23 (EOD)  
**Owner:** Arun  

---

## 🎯 FULL MVP SCOPE - ALL FEATURES

### Core Features ✅ (All Included)
1. ✅ Resume upload & PDF parsing
2. ✅ **Job search (Adzuna API)**
3. ✅ **RAG pipeline (LangChain + FAISS + OpenAI embeddings)**
4. ✅ Skill gap analysis (RAG-powered LLM)
5. ✅ Cover letter generation
6. ✅ Interview questions generation
7. ✅ Streamlit UI (multi-step workflow)
8. ✅ **SQLite persistence** (sessions, history, embeddings cache)
9. ✅ **Docker containerization**
10. ✅ **GitHub Actions CI/CD**

### Optimized for Speed (Not Skipped)
- ❌ Comprehensive test suite (add later, basic smoke tests only)
- ❌ Multi-user auth (single session MVP)
- ❌ Production logging (basic logging only)
- ❌ Resume update recommendations (cover letter + gap analysis sufficient)

---

## 📐 Full Architecture (Optimized for 2-Day Build)

```
┌─────────────────────────────────────────────────────────┐
│              Streamlit UI (Multi-Step)                   │
│  ✓ Upload Resume → Extract & embed                      │
│  ✓ Search Jobs (Adzuna API) → Select job               │
│  ✓ Analyze Gap (RAG + LLM) → Show results              │
│  ✓ Generate Cover Letter & Interview Q&A              │
│  ✓ View/Export Results & Session History              │
└──────────────┬────────────────────────────────────────┘
               │
┌──────────────▼────────────────────────────────────────┐
│          FastAPI Backend (RESTful APIs)               │
│  • POST /upload (resume PDF)                          │
│  • POST /search-jobs (query params from resume)       │
│  • POST /analyze-gap (resume + job)                  │
│  • POST /generate-cover-letter                        │
│  • POST /generate-interview-questions                 │
│  • GET  /sessions/{id}/history                       │
│  • GET  /health                                      │
└──────────────┬────────────────────────────────────────┘
               │
┌──────────────▼────────────────────────────────────────┐
│     Services Layer (LangChain-Powered)                │
│  ├─ pdf_parser.py (PyMuPDF → text)                   │
│  ├─ embedding_service.py (OpenAI embeddings)         │
│  ├─ rag_service.py (LangChain orchestration)         │
│  ├─ job_search_service.py (Adzuna API)               │
│  ├─ llm_service.py (OpenAI + prompt templates)       │
│  ├─ db_service.py (SQLite queries)                   │
│  └─ content_generators.py (cover letter, Q&A)        │
└──────────────┬────────────────────────────────────────┘
               │
┌──────────────▼────────────────────────────────────────┐
│     Data Layer (Persistence)                          │
│  ├─ FAISS Index (local file-based)                   │
│  │  └─ Resume chunks + embeddings                    │
│  │  └─ Job descriptions + embeddings                 │
│  │                                                   │
│  ├─ SQLite Database                                  │
│  │  ├─ users (session data)                          │
│  │  ├─ resumes (parsed text, metadata)              │
│  │  ├─ jobs (from Adzuna, cached)                   │
│  │  ├─ analyses (gap analysis results)              │
│  │  └─ generated_content (cover letters, Q&A)       │
│  │                                                   │
│  └─ Temp Storage (PDF uploads)                       │
└──────────────┬────────────────────────────────────────┘
               │
┌──────────────▼────────────────────────────────────────┐
│     External APIs                                     │
│  ├─ OpenAI (embeddings + GPT-4)                      │
│  └─ Adzuna Job API (real job listings)               │
└─────────────────────────────────────────────────────┘

[Docker Container] + [GitHub Actions CI/CD]
```

---

## 📋 Directory Structure (Final)

```
ai-job-assistant/
│
├── app/
│   ├── __init__.py
│   ├── main.py                           # FastAPI entry
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py                     # All endpoints
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── pdf_parser.py                 # PDF → text
│   │   ├── embedding_service.py          # OpenAI embeddings
│   │   ├── rag_service.py                # LangChain + FAISS
│   │   ├── job_search_service.py         # Adzuna API
│   │   ├── llm_service.py                # OpenAI calls
│   │   ├── db_service.py                 # SQLite ORM
│   │   └── content_generators.py         # Cover letter, Q&A
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                     # .env config
│   │   ├── logger.py                     # Basic logging
│   │   └── constants.py                  # Prompt templates
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── schemas.py                    # Pydantic models
│   │   └── db_models.py                  # SQLAlchemy ORM
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── file_handler.py               # PDF upload
│   │   └── text_chunking.py              # For FAISS
│   │
│   └── db/
│       ├── __init__.py
│       ├── database.py                   # SQLite connection
│       └── init_db.py                    # Schema setup
│
├── streamlit_app/
│   ├── app.py                            # Multi-page Streamlit
│   ├── pages/
│   │   ├── 1_Upload_Resume.py
│   │   ├── 2_Search_Jobs.py
│   │   ├── 3_Analyze_Gap.py
│   │   ├── 4_Cover_Letter.py
│   │   └── 5_Interview_Prep.py
│   └── utils.py                          # UI helpers
│
├── prompts/
│   ├── gap_analysis.txt
│   ├── cover_letter.txt
│   └── interview_prep.txt
│
├── data/
│   ├── vector_store/                     # FAISS index
│   └── sessions/                         # SQLite DB
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                       # pytest fixtures
│   ├── test_pdf_parser.py
│   ├── test_job_search.py
│   └── test_e2e.py                       # Smoke tests only
│
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
│
├── .github/
│   └── workflows/
│       ├── lint.yml                      # Black + Ruff
│       ├── tests.yml                     # pytest
│       └── build.yml                     # Docker build
│
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── run.sh
```

---

## 📅 DAY 1 TIMELINE (8 hours)

### Hours 1-2: Foundation Setup
**Goal:** Project skeleton, dependencies, config

- [ ] Create FastAPI main.py with health check
- [ ] Setup config.py (.env variables)
- [ ] Create requirements.txt (all deps)
- [ ] Initialize SQLite database schema
- [ ] Create Streamlit app structure

**Stack to Install:**
```
fastapi, uvicorn, streamlit
openai, langchain, faiss-cpu
PyMuPDF, pdfplumber, requests
sqlalchemy, python-dotenv
```

**Deliverable:** Running FastAPI server + Streamlit app (empty)

---

### Hours 2-4: PDF Parsing + Embeddings Setup
**Goal:** Parse resume, create FAISS index, test embeddings

- [ ] Implement pdf_parser.py (PyMuPDF)
- [ ] Create embedding_service.py (OpenAI embeddings)
- [ ] Create text_chunking.py (split text for FAISS)
- [ ] Initialize FAISS vector store (local file)
- [ ] Test with sample resume

**Deliverable:** Can upload resume → extract text → create embeddings → store in FAISS

---

### Hours 4-6: Job Search API + Database
**Goal:** Integrate Adzuna, cache jobs in SQLite

- [ ] Implement job_search_service.py (Adzuna API client)
- [ ] Create db_models.py (SQLAlchemy ORM for jobs)
- [ ] Create /search-jobs endpoint
- [ ] Test Adzuna API integration

**Deliverable:** Can search jobs by keywords, results cached in SQLite

---

### Hours 6-8: RAG Pipeline
**Goal:** Connect resume embeddings to job descriptions

- [ ] Implement rag_service.py (LangChain orchestration)
- [ ] Create retriever (FAISS + resume embeddings)
- [ ] Setup LangChain pipeline (embed jobs + retrieve relevant resume sections)
- [ ] Test end-to-end RAG flow

**Deliverable:** RAG pipeline working: resume chunks retrieved based on job description

---

## 📅 DAY 2 TIMELINE (8 hours)

### Hours 1-3: LLM Integration + Skill Gap
**Goal:** Connect OpenAI to RAG, analyze gaps

- [ ] Implement llm_service.py (OpenAI API calls)
- [ ] Create gap_analyzer (uses RAG + LLM)
- [ ] Create /analyze-gap endpoint
- [ ] Write skill gap prompt template
- [ ] Test with real data

**Deliverable:** API endpoint that returns structured skill gap analysis

---

### Hours 3-5: Content Generators
**Goal:** Cover letter + interview questions

- [ ] Implement content_generators.py
- [ ] Create /generate-cover-letter endpoint
- [ ] Create /generate-interview-questions endpoint
- [ ] Write prompt templates
- [ ] Store results in SQLite

**Deliverable:** All 3 content generation endpoints working

---

### Hours 5-7: Streamlit UI Integration
**Goal:** Multi-page Streamlit connecting to FastAPI

- [ ] Create Streamlit pages (5-page workflow)
- [ ] Page 1: Upload resume
- [ ] Page 2: Search jobs (call /search-jobs)
- [ ] Page 3: View gap analysis (call /analyze-gap)
- [ ] Page 4: View cover letter (call /generate-cover-letter)
- [ ] Page 5: View interview questions
- [ ] Add download functionality

**Deliverable:** Full end-to-end UI workflow

---

### Hours 7-8: Docker + CI/CD
**Goal:** Containerize app, setup GitHub Actions

- [ ] Create Dockerfile (Python 3.10 + deps)
- [ ] Create docker-compose.yml (FastAPI + Streamlit)
- [ ] Setup GitHub Actions workflow (lint + test + build)
- [ ] Test Docker build locally

**Deliverable:** Docker image builds, can run full app in container

---

## 🛠️ Tech Stack (Precise)

```
Backend Framework
├── FastAPI 0.104+
├── Uvicorn 0.24+
└── Pydantic 2.0+

LLM & RAG
├── OpenAI SDK 1.0+
├── LangChain 0.1+
├── FAISS-CPU 1.7+ (or GPU if available)
└── OpenAI Embeddings (3-small or 3-large)

Data & Parsing
├── PyMuPDF (fitz) 1.23+
├── pdfplumber 0.10+
└── SQLAlchemy 2.0+

Frontend
├── Streamlit 1.28+
├── Streamlit-session-state (for persistence)
└── Requests (for API calls)

Job API
├── Adzuna API (via requests)

DevOps
├── Docker 24+
├── docker-compose 2.0+
├── GitHub Actions (workflows)

Development
├── Black (formatting)
├── Ruff (linting)
├── pytest (testing)
└── python-dotenv (config)
```

---

## ✅ Daily Checklist

### Day 1 End Goals
- [ ] ✅ FastAPI + Streamlit running
- [ ] ✅ PDF parsing working
- [ ] ✅ FAISS vector store initialized
- [ ] ✅ Adzuna API integration complete
- [ ] ✅ SQLite database working
- [ ] ✅ RAG pipeline functional
- [ ] **END OF DAY 1:** All infrastructure ready, backend 80% done

### Day 2 End Goals
- [ ] ✅ /analyze-gap endpoint working
- [ ] ✅ /generate-cover-letter endpoint working
- [ ] ✅ /generate-interview-questions endpoint working
- [ ] ✅ Streamlit UI fully integrated
- [ ] ✅ End-to-end workflow tested
- [ ] ✅ Docker image builds
- [ ] ✅ GitHub Actions CI/CD working
- [ ] ✅ Basic smoke tests passing
- [ ] **END OF DAY 2:** Production-ready MVP, fully containerized

---

## 🎬 Verification (Testing Your Build)

### Smoke Test Checklist
```bash
# 1. Start backend
uvicorn app.main:app --reload

# 2. Start Streamlit (new terminal)
streamlit run streamlit_app/app.py

# 3. Test workflow
  - Upload sample_resume.pdf
  - Verify text extraction
  - Search for "AI Engineer" jobs
  - Select a job
  - Analyze skill gap → verify results
  - Generate cover letter → verify output
  - Generate interview questions → verify 5+ questions
  - Download results

# 4. Test Docker
docker-compose up --build
# Verify both services running
```

---

## 🚨 Speed Hacks (How We Do This in 2 Days)

1. **Reuse LangChain Abstractions** - Don't build RAG from scratch
2. **Simple Prompt Templates** - No complex few-shot learning yet
3. **Mock Data Ready** - Have 2-3 sample resumes + jobs pre-prepared
4. **Direct SQLite** - No migrations, just SQLAlchemy auto-create
5. **GitHub Actions Templates** - Use marketplace actions (lint, test, build)
6. **Streamlit Components** - Use built-in widgets, minimal custom CSS
7. **Minimal Error Handling** - Focus on happy path first
8. **No Optimization Yet** - Ship MVP, optimize in Phase 2

---

## 📊 Feature Comparison

| Component | Details | Status |
|-----------|---------|--------|
| **Resume Upload** | PDF → text extraction | Day 1 |
| **FAISS + Embeddings** | Vector store + OpenAI embeddings | Day 1 |
| **Adzuna API** | Real job search | Day 1 |
| **RAG Pipeline** | LangChain retrieval | Day 1 |
| **Skill Gap Analysis** | LLM + RAG | Day 2 Hour 1-3 |
| **Cover Letter** | LLM generation | Day 2 Hour 3-5 |
| **Interview Q&A** | LLM generation | Day 2 Hour 3-5 |
| **Streamlit UI** | Multi-page workflow | Day 2 Hour 5-7 |
| **SQLite DB** | Persistence | Day 1 |
| **Docker** | Containerization | Day 2 Hour 7-8 |
| **CI/CD** | GitHub Actions | Day 2 Hour 7-8 |

---

## 📦 Prerequisites (You Need)

1. **OpenAI API Key**
   - Sign up: https://platform.openai.com
   - Budget: $5-10 for testing
   - Models: gpt-4, text-embedding-3-small

2. **Adzuna API Key**
   - Sign up: https://developer.adzuna.com
   - Free tier: 300 requests/month (enough for testing)

3. **Local Environment**
   - Python 3.10+
   - ~2GB disk (for FAISS + db)
   - Docker installed (for final step)

---

## 🚀 Execution Commands

```bash
# Day 1 Start
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env
cat > .env << EOF
OPENAI_API_KEY=your_key_here
ADZUNA_APP_ID=your_app_id
ADZUNA_API_KEY=your_api_key
DATABASE_URL=sqlite:///./data/app.db
FAISS_PATH=./data/vector_store/
EOF

# Test backend
uvicorn app.main:app --reload

# Day 2 - Test Streamlit (new terminal)
streamlit run streamlit_app/app.py

# Day 2 End - Test Docker
docker-compose up --build
```

---

## 📝 API Endpoints (Final)

```
POST   /upload                          # Upload resume PDF
POST   /search-jobs                     # Search jobs (Adzuna)
POST   /analyze-gap                     # Skill gap analysis (RAG + LLM)
POST   /generate-cover-letter          # Generate cover letter
POST   /generate-interview-questions   # Generate interview Q&A
GET    /sessions/{id}/history          # Get user session history
GET    /health                          # Health check
GET    /docs                            # Auto-generated API docs
```

---

## 🎯 Definition of Done

App is "Done" when:
- ✅ Can upload PDF resume
- ✅ Can search real jobs (Adzuna API)
- ✅ Can analyze skill gaps (RAG + LLM)
- ✅ Can generate cover letter
- ✅ Can generate 5+ interview questions
- ✅ Full workflow runs in Streamlit UI
- ✅ Results persist in SQLite
- ✅ Docker image builds and runs
- ✅ GitHub Actions CI/CD passes
- ✅ No crashes or unhandled errors
- ✅ README documents setup

---

**Next Step:** Provide OpenAI API key and confirm Adzuna credentials, then we BEGIN BUILDING! 🚀

---

**Prepared:** 2026-05-22  
**Build Starts:** [AWAITING YOUR GO SIGNAL]  
**Target Completion:** 2026-05-23 EOD  
**Owner:** Arun
