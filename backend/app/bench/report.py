"""Benchmark CSV and report generators (PRD §11.3, §12.3 queue item C6)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from .. import models as m

RUNRESULT_FIELDS = list(m.RunResult.model_fields.keys())


def _flatten(result: m.RunResult) -> dict:
    """CSV has no nested types; serialize `metrics` and `adaptation_wall_ms` as JSON text
    in their own cell, same convention either column would need regardless of method."""
    row = result.model_dump(mode="json")
    row["metrics"] = json.dumps(row["metrics"])
    row["adaptation_wall_ms"] = json.dumps(row["adaptation_wall_ms"])
    return row


def append_result_row(path: Path, result: m.RunResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RUNRESULT_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(_flatten(result))


def write_summary_json(path: Path, results: list[m.RunResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    by_method: dict[str, dict] = {}
    for method in sorted({r.method for r in results}):
        method_results = [r for r in results if r.method == method]
        by_method[method] = {
            "runs": len(method_results),
            "model_calls_total": sum(r.model_calls for r in method_results),
            "wall_ms_total": sum(r.wall_ms_total for r in method_results),
        }
    path.write_text(json.dumps({"run_count": len(results), "by_method": by_method}, indent=2))


def read_results_csv(path: Path) -> list[m.RunResult]:
    """Load saved results through the shared schema before writing a report."""
    optional = {"model", "budget_calls", "budget_tokens", "tokens_in", "tokens_out", "cost_usd_estimate"}
    with path.open(newline="") as source:
        rows = list(csv.DictReader(source))
    results = []
    for row in rows:
        data = dict(row)
        data["metrics"] = json.loads(data["metrics"])
        data["adaptation_wall_ms"] = json.loads(data["adaptation_wall_ms"])
        for key in optional:
            if data[key] == "":
                data[key] = None
        results.append(m.RunResult.model_validate(data))
    return results


def _number(value: int | float | None, *, digits: int = 0) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}" if digits else str(value)


def render_markdown(results: list[m.RunResult]) -> str:
    """Every saved run and every measured PRD §11.1 metric, without a winner claim."""
    if not results:
        return "# RescueMesh benchmark results\n\nNo recorded runs. No comparison is available.\n"
    stub = any("STUB" in result.notes for result in results)
    coverage = {(result.preset, result.seed, result.method) for result in results}
    expected = {(preset, seed, method)
                for preset in ("normal", "wind_shift", "road_closure", "compound_failure")
                for seed in (1, 2, 3)
                for method in ("rescuemesh", "fixed_rule", "single_agent")}
    missing = expected - coverage
    lines = [
        "# RescueMesh benchmark results",
        "",
        "**Synthetic simulation.**",
        "",
        ("**STUB DATA — no comparative result.**" if stub else
         "Recorded method runs only. Missing methods are absent, never treated as zero. "
         "Three seeds per preset do not support a significance claim."),
        "",
        f"Coverage: {len(coverage)} of {len(expected)} planned preset × seed × method combinations. "
        + ("The paired comparison is incomplete." if missing else "The planned combinations are present."),
        "",
        "## Realized outcomes",
        "",
        "| Preset | Seed | Method | Exposure (person-steps) | Assisted sheltered / demand | Assisted completion | Evacuation step | Fire extent | Burning cell-steps | Crew risk-steps | Logistics risk | Invalid attempted / executed |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        metric = r.metrics
        lines.append(
            f"| {r.preset} | {r.seed} | {r.method} | {metric.civilian_exposure} | "
            f"{metric.assisted_sheltered} / {metric.assisted_demand} | "
            f"{_number(metric.assisted_completion, digits=3)} | "
            f"{_number(metric.evacuation_completion_step)} | {metric.fire_extent} | "
            f"{metric.burning_cell_steps} | {metric.crew_risk_steps} | {metric.logistics_risk} | "
            f"{metric.invalid_attempted} / {metric.invalid_executed} |"
        )
    lines.extend([
        "",
        "## Decisions, latency and cost",
        "",
        "| Run ID | Preset | Seed | Method | DPs | Commits | Escalations | Inappropriate consensus | Justified escalations | Adaptation ms | Model calls | Tokens in / out | Wall ms | Estimated cost USD | Notes |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---|",
    ])
    for r in results:
        adaptation = ", ".join(str(delay) for delay in r.adaptation_wall_ms) or "N/A"
        lines.append(
            f"| {r.run_id} | {r.preset} | {r.seed} | {r.method} | {r.decision_points} | "
            f"{r.commits} | {r.escalations} | {r.inappropriate_consensus} | "
            f"{r.justified_escalations} | {adaptation} | {r.model_calls} | "
            f"{_number(r.tokens_in)} / {_number(r.tokens_out)} | {r.wall_ms_total} | "
            f"{_number(r.cost_usd_estimate, digits=4)} | {r.notes.replace('|', '/')} |"
        )
    lines.extend([
        "",
        "Cost is N/A when model pricing has not been verified. Evacuation step N/A means unfinished at the horizon.",
        "Forecast-versus-realized differences require commit-time Evaluation records; the results CSV contains realized metrics only.",
    ])
    return "\n".join(lines) + "\n"


def write_markdown_from_csv(csv_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(read_results_csv(csv_path)))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m app.bench.report runs/results.csv docs/results.md")
    write_markdown_from_csv(Path(sys.argv[1]), Path(sys.argv[2]))
