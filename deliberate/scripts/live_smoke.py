#!/usr/bin/env python
"""Live smoke test: run Deliberate's full adapter path against a REAL Qwen endpoint.

This does not need a running server — it wires the FastAPI app in-process (so the
adapter, effort parsing, streaming synthesis and admission control all execute) and
lets the backend make real HTTPS calls upstream (honouring HTTPS_PROXY).

Usage:
    export DELIBERATE_UPSTREAM_URL="https://openrouter.ai/api/v1"   # any OpenAI-compatible base
    export DELIBERATE_UPSTREAM_MODEL="qwen/qwen3.5-397b-a17b"       # a Qwen-family model slug
    export DELIBERATE_UPSTREAM_KEY="sk-or-..."                       # provider API key
    python scripts/live_smoke.py

What it checks:
  1. Transparency (non-stream) — a plain question returns non-empty content.
  2. Transparency (stream)     — a streamed answer forwards and terminates with [DONE].
  3. Tool calling              — a request with a tool returns structured tool_calls
                                 (whether the provider parsed them or Deliberate
                                 recovered them from <tool_call> text).
  4. Recovery (best-effort)    — asks the model to emit a literal <tool_call> block as
                                 content; passes if Deliberate lifts it into tool_calls.
                                 NOTE: a provider that pre-parses tool calls may make
                                 this inconclusive — the recovery path is best proven
                                 against your own vLLM started WITHOUT --tool-call-parser.

Exit code is non-zero if a hard check fails; the best-effort recovery check only warns.
"""

from __future__ import annotations

import json
import os
import sys

from fastapi.testclient import TestClient

from deliberate.config import Config
from deliberate.server import build_app


def _env(name: str, required: bool = True, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        sys.exit(f"missing required env var {name} (see the module docstring)")
    return val


def build_client() -> TestClient:
    cfg = Config.model_validate(
        {
            "backends": {
                "base": {
                    "endpoint": _env("DELIBERATE_UPSTREAM_URL"),
                    "model": _env("DELIBERATE_UPSTREAM_MODEL"),
                    "profile": "qwen3",
                    "api_key": _env("DELIBERATE_UPSTREAM_KEY"),
                    "timeout_s": 120,
                }
            },
            "profiles": {"qwen3": {"recover_tool_calls": True}},
        }
    )
    return TestClient(build_app(cfg))


WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}


def main() -> int:
    client = build_client()
    failures = 0

    def check(name: str, ok: bool, detail: str = "", hard: bool = True) -> None:
        nonlocal failures
        mark = "PASS" if ok else ("FAIL" if hard else "WARN")
        print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
        if not ok and hard:
            failures += 1

    # 1. transparency, non-streaming
    r = client.post(
        "/v1/chat/completions",
        json={"model": "base", "messages": [{"role": "user", "content": "What is 2+2? Reply with just the number."}]},
    )
    ok = r.status_code == 200 and (r.json()["choices"][0]["message"].get("content") or "").strip() != ""
    check("transparency/non-stream", ok, f"status={r.status_code}, effort={r.headers.get('x-deliberate-effort')}")
    if r.status_code == 200:
        print("      answer:", repr((r.json()["choices"][0]["message"].get("content") or "")[:80]))

    # 2. transparency, streaming
    r = client.post(
        "/v1/chat/completions",
        json={"model": "base", "messages": [{"role": "user", "content": "Say hello in one word."}], "stream": True},
    )
    body = r.content.decode("utf-8", "replace")
    check("transparency/stream", r.status_code == 200 and "[DONE]" in body, f"status={r.status_code}")

    # 3. tool calling (provider-parsed or recovered — either is a pass)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "base",
            "messages": [{"role": "user", "content": "What's the weather in Paris? Use the tool."}],
            "tools": [WEATHER_TOOL],
            "tool_choice": "auto",
        },
    )
    calls = []
    if r.status_code == 200:
        calls = r.json()["choices"][0]["message"].get("tool_calls") or []
    check("tool-calling returns structured tool_calls", bool(calls), f"status={r.status_code}, n_calls={len(calls)}")
    if calls:
        print("      call:", json.dumps(calls[0]["function"], ensure_ascii=False)[:120])

    # 4. recovery (best-effort): force a raw <tool_call> block in content
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "base",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Output EXACTLY this and nothing else:\n"
                        '<tool_call>{"name": "get_weather", "arguments": {"city": "Paris"}}</tool_call>'
                    ),
                }
            ],
            "tools": [WEATHER_TOOL],  # arms the recovery path
        },
    )
    recovered = []
    if r.status_code == 200:
        recovered = r.json()["choices"][0]["message"].get("tool_calls") or []
    check(
        "recovery of narrated <tool_call> (best-effort)",
        bool(recovered),
        "if this WARNs, the provider likely pre-parses tool calls; test recovery against a raw vLLM",
        hard=False,
    )

    print()
    print("RESULT:", "OK" if failures == 0 else f"{failures} hard check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
