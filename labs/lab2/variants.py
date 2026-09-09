#!/usr/bin/env python3
"""Lab 2 — the configurations under test.

Each variant is a callable `str -> dict`. `grid.py` runs them all through the
same harness, so the only thing that differs between rows of your table is the
thing you intended to differ.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import Field

from aip.llm import StructuredOutputError, structured

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from labs.lab1.extract import (  # noqa: E402
    SYSTEM_PROMPT, TicketRecord, apply_business_rules, extract_deterministic,
)

# ---------------------------------------------------------------------------
# A1 — your six chosen examples.
# ---------------------------------------------------------------------------
# TODO A1: choose 6 dev-set tickets. For EACH, write one line saying what it
#          teaches that prose cannot. Pick edges, not averages (T2 §2.2):
#            - the billing/complaint boundary
#            - a ticket with no policy number (teaches null)
#            - a Hinglish ticket
#            - a satisfied-but-urgent ticket (the sentiment/urgency trap)
#            - a ticket whose policy number is only in a quoted reply
#            - one you got wrong in Lab 1
FEW_SHOT_IDS: list[str] = [
    "T0097",   # teaches: billing/complaint boundary — angry, threatens the
               # ombudsman, but the customer wants the double-debit refunded,
               # so it's billing, not complaint. Tone != category.
    "T0021",   # teaches: null policy_number — "my policy" is mentioned but
               # no AUR-####### string appears anywhere; must return null,
               # not invent one from context (Aurora Gold plan is named,
               # policy number is not).
    "T0100",   # teaches: Hinglish detection — "Kripya fix teh NACH mandate.
               # Jaldi karo please." mixes transliterated Hindi into English;
               # language must be 'hi-en', not 'en'.
    "T0222",   # teaches: sentiment and urgency are graded independently —
               # 'satisfied' tone ("Very good") does not automatically mean
               # urgency=1; each must be judged on its own definition.
    "T0238",   # teaches: quoted-reply caution — the auto-reply block below
               # the live message carries an SR- reference number, not an
               # AUR- policy number; the extractor must not confuse a
               # quoted support reference with a real policy_number, and
               # correctly returns null since no AUR- string exists live.
    "T0054",   # teaches: got wrong in Lab 1 (urgency + escalate both
               # missed) — "mis-sold... 5-month waiting period... full
               # refund" reads calm in text but the mis-selling complaint
               # + refund demand should land at urgency 4/escalate=true;
               # model likely under-weighted the complaint's severity
               # since there's no shouting or ALL CAPS.
]


def load_examples(ids: list[str]) -> list[dict]:
    rows = [json.loads(l) for l in
            (ROOT / "data/eval/extraction_dev.jsonl").open(encoding="utf-8")]
    by_id = {r["id"]: r for r in rows}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise KeyError(f"unknown example ids: {missing}")
    return [by_id[i] for i in ids]


def few_shot_block(ids: list[str]) -> str:
    """TODO A2: render the examples into the prompt.

    The example output format must be byte-identical to the format you are
    asking the model to produce. A mismatch here is a classic own goal.
    """
    examples = load_examples(ids)

    # Hand-written evidence quotes — gold labels don't include `evidence`,
    # since it's a model-generated justification, not a ground-truth field.
    EVIDENCE_OVERRIDES = {
        "T0097": "Refund it or I am going to teh ombudsman",
        "T0021": "the app crashes... this needs to be resolved before tomorrow morning",
        "T0100": "Kripya fix teh NACH mandate",
        "T0222": "The cashless approval came through in under an hour. Very good.",
        "T0238": "I submitted a portability request 21 days ago and heard nothing",
        "T0054": "Your agent mis-sold me this policy... I want a full refund",
    }

    blocks = []
    for ex in examples:
        gold = ex["expected"]
        shown_output = {
            "evidence": EVIDENCE_OVERRIDES[ex["id"]],
            "category": gold["category"],
            "urgency": gold["urgency"],
            "sentiment": gold["sentiment"],
            "product": gold["product"],
            "language": gold["language"],
        }
        blocks.append(
            f"Ticket:\n{ex['input']}\n\nOutput:\n{json.dumps(shown_output)}"
        )
    return "\n\n---\n\n".join(blocks)


# ---------------------------------------------------------------------------
# The variants
# ---------------------------------------------------------------------------
def zero_shot(ticket: str, tier: str = "SMALL") -> dict:
    """TODO B: Lab 1 Part C, no examples. This is your baseline."""
    try:
        model_rec = structured(
            ticket,
            schema=TicketRecord,
            system=SYSTEM_PROMPT,
            tier=tier,
        )
        fields = model_rec.model_dump()
    except StructuredOutputError as e:
        fields = TicketRecord(
            evidence="", category="information", urgency=1,
            sentiment="neutral", product="unknown", language="en",
            needs_human_review=True, review_reason=str(e),
        ).model_dump()
    fields.update(extract_deterministic(ticket))
    return apply_business_rules(fields, ticket)



def few_shot(ticket: str, tier: str = "SMALL") -> dict:
    """TODO B: zero_shot + the few-shot block."""
    examples_block = few_shot_block(FEW_SHOT_IDS)
    system_with_examples = f"{SYSTEM_PROMPT}\n\nExamples:\n\n{examples_block}"
    try:
        model_rec = structured(
            ticket,
            schema=TicketRecord,
            system=system_with_examples,
            tier=tier,
        )
        fields = model_rec.model_dump()
    except StructuredOutputError as e:
        fields = TicketRecord(
            evidence="", category="information", urgency=1,
            sentiment="neutral", product="unknown", language="en",
            needs_human_review=True, review_reason=str(e),
        ).model_dump()
    fields.update(extract_deterministic(ticket))
    return apply_business_rules(fields, ticket)


class TicketRecordReasoned(TicketRecord):
    """TODO B: add a `reasoning: str` field FIRST (T2 §3.3).

    Pydantic keeps declaration order, and field order in the JSON Schema
    influences generation order. Putting reasoning first makes it condition the
    answer; putting it last makes it a post-hoc rationalisation. You want the
    first. Measure the difference in output tokens.
    """
    reasoning: str = Field(
        description="Think step by step about this ticket BEFORE deciding "
                     "any field below: what is the customer actually asking "
                     "for, what is their tone, and what evidence in the "
                     "text supports each judgement. 2-3 sentences."
    )


def few_shot_reasoned(ticket: str, tier: str = "SMALL") -> dict:
    """TODO B: few_shot with TicketRecordReasoned."""
    examples_block = few_shot_block(FEW_SHOT_IDS)
    system_with_examples = f"{SYSTEM_PROMPT}\n\nExamples:\n\n{examples_block}"
    try:
        model_rec = structured(
            ticket,
            schema=TicketRecordReasoned,
            system=system_with_examples,
            tier=tier,
        )
        fields = model_rec.model_dump()
    except StructuredOutputError as e:
        fields = TicketRecordReasoned(
            reasoning="", evidence="", category="information", urgency=1,
            sentiment="neutral", product="unknown", language="en",
            needs_human_review=True, review_reason=str(e),
        ).model_dump()
    fields.update(extract_deterministic(ticket))
    return apply_business_rules(fields, ticket)


def cascade(ticket: str) -> dict:
    """TODO C: SMALL first; escalate to MAIN on a trigger you choose.

    Triggers, roughly in ascending order of how well they work:
      - validation failed                      (free, weak: misses confident errors)
      - evidence field empty or very short     (free, surprisingly decent)
      - urgency >= 4                           (free, but it is not a confidence signal)
      - two SMALL samples at T=0.7 disagree    (2x small cost, much the best)

    Record which path each ticket took -- set rec['_path'] = 'small' | 'large'
    so grid.py can report the escalation rate.
    """
    try:
        sample_1 = structured(
            ticket, schema=TicketRecord, system=SYSTEM_PROMPT,
            tier="SMALL",
        )
    except StructuredOutputError:
        sample_1 = None

    # Trigger 1: Validation failure or empty/short evidence
    needs_escalation = (
        sample_1 is None
        or not sample_1.evidence
        or len(sample_1.evidence.strip()) < 5
    )

    # Trigger 2: Self-consistency disagreement at T=0.7 (different cache key)
    if not needs_escalation:
        try:
            sample_2 = structured(
                ticket, schema=TicketRecord, system=SYSTEM_PROMPT,
                tier="SMALL", temperature=0.7,
            )
            disagree = (
                sample_1.model_dump(exclude={"needs_human_review", "review_reason"})
                != sample_2.model_dump(exclude={"needs_human_review", "review_reason"})
            )
            if disagree:
                needs_escalation = True
        except StructuredOutputError:
            needs_escalation = True

    if needs_escalation:
        try:
            large_rec = structured(
                ticket, schema=TicketRecord, system=SYSTEM_PROMPT,
                tier="MAIN",
            )
            fields = large_rec.model_dump()
        except StructuredOutputError as e:
            if sample_1:
                fields = sample_1.model_dump()
            else:
                fields = TicketRecord(
                    evidence="", category="information", urgency=1,
                    sentiment="neutral", product="unknown", language="en",
                ).model_dump()
            fields["needs_human_review"] = True
            fields["review_reason"] = str(e)
        path = "large"
    else:
        fields = sample_1.model_dump()
        path = "small"

    fields.update(extract_deterministic(ticket))
    fields = apply_business_rules(fields, ticket)
    fields["_path"] = path
    return fields


VARIANTS = {
    "zero_shot": lambda t: zero_shot(t, "SMALL"),
    "zero_shot_main": lambda t: zero_shot(t, "MAIN"),
    "few_shot": lambda t: few_shot(t, "SMALL"),
    "few_shot_main": lambda t: few_shot(t, "MAIN"),
    "few_shot_reasoned": lambda t: few_shot_reasoned(t, "SMALL"),
    "few_shot_reasoned_main": lambda t: few_shot_reasoned(t, "MAIN"),
    "cascade": cascade,
}
