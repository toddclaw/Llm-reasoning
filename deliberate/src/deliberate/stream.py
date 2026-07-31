"""Turn a complete chat completion into an OpenAI-style SSE chunk stream.

Used when the client asked for ``stream: true`` but the request carried tools: we
call the backend non-streaming so the Qwen adapter can recover tool calls from the
full text, then re-emit the (repaired) result as a synthetic stream. Requests
without tools are streamed straight through and never touch this module.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any


def _chunk(base_id: str, created: int, model: str, choice_delta: dict[str, Any]) -> str:
    payload = {
        "id": base_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [choice_delta],
    }
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def synthesize_sse(response: dict[str, Any]) -> Iterator[str]:
    """Yield SSE lines reproducing ``response`` as a streamed completion."""
    base_id = response.get("id", "chatcmpl-deliberate")
    created = int(response.get("created", time.time()))
    model = response.get("model", "unknown")
    choices = response.get("choices") or [{}]

    for index, choice in enumerate(choices):
        msg = choice.get("message") or {}
        finish = choice.get("finish_reason")

        # 1) role
        yield _chunk(base_id, created, model,
                     {"index": index, "delta": {"role": "assistant"}, "finish_reason": None})

        # 2) content (single delta is fine for a synthetic stream)
        content = msg.get("content")
        if content:
            yield _chunk(base_id, created, model,
                         {"index": index, "delta": {"content": content}, "finish_reason": None})

        # 3) tool calls, one delta each (with the streaming ``index`` field)
        for i, call in enumerate(msg.get("tool_calls") or []):
            delta_call = {
                "index": i,
                "id": call.get("id"),
                "type": call.get("type", "function"),
                "function": call.get("function", {}),
            }
            yield _chunk(base_id, created, model,
                         {"index": index, "delta": {"tool_calls": [delta_call]},
                          "finish_reason": None})

        # 4) terminal chunk
        yield _chunk(base_id, created, model,
                     {"index": index, "delta": {}, "finish_reason": finish or "stop"})

    yield "data: [DONE]\n\n"
