"""Runners: how a completion is produced for a request.

A *runner* is one system-under-test. The harness compares runners on the same tasks:

  * ``DirectRunner`` — the base model, called raw (no Deliberate adaptation). The
    floor the layer must beat.
  * ``ProxyRunner``  — the same model through Deliberate's Qwen adapter (the same
    transform the server applies), so the comparison isolates the layer's effect.
  * ``ScriptedRunner`` — canned responses for offline tests.
  * ``CachingRunner`` — wraps any runner with a content-addressed response cache.

Both Direct and Proxy hit the *same* upstream model, so any measured lift is the
layer's doing, not a model difference.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..adapt import Profile, build_profile
from ..backend import Backend, BackendError
from ..config import BackendConfig, ProfileConfig


@dataclass
class Completion:
    message: dict[str, Any]
    finish_reason: str | None
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None
    confidence: float | None = None  # set by ReasonRunner when the frame stage ran

    @property
    def text(self) -> str:
        return self.message.get("content") or ""

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return self.message.get("tool_calls") or []

    @property
    def prompt_tokens(self) -> int:
        return int(self.usage.get("prompt_tokens", 0) or 0)

    @property
    def completion_tokens(self) -> int:
        return int(self.usage.get("completion_tokens", 0) or 0)

    @staticmethod
    def from_response(resp: dict[str, Any], latency_ms: float) -> "Completion":
        choices = resp.get("choices") or [{}]
        choice = choices[0]
        return Completion(
            message=choice.get("message") or {},
            finish_reason=choice.get("finish_reason"),
            usage=resp.get("usage") or {},
            latency_ms=latency_ms,
        )

    @staticmethod
    def errored(msg: str, latency_ms: float) -> "Completion":
        return Completion(message={}, finish_reason=None, latency_ms=latency_ms, error=msg)


class Runner(Protocol):
    name: str
    model: str

    async def run(self, request: dict[str, Any], seed: int | None) -> Completion: ...


def _with_seed(request: dict[str, Any], model: str, seed: int | None) -> dict[str, Any]:
    payload = {**request, "model": model}
    if seed is not None:
        payload.setdefault("seed", seed)
    return payload


class DirectRunner:
    """Base model, no adaptation — send the request as-is."""

    def __init__(self, name: str, backend: Backend) -> None:
        self.name = name
        self._backend = backend
        self.model = backend.cfg.model

    async def run(self, request: dict[str, Any], seed: int | None) -> Completion:
        payload = _with_seed(request, self.model, seed)
        t0 = time.perf_counter()
        try:
            resp = await self._backend.chat(payload)
        except BackendError as exc:
            return Completion.errored(str(exc), (time.perf_counter() - t0) * 1000)
        return Completion.from_response(resp, (time.perf_counter() - t0) * 1000)

    async def aclose(self) -> None:
        await self._backend.aclose()


class ProxyRunner:
    """Same model through Deliberate's adapter (the server's transform, minus HTTP)."""

    def __init__(self, name: str, backend: Backend, profile: Profile) -> None:
        self.name = name
        self._backend = backend
        self._profile = profile
        self.model = backend.cfg.model

    async def run(self, request: dict[str, Any], seed: int | None) -> Completion:
        had_tools = bool(request.get("tools"))
        payload = self._profile.prepare_request(_with_seed(request, self.model, seed), self.model)
        t0 = time.perf_counter()
        try:
            resp = await self._backend.chat(payload)
        except BackendError as exc:
            return Completion.errored(str(exc), (time.perf_counter() - t0) * 1000)
        resp = self._profile.adapt_response(resp, had_tools=had_tools)
        return Completion.from_response(resp, (time.perf_counter() - t0) * 1000)

    async def aclose(self) -> None:
        await self._backend.aclose()


class ScriptedRunner:
    """Returns canned completions keyed by task tag or a default. Test-only."""

    def __init__(self, name: str, responses: dict[str, Completion], default: Completion | None = None):
        self.name = name
        self.model = "scripted"
        self._responses = responses
        self._default = default

    async def run(self, request: dict[str, Any], seed: int | None) -> Completion:
        # Key on the first user message content for determinism in tests.
        key = ""
        for m in request.get("messages", []):
            if m.get("role") == "user":
                key = str(m.get("content", ""))
                break
        comp = self._responses.get(key, self._default)
        if comp is None:
            return Completion.errored(f"no scripted response for {key!r}", 0.0)
        return comp


class CachingRunner:
    """Wrap a runner with a content-addressed response cache (skip repeat calls)."""

    def __init__(self, inner: Runner, cache: "ResponseCache") -> None:
        self._inner = inner
        self._cache = cache
        self.name = inner.name
        self.model = inner.model

    async def run(self, request: dict[str, Any], seed: int | None) -> Completion:
        key = self._cache.key(self.name, self.model, request, seed)
        cached = self._cache.get(key)
        if cached is not None:
            return Completion(**cached)
        comp = await self._inner.run(request, seed)
        if comp.error is None:  # never cache failures
            self._cache.put(key, _completion_to_dict(comp))
        return comp

    async def aclose(self) -> None:
        inner_close = getattr(self._inner, "aclose", None)
        if inner_close is not None:
            await inner_close()


def _completion_to_dict(c: Completion) -> dict[str, Any]:
    return {
        "message": c.message,
        "finish_reason": c.finish_reason,
        "usage": c.usage,
        "latency_ms": c.latency_ms,
        "error": c.error,
    }


class ReasonRunner:
    """Runs a fixed reasoning pipeline (Phase 2) so the harness can measure stage lift.

    Unlike the server, the pipeline here is an explicit list of stage ids (not
    classified), so an eval target pins exactly the stages under test.
    """

    def __init__(
        self,
        name: str,
        backend: Backend,
        profile: Profile,
        stage_ids: list[str],
        stage_params: dict[str, dict[str, Any]] | None = None,
        max_model_calls: int = 20,
        max_tokens: int = 400_000,
    ) -> None:
        from ..reason import BackendModelClient
        from ..reason.routing import build_stages

        self.name = name
        self.model = backend.cfg.model
        self._backend = backend
        self._profile = profile
        self._stages = build_stages(stage_ids, stage_params)
        self._make_client = lambda: BackendModelClient(backend, profile, backend.cfg.model)
        self._budget_limits = (max_model_calls, max_tokens)

    async def run(self, request: dict[str, Any], seed: int | None) -> Completion:
        from ..reason import Budget, BudgetedClient, ReasoningState, run_pipeline

        t0 = time.perf_counter()
        rstate = ReasoningState.from_request(dict(request), effort="eval", difficulty="eval")
        budget = Budget(max_model_calls=self._budget_limits[0], max_tokens=self._budget_limits[1])
        client = BudgetedClient(self._make_client(), budget)
        rstate = await run_pipeline(self._stages, rstate, client)
        msg = rstate.answer or {}
        finish = "tool_calls" if msg.get("tool_calls") else "stop"
        return Completion(
            message=msg,
            finish_reason=finish,
            usage={"total_tokens": budget.tokens},
            latency_ms=(time.perf_counter() - t0) * 1000,
            confidence=rstate.confidence,
        )

    async def aclose(self) -> None:
        await self._backend.aclose()


def build_backend_runner(
    name: str,
    mode: str,
    backend_cfg: BackendConfig,
    stage_ids: list[str] | None = None,
    stage_params: dict[str, dict[str, Any]] | None = None,
) -> Runner:
    """Construct a Direct, Proxy, or Reason runner from a backend config."""
    backend = Backend(backend_cfg)
    if mode == "direct":
        return DirectRunner(name, backend)
    profile = build_profile(backend_cfg.profile, ProfileConfig())
    if mode == "proxy":
        return ProxyRunner(name, backend, profile)
    if mode == "reason":
        return ReasonRunner(name, backend, profile, stage_ids or [], stage_params)
    raise ValueError(f"unknown runner mode: {mode!r} (expected direct|proxy|reason)")


# Imported lazily to avoid a cycle at module import time.
from .cache import ResponseCache  # noqa: E402
