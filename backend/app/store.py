"""JSONL event persistence (PRD §4.7, §12.7). Owner: Tisha / WS-C.

Every envelope is appended to `runs/<run_id>/events.jsonl` with a strictly increasing `seq`.
`runs/` is git-ignored except `runs/fixtures/` and `runs/results.csv` (see .gitignore); this
module only ever writes under a run's own sub-directory.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"

MAX_EVENTS_FILE_BYTES = 20 * 1024 * 1024  # NFR-010: event log per run <= 20 MB


def run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def events_path(run_id: str) -> Path:
    return run_dir(run_id) / "events.jsonl"


def start_run(run_id: str) -> None:
    """Create (or truncate) this run's events.jsonl. Always call before the first
    `append_event` for a `run_id`: the PRD's run_id format (§7) has minute granularity,
    so a restarted process resetting with the same scenario/seed within the same clock
    minute would otherwise silently append onto a stale file from an earlier process."""
    path = events_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")


def append_event(run_id: str, envelope: dict) -> None:
    path = events_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(envelope))
        f.write("\n")
    size = path.stat().st_size
    assert size <= MAX_EVENTS_FILE_BYTES, (
        f"events.jsonl for {run_id} is {size} bytes, over the NFR-010 bound of "
        f"{MAX_EVENTS_FILE_BYTES} bytes"
    )


def read_events(run_id: str) -> list[dict]:
    path = events_path(run_id)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def list_run_ids() -> list[str]:
    if not RUNS_DIR.exists():
        return []
    return sorted(
        p.name for p in RUNS_DIR.iterdir()
        if p.is_dir() and p.name not in ("fixtures",) and (p / "events.jsonl").exists()
    )


def run_summary(run_id: str) -> dict | None:
    """PRD §8.2 GET /runs row shape: {run_id, preset, seed, method, mode, created_ts,
    final_state_hash}. Not one of §7's named contracts -- a plain dict, like
    ResetRequest/StepRequest in app.main."""
    events = read_events(run_id)
    if not events:
        return None
    first, last = events[0], events[-1]
    reset_data = first.get("data", {}) if first.get("type") == "run.reset" else {}
    final_state_hash = last.get("data", {}).get("final_state_hash") if last.get("type") == "run.closed" else None
    return {
        "run_id": run_id,
        "preset": reset_data.get("scenario_id"),
        "seed": reset_data.get("seed"),
        "method": "rescuemesh",  # no fixed_rule/single_agent baseline runs exist yet (C6)
        "mode": first.get("mode", "live"),
        "created_ts": first.get("ts"),
        "final_state_hash": final_state_hash,
    }
