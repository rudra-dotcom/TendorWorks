"""Deterministic intake guard, separate from applicability and engineering validation."""

import re

POLICY_VERSION = "2026-11-17-v1"
INJECTION = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|system|developer)\s+instructions|"
    r"(?:reveal|print|show|extract)\s+(?:the\s+)?(?:system prompt|api keys?|passwords?|secrets?)|"
    r"(?:bypass|disable)\s+(?:the\s+)?(?:guardrails?|validation|approval)|"
    r"pretend\s+(?:to\s+be|you\s+are)\s+(?:a\s+)?(?:system|administrator)",
    re.I,
)
WORK = re.compile(
    r"\b(build|building|construct(?:ion)?|school|office|hospital|road|bridge|railway|"
    r"foundation|renovat\w*|repair\w*|estimate|boq|tender|drain\w*|waterproof\w*|"
    r"plaster\w*|paint\w*|civil|plinth|community hall)\b",
    re.I,
)
OFF_TOPIC = re.compile(
    r"\b(recipe|horoscope|dating|poem|joke|stock tips|movie review|football score)\b", re.I
)


def assess_brief(brief):
    text = brief.description
    if INJECTION.search(text):
        return {
            "allowed": False,
            "code": "instruction_override",
            "message": "Remove instructions to override controls or disclose secrets; submit only the works brief.",
        }
    if OFF_TOPIC.search(text) or not WORK.search(text):
        return {
            "allowed": False,
            "code": "out_of_scope",
            "message": "Tenderworks supports public-works estimates. Describe the construction or maintenance work, authority and location.",
        }
    return {
        "allowed": True,
        "code": "in_scope",
        "message": "Scope screening passed; applicability still requires validation.",
    }
