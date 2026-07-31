"""Profile protocol and the identity (passthrough) profile."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..config import ProfileConfig


@runtime_checkable
class Profile(Protocol):
    """Wraps every backend call for one model family.

    Two hooks, applied around the backend:
      * ``prepare_request`` — rewrite the outgoing OpenAI payload (set upstream
        model, translate structured-output/tool fields).
      * ``adapt_response`` — repair the returned completion (recover tool calls,
        fix finish_reason) so the client gets a clean OpenAI response.
    """

    name: str

    def prepare_request(self, payload: dict[str, Any], upstream_model: str) -> dict[str, Any]: ...

    def adapt_response(self, response: dict[str, Any], *, had_tools: bool) -> dict[str, Any]: ...


class PassthroughProfile:
    """Identity profile: set the upstream model, change nothing else."""

    name = "passthrough"

    def __init__(self, cfg: ProfileConfig | None = None) -> None:
        self.cfg = cfg or ProfileConfig()

    def prepare_request(self, payload: dict[str, Any], upstream_model: str) -> dict[str, Any]:
        out = dict(payload)
        out["model"] = upstream_model
        out.pop("reasoning_effort", None)  # Deliberate-only field; never forward it
        return out

    def adapt_response(self, response: dict[str, Any], *, had_tools: bool) -> dict[str, Any]:
        return response
