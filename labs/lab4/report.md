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

## Refusal precision / recall (two strictness settings)

| Setting | Refusal recall | Refusal precision |
|--------|----------------|-------------------|
| Strictness 1 (exact refusal string) | 1.00 (5/5) | 0.63 (5/8) |
| Strictness 2 (allow partial) | 1.00 (5/5) | 0.63 (5/8) |

## Judge κ for both rubrics

| Rubric | Cohen’s κ |
|--------|-----------|
| Faithfulness | **1.00** |
| Correctness | **0.90** |

## E2 Decomposition (gold vs retrieved)

| Metric | Gold (A) | Retrieved (B) | Retrieval‑attributable loss | Generation‑attributable loss |
|--------|----------|---------------|----------------------------|------------------------------|
| Correctness (normalized) | **0.833** | **0.726** | **0.107** | **0.167** |

## E3 Failure‑mode tally (10 worst answers)

*Pending – to be completed after manual inspection of the 10 lowest‑scoring answers.*

---

*All numbers are taken from the latest evaluation runs (`reports/lab4.json` and `reports/lab4_strict.json`).*
