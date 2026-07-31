"""Qwen (Hermes-style) adaptation profile.

The headline Phase 0 fix for "pi/Claude Code + Qwen underperforms": Qwen models
frequently emit tool calls as text — a Hermes-style ``<tool_call>{...}</tool_call>``
block inside ``content`` — instead of the structured ``tool_calls`` field a client
loop expects. When the serving stack doesn't parse those out, the agent loop breaks:
the client sees prose, not a call. This profile recovers them into proper OpenAI
``tool_calls`` so the client never has to know.

It also optionally translates an OpenAI ``response_format`` json_schema into a vLLM
``guided_json`` field for grammar-constrained structured output.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from ..config import ProfileConfig


def _tool_call_pattern(tags: list[str]) -> re.Pattern[str]:
    alt = "|".join(re.escape(t) for t in tags)
    # Non-greedy body; DOTALL so JSON may span newlines. Tolerates whitespace.
    return re.compile(rf"<(?:{alt})>\s*(.*?)\s*</(?:{alt})>", re.DOTALL)


def _new_call_id() -> str:
    return "call_" + uuid.uuid4().hex[:24]


def _coerce_tool_call(obj: Any) -> dict[str, Any] | None:
    """Turn a parsed ``{"name":..,"arguments":..}`` object into an OpenAI tool_call.

    Accepts ``arguments`` or ``parameters`` for the args, and tolerates args given
    as either a JSON object or an already-serialised string.
    """
    if not isinstance(obj, dict):
        return None
    name = obj.get("name") or obj.get("function")
    if not isinstance(name, str) or not name:
        return None
    args = obj.get("arguments")
    if args is None:
        args = obj.get("parameters")
    if args is None:
        args = {}
    if isinstance(args, str):
        arguments = args  # trust the model's own serialisation
    else:
        arguments = json.dumps(args, ensure_ascii=False)
    return {
        "id": _new_call_id(),
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def recover_tool_calls(
    content: str, pattern: re.Pattern[str]
) -> tuple[str, list[dict[str, Any]]]:
    """Extract narrated tool calls from ``content``.

    Returns ``(cleaned_content, tool_calls)``. Blocks that don't parse as a valid
    tool-call object are left in the content untouched (better to surface odd text
    than to silently drop it).
    """
    tool_calls: list[dict[str, Any]] = []
    leftover_spans: list[str] = []
    last = 0
    for m in pattern.finditer(content):
        call = None
        body = m.group(1).strip()
        try:
            call = _coerce_tool_call(json.loads(body))
        except (json.JSONDecodeError, ValueError):
            call = None
        if call is None:
            continue  # leave this block in the content
        leftover_spans.append(content[last : m.start()])
        tool_calls.append(call)
        last = m.end()
    if not tool_calls:
        return content, []
    leftover_spans.append(content[last:])
    cleaned = "".join(leftover_spans).strip()
    return cleaned, tool_calls


class QwenProfile:
    name = "qwen3"

    def __init__(self, cfg: ProfileConfig | None = None) -> None:
        self.cfg = cfg or ProfileConfig()
        self._pattern = _tool_call_pattern(self.cfg.tool_call_tags)

    # -- request ----------------------------------------------------------
    def prepare_request(self, payload: dict[str, Any], upstream_model: str) -> dict[str, Any]:
        out = dict(payload)
        out["model"] = upstream_model
        out.pop("reasoning_effort", None)  # Deliberate-only field; never forward it
        if self.cfg.guided_json:
            self._apply_guided_json(out)
        return out

    def _apply_guided_json(self, payload: dict[str, Any]) -> None:
        rf = payload.get("response_format")
        if not isinstance(rf, dict):
            return
        schema: Any = None
        if rf.get("type") == "json_schema":
            js = rf.get("json_schema")
            if isinstance(js, dict):
                schema = js.get("schema")
        if schema is not None:
            payload["guided_json"] = schema
            if self.cfg.guided_decoding_backend:
                payload["guided_decoding_backend"] = self.cfg.guided_decoding_backend

    # -- response ---------------------------------------------------------
    def adapt_response(self, response: dict[str, Any], *, had_tools: bool) -> dict[str, Any]:
        if not self.cfg.recover_tool_calls or not had_tools:
            return response
        choices = response.get("choices")
        if not isinstance(choices, list):
            return response
        for choice in choices:
            self._adapt_choice(choice)
        return response

    def _adapt_choice(self, choice: dict[str, Any]) -> None:
        msg = choice.get("message")
        if not isinstance(msg, dict):
            return
        # If the backend already produced structured tool_calls, trust them.
        if msg.get("tool_calls"):
            return
        content = msg.get("content")
        if not isinstance(content, str) or "<" not in content:
            return
        cleaned, calls = recover_tool_calls(content, self._pattern)
        if not calls:
            return
        msg["tool_calls"] = calls
        msg["content"] = cleaned or None
        # A tool-calling turn should report the matching finish_reason.
        if choice.get("finish_reason") in (None, "stop", "length"):
            choice["finish_reason"] = "tool_calls"
