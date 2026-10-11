"""Scenario tuning gate (PRD §5.13). Run from the repo root:

    cd backend && uv run python ../scenarios/tune.py            # all three checks, seeds 1-3
    cd backend && uv run python ../scenarios/tune.py --quick    # fewer samples, for iteration

Checks, for seeds 1-3 (forecasts on the authoritative world, no future events — D-15):
1. Conflict exists in `normal`: the fixed-rule plan misses at least one agent's aspiration, AND at least one plan
   from a 300-plan random sampler meets all floors.
2. Escalation is justified in `compound_failure`: none of 500 sampled feasible plans meets all three agents' floors
   after the step-15 events.
3. Disruption matters: the committed `normal` plan becomes invalid or misses a floor after the `road_closure` event.

Tune the JSON (never the rules) and record changes in scenarios/CHANGELOG.md. Exit code 0 = all checks pass.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.baselines.fixed_rule import FixedRulePlanner  # noqa: E402
from app.models import Assignment, AssignmentDraft  # noqa: E402
from app.sim.contract import BeliefView  # noqa: E402
from app.sim.service import SimulatorService  # noqa: E402
from app.sim.metrics import target_checks  # noqa: E402
from app.sim.world import cells_within  # noqa: E402

SEEDS = (1, 2, 3)
EVENT_STEP = 15


def _draft(resource: str, task: str, **kw) -> AssignmentDraft:
    return AssignmentDraft(resource_id=resource, task=task, origin=kw.get("origin"), destination=kw.get("destination"),
                           route_ids=list(kw.get("route_ids", [])), start_step=kw.get("start_step"),
                           people_count=kw.get("people_count"), zone_id=kw.get("zone_id"),
                           shelter_id=kw.get("shelter_id"), crew_id=kw.get("crew_id"),
                           target_cells=list(kw.get("target_cells", [])), edge_id=kw.get("edge_id"),
                           duration_steps=kw.get("duration_steps"))


# --- random feasible plans ------------------------------------------------------------------------------------------

def sample_plan(sim: SimulatorService, view: BeliefView, rng: random.Random,
                locked: list[Assignment] | None = None) -> list[AssignmentDraft]:
    """A random plan built step by step; every step is kept only if the simulator validator accepts it."""
    world = view.world
    horizon = int(world["horizon"])
    plan: list[AssignmentDraft] = list(locked or [])
    pos = {rid: r["node"] for rid, r in world["resources"].items()}
    locked_ids = {a.resource_id for a in plan}

    def keep(steps: list[AssignmentDraft]) -> bool:
        nonlocal plan
        cand = [*plan, *steps]
        if sim.validate_plan(view, cand):
            return False
        timing = sim.plan_timing(view, cand)
        if not timing or timing[-1]["end_step"] > horizon:
            return False
        plan = cand
        return True

    def route(rid: str, a: str, b: str):
        found = sim.find_routes(view, a, b, resource_id=rid)
        return rng.choice(found) if found else None

    crews = sorted(r for r, d in world["resources"].items() if d["type"] == "crew" and d.get("available", True))
    vehicles = sorted(r for r, d in world["resources"].items()
                      if d["type"] in ("bus", "transport") and d.get("available", True))

    # V1 sometimes ferries a crew (the shared-resource conflict, §5.3)
    if "V1" in vehicles and pos.get("V1") and crews and rng.random() < 0.4 and "V1" not in locked_ids:
        crew = rng.choice(crews)
        crew_node = pos[crew]
        dest = rng.choice(sorted(world["nodes"]))
        to_crew = route("V1", pos["V1"], crew_node) if pos["V1"] != crew_node else None
        steps = []
        if pos["V1"] != crew_node and to_crew:
            steps.append(_draft("V1", "drive", origin=pos["V1"], destination=crew_node, route_ids=to_crew.route_ids))
        ferry = route("V1", crew_node, dest)
        if ferry and dest != crew_node and (pos["V1"] == crew_node or to_crew):
            steps.append(_draft("V1", "transfer_crew", origin=crew_node, destination=dest, route_ids=ferry.route_ids,
                                crew_id=crew))
            if keep(steps):
                pos["V1"], pos[crew] = dest, dest

    # Evacuation trips: random order and choices, but only sensible ones (people still waiting, a shelter with room),
    # so the sampler explores the trade-offs instead of mostly-empty plans.
    waiting = {z: int(d["assisted_waiting"]) for z, d in world["zones"].items()}
    room = {s_: int(d["remaining"]) for s_, d in world["shelters"].items()}
    order = rng.sample(vehicles, len(vehicles))
    for _ in range(rng.randint(2, 8)):
        rid = rng.choice(order)
        if rid in locked_ids or pos.get(rid) is None:
            continue
        zones = [z for z in sorted(waiting) if waiting[z] > 0]
        if not zones:
            break
        zone = rng.choice(zones)
        cap = int(world["resources"][rid]["capacity"])
        people = min(cap, waiting[zone])
        shelters = [s_ for s_ in sorted(room) if room[s_] >= people]
        if not shelters:
            continue
        shelter = rng.choice(shelters)
        go = route(rid, pos[rid], zone) if pos[rid] != zone else None
        back = route(rid, zone, shelter)
        if back is None or (pos[rid] != zone and go is None):
            continue
        steps = []
        if go:
            steps.append(_draft(rid, "drive", origin=pos[rid], destination=zone, route_ids=go.route_ids))
        steps += [_draft(rid, "load", origin=zone, destination=zone, zone_id=zone, people_count=people),
                  _draft(rid, "drive", origin=zone, destination=shelter, route_ids=back.route_ids),
                  _draft(rid, "unload", origin=shelter, destination=shelter, shelter_id=shelter)]
        if keep(steps):
            pos[rid] = shelter
            waiting[zone] -= people
            room[shelter] -= people

    for crew in crews:
        if crew in locked_ids or pos.get(crew) is None or rng.random() < 0.15:
            continue
        node = rng.choice(sorted(world["nodes"]))
        steps = []
        if node != pos[crew]:
            r = route(crew, pos[crew], node)
            if r is None:
                continue
            steps.append(_draft(crew, "drive", origin=pos[crew], destination=node, route_ids=r.route_ids))
        near = cells_within(world["nodes"][node], 1, tuple(world["grid"]))
        targets = rng.sample(near, min(len(near), rng.randint(1, 3)))
        steps.append(_draft(crew, "contain", target_cells=targets, duration_steps=rng.randint(3, 30)))
        if keep(steps):
            pos[crew] = node
    return plan


def meets_all_floors(evaluation) -> bool:
    return evaluation.valid and all(c.meets_floor for c in evaluation.target_checks)


def meets_all_aspirations(evaluation) -> bool:
    return evaluation.valid and all(c.meets_aspiration for c in evaluation.target_checks)


# --- the three checks -----------------------------------------------------------------------------------------------

def check_conflict(seed: int, samples: int) -> tuple[bool, str]:
    sim = SimulatorService("normal", seed)
    auth = sim.build_belief_view("authoritative")
    fixed = FixedRulePlanner(sim).plan(sim.build_belief_view("union"))
    fixed_ev = sim.evaluate_plan(auth, fixed, plan_hash="fixed")
    rng = random.Random(1000 + seed)
    feasible = 0
    for i in range(samples):
        plan = sample_plan(sim, sim.build_belief_view("authoritative"), rng)
        if meets_all_floors(sim.evaluate_plan(auth, plan, plan_hash=f"s{i}")):
            feasible += 1
    ok = (not meets_all_aspirations(fixed_ev)) and feasible > 0
    return ok, f"fixed-rule misses an aspiration: {not meets_all_aspirations(fixed_ev)}; sampled plans meeting all floors: {feasible}/{samples}"


def _world_after_events(preset: str, seed: int) -> SimulatorService:
    """Execute the fixed-rule plan to the step-15 pause, so the events have fired on the authority."""
    sim = SimulatorService(preset, seed)
    view = sim.build_belief_view("union")
    drafts = FixedRulePlanner(sim).plan(view)
    timing = sim.plan_timing(view, drafts)
    plan = [Assignment(**d.model_dump() | {"order": i, "locked": False, "start_step": t["start_step"],
                                            "end_step": t["end_step"], "wait_steps": t["wait_steps"]})
            for i, (d, t) in enumerate(zip(drafts, timing))]
    sim.apply_accepted_plan(plan, "fixed")
    while sim.world.step < EVENT_STEP:
        sim.step(EVENT_STEP - sim.world.step)
    sim.step(1)                                                # the step-15 events apply here and pause the run
    return sim


def check_escalation_justified(seed: int, samples: int) -> tuple[bool, str]:
    sim = _world_after_events("compound_failure", seed)
    auth = sim.build_belief_view("authoritative")
    locked = sim.locked_legs()
    rng = random.Random(2000 + seed)
    best = 0
    for i in range(samples):
        plan = sample_plan(sim, sim.build_belief_view("authoritative"), rng, locked=locked)
        ev = sim.evaluate_plan(auth, plan, plan_hash=f"c{i}")
        if meets_all_floors(ev):
            return False, f"sample {i} meets all floors after the compound events"
        best = max(best, sum(c.meets_floor for c in ev.target_checks) if ev.valid else 0)
    return True, f"no sampled plan meets all floors (best: {best} of 5 floors)"


def _execute_committed(preset: str, seed: int):
    """Commit the fixed-rule plan at step 0 and execute it to the horizon with no renegotiation: scheduled events still
    fire (and pause), the plan simply continues. Returns (realized target checks, legs skipped for a closed road)."""
    sim = SimulatorService(preset, seed)
    view = sim.build_belief_view("union")
    drafts = FixedRulePlanner(sim).plan(view)
    timing = sim.plan_timing(view, drafts)
    plan = [Assignment(**d.model_dump() | {"order": i, "locked": False, "start_step": t["start_step"],
                                            "end_step": t["end_step"], "wait_steps": t["wait_steps"]})
            for i, (d, t) in enumerate(zip(drafts, timing))]
    sim.apply_accepted_plan(plan, "fixed")
    skipped = 0
    while sim.world.step < sim.scenario.horizon:
        sim.step(sim.scenario.horizon - sim.world.step)
        skipped += sum(1 for c in sim.last_changes
                       if c.get("kind") == "task.skipped_unsafe" and c["data"].get("reason") == "ROAD_CLOSED")
    return target_checks(sim.realized_metrics(), sim.scenario.targets), skipped


def check_disruption_matters(seed: int) -> tuple[bool, str]:
    """The plan committed in `normal` is carried unchanged through the `road_closure` event: the closure must make it
    skip a leg or miss a floor that it met without the event."""
    base_checks, base_skipped = _execute_committed("normal", seed)
    closed_checks, closed_skipped = _execute_committed("road_closure", seed)
    base_ok = {c.metric for c in base_checks if c.meets_floor}
    newly_missed = sorted(c.metric for c in closed_checks if not c.meets_floor and c.metric in base_ok)
    ok = closed_skipped > base_skipped or bool(newly_missed)
    return ok, (f"legs skipped for a closed road: {base_skipped} → {closed_skipped}; "
                f"floors newly missed after the closure: {newly_missed or 'none'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="60/100 samples instead of 300/500")
    args = parser.parse_args()
    n1, n2 = (60, 100) if args.quick else (300, 500)
    all_ok = True
    for seed in SEEDS:
        for name, (ok, detail) in (("1 conflict (normal)", check_conflict(seed, n1)),
                                   ("2 escalation justified (compound_failure)", check_escalation_justified(seed, n2)),
                                   ("3 disruption matters (road_closure)", check_disruption_matters(seed))):
            all_ok &= ok
            print(f"seed {seed} · check {name}: {'PASS' if ok else 'FAIL'} — {detail}")
    print("ALL CHECKS PASS" if all_ok else "SOME CHECKS FAIL — tune scenarios/*.json (never the rules)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
