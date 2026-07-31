"""Adaptation profiles: how to talk to a particular model family.

A profile is the shareability seam (docs/deliberate/03-qwen-adaptation.md §7): the
reasoning core stays model-agnostic, and everything model-specific — tool-call
format, structured-output translation — lives in a profile. ``qwen3`` is the first;
``passthrough`` is the identity profile for already-compliant backends.
"""

from __future__ import annotations

from ..config import ProfileConfig
from .base import PassthroughProfile, Profile
from .qwen import QwenProfile


def build_profile(name: str, cfg: ProfileConfig) -> Profile:
    if name in ("qwen3", "qwen", "hermes"):
        return QwenProfile(cfg)
    if name in ("passthrough", "generic", "openai"):
        return PassthroughProfile(cfg)
    # Unknown profile name: default to Qwen behaviour, which is a strict superset of
    # passthrough when its features find nothing to do.
    return QwenProfile(cfg)


__all__ = ["Profile", "PassthroughProfile", "QwenProfile", "build_profile"]
