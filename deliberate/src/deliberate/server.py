"""The OpenAI-compatible FastAPI app.

Phase 0 endpoints:
  * ``POST /v1/chat/completions`` — the proxy (streaming + non-streaming)
  * ``GET  /v1/models``           — advertise the served model + effort variants
  * ``GET  /health``              — liveness

The request flow, per docs/deliberate/01-architecture.md §1, with the reasoning
pipeline collapsed to identity for now: parse effort → select backend/profile →
adapt request → admission slot → backend → adapt response → render.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .adapt import Profile, build_profile
from .admission import Admission, AdmissionFull
from .backend import Backend, BackendError
from .config import Config
from .effort import Effort, resolve_effort, split_model_effort
from .stream import synthesize_sse

log = structlog.get_logger("deliberate")


class App:
    """Holds the wired-up runtime state (backends, profiles, admission)."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.backends: dict[str, Backend] = {
            name: Backend(cfg) for name, cfg in config.backends.items()
        }
        self.profiles: dict[str, Profile] = {
            name: build_profile(cfg.profile, config.profile_for(cfg))
            for name, cfg in config.backends.items()
        }
        self.admission = Admission(
            config.server.max_concurrent_requests, config.server.admission_wait_s
        )

    async def aclose(self) -> None:
        for be in self.backends.values():
            await be.aclose()


def build_app(config: Config) -> FastAPI:
    state = App(config)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await state.aclose()

    api = FastAPI(title="Deliberate", version="0.0.1", lifespan=lifespan)
    api.state.app = state

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/v1/models")
    async def models() -> dict[str, Any]:
        now = int(time.time())
        data = []
        for name in config.backends:
            for suffix in ("", ":low", ":medium", ":high", ":off"):
                data.append(
                    {"id": f"{name}{suffix}", "object": "model",
                     "created": now, "owned_by": "deliberate"}
                )
        return {"object": "list", "data": data}

    @api.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        try:
            body = await request.json()
        except Exception:
            return _error(400, "invalid JSON body")
        if not isinstance(body, dict) or "messages" not in body:
            return _error(400, "request must be an object with a 'messages' field")

        model_field = str(body.get("model", ""))
        base_model, suffix_effort = split_model_effort(model_field)
        effort = resolve_effort(
            body.get("reasoning_effort"), suffix_effort, config.defaults.reasoning_effort
        )

        backend_name, backend_cfg = config.select_backend(base_model)
        backend = state.backends[backend_name]
        profile = state.profiles[backend_name]

        had_tools = bool(body.get("tools"))
        wants_stream = bool(body.get("stream"))
        payload = profile.prepare_request(body, backend_cfg.model)

        headers = {
            "x-deliberate-effort": effort.label,
            "x-deliberate-profile": profile.name,
            "x-deliberate-backend": backend_name,
        }

        # NOTE: in Phase 0 every effort level resolves to passthrough reasoning; the
        # Qwen adaptation applies regardless of effort because it is a transport fix,
        # not a reasoning stage. Reasoning stages arrive in Phase 2.
        try:
            # True passthrough streaming when there are no tools to recover.
            if wants_stream and not had_tools:
                return await _stream_passthrough(state, backend, payload, headers)

            # Otherwise call non-streaming so the adapter sees the whole message.
            async with state.admission.slot():
                raw = await backend.chat(payload)
            adapted = profile.adapt_response(raw, had_tools=had_tools)

            if wants_stream:
                return StreamingResponse(
                    _aiter(synthesize_sse(adapted)),
                    media_type="text/event-stream",
                    headers=headers,
                )
            return JSONResponse(adapted, headers=headers)

        except AdmissionFull as exc:
            return _error(503, str(exc), headers)
        except BackendError as exc:
            return _error(exc.status_code, exc.body, headers, raw_body=True)

    return api


async def _stream_passthrough(state, backend: Backend, payload, headers) -> StreamingResponse:
    async def gen():
        async with state.admission.slot():
            async for chunk in backend.chat_stream(payload):
                yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


async def _aiter(iterable):
    for item in iterable:
        yield item


def _error(status: int, message: str, headers: dict | None = None, *, raw_body: bool = False):
    if raw_body:
        # Forward the upstream body/status verbatim where we can.
        return JSONResponse(_maybe_json(message), status_code=status, headers=headers)
    return JSONResponse(
        {"error": {"message": message, "type": "deliberate_error", "code": status}},
        status_code=status,
        headers=headers,
    )


def _maybe_json(text: str):
    import json

    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"error": {"message": text, "type": "backend_error"}}
