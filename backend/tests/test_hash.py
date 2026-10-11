"""Canonical plan hash (PRD §6.7, D-08; AC-006, AC-027, AC-028 prerequisite)."""

from __future__ import annotations

import json

import pytest

from app.agents.contracts import Assignment, AssignmentDraft
from app.negotiation.hash import COVERED_FIELDS, HashInputError, canonical_assignment, hash_input, plan_hash, short

RUN = "run-20261010T1830Z-normal-s1"

# The §6.7 worked example, verbatim.
PRD_HASH_INPUT = ('{"assignments":[{"crew_id":null,"destination":"VJ","duration_steps":null,"edge_id":null,'
                  '"locked":false,"origin":"BASE","people_count":null,"resource_id":"B1","route_ids":["R1","R3"],'
                  '"shelter_id":null,"start_step":0,"target_cells":[],"task":"drive","zone_id":null}],'
                  '"run_id":"run-20261010T1830Z-normal-s1","scenario_id":"normal","state_version":1}')


def assignment(**overrides) -> Assignment:
    base = dict(order=0, locked=False, resource_id="B1", task="drive", origin="BASE", destination="VJ",
                route_ids=["R1", "R3"], start_step=0, end_step=5, wait_steps=0, people_count=None, zone_id=None,
                shelter_id=None, crew_id=None, target_cells=[], edge_id=None, duration_steps=None)
    base.update(overrides)
    return Assignment(**base)


def test_hash_input_matches_prd_example_byte_for_byte():
    assert hash_input(RUN, "normal", 1, [assignment()]) == PRD_HASH_INPUT
    assert plan_hash(RUN, "normal", 1, [assignment()]) == __import__("hashlib").sha256(PRD_HASH_INPUT.encode()).hexdigest()
    assert len(short(plan_hash(RUN, "normal", 1, [assignment()]))) == 12


def test_hash_is_independent_of_key_order_and_whitespace():
    """§11.5: 'independent of key order and whitespace'."""
    as_model = plan_hash(RUN, "normal", 1, [assignment()])
    shuffled = json.loads(PRD_HASH_INPUT)["assignments"][0]
    shuffled = dict(reversed(list(shuffled.items())))
    shuffled["order"], shuffled["end_step"], shuffled["wait_steps"] = 7, 99, 3   # derived fields: ignored
    assert plan_hash(RUN, "normal", 1, [shuffled]) == as_model


def test_hash_excludes_derived_and_display_fields():
    """§6.7 step 5: plan_id, proposer, rationale, evidence, evaluations, end_step and waits are not covered."""
    a, b = assignment(), assignment(order=3, end_step=40, wait_steps=9)
    assert plan_hash(RUN, "normal", 1, [a]) == plan_hash(RUN, "normal", 1, [b])
    assert set(COVERED_FIELDS).isdisjoint({"order", "end_step", "wait_steps", "plan_id", "proposer", "rationale"})


@pytest.mark.parametrize("field,value", [
    ("start_step", 1), ("route_ids", ["R1", "R3", "R5"]), ("destination", "SS"), ("resource_id", "B2"),
    ("task", "hold"), ("people_count", 30), ("locked", True), ("target_cells", ["c1_1"]), ("duration_steps", 3),
])
def test_hash_changes_when_any_covered_field_changes(field, value):
    """AC-027 `test_near_identical`: two plans differing only in one start_step (or any covered field) differ."""
    assert plan_hash(RUN, "normal", 1, [assignment()]) != plan_hash(RUN, "normal", 1, [assignment(**{field: value})])


def test_hash_covers_run_and_state_version():
    """AC-006: the same assignments at another state_version are a different plan hash (stale acceptances)."""
    h = plan_hash(RUN, "normal", 1, [assignment()])
    assert h != plan_hash(RUN, "normal", 2, [assignment()])
    assert h != plan_hash("run-other", "normal", 1, [assignment()])
    assert h != plan_hash(RUN, "wind_shift", 1, [assignment()])


def test_assignments_are_sorted_by_start_resource_then_index():
    """§6.7 step 3: order in the message does not matter; (start_step, resource_id, index) does."""
    a = assignment(resource_id="B2", start_step=0)
    b = assignment(resource_id="B1", start_step=0)
    c = assignment(resource_id="B1", start_step=3, task="load", route_ids=[], destination="VJ", people_count=30, zone_id="VJ")
    assert plan_hash(RUN, "normal", 1, [a, b, c]) == plan_hash(RUN, "normal", 1, [c, a, b])
    order = [x["resource_id"] + str(x["start_step"]) for x in json.loads(hash_input(RUN, "normal", 1, [c, a, b]))["assignments"]]
    assert order == ["B10", "B20", "B13"]


def test_identical_drafts_from_two_agents_hash_identically():
    draft = AssignmentDraft(resource_id="B1", task="drive", origin="BASE", destination="VJ", route_ids=["R1", "R3"],
                            start_step=0, people_count=None, zone_id=None, shelter_id=None, crew_id=None,
                            target_cells=[], edge_id=None, duration_steps=None)
    assert plan_hash(RUN, "normal", 1, [draft]) == plan_hash(RUN, "normal", 1, [assignment()])


def test_unnormalized_plan_cannot_be_hashed():
    """Normalization (§6.7 step 1) must fill start_step first; hashing a None start_step is a programming error."""
    with pytest.raises(HashInputError):
        canonical_assignment({"resource_id": "B1", "task": "drive", "start_step": None})
    with pytest.raises(HashInputError):
        canonical_assignment({"resource_id": "B1", "task": "drive", "start_step": 0, "people_count": 2.5})
