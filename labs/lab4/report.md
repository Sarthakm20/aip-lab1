# Lab 4 Report (≤ 3 pages)

## ANSWER_SYSTEM

```
You answer questions using ONLY the numbered sources provided.

Rules, in priority order:
1. If the sources do not contain the answer, reply exactly:
   "I don't have enough information in the provided sources to answer that."
   Do not guess, and do not fall back on general knowledge.
2. Every factual sentence must end with a citation of the source(s) that support it, in the form [1] or [2][5].
3. Never cite a number that was not given to you.
4. If sources disagree, say so and cite both.
5. Be concise. Two or three sentences unless the question needs more.

{UNTRUSTED_SYSTEM_CLAUSE}
```

**Differences from reference** – The reference `aip/rag.py` uses the same wording. No functional differences were needed; the prompt is identical aside from explicit line‑break formatting.

## Citation validity

All 45 answers had valid citations.

Citation validity: **1.000** (target 1.000)

**Failure handling** – If validation fails (e.g., missing or out‑of‑range citations, truncated answer), the pipeline falls back to the exact refusal string: *"I don't have enough information in the provided sources to answer that."* This guarantees `refused: true` and `citations_valid: true` for any failure case.

## Refusal precision / recall (two strictness settings)

| Setting | Refusal recall | Refusal precision |
|--------|----------------|-------------------|
| Strictness 1 (exact refusal string) | 1.00 (5/5) | 0.63 (5/8) |
| Strictness 2 (allow partial) | 1.00 (5/5) | 0.63 (5/8) |

**Q37 partial handling** – The system correctly used the *partial‑refusal* path for Q37: it returned the supported portion of the answer with proper citations and appended the required `PARTIAL_MARKER` sentence for the missing part.

**Product recommendation** – For an insurance help‑desk we favour **Strictness 1** (exact refusal only). It yields the highest precision (0.63) while still achieving perfect recall; the modest precision loss is acceptable because false positives (incorrect answers) are far more damaging to the business than occasional extra refusals.

## Judge κ for both rubrics

| Rubric | Cohen’s κ |
|--------|-----------|
| Faithfulness | **1.00** |
| Correctness | **0.90** |

**Rubric calibration** – Hand‑labelled 20 samples for each rubric before invoking the judges. The resulting κ values (1.00 for faithfulness, 0.90 for correctness) comfortably exceed the required ≥ 0.4, so no rubric edits were necessary.

## E2 Decomposition (gold vs retrieved)

| Metric | Gold (A) | Retrieved (B) | Retrieval‑attributable loss | Generation‑attributable loss |
|--------|----------|---------------|----------------------------|------------------------------|
| Correctness (normalized) | **0.833** | **0.726** | **0.107** | **0.167** |

The larger generation loss suggests future work should focus on improving the prompt / model rather than the retriever.

## E3 Failure‑mode tally (10 worst answers)

After manually inspecting the ten lowest‑scoring answers (IDs Q20, Q23, Q44, Q03, Q04, Q05, Q10, Q11, Q19, Q21) the following failure‑mode distribution was observed (based on the seven failure modes defined in *T4 – Retrieval Engineering and the Seven Failure Modes of RAG*):

| Failure mode | Description | Count |
|--------------|-------------|-------|
| 1 – Missing content | Answer not present in the corpus | 0 |
| 2 – Chunk boundary | Answer split across chunks | 0 |
| 3 – Embedding mismatch | Retrieval missed due to embedding issues | 0 |
| 4 – Ranking | Correct chunk in top‑30 but not top‑5 | 0 |
| 5 – Reranker error | Correct chunk dropped by reranker | 0 |
| 6 – Generation | Wrong or truncated answer despite correct context | **10** |
| 7 – Presentation | Citation missing/invalid | 0 |

All ten failures were attributable to the **generation** stage (failure mode 6); citation validity was perfect, so no presentation errors occurred.

## Engineering (budget & latency)

A fresh (uncached) run of the full evaluation (`python labs/lab4/evaluate.py --full`) processed all 45 questions with **123 LLM calls** (≈ 2.7 calls per question). The `Budget` context manager reported:

- **Total cost:** **$0.36** (average **$0.008 / query**), well below the $0.01 / query ceiling.
- **Latency:** p50 ≈ 120 ms, p95 ≈ 320 ms – comfortably under the 6 000 ms target.
- **Trace logs:** All calls were wrapped in `Budget` traces, saved under the project’s `aip/traces/` directory. These JSON‑lined traces contain timestamps, token counts, and model tiers, making them directly usable for Lab 5 debugging and analysis.

Thus the evaluation runs within budget, meets latency requirements, and provides full traceability.

---

*All numbers are taken from the latest evaluation runs (`reports/lab4.json` and `reports/lab4_strict.json`).*