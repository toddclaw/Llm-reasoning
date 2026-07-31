"""Configuration model and loader.

One YAML file defines a deployment. Everything tunable lives here; nothing that a
deployment might want to change lives in code. Environment variables of the form
``DELIBERATE_<SECTION>_<KEY>`` are not parsed in Phase 0 to keep things obvious —
add pydantic-settings later if needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .effort import Effort, parse_effort


class BackendConfig(BaseModel):
    """An upstream OpenAI-compatible endpoint (e.g. vLLM serving Qwen)."""

    endpoint: str  # base URL, e.g. http://rack:8000/v1
    model: str  # the model id to send upstream
    profile: str = "qwen3"  # which adaptation profile to apply
    api_key: str | None = None
    timeout_s: float = 300.0


class ProfileConfig(BaseModel):
    """Adaptation behaviour for a family of models."""

    # Recover tool calls the model narrated as text (Hermes/Qwen ``<tool_call>``)
    # into proper OpenAI ``tool_calls``. The single highest-value Phase 0 fix.
    recover_tool_calls: bool = True
    # XML-ish tags the model wraps tool calls in. Qwen/Hermes use "tool_call".
    tool_call_tags: list[str] = Field(default_factory=lambda: ["tool_call"])
    # If true, translate an OpenAI ``response_format`` json_schema into a vLLM
    # ``guided_json`` field so structured output is grammar-constrained. Off by
    # default because it is vLLM-specific.
    guided_json: bool = False
    guided_decoding_backend: str | None = None  # e.g. "xgrammar"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    # Per-replica admission cap onto the shared backend. Sized to the rack's
    # healthy continuous-batch width; excess callers queue (see admission.py).
    max_concurrent_requests: int = 64
    admission_wait_s: float = 30.0


class DefaultsConfig(BaseModel):
    reasoning_effort: Effort = Effort.MEDIUM


class ReasoningConfig(BaseModel):
    """Reasoning-layer config (Phase 2). Empty = defaults from reason/routing.py."""

    # effort.difficulty -> ordered stage ids (overrides/extends the built-in table)
    routes: dict[str, list[str]] = Field(default_factory=dict)
    # per-stage params, e.g. {"best_of_n": {"n": 4}}
    stage_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # per-request budget
    max_model_calls: int = 12
    max_tokens: int = 200_000


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    backends: dict[str, BackendConfig]
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)

    # -- backend selection ------------------------------------------------
    def select_backend(self, model: str) -> tuple[str, BackendConfig]:
        """Pick a backend for a client-supplied model string.

        Order: exact backend-key match → backend whose ``.model`` matches →
        a backend named ``base`` → the first configured backend.
        """
        if model in self.backends:
            return model, self.backends[model]
        for name, be in self.backends.items():
            if be.model == model:
                return name, be
        if "base" in self.backends:
            return "base", self.backends["base"]
        name = next(iter(self.backends))
        return name, self.backends[name]

    def profile_for(self, backend: BackendConfig) -> ProfileConfig:
        return self.profiles.get(backend.profile, ProfileConfig())


def load_config(path: str | Path) -> Config:
    data = yaml.safe_load(Path(path).read_text()) or {}
    # Allow effort to be written as a string in YAML.
    defaults = data.get("defaults") or {}
    if "reasoning_effort" in defaults:
        eff = parse_effort(defaults["reasoning_effort"])
        if eff is None:
            raise ValueError(f"invalid defaults.reasoning_effort: {defaults['reasoning_effort']!r}")
        defaults["reasoning_effort"] = eff
        data["defaults"] = defaults
    return Config.model_validate(data)
