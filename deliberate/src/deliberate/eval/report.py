"""Text and HTML reports.

The report answers the exit criterion for Phase 1: compare targets with a lift
number and a variance band. The HTML is self-contained (no external assets) and
theme-aware; the text summary is for the terminal.
"""

from __future__ import annotations

import html
from typing import Any

from .metrics import Lift, Row, TargetSummary


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def render_text(summaries: dict[str, TargetSummary], lift: Lift | None) -> str:
    lines: list[str] = []
    lines.append("Target              pass_rate   band            tool_valid  lat(ms)  cost")
    lines.append("-" * 78)
    for s in summaries.values():
        lo, hi = s.band
        band = f"[{lo * 100:.0f}–{hi * 100:.0f}%]"
        cost = "—" if s.total_cost_usd is None else f"${s.total_cost_usd:.4f}"
        lines.append(
            f"{s.name:<18}  {_pct(s.pass_rate):>8}   {band:<14}  "
            f"{_pct(s.tool_call_validity):>9}  {s.mean_latency_ms:>6.0f}  {cost}"
        )
    if lift is not None:
        lines.append("")
        verdict = "clears the noise band" if lift.clears_band else "WITHIN the noise band"
        sign = "+" if lift.overall >= 0 else ""
        lines.append(
            f"LIFT ({lift.layer} vs {lift.base}): {sign}{lift.overall * 100:.1f} pts "
            f"(±{lift.combined_band_halfwidth * 100:.1f} combined band) — {verdict}"
        )
        if lift.per_kind:
            per = ", ".join(f"{k}: {v * 100:+.0f}" for k, v in lift.per_kind.items())
            lines.append(f"  by kind: {per}")
    return "\n".join(lines)


def render_html(
    rows: list[Row],
    summaries: dict[str, TargetSummary],
    lift: Lift | None,
    meta: dict[str, Any] | None = None,
) -> str:
    meta = meta or {}
    targets = list(summaries)
    task_ids = sorted({r.task_id for r in rows})

    # pass fraction per (task, target) across seeds, for the grid
    grid: dict[tuple[str, str], float] = {}
    kinds: dict[str, str] = {}
    for r in rows:
        kinds[r.task_id] = r.kind
        cell = grid.setdefault((r.task_id, r.target), 0.0)
    for tid in task_ids:
        for tgt in targets:
            trows = [r for r in rows if r.task_id == tid and r.target == tgt]
            grid[(tid, tgt)] = sum(1 for r in trows if r.passed) / len(trows) if trows else 0.0

    def bar(s: TargetSummary) -> str:
        lo, hi = s.band
        return (
            f'<div class="bar"><div class="fill" style="width:{s.pass_rate*100:.1f}%"></div>'
            f'<div class="band" style="left:{lo*100:.1f}%;width:{(hi-lo)*100:.1f}%"></div></div>'
        )

    rows_html = "\n".join(
        f"<tr><td>{html.escape(s.name)}</td><td class=num>{_pct(s.pass_rate)}</td>"
        f"<td>{bar(s)}</td><td class=num>{_pct(s.tool_call_validity)}</td>"
        f"<td class=num>{s.mean_latency_ms:.0f}</td>"
        f"<td class=num>{'—' if s.total_cost_usd is None else f'${s.total_cost_usd:.4f}'}</td></tr>"
        for s in summaries.values()
    )

    head = "".join(f"<th>{html.escape(t)}</th>" for t in targets)
    grid_rows = []
    for tid in task_ids:
        cells = []
        for tgt in targets:
            frac = grid[(tid, tgt)]
            cls = "pass" if frac >= 0.999 else ("fail" if frac <= 0.001 else "partial")
            cells.append(f'<td class="cell {cls}" title="{frac*100:.0f}% of seeds">{frac*100:.0f}</td>')
        grid_rows.append(
            f"<tr><td class=tid>{html.escape(tid)}</td>"
            f"<td class=kind>{html.escape(kinds[tid])}</td>{''.join(cells)}</tr>"
        )

    lift_html = ""
    if lift is not None:
        cls = "good" if (lift.clears_band and lift.overall > 0) else (
            "bad" if lift.overall < 0 else "meh")
        verdict = "clears the noise band" if lift.clears_band else "within the noise band"
        lift_html = (
            f'<div class="lift {cls}"><span class="big">{lift.overall*100:+.1f} pts</span>'
            f'<span> lift ({html.escape(lift.layer)} vs {html.escape(lift.base)}), '
            f'±{lift.combined_band_halfwidth*100:.1f} combined band — {verdict}</span></div>'
        )

    meta_html = "".join(
        f"<span>{html.escape(str(k))}: {html.escape(str(v))}</span>" for k, v in meta.items()
    )

    return f"""<!doctype html>
<meta charset="utf-8"><title>Deliberate eval report</title>
<style>
  :root {{ --bg:#fff; --fg:#111; --muted:#666; --line:#e2e2e2; --fill:#3b82f6;
           --band:#3b82f633; --pass:#16a34a; --fail:#dc2626; --partial:#d97706; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f1115; --fg:#e8e8e8; --muted:#9aa0a6; --line:#2a2d34;
             --fill:#60a5fa; --band:#60a5fa33; }} }}
  body {{ background:var(--bg); color:var(--fg); font:14px/1.5 system-ui,sans-serif;
          margin:2rem auto; max-width:1000px; padding:0 1rem; }}
  h1 {{ font-size:1.4rem; margin:0 0 .25rem; }}
  .meta {{ color:var(--muted); font-size:.85rem; display:flex; gap:1rem; flex-wrap:wrap;
           margin-bottom:1rem; }}
  table {{ border-collapse:collapse; width:100%; margin:1rem 0; }}
  th,td {{ border-bottom:1px solid var(--line); padding:.4rem .6rem; text-align:left; }}
  td.num,.cell {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .bar {{ position:relative; height:14px; background:var(--line); border-radius:3px; min-width:120px; }}
  .fill {{ position:absolute; height:100%; background:var(--fill); border-radius:3px; }}
  .band {{ position:absolute; height:100%; background:var(--band);
           border-left:1px solid var(--fill); border-right:1px solid var(--fill); }}
  .lift {{ padding:.75rem 1rem; border-radius:8px; margin:1rem 0; border:1px solid var(--line); }}
  .lift .big {{ font-size:1.5rem; font-weight:700; margin-right:.5rem; }}
  .lift.good {{ border-color:var(--pass); }} .lift.bad {{ border-color:var(--fail); }}
  .cell.pass {{ color:var(--pass); }} .cell.fail {{ color:var(--fail); }}
  .cell.partial {{ color:var(--partial); }}
  .tid {{ font-family:ui-monospace,monospace; }} .kind {{ color:var(--muted); }}
  .wrap {{ overflow-x:auto; }}
</style>
<h1>Deliberate eval report</h1>
<div class="meta">{meta_html}</div>
{lift_html}
<h2>Targets</h2>
<div class="wrap"><table>
<thead><tr><th>target</th><th>pass rate</th><th>rate + band</th><th>tool valid</th>
<th>lat ms</th><th>cost</th></tr></thead>
<tbody>{rows_html}</tbody>
</table></div>
<h2>Per-task (% of seeds passing)</h2>
<div class="wrap"><table>
<thead><tr><th>task</th><th>kind</th>{head}</tr></thead>
<tbody>{''.join(grid_rows)}</tbody>
</table></div>
"""
