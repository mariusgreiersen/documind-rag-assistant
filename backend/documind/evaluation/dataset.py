"""Evaluation dataset: loading, schema validation and evidence location.

Each case names its supporting evidence as verbatim text on a specific page of a
specific document. Evidence is located in the *extracted* page text, which both
verifies the dataset (a typo or a wrong page number fails loudly) and turns the
evidence into a character span that can be compared with any chunk's span.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from documind.core.config import REPO_ROOT

DEFAULT_DATASET = REPO_ROOT / "evals" / "questions.jsonl"


class Evidence(BaseModel):
    document_id: str
    page: int = Field(ge=1)
    text: str = Field(min_length=10)


class EvalCase(BaseModel):
    id: str
    question: str = Field(min_length=3)
    answerable: bool
    category: str
    difficulty: str = "medium"
    evidence: list[Evidence] = Field(default_factory=list)
    reference_answer: str
    key_facts: list[str] = Field(default_factory=list)
    forbidden_phrases: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_evidence(self) -> EvalCase:
        if self.answerable and not self.evidence:
            raise ValueError(f"{self.id}: answerable cases need evidence")
        if not self.answerable and self.evidence:
            raise ValueError(f"{self.id}: unanswerable cases must not list evidence")
        return self


def load_cases(path: Path = DEFAULT_DATASET) -> list[EvalCase]:
    cases = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(EvalCase.model_validate(json.loads(line)))
        except Exception as exc:
            raise ValueError(f"{path.name}:{line_no}: {exc}") from exc
    ids = [c.id for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate case ids: {sorted(duplicates)}")
    return cases


# --- whitespace-insensitive span search ------------------------------------------
def _normalise_with_map(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace runs to one space; map each output char to its source index."""
    out: list[str] = []
    index: list[int] = []
    pending_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            pending_space = bool(out)
            continue
        if pending_space:
            out.append(" ")
            index.append(i - 1)
            pending_space = False
        out.append(ch)
        index.append(i)
    return "".join(out), index


def find_spans(page_text: str, needle: str) -> list[tuple[int, int]]:
    """All ``(start, end)`` spans of ``needle`` in ``page_text``, ignoring whitespace differences."""
    hay, index = _normalise_with_map(page_text)
    target = " ".join(needle.split())
    spans = []
    start = hay.find(target)
    while start != -1:
        end = start + len(target)
        spans.append((index[start], index[end - 1] + 1))
        start = hay.find(target, start + 1)
    return spans


@dataclass(frozen=True)
class EvidenceSpan:
    case_id: str
    index: int
    document_id: str
    page: int
    start: int
    end: int


def locate_evidence(cases: Iterable[EvalCase], page_texts: dict[tuple[str, int], str]) -> dict[str, list[EvidenceSpan]]:
    """Resolve every evidence item to exactly one character span, or raise."""
    located: dict[str, list[EvidenceSpan]] = {}
    problems = []
    for case in cases:
        spans = []
        for i, ev in enumerate(case.evidence):
            text = page_texts.get((ev.document_id, ev.page))
            if text is None:
                problems.append(f"{case.id}[{i}]: no extracted text for {ev.document_id} page {ev.page}")
                continue
            found = find_spans(text, ev.text)
            if len(found) != 1:
                problems.append(f"{case.id}[{i}]: evidence found {len(found)} times on {ev.document_id} page {ev.page}")
                continue
            spans.append(EvidenceSpan(case.id, i, ev.document_id, ev.page, *found[0]))
        located[case.id] = spans
    if problems:
        raise ValueError("evidence could not be located:\n  " + "\n  ".join(problems))
    return located
