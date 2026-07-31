"""Async client for an upstream OpenAI-compatible endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import BackendConfig


class BackendError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"backend returned {status_code}: {body[:500]}")
        self.status_code = status_code
        self.body = body


class Backend:
    """Wraps one upstream endpoint. One instance per configured backend."""

    def __init__(self, cfg: BackendConfig) -> None:
        self.cfg = cfg
        headers = {"content-type": "application/json"}
        if cfg.api_key:
            headers["authorization"] = f"Bearer {cfg.api_key}"
        self._client = httpx.AsyncClient(
            base_url=cfg.endpoint.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(cfg.timeout_s),
        )

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Non-streaming chat completion."""
        body = {**payload, "stream": False}
        resp = await self._client.post("/chat/completions", json=body)
        if resp.status_code >= 400:
            raise BackendError(resp.status_code, resp.text)
        return resp.json()

    async def chat_stream(self, payload: dict[str, Any]) -> AsyncIterator[bytes]:
        """Streaming chat completion — yields raw SSE chunks for passthrough."""
        body = {**payload, "stream": True}
        async with self._client.stream("POST", "/chat/completions", json=body) as resp:
            if resp.status_code >= 400:
                text = (await resp.aread()).decode("utf-8", "replace")
                raise BackendError(resp.status_code, text)
            async for chunk in resp.aiter_raw():
                yield chunk

    async def aclose(self) -> None:
        await self._client.aclose()
