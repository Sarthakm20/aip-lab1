#!/usr/bin/env python3
"""Lab 3 — retrieval sweeps.

The scaffolding (corpus loading, metric computation, table printing) is
written for you. The sweeps are yours.

    python labs/lab3/search.py --baseline
    python labs/lab3/search.py --sweep chunking
    python labs/lab3/search.py --sweep retrieval
    python labs/lab3/search.py --sweep rerank
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip.chunking import STRATEGIES, Chunk  # noqa: E402
from aip.evals import retrieval_metrics  # noqa: E402
from aip.retrieval import Bm25Retriever, DenseRetriever, HybridRetriever, Retriever  # noqa: E402

CORPUS_DIR = ROOT / "data/corpus"
GOLDEN = ROOT / "data/eval/rag_golden.jsonl"


# ---------------------------------------------------------------------------
# scaffolding (provided)
# ---------------------------------------------------------------------------
def load_corpus() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(CORPUS_DIR.glob("*.md"))}


def load_questions(include_unanswerable: bool = False) -> list[dict]:
    rows = [json.loads(l) for l in GOLDEN.open(encoding="utf-8")]
    if include_unanswerable:
        return rows
    # THREE questions (Q36, Q38, Q39) have no relevant document, so recall and
    # nDCG are undefined for them -- you cannot rank correctly against an empty
    # relevant set. Dropping them leaves n = 42.
    #
    # Do not confuse that with the FIVE questions of kind 'unanswerable'
    # (Q36-Q40): two of those do keep relevant documents, because part of what
    # they ask is supported. All five are measured properly in Lab 4, as
    # refusal precision and recall.
    #
    # Excluding the three is correct -- but say so in your report rather than
    # letting an unexplained n = 42 pass for a stated 45.
    return [r for r in rows if r["relevant_docs"]]


def build_chunks(corpus: dict[str, str], strategy: str = "sliding",
                 size: int = 800, **kw) -> list[Chunk]:
    fn = STRATEGIES[strategy]
    out: list[Chunk] = []
    for doc_id, text in corpus.items():
        try:
            out.extend(fn(text, doc_id, size=size, **kw))
        except TypeError:                       # chunker without that kwarg
            out.extend(fn(text, doc_id, size=size))
    return out


def evaluate(retriever: Retriever, questions: list[dict], k: int = 10,
             reranker=None, final_k: int = 5) -> dict:
    """Run every question, return aggregate metrics + per-kind breakdown."""
    agg: dict[str, list[float]] = defaultdict(list)
    by_kind: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    latencies: list[float] = []
    per_q: dict[str, float] = {}
    per_q_mrr: dict[str, float] = {}

    for q in questions:
        t0 = time.perf_counter()
        hits = retriever.search(q["question"], k=k)
        if reranker is not None:
            hits = reranker.rerank(q["question"], hits, k=final_k)
        latencies.append((time.perf_counter() - t0) * 1000)

        # A document counts as retrieved at rank r if any of its chunks does.
        seen, ranked = set(), []
        for h in hits:
            if h.doc_id not in seen:
                seen.add(h.doc_id)
                ranked.append(h.doc_id)

        m = retrieval_metrics(ranked, q["relevant_docs"], ks=(1, 3, 5, 10))
        per_q[q["id"]] = m["hit_rate@5"]
        per_q_mrr[q["id"]] = m["mrr"]
        for key, val in m.items():
            agg[key].append(val)
            by_kind[q["kind"]][key].append(val)

    out = {k2: statistics.fmean(v) for k2, v in agg.items()}
    out["latency_p50_ms"] = statistics.median(latencies)
    out["latency_p95_ms"] = sorted(latencies)[int(0.95 * (len(latencies) - 1))]
    out["_by_kind"] = {kind: {k2: statistics.fmean(v) for k2, v in d.items()}
                       for kind, d in by_kind.items()}
    out["_per_question"] = per_q            # hit_rate@5 -- saturated, see kind_table
    out["_per_question_mrr"] = per_q_mrr    # use this one for Part B
    out["_kind_n"] = {kind: len(d["mrr"]) for kind, d in by_kind.items()}
    return out


def table(rows: dict[str, dict], cols: tuple[str, ...] =
          ("hit_rate@1", "hit_rate@5", "recall@5", "mrr", "ndcg@10",
           "latency_p95_ms")) -> str:
    name_w = max(len(n) for n in rows) + 2
    head = f"{'config':<{name_w}}" + "".join(f"{c:>15}" for c in cols)
    lines = [head, "-" * len(head)]
    for name, m in rows.items():
        lines.append(f"{name:<{name_w}}" + "".join(f"{m.get(c, 0):>15.4f}" for c in cols))
    return "\n".join(lines)


def kind_table(metrics: dict, col: str = "hit_rate@5") -> str:
    """Break a result down by question kind.

    NOTE the default column. `hit_rate@5` is saturated on this corpus -- every
    retriever scores 0.93-0.98 -- so this table will look flat and tell you
    nothing. Pass col='mrr' or col='ndcg@10' for Part B. The default is left
    saturated on purpose.
    """
    bk, counts = metrics["_by_kind"], metrics.get("_kind_n", {})
    w = max(len(k) for k in bk) + 2
    lines = [f"{'kind':<{w}}{col:>12}{'n':>6}", "-" * (w + 18)]
    for kind, m in sorted(bk.items()):
        lines.append(f"{kind:<{w}}{m.get(col, 0):>12.4f}{counts.get(kind, 0):>6}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# sweeps (yours)
# ---------------------------------------------------------------------------
def sweep_baseline() -> None:
    corpus, questions = load_corpus(), load_questions()
    chunks = build_chunks(corpus, "sliding", 800, overlap=150)
    print(f"corpus: {len(corpus)} docs -> {len(chunks)} chunks "
          f"(mean {statistics.fmean(len(c) for c in chunks):.0f} chars)")
    r = DenseRetriever(chunks)
    m = evaluate(r, questions)
    print(table({"baseline sliding-800 dense": m}))
    print()
    print(kind_table(m))
    print("\nWrite these numbers down before you change anything.")


def sweep_chunking() -> None:
    """TODO A1-A3.

    A1: all four strategies at size=800.
    A2: the winner at sizes 400 / 800 / 1600. Plot or tabulate the curve.
    A3: markdown WITH and WITHOUT the '[heading > path]' prefix.
        (Strip it with a list comprehension over the chunks -- do not modify
         aip/chunking.py; other labs depend on it.)

    Report chunk count and index build time alongside quality. A configuration
    that is 1 point better and takes 4x as long to build is a real trade-off.
    """
    import copy

    corpus, questions = load_corpus(), load_questions()
    cols = ("hit_rate@1", "recall@5", "mrr", "ndcg@10")

    def run(name: str, chunks: list[Chunk], results: dict[str, dict]) -> None:
        t0 = time.perf_counter()
        r = DenseRetriever(chunks)
        build_ms = (time.perf_counter() - t0) * 1000
        m = evaluate(r, questions)
        m["_chunk_count"] = len(chunks)
        m["_build_ms"] = build_ms
        results[name] = m

    def report(results: dict[str, dict]) -> None:
        print(table(results, cols=cols))
        print()
        for name, m in results.items():
            print(f"{name:<20} chunks={m['_chunk_count']:>5}  "
                  f"build={m['_build_ms']:>8.1f}ms")

    # --- A1: all four strategies at size=800 ---
    print("=== A1: chunking strategies @ size=800 ===\n")
    a1_results: dict[str, dict] = {}
    for strategy in STRATEGIES:
        chunks = build_chunks(corpus, strategy, 800)
        run(strategy, chunks, a1_results)
    report(a1_results)

    winner = max(a1_results, key=lambda s: a1_results[s]["ndcg@10"])
    print(f"\nWinner by ndcg@10: {winner}\n")

    # --- A2: winner at sizes 400 / 800 / 1600 ---
    print(f"=== A2: {winner} @ sizes 400/800/1600 ===\n")
    a2_results: dict[str, dict] = {}
    for size in (400, 800, 1600):
        chunks = build_chunks(corpus, winner, size)
        run(f"{winner}-{size}", chunks, a2_results)
    report(a2_results)

    # --- A3: markdown with vs without heading prefix ---
    print("\n=== A3: markdown heading prefix on/off ===\n")
    md_chunks = build_chunks(corpus, "markdown", 800)

    def strip_prefix(c: Chunk) -> Chunk:
        text = c.text
        first_line = text.split("\n", 1)[0]
        if text.startswith("[") and "] " in first_line:
            idx = text.index("] ")
            nc = copy.copy(c)
            nc.text = text[idx + 2:]
            return nc
        return c

    md_stripped = [strip_prefix(c) for c in md_chunks]

    a3_results: dict[str, dict] = {}
    run("markdown+prefix", md_chunks, a3_results)
    run("markdown-no-prefix", md_stripped, a3_results)
    print(table(a3_results, cols=("hit_rate@1", "hit_rate@5", "recall@5", "mrr", "ndcg@10")))
    print()
    for name, m in a3_results.items():
        print(f"{name:<20} chunks={m['_chunk_count']:>5}  build={m['_build_ms']:>8.1f}ms")


def sweep_retrieval() -> None:
    """TODO B1-B4.

    B1: dense / bm25 / hybrid on your best chunking.
    B2: print kind_table(m, col='mrr') for each, and pull out Q44 and Q41
        individually from metrics['_per_question_mrr'].

        USE MRR, NOT hit_rate@5. Every retriever here scores 0.93-0.98 on
        hit_rate@5, so it is saturated and shows you nothing -- which is why
        kind_table() and metrics['_per_question'] both default to it. That
        default is the trap, and noticing it is part of the lab.

    B3: RRF k in {10, 30, 60, 100} -- HybridRetriever(..., rrf_k=k).
    B4: unequal fusion weights -- HybridRetriever(..., weights=[2.0, 1.0]).
    """
    BEST_STRATEGY, BEST_SIZE = "markdown", 800

    corpus, questions = load_corpus(), load_questions()
    chunks = build_chunks(corpus, BEST_STRATEGY, BEST_SIZE)
    print(f"using chunking: {BEST_STRATEGY}-{BEST_SIZE} -> {len(chunks)} chunks\n")

    dense = DenseRetriever(chunks)
    bm25 = Bm25Retriever(chunks)
    hybrid = HybridRetriever([dense, bm25])

    # --- B1: dense / bm25 / hybrid ---
    print("=== B1: dense vs bm25 vs hybrid ===\n")
    b1_results = {
        "dense": evaluate(dense, questions),
        "bm25": evaluate(bm25, questions),
        "hybrid": evaluate(hybrid, questions),
    }
    print(table(b1_results, cols=("hit_rate@1", "hit_rate@5", "recall@5", "mrr", "ndcg@10")))

    # --- B2: per-kind MRR breakdown + Q44 / Q41 ---
    print("\n=== B2: per-kind MRR (NOT hit_rate@5 -- that's saturated) ===\n")
    for name, m in b1_results.items():
        print(f"-- {name} --")
        print(kind_table(m, col="mrr"))
        q44 = m["_per_question_mrr"].get("Q44")
        q41 = m["_per_question_mrr"].get("Q41")
        print(f"Q44 mrr={q44!r}   Q41 mrr={q41!r}\n")

    # --- B3: RRF k sweep ---
    print("=== B3: RRF k sweep ===\n")
    b3_results = {}
    for k in (10, 30, 60, 100):
        h = HybridRetriever([dense, bm25], rrf_k=k)
        b3_results[f"rrf_k={k}"] = evaluate(h, questions)
    print(table(b3_results, cols=("hit_rate@1", "hit_rate@5", "recall@5", "mrr", "ndcg@10")))

    # --- B4: unequal fusion weights ---
    print("\n=== B4: fusion weights ===\n")
    b4_results = {
        "weights=1:1": evaluate(HybridRetriever([dense, bm25], weights=[1.0, 1.0]), questions),
        "weights=2:1 (dense-heavy)": evaluate(
            HybridRetriever([dense, bm25], weights=[2.0, 1.0]), questions),
        "weights=1:2 (bm25-heavy)": evaluate(
            HybridRetriever([dense, bm25], weights=[1.0, 2.0]), questions),
    }
    print(table(b4_results, cols=("hit_rate@1", "hit_rate@5", "recall@5", "mrr", "ndcg@10")))


def sweep_rerank() -> None:
    """TODO C1-C4.

    Retrieve k=30, rerank to 5: evaluate(r, questions, k=30, reranker=rr,
    final_k=5).

    C1: CrossEncoderReranker. First run downloads ~90 MB.
    C2: LLMReranker -- report cost as well as latency.
    C3: the decision table, and TWO different deployment answers
        (interactive search box vs overnight batch). They should differ.
    C4: find a query reranking made worse, using
        metrics['_per_question_mrr'] before and after.
    """
    from aip.retrieval import CrossEncoderReranker, LLMReranker

    BEST_STRATEGY, BEST_SIZE = "markdown", 800  # from Part A

    corpus, questions = load_corpus(), load_questions()
    chunks = build_chunks(corpus, BEST_STRATEGY, BEST_SIZE)
    dense = DenseRetriever(chunks)

    cols = ("hit_rate@1", "recall@5", "mrr", "ndcg@10", "latency_p95_ms")

    print("=== baseline: retrieve k=30, no rerank (top 5 by original score) ===\n")
    no_rerank = evaluate(dense, questions, k=30, final_k=5)

    results = {"no_rerank (k=30)": no_rerank}

    print("=== C1: CrossEncoderReranker ===\n")
    ce = CrossEncoderReranker()
    ce_metrics = evaluate(dense, questions, k=30, reranker=ce, final_k=5)
    results["cross_encoder"] = ce_metrics
    print(table(results, cols=cols))

    print("\n=== C2: LLMReranker ===\n")
    llm = LLMReranker(tier="SMALL")
    t0 = time.perf_counter()
    llm_metrics = evaluate(dense, questions, k=30, reranker=llm, final_k=5)
    wall_s = time.perf_counter() - t0
    results["llm_reranker"] = llm_metrics
    print(table(results, cols=cols))
    print(f"\nllm_reranker wall time for {len(questions)} questions: {wall_s:.1f}s "
          f"({wall_s / len(questions):.2f}s/query)")
    print("Cost: report $/query x n_questions from your LLMReranker's own "
          "usage/cost accounting (tier=SMALL) -- not computed here since "
          "pricing isn't exposed to this script.")

    print("\n=== C3: decision table ===\n")
    print(table(results, cols=cols))
    print("""Two deployment answers from the SAME table:
    Interactive search box (latency-bound):
    p95 latency budget is tight (users bail past ~300-500ms). Compare
    latency_p95_ms across rows above. If cross_encoder's added latency is
    small relative to no_rerank and the ndcg@10 gain is real, ship it.
    LLMReranker is very likely disqualified here regardless of quality --
    check its p95 above against an interactive budget.

    Overnight batch (quality-bound):
    No user is waiting, so latency is nearly free. Pick whichever reranker
    has the best ndcg@10 / recall@5, even if it's LLMReranker at several
    seconds/query and nonzero $/query -- confirm the $/query x n_docs cost
    is acceptable at your real corpus/query volume before committing.
    """)

    print("=== C4: queries hurt by reranking (cross-encoder vs no-rerank) ===\n")
    before = no_rerank["_per_question_mrr"]
    after = ce_metrics["_per_question_mrr"]
    deltas = sorted(
        ((qid, after.get(qid, 0) - before.get(qid, 0)) for qid in before),
        key=lambda x: x[1],
    )
    print("worst regressions (mrr after - mrr before):")
    for qid, delta in deltas[:5]:
        print(f"  {qid}: before={before[qid]:.3f}  after={after.get(qid, 0):.3f}  "
              f"delta={delta:+.3f}")


def sweep_index() -> None:
    """TODO D1-D3.

    D1/D2: ChromaRetriever vs DenseRetriever -- recall gap and latency.
    D3: pass status metadata into the chunks and filter at query time.

        Set chunk.meta['status'] = 'archived' if 'ARCHIVED' in doc_id else 'current'
        then ChromaRetriever.search(..., where={"status": "current"}).

        Report hit_rate@1 on Q29/Q30/Q31 before and after (hit_rate@1, not
        @5 -- @5 is saturated here and will hide the whole effect).
    """
    from aip.retrieval import ChromaRetriever

    BEST_STRATEGY, BEST_SIZE = "markdown", 800  # from Part A

    corpus, questions = load_corpus(), load_questions()
    chunks = build_chunks(corpus, BEST_STRATEGY, BEST_SIZE)

    cols = ("hit_rate@1", "hit_rate@5", "recall@5", "mrr", "ndcg@10","latency_p50_ms", "latency_p95_ms")

    print("=== D1/D2: ChromaRetriever vs DenseRetriever ===\n")

    t0 = time.perf_counter()
    dense = DenseRetriever(chunks)
    dense_build_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    chroma = ChromaRetriever(chunks, reset=True)
    chroma_build_ms = (time.perf_counter() - t0) * 1000

    results = {
        "dense": evaluate(dense, questions),
        "chroma": evaluate(chroma, questions),
    }
    print(table(results, cols=cols))
    print(f"\nbuild time: dense={dense_build_ms:.1f}ms  chroma={chroma_build_ms:.1f}ms")

    gap = results["dense"]["recall@5"] - results["chroma"]["recall@5"]
    print(f"recall@5 gap (dense - chroma): {gap:+.4f}")

    print("\n=== D3: filtering archived docs via metadata ===\n")

    for c in chunks:
        c.meta["status"] = "archived" if "ARCHIVED" in c.doc_id else "current"

    chroma_filtered_base = ChromaRetriever(chunks, reset=True)

    target_ids = {"Q29", "Q30", "Q31"}
    target_qs = [q for q in questions if q["id"] in target_ids]
    if len(target_qs) < len(target_ids):
        missing = target_ids - {q["id"] for q in target_qs}
        print(f"warning: {missing} not found in loaded questions "
              f"(check load_questions() exclusions)")

    class _NoFilterWrapper:
        def __init__(self, inner):
            self.inner = inner

        def search(self, query, k=10):
            return self.inner.search(query, k=k)

    before_metrics = evaluate(_NoFilterWrapper(chroma_filtered_base), target_qs)

    class _FilteredWrapper:
        def __init__(self, inner):
            self.inner = inner

        def search(self, query, k=10):
            return self.inner.search(query, k=k, where={"status": "current"})

    after_metrics = evaluate(_FilteredWrapper(chroma_filtered_base), target_qs)

    print(f"Q29/Q30/Q31 hit_rate@1 before filter: {before_metrics['hit_rate@1']:.4f}")
    print(f"Q29/Q30/Q31 hit_rate@1 after  filter: {after_metrics['hit_rate@1']:.4f}")
    print("\nper-question (before -> after):")
    for qid in sorted(target_ids):
        b = before_metrics["_per_question"].get(qid)
        a = after_metrics["_per_question"].get(qid)
        print(f"  {qid}: {b!r} -> {a!r}")


SWEEPS = {
    "chunking": sweep_chunking,
    "retrieval": sweep_retrieval,
    "rerank": sweep_rerank,
    "index": sweep_index,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--sweep", choices=list(SWEEPS))
    args = ap.parse_args()
    if args.baseline or not args.sweep:
        sweep_baseline()
    if args.sweep:
        SWEEPS[args.sweep]()


if __name__ == "__main__":
    main()
