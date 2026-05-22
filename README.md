# AI Job Application Assistant - Phase 1 Setup Complete ✅

## 🐳 Quick Start with Docker (Recommended)

### Prerequisites
- Docker installed
- docker-compose installed

### One-Command Start
```bash
chmod +x run.sh
./run.sh
```

Or manually:
```bash
docker-compose build
docker-compose up
```

The application will be available at:
- **API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs
- **Streamlit UI:** http://localhost:8501

### Stop the Application
```bash
docker-compose down
```

---

## 🖥️ Alternative: Local Setup (Without Docker)

### Prerequisites
- Python 3.10+
- pip

### Installation

**Step 1: Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

**Step 2: Install dependencies**
```bash
pip install -r requirements.txt
```

**Step 3: Initialize database**
```bash
python app/db/init_db.py
```

**Step 4: Run FastAPI server**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at: http://localhost:8000

**Step 5: Open API docs**
Visit: http://localhost:8000/docs

**Step 6: Run Streamlit (in another terminal)**
```bash
streamlit run streamlit_app/app.py
```

The UI will be available at: http://localhost:8501

---

## 📋 Phase 1 Status

✅ **Foundation Setup Complete:**
- FastAPI skeleton
- SQLite database models
- Pydantic schemas
- Environment configuration
- Streamlit app structure

### Files Created:
```
app/
├── __init__.py
├── main.py (FastAPI entry)
├── core/
│   ├── config.py (settings)
│   ├── logger.py
│   └── constants.py (prompt templates)
├── db/
│   ├── database.py (SQLAlchemy)
│   ├── db_models.py (ORM models)
│   └── init_db.py (schema init)
├── models/
│   └── schemas.py (Pydantic)
├── api/
│   └── routes.py (API stubs)
├── services/
│   └── __init__.py
└── utils/
    └── __init__.py

streamlit_app/
└── app.py (UI skeleton)

requirements.txt
.env (empty keys)
.gitignore
```

---

## 🔄 Next Steps (Phase 1 Continued)

### Hours 2-4: PDF Parsing + Embeddings
- [ ] pdf_parser.py (PyMuPDF)
- [ ] embedding_service.py (OpenAI)
- [ ] text_chunking.py
- [ ] FAISS initialization

### Hours 4-6: Job Search + Database
- [ ] job_search_service.py (Adzuna)
- [ ] /search-jobs endpoint
- [ ] SQLite job caching

### Hours 6-8: RAG Pipeline
- [ ] rag_service.py (LangChain)
- [ ] FAISS retriever setup
- [ ] Test end-to-end RAG

---

## 📝 Environment Variables

See `.env` file. Currently set to empty strings:
```
OPENAI_API_KEY=""
ADZUNA_APP_ID=""
ADZUNA_API_KEY=""
```

Add your actual keys when ready.

---

## 🧪 Testing

### Health Check
```bash
curl http://localhost:8000/health
```

Should return:
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

**Status:** Phase 1 (Hours 1-2) ✅ Complete  
**Duration:** 2 days  
**Last Updated:** 2026-05-22
