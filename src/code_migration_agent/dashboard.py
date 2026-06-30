"""Static, dependency-free dashboard for benchmark results."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _modes(results: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = results.get("modes", {})
    return raw if isinstance(raw, Mapping) else {}


def _metrics(results: Mapping[str, Any], mode: str) -> Mapping[str, Any]:
    modes = _modes(results)
    mode_data = modes.get(mode, {})
    if isinstance(mode_data, Mapping):
        metrics = mode_data.get("metrics", {})
        if isinstance(metrics, Mapping):
            return metrics
    return {}


def _runs(results: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = results.get("runs", {})
    if not isinstance(raw, Mapping):
        return []
    rows: list[Mapping[str, Any]] = []
    for mode, runs in raw.items():
        if isinstance(runs, list):
            for run in runs:
                if isinstance(run, Mapping):
                    rows.append({**run, "_mode": mode})
    return rows


def _taxonomy(results: Mapping[str, Any], mode: str) -> Mapping[str, Any]:
    taxonomy = results.get("taxonomy", {})
    if isinstance(taxonomy, Mapping):
        mode_data = taxonomy.get(mode, {})
        if isinstance(mode_data, Mapping):
            return mode_data
    return {}


def _as_float(value: object) -> float | None:
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _pct(value: object) -> str:
    number = _as_float(value)
    if number is None:
        return "n/a"
    return f"{number * 100:.1f}%"


def _num(value: object, suffix: str = "") -> str:
    number = _as_float(value)
    if number is None:
        return "n/a"
    return f"{number:,.2f}{suffix}"


def _bar(label: str, value: object) -> str:
    number = _as_float(value)
    rate = 0.0 if number is None else max(0.0, min(1.0, number))
    return (
        '<div class="bar-row">'
        f'<span class="bar-label">{_escape(label)}</span>'
        f'<span class="bar-track"><span class="bar-fill" style="width:{rate * 100:.1f}%"></span></span>'
        f'<span class="bar-value">{_escape(_pct(value))}</span>'
        "</div>"
    )


def render_dashboard(results: Mapping[str, Any]) -> str:
    corpus = results.get("corpus", {})
    corpus = corpus if isinstance(corpus, Mapping) else {}
    full_metrics = _metrics(results, "full")
    recipe_metrics = _metrics(results, "recipes_only")
    runs = _runs(results)

    taxonomy_sections: list[str] = []
    for mode, title in (("full", "Full pipeline"), ("recipes_only", "Recipes only")):
        taxonomy = _taxonomy(results, mode)
        rows: list[str] = []
        if taxonomy:
            for failure_class, payload in sorted(taxonomy.items()):
                data = payload if isinstance(payload, Mapping) else {}
                count = data.get("count", 0)
                exemplars = data.get("exemplars", [])
                details: list[str] = []
                if isinstance(exemplars, list):
                    for exemplar in exemplars[:3]:
                        if not isinstance(exemplar, Mapping):
                            continue
                        details.append(
                            "<details><summary>"
                            + _escape(exemplar.get("repo", "repo"))
                            + "</summary><p>"
                            + _escape(exemplar.get("reason", ""))
                            + "</p><pre>"
                            + _escape(exemplar.get("diff_excerpt", ""))
                            + "</pre></details>"
                        )
                rows.append(
                    "<tr><td><code>"
                    + _escape(failure_class)
                    + "</code></td><td>"
                    + _escape(count)
                    + "</td><td>"
                    + "".join(details)
                    + "</td></tr>"
                )
        body = (
            "<table><thead><tr><th>Class</th><th>Count</th><th>Exemplar</th></tr></thead>"
            "<tbody>"
            + "".join(rows)
            + "</tbody></table>"
            if rows
            else "<p>No failures recorded.</p>"
        )
        taxonomy_sections.append(f"<h3>{_escape(title)}</h3>{body}")

    repo_rows = []
    for run in sorted(runs, key=lambda item: (str(item.get("name", "")), str(item.get("_mode", "")))):
        delta = run.get("coverage_delta")
        delta_text = "n/a" if delta is None else f"{float(delta):+.2f} pp"
        cls = run.get("failure_class") or "-"
        cost_text = f"${float(run.get('cost_usd', 0.0)):.4f}"
        duration_text = f"{float(run.get('duration_s', 0.0)):.2f}s"
        repo_rows.append(
            "<tr>"
            f"<td>{_escape(run.get('name', ''))}</td>"
            f"<td>{_escape(run.get('_mode', ''))}</td>"
            f"<td>{_escape(run.get('outcome', ''))}</td>"
            f"<td><code>{_escape(cls)}</code></td>"
            f"<td>{_escape(delta_text)}</td>"
            f"<td>{_escape(run.get('turns', 0))}</td>"
            f"<td>{_escape(cost_text)}</td>"
            f"<td>{_escape(duration_text)}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Code Migration Agent — failure taxonomy</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem auto; max-width: 1100px; padding: 0 1rem; line-height: 1.45; }}
  h1, h2, h3 {{ line-height: 1.15; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 1rem; margin: 1.5rem 0; }}
  .card {{ border: 1px solid #8888; border-radius: 10px; padding: 1rem; }}
  .card .value {{ font-size: 1.7rem; font-weight: 700; display: block; }}
  .card .label {{ font-size: 0.82rem; opacity: 0.72; }}
  .bar-row {{ display: grid; grid-template-columns: 9rem 1fr 4rem; gap: 0.6rem; align-items: center; margin: 0.4rem 0; }}
  .bar-track {{ background: #8883; border-radius: 999px; height: 0.9rem; overflow: hidden; }}
  .bar-fill {{ display: block; height: 100%; background: #3b82f6; }}
  .bar-value {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table {{ border-collapse: collapse; width: 100%; margin: 0.6rem 0 1.4rem; }}
  th, td {{ border-bottom: 1px solid #8884; text-align: left; padding: 0.4rem; vertical-align: top; }}
  td pre {{ max-width: 34rem; overflow: auto; white-space: pre-wrap; }}
  details {{ margin: 0.25rem 0; }}
  code {{ font-family: ui-monospace, monospace; }}
</style>
</head>
<body>
<h1>Code Migration Agent</h1>
<p>Failure taxonomy and migration gates. Corpus: <strong>{_escape(corpus.get("kind", "unknown"))}</strong>,
{_escape(corpus.get("count", 0))} repositories, seed <code>{_escape(corpus.get("seed", "n/a"))}</code>.</p>
<div class="cards">
  <div class="card"><span class="value">{_escape(_pct(full_metrics.get("pass_rate")))}</span><span class="label">Full pipeline pass rate</span></div>
  <div class="card"><span class="value">{_escape(_pct(recipe_metrics.get("pass_rate")))}</span><span class="label">Recipes-only pass rate</span></div>
  <div class="card"><span class="value">{_escape(_num(full_metrics.get("mean_coverage_delta"), " pp"))}</span><span class="label">Mean coverage delta</span></div>
  <div class="card"><span class="value">${_escape(_num(full_metrics.get("cost_per_passing_repo")))}</span><span class="label">Cost per passing repo</span></div>
  <div class="card"><span class="value">{_escape(_pct(full_metrics.get("agent_fix_share")))}</span><span class="label">Agent-authored fix share</span></div>
  <div class="card"><span class="value">{_escape(_num(full_metrics.get("ttfgb_median_s"), " s"))}</span><span class="label">Median time to green</span></div>
</div>
<h2>Pass rate</h2>
{_bar("Full pipeline", full_metrics.get("pass_rate"))}
{_bar("Recipes only", recipe_metrics.get("pass_rate"))}
<h2>Failure taxonomy</h2>
{''.join(taxonomy_sections)}
<h2>Repositories</h2>
<table>
<thead><tr><th>Repo</th><th>Mode</th><th>Outcome</th><th>Class</th><th>Coverage Δ</th><th>Turns</th><th>Cost</th><th>Time</th></tr></thead>
<tbody>{''.join(repo_rows)}</tbody>
</table>
<p>Generated locally. Offline deterministic policy unless the results record an LLM policy.</p>
</body>
</html>
"""


def write_dashboard(results_path: Path, out_path: Path) -> Path:
    data = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("results JSON must be an object")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_dashboard(data), encoding="utf-8")
    return out_path
