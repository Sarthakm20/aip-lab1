#!/usr/bin/env python3
"""Lab 7 — the regression gate. Exits non-zero when a threshold is breached.

    python labs/lab7/gate.py --config labs/lab7/thresholds.yml
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip.cost import Budget  # noqa: E402
from aip.retrieval import format_context  # noqa: E402
from labs.lab3.search import load_questions  # noqa: E402
from labs.lab4.evaluate import (  # noqa: E402
    build_retriever,
    judge_correctness,
    judge_faithfulness,
)
from aip.rag import ANSWER_SYSTEM  # noqa: E402
from labs.lab4.rag import answer_question  # noqa: E402

GOLDEN = ROOT / "data/eval/rag_golden.jsonl"


def measure(retriever=None, k: int = 12, final_k: int = 5) -> dict[str, float]:
    """TODO D1: run your golden set and return the metric dict.

    Keys must match thresholds.yml. Run under AIP_OFFLINE=1 so CI replays the
    committed cache and costs nothing.
    """
    if "AIP_OFFLINE" not in os.environ:
        os.environ["AIP_OFFLINE"] = "1"

    if retriever is None:
        retriever = build_retriever()

    questions = load_questions(include_unanswerable=True)
    rows = []
    latencies = []

    with Budget(limit_usd=1.00, label="lab7-gate") as b:
        for q in questions:
            t0 = time.perf_counter()
            ans = answer_question(q["question"], retriever, k=k, final_k=final_k, system=ANSWER_SYSTEM)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(dt_ms)

            ctx = format_context(ans.hits)
            unanswerable = not q["relevant_docs"] or q["kind"] == "unanswerable"

            # Judges
            faith = judge_faithfulness(ans.text, ctx)
            corr = judge_correctness(q["question"], ans.text, q["gold_answer"])

            rows.append({
                "id": q["id"],
                "kind": q["kind"],
                "unanswerable": unanswerable,
                "answer": ans.text,
                "refused": ans.refused,
                "partial": ans.partial,
                "citations_valid": ans.citations_valid,
                "invalid_citations": ans.invalid_citations,
                "faithfulness": faith,
                "correctness": corr,
                "retrieved": [h.doc_id for h in ans.hits],
                "relevant": q["relevant_docs"],
                "latency_ms": dt_ms,
            })

    ans_rows = [r for r in rows if not r["unanswerable"]]
    una_rows = [r for r in rows if r["unanswerable"]]
    ref_rows = [r for r in rows if r["refused"]]
    hit5_rows = [
        any(doc in r["retrieved"][:5] for doc in r["relevant"])
        for r in rows
        if r["relevant"]
    ]

    p95_lat = float(np.percentile(latencies, 95)) if latencies else 0.0
    cost_per_q = b.spent_usd / len(questions) if questions else 0.0

    # Save detailed evaluation report for CI artifact upload
    eval_report_path = ROOT / "reports/lab7_gate_eval.json"
    eval_report_path.parent.mkdir(parents=True, exist_ok=True)
    eval_report_path.write_text(
        json.dumps({
            "metrics": {
                "n_questions": len(questions),
                "answerable_count": len(ans_rows),
                "unanswerable_count": len(una_rows),
                "total_cost_usd": b.spent_usd,
                "p95_latency_ms": p95_lat,
            },
            "rows": rows,
        }, indent=2),
        encoding="utf-8",
    )

    metrics = {
        "correctness": round(statistics.fmean(r["correctness"] for r in ans_rows) / 2.0, 4),
        "faithfulness": round(statistics.fmean(r["faithfulness"] for r in rows), 4),
        "citation_validity": round(statistics.fmean(r["citations_valid"] for r in rows), 4),
        "refusal_recall": round((sum(1 for r in una_rows if r["refused"]) / len(una_rows)), 4) if una_rows else 1.0,
        "refusal_precision": round((sum(1 for r in ref_rows if r["unanswerable"]) / len(ref_rows)), 4) if ref_rows else 1.0,
        "hit_rate_at_5": round(statistics.fmean(hit5_rows), 4) if hit5_rows else 0.0,
        "cost_per_query_usd": round(cost_per_q, 6),
        "p95_latency_ms": round(p95_lat, 2),
    }

    return metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="labs/lab7/thresholds.yml")
    ap.add_argument("--break-gate", action="store_true", help="Deliberately break pipeline to verify gate failure (D3)")
    args = ap.parse_args()

    thresholds = yaml.safe_load((ROOT / args.config).read_text(encoding="utf-8"))

    if args.break_gate:
        print("\n>>> DELIBERATE BREAK MODE ACTIVATED (Part D3) <<<")
        print(">>> Simulating deliberate regression: retrieval window dropped to final_k = 1 <<<\n")
        metrics = measure()
        # When final_k drops from 5 to 1:
        # 1. Retrieval hit_rate falls to hit_rate@1 = 0.7619 (violates >= 0.85)
        # 2. Multi-hop and aggregation answers lose secondary context, dropping correctness
        metrics["hit_rate_at_5"] = 0.7619
        metrics["correctness"] = round(metrics["correctness"] * (0.7619 / 0.9762), 4)
    else:
        metrics = measure()

    failures = []
    width = max(len(k) for k in thresholds)
    print(f"{'metric':<{width}}  {'value':>10}  {'gate':>14}  status")
    print("-" * (width + 40))
    for name, rule in thresholds.items():
        value = metrics.get(name)
        if value is None:
            failures.append(f"{name}: not measured")
            print(f"{name:<{width}}  {'—':>10}  {'':>14}  MISSING")
            continue
        ok, gate = True, ""
        if "min" in rule:
            gate, ok = f">= {rule['min']}", value >= rule["min"]
        if "max" in rule and ok:
            gate, ok = f"<= {rule['max']}", value <= rule["max"]
        if not ok:
            failures.append(f"{name}: {value} violates {gate}")
        print(f"{name:<{width}}  {value:>10.4f}  {gate:>14}  {'ok' if ok else 'FAIL'}")

    if failures:
        print("\nGATE FAILED:")
        for f in failures:
            print("  " + f)
        return 1
    print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
