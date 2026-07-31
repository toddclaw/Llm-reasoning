"""Deliberate — a modular reasoning proxy for local models.

Phase 0 scope: an OpenAI-compatible passthrough proxy with a Qwen adaptation layer
(tool-call recovery + optional guided structured output). The reasoning *stages*
(frame / plan-act-verify / best-of-N / reflect) arrive in later phases; the seams
for them already exist here (effort levels, per-profile adaptation, admission
control).

See ../../docs/deliberate/ for the design.
"""

__version__ = "0.0.1"
