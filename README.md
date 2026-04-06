# AI Job Application Assistant
Helps you tailor your application for the next AI job.

A system that helps users:

* Upload their resume
* Paste a job description
* Get:
  * Resume improvements
  * Skill gap analysis
  * Tailored cover letter
  * Interview questions

## Core features:
1. Input
Upload resume (PDF)
Paste job description
2. Processing (THIS is the important part)
Parse resume text
Chunk + embed both resume + job description
Store in vector DB (FAISS)
3. Output (via LLM)
Skill gap analysis
Resume improvement suggestions
Tailored bullet points
Cover letter generation

## Tech stack:
Backend
* Python + FastAPI

LLM
* OpenAI API (GPT-4 / GPT-4o)

RAG
* FAISS (local, simple)
* LangChain or LlamaIndex

Parsing
* PyMuPDF or pdfplumber

Optional UI
* Streamlit (fastest)   
* OR Gradio (more customizable)

## Architecture:
```
User Input
   ↓
PDF Parser (resume)
   ↓
Text Chunking
   ↓
Embeddings (OpenAI)
   ↓
FAISS Vector Store
   ↓
Retriever
   ↓
LLM (Prompt + Context)
   ↓
Response (analysis, cover letter, etc.)
```

## GitHub Repo Structure:
```ai-job-assistant/
│
├── app/
│   ├── main.py                # FastAPI entrypoint
│   ├── api/
│   │   └── routes.py         # API endpoints
│   │
│   ├── core/
│   │   ├── config.py         # env variables
│   │   ├── logger.py         # logging setup
│   │
│   ├── services/
│   │   ├── llm_service.py    # OpenAI calls
│   │   ├── rag_service.py    # retrieval logic
│   │   ├── embedding.py      # embedding logic
│   │
│   ├── utils/
│   │   ├── pdf_parser.py     # resume parsing
│   │   ├── chunking.py       # text chunking
│   │
│   └── models/
│       └── schemas.py        # request/response schemas
│
├── data/
│   └── vector_store/         # FAISS index (local)
│
├── notebooks/
│   └── experimentation.ipynb # optional (for testing ideas)
│
├── tests/
│   └── test_api.py
│
├── .env
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── README.md
└── run.sh

