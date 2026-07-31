"""Content-addressed response cache.

Keyed by ``(runner, model, canonical request, seed)`` so that changing only the
grader, the report, or an unrelated task replays every prior completion from disk
instead of re-calling the model. Turns a slow suite into a fast one and makes
iteration cheap — a discipline carried over from the Nightshift eval plan.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ResponseCache:
    def __init__(self, directory: str | Path | None) -> None:
        self.dir = Path(directory) if directory else None
        if self.dir is not None:
            self.dir.mkdir(parents=True, exist_ok=True)

    def key(self, runner: str, model: str, request: dict[str, Any], seed: int | None) -> str:
        payload = {
            "runner": runner,
            "model": model,
            "request": request,
            "seed": seed,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        if self.dir is None:
            return None
        path = self.dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        if self.dir is None:
            return
        (self.dir / f"{key}.json").write_text(json.dumps(value, ensure_ascii=False))
