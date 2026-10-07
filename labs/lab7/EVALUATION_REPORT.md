# Evaluation Report — Aurora Policy Assistant
**Lab 7 Capstone Deliverable · AI in Practice (Module 1)**  
*Authors: Sarthak Monga · System: Aurora Policy Assistant v1.0 · October 2026*  
*Repository: https://github.com/Sarthakm20/aip-lab1 · CI: https://github.com/Sarthakm20/aip-lab1/actions*

---

## 1. What It Does

The Aurora Policy Assistant is an automated customer service system that answers policyholders' questions about health and travel insurance coverage, claim filing deadlines, waiting periods, and exclusions. Instead of having customers read through 30 dense policy PDFs or wait on hold for an agent, the assistant searches Aurora's official contract documents and writes a clear, concise answer citing the exact policy sections that support each statement. When a customer asks about something not covered in the documents—such as an unlisted benefit or an unstated rate—the assistant explicitly declines to answer rather than guessing or fabricating terms.

---

## 2. How Well It Works

Evaluated on the 45-question golden benchmark (`data/eval/rag_golden.jsonl`), comprising 40 answerable queries across 5 difficulty types and 5 unanswerable queries under `AIP_OFFLINE=1` using committed cache `.aip_cache/calls.sqlite3`. Live latencies are recorded live over network calls to Gemini 3.7 Flash (n=20), while CI gate replay latency is measured deterministically from cache (n=45).

| Evaluation Metric | Baseline (Lab 4 Harness)* | Final Service (Serving Only) | Target / SLO | Gate Rule | Status |
|---|---|---|---|---|---|
| **Answer Correctness (Answerable, n=40)** | 0.7625 (61/80 pts) | **0.7625** (61/80 pts) | >= 0.750 | min 0.750 | **PASS** |
| **Faithfulness to Context (n=45)** | 1.0000 (45/45) | **1.0000** (45/45) | >= 0.900 | min 0.900 | **PASS** |
| **Citation Validity (All Queries)** | 1.0000 (45/45) | **1.0000** (45/45) | 1.000 | min 0.980 | **PASS** |
| **Refusal Recall (Unanswerable, n=5)** | 1.0000 (5/5) | **1.0000** (5/5) | >= 0.800 | min 0.800 | **PASS** |
| **Refusal Precision (Refusals, n=8)** | 0.6250 (5/8) | **0.6250** (5/8) | >= 0.600 | min 0.600 | **PASS** |
| **Retrieval Hit Rate @ 5 (Relevant, n=42)** | 0.9762 (41/42) | **0.9762** (41/42) | >= 0.850 | min 0.850 | **PASS** |
| **Retrieval nDCG @ 10 (Relevant, n=42)** | 0.8458 | **0.8458** | >= 0.800 | — | **PASS** |
| **Cost per Query (Uncached Live)** | $0.0080* | **$0.00128** | <= $0.010 | max 0.010 | **PASS** |
| **p95 Latency (Cached / Uncached Live)** | — / 4,310 ms | **0.16 ms / 4,285 ms** | <= 800 / 6,000 ms | max 6000 | **PASS** |
| **Streaming TTFT (Live / Cached Replay)** | — | **1,180 ms / 15.0 ms** | <= 1,500 ms | — | **PASS** |

*\*Note on Denominators, Latency Provenance & Cost Breakdown:*
1. **Scoring Denominators:** Correctness evaluates 40 answerable questions on a 0–2 scale (max 80 points; 61/80 = 0.7625). Retrieval hit rate evaluates the 42 questions that specify ground-truth `relevant_docs` (41/42 = 0.9762; 2 unanswerable questions still reference background policy context).
2. **Latency Provenance:** Uncached p95 (4,285 ms) and TTFT (1,180 ms) are recorded live timings over network calls to Gemini 3.7 Flash. Deterministic CI replay under `AIP_OFFLINE=1` runs in 9.7 ms from `.aip_cache/calls.sqlite3`.
3. **Cost Reconciliation:** Lab 4 baseline ($0.0080) measured the full evaluation harness: $0.00128 base serving + $0.00470 judge overhead (correctness & faithfulness judges on tier=LARGE consuming ~1,770 prompt and ~270 output tokens at $1.50/$9.00 per 1M) + $0.00202 (estimated) multi-candidate sweep runs and retries in `evaluate.py`. Lab 7 excludes judges at runtime, costing purely $0.00128/query.

---

## 3. Where It Fails

Across 40 answerable questions (80 possible points), the system scored **61/80 (0.7625)**, with exactly **16 non-perfect responses** (losing 19 points):

1. **False Refusals Induced by Distractors (Mode 4 — Worst for User Utility): 3 cases (loss of 6 pts).**  
   *Questions:* Q20 (family floater rules), Q23 (Bronze OPD cover), Q44 (product code `AUR-HI-SIL-2026`) (each scored 0/2).  
   *Mechanism:* Answerable queries where the gold chunk was retrieved in the top 5 (ranks 2–4), but adjacent distractor chunks triggered excessive conservatism, causing a complete refusal. On demo day, we highlight this as the single worst failure because a false refusal gives users zero utility and forces an expensive support call.
2. **Secondary Caveat Omission (Mode 6 — Worst for Safety & Compliance): 12 cases (loss of 12 pts).**  
   *Questions:* Q03, Q04, Q05, Q10, Q11, Q21, Q24, Q25, Q26, Q32, Q33, Q34 (each scored 1/2).  
   *Mechanism:* Accurately states the primary rule but omits secondary exceptions due to prompt rule 5 (*"Be concise. Two or three sentences"*). On Q04 (*waiting period*), it states 36 months but omits Senior Care 24 months. On Q11 (*ambulance*), it cites Rs 5,000 but omits the air ambulance exclusion.
3. **Archived Document Distractor Contamination (Mode 4): 1 case (Q29, loss of 1 pt).** Retrieved deprecated `claims-timelines-2024-ARCHIVED` in top 5.

---

## 4. What It Costs

### Token Cost Arithmetic
Model: `gemini/gemini-3.7-flash` (tier: MAIN). Pricing in `aip/config.py`: **$0.75 / 1M prompt**, **$3.75 / 1M completion**. Average query: **855 prompt**, **170 completion tokens**:
`Cost per query = (855 * $0.75 + 170 * $3.75) / 1,000,000 = $0.00064125 + $0.00063750 = $0.00128`

### Projections (at 10,000 queries/day = 3,650,000 queries/year)
- **Uncached (100% cold traffic):** $1.28 / 1,000 queries --> **$4,667 / year**.
- **Blended (projecting 30% repeat traffic hit rate):** $0.896 / 1,000 queries --> **$3,267 / year** (net savings: **$1,400 / year**).  
  *(Note: 30% is an operational estimate based on expected repeat user traffic, not offline paraphrase data).*

---

## 5. How Fast It Is & The Caching Boundary

### Latency Budget & Stage Breakdown
- **Uncached Live (n=20):** p50 = 3,850 ms, p95 = 4,285 ms (SLO: <= 6,000 ms).
- **Cached (n=45):** p50 = 0.12 ms, p95 = 0.16 ms (SLO: <= 800 ms).
- **Offline CI Replay (`AIP_OFFLINE=1`):** p95 = 9.7 ms (deterministic SQLite read).
- **Stage Breakdown:** embed: 3.2 ms (0.07%) | retrieve: 2.8 ms (0.07%) | rerank: 0.0 ms (bypassed) | generate: 4,278.0 ms (99.83%) | validate: 1.0 ms (0.02%). LLM generation accounts for 99.83% of uncached latency.

### Semantic Cache Pair Analysis & Architectural Decision (Part B1)
Tested across 11 representative query pairs (`reports/cache_sweep.json`):

| Threshold | Paraphrase Hit Rate (TP, n=5) | False Hit Rate (FP, n=6) | Cross-Plan Collisions? |
|---|---|---|---|
| **>= 0.950** (Shipped) | **0% (0/5)** | **0% (0/6)** | None |
| **>= 0.940** | 20% (1/5) [claim deadline: 0.9419] | 0% (0/6) | None (margin is only 0.0047!) |
| **>= 0.930** | 20% (1/5) | 17% (1/6) | **YES** (Gold vs Silver Sum Insured: 0.9372) |
| **>= 0.910** | 20% (1/5) | 50% (3/6) | **YES** (Waiting Periods: 0.9181, Copay: 0.9136) |
| **>= 0.850** | 40% (2/5) [+ grace period: 0.8566] | 50% (3/6) | **YES** (Cross-plan collisions remain) |

**Architectural Decision:** At the shipped 0.950 threshold, the semantic cache is 100% safe but captures **0% of tested paraphrases**; the narrow margin above Gold/Silver (0.9372) is only 0.0047. Therefore, we **disable or keep semantic caching dormant** (`SEMANTIC_SIMILARITY_THRESHOLD = 1.1`) until plan metadata keying is introduced, relying purely on Layer 1 exact hash caching.

---

## 6. Operating Boundaries: Permitted vs. Strictly Prohibited

- **Where it MAY run unsupervised:** Informational policy FAQ lookup, benefit exploration, and self-service navigation, provided the UI disclaims that specific exclusions must be verified against the official policy schedule.
- **Where it is STRICTLY PROHIBITED:**
  1. **Binding claim pre-authorizations or coverage decisions:** 12 of 40 answers drop secondary caveats (e.g., Senior Care 24-mo waiting period); automated adjudication without licensed adjuster review creates immediate legal liability under IRDAI regulations.
  2. **Unsupervised financial mutations (`issue_refund`):** Payout tools require human sign-off via `ToolGuard`. (Note: `issue_refund` is an architectural boundary for future agentic tools, not exposed on the read-only `/ask` endpoint).
  3. **Unkeyed semantic caching across plans:** Cross-plan term collisions at cosine 0.9372 prohibit raw semantic caching across plan tiers.

---

## 7. What We Would Do Next (Ranked by Expected Value)

1. **Retrieval Window & Reranker Ablation (EV Upper Bound: +0.075 Correctness, Targets Q20, Q23, Q44):**  
   *Untested Hypothesis Nuance:* Because gold chunks were already in the top 5 (ranks 2–4), reordering them alone may not prevent refusals if distractors remain in context. We would run an empirical ablation testing: (a) cross-encoder reranking (~15–25 ms estimated CPU latency), (b) cutting `final_k` from 5 to 3, and (c) relaxing prompt refusal rules. (LLM rerankers are ruled out as they would add 2–3s against the 6,000 ms budget). Recovering all 3 queries yields +6 pts / 80 = +0.075 correctness.
2. **Structured Exception Prompting with Output Cap (EV: +0.050 to +0.075 Correctness, Targets 12 Omissions):**  
   *Latency/Cost Trade-off (T3 Section 3.2):* Generation pace is 18.3–25.2 ms/token (derived from 4,278 ms for 170 tokens, with TTFT = 1,180 ms). Generating 60–80 extra caveat tokens costs **+1.1 to +2.0 s**, pushing uncached p95 to **5.4–6.3 s** (risking a breach of the 6,000 ms gate). Therefore, this fix is **only viable if paired with an output token cap (`max_tokens=220`)** or speculative drafting.
3. **Pre-Retrieval Status Filter (`status != ARCHIVED`) (EV: +0.0125 Correctness, Fixes Q29, Cost/Latency Delta: $0):**  
   Filter deprecated 2024 documents at search time, recovering Q29 (+1 pt / 80).
4. **Metadata-Keyed Semantic Cache at 0.850 (EV: Estimated +15% Repeat Hit Rate, 0% Cross-Plan False Hits):**  
   Plan-keying at 0.88 still captures only 1 paraphrase because the next sits at 0.8566. Keying by `(plan_name, query_embedding)` eliminates cross-plan collisions, allowing the threshold to safely drop to **0.850**—capturing the 0.8566 grace period paraphrase while staying above the 0.8369 intra-plan room/ICU rent collision.

---

## 8. Provenance, CI Verification & Regression Gate

- **CI Pipeline:** Codified in `.github/workflows/eval.yml` and tracked in GitHub Actions at https://github.com/Sarthakm20/aip-lab1/actions.
- **Passing Build (main branch, commit `5b1fda3`):**  
  `python labs/lab7/gate.py --config labs/lab7/thresholds.yml` runs deterministically under `AIP_OFFLINE=1` using committed cache `.aip_cache/calls.sqlite3`. Result: **8/8 metrics green, exit code 0 (`GATE PASSED`)**.
- **Deliberate Regression Break (Part D3, commit `d7a31b9` in PR #1):**  
  `python labs/lab7/gate.py --break-gate` simulates restricting retrieval to `final_k=1`. Hit rate collapses to 32/42 = 0.7619 (fails >= 0.850) and correctness scales to 0.7625 * (0.7619 / 0.9762) = 0.5951 (~47.6/80 pts, fails >= 0.750). Result: **Exit code 1 (`GATE FAILED`)**, turning the CI build red and blocking merge.

### Work Done
- FastAPI service (`service.py`), multi-tier caching (exact & semantic), SSE streaming endpoint with citation validation, and offline regression gate (`gate.py`, `thresholds.yml`).
- Front-end Streamlit UI (`ui.py`), operations telemetry dashboard (`dashboard.py`), empirical cosine cache sweep analysis (`sweep_cache.py`), and error diagnosis.
