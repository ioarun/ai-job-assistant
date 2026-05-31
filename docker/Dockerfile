# syntax=docker/dockerfile:1.7

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ─── OS deps ──────────────────────────────────────────────────────
# - python3 + pip: runtime
# - curl: install uv
# - libgl1 / libglib2.0-0: required by unstructured / pdf2image
# - poppler-utils: pdftoppm, used by pdf2image
# - tesseract-ocr: used by unstructured for OCR fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        curl \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        poppler-utils \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# ─── uv (fast pip) ────────────────────────────────────────────────
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# ─── Python deps ──────────────────────────────────────────────────
WORKDIR /workspace

# Copy requirements first so dep install caches independent of source code.
COPY requirements.txt /workspace/requirements.txt
RUN uv pip install --system -r /workspace/requirements.txt

# ─── App source ───────────────────────────────────────────────────
COPY . /workspace

# ─── Runtime config ───────────────────────────────────────────────
# 8000 = FastAPI
# 8501 = Streamlit (Phase G)
# 8888 = Jupyter (notebook exploration)
EXPOSE 8000 8501 8888

# Default command — overridden by docker-compose for streamlit/jupyter.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
