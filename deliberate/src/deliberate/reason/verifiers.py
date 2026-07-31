"""Verifiers and candidate selection for best-of-N.

Always prefer a deterministic check; fall back to a judge model only when nothing
better applies. The selector reports *which* verifier decided, so downstream
confidence can reflect how strong the check was (deterministic > judge).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .client import ModelClient
from .state import Message
from .util import extract_json_object


def _valid_tool_calls(msg: Message) -> bool:
    calls = msg.get("tool_calls") or []
    if not calls:
        return False
    for c in calls:
        fn = c.get("function") or {}
        if not fn.get("name") or not isinstance(fn.get("arguments"), str):
            return False
        try:
            json.loads(fn["arguments"])
        except (json.JSONDecodeError, ValueError):
            return False
    return True


def _valid_json(msg: Message, schema: dict | None) -> bool:
    obj = extract_json_object(msg.get("content") or "")
    if obj is None:
        return False
    if schema is None:
        return True
    try:
        import jsonschema

        jsonschema.validate(obj, schema)
        return True
    except Exception:  # noqa: BLE001 - any validation failure means invalid
        return False


@dataclass
class Selection:
    message: Message
    index: int
    verifier: str  # which check decided (tool | json | consistency | judge | first)
    passing: int  # how many candidates passed the structural check (0 if n/a)


async def select_best(
    candidates: list[Message],
    *,
    client: ModelClient,
    question: str,
    tools: list[dict] | None = None,
    response_format: dict | None = None,
    selector: str = "auto",
) -> Selection:
    if len(candidates) == 1:
        return Selection(candidates[0], 0, "single", 0)

    # 1) structural verifier where one applies
    if tools:
        passing = [i for i, m in enumerate(candidates) if _valid_tool_calls(m)]
        if passing:
            best = min(passing, key=lambda i: len(json.dumps(candidates[i].get("tool_calls"))))
            return Selection(candidates[best], best, "tool", len(passing))
    if response_format:
        schema = _schema_of(response_format)
        passing = [i for i, m in enumerate(candidates) if _valid_json(m, schema)]
        if passing:
            best = min(passing, key=lambda i: len(candidates[i].get("content") or ""))
            return Selection(candidates[best], best, "json", len(passing))

    # 2) consistency (majority of normalised answers), cheap and deterministic
    if selector in ("auto", "consistency"):
        idx = _majority_index(candidates)
        if idx is not None:
            return Selection(candidates[idx], idx, "consistency", 0)

    # 3) judge model picks the best
    if selector in ("auto", "judge"):
        idx = await _judge_pick(candidates, client=client, question=question)
        return Selection(candidates[idx], idx, "judge", 0)

    return Selection(candidates[0], 0, "first", 0)


def _schema_of(response_format: dict) -> dict | None:
    if response_format.get("type") == "json_schema":
        js = response_format.get("json_schema") or {}
        return js.get("schema")
    return None


def _majority_index(candidates: list[Message]) -> int | None:
    counts: dict[str, list[int]] = {}
    for i, m in enumerate(candidates):
        key = (m.get("content") or "").strip().lower()
        counts.setdefault(key, []).append(i)
    best_key = max(counts, key=lambda k: len(counts[k]))
    if best_key and len(counts[best_key]) > 1:
        return counts[best_key][0]
    return None


async def _judge_pick(candidates: list[Message], *, client: ModelClient, question: str) -> int:
    listing = "\n\n".join(
        f"[{i}] {(m.get('content') or '(tool call)')[:1500]}" for i, m in enumerate(candidates)
    )
    prompt = (
        "You are selecting the single best answer to a question. "
        "Reply with ONLY a JSON object {\"best_index\": <int>}.\n\n"
        f"Question:\n{question}\n\nCandidates:\n{listing}"
    )
    result = await client.complete([{"role": "user", "content": prompt}], temperature=0.0)
    obj = extract_json_object(result.text) or {}
    idx = obj.get("best_index")
    if isinstance(idx, int) and 0 <= idx < len(candidates):
        return idx
    return 0
