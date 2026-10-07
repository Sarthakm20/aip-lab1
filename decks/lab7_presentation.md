# Aurora Policy Assistant — 4-Slide Demo Day Deck
**Lab 7 Capstone Presentation · AI in Practice (Module 1)**  
*Presenters: Sarthak M. & Aarav Sharma · Maximum 4 Slides*

---

## Slide 1: System Overview, Grounded Answer & Correct Refusal

### System Architecture
- Production FastAPI service implementing the 7-layer architecture.
- Two-tier caching (Exact SHA-256 hash match + Semantic cosine similarity).
- Guarded RAG pipeline (Input injection filter, untrusted delimiters, citation validator).

### Live Question 1: Cited & Grounded (30s Demo)
- **User Query:** *"How many days do I have to submit a reimbursement claim after discharge?"*
- **Model Answer:** *"Under standard claim timelines, you have 30 days from the date of discharge to submit a reimbursement claim [1]."*
- **Grounding & Telemetry:** Cited source `[1]` (`claim-process`, Rank 1); Latency: 401 ms; Cost: \$0.0013; Citations Valid: True.

### Live Question 2: Grounded Refusal & System Boundary (30s Demo)
- **Unanswerable Query (Q36):** *"What is the annual premium for a 35-year-old on Aurora Gold with 25L sum insured?"*
- **Model Answer:** *"I don't have enough information in the provided sources to answer that."*
- **Why Refusal is Correct:** The policy corpus specifies tax, loadings, and discounts but *contains no premium rate table*. Refusing prevents severe financial and regulatory misrepresentation.

---

## Slide 2: Operational Metrics & Semantic Cache Boundary

### Live Metrics from `/metrics` vs Target SLOs (1 Min)
- **Cost per Query:** **\$0.00128** (SLO Target: ≤ \$0.010)
- **p95 Latency (Cached / Uncached):** **0.16 ms / 4,285 ms** (SLO Target: ≤ 800 ms / ≤ 6,000 ms)
- **Streaming TTFT (Live / Cached):** **1,180 ms / 15.0 ms** (Target: ≤ 1,500 ms)
- **Annual Operational Cost (10,000 queries/day):** **\$3,267 / year** (with 30% projected repeat-traffic cache hit rate saving \$1,400/yr)
- **Latency Bottleneck:** LLM generation accounts for **99.8%** of uncached latency (4,278 ms); retrieval accounts for only 2.8 ms.

### Semantic Cache Sweep & Boundary Analysis (Part B1 Finding)
- **Sweep Finding:** Collisions between subtle plan terms (Gold vs. Silver sum insured) occur at cosine **0.9372**, while true paraphrases score **0.9419** (claim deadline) down to **0.8566** (grace period).
- **The Razor-Thin Margin:** Only **0.0047** separates the claim paraphrase from the cross-plan collision. Setting threshold $\le 0.937$ triggers confident false hits.
- **Shipped Threshold (0.950):** 100% safe against cross-plan collisions, but captures **0% of tested paraphrases**. Distant paraphrases (grace period 0.8566) require metadata keying `(plan_name, embedding)` to eliminate cross-plan collisions.

---

## Slide 3: Continuous Regression Gate in CI

### Deterministic Offline Replay (Part D1)
- Codified in `.github/workflows/eval.yml`, running on push/PR with `AIP_OFFLINE=1`.
- Replays deterministic calls against committed cache `.aip_cache/calls.sqlite3` (zero API key, zero cost).
- **Tuned Thresholds (Official Lab Defaults):**
  - Correctness: 0.7625 ≥ 0.750 (**OK**)
  - Faithfulness: 1.0000 ≥ 0.900 (**OK**)
  - Citation Validity: 1.0000 ≥ 0.980 (**OK**)
  - Refusal Recall: 1.0000 ≥ 0.800 (**OK**)
  - Refusal Precision: 0.6250 ≥ 0.600 (**OK**)
  - Hit Rate @ 5: 0.9762 ≥ 0.850 (**OK**)
  - Cost per Query: \$0.0000 ≤ \$0.010 (**OK**)
  - p95 Latency: 9.7 ms ≤ 6,000 ms (**OK**)
- **Normal Build Status:** `GATE PASSED` (Exit Code 0).

### Deliberate Regression Demonstration (Part D3 - 1 Min)
- **Deliberate Break:** `python labs/lab7/gate.py --break-gate` simulates a regression PR restricting candidates to `final_k = 1`.
- **Immediate CI Failure:**
  - `hit_rate_at_5` collapses to **0.7619** (Violates ≥ 0.850 -> **FAIL**)
  - `correctness` drops to **0.5951** (Violates ≥ 0.750 -> **FAIL**)
- **Deliberate Build Status:** `GATE FAILED` (Exit Code 1).
- *Takeaway:* A gate you have not seen fail is a gate you do not have.

---

## Slide 4: Worst Remaining Failure, Fix & Operational Limits

### Worst Remaining Failure (Graded Item 5 - 1 Min)
- **Dual Framing:**
  - **Worst for Utility:** **False Refusals (Mode 4, Q20, Q23, Q44)** — answerable queries where retrieved chunks were ignored due to distractor chunks, giving users zero value (score 0/2, loss of 6 pts / 80).
  - **Worst for Safety:** **Caveat Omissions (Mode 6, 12 cases)** — omits secondary sub-limits (e.g. Senior Care 24-mo pre-existing disease terms), risking regulatory penalties.
- **Remedy 1: Reranking & Retrieval Ablation (EV Upper Bound: +0.075 Correctness):**
  - Reordering chunks is an untested hypothesis since gold chunks are already in top 5. We will run an ablation testing cross-encoder reranking (~20 ms) vs cutting `final_k` to 3 vs prompt refusal relaxation. (LLM rerankers ruled out due to 2–3s latency cost).
- **Remedy 2: Structured Exception Prompting (EV: +0.050 to +0.075 Correctness):**
  - Targets 12 omissions. *Trade-off (T3 §3.2):* Adds ~60–80 completion tokens, increasing cost by ~\$0.00030/query and p95 latency by ~600–800 ms (still within 6,000 ms ceiling).

### Concrete Boundary of Safe Use (Honest Limitations)
- **Permitted Unsupervised Use:** Informational FAQ lookup, benefit exploration, and policy navigation with clear disclaimer.
- **Strictly Prohibited:**
  1. **Binding claim pre-authorizations or coverage decisions:** 12/40 answers drop secondary caveats; human adjuster review is legally mandatory under IRDAI guidelines.
  2. **Unsupervised financial mutations (`issue_refund`):** Payout tools require out-of-band supervisor sign-off via `ToolGuard` (boundary for future agentic extensions).
  3. **Unkeyed semantic caching across plans:** Collisions occur at cosine 0.9372.
