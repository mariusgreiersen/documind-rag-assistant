"""Validation of model-produced citations against the retrieved context.

The model may only cite reference IDs (S1, S2, ...) that were assigned to the
passages it was given. Every marker in the answer text is checked:

* valid markers are renumbered to ``[1]``, ``[2]``, ... in order of first use and
  mapped to citations built from *backend* metadata (title, page, text), never
  from anything the model wrote;
* unknown markers are removed and reported, never displayed;
* an "answered" response without a single valid citation is downgraded to
  insufficient evidence, because an uncited claim cannot be verified.

A valid marker proves only that the cited passage was in the context, not that
it supports the sentence. Support is measured separately in the evaluation.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from documind.generation.prompts import INSUFFICIENT_EVIDENCE_MESSAGE, SourcePassage

# [S1], [S1, S3], [S1; S3], [ s2 ]
_MARKER = re.compile(r"\[\s*([Ss]\d+(?:\s*[,;]\s*[Ss]\d+)*)\s*\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class RawAnswer:
    """Structured output as returned by the LLM (untrusted)."""

    status: str
    answer: str
    cited_source_ids: list[str] = field(default_factory=list)
    unsupported_aspects: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValidatedCitation:
    number: int
    source: SourcePassage


@dataclass(frozen=True)
class ValidatedAnswer:
    status: str
    answer: str
    citations: list[ValidatedCitation]
    unsupported_aspects: list[str]
    rejected_citation_ids: list[str]
    downgraded: bool
    downgrade_reason: str | None
    citation_coverage: float  # fraction of factual sentences carrying >= 1 valid marker


def _normalise_id(raw: str) -> str:
    return raw.strip().upper()


def sentence_citation_coverage(text: str) -> float:
    """Share of sentences that contain at least one rendered citation marker.

    A heuristic: headings, list intros and other short fragments count as
    sentences too, so 1.0 is not always reachable for good answers.
    """
    sentences = [s for s in _SENTENCE_SPLIT.split(text) if len(s.strip()) > 20]
    if not sentences:
        return 0.0
    cited = sum(1 for s in sentences if re.search(r"\[\d+\]", s))
    return round(cited / len(sentences), 3)


def validate_answer(raw: RawAnswer, sources: Sequence[SourcePassage]) -> ValidatedAnswer:
    by_id = {s.ref_id.upper(): s for s in sources}
    numbering: dict[str, int] = {}
    rejected: list[str] = []

    def number_for(ref: str) -> int:
        if ref not in numbering:
            numbering[ref] = len(numbering) + 1
        return numbering[ref]

    def replace(match: re.Match[str]) -> str:
        refs = [_normalise_id(r) for r in re.split(r"[,;]", match.group(1))]
        rendered = []
        for ref in refs:
            if ref in by_id:
                n = number_for(ref)
                marker = f"[{n}]"
                if marker not in rendered:
                    rendered.append(marker)
            elif ref not in rejected:
                rejected.append(ref)
        return "".join(rendered)

    status = raw.status if raw.status in {"answered", "partially_answered", "insufficient_evidence"} else "answered"
    text = _MARKER.sub(replace, raw.answer or "").strip()
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)  # tidy spaces left by removed markers

    listed = [_normalise_id(r) for r in raw.cited_source_ids]
    for ref in listed:
        if ref not in by_id and ref not in rejected:
            rejected.append(ref)

    # The model listed valid sources but placed no inline markers: attach them at the end
    # so that the answer is still traceable, rather than silently dropping them.
    if not numbering and status != "insufficient_evidence":
        valid_listed = [r for r in dict.fromkeys(listed) if r in by_id]
        if valid_listed:
            text = text + " " + "".join(f"[{number_for(r)}]" for r in valid_listed)

    citations = [ValidatedCitation(number=n, source=by_id[ref]) for ref, n in sorted(numbering.items(), key=lambda kv: kv[1])]

    downgraded, reason = False, None
    if status in {"answered", "partially_answered"} and not citations:
        status, text, downgraded, reason = "insufficient_evidence", INSUFFICIENT_EVIDENCE_MESSAGE, True, "no_valid_citations"
    if status == "insufficient_evidence" and not text:
        text = INSUFFICIENT_EVIDENCE_MESSAGE

    return ValidatedAnswer(
        status=status,
        answer=text,
        citations=citations,
        unsupported_aspects=[a for a in raw.unsupported_aspects if a.strip()],
        rejected_citation_ids=rejected,
        downgraded=downgraded,
        downgrade_reason=reason,
        citation_coverage=sentence_citation_coverage(text) if citations else 0.0,
    )
