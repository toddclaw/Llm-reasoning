"""The `frame` stage — Inquiry & Debiasing (the Kahneman pre-flight).

Before the model commits to an answer, it answers a different question first: *what
do I need to know to answer this well, and where am I about to fool myself?* The
result — a Framing Brief — is injected as grounding for the answer stages, and its
residual unknowns + calibrated confidence become the honesty artifacts the layer
reports. See docs/deliberate/02-reasoning-modules.md §2.
"""

from __future__ import annotations

from ..client import ModelClient
from ..state import ReasoningState
from ..util import clamp01, extract_json_object, system_message

_BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "reframed_question": {"type": "string"},
        "substitution_risk": {"type": "string"},
        "knowledge_requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "need": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["in_context", "retrievable", "unknown", "assumption"],
                    },
                },
                "required": ["need", "status"],
            },
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "answer_shape": {"type": "string"},
        "disconfirmer": {"type": "string"},
        "residual_unknowns": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["reframed_question", "answer_shape", "confidence"],
}

_INQUIRY_PROMPT = """You are the analytical pre-flight for another assistant. Do NOT \
answer the user's question. Instead analyse how to answer it well and where bias \
could creep in, then output ONLY a JSON object with these fields:
- reframed_question: the question restated precisely, in the asker's terms
- substitution_risk: is there an EASIER question one might answer instead of the real \
one? Name it, or "" if none. (Kahneman's substitution.)
- knowledge_requirements: list of {{need, status}} where status is one of \
in_context | retrievable | unknown | assumption
- assumptions: load-bearing assumptions being made explicit
- answer_shape: what a correct answer must contain to actually settle the question
- disconfirmer: the strongest evidence or consideration that would make the obvious \
answer WRONG (guards confirmation bias)
- residual_unknowns: things that genuinely cannot be determined from what's available
- confidence: 0.0-1.0, calibrated — how likely a careful answer is to be correct, \
accounting for the unknowns and disconfirmer

User question:
{question}
"""


def _first_user_text(state: ReasoningState) -> str:
    for m in reversed(state.messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""


class FrameStage:
    id = "frame"

    def applicable(self, state: ReasoningState) -> bool:
        # Framing helps open-ended reasoning; skip pure tool-dispatch turns where the
        # job is to emit a call, not to deliberate.
        return not state.has_tools

    async def run(self, state: ReasoningState, client: ModelClient) -> None:
        question = _first_user_text(state)
        result = await client.complete(
            [{"role": "user", "content": _INQUIRY_PROMPT.format(question=question)}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "framing_brief", "schema": _BRIEF_SCHEMA}},
            temperature=0.2,
        )
        brief = extract_json_object(result.text)
        if not brief:
            state.log(self.id, "no_brief")
            return

        brief["confidence"] = clamp01(brief.get("confidence"), default=0.5)
        state.scratch["framing_brief"] = brief
        state.scratch["confidence"] = brief["confidence"]

        state.messages.insert(0, system_message(_grounding(brief)))
        state.log(self.id, "brief", confidence=brief["confidence"],
                  substitution=bool(brief.get("substitution_risk")),
                  unknowns=len(brief.get("residual_unknowns") or []))


def _grounding(brief: dict) -> str:
    lines = ["Before answering, keep this analysis in mind:"]
    if brief.get("reframed_question"):
        lines.append(f"- The real question: {brief['reframed_question']}")
    if brief.get("answer_shape"):
        lines.append(f"- A good answer must: {brief['answer_shape']}")
    if brief.get("substitution_risk"):
        lines.append(f"- Do NOT answer this easier question instead: {brief['substitution_risk']}")
    if brief.get("disconfirmer"):
        lines.append(f"- Check this could make the obvious answer wrong: {brief['disconfirmer']}")
    unknowns = brief.get("residual_unknowns") or []
    if unknowns:
        lines.append("- State these explicitly as unknowns rather than guessing: "
                     + "; ".join(map(str, unknowns)))
    assumptions = brief.get("assumptions") or []
    if assumptions:
        lines.append("- Surface these assumptions if they matter: " + "; ".join(map(str, assumptions)))
    return "\n".join(lines)
