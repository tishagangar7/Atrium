"""Scenario loading (PRD §5, §5.11, §7.2). Numbers live in `scenarios/*.json`, never in code (AGENTS.md §7)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.models import Scenario

SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "scenarios"
PRESETS = ("normal", "wind_shift", "road_closure", "compound_failure")


class ScenarioNotFound(KeyError):
    pass


def scenario_path(scenario_id: str) -> Path:
    return SCENARIOS_DIR / f"{scenario_id}.json"


@lru_cache(maxsize=None)
def _load_text(scenario_id: str) -> str:
    path = scenario_path(scenario_id)
    if not path.is_file():
        raise ScenarioNotFound(scenario_id)
    return path.read_text(encoding="utf-8")


def load_scenario(scenario_id: str) -> Scenario:
    """A fresh, validated `Scenario` each call (callers may mutate their copy)."""
    return Scenario.model_validate(json.loads(_load_text(scenario_id)))


def available_scenarios() -> list[str]:
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.json"))


def param(scenario: Scenario, name: str) -> float:
    try:
        return scenario.fire_params[name]
    except KeyError as e:
        raise KeyError(f"scenario {scenario.scenario_id!r} lacks fire_params[{name!r}]") from e
