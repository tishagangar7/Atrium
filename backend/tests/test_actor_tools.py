"""Tool execution on the caller's belief view with injected ToolContext (PRD §6.2, §4.4, §10.3; AC-024, AC-022)."""

from __future__ import annotations

import json

from app.agents.provider import ToolCall
from app.agents.schema import INT_SENTINEL, parse_assignment_drafts
from app.agents.sim_stub import StubSim, world_fingerprint
from app.agents.tools import MAX_TOOL_EXECUTIONS, ToolContext, execute_tool, tool_specs

DRIVE = {"resource_id": "B1", "task": "drive", "origin": "BASE", "destination": "VJ", "route_ids": ["R1", "R3"],
         "start_step": 0, "people_count": INT_SENTINEL, "zone_id": "", "shelter_id": "", "crew_id": "",
         "target_cells": [], "edge_id": "", "duration_steps": INT_SENTINEL}
DRIVE_R2 = dict(DRIVE, destination="PR", route_ids=["R1", "R2"])


def ctx_for(sim: StubSim, agent: str, history=None) -> ToolContext:
    kwargs = dict(agent_id=agent, sim=sim, view=sim.build_belief_view(agent), run_id="run-t", dp_id="dp-1")
    if history is not None:
        kwargs["history"] = history
    return ToolContext(**kwargs)


def call(name: str, **args) -> ToolCall:
    return ToolCall(call_id="c", name=name, arguments=args)


def run(sim: StubSim, agent: str, name: str, **args):
    result, row = execute_tool(ctx_for(sim, agent), call(name, **args))
    return json.loads(result.content), result, row


def test_find_routes_uses_callers_view():
    """AC-024 / FR-013 through the tool path: EVAC sees R2 open, LOG does not."""
    sim = StubSim()
    evac, _, row = run(sim, "EVAC", "find_routes", resource_id="B1", origin="BASE", destination="PR")
    log, _, _ = run(sim, "LOG", "find_routes", resource_id="B1", origin="BASE", destination="PR")
    assert evac["routes"][0]["route_ids"] == ["R1", "R2"] and evac["basis"] == "view_EVAC"
    assert all("R2" not in r["route_ids"] for r in log["routes"]) and log["basis"] == "view_LOG"
    assert row.tool == "find_routes" and row.result_summary.endswith("routes") and not row.is_error


def test_model_supplied_agent_id_is_ignored_and_logged():
    """§4.4 #2: tool arguments never select the view; a supplied agent_id is dropped and recorded."""
    sim = StubSim()
    payload, _, row = run(sim, "EVAC", "find_routes", agent_id="LOG", resource_id="B1", origin="BASE", destination="PR")
    assert payload["routes"][0]["route_ids"] == ["R1", "R2"]       # still EVAC's view
    assert row.ignored_args == ["agent_id"] and "agent_id" not in row.args_summary


def test_bad_calls_fail_closed():
    """§10.3: unknown tool / unknown id / bad shape → error tool result, never an exception or a guess."""
    sim = StubSim()
    for name, args in [("open_road", {}),
                       ("find_routes", {"resource_id": "B9", "origin": "BASE", "destination": "PR"}),
                       ("find_routes", {"resource_id": "B1", "origin": "BASE", "destination": "MARS"}),
                       ("find_routes", {"resource_id": "B1"}),
                       ("validate_plan", {"plan": "not a list"}),
                       ("validate_plan", {"plan": [{"resource_id": "B1"}]}),
                       ("evaluate_plan", {"plan": [], "horizon": -1}),
                       ("evaluate_plan", {"plan": [DRIVE], "horizon": 99}),
                       ("get_negotiation_history", {"rounds": -5})]:
        payload, result, row = run(sim, "LOG", name, **args)
        assert result.is_error and "error" in payload and row.is_error, (name, args)


def test_validate_plan_parses_sentinel_plan():
    sim = StubSim()
    ok, _, _ = run(sim, "LOG", "validate_plan", plan=[DRIVE])
    bad, _, row = run(sim, "LOG", "validate_plan", plan=[DRIVE_R2])
    assert ok["valid"] is True and ok["violations"] == []
    assert bad["valid"] is False and bad["violations"][0]["code"] == "ROAD_CLOSED"
    assert "ROAD_CLOSED" in row.result_summary
    # the same plan is fine on EVAC's view, where R2 looks open
    evac, _, _ = run(sim, "EVAC", "validate_plan", plan=[DRIVE_R2])
    assert evac["valid"] is True


def test_evaluate_plan_returns_evaluation_on_view_and_does_not_mutate():
    """AC-022 + invariant 3: the only outcome numbers come from an Evaluation; the world is untouched."""
    sim = StubSim()
    before = world_fingerprint(sim.world)
    payload, _, row = run(sim, "LOG", "evaluate_plan", plan=[DRIVE], horizon=-1)
    assert world_fingerprint(sim.world) == before
    assert payload["basis"] == "view_LOG" and payload["kind"] == "forecast" and payload["horizon"] == 60
    assert payload["valid"] and payload["metrics"]["civilian_exposure"] == 0 and payload["trace_ref"] is None
    assert payload["evaluation_id"].startswith("ev-") and row.evaluation_id == payload["evaluation_id"]
    assert payload["leg_timing"][0]["edge_id"] == "R1"
    assert "draft" in payload["note"]


def test_history_passes_rounds_through():
    sim = StubSim()
    seen = []

    def history(rounds):
        seen.append(rounds)
        return [{"message_id": "dp-1:r1:EVAC:0"}]

    result, _ = execute_tool(ctx_for(sim, "LOG", history), call("get_negotiation_history", rounds=-1))
    execute_tool(ctx_for(sim, "LOG", history), call("get_negotiation_history", rounds=2))
    assert json.loads(result.content)["messages"][0]["message_id"] == "dp-1:r1:EVAC:0"
    assert seen == [None, 2]


def test_specs_and_budget():
    assert [s.name for s in tool_specs()] == ["find_routes", "validate_plan", "evaluate_plan", "get_negotiation_history"]
    assert MAX_TOOL_EXECUTIONS == 4   # §10.2


def test_parse_assignment_drafts_sentinels():
    drafts = parse_assignment_drafts([DRIVE])
    assert drafts[0].people_count is None and drafts[0].zone_id is None and drafts[0].start_step == 0
