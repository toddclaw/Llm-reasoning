"""``deliberate`` command-line entry point."""

from __future__ import annotations

from pathlib import Path

import typer

from . import __version__

app = typer.Typer(add_completion=False, help="Deliberate — a modular reasoning proxy.")


@app.command()
def serve(
    config: Path = typer.Option(..., "--config", "-c", exists=True, help="Path to config YAML."),
    host: str | None = typer.Option(None, help="Override server.host."),
    port: int | None = typer.Option(None, help="Override server.port."),
) -> None:
    """Start the OpenAI-compatible reasoning proxy."""
    import uvicorn

    from .config import load_config
    from .server import build_app

    cfg = load_config(config)
    if host:
        cfg.server.host = host
    if port:
        cfg.server.port = port

    api = build_app(cfg)
    typer.echo(
        f"deliberate {__version__} serving on http://{cfg.server.host}:{cfg.server.port} "
        f"(backends: {', '.join(cfg.backends)})"
    )
    uvicorn.run(api, host=cfg.server.host, port=cfg.server.port, log_level="info")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
