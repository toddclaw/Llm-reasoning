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
def bench(
    config: Path = typer.Option(..., "--config", "-c", exists=True, help="Bench run config YAML."),
    suite: Path = typer.Option(..., "--suite", "-s", exists=True, help="Directory of task YAMLs."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write an HTML report here."),
    seeds: int | None = typer.Option(None, help="Override number of seeds."),
) -> None:
    """Run a task suite across targets and report base-vs-layer lift with a band."""
    import asyncio

    from .eval import (
        ResponseCache,
        compute_lift,
        load_suite,
        render_html,
        render_text,
        run_suite,
        summarize,
    )
    from .eval.runconfig import build_runners, load_bench_config

    cfg = load_bench_config(config)
    if seeds is not None:
        cfg.seeds = seeds
    tasks = load_suite(suite)
    cache = ResponseCache(cfg.cache_dir)
    runners = build_runners(cfg, cache)

    async def _run():
        try:
            return await run_suite(
                runners, tasks, cfg.seed_list(),
                concurrency=cfg.concurrency, pricing=cfg.pricing,
            )
        finally:
            for r in runners:
                close = getattr(r, "aclose", None)
                if close is not None:
                    await close()

    rows = asyncio.run(_run())
    summaries = summarize(rows)
    pair = cfg.lift_pair()
    lift = compute_lift(summaries, *pair) if pair else None

    typer.echo(render_text(summaries, lift))
    if out is not None:
        meta = {"suite": str(suite), "tasks": len(tasks), "seeds": len(cfg.seed_list())}
        out.write_text(render_html(rows, summaries, lift, meta))
        typer.echo(f"\nwrote {out}")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
