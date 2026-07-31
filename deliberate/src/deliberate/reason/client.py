"""Model client used by stages.

Stages never touch the backend directly — they call a ``ModelClient``, which wraps
the upstream endpoint plus the Qwen adapter and (optionally) budget accounting.
Best-of-N is implemented as N parallel calls with varied seeds so it works against
*any* backend, not only ones that support an ``n`` parameter.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..adapt import Profile
from ..backend import Backend, BackendError
from .state import Budget, Message


@dataclass
class CallResult:
    messages: list[Message]  # one per sample (n)
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def message(self) -> Message:
        return self.messages[0] if self.messages else {}

    @property
    def text(self) -> str:
        return self.message.get("content") or ""

    @property
    def total_tokens(self) -> int:
        return int(self.usage.get("total_tokens", 0) or 0)


class ModelClient(Protocol):
    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        n: int = 1,
        seed: int | None = None,
    ) -> CallResult: ...


class BackendModelClient:
    """Real client: upstream endpoint + Qwen adapter."""

    def __init__(self, backend: Backend, profile: Profile, model: str | None = None) -> None:
        self._backend = backend
        self._profile = profile
        self._model = model or backend.cfg.model

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        n: int = 1,
        seed: int | None = None,
    ) -> CallResult:
        async def one(sample_seed: int | None) -> tuple[Message | None, dict, str | None]:
            payload: dict[str, Any] = {"model": self._model, "messages": messages}
            if tools:
                payload["tools"] = tools
            if response_format:
                payload["response_format"] = response_format
            if temperature is not None:
                payload["temperature"] = temperature
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            if sample_seed is not None:
                payload["seed"] = sample_seed
            payload = self._profile.prepare_request(payload, self._model)
            try:
                resp = await self._backend.chat(payload)
            except BackendError as exc:
                return None, {}, str(exc)
            resp = self._profile.adapt_response(resp, had_tools=bool(tools))
            choice = (resp.get("choices") or [{}])[0]
            return choice.get("message") or {}, resp.get("usage") or {}, None

        seeds = [None] * n if seed is None else [seed + i for i in range(n)]
        results = await asyncio.gather(*(one(s) for s in seeds))

        msgs = [m for m, _, err in results if err is None and m is not None]
        errs = [err for _, _, err in results if err is not None]
        usage = _sum_usage([u for _, u, err in results if err is None])
        if not msgs:
            return CallResult(messages=[], usage=usage, error="; ".join(errs) or "no output")
        return CallResult(messages=msgs, usage=usage)

    async def aclose(self) -> None:
        await self._backend.aclose()


class BudgetedClient:
    """Wrap a ModelClient to count calls/tokens against a Budget."""

    def __init__(self, inner: ModelClient, budget: Budget) -> None:
        self._inner = inner
        self._budget = budget

    async def complete(self, messages: list[Message], *, n: int = 1, **kwargs: Any) -> CallResult:
        result = await self._inner.complete(messages, n=n, **kwargs)
        self._budget.charge(calls=max(1, n), tokens=result.total_tokens)
        return result


def _sum_usage(usages: list[dict]) -> dict[str, int]:
    out = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for u in usages:
        for k in out:
            out[k] += int(u.get(k, 0) or 0)
    return out
