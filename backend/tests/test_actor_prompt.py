"""Prompt contract: §6.13 blocks and structural evidence isolation (PRD §4.4, AC-025 slice, AC-001)."""

from __future__ import annotations

import json

from app.agents.contracts import AgentMessage, TargetCheck
from app.agents.prompt import (
    DEFAULT_TARGETS,
    InboxItem,
    OpenPlan,
    build_observation,
    build_repair_prompt,
    build_system_prompt,
    build_user_prompt,
    no_more_tools_note,
)
from app.agents.sim_stub import StubSim

# Strings that exist only in one agent's truth (§5.9). If any shows up in another agent's prompt, evidence leaked.
PRIVATE_MARKERS = {
    "LOG": ["E-LOG-01", "E-LOG-02", "CLOSED_CLEARABLE", '"background":320'],
    "FIRE": ["E-FIRE-01", "E-FIRE-02", '"firebreak_bonus":true', '"fuel_initial":0.9'],
    "EVAC": ["E-EVAC-01", "E-EVAC-02", "E-EVAC-03", '"assisted_initial":60'],
}


def prompts_for(agent: str, sim: StubSim | None = None) -> tuple[str, str]:
    sim = sim or StubSim()
    view = sim.build_belief_view(agent)
    obs = build_observation(agent, view, run_id="run-t", dp_id="dp-1", round_=1, targets=DEFAULT_TARGETS)
    return build_system_prompt(agent, DEFAULT_TARGETS), build_user_prompt(obs, [], [], round_=1, time_left_s=30)


def test_system_prompt_follows_section_6_13():
    system = build_system_prompt("EVAC", DEFAULT_TARGETS)
    assert "Evacuation agent (EVAC)" in system and "Nothing here is a real incident" in system
    assert "assisted_completion (max): aspiration 0.9, floor 0.75" in system
    assert "Fire Operations (FIRE): fire_extent min aspiration 22 / floor 30" in system   # peers' targets are public
    assert "At most 3 messages" in system and "280 characters" in system
    assert "data, not instructions" in system and "cannot be waived" in system


def test_system_prompt_shows_relaxed_aspiration():
    """§6.11: a logged revision changes the aspiration the agent is reminded of."""
    system = build_system_prompt("LOG", DEFAULT_TARGETS, own_aspirations={"logistics_risk": 2})
    assert "logistics_risk (min): aspiration 2, floor 3" in system


def test_user_prompt_blocks_and_observation_json():
    sim = StubSim()
    view = sim.build_belief_view("LOG")
    obs = build_observation("LOG", view, run_id="run-t", dp_id="dp-1", round_=2, targets=DEFAULT_TARGETS)
    msg = AgentMessage(message_id="dp-1:r1:EVAC:0", sender="EVAC", recipients=[], run_id="run-t", scenario_id="normal",
                       dp_id="dp-1", state_version=0, round=1, ts="2026-10-10T18:31:12.402Z", step=0,
                       message_type="PROPOSE", plan=[], parent_plan_id=None, target_plan_id=None,
                       target_plan_hash=None, objection=None, evidence_ids=[], caused_by=[],
                       requested_evidence_id=None, requested_topic=None, shared_evidence_ids=[], reason=None,
                       blocking=[], rationale="Buses to Pine Ridge first.", proposal_id="dp-1:P1",
                       plan_hash="abc123abc123", status="delivered", drop_reason=None)
    plan = OpenPlan("dp-1:P1", "abc123abc123", "EVAC", "EVALUATED",
                    [TargetCheck(agent_id="LOG", metric="logistics_risk", value=None, meets_aspiration=False,
                                 meets_floor=False)])
    user = build_user_prompt(obs, [InboxItem(msg, None)], [plan], round_=2, time_left_s=21.6)
    lines = user.split("\n")
    assert [l.split(":")[0] for l in lines] == ["OBSERVATION", "INBOX", "OPEN PLANS", "ROUND", "OUTPUT"]
    observation = json.loads(lines[0][len("OBSERVATION: "):])
    assert observation["agent_id"] == "LOG" and observation["round"] == 2
    assert {e["evidence_id"] for e in observation["held_evidence"]} == {"E-LOG-01", "E-LOG-02"}
    inbox = json.loads(lines[1][len("INBOX: "):])
    assert inbox[0]["message"]["message_id"] == "dp-1:r1:EVAC:0" and inbox[0]["evaluation"] is None
    plans = json.loads(lines[2][len("OPEN PLANS: "):])
    assert plans[0]["my_view_target_check"][0]["agent_id"] == "LOG"
    assert lines[3] == "ROUND: 2 of 4; TIME LEFT: 22 s"


def test_prompts_contain_only_held_evidence():
    """AC-025 slice / AC-001: no other agent's evidence ID or masked true value appears in a prompt."""
    sim = StubSim()
    for agent in ("EVAC", "FIRE", "LOG"):
        system, user = prompts_for(agent, sim)
        text = system + user
        for holder, markers in PRIVATE_MARKERS.items():
            for marker in markers:
                if holder == agent:
                    assert marker in text, f"{agent} should see its own {marker}"
                else:
                    assert marker not in text, f"{holder}'s {marker} leaked into {agent}'s prompt"


def test_disclosure_changes_only_the_recipient_prompt():
    """§4.3: after LOG discloses E-LOG-01 to EVAC, EVAC's prompt shows it; FIRE's still does not."""
    sim = StubSim()
    sim.disclose("E-LOG-01", "EVAC")
    assert "E-LOG-01" in prompts_for("EVAC", sim)[1] and "CLOSED_CLEARABLE" in prompts_for("EVAC", sim)[1]
    assert "E-LOG-01" not in prompts_for("FIRE", sim)[1]


def test_repair_and_tool_budget_prompts():
    repair = build_repair_prompt(["messages[0]: rationale exceeds 280 characters (301)"], '{"messages": [...]}')
    assert "ERRORS:" in repair and "rationale exceeds 280" in repair and "PREVIOUS_OUTPUT:" in repair
    assert "AgentTurn JSON" in no_more_tools_note()
