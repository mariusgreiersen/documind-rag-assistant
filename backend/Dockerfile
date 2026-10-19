# syntax=docker/dockerfile:1
# Build context: repository root (the image needs data/demo and evals next to the backend).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf-cache

WORKDIR /app/backend

# CPU-only PyTorch keeps the image ~2 GB smaller than the default CUDA build.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install dependencies in their own layer so source changes do not reinstall them.
COPY backend/pyproject.toml ./
RUN mkdir documind && touch documind/__init__.py \
    && pip install . \
    && pip uninstall -y documind && rm -rf documind build *.egg-info

# Bake the embedding model into the image: no download at container start, works offline.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

COPY backend/documind ./documind
RUN pip install --no-deps .

COPY data/demo /app/data/demo
COPY evals /app/evals

RUN useradd --create-home --uid 10001 documind \
    && mkdir -p /app/data/runtime \
    && chown -R documind:documind /app/data/runtime
USER documind

ENV DATA_DIR=/app/data/runtime \
    EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    HF_HUB_OFFLINE=1 \
    LOG_FORMAT=json

EXPOSE 8000
# The first start loads PyTorch and the model and indexes the demo corpus, which took about
# two minutes on a laptop under Docker Desktop, so allow a generous start period.
HEALTHCHECK --interval=15s --timeout=5s --start-period=300s --start-interval=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "documind.main:app", "--host", "0.0.0.0", "--port", "8000"]
