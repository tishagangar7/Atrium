"""Shared data contracts for RescueMesh (PRD §7, §8.5).

Sole editor: Tisha / WS-C (AGENTS.md §2, §12.2). Madhav (WS-A) and Ali (WS-B) review
the fields relevant to their workstreams before G0; after G0, schema changes need the
producing and consuming owners to agree first (a `contracts/<name>-<slug>` branch with
`[contract]` in the PR title).

Conventions (PRD §7 preamble):
- IDs are strings, formats per PRD §7.
- `ts` is ISO 8601 UTC with milliseconds; `step` is an integer simulated step. Never
  interchangeable.
- `state_version` starts at 0 on reset; increments on every event application and commit.
- Optional fields are `None`, never missing, in model outputs (strict structured output
  requires every field present; see the model-facing sentinel variant in `app/agents`,
  owned by WS-B).
- Every top-level object that the PRD lists with `schema_version` carries
  `schema_version: Literal["1"] = "1"`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SchemaVersion = Literal["1"]

# --- 7.1 Enums ---------------------------------------------------------------

AgentId = Literal["EVAC", "FIRE", "LOG"]
ResourceType = Literal["bus", "transport", "crew"]
TaskType = Literal[
    "drive", "load", "unload", "transfer_crew", "contain", "clear_road", "refuel", "hold"
]
RoadStatus = Literal["OPEN", "CLOSED_CLEARABLE", "CLOSED_HARD"]
CellState = Literal["UNBURNED", "BURNING", "BURNED_OUT", "EXTINGUISHED"]
WindDir = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
MessageType = Literal[
    "PROPOSE",
    "COUNTERPROPOSE",
    "CHALLENGE",
    "REQUEST_EVIDENCE",
    "SHARE_EVIDENCE",
    "ACCEPT",
    "WITHDRAW",
    "ESCALATE",
]
PlanState = Literal[
    "PROPOSED",
    "EVALUATED",
    "CHALLENGED",
    "PARTIALLY_ACCEPTED",
    "UNANIMOUS",
    "COMMITTED",
    "REJECTED_AT_COMMIT",
    "WITHDRAWN",
    "STALE",
    "ESCALATED",
    "SUPERSEDED",
]
EvalBasis = Literal["view_EVAC", "view_FIRE", "view_LOG", "authoritative", "union"]
Method = Literal["rescuemesh", "fixed_rule", "single_agent"]
RunMode = Literal["live", "replay", "benchmark"]
ViolationCode = Literal[
    "ROAD_CLOSED",
    "ROAD_NOT_ENGINE_CAPABLE",
    "RESOURCE_DOUBLE_BOOKED",
    "RESOURCE_UNAVAILABLE",
    "UNKNOWN_RESOURCE",
    "VEHICLE_OVER_CAPACITY",
    "SHELTER_OVER_CAPACITY",
    "FUEL_INSUFFICIENT",
    "WRONG_LOCATION",
    "TARGET_TOO_INTENSE",
    "TARGET_OUT_OF_REACH",
    "MIXED_PAYLOAD",
    "SCHEDULE_OVERRUN",
    "LOCKED_LEG_CHANGED",
    "NO_CHANGE",
]

# --- 7.3 Evidence and Target ---------------------------------------------------

EvidenceValue = str | int | float | bool


class Evidence(BaseModel):
    evidence_id: str
    holders: set[AgentId]  # grows only by disclosure
    field_path: str  # e.g. "roads.R2.initial_status"
    true_value: EvidenceValue
    prior_value: EvidenceValue
    summary: str = Field(max_length=160)  # shown to holders and UI
    observed_step: int
    confidence: Literal["low", "medium", "high"]


class Target(BaseModel):
    metric: Literal[
        "assisted_completion", "civilian_exposure", "fire_extent", "crew_risk_steps", "logistics_risk"
    ]
    direction: Literal["min", "max"]
    aspiration: float
    floor: float
    revisable_by_agent: bool = True


# --- 7.2 Scenario and WorldState: base entities --------------------------------


class Road(BaseModel):
    id: str
    a: str
    b: str
    travel_steps: int = Field(ge=1)
    capacity: int = Field(ge=1)  # vehicles on the edge at once
    engine_ok: bool
    initial_status: RoadStatus  # static; may be masked by evidence
    status_override: RoadStatus | None  # set by public events or clear_road
    clear_progress: int = Field(ge=0, le=6)  # steps of clearing work done


class Zone(BaseModel):
    id: str
    name: str
    cell: str
    unassisted_initial: int  # static
    assisted_initial: int  # static
    self_evacuated: int  # counter
    assisted_picked_up: int  # counter
    # derived (computed by the simulator, not stored here): unassisted_in_zone, assisted_waiting


class Shelter(BaseModel):
    id: str
    name: str
    cell: str
    capacity: int
    background: int  # static
    arrivals: int  # counter


class Cell(BaseModel):
    id: str
    x: int
    y: int
    fuel_initial: float
    fuel_burned: float
    firebreak_bonus: bool
    state: CellState
    intensity: int
    ignited_step: int | None


class Resource(BaseModel):
    id: str
    type: ResourceType
    node: str | None  # None while on an edge
    edge: str | None
    edge_steps_left: int
    capacity: int  # civilians; 0 for crews
    fuel_capacity: int | None
    fuel_used: int
    aboard_people: dict[str, int]  # origin zone -> count
    aboard_crew: str | None  # V1 only
    engine_node: str | None  # crews: where their engine is
    available: bool  # False when OUT_OF_SERVICE


class Wind(BaseModel):
    direction: WindDir
    speed: int = Field(ge=1, le=3)


class ScheduledEvent(BaseModel):
    event_id: str
    step: int
    kind: Literal["wind_change", "road_status", "resource_status"]
    target: str | None
    value: str | int | None
    public: bool = True


# --- 7.5 / 7.6 Assignments (needed by Observation, Plan) -----------------------


class AssignmentDraft(BaseModel):
    """What an agent writes."""

    resource_id: str
    task: TaskType
    origin: str | None
    destination: str | None
    route_ids: list[str]  # may be empty -> filled at normalization
    start_step: int | None
    people_count: int | None
    zone_id: str | None
    shelter_id: str | None
    crew_id: str | None
    target_cells: list[str]
    edge_id: str | None
    duration_steps: int | None  # contain only


class Assignment(AssignmentDraft):
    """Normalized."""

    order: int
    locked: bool
    route_ids: list[str]
    start_step: int
    end_step: int  # computed by runtime
    wait_steps: int  # computed


# --- 7.6 Leg, Violation, Metrics, TargetCheck -----------------------------------


class Leg(BaseModel):
    """Executable unit."""

    resource_id: str
    kind: str  # "traverse", "load", "unload", "work", "board", "drop", "refuel"
    edge_id: str | None
    node: str | None
    start_step: int
    end_step: int


class Violation(BaseModel):
    code: ViolationCode
    assignment_order: int | None
    resource_id: str | None
    road_id: str | None
    detail: str


class Metrics(BaseModel):
    civilian_exposure: int  # person-steps
    assisted_completion: float | None  # None when assisted demand is 0 (reported N/A)
    assisted_sheltered: int
    assisted_demand: int
    evacuation_completion_step: int | None  # None = unfinished by horizon
    fire_extent: int  # cells ever ignited
    burning_cell_steps: int
    crew_risk_steps: int
    logistics_risk: int
    invalid_attempted: int
    invalid_executed: int


class TargetCheck(BaseModel):
    agent_id: AgentId
    metric: str
    value: float | None
    meets_aspiration: bool
    meets_floor: bool


# --- 7.2 Scenario and WorldState: composites ------------------------------------


class Scenario(BaseModel):
    schema_version: SchemaVersion = "1"
    scenario_id: str
    title: str
    horizon: int
    step_minutes: int
    grid: tuple[int, int]
    nodes: dict[str, str]  # node id -> cell id
    roads: list[Road]
    zones: list[Zone]
    shelters: list[Shelter]
    cells: list[Cell]
    resources: list[Resource]
    wind: Wind
    fire_params: dict[str, float]  # k, growth_every, burn_rate, ...
    evidence: list[Evidence]
    events: list[ScheduledEvent]
    targets: dict[AgentId, list[Target]]
    label: Literal["Synthetic simulation"]


class WorldState(BaseModel):
    schema_version: SchemaVersion = "1"
    run_id: str
    scenario_id: str
    seed: int
    step: int
    state_version: int
    roads: dict[str, Road]
    zones: dict[str, Zone]
    shelters: dict[str, Shelter]
    cells: dict[str, Cell]
    resources: dict[str, Resource]
    wind: Wind
    committed_plan_hash: str | None
    active_legs: list[Leg]  # expanded from the committed plan
    metrics_so_far: Metrics
    paused: bool


# --- 7.4 Observation -------------------------------------------------------------


class Observation(BaseModel):
    schema_version: SchemaVersion = "1"
    agent_id: AgentId
    run_id: str
    dp_id: str
    state_version: int
    step: int
    round: int
    world: dict  # BeliefView world, serialized (WS-A belief view shape)
    held_evidence: list[Evidence]  # only items this agent holds; true_value included
    public_events: list[ScheduledEvent]  # already applied
    targets: dict[AgentId, list[Target]]  # public
    locked_assignments: list[Assignment]


# --- 7.5 AgentTurn (model output) and AgentMessage -------------------------------


class Objection(BaseModel):
    kind: Literal["infeasible", "target_unmet", "evidence_conflict", "risk"]
    metric: str | None
    evaluation_id: str | None
    proposed_amendment: str | None = Field(default=None, max_length=200)


class TargetRevision(BaseModel):
    by: Literal["EVAC", "FIRE", "LOG", "human"]
    metric: str
    old_aspiration: float
    new_aspiration: float
    reason: str
    dp_id: str


class TurnMessage(BaseModel):
    message_type: MessageType
    recipients: list[AgentId]  # empty = all peers
    plan: list[AssignmentDraft] | None
    parent_plan_id: str | None
    target_plan_id: str | None
    target_plan_hash: str | None
    objection: Objection | None
    evidence_ids: list[str]  # cited (and so disclosed) evidence
    caused_by: list[str]  # message or evidence IDs behind a revision
    requested_evidence_id: str | None
    requested_topic: str | None
    shared_evidence_ids: list[str]
    reason: str | None
    blocking: list[str]
    rationale: str = Field(max_length=280)


class AgentTurn(BaseModel):
    messages: list[TurnMessage]  # 0..3 (0 = deliberate silence)
    target_revision: TargetRevision | None


class AgentMessage(TurnMessage):
    """Stored and streamed; the router adds these envelope fields to each TurnMessage."""

    schema_version: SchemaVersion = "1"
    message_id: str
    sender: AgentId
    run_id: str
    scenario_id: str
    dp_id: str
    state_version: int
    round: int
    ts: str
    step: int
    proposal_id: str | None
    plan_hash: str | None
    status: Literal["delivered", "dropped"]
    drop_reason: str | None


# --- 7.6 Plan, Evaluation -----------------------------------------------------


class Plan(BaseModel):
    schema_version: SchemaVersion = "1"
    plan_id: str
    plan_hash: str
    proposer: AgentId
    parent_plan_id: str | None
    run_id: str
    dp_id: str
    state_version: int
    assignments: list[Assignment]
    evidence_ids: list[str]
    state: PlanState
    evaluation_ids: list[str]  # attached at delivery
    tradeoffs: list[str]  # filled from evaluations: unmet targets per agent
    expected_shelter_use: dict[str, int]  # computed


class Evaluation(BaseModel):
    schema_version: SchemaVersion = "1"
    evaluation_id: str
    plan_hash: str
    basis: EvalBasis
    kind: Literal["forecast", "realized"]
    run_id: str
    state_version: int
    from_step: int
    horizon: int
    seed: int
    valid: bool
    violations: list[Violation]
    metrics: Metrics | None  # None when invalid
    target_checks: list[TargetCheck]
    leg_timing: list[Leg]
    trace_ref: str | None  # file path of compact per-step trace
    sim_ms: int


# --- 7.7 Acceptance, TargetRevision, Commit, Escalation --------------------------


class Acceptance(BaseModel):
    agent_id: AgentId
    plan_hash: str
    dp_id: str
    state_version: int
    via: Literal["ACCEPT", "PROPOSE", "COUNTERPROPOSE"]
    message_id: str
    round: int
    revoked: bool


class Commit(BaseModel):
    schema_version: SchemaVersion = "1"
    run_id: str
    dp_id: str
    plan_hash: str
    plan_id: str
    state_version_before: int
    state_version_after: int
    acceptances: list[Acceptance]  # exactly 3 unless human
    ordering_rule: Literal["first_proposed_seq"]
    authority: Literal["unanimous", "human_choice", "auto_fallback"]
    authoritative_evaluation_id: str
    ts: str
    step: int


class EscalationPackage(BaseModel):
    schema_version: SchemaVersion = "1"
    run_id: str
    dp_id: str
    state_version: int
    trigger: Literal["ROUNDS_EXHAUSTED", "BUDGET_EXCEEDED", "ALL_ESCALATED", "AGENT_UNAVAILABLE"]
    candidates: list[str]  # plan_hashes valid on the authoritative world
    candidate_checks: dict[str, list[TargetCheck]]
    unmet_targets: dict[AgentId, list[str]]
    open_objections: list[str]  # message_ids
    blocking_constraints: list[str]
    fallback_plan_hash: str


# --- 7.8 SimulationEvent, RunResult, ErrorObject ---------------------------------


class SimulationEvent(BaseModel):
    """A fact that happened in the world, streamed and logged."""

    schema_version: SchemaVersion = "1"
    run_id: str
    step: int
    state_version: int
    kind: Literal[
        "event.applied",
        "leg.started",
        "leg.completed",
        "people.sheltered",
        "cell.ignited",
        "cell.extinguished",
        "road.opened",
        "task.skipped_unsafe",
        "invariant.failed",
    ]
    data: dict


class RunResult(BaseModel):
    """One row of runs/results.csv."""

    run_id: str
    preset: str
    seed: int
    method: Method
    model: str | None
    budget_calls: int | None
    budget_tokens: int | None
    metrics: Metrics  # realized, at horizon
    decision_points: int
    commits: int
    escalations: int
    human_decisions: int
    inappropriate_consensus: int
    justified_escalations: int
    adaptation_wall_ms: list[int]  # per disruption
    model_calls: int
    tokens_in: int | None
    tokens_out: int | None
    wall_ms_total: int
    cost_usd_estimate: float | None  # None if pricing unverified
    notes: str


class ErrorObject(BaseModel):
    code: Literal[
        "STATE_VERSION_MISMATCH",
        "RUN_MISMATCH",
        "NOT_FOUND",
        "INVALID_REQUEST",
        "NEGOTIATION_IN_PROGRESS",
        "NO_ACTIVE_ESCALATION",
        "PLAN_INFEASIBLE",
        "MODEL_UNAVAILABLE",
        "REPLAY_READ_ONLY",
        "BUDGET_EXCEEDED",
        "INTERNAL",
        # Added in C6: §8.2's POST /benchmarks/run specifies "409 if one is running" but
        # never names a code for it; NEGOTIATION_IN_PROGRESS is specifically about the
        # /negotiate decision-point lifecycle, not benchmarks, so it doesn't fit.
        "BENCHMARK_IN_PROGRESS",
    ]
    message: str
    retryable: bool
    run_id: str | None
    state_version: int | None
    details: dict


# --- 8.5 Snapshot -----------------------------------------------------------------


class Snapshot(BaseModel):
    schema_version: SchemaVersion = "1"
    run_id: str
    mode: RunMode
    last_seq: int
    world: WorldState  # authoritative (operator view)
    evidence_holders: dict[str, list[AgentId]]  # who knows what, for the map badges
    dp_id: str | None
    negotiation_status: Literal["idle", "running", "committed", "escalated", "cancelled"]
    committed_plan: Plan | None
    escalation: EscalationPackage | None
    label: Literal["Synthetic simulation"]
    # Public agent targets (§5.12, §6.1: targets are public), current after any logged revision (§6.11). Lets the
    # dashboard show each agent's objective and offer bounded relax controls (§9.3, §9.7). None for non-PRD fixtures.
    targets: dict[AgentId, list[Target]] | None = None
