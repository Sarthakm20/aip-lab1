# Report

## Part A — v0 failure characterisation (n=40, SMALL tier)

| Failure mode | Count | Example ID | T1 §3 mapping |
|---|---|---|---|
| Not valid JSON at all | 0 | — | T1.1 Raw formatting / syntax |
| JSON wrapped in a markdown fence | 33 | T0054 | T1.1 Raw formatting / syntax |
| Extra prose before or after the JSON | 0 | — | T1.1 Raw formatting / syntax |
| Valid JSON, missing a required field | 0 | — | T1.2 Schema & data-type violations |
| Valid JSON, category outside allowed set | 33 | T0054 | T1.3 Constraint & enum violations |
| Urgency as a string instead of an int | 33 | T0054 | T1.2 Schema & data-type violations |
| Policy number invented | 0 | — | T1.4 Hallucination & faithfulness |
| Unhandled exception | 7 | T0110 | *Not in T1 §3 — infrastructure/API failure* |

**Two rows with no T1 §3 entry:** *Unhandled exception* (`RateLimitError`, provider quota exhaustion — an infrastructure failure, not a model-output defect) and, arguably, *markdown fence* itself, which is a transport/packaging issue rather than a content defect — the JSON inside is well-formed; only the wrapper breaks a naive parser.

**The arc:** 0/40 parsed → 33/40 parsed after stripping the fence → 0/40 fully clean. The one-line fix that unblocks parsing simply reveals the next layer of defects (enum violations, type mismatches) that were previously invisible behind a parse failure. This is the case for Part B: syntactic validity and semantic validity are different guarantees, and only the second one is worth anything in production.

---

## Variant comparison — v0 / B / C

| Variant | Split | Schema valid | Field acc. | Record acc. | Cost (n) | p95 latency |
|---|---|---|---|---|---|---|
| v0 (naive) | dev, n=40 | 0% clean | — (unstructured) | — | not measured | not measured |
| B (model decides all 8) | dev, n=60 | 1.00 | 0.902 | 0.451–0.476* | ~$0.008–0.009* | ~1,210–1,260 ms* |
| C (3 fields moved to code) | dev, n=60 | 1.00 | 0.906 | 0.438–0.482* | ~$0.018–0.021* | ~1,260–8,800 ms* |
| C (final) | **test, n=120** | 1.00 | 0.9125 | 0.48 | $0.033 | p50 1,082 ms / p95 1,636 ms |

*B vs. C dev-split cost and latency figures are **not directly comparable** across repeated runs: the harness cache was warming asymmetrically between variants (B accumulated far more cache hits than C, since C's reduced schema produces a different cache key). Field accuracy, which is unaffected by caching, is the trustworthy comparison here and shows the expected finding: **C holds flat relative to B (0.906 vs 0.902)** — accuracy does not rise, because `policy_number`, `contains_pii`, `product`, and `language` were already at ~1.000 in B. There were no points left to win; what C buys is that those four fields are now deterministic and auditable rather than usually-right, at a shorter model-facing prompt.

**Test-split caveat (Measurement, D1):** the reported test-split run completed with `error_rate = 0.583` — 70 of 120 tickets failed on `RateLimitError` (free-tier quota, 15 req/min) rather than returning a model response, so `field_accuracy`/`record_accuracy` above are computed over the ~50 tickets that did return a response, not the full 120-item split. Cost and latency are computed only over completed calls and are internally consistent but represent a partial sample. This is reported honestly rather than re-run to produce a cleaner-looking number.

---

## Per-field accuracy (test split, n≈50 completed)

| Field | Accuracy |
|---|---|
| contains_pii | 1.00 |
| language | 1.00 |
| policy_number | 1.00 |
| product | 1.00 |
| category | 0.94 |
| escalate | 0.88 |
| sentiment | 0.84 |
| **urgency** | **0.64** (worst) |

**Category confusion matrix (dev, n=60, most complete run):**

```
                billing  claims  complaint  information  policy_change  technical
billing              10       .          .            .              .          .
claims                .      10          .            .              .          .
complaint             .       2          6            .              .          .
information            .       1          .           10              .          .
policy_change          .       .          .            .             10          .
technical              .       .          .            .              .          7
```

Errors cluster almost entirely on `complaint → claims` (2 of 3 total misclassifications) — exactly the boundary `data/README.md` flags: an angry claims message stays `claims` unless Aurora's *conduct* is the actual subject, and that distinction is genuinely hard to draw from surface tone alone.

**Urgency errors** are off-by-one at adjacent boundaries (e.g. predicted 2 vs gold 3 on "stuck and waiting" tickets; predicted 4 vs gold 5 on tense-sensitive Ombudsman language), not scattered across the scale — consistent with the README's warning that the 1/2 ("does Aurora need to look anything up") and 4/5 ("threatening vs. already escalating") boundaries are where nearly all urgency error concentrates.

---

## Top three error clusters

**1. Urgency boundary errors (and downstream `escalate` errors).**
`urgency` is the worst field at 0.64, and `escalate` (0.88) is entirely downstream of it — `escalate` is a Part C business rule computed in code from `urgency`, so it can only be wrong when `urgency` is wrong; it is not a separate model failure. Root cause: the 1/2 boundary ("can this be answered without opening the customer's record?") and 4/5 boundary (threat vs. active escalation, a tense distinction) require situational judgement the field description alone doesn't fully pin down. *Fix:* add one or two contrastive anchor examples directly in the `urgency` field description for the 1/2 and 4/5 boundaries specifically — not a general few-shot block, since T2 guidance is that most instruction belongs in the schema, not prose. *Estimated impact:* the reference solution reaches 0.75 on this exact field with a well-tuned description, suggesting real headroom above 0.64.

**2. Sentiment neutral/frustrated boundary.**
Sentiment sits at 0.84. Per `data/README.md`, `frustrated` requires the message to reference a *prior failure* (repeat contact, delay, unanswered request) — a terse first-time request is `neutral` even if short and blunt. This is easy for a model to conflate with tone alone. *Fix:* strengthen the field description to explicitly state the "first-time request → neutral, regardless of brevity" rule as a standalone clause, since it is a specific, checkable heuristic rather than a vague tone judgement.

**3. Category complaint/claims boundary.**
Category is otherwise strong (0.94) but its few errors concentrate at `complaint ↔ claims`, matching the confusion matrix. *Fix:* the description already states the rule ("still wants the claim processed" → claims), but the evidence field's placement (before category) doesn't fully compensate when the model latches onto tone words ("furious," "denied") rather than the customer's actual ask. Adding a one-clause tie-breaker — "if in doubt, ask whether the customer wants a transaction to happen or is objecting to how they were treated" — directly targets this residual gap.

---

## Economic argument (D5)

- LLM cost per ticket (measured, test split): **$0.000276** (~₹0.023 at ₹83.5/$1)
- Human agent cost per ticket: 40s at ₹300/hr = **₹3.33**
- Annual system cost at 10,000 tickets/day: **~₹84,057/yr** (LLM only)
- Annual human-only cost at the same volume: **~₹1.22 crore/yr**

Modelling rework cost for incorrect records:
`Cost_system = LLM_cost + (1 − A) × ₹3.33`, break-even where `Cost_system < ₹3.33` gives `A > ~0.007` — i.e. because LLM inference cost is negligible next to human labour cost, the system is cost-positive at almost any non-trivial accuracy.

**This number is directionally real but the model understates true cost, and that gap is worth stating explicitly.** `needs_human_review` triggers on only ~2% of records (hard schema failures caught by the repair loop). The other ~48% of incorrect records in this run (right schema, wrong `category`/`urgency`/`sentiment` value) pass validation silently and get auto-routed *incorrectly*, with **no rework cost captured in the model above** — but a real downstream cost exists: misrouted tickets, SLA breaches on under-flagged urgent cases, wrong-priority handling. This cost isn't ₹3.33 (a human never manually reworks it, since nothing flagged it), and it isn't zero either. We do not have the data to price it honestly, so we report the gap rather than inventing a number for it. **The true break-even accuracy is higher than 0.7% once silent misrouting cost is included** — the 0.7% figure is a lower bound, not the answer.

---

## One thing that didn't work

Comparing Part B and Part C cost/latency directly from repeated dev-split harness runs. The response cache filled asymmetrically between variants — B (unchanged schema across dev-split runs) accumulated far more cache hits over successive runs than C (which uses a reduced schema, `TicketRecordC`, producing a different cache key). This made B's reported cost/latency look artificially better in later runs purely as a caching artefact, not a genuine effect of the schema change. The fair comparison — field accuracy, which caching doesn't affect — still showed the expected result (C holds flat vs. B), but the cost/latency reduction Part C is supposed to demonstrate (the ~20–25% reference figure) could not be confirmed cleanly without a cache-bypass mechanism, which this harness did not appear to expose. Documenting this limitation rather than presenting a misleading cost delta was the more defensible choice.