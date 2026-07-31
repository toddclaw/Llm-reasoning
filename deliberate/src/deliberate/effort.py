"""Reasoning-effort levels and how they are parsed from an OpenAI request.

Effort is the caller-facing dial for *how much deliberation a request earns*. In
Phase 0 no reasoning stages exist yet, so effort is parsed, echoed back in a
response header, and otherwise inert — but the precedence rules and the model-suffix
convention are settled here so clients (and pi) can start using them now.

Precedence (highest first):
  1. explicit ``reasoning_effort`` request field
  2. a model-name suffix, e.g. ``qwen3.5:high``
  3. the server default from config
"""

from __future__ import annotations

from enum import IntEnum


class Effort(IntEnum):
    OFF = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3

    @property
    def label(self) -> str:
        return self.name.lower()


_BY_NAME = {e.label: e for e in Effort}


def parse_effort(value: str | int | None) -> Effort | None:
    """Parse an effort from a string/int, or ``None`` if unrecognised/absent."""
    if value is None:
        return None
    if isinstance(value, Effort):
        return value
    if isinstance(value, int):
        try:
            return Effort(value)
        except ValueError:
            return None
    return _BY_NAME.get(str(value).strip().lower())


def split_model_effort(model: str) -> tuple[str, Effort | None]:
    """Split a ``model:effort`` string into ``(model, effort)``.

    Only a trailing segment that names a known effort is treated as an effort
    suffix; anything else (e.g. a real model tag like ``qwen3.5:q4``) is left on the
    model string untouched.
    """
    if ":" in model:
        base, _, suffix = model.rpartition(":")
        effort = _BY_NAME.get(suffix.strip().lower())
        if effort is not None and base:
            return base, effort
    return model, None


def resolve_effort(
    field: str | int | None,
    suffix_effort: Effort | None,
    default: Effort,
) -> Effort:
    """Apply the precedence rules to land on a single effort level."""
    return parse_effort(field) or suffix_effort or default
