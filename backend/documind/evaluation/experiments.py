"""Compare retrieval configurations on the same benchmark.

    python -m documind.evaluation.experiments

Every configuration indexes the demo corpus from scratch in its own temporary
workspace and is scored with the same questions and evidence spans. Results are
reported three ways: ranking quality (with a random-ranking baseline), evidence
recall at an equal context budget, and indexing/query cost.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

from documind.core.config import default_query_prefix, get_settings
from documind.core.logging import configure_logging
from documind.evaluation.dataset import DEFAULT_DATASET, EvalCase, load_cases
from documind.evaluation.harness import (
    RetrievalConfig,
    environment_info,
    eval_workspace,
    evaluate_retrieval,
    locate,
    random_baseline,
    recall_at_token_budget,
    summarize_retrieval,
)
from documind.evaluation.run import RESULTS_DIR

BGE = "BAAI/bge-small-en-v1.5"
BGE_PREFIX = default_query_prefix(BGE)
MINILM = "sentence-transformers/all-MiniLM-L6-v2"

CONFIGS = [
    RetrievalConfig("A: MiniLM, small chunks", MINILM, "", 128, 16),
    RetrievalConfig("B: MiniLM 250", MINILM, "", 250, 30),
    RetrievalConfig("C: MiniLM 500 (truncated)", MINILM, "", 500, 60),
    RetrievalConfig("D: multi-qa MiniLM 250", "sentence-transformers/multi-qa-MiniLM-L6-cos-v1", "", 250, 30),
    RetrievalConfig("E: BGE-small 250", BGE, BGE_PREFIX, 250, 30),
    RetrievalConfig("F: BGE-small 500", BGE, BGE_PREFIX, 500, 60),
    RetrievalConfig("G: BGE-small 250, no query prefix", BGE, "", 250, 30),
]

# Approximate amount of passage text handed to the LLM; used for the equal-budget comparison.
CONTEXT_BUDGET_TOKENS = 2500
K_MAX = 20


def is_default(cfg: RetrievalConfig, default: RetrievalConfig) -> bool:
    keys = ("embedding_model", "query_prefix", "chunk_size", "chunk_overlap")
    return all(getattr(cfg, k) == getattr(default, k) for k in keys)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m documind.evaluation.experiments")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    configure_logging("WARNING", "text")

    settings = get_settings()
    default = RetrievalConfig.from_settings(settings)
    cases = load_cases(args.dataset)
    spans = locate(cases, settings)
    env = environment_info()
    results: list[dict[str, Any]] = []

    for cfg in CONFIGS:
        print(f"Running {cfg.name} ...", flush=True)
        with eval_workspace(cfg, settings) as (container, ingest_s):
            started = time.perf_counter()
            rows = evaluate_retrieval(container, cases, spans, k_max=K_MAX)
            query_ms = (time.perf_counter() - started) * 1000 / len(cases)
            summary = summarize_retrieval(rows)
            budget_k, budget_recall = recall_at_token_budget(rows, cfg.chunk_size, CONTEXT_BUDGET_TOKENS)
            baseline = random_baseline(container, cases, spans)
            max_input = container.embedder.max_input_tokens
            results.append(
                {
                    "config": cfg.name,
                    "default": is_default(cfg, default),
                    "embedding_model": cfg.embedding_model,
                    "query_prefix": bool(cfg.query_prefix),
                    "max_seq_length": container.embedder.max_seq_length,
                    "max_input_tokens": max_input,
                    "chunk_size": cfg.chunk_size,
                    "chunk_overlap": cfg.chunk_overlap,
                    "truncated": cfg.chunk_size > max_input,
                    "chunks": baseline["corpus_chunks"],
                    "hit@1": summary["hit@1"],
                    "mrr@10": summary["mrr@10"],
                    "hit@5": summary["hit@5"],
                    "random_hit@5": baseline["random_hit@5"],
                    "evidence_recall@5": summary["evidence_recall@5"],
                    "budget_k": budget_k,
                    "evidence_recall@budget": budget_recall,
                    "ingest_s": round(ingest_s, 2),
                    "query_ms": round(query_ms, 1),
                }
            )
        r = results[-1]
        print(f"   chunks={r['chunks']} hit@1={r['hit@1']} mrr={r['mrr@10']} recall@budget(k={budget_k})={budget_recall}", flush=True)

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "experiments.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    payload = {"environment": env, "context_budget_tokens": CONTEXT_BUDGET_TOKENS, "results": results}
    (args.out / "experiments.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    (args.out / "experiments.md").write_text(render(results, env, cases), encoding="utf-8", newline="\n")
    print(f"Wrote {args.out / 'experiments.md'}")
    return 0


def render(results: list[dict[str, Any]], env: dict[str, str], cases: list[EvalCase]) -> str:
    n_ans = sum(c.answerable for c in cases)

    def name(r: dict[str, Any]) -> str:
        return f"**{r['config']}** (default)" if r["default"] else r["config"]

    lines = [
        "# Retrieval experiments",
        "",
        f"Generated by `python -m documind.evaluation.experiments` at {env['timestamp_utc']} "
        f"(Python {env['python']}, {env['platform']}, CPU, torch {env['torch']}).",
        f"Every configuration indexes the same demo corpus from scratch and answers the same {len(cases)} questions "
        f"({n_ans} answerable). One question is worth {1 / n_ans:.3f} on the answerable-question metrics, so differences "
        "of one or two questions are within noise for a benchmark of this size. Retrieval metrics are deterministic: "
        "repeated runs produce identical values.",
        "",
        "## 1. Ranking quality",
        "",
        "Hit@1 and MRR measure how high the first relevant passage ranks. *Random Hit@5* is the expected Hit@5 if chunks "
        "were ranked at random. With few, large chunks it is high, so Hit@5 alone says little on this corpus.",
        "",
        "| Config | Model | Chunk / overlap | Chunks | Hit@1 | MRR@10 | Hit@5 | Random Hit@5 | Evidence recall@5 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        trunc = " ⚠" if r["truncated"] else ""
        model = r["embedding_model"].split("/")[-1] + (" + prefix" if r["query_prefix"] else "")
        lines.append(
            f"| {name(r)} | `{model}` | {r['chunk_size']} / {r['chunk_overlap']}{trunc} | {r['chunks']} | {r['hit@1']:.3f} | "
            f"{r['mrr@10']:.3f} | {r['hit@5']:.3f} | {r['random_hit@5']:.3f} | {r['evidence_recall@5']:.3f} |"
        )
    lines += [
        "",
        f"## 2. Evidence recall at an equal context budget (~{CONTEXT_BUDGET_TOKENS} tokens)",
        "",
        "The LLM reads a bounded amount of retrieved text. Comparing recall@5 across chunk sizes favours large chunks "
        f"because five large chunks contain more text. Here each configuration retrieves K = {CONTEXT_BUDGET_TOKENS} / chunk size "
        "passages, so every configuration hands the model about the same amount of text.",
        "",
        "| Config | K | Evidence recall@K |",
        "|---|---|---|",
    ]
    lines += [f"| {name(r)} | {r['budget_k']} | {r['evidence_recall@budget']:.3f} |" for r in results]
    lines += [
        "",
        "## 3. Cost",
        "",
        "Single runs on a shared Windows laptop (CPU). Timings of identical configurations varied by more than 2x between "
        "runs, so treat them as rough orders of magnitude only.",
        "",
        "| Config | Max input tokens | Index time (s) | Query time (ms) |",
        "|---|---|---|---|",
    ]
    lines += [f"| {name(r)} | {r['max_input_tokens']} | {r['ingest_s']:.1f} | {r['query_ms']:.1f} |" for r in results]
    lines += [
        "",
        "⚠ truncated: the chunk size exceeds the tokens the model embeds (`max_seq_length` minus [CLS]/[SEP]), so the end of "
        "each chunk is never embedded. The application refuses this configuration at startup; it is included only to "
        "measure the effect.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
