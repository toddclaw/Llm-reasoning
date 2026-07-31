"""Difficulty classifier.

Kahneman's real point is that System 2 is costly and should be recruited
*selectively*. A cheap heuristic estimates task hardness so easy prompts stay fast
and only hard ones pay for deliberation. Heuristic-only by default (no extra model
call); a model-backed classifier is a later refinement.
"""

from __future__ import annotations

import re

TRIVIAL = "trivial"
MODERATE = "moderate"
HARD = "hard"

_HARD_HINTS = re.compile(
    r"\b(prove|derive|design|analyz|evaluate|compare|trade-?off|optimi|why|"
    r"explain how|step by step|debug|refactor|algorithm|complexity)\b",
    re.IGNORECASE,
)
_MATH = re.compile(r"\d+\s*[-+*/^]\s*\d+|\bsolve\b|\bcalculate\b|\bhow many\b", re.IGNORECASE)


def classify_difficulty(messages: list[dict], *, has_tools: bool = False) -> str:
    """Return ``trivial | moderate | hard`` from the last user message."""
    text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            text = str(m.get("content", ""))
            break

    words = len(text.split())
    has_hard = bool(_HARD_HINTS.search(text))
    is_math = bool(_MATH.search(text))
    multi_sentence = text.count("?") + text.count(".") >= 3

    if has_hard or (is_math and words > 12) or (multi_sentence and words > 60):
        return HARD
    if words <= 12 and not has_hard and not is_math:
        return TRIVIAL
    return MODERATE
