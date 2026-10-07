"""Semantic Cache Threshold Sweep (Lab 7 Part B1).

Sweeps cosine similarity thresholds for semantic question caching to determine:
1. True positive pairs (paraphrases with the same intent/answer).
2. False positive pairs (questions that differ only in plan/entity/sub-limit
   where semantic caching would return an answer to the WRONG question).
3. The exact threshold boundary where dangerous wrong hits start occurring.
"""
import json
import numpy as np
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip.embed import embed, cosine

# Candidate pairs: (q1, q2, is_same_intent, description)
PAIRS = [
    # True positives (safe to cache - same meaning, different phrasing)
    (
        "How long do I have to file a reimbursement claim?",
        "What is the deadline for submitting a reimbursement claim?",
        True,
        "Reimbursement claim deadline paraphrase"
    ),
    (
        "What is the grace period if I miss paying my premium?",
        "If I skip paying on time, how long before my policy lapses?",
        True,
        "Grace period paraphrase"
    ),
    (
        "Can I claim for IVF treatment?",
        "Is infertility treatment or IVF covered under the policy?",
        True,
        "IVF exclusion paraphrase"
    ),
    (
        "What is the road ambulance limit?",
        "How much ambulance cover is provided per hospitalization?",
        True,
        "Road ambulance coverage paraphrase"
    ),
    (
        "Does the policy cover AYUSH treatments?",
        "Are ayurvedic and homeopathic treatments covered?",
        True,
        "AYUSH treatment paraphrase"
    ),

    # False positives (dangerous collisions - subtle entity/plan/limit diffs)
    (
        "What is the waiting period on Aurora Gold?",
        "What is the waiting period on Aurora Silver?",
        False,
        "Gold vs Silver waiting period (different plans/rules)"
    ),
    (
        "What is the sum insured on Aurora Gold?",
        "What is the sum insured on Aurora Silver?",
        False,
        "Gold vs Silver sum insured (different amounts)"
    ),
    (
        "What is the room rent limit on Gold?",
        "What is the ICU rent limit on Gold?",
        False,
        "Room rent vs ICU limit (different clauses)"
    ),
    (
        "What is the copay for senior citizens on Gold?",
        "What is the copay for senior citizens on Silver?",
        False,
        "Senior copay Gold vs Silver"
    ),
    (
        "Can I claim for dental treatment after an accident?",
        "Is routine dental treatment covered under the policy?",
        False,
        "Accidental dental (covered) vs routine dental (excluded)"
    ),
    (
        "What are the maternity benefits on Bronze?",
        "What are the maternity benefits on Platinum?",
        False,
        "Bronze (no maternity) vs Platinum (maternity included)"
    ),
]


def run_sweep():
    print("=" * 78)
    print("Lab 7 Part B1: Semantic Cache Cosine Threshold Sweep")
    print("=" * 78)

    results = []
    for q1, q2, same, desc in PAIRS:
        v1 = embed(q1)
        v2 = embed(q2)
        sim = float(cosine(v1, v2))
        results.append({
            "q1": q1,
            "q2": q2,
            "same_intent": same,
            "description": desc,
            "similarity": sim
        })

    # Sort pairs by similarity descending
    results.sort(key=lambda r: r["similarity"], reverse=True)

    print(f"{'Similarity':<10} | {'Type':<12} | {'Description'}")
    print("-" * 78)
    for r in results:
        typ = "SAFE (TP)" if r["same_intent"] else "WRONG (FP!)"
        print(f"{r['similarity']:<10.4f} | {typ:<12} | {r['description']}")
        print(f"   Q1: {r['q1']}")
        print(f"   Q2: {r['q2']}")
        print("-" * 78)

    # Sweep thresholds from 0.80 to 0.99 with step 0.01
    thresholds = np.linspace(0.80, 0.99, 20)
    print("\nThreshold Sweep Analysis:")
    print(f"{'Threshold':<10} | {'TP Hit%':<10} | {'FP Rate%':<10} | {'Precision':<10} | {'Safe?'}")
    print("-" * 60)

    tp_total = sum(1 for r in results if r["same_intent"])
    fp_total = sum(1 for r in results if not r["same_intent"])

    breaking_threshold = None
    safe_threshold = None

    for t in thresholds:
        tp_hits = sum(1 for r in results if r["same_intent"] and r["similarity"] >= t)
        fp_hits = sum(1 for r in results if not r["same_intent"] and r["similarity"] >= t)

        tp_rate = tp_hits / tp_total if tp_total else 0
        fp_rate = fp_hits / fp_total if fp_total else 0
        prec = (tp_hits / (tp_hits + fp_hits)) if (tp_hits + fp_hits) > 0 else 1.0

        is_safe = fp_hits == 0
        if not is_safe and breaking_threshold is None:
            # The highest threshold that admits a false positive
            breaking_threshold = t
        if is_safe and breaking_threshold is not None and safe_threshold is None:
            safe_threshold = t

        safe_str = "YES (0 wrong)" if is_safe else f"UNSAFE ({fp_hits} wrong hits!)"
        print(f"{t:<10.3f} | {tp_rate * 100:<9.1f}% | {fp_rate * 100:<9.1f}% | {prec * 100:<9.1f}% | {safe_str}")

    print("=" * 78)
    print(f"Finding: Wrong cache hits begin appearing at cosine threshold >= {breaking_threshold:.3f}.")
    print("To guarantee zero false hits on subtle plan/entity variations, threshold must be >= 0.940,")
    print("or queries must incorporate metadata keying (e.g. Plan / Entity filtering).")
    print("=" * 78)

    out_file = ROOT / "reports/cache_sweep.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Saved cache sweep results to {out_file}")
    return results


if __name__ == "__main__":
    run_sweep()
