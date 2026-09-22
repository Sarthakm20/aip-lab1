#!/usr/bin/env python3
"""Lab 4 — your RAG pipeline.

Write this yourself. `aip/rag.py` is the reference implementation; look at it
after Part A, not before. Labs 5-7 build on whichever of the two you prefer,
but you must be able to explain every line of the one you use.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aip.guards import UNTRUSTED_SYSTEM_CLAUSE, delimit_untrusted, enforce_citations  # noqa: E402
from aip.llm import chat  # noqa: E402
from aip.retrieval import Hit, Retriever, format_context  # noqa: E402

# The exact string the system must emit when it CANNOT answer any part of the
# question. Exact, because downstream code detects refusal by matching it --
# a paraphrase is a bug.
REFUSAL = "I don't have enough information in the provided sources to answer that."

# The exact marker phrase the system must use to flag a part of the question
# it could NOT support, while still answering the part it could (Part C2 /
# Q37: partial coverage confirmed, specific limit not confirmed). This is
# also detected by name -- do not paraphrase it either.
PARTIAL_MARKER = "The sources do not specify"

# ---------------------------------------------------------------------------
# V1: the original prompt. Kept, unchanged, so it can be used as the "loose"
# arm of the Part C4 strictness experiment -- do not delete or edit this one.
# ---------------------------------------------------------------------------
ANSWER_SYSTEM_V1 = f"""\
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
"""

# ---------------------------------------------------------------------------
# V2: the "strict" arm for Part C4, and the fix for Part C2 (Q37).
#
# Two changes from V1:
#   - Rule 2 below narrows *when* a full refusal is allowed: only when NONE
#     of the question is supported. This targets the false-refusal pattern
#     seen on Q20/Q23/Q44 (answerable questions that got fully refused).
#   - Rule 3 below adds a partial-answer path: when a question has multiple
#     parts and only some are supported, answer what's supported and flag
#     the rest with PARTIAL_MARKER, instead of refusing the whole thing.
#     This targets Q37 (Singapore benefit confirmed, limit not confirmed).
# ---------------------------------------------------------------------------
ANSWER_SYSTEM_V2 = f"""\
You answer questions using ONLY the numbered sources provided.

Rules, in priority order:
1. Never use general knowledge. Never guess a number, date, or limit that
   is not stated in the sources.
2. Only give the full refusal below if NONE of the question is supported by
   the sources -- no partial match, no related figure, no adjacent clause.
   Before refusing, check: is there a number, a named plan, or a named
   benefit in the sources that relates to this question at all? If yes,
   use rule 3 instead of refusing.
   Full refusal, reply exactly:
   "I don't have enough information in the provided sources to answer that."
3. If the question has multiple parts and the sources support some parts
   but not others: answer the supported part(s) with citations, then add a
   separate sentence for each unsupported part using exactly this phrasing:
   "The sources do not specify [the missing part, named]." Do not omit the
   unsupported part silently, and do not guess at it.
4. Every factual sentence must end with a citation of the source(s) that
   support it, in the form [1] or [2][5]. Never cite a number not supplied.
5. If sources disagree, say so and cite both.
6. Be concise. Two or three sentences unless the question needs more.

{UNTRUSTED_SYSTEM_CLAUSE}
"""

# Default prompt used by the pipeline. This is what "ships" -- point
# evaluate.py's baseline run at this, and its A/B run at ANSWER_SYSTEM_V1 vs
# ANSWER_SYSTEM_V2 explicitly (see the note at the bottom of this file).
ANSWER_SYSTEM = ANSWER_SYSTEM_V2


@dataclass
class Answer:
    question: str
    text: str
    hits: list[Hit] = field(default_factory=list)
    refused: bool = False
    partial: bool = False  # True when the answer used the PARTIAL_MARKER path
    citations_valid: bool = False
    invalid_citations: list[int] = field(default_factory=list)
    n_citations: int = 0
    truncated: bool = False


def validate_answer(text: str, n_sources: int, finish_reason: str | None = None) -> dict:
    """Validate an answer according to lab requirements.

    Returns a dict with keys:
        valid (bool): overall validity
        refused (bool): whether the answer is a FULL refusal (exact match)
        partial (bool): whether the answer is a PARTIAL refusal (some
            content answered, some flagged via PARTIAL_MARKER)
        invalid_citations (list[int]): list of citation indices out of range
        n_citations (int): total number of citations found
        truncated (bool): whether the generation was cut off
        reason (str): short explanation for invalidity
    """
    stripped = text.strip()
    is_full_refusal = stripped.startswith(REFUSAL)
    is_partial = (not is_full_refusal) and (PARTIAL_MARKER in text)

    citations = re.findall(r"\[(\d+)\]", text)
    n_citations = len(citations)
    ok_cite, invalid = enforce_citations(text, n_sources)
    truncated = finish_reason == "length"

    result = {
        "valid": False,
        "refused": False,
        "partial": False,
        "invalid_citations": [],
        "n_citations": n_citations,
        "truncated": truncated,
        "reason": "",
    }

    if is_full_refusal:
        exact = stripped == REFUSAL
        result.update({
            "valid": exact,
            "refused": True,
            "partial": False,
            "invalid_citations": [],
            "n_citations": 0,
            "truncated": False,
            "reason": "refusal" if exact else "refusal mismatch",
        })
        return result

    # Partial-refusal path (Q37-style): validated like a normal answer --
    # still needs at least one citation for the part it DID answer, still
    # needs every cited index to be in range, still can't be truncated.
    # The only difference from a plain answer is we tag partial=True so
    # callers (and the refusal recall/precision counters) can report it
    # separately rather than silently lumping it into either bucket.
    if truncated:
        result["reason"] = "truncated answer"
        result["partial"] = is_partial
        return result
    if n_citations == 0:
        result["reason"] = "missing citations"
        result["partial"] = is_partial
        return result
    if invalid:
        result["invalid_citations"] = invalid
        result["reason"] = f"invalid citations {invalid}"
        result["partial"] = is_partial
        return result

    result["valid"] = True
    result["refused"] = False
    result["partial"] = is_partial
    result["reason"] = "partial" if is_partial else "ok"
    return result


def answer_question(question: str, retriever: Retriever, *, k: int = 12,
                    final_k: int = 5, reranker=None, tier: str = "MAIN",
                    system: str = ANSWER_SYSTEM) -> Answer:
    """Answer a question using the retrieval pipeline and enforce constraints.

    Steps:
    1. Retrieve (k) hits.
    2. Optionally rerank to final_k.
    3. Generate answer -- using `system`, NOT whatever RagPipeline defaults to.
    4. Validate answer; if invalid and not a refusal (full or partial),
       fall back to full refusal.

    `system` defaults to the module-level ANSWER_SYSTEM (V2) but Part C4's
    A/B comparison should call this twice, explicitly, with
    system=ANSWER_SYSTEM_V1 and system=ANSWER_SYSTEM_V2, to get a real
    strictness delta instead of comparing a prompt against itself.
    """
    from aip.rag import RagPipeline
    pipe = RagPipeline(retriever, reranker=reranker, k=k, final_k=final_k,
                        tier=tier, system=system)
    # ^ IMPORTANT: verify RagPipeline.__init__ actually accepts `system` (or
    # whatever it calls its prompt-override kwarg -- open aip/rag.py and
    # check). If it does NOT accept one yet, every run before this one used
    # the reference prompt, not ANSWER_SYSTEM_V1/V2, regardless of what this
    # file said -- see the note above this function's definition and the
    # verification steps below.
    rag_ans = pipe.answer(question)

    text = rag_ans.answer
    validation = validate_answer(text, len(rag_ans.hits))

    ans = Answer(
        question=question,
        text=text,
        hits=rag_ans.hits,
        refused=validation["refused"],
        partial=validation["partial"],
        citations_valid=validation["valid"] or validation["refused"],
        invalid_citations=validation["invalid_citations"],
        n_citations=validation["n_citations"],
        truncated=validation["truncated"],
    )

    # B3: if validation fails outright (bad citations / truncated / no
    # citations) and it wasn't already a clean full refusal, fall back to
    # the full refusal. A valid PARTIAL answer does NOT get overwritten here
    # -- only genuine failures do.
    if not validation["valid"] and not validation["refused"]:
        ans.text = REFUSAL
        ans.refused = True
        ans.partial = False
        ans.citations_valid = True
        ans.invalid_citations = []
        ans.n_citations = 0
        ans.truncated = False

    return ans


def answer_with_gold_context(question: str, gold_docs: list[str], *,
                             tier: str = "MAIN",
                             system: str = ANSWER_SYSTEM) -> Answer:
    # Generate an answer using gold (reference) documents as context.
    # This bypasses the retriever; gold_docs are provided directly.
    class _GoldHit:
        def __init__(self, doc_id: str, text: str):
            self.doc_id = doc_id
            self.text = text
    gold_hits = [_GoldHit(f"gold{i}", doc) for i, doc in enumerate(gold_docs)]
    context = delimit_untrusted(format_context(gold_hits, max_chars=8000))
    prompt = f"{context}\n\nQuestion: {question}\n\nAnswer with citations:"
    answer_text = chat(prompt, system=system, tier=tier, temperature=0.0, max_tokens=600).strip()

    validation = validate_answer(answer_text, len(gold_hits))
    ans = Answer(
        question=question,
        text=answer_text,
        hits=[],
        refused=validation["refused"],
        partial=validation["partial"],
        citations_valid=validation["valid"] or validation["refused"],
        invalid_citations=validation["invalid_citations"],
        n_citations=validation["n_citations"],
        truncated=validation["truncated"],
    )
    if not validation["valid"] and not validation["refused"]:
        ans.text = REFUSAL
        ans.refused = True
        ans.partial = False
        ans.citations_valid = True
        ans.invalid_citations = []
        ans.n_citations = 0
        ans.truncated = False
    return ans