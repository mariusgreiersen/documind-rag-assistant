from __future__ import annotations

import hashlib
import io
import math
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from documind.container import Container, build_container
from documind.core.config import REPO_ROOT, Settings
from documind.generation.llm_provider import LLMProvider, MockLLMProvider
from documind.main import create_app

WORD = re.compile(r"\w+|[^\w\s]")


# --- PDF builders ---------------------------------------------------------------
def make_pdf(pages: list[str], *, title: str | None = None) -> bytes:
    """A text-based PDF with one string per page (wrapped at ~90 characters)."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4, invariant=1)
    if title:
        c.setTitle(title)
    for text in pages:
        y = 800
        c.setFont("Helvetica", 10)
        for paragraph in text.split("\n"):
            line = ""
            for word in paragraph.split():
                if len(line) + len(word) > 90:
                    c.drawString(50, y, line)
                    y -= 14
                    line = ""
                line = f"{line} {word}".strip()
            if line:
                c.drawString(50, y, line)
                y -= 14
        c.showPage()
    c.save()
    return buffer.getvalue()


def make_image_only_pdf(pages: int = 2) -> bytes:
    """Pages with drawings but no text, like a scanned document."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4, invariant=1)
    for _ in range(pages):
        c.rect(50, 50, 400, 600, fill=1)
        c.showPage()
    c.save()
    return buffer.getvalue()


def encrypt_pdf(data: bytes, user_password: str) -> bytes:
    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(user_password=user_password, owner_password="owner-secret", algorithm="AES-256")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def pdf_factory() -> Callable[..., bytes]:
    return make_pdf


# --- Deterministic fake embedder --------------------------------------------------
class HashingEmbedder:
    """Bag-of-words feature hashing. Deterministic and dependency-free, so tests that
    exercise the pipeline do not need to download a model. Lexical overlap stands in
    for semantic similarity."""

    def __init__(self, dimension: int = 256, max_seq_length: int = 256) -> None:
        self._dimension = dimension
        self._max_seq_length = max_seq_length

    @property
    def model_id(self) -> str:
        return "test/hashing-embedder"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def max_seq_length(self) -> int:
        return self._max_seq_length

    @property
    def max_input_tokens(self) -> int:
        return self._max_seq_length - 2

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        return [m.span() for m in WORD.finditer(text)]

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        for word in re.findall(r"\w+", text.lower()):
            if len(word) < 3:
                continue
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            vec[h % self._dimension] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


# --- Settings, containers, app ----------------------------------------------------
@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        data_dir=tmp_path / "data",
        demo_dir=REPO_ROOT / "data" / "demo",
        llm_provider="none",
        log_format="text",
        log_level="WARNING",
        chunk_size_tokens=64,
        chunk_overlap_tokens=8,
        min_chunk_tokens=4,
        min_relevance_score=0.05,
    )


@pytest.fixture
def make_container(settings: Settings, embedder: HashingEmbedder) -> Iterator[Callable[..., Container]]:
    created: list[Container] = []

    def factory(llm: LLMProvider | None = None, **overrides: object) -> Container:
        s = settings.model_copy(update=overrides) if overrides else settings
        c = build_container(s, embedder=embedder, llm=llm)
        created.append(c)
        return c

    yield factory
    for c in created:
        c.close()


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture
def make_client(settings: Settings, embedder: HashingEmbedder) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def factory(llm: LLMProvider | None = None, **overrides: object) -> TestClient:
        s = settings.model_copy(update=overrides) if overrides else settings
        app = create_app(s, container_factory=lambda st: build_container(st, embedder=embedder, llm=llm))
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


SAMPLE_PAGES = [
    "Raft is a consensus algorithm. A log entry is committed once the leader has replicated it on a majority of servers. "
    "Leaders send heartbeats using AppendEntries messages that carry no entries.",
    "Caching reduces latency. Cache-aside is the most common pattern: the application reads the cache first and loads "
    "from the database on a miss. A cache stampede happens when many requests miss at once.",
    "Optimistic concurrency control validates transactions before commit. Pessimistic concurrency control uses locks "
    "such as two-phase locking to prevent conflicts.",
]


@pytest.fixture
def sample_pdf() -> bytes:
    return make_pdf(SAMPLE_PAGES, title="Systems Notes")
