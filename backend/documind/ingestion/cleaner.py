"""Text normalisation for extracted PDF pages.

Cleaning is applied per page, before chunking, so page boundaries (and therefore
page citations) can never be lost here. The rules are deliberately conservative:
they repair common extraction artefacts but do not try to reconstruct layout.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK = re.compile(r"([a-z])-\n([a-z])")
# Horizontal whitespace, including no-break, thin and zero-width spaces (U+00A0, U+2000-U+200B,
# U+202F, U+205F, U+3000). Built from code points to keep invisible characters out of the source.
_SPACE_CODEPOINTS = (0x20, 0x09, 0xA0, *range(0x2000, 0x200C), 0x202F, 0x205F, 0x3000)
_HSPACE = re.compile("[" + re.escape("".join(map(chr, _SPACE_CODEPOINTS))) + "]+")
_SOFT_HYPHEN = chr(0xAD)
_DIGITS = re.compile(r"\d+")


def normalize_page_text(raw: str) -> str:
    """Return cleaned page text with single spaces and one line per text line.

    - NFKC normalisation folds ligatures ("fi" ligature -> "fi") and full-width forms.
    - Soft hyphens and control characters are removed.
    - A hyphen at a line end between two lowercase letters is treated as a word
      split by line wrapping ("distri-" + newline + "buted" -> "distributed"). This is a
      heuristic: a genuine hyphenated compound broken at its hyphen loses the hyphen.
    - Runs of horizontal whitespace collapse to one space; blank lines are dropped.
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    text = text.replace(_SOFT_HYPHEN, "").replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    lines = (_HSPACE.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def collapse_whitespace(text: str) -> str:
    """Single-line form used for matching passages against other text."""
    return " ".join(text.split())


def _line_signature(line: str) -> str:
    """Comparison key for a line. Short lines such as "Page 3 of 9" differ only by their
    numbers, so numbers are ignored there; longer lines must repeat exactly, so that
    content rows like "Revenue 2024: 48.2" are never mistaken for page furniture."""
    key = line.strip().lower()
    return _DIGITS.sub("#", key) if len(key) <= 25 else key


def remove_repeated_lines(pages: Sequence[str], *, min_pages: int = 3, min_fraction: float = 0.6, max_line_chars: int = 80) -> list[str]:
    """Drop short lines that repeat on most pages: running headers, footers and page numbers.

    Only applies to documents with at least ``min_pages`` pages containing text, and
    only to lines no longer than ``max_line_chars``, so real content that happens to
    repeat (for example a recurring sentence) is unlikely to be removed.
    """
    text_pages = [p for p in pages if p]
    if len(text_pages) < min_pages:
        return list(pages)
    counts: Counter[str] = Counter()
    for page in text_pages:
        counts.update({_line_signature(line) for line in page.split("\n") if 0 < len(line) <= max_line_chars})
    threshold = max(min_pages, int(len(text_pages) * min_fraction + 0.5))
    repeated = {sig for sig, n in counts.items() if n >= threshold}
    if not repeated:
        return list(pages)
    return ["\n".join(line for line in page.split("\n") if _line_signature(line) not in repeated) for page in pages]
