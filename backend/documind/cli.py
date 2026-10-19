"""Command-line utilities that operate on the same workspace as the API.

    python -m documind.cli seed-demo           index the bundled demo documents
    python -m documind.cli ingest FILE.pdf     upload and index a PDF
    python -m documind.cli list                list documents
    python -m documind.cli chunks DOC_ID       print a document's chunks
    python -m documind.cli search "query"      semantic search (no LLM)
    python -m documind.cli ask "question"      grounded answer (uses the configured LLM)
    python -m documind.cli reindex             re-index everything after changing model/chunking

Stop the API server before running write commands against the same data directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from documind.container import build_container
from documind.core.config import get_settings
from documind.core.errors import DocuMindError
from documind.core.logging import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="documind")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-demo")
    sub.add_parser("list")
    sub.add_parser("reindex")
    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("path", type=Path)
    p_chunks = sub.add_parser("chunks")
    p_chunks.add_argument("document_id")
    for name in ("search", "ask"):
        p = sub.add_parser(name)
        p.add_argument("query")
        p.add_argument("--top-k", type=int, default=5)
        p.add_argument("--document", action="append", dest="document_ids")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    settings = get_settings()
    configure_logging("WARNING", "text")
    c = build_container(settings)
    try:
        if args.command == "seed-demo":
            for r in c.documents.seed_demo():
                print(f"{r.id:28s} {r.status.value:10s} {r.page_count:>3d} pages {r.chunk_count:>4d} chunks  {r.title}")
        elif args.command == "list":
            for r in c.documents.list_documents():
                print(f"{r.id:28s} {r.status.value:10s} {r.page_count:>3d} pages {r.chunk_count:>4d} chunks  {r.title}")
        elif args.command == "ingest":
            r = c.documents.upload(args.path.read_bytes(), args.path.name)
            print(f"{r.id} {r.status.value} pages={r.page_count} chunks={r.chunk_count}")
        elif args.command == "chunks":
            for ch in c.documents.chunks(args.document_id):
                print(f"--- {ch.chunk_id}  page {ch.page_number}  chars {ch.char_start}-{ch.char_end}\n{ch.text}\n")
        elif args.command == "search":
            scope = c.documents.search_scope(args.document_ids)
            result = c.retriever.search(args.query, document_ids=scope, top_k=args.top_k)
            for i, ch in enumerate(result.chunks, 1):
                print(f"[{i}] score={ch.score:.3f}  {ch.title} — page {ch.page_number}  ({ch.chunk_id})")
                print("    " + " ".join(ch.text.split())[:300] + "\n")
        elif args.command == "ask":
            outcome = c.answers.answer(args.query, document_ids=args.document_ids, top_k=args.top_k)
            print(f"status: {outcome.status}")
            if outcome.notice:
                print(f"notice: {outcome.notice}")
            if outcome.answer:
                print(f"\n{outcome.answer}\n")
            for cit in outcome.citations:
                print(f"[{cit.number}] {cit.source.chunk.title} — page {cit.source.chunk.page_number}")
            print("\ndiagnostics: " + json.dumps(outcome.diagnostics, default=str))
        elif args.command == "reindex":
            for r in c.documents.reindex_all():
                print(f"{r.id:28s} {r.status.value:10s} {r.chunk_count:>4d} chunks")
    except DocuMindError as exc:
        print(f"error ({exc.code}): {exc.message}", file=sys.stderr)
        return 1
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
