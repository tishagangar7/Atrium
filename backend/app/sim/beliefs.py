"""Belief views and evidence masking (PRD §5.9, §4.3, D-05, FR-013, FR-015, AC-024).

`BeliefView(agent)` = deep copy of the authoritative world with every un-held evidence item set to its public
prior, and all derived values recomputed from the masked statics. Only statics are masked, so beliefs stay consistent
as the world evolves; a public override (a cleared road, an injected closure) is visible to everyone. Baselines get
`union` (every item that exists); the dashboard and the commit gate get `authoritative` (nothing masked, no
`held_evidence`, since it is not an agent).

Isolation is in code: a view never contains an un-held id or true value, so prompts built from it cannot leak.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from app.models import AgentId, Evidence, Scenario, WorldState
from app.sim.contract import BeliefView, ViewAgent
from app.sim.world import world_dict

_MULTI = re.compile(r"^(\w+)\[([^\]]+)\]\.(\w+)$")


def expand_field_path(path: str) -> list[list[str]]:
    """'cells[c1_1, c2_1].fuel_initial' -> [['cells','c1_1','fuel_initial'], ['cells','c2_1','fuel_initial']]."""
    m = _MULTI.match(path)
    if m:
        return [[m.group(1), key.strip(), m.group(3)] for key in m.group(2).split(",")]
    return [path.split(".")]


def mask(world: dict[str, Any], evidence: list[Evidence], agent: ViewAgent) -> list[Evidence]:
    """Set un-held items to their priors in place; return the items the agent holds (deep copies)."""
    held: list[Evidence] = []
    for e in evidence:
        if agent in ("authoritative", "union") or agent in e.holders:
            held.append(e.model_copy(deep=True))
        else:
            for path in expand_field_path(e.field_path):
                _set(world, path, e.prior_value)
    return [] if agent == "authoritative" else held


def build_view(scenario: Scenario, world: WorldState, evidence: list[Evidence], agent: ViewAgent) -> BeliefView:
    masked = world_dict(world, scenario)          # serialized copy with scenario statics
    held = mask(masked, evidence, agent)
    # Derived values must follow the masked statics (§5.9): rebuild them from the masked WorldState fields.
    masked = world_dict(WorldState.model_validate(masked), scenario) | {
        k: v for k, v in masked.items() if k not in WorldState.model_fields}
    return BeliefView(agent=agent, world=masked, held_evidence=held, state_version=world.state_version, step=world.step)


def masked_world(view: BeliefView) -> WorldState:
    """A `WorldState` rebuilt from a view (statics masked as the agent believes them); a fresh copy every call."""
    return WorldState.model_validate(copy.deepcopy(view.world))


def disclose(evidence: list[Evidence], evidence_id: str, to: AgentId) -> Evidence:
    for e in evidence:
        if e.evidence_id == evidence_id:
            e.holders.add(to)
            return e
    raise KeyError(evidence_id)


def holders(evidence: list[Evidence]) -> dict[str, list[AgentId]]:
    """§8.5 `Snapshot.evidence_holders` for the dashboard's 'known only to X' badges."""
    return {e.evidence_id: sorted(e.holders) for e in evidence}


def _set(obj: dict[str, Any], path: list[str], value: Any) -> None:
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value
