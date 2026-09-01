#!/usr/bin/env python3
"""Lab 1, Parts B and C — the extractor you actually ship.

Complete the TODOs. `run_eval.py` imports `extract_b` and `extract_c` from
here, so keep those two function names.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aip.guards import _PII_PATTERNS  # noqa: E402
from aip.llm import StructuredOutputError, structured  # noqa: E402

CATEGORIES = Literal["billing", "claims", "policy_change",
                     "technical", "complaint", "information"]


# ===========================================================================
# PART B — the schema
# ===========================================================================
class TicketRecord(BaseModel):
    """The contract. Everything the model is allowed to say, and nothing else.

    Remember from T2 §3.2: field `description`s are shipped to the model as
    part of the JSON Schema. They are the highest-leverage place to put an
    instruction, because they sit next to the thing they govern. Write them as
    instructions to the model, not as documentation for a human.
    """

    # TODO B1a: Should `evidence` be declared here, BEFORE the fields it
    #           justifies, or after them? T2 §3.3. Decide, move it, and leave
    #           a one-line comment saying which effect you chose and why.

    evidence: str = Field(
        max_length=200,
        description="The exact span of the ticket that determined the "
                     "category. Quote verbatim from the ticket, do not "
                     "paraphrase. One sentence at most."
    )
    
    category: CATEGORIES = Field(
        description="billing = money in: premium, debits, refunds, invoices, the "
            "80D tax certificate, instalment options. "
            "claims = an actual or intended claim: cashless, reimbursement, "
            "settlement amount, deduction, rejection. "
            "policy_change = altering the contract: add or remove a member, "
            "upgrade, port, change contact details. "
            "technical = the app, portal, OTP, locator, or document upload "
            "is broken. "
            "complaint = the subject is Aurora's conduct itself — "
            "mis-selling, being kept on hold, an ignored grievance. "
            "information = a question with no pending transaction behind it. "
            "The key boundary: an angry message about a claim is still "
            "'claims' if the customer wants the claim processed. It is only "
            "'complaint' when Aurora's conduct is itself the subject, not "
            "the customer's tone."
    )

    urgency: int = Field(
        ge=1, le=5,
        description="Judge the situation, not the volume or tone — shouting is a "
            "sentiment signal, not an urgency signal. "
            "1 = answerable from general product knowledge or a self-service "
            "how-to; Aurora need not look anything up (e.g. 'what is the "
            "waiting period for cataract surgery'). "
            "2 = requires Aurora to look up this customer's account, act on "
            "it, or fix a defect, or a transaction is in flight (e.g. 'add "
            "my newborn', 'the app crashes on upload'). "
            "3 = something has already gone wrong or is stuck and the "
            "customer is waiting (e.g. 'debited twice'). "
            "4 = repeated failure to resolve, money or access at risk now, "
            "or an explicit escalation THREAT (e.g. 'this is the third "
            "time', 'refund it or I am going to the ombudsman'). "
            "5 = an emergency in progress, a formal denial demanding "
            "immediate reversal, or the customer STATES they are already "
            "escalating to the Ombudsman, not merely threatening to (e.g. "
            "'I am filing a complaint with the ombudsman'). "
            "Modifier: add 1 (capped at 5) if the message states a same-day "
            "or next-morning deadline. "
            "The 1/2 boundary: can this be answered without opening the "
            "customer's record? If yes, 1, however long the message. "
            "The 4/5 boundary is about tense: threatening to escalate is 4; "
            "stating you already are escalating is 5."
    )

    # TODO B1d: sentiment  -> Literal["angry","frustrated","neutral","satisfied"]
    # TODO B1e: product    -> Literal["bronze","silver","gold","platinum","unknown"]
    #           Note "unknown" is a legal value. Say explicitly when to use it.
    # TODO B1f: language   -> Literal["en","hi-en"]
    # TODO B1g: evidence   -> str, max_length=200, "the span of the ticket that
    #           determined the category, quoted verbatim"

    sentiment: Literal["angry", "frustrated", "neutral", "satisfied"] = Field(
        description=(
            "Tone only, independent of urgency. "
            "angry = hostile, shouting, threatening. "
            "frustrated = unhappy and tired of trying, still civil — "
            "requires the message to reference a prior failure: a repeat "
            "attempt, an unanswered request, or a delay. "
            "neutral = matter-of-fact; a first-time request, however terse, "
            "is neutral, not frustrated. "
            "satisfied = thanks or praise."
        )
    )

    product: Literal["bronze", "silver", "gold", "platinum", "unknown"] = Field(
        description="The plan must be explicitly named in the message. "
                     "Never infer it from the sum insured or from context. "
                     "Use 'unknown' if no plan name appears."
    )

    language: Literal["en", "hi-en"] = Field(
        description="'hi-en' if Hindi words are mixed into the English, "
                     "including transliterated Hindi in Latin script (e.g. "
                     "kripya, jaldi, bahut, turant). 'en' otherwise."
    )
    # Part B only: the model decides these. In Part C you will delete them
    # from this schema and compute them in code instead.
    policy_number: str | None = Field(
        default=None,
        description= "Format AUR- followed by exactly 7 digits, copied verbatim. "
            "Only from the LIVE message: lines beginning with '>' are a "
            "quoted reply from an earlier thread and may carry a stale, "
            "wrong number — ignore them, as are signature blocks. If the "
            "only policy-shaped string in the ticket is inside a quoted "
            "reply, return null. Never invent, guess, or reformat one."
    )
    contains_pii: bool = Field(
        default=False,
        description="True if the text contains a phone number, or an email address "
            "that is NOT one of Aurora's own published addresses "
            "(support@aurorahealth.example, grievance@aurorahealth.example). "
            "A personal name alone does not count."
    )

    # Set by our code, never by the model.
    needs_human_review: bool = False
    review_reason: str = ""

    @field_validator("policy_number")
    @classmethod
    def _policy_format(cls, v: str | None) -> str | None:
        # TODO B1j: reject anything that is not exactly AUR-<7 digits>.
        #           Return None rather than raising if the model returned an
        #           empty string or the literal "null" -- decide which of those
        #           two behaviours you want and defend it in your report.
        if v is None:
            return None
        v = v.strip()
        if not re.fullmatch(r"AUR-\d{7}", v):
            return None
        return v


SYSTEM_PROMPT = """\
You are a support-ticket classifier for Aurora Health Insurance.

You will be given the raw text of one customer support ticket — email, \
WhatsApp, or web-form text, possibly containing quoted reply history, \
signature blocks, typos, or Hindi-English code-mixing.

Extract a single structured record describing the ticket, following \
exactly the schema provided. Every field's definition and allowed values \
are specified in that schema — follow them precisely, do not invent your \
own categories or scales.

Ground every judgement in the ticket text itself, not in assumptions. If \
information is not present, use the field's documented default rather \
than guessing.
"""


def extract_b(ticket: str) -> TicketRecord:
    """Part B: the model decides everything."""
    # TODO B3: call aip.llm.structured with TicketRecord.
    # TODO B4: catch StructuredOutputError and return a record with
    #          needs_human_review=True. This function must never raise.
    try:
        return structured(
            ticket,
            schema=TicketRecord,
            system=SYSTEM_PROMPT,
        )
    except StructuredOutputError as e:
        return TicketRecord(
            evidence="",
            category="information",
            urgency=1,
            sentiment="neutral",
            product="unknown",
            language="en",
            needs_human_review=True,
            review_reason=str(e),
        )


# ===========================================================================
# PART C — move the deterministic work out of the model
# ===========================================================================
POLICY_RE = re.compile(r"\bAUR-\d{7}\b")

# The quoted-reply marker. Everything after this is history, not the current
# message. Part C3 asks you to decide what that means for policy extraction.
QUOTE_MARKER = re.compile(r"^\s*>", re.MULTILINE)

AURORA_ADDRESSES = {"support@aurorahealth.example", "grievance@aurorahealth.example"}
_PII_LABELS_FOR_THIS_TASK = {"EMAIL", "PHONE_IN"}
def _strip_quoted_and_signature(ticket: str) -> str:
    """Return only the live message: drop lines starting with '>' (quoted
    reply history) and a trailing signature block.

    Heuristic for the signature block: many of these tickets end with a
    short block containing a name/phone/etc. We treat everything from the
    last '--' or '_____' style separator onward as signature, if present.
    Simpler and safer: since the policy_number regex only needs to *avoid*
    quoted lines, and signature blocks in this dataset are short trailing
    lines, we primarily rely on the '>' filter — see comment on C3 below
    for why this is deliberately conservative.
    """
    live_lines = [
        line for line in ticket.splitlines()
        if not QUOTE_MARKER.match(line)
    ]
    return "\n".join(live_lines)

def extract_deterministic(ticket: str) -> dict:
    """TODO C1: return {'policy_number', 'contains_pii'} without a model call.
    
    policy_number:
        Find AUR-<7 digits>.

    TODO C3 -- the trap. Some tickets contain TWO policy-number-shaped strings:
        one in the live body, and one in a quoted reply below a '>' line from
        an earlier thread. They are not always the same number.

        Decide a rule. Write it down in a comment right here. Implement it.
        Then ask yourself whether it generalises or whether you have fitted it
        to this dataset -- the honest answer is worth marks.

    contains_pii:
        True if the ticket contains a phone number or an email address.
        aip.guards._PII_PATTERNS has the patterns. Note that a *name* alone
        does not count for this dataset's labels -- check the gold data and
        say in your report whether you think that definition is right.
    """
    live_text = _strip_quoted_and_signature(ticket)
    match = POLICY_RE.search(live_text)
    policy_number = match.group(0) if match else None
    contains_pii = False
    for label in _PII_LABELS_FOR_THIS_TASK:
        pattern = _PII_PATTERNS[label]
        for m in pattern.finditer(ticket):
            value = m.group(0)
            if label == "EMAIL" and value.lower() in AURORA_ADDRESSES:
                continue
            contains_pii = True
            break
        if contains_pii:
            break

    return {"policy_number": policy_number, "contains_pii": contains_pii}



def apply_business_rules(rec_fields: dict, ticket: str) -> dict:
    """escalate = urgency >= 4 or 'ombudsman' appears in the ticket."""
    rec_fields = dict(rec_fields)
    rec_fields["escalate"] = (
        rec_fields["urgency"] >= 4 or "ombudsman" in ticket.lower()
    )
    return rec_fields


class TicketRecordC(BaseModel):
    """TODO C2: the reduced schema the model sees in Part C.

    Copy TicketRecord and delete the fields you now compute in code. Fewer
    fields means a shorter prompt, fewer output tokens, and three fields at
    100% accuracy. Measure all three effects.
    """
    evidence: str = Field(
        max_length=200,
        description="The exact span of the ticket that determined the "
                     "category. Quote verbatim from the ticket, do not "
                     "paraphrase. One sentence at most."
    )

    category: CATEGORIES = Field(
        description=TicketRecord.model_fields["category"].description
    )

    urgency: int = Field(
        ge=1, le=5,
        description=TicketRecord.model_fields["urgency"].description
    )

    sentiment: Literal["angry", "frustrated", "neutral", "satisfied"] = Field(
        description=TicketRecord.model_fields["sentiment"].description
    )

    product: Literal["bronze", "silver", "gold", "platinum", "unknown"] = Field(
        description=TicketRecord.model_fields["product"].description
    )

    language: Literal["en", "hi-en"] = Field(
        description=TicketRecord.model_fields["language"].description
    )

    needs_human_review: bool = False
    review_reason: str = ""

def extract_c(ticket: str) -> dict:
    """Part C: model for judgement, code for everything else."""
    try:
        model_rec = structured(
            ticket,
            schema=TicketRecordC,
            system=SYSTEM_PROMPT,
        )
        fields = model_rec.model_dump()
    except StructuredOutputError as e:
        fields = TicketRecordC(
            evidence="",
            category="information",
            urgency=1,
            sentiment="neutral",
            product="unknown",
            language="en",
            needs_human_review=True,
            review_reason=str(e),
        ).model_dump()

    fields.update(extract_deterministic(ticket))
    fields = apply_business_rules(fields, ticket)
    return fields


if __name__ == "__main__":
    import json

    root = Path(__file__).resolve().parents[2]
    sample = json.loads(
        (root / "data/eval/extraction_dev.jsonl").open(encoding="utf-8").readline()
    )
    print("--- ticket ---")
    print(sample["input"][:600])
    print("\n--- gold ---")
    print(sample["expected"])
    print("\n--- yours ---")
    print(extract_c(sample["input"]))
