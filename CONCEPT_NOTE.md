# Concept Note — Lab 7: Production Service Integration (Ship It)
**Module 1 Capstone · AI in Practice**  
*Team: Sarthak M. & Aarav Sharma · System: Aurora Policy Assistant*

---

## 1. Problem and Objective

Throughout Labs 1 to 6, individual subsystems were engineered in isolation: extraction (Lab 1), routing and evaluation (Lab 2), retrieval and chunking (Lab 3), grounded RAG and judges (Lab 4), error diagnosis (Lab 5), and tool-use guardrails (Lab 6). However, an offline notebook is not a production service. No end user or customer can query a Jupyter notebook, and a notebook cannot enforce Service Level Objectives (SLOs), prevent regression under code modifications, or protect financial budgets.

**Objective:** Transform our best research components into a hardened, production-grade HTTP service (`POST /ask`, `POST /ask/stream`, `GET /health`, `GET /metrics`) featuring:
1. Two-tier response caching (Exact hash match + Semantic cosine similarity).
2. Progressive streaming with server-sent events (SSE) resolving the citation validation dilemma.
3. Full observability answering *"why did request X take 9 seconds?"* via structured spans.
4. A continuous integration (CI) regression gate enforced offline via committed cache.
5. Quantified economic, latency, and failure bounds defended with real numbers.

---

## 2. Seven-Layer Architecture

The system implements the 7-layer production architecture defined in Theory Note T1 §4:

```
Layer 7: INTERFACE       FastAPI HTTP REST & SSE Endpoints (/ask, /ask/stream) + Streamlit UI (ui.py)
Layer 6: ORCHESTRATION   Guarded Tool Loop (run_agent), Budget Contexts, Retry with Exponential Jitter
Layer 5: VALIDATION      Pydantic Input Schemas, Citation Enforcer (enforce_citations), Injection Guard
Layer 4: MODEL           LiteLLM Client (~20 lines in aip/llm.py, Tier: MAIN -> gemini-3.7-flash)
Layer 3: CONTEXT         Markdown Chunker (size=800), Dense NumPy Cosine Retriever, format_context
Layer 2: DATA            Policy Corpus (30 docs), SQLite Call Cache, In-Memory Exact & Semantic Cache
Layer 1: OBSERVABILITY   Structured JSONL Spans (.aip_traces/), Operations Dashboard (dashboard.py)
```

**Key Architectural Insight:** Layer 4 (the generative model) is the smallest layer and the only non-deterministic component. The surrounding deterministic layers (1–3 and 5–7) enforce reliability, latency bounds, and correctness.

---

## 3. Key Design Decisions & Technical Trade-offs

### A. Pipeline Configuration
- **Chosen Retriever:** Dense cosine retrieval over markdown-aware 800-character chunks (`markdown_chunks`).
- **Rationale:** Lab 3 proved that markdown-aware chunking isolates structural clauses cleanly (MRR 0.8720 vs fixed 0.8387) while avoiding table truncation. Cross-encoder rerankers were discarded for interactive queries because they added 2.7s of latency with negligible precision gain.
- **Startup Singleton:** The pipeline is initialized once during FastAPI startup (`@app.on_event("startup")`). Re-embedding the corpus per-request causes an immediate 40-second latency penalty.

### B. Two-Tier Caching & Semantic Threshold Sweep
- **Layer 1 (Exact Match):** Normalized question hashed with SHA-256. Hit rate: 20–30%; latency: < 0.2 ms; cost: \$0.00; error risk: 0%.
- **Layer 2 (Semantic Cache):** Query embedded using `gemini-embedding-001`.
- **The Empirical Sweep:** Rather than blindly adopting the default 0.95 threshold, we evaluated cosine similarities across true-positive paraphrases and false-positive entity collisions (e.g. Gold vs. Silver plan terms).
- **Critical Finding:** Collisions between subtle plan terms (e.g. *"What is the sum insured on Aurora Gold?"* vs *"Aurora Silver?"*) occur at cosine **0.9372** and waiting periods at **0.9181**. Setting the threshold at ≤ 0.935 returns confident, cited, and completely incorrect answers. We configured the safe operating threshold at **0.950** and established that semantic caching across differing entities requires metadata keying.

### C. Streaming & The Citation Dilemma (Part B3 Defense)
- **The Dilemma:** Streaming requires output tokens to be pushed to the client progressively (TTFT ≤ 1,500 ms). However, citation validity cannot be verified until generation completes.
- **Our Resolution:** Stream the prose tokens progressively over SSE (`event: token`). Once the model finishes generation, run citation validation (`enforce_citations`). Emit a dedicated `event: citation` and `event: validation`. If citations are hallucinated or ungrounded, the validation event issues `action: "fallback"`, instructing the UI to immediately flag or replace the invalid prose with the standard refusal. This preserves responsiveness while guaranteeing grounding integrity.

---

## 4. Key Results

| Target | Requirement | Achieved | Status |
|---|---|---|---|
| Grounded Answers with Citations | Working on `POST /ask` | Working, 100% Citation Validity | **PASSED** |
| Service Health & Metrics | `/health` & `/metrics` endpoints | Live index stats, percentiles, cost | **PASSED** |
| Streaming TTFT | ≤ 1,500 ms | **1,180 ms (Live) / 15.0 ms (Cached)** | **PASSED** |
| p95 Latency (Cached) | ≤ 800 ms | **0.16 ms** | **PASSED** |
| p95 Latency (Uncached) | ≤ 6,000 ms | **4,285 ms** | **PASSED** |
| Cost per Query | ≤ \$0.010 | **\$0.00128** | **PASSED** |
| Regression Gate | Fails build on metric regression | Exits 0 on green, exits 1 on break | **PASSED** |

---

## 5. Failure Modes and Operating Boundaries

1. **Secondary Caveat Omission (75% of residual errors):** Single-hop queries accurately state the primary rule but omit secondary sub-limits due to the prompt's conciseness constraint.
2. **Safe Boundary:** The system is authorized for **informational guidance only**. It is explicitly **not authorized for binding coverage determination, claim payout adjudication, or unsupervised financial actions** without human adjuster confirmation.

---

## 6. Team Contributions (Pair Split)

- **Sarthak:** Engineered the FastAPI service (`service.py`), exact & semantic cache engines, streaming SSE endpoint with B3 validation, and the CI regression gate (`gate.py` & `thresholds.yml`).
- **Aarav Sharma:** Built the front-end UI (`ui.py`), operations telemetry dashboard (`dashboard.py`), telemetry alert monitors, and executed the empirical cache sweep and diagnostic failure analysis.
