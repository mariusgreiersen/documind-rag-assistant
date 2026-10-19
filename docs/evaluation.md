# Evaluation

DocuMind's retrieval is measured, not assumed. Everything here is reproducible:

```bash
cd backend
python -m documind.evaluation.run            # baseline report  -> evals/results/retrieval_baseline.{md,json}
python -m documind.evaluation.experiments    # configuration comparison -> evals/results/experiments.{md,csv,json}
python -m documind.evaluation.run --answers  # + answer-level checks (needs LLM_API_KEY; not run here)
```

Each run indexes the bundled demo corpus into a throwaway workspace through the
production `DocumentService`, then queries it through the production `Retriever`
and `AnswerService`. Retrieval metrics are deterministic: repeated runs produced
identical values.

## Dataset

[`evals/questions.jsonl`](../evals/questions.jsonl) contains **36 hand-written
questions** over the five demo documents:

| Category | n | Purpose |
|---|---|---|
| direct | 9 | One fact, close to the wording of the source |
| multi_passage | 5 | Needs two passages from the same document |
| multi_document | 3 | Needs passages from two different documents |
| conflicting | 1 | The documents disagree (Northwind's handbook vs. the study guide) |
| paraphrase | 4 | Different vocabulary from the source |
| noisy | 3 | The question contains irrelevant words |
| scalability | 3 | Topic-style questions |
| unanswerable (off-topic) | 2 | Nothing in the corpus is related |
| unanswerable (on-topic) | 5 | Related passages exist, but the asked fact does not (e.g. 2028 revenue) |
| unanswerable (injection) | 1 | Asks for the secret API key that the injection document mentions |

Every answerable case lists its **evidence**: a document ID, a page number and a
verbatim sentence from that page, plus a reference answer and key facts.

**Evidence is verified, not trusted.** At load time each evidence sentence is located
in the *extracted* page text, ignoring whitespace differences. A typo or wrong page
number makes the evaluation (and a CI test) fail. The located character span is then
compared with each retrieved chunk's span. A chunk is **relevant** if it is on the
same document and page and covers at least 50% of an evidence span. Relevance is
therefore defined independently of the chunking configuration, so the same dataset
scores any chunk size.

I wrote the documents and the questions, so the reference answers were checked
against my own sources. The obvious caveat is that the author of a benchmark knows
its documents. Paraphrase and noisy questions were written to reduce lexical
overlap, but this is a small, author-made benchmark, not an independent test set.

## Metrics

Computed over the 28 answerable questions:

* **Hit@K** (Recall@K, any relevant): 1 if at least one relevant chunk is in the top K.
* **Evidence recall@K** (Recall@K, all evidence): the fraction of a question's
  evidence items covered by the top K, so a two-passage question with one passage
  found scores 0.5.
* **Full coverage@K**: every evidence item is in the top K.
* **Precision@K**: relevant chunks in the top K divided by K. Most questions have one
  or two relevant chunks, so the attainable maximum is far below 1 for K ≥ 3.
* **MRR@10**: mean reciprocal rank of the first relevant chunk.
* **Random Hit@K**: the expected Hit@K if chunks were ranked at random,
  `1 − C(N−r, K) / C(N, K)` for N chunks of which r are relevant. With a small corpus,
  a high Hit@5 is easy, so this baseline is reported next to it.

## Baseline results

Configuration: `BAAI/bge-small-en-v1.5` with its query instruction, 500-token chunks,
60-token overlap, 22 chunks in the corpus. From
[`retrieval_baseline.md`](../evals/results/retrieval_baseline.md):

| K | Hit@K | Random Hit@K | Evidence recall@K | Precision@K |
|---|---|---|---|---|
| 1 | 0.714 | 0.055 | 0.661 | 0.714 |
| 3 | 0.893 | 0.163 | 0.857 | 0.333 |
| 5 | 1.000 | 0.267 | 0.964 | 0.229 |
| 10 | 1.000 | 0.510 | 1.000 | 0.121 |

MRR@10 = **0.823**; full evidence coverage@5 = **0.929** (26 of 28 questions have
every required passage in the top 5).

**How to read this.** Retrieval is far better than chance at every K, and the
first relevant passage is ranked first for 20 of 28 questions. But the corpus has
only 22 chunks, so the top 5 covers 23% of it. Hit@5 = 1.000 is not a claim about
large collections, where these numbers would be lower.

## Configuration experiments

Seven configurations, the same questions, from
[`experiments.md`](../evals/results/experiments.md):

| Config | Model | Chunk / overlap | Chunks | Hit@1 | MRR@10 | Evidence recall @ ~2,500 tokens |
|---|---|---|---|---|---|---|
| A | all-MiniLM-L6-v2 | 128 / 16 | 94 | 0.607 | 0.744 | 0.982 (K=20) |
| B | all-MiniLM-L6-v2 | 250 / 30 | 47 | 0.750 | 0.846 | 0.982 (K=10) |
| C | all-MiniLM-L6-v2 | 500 / 60, **truncated** | 22 | 0.643 | 0.769 | 0.893 (K=5) |
| D | multi-qa-MiniLM-L6-cos-v1 | 250 / 30 | 47 | 0.714 | 0.810 | 0.964 (K=10) |
| E | bge-small-en-v1.5 + prefix | 250 / 30 | 47 | 0.786 | 0.850 | 0.929 (K=10) |
| **F (default)** | bge-small-en-v1.5 + prefix | 500 / 60 | 22 | 0.714 | 0.823 | 0.964 (K=5) |
| G | bge-small-en-v1.5, no prefix | 250 / 30 | 47 | 0.821 | 0.868 | 0.929 (K=10) |

The last column compares configurations **at the same amount of retrieved text**
(about 2,500 tokens, the context the model reads). Comparing recall@5 directly would
favour large chunks, because five large chunks simply contain more text.

**Findings.**

1. **Silent truncation costs recall.** With the same model and the same context
   budget, 500-token chunks embedded by MiniLM (which only sees the first 254 tokens)
   reach 0.893 evidence recall against 0.982 for 250-token chunks. This is why the
   application refuses chunk sizes above the model's input length.
2. **Very small chunks rank worst.** At 128 tokens, Hit@1 drops to 0.607 and MRR to
   0.744. Recall at an equal budget is still high, but only because K = 20.
3. **The remaining configurations are not separable on this benchmark.** One
   question is worth 0.036. B, D, E, F and G differ by one to three questions on any
   metric, and the ranking changes depending on the metric. Even the effect of BGE's
   query instruction flipped: it helped at rank 1 before the header/footer cleaning
   was added and slightly hurt afterwards (E vs. G).

**Why F is the default.** Answers are generated from the top-5 passages
(`DEFAULT_TOP_K=5`). F has the best evidence recall and full coverage at K = 5,
uses a chunk size in the commonly recommended 400–600-token range, and has 10 tokens
of headroom below bge-small's 510-token input. The trade-off is precision: on these
demo documents a page holds about 450–500 tokens, so a 500-token chunk is roughly a
page. Citations stay exact at page level, but the highlighted passage covers most of
the page. **B (MiniLM, 250-token chunks, top-K 10) is an equally good choice** by
these numbers, with a smaller model and tighter passages. The benchmark is too small
to prefer one over the other with confidence.

## Relevance gate calibration

The gate skips generation when the best passage's cosine similarity is below
`MIN_RELEVANCE_SCORE`. Measured top-1 similarities with the default configuration:

| | Lowest | Highest |
|---|---|---|
| Answerable questions | 0.613 | 0.866 |
| Off-topic unanswerable (World Cup, rye bread) | 0.457 | 0.468 |
| On-topic unanswerable, incl. the injection question (2028 revenue, Raft benchmarks, …) | 0.653 | 0.829 |

The threshold **0.55** sits between off-topic questions and the lowest answerable
one. On this benchmark the gate rejects 2 of 8 unanswerable questions (both
off-topic) and wrongly blocks 0 of 28 answerable ones. The on-topic unanswerable
questions overlap completely with answerable ones, so **no similarity threshold can
separate them**. Declining those is the job of the model's instructions and the
citation validator. Thresholds are model-specific: with MiniLM, off-topic questions
scored about 0.1, so the same calibration had to be redone after switching models.

## Failure analysis

* **q18, conflicting sources:** all five passages come from the concurrency study
  guide, so Northwind's contradicting claim never reaches the model, and the system
  cannot report the disagreement. Diversity-aware retrieval (MMR, or a per-document
  quota) would address this.
* **q16, multi-document:** the Northwind billing passage is found at rank 5; the
  study-guide passage explaining serialization failures is not in the top 5.
* **q11 and q12, paraphrases:** a neighbouring chunk on the right topic outranks the
  chunk holding the evidence (rank 4 in both cases).
* **q03:** "When is a log entry committed?" ranks the page about *safety* (which
  mentions committed entries many times) above the page with the definition. Dense
  retrieval favours topical similarity over the exact defining sentence; hybrid
  lexical + vector search or a cross-encoder reranker would likely help.

## Answer-level evaluation (implemented, not run)

`--answers` generates an answer for every question with the configured LLM and
reports:

* **answerability accuracy:** answered vs. declined, compared with the label;
* **citation validity rate:** valid markers / (valid + rejected);
* **cited-evidence precision:** the share of citations whose chunk overlaps the
  annotated evidence;
* **key-fact recall:** a keyword heuristic, not a correctness measure;
* **forbidden-phrase violations:** for example "1 billion" from the injected text;
* a Markdown file with every answer and an empty *Reviewer verdict* field for manual
  groundedness review.

These checks are deterministic and unit-tested, but **no answer-level results are
reported**: no LLM API key was available when this project was built, and I have not
substituted fabricated or simulated numbers. With a key, run
`python -m documind.evaluation.run --answers` and the opt-in live tests
(`DOCUMIND_LIVE_LLM_TESTS=1 pytest -m live_llm`).

## Limitations of this evaluation

* 36 questions over 5 short documents; differences of a few percentage points are noise.
* The question author also wrote the documents.
* Relevance at 50% evidence overlap is a reasonable but arbitrary threshold.
* Timings come from single runs on a shared laptop and varied by more than 2x.
* No held-out set: the default configuration and the gate threshold were chosen on
  the same questions they are reported on.
