# Evaluation Report — Aurora Policy Assistant
**Lab 7 Capstone Deliverable · AI in Practice (Module 1)**  
*Authors: Sarthak M. & Aarav Sharma · System: Aurora Policy Assistant v1.0 · October 2026*  
*Repository: `aip-lab1` · CI Workflow: `.github/workflows/eval.yml` · Offline Replay: Deterministic*

---

## 1. What It Does

The Aurora Policy Assistant is an automated customer service system that answers policyholders' questions about health and travel insurance coverage, claim filing deadlines, waiting periods, and exclusions. Instead of having customers read through 30 dense policy PDFs or wait on hold for an agent, the assistant searches Aurora's official contract documents and writes a clear, concise answer citing the exact policy sections that support each statement. When a customer asks about something not covered in the documents—such as an unlisted benefit or an unstated rate—the assistant explicitly declines to answer rather than guessing or fabricating terms.

---

## 2. How Well It Works

Evaluated on the 45-question golden benchmark (`data/eval/rag_golden.jsonl`), comprising 40 answerable queries across 5 difficulty types and 5 unanswerable queries under `AIP_OFFLINE=1` using committed cache `.aip_cache/calls.sqlite3`. Latency percentiles and TTFT are evaluated across $n=45$ benchmark queries and verified on $n=20$ live endpoint requests.

| Evaluation Metric | Baseline (Lab 4 Harness)* | Final Service (Serving Only) | Target / SLO | Gate Rule | Status |
|---|---|---|---|---|---|
| **Answer Correctness (Answerable, n=40)** | 0.7625 (61/80) | **0.7625** (61/80) | ≥ 0.750 | min 0.750 | **PASS** |
| **Faithfulness to Context (n=45)** | 1.0000 (45/45) | **1.0000** (45/45) | ≥ 0.900 | min 0.900 | **PASS** |
| **Citation Validity (All Queries)** | 1.0000 (45/45) | **1.0000** (45/45) | 1.000 | min 0.980 | **PASS** |
| **Refusal Recall (Unanswerable, n=5)** | 1.0000 (5/5) | **1.0000** (5/5) | ≥ 0.800 | min 0.800 | **PASS** |
| **Refusal Precision (Refusals, n=8)** | 0.6250 (5/8) | **0.6250** (5/8) | ≥ 0.600 | min 0.600 | **PASS** |
| **Retrieval Hit Rate @ 5** | 0.9762 | **0.9762** | ≥ 0.850 | min 0.850 | **PASS** |
| **Retrieval nDCG @ 10** | 0.8458 | **0.8458** | ≥ 0.800 | — | **PASS** |
| **Cost per Query (Uncached Live)** | \$0.0080* | **\$0.00128** | ≤ \$0.010 | max 0.010 | **PASS** |
| **p95 Latency (Cached / Uncached)** | — / 4,310 ms | **0.16 ms / 4,285 ms** | ≤ 800 / 6,000 ms | max 6000 | **PASS** |
| **Streaming TTFT (Live / Cached)** | — | **1,180 ms / 15.0 ms** | ≤ 1,500 ms | — | **PASS** |

*\*Note on Cost Comparison:* The Lab 4 baseline (\$0.0080) measured an offline evaluation harness that invoked LLM judges (`tier=LARGE` at \$1.50/1M prompt, \$9.00/1M completion, consuming ~1,100 prompt + ~300 output tokens per evaluated query $\approx \$0.0044$ judge cost + multi-candidate runs). The Lab 7 production service does not invoke judges at runtime, dropping serving cost to \$0.00128/query. Both environments run identical single-pass token generation on Gemini 3.7 Flash, maintaining uncached p95 latency at ~4.3s.

---

## 3. Where It Fails

Across 40 answerable questions (80 possible points), the system scored **61/80 (0.7625)**, with exactly **16 non-perfect responses** (losing 19 points):

1. **Secondary Caveat Omission (Mode 6 — Generation Completeness): 12 cases (loss of 12 pts).**  
   *Questions:* Q03, Q04, Q05, Q10, Q11, Q21, Q24, Q25, Q26, Q32, Q33, Q34 (each scored 1/2).  
   *Mechanism:* The model accurately states the primary rule but omits minor exceptions due to prompt rule 5 (*"Be concise. Two or three sentences"*). On Q04 (*pre-existing disease waiting period*), it cites the standard 36 months but omits the Senior Care 24-month exception. On Q11 (*ambulance limit*), it cites ₹5,000 but misses the air ambulance exclusion.
2. **False Refusals Induced by Distractors (Mode 4 — Ranking/Distractor Traps): 3 cases (loss of 6 pts).**  
   *Questions:* Q20 (family floater rules), Q23 (Bronze OPD cover), Q44 (product code `AUR-HI-SIL-2026`) (each scored 0/2).  
   *Mechanism:* Answerable queries where the gold chunk was retrieved (ranks 2–4), but adjacent distractor chunks triggered excessive conservatism, yielding a full refusal.
3. **Archived Document Distractor Contamination (Mode 4): 1 case (loss of 1 pt).**  
   *Question:* Q29 (scored 1/2) retrieved deprecated `claims-timelines-2024-ARCHIVED` in top 5.
4. **Failure Framing Reconciliation:**  
   - **Worst failure for user utility / customer experience:** The **3 false refusals (Q20, Q23, Q44)**, which yield zero value on valid questions, causing unnecessary customer frustration and support escalations.
   - **Worst failure for regulatory and legal safety:** The **12 secondary caveat omissions (Mode 6)**, which under-inform customers on critical exclusions and sub-limits, risking policy disputes and IRDAI compliance violations.

---

## 4. What It Costs

### Token Cost Arithmetic
Model: `gemini/gemini-3.7-flash` (tier: MAIN). Pricing in `aip/config.py`: **\$0.75 / 1M input tokens**, **\$3.75 / 1M output tokens**. Average query: **855 prompt tokens**, **170 completion tokens**:
$$\text{Cost per query} = \frac{855 \times \$0.75 + 170 \times \$3.75}{1,000,000} = \$0.00064125 + \$0.00063750 = \mathbf{\$0.00127875 \approx \$0.00128}$$

### Volume Projections
- **Cost per query (Uncached / Cached):** \$0.00128 / \$0.00000
- **Cost per 1,000 queries (Cold, 0% hit rate):** \$1.28
- **Cost per 1,000 queries (Blended, 30% projected repeat-traffic hit rate):** \$0.896  
  *(Note: The 30% hit rate is an operational projection based on expected repeat query distributions, not an offline measurement from paraphrase embeddings.)*
- **Annual Cost at 10,000 queries/day (3,650,000 queries/year):**
  - *Uncached worst-case:* **\$4,667 / year**
  - *With 30% projected cache hits:* **\$3,267 / year** (net annual savings: **\$1,400**)

---

## 5. How Fast It Is & The Caching Boundary

### Latency Budget & Stage Breakdown
- **Uncached p50 / p95 ($n=45$):** 3,850 ms / 4,285 ms (SLO: ≤ 6,000 ms)
- **Cached p50 / p95:** 0.12 ms / 0.16 ms (SLO: ≤ 800 ms)
- **Streaming TTFT (Live / Cached):** **1,180 ms** / **15.0 ms** (Target: ≤ 1,500 ms)

```
embed query      3.2 ms   ( 0.07%)
retrieve         2.8 ms   ( 0.07%)
rerank           0.0 ms   ( 0.00% - bypassed for interactive latency)
generate      4,278.0 ms   (99.83% - dominates the wait)
validate         1.0 ms   ( 0.02% - regex citation parser)
─────────────────────────────────────────────────────────────
total         4,285.0 ms   (100.0%)
```

**Optimization Bottleneck:** LLM generation is 99.83% of uncached latency. Speedup requires output token constraints or speculative drafting, not retrieval tuning.

### Semantic Cache Targeted Pair Analysis (Part B1)
A cache hit occurs when $\text{cosine similarity} \ge \text{threshold}$. Sweep results over 11 representative pairs (`labs/lab7/sweep_cache.py`, `reports/cache_sweep.json`):

| Threshold | Paraphrase Hit Rate (TP, n=5) | False Hit Rate (FP, n=6) | Cross-Plan Collisions? |
|---|---|---|---|
| **≥ 0.950** (Shipped) | **0% (0/5)** | **0% (0/6)** | None |
| **≥ 0.940** | 20% (1/5) [claim deadline: 0.9419] | 0% (0/6) | None (margin is only 0.0047!) |
| **≥ 0.930** | 20% (1/5) | 17% (1/6) | **YES** (Gold vs Silver Sum Insured, 0.9372) |
| **≥ 0.910** | 20% (1/5) | 50% (3/6) | **YES** (Waiting Periods 0.9181, Copay 0.9136) |
| **≥ 0.850** | 40% (2/5) [+ grace period: 0.8566] | 50% (3/6) | **YES** (Cross-plan collisions remain) |
| **≥ 0.800** | 80% (4/5) [+ AYUSH, IVF] | 83% (5/6) | **YES** (Intra-plan clause collision 0.8369) |

**Key Findings:**
1. **At the shipped threshold of 0.950, the cache captures 0% of tested paraphrases.** Its benefit is restricted to near-verbatim queries.
2. A razor-thin margin of only **0.0047** separates the claim deadline paraphrase (0.9419) from cross-plan collision (Gold vs Silver sum insured at 0.9372). Any threshold $\le 0.937$ returns wrong answers.
3. Distant paraphrases (grace period at 0.8566, AYUSH at 0.8376) score lower than all plan collisions and cannot be captured safely by raw cosine similarity.

---

## 6. What It Is (and Is Not) Safe For (Concrete Operating Boundary)

Reconciling our measured **16 non-perfect responses** (3 false refusals, 12 caveat omissions, 1 distractor trap):

- **Where it MAY run unsupervised:** Informational policy exploration, FAQ search, and customer self-service navigation, provided the UI explicitly disclaims that specific exceptions must be verified in the policy schedule.
- **Where it is STRICTLY PROHIBITED:**
  1. **Binding claim pre-authorizations or coverage decisions:** Because 12 of 40 answerable questions dropped secondary caveats (e.g. Senior Care 24-month terms on Q04 or air ambulance exclusion on Q11), automated adjudication risks severe financial loss and regulatory penalties under IRDAI guidelines. Licensed human review is mandatory.
  2. **Unsupervised financial mutations (`issue_refund`):** Payout tools (engineered under Lab 6's `ToolGuard`) are prohibited from automated execution; they require supervisor authentication and out-of-band human sign-off. (Note: `issue_refund` is a boundary for future agentic write tools, not exposed on the current read-only `/ask` endpoint).
  3. **Unkeyed semantic caching across plans:** Collisions at cosine 0.9372 prohibit raw semantic caching across plan tiers.

---

## 7. What We Would Do Next (Ranked by Expected Value)

1. **Reranker / Retrieval Window Tuning (EV: Upper Bound +0.075 Correctness, Targets Q20, Q23, Q44):**  
   *Hypothesis & Testing:* Gold chunks were retrieved at ranks 2–4 within the top 5. Reordering them is an untested hypothesis that may not eliminate refusals if distractors remain in context. We would run an empirical ablation testing: (a) cross-encoder reranking (~15–25 ms latency cost), (b) truncating `final_k` from 5 to 3, and (c) relaxing the refusal trigger in `ANSWER_SYSTEM`. An LLM reranker is ruled out as it would add 2–3s against our 6,000 ms budget. Recovering all 3 queries yields $+6\text{ pts}/80 = +0.075$ correctness.
2. **Structured Exception Prompting (EV: +0.050 to +0.075 Correctness, Targets 12 Omissions):**  
   *Cost/Latency Trade-off (T3 §3.2):* Instructing the model to format caveats and sub-limits in bullet points will add ~60–80 completion tokens (+35–47%), increasing cost by ~\$0.00030/query and p95 latency by ~600–800 ms (pushing p95 to ~5,000 ms, within the 6,000 ms ceiling). Expected recovery: 4–6 of the 12 caveat omissions (+4 to +6 pts / 80).
3. **Pre-Retrieval Status Filter (`status != ARCHIVED`) (EV: +0.0125 Correctness, Fixes Q29, Cost Δ: \$0):**  
   Filter deprecated 2024 documents at search time, recovering Q29 (+1 pt / 80) at zero latency or financial cost.
4. **Metadata-Keyed Semantic Cache (EV: +15% Projected Hit Rate, 0% Cross-Plan False Hits):**  
   Key the semantic cache by `(plan_name, query_embedding)`. This eliminates 100% of **cross-plan** collisions (0.9372), allowing the threshold to drop to 0.88, while intra-plan clause distinctions (e.g. room rent vs ICU at 0.8369) still require clause-level metadata or threshold > 0.84.

---

## 8. Provenance, CI Verification & Pair Split

- **CI Pipeline Codification:** Codified in [`.github/workflows/eval.yml`](file:///.github/workflows/eval.yml) running on `push` and `pull_request` with `AIP_OFFLINE=1`.
- **Passing Build:** `python labs/lab7/gate.py --config labs/lab7/thresholds.yml` runs golden benchmark deterministically from `.aip_cache/calls.sqlite3` $\rightarrow$ `GATE PASSED` (Exit Code 0, 8/8 metrics green).
- **Deliberate Regression Break (Part D3):** `python labs/lab7/gate.py --break-gate` simulates a regression PR that truncates retrieval to `final_k=1`, failing `correctness` (0.5951 < 0.75) and `hit_rate_at_5` (0.7619 < 0.85) $\rightarrow$ `GATE FAILED` (Exit Code 1).
- **Pair Contributions:**
  - *Sarthak M.:* FastAPI service (`service.py`), multi-tier caching, SSE streaming with B3 validation, and regression gate (`gate.py`, `thresholds.yml`).
  - *Aarav Sharma:* Front-end UI (`ui.py`), telemetry dashboard (`dashboard.py`), cosine sweep analysis (`sweep_cache.py`), and error diagnosis.
