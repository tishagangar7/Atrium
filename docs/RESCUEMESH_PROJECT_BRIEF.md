# RescueMesh: Forest-Fire Response Through Collective AI
## Master project brief
Version: 1.0 | Prepared: October 9, 2026 (Pacific time)  
Event: UCSC AI Hackathon @ SF Tech Week, October 10-11, 2026  
Target: Cisco Cloud AI track, Level 3 - Build a Collective Intelligence

> **One-line pitch:** When a wildfire changes direction, three independent AI agents negotiate how to use limited crews, evacuation vehicles, and safe routes, test competing plans in a simulation, and explain their agreement - or why a human must decide.

## 1. Context and status

RescueMesh is the project selected in the discussion. The demo focuses on forest fires. The goal is a strong Cisco Level 3 entry with potential to compete for Best Overall.

This document is the working source of truth for implementation and pitching. The project choice and forest-fire focus are established; the detailed agents, scenario numbers, architecture, and build plan below are proposed implementation defaults. No software, performance results, real-world validation, or prize outcome is claimed.

The supplied track PDF is the authority for the eligibility mapping in this brief. It does not provide a separate Best Overall judging rubric. Winning potential is a strategic assessment, not a guarantee.

## 2. The problem and product

A wildfire response involves several reasonable priorities that cannot always be satisfied at once:
- Protect people who need help evacuating.
- Use firefighting crews to reduce the modeled threat.
- Keep vehicles and crews on usable routes with enough fuel and shelter capacity.

A plan that looks best for one objective can make another worse. Sending a shared vehicle to move a crew may leave a neighborhood without transport. Opening an evacuation route may consume the same crew needed elsewhere. A wind shift can make yesterday's sensible allocation invalid.

RescueMesh makes those disagreements visible and actionable. Each agent gets its own evidence, objectives, and tools. Agents propose structured plans, challenge each other's assumptions, simulate alternatives, and negotiate revisions.

The demo is a synthetic decision-support sandbox. It does not issue real evacuation orders or model operational wildfire behavior. Its strength is demonstrating collective decision-making under changing constraints.

### User and main workflow

The demo user is an incident coordinator reviewing simulated response options.

1. Open the incident map.
2. Inspect current resources, risks, and evidence.
3. Start negotiation.
4. Watch proposals, objections, and tested alternatives.
5. Inspect the accepted plan and its trade-offs.
6. Trigger a disruption and watch the agents reconsider.
7. Review a deadlock or approve an explicitly labeled human override.
8. Compare outcomes with simpler approaches.

## 3. What makes it distinctive

Disaster coordination is already an example in the challenge. Originality must come from the mechanism and demonstration, rather than the disaster theme alone.

**Primary differentiator: counterfactual negotiation.** Agents cannot settle a conflict using persuasive text alone. They attach a structured plan and simulator results to each proposal. Another agent can test an alternative and challenge the original with concrete evidence.

**Secondary differentiators:**
- Local knowledge: agents initially see different evidence.
- Traceable revisions: every changed decision points to the evidence or objection that caused it.
- Explicit unresolved disagreement: the UI shows what prevented consensus.
- Paired comparison: the same scenarios and resource limits are used for all methods.

Counterfactual negotiation is the project's proposed feature name, not a claim that the underlying concept is novel research.

## 4. The three autonomous agents

Use exactly three decision-making agents for the MVP. Additional agents are stretch work.

| Agent | Main objective | Initial private evidence | Tools | Example conflict |
| --- | --- | --- | --- | --- |
| Evacuation Agent | Reduce modeled civilian exposure and evacuation delay, with attention to people needing assistance | Population counts, assisted-evacuation demand, estimated vehicle loading times | Inspect zones, calculate evacuation demand, evaluate a plan | Wants the shared transport vehicle for a vulnerable community |
| Fire Operations Agent | Reduce modeled fire growth and exposure of communities while limiting crew risk | Crew capabilities, containment opportunities, local fire observations | Inspect fire state, estimate action effects, evaluate a plan | Wants that vehicle to reposition a crew to a threatened corridor |
| Logistics Agent | Keep allocations feasible: travel, fuel, resource availability, route and shelter capacity | Route closures, vehicle status, fuel, shelter capacity | Find routes, check resources, evaluate a plan | Rejects a fast-looking plan because its route is blocked or shelter is full |

### Independence requirements

Each agent must:
- Run as a separate logical actor with its own prompt, local state, inbox, and proposal history.
- Choose when to propose, challenge, disclose evidence, accept, or request escalation.
- Use tools to evaluate consequences instead of inventing outcome numbers.
- Have an objective that can conflict with another agent's objective.
- Receive peer messages and revise its own position.
- Never serve as a supervisor choosing the final plan for the others.

Separate operating-system processes are optional. Independent actor state and decision calls are required.

### What to show publicly

Show concise rationales, evidence IDs, tool results, proposals, and objections. Do not request or display hidden chain-of-thought. An explanation such as “Route R2 is closed; proposal P3 cannot reach Pine Ridge” is sufficient.

## 5. Synthetic demo world

Use a fictional region inspired by the forested geography around Santa Cruz, with a clear “Synthetic simulation” label. Fictional names avoid implying that the map or orders describe a real incident.

### Proposed map

| Location | Role | Why it matters |
| --- | --- | --- |
| Pine Ridge | Residential zone: 120 simulated people; 30 need assisted transport | Small community with high assistance demand |
| Valley Junction | Residential zone: 300 simulated people; 60 need assisted transport | Larger evacuation demand competing for vehicles |
| North Camp | Recreation zone: 40 simulated people; 20 need assisted transport | Remote access and limited routes |
| Shelter South | Shelter: capacity 350 | Main destination with limited space |
| Shelter East | Shelter: capacity 150 | Alternative destination reached by a longer road |
| Response Base | Starting location for crews and vehicles | Resource origin |
| West Forest | Initial fire cells | Fire begins here and threatens connected zones |

These numbers are demo parameters, not estimates of real communities.

### Proposed resource pool

- Three fire crews, each with one dedicated engine.
- Two evacuation buses, each with capacity 30.
- One multi-purpose transport vehicle, capacity 10 civilians **or** one crew transfer per trip.
- Two shelters.
- A small road graph with approximately 8-12 edges.
- A wind vector and bounded fire-intensity values.
- One simulation step represents two modeled minutes; a negotiation happens while the world is paused.

All methods get the same pause and decision horizon. Inference latency is reported separately.

### Force an actual shared-resource conflict

The shared transport vehicle can either carry people or move a crew. A road bottleneck also limits throughput. This creates a conflict beyond agents having different opinions.

A crew-opening-road action may make later bus trips possible, but delays an immediate containment action. Its benefit should be modeled as a simple, documented rule.

## 6. The main live demo

Target length: approximately 2-3 minutes, with a shorter 90-second version available.

| Beat | Trigger | What the judges see | What it proves |
| --- | --- | --- | --- |
| 1. Establish scarcity | Load scenario | Map, fire front, three communities, resources, objective cards | Understandable problem and different priorities |
| 2. Show disagreement | Start negotiation | Evacuation requests the shared vehicle; Fire Operations requests it too; Logistics identifies a route bottleneck | Genuine competing objectives |
| 3. Test alternatives | Agent tool calls | Proposal cards with predicted civilian exposure, fire extent, feasibility, and agent acceptance | Evidence-based deliberation |
| 4. Revise and agree | Peer counterproposal | A revised plan, explicit accepts, routes and assignments | Consensus emerged from the agents |
| 5. Execute in simulation | Advance time | Vehicles move, people reach shelters, resources become busy, fire state changes | Decisions affect the world |
| 6. Introduce new evidence | Click “Wind shift + road closure” | Changed fire direction, closed road, invalidated old plan | Adaptation under a repeatable disruption |
| 7. Renegotiate | Agents receive new event | New proposals cite the wind and closure; plan changes | Agents actually respond to evidence |
| 8. Show limits | Optional “Compound failure” preset | No consensus, exact objections, available fallback, human decision panel | The system does not force agreement |
| 9. Show evidence | Open comparison tab | Paired scenario results and limitations | Learning and baseline comparison |

### Example negotiation story

Illustrative dialogue only; actual live proposals must be generated by the agents.

1. Evacuation: “Pine Ridge needs assisted transport. Assign the shared vehicle there.”
2. Fire Operations: “That delays a crew transfer that could protect the road to both communities.”
3. Logistics: “The direct route is closed. Neither proposal has a valid arrival time yet.”
4. Evacuation requests the closure evidence and tests a revised bus route.
5. Fire Operations tests using one crew to restore a corridor instead of moving all crews west.
6. Logistics proposes a feasible schedule with separate loading and road-use windows.
7. Peers accept the same plan ID and state version, or retain named objections.

Do not hard-code this conversation. Tune the scenario to create the conflict; let agents choose how to resolve it.

### Compound-failure preset

Close the remaining short route and remove one bus. Configure the scenario so the initial acceptance targets cannot all be met within the decision horizon.

Show:
- A physically feasible partial response, if one exists.
- Which agent targets remain unmet.
- Why further negotiation is unlikely to resolve the shortage.
- A request for a human to prioritize among feasible alternatives.

A human can choose a trade-off or relax an aspiration target. An override cannot create a missing vehicle or allow movement across a closed road.

## 7. Negotiation protocol

### State and message flow

1. Simulator publishes state version and public evidence.
2. Each agent receives its local observations.
3. Agents independently produce a proposal or request evidence.
4. Peers validate and simulate the proposed allocation.
5. Each peer sends ACCEPT, CHALLENGE, COUNTERPROPOSE, or REQUEST_EVIDENCE.
6. Agents revise proposals with cited evidence.
7. A plan commits only when all three accept the same plan hash and state version.
8. After a bounded number of rounds or timeout, unresolved negotiation escalates.
9. New state evidence invalidates old acceptance; a new negotiation begins.

Proposed limits: three negotiation rounds and a configurable 20-30 second wall-clock budget. Measure and tune during the event.

### No central decision-maker

A message router may deliver messages, deduplicate them, apply timeouts, and record acceptances. A deterministic validator may check feasibility. Neither chooses the “best” proposal or optimizes a global score.

If multiple plans receive unanimous acceptance, commit the first fully accepted plan under a stable ordering rule, and record that rule. Agent acceptances, not a supervisor model, determine the outcome.

The simulator is authoritative about physics and resource constraints. Shared tool access is compatible with decentralized decision authority.

### Feasibility versus preferences

**Non-negotiable simulator constraints:**
- A resource cannot perform overlapping tasks.
- Vehicle and shelter capacities cannot be exceeded.
- A route must be open for the planned traversal.
- Travel and action durations must fit the plan schedule.
- Assigned resources must exist and be available.

**Agent acceptance targets:**
- Assisted evacuation below a target delay.
- Fire extent below a target level.
- Exposure or logistics risk below an agent's tolerated limit.

Targets are synthetic policy choices. Agents may revise explicitly permitted targets, with explanation. Hard physical constraints cannot be waived.

### Message contract

Every message includes:
- message_id, sender, recipient(s), message_type
- scenario_id, state_version, round, timestamp
- proposal_id and plan_hash when applicable
- evidence_ids
- concise public rationale
- structured objection or proposed amendment

Message types: PROPOSE, CHALLENGE, COUNTERPROPOSE, REQUEST_EVIDENCE, SHARE_EVIDENCE, ACCEPT, WITHDRAW, ESCALATE.

### Plan contract

A plan includes:
- plan_id, proposer, state_version
- ordered assignments: resource_id, task, origin, destination, route_ids, start_step, end_step
- expected resource and shelter usage
- referenced evidence IDs
- simulator evaluation ID
- trade-offs and unmet targets

Outcome estimates are attached by the simulator. Agent-authored numbers are not treated as simulation results.

## 8. Simulator and tools

Build a small deterministic graph-and-grid simulator. It should be reproducible, fast, and transparent. Real wildfire prediction is outside the MVP.

### Minimum world state

- Zones: population, assisted demand, people evacuated, hazard.
- Fire cells: fuel proxy, intensity, adjacent cells.
- Roads: endpoints, traversal time, capacity, open/closed status.
- Resources: type, position, capacity, availability, remaining task.
- Shelters: location, capacity, occupancy.
- Environment: wind, scenario seed, step, scheduled disruptions.
- Evidence: source agent, observation time, state version, confidence label.

### Simplified rules

- Fire spreads through adjacent cells according to documented wind and fuel rules.
- A crew action reduces the modeled intensity or spread probability in its target cells.
- Vehicle trips move a capacity-limited number of people along valid paths.
- Shared road capacity delays conflicting trips.
- Evidence events change routes, wind, or resource availability.
- All scenario randomness uses an explicit seed.

These are synthetic rules for comparing decisions. A reduced fire score or exposure score is not evidence of lives saved.

### Tools

| Tool | Output | Purpose |
| --- | --- | --- |
| get_local_observations(agent_id) | Role-specific evidence | Give agents incomplete information |
| request_peer_evidence(evidence_id) | Shared observation | Make communication necessary |
| find_routes(origin, destination) | Valid paths and timing | Ground transport planning |
| validate_plan(plan) | Valid/invalid and violation list | Enforce feasibility |
| evaluate_plan(plan, horizon, seed) | Predicted metrics and action trace | Test counterfactuals |
| submit_message(message) | Delivery receipt | Peer negotiation |
| get_negotiation_history() | Prior messages and versions | Support revision |
| apply_accepted_plan(plan_hash) | New state and event trace | Execute only a committed decision |

## 9. Dashboard: what we will show

Use one polished command-center screen with a clear visual hierarchy.

**Main map**
- Fire cells and directional wind indicator.
- Community population and assisted-transport demand.
- Roads, closures, shelters, crews, buses, shared vehicle.
- Routes and actions for the selected proposal.
- Distinct “predicted” and “executed” views.

**Agent cards**
- Objective, current proposal, latest evidence, acceptance status.
- A visible disagreement label and concise objection.
- Objective change after new information.

**Proposal comparison**
- Two or three candidate plans.
- Predicted metrics, feasibility violations, trade-offs.
- Which agents accept each candidate.

**Decision timeline**
- Observation -> proposal -> challenge -> tool evaluation -> revision -> consensus.
- Click an event to inspect evidence and structured output.

**Controls**
- Start, pause, step, reset.
- Wind shift + road closure.
- Compound failure.
- Run comparison.
- Human choice between feasible plans when escalated.

**Result panel**
- Real measurements from saved runs.
- Baseline comparison, latency, and unresolved cases.
- Clear live/replay and synthetic-simulation labels.

Suggested visual style: dark map, orange fire, blue evacuation, teal logistics, restrained motion. Prioritize legible evidence over decoration.

## 10. Technical architecture

Proposed stack:
- Frontend: React + TypeScript; SVG or canvas for the synthetic map.
- Backend: Python + FastAPI.
- Simulation: plain Python data models and deterministic step functions.
- Agents: three independent actor loops using a model API.
- Transport: backend event stream or WebSocket to the dashboard.
- Persistence: JSON/JSONL scenario inputs, event logs, run results, and replay traces.

These are implementation defaults, not verified dependency versions. Pin versions at build time.

### Components

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Simulator | Apply rules, validate and evaluate plans | Let an LLM invent physics |
| Agent actors | Propose, challenge, revise, accept | Delegate the final choice to a supervisor |
| Message router | Deliver and log peer messages | Rank or select plans |
| Commit gate | Verify unanimous acceptance and current state | Treat silence as approval |
| Dashboard | Render state, evidence, decisions, comparisons | Present a replay as live |
| Benchmark runner | Run paired methods and summarize outcomes | Change scenarios to favor one method |

### Suggested repository layout

~~~text
rescuemesh/
  README.md
  frontend/
  backend/
    app/
      api.py
      models.py
      simulator.py
      agents/
      negotiation/
      tools/
      benchmarks/
  scenarios/
  runs/
  docs/
    architecture.md
    demo-script.md
    results.md
~~~

### Suggested API surface

- POST /scenarios/{id}/reset
- GET /state
- POST /negotiate
- POST /events/inject
- POST /simulation/step
- GET /proposals
- GET /runs/{id}
- POST /benchmarks/run
- GET /events/stream

Keep API credentials on the backend. Run replay fixtures without model credentials for demo recovery.

## 11. MVP and scope discipline

### Required

- Three independent agents with competing objectives.
- One small forest-fire world.
- Shared-resource conflict.
- Structured peer negotiation with tool-grounded objections.
- Counterfactual evaluation of at least two proposals.
- Unanimous acceptance or explicit escalation.
- Wind/closure disruption that changes the plan.
- Map, agent cards, proposals, and timeline.
- At least one fixed-rule baseline and one single-agent baseline.
- Saved repeatable traces and honest result summary.

### Stretch, only after the full demo works

- Richer uncertainty and multiple forecast seeds.
- Capability-based collaborator discovery.
- Additional specialist agent.
- Real geographic background with clearly synthetic incident data.
- AGNTCY integration if the team can learn and use it without destabilizing the build.
- Second disaster domain to demonstrate portability.

### Out of scope

- Real emergency dispatch or evacuation orders.
- Live satellite ingestion.
- Operational fire-behavior forecasting.
- Production authentication and integrations.
- Large photorealistic 3D city.
- Six or more agents.
- A general autonomous-disaster platform.

## 12. Evidence and evaluation

The key question is: **Does negotiation improve useful outcomes enough to justify its complexity in this simulator?**

### Baselines

1. **Fixed-rule planner:** a disclosed deterministic priority policy, such as assisted evacuation first, nearest valid shelter, then crew containment.
2. **Single-agent planner:** one model with all shared evidence, the same action schema, and the same simulator tools.
3. **RescueMesh:** three actors with peer negotiation and progressively shared evidence.

Provide the fixed-rule planner the same revealed evidence. Give the single agent the union of evidence available to RescueMesh at each decision point. Do not manufacture an advantage by hiding information from a baseline.

### Metrics

| Metric | Definition | Desired direction |
| --- | --- | --- |
| Civilian exposure | Sum of people present in hazardous zones across simulation steps | Lower |
| Assisted evacuation completion | Fraction of assisted-demand people reaching shelter by horizon | Higher |
| Evacuation completion time | Steps to complete evacuation, or explicitly unfinished | Lower |
| Fire extent | Burning-cell count or accumulated burned-cell score | Lower |
| Feasibility violations | Invalid actions attempted and invalid actions executed, separately | Lower |
| Adaptation delay | Time from disruption to a new valid committed plan | Lower |
| Consensus rate | Fraction of decision points reaching unanimous acceptance | Context-dependent |
| Escalation quality | Whether an infeasible or unresolved case identifies the blocking constraint | Higher |
| Model cost and latency | Calls, token usage if available, wall-clock decision time | Report trade-off |

Consensus is not inherently good. Report inappropriate consensus and justified escalation separately.

### Experiment design

- Use four presets: normal scarcity, wind shift, road closure, compound failure.
- Run at least three seeds per preset if time permits: 12 paired scenario runs per method.
- Fix initial states, exogenous event timing, horizon, and seeds.
- Record model identity, prompts, tool access, token budget, and negotiation limits.
- Compare quality under a matched total model-call/token budget; also report the natural configuration if different.
- Report every preset, not only the run RescueMesh wins.
- Distinguish predictions from realized outcomes.
- If a baseline performs better, include that finding and explain the observed failure mode.

No benchmark numbers should appear in the pitch until runs exist.

### Evidence to keep

- Scenario files and seeds.
- Structured proposals and peer messages.
- Simulator evaluation traces.
- Accepted plan hashes and state versions.
- Baseline outputs.
- CSV/JSON metrics.
- At least one success, one recovery, and one escalation trace.

## 13. Track requirement mapping

Source: supplied “Track Challenges - UCSC AI Hackathon.pdf,” Cisco section, pages 1-2.

| Official requirement or criterion | RescueMesh demonstration |
| --- | --- |
| At least three autonomous agents with competing objectives | Evacuation, Fire Operations, Logistics |
| Deliberate, negotiate, try for consensus without a central decision-maker | Peer proposals, challenges, revisions, unanimous commit |
| Genuine disagreement | Shared vehicle and road bottleneck |
| Real negotiation mechanism | Structured messages and bounded rounds |
| Effect of new information | Wind shift and road closure invalidate old acceptance |
| Comparison against a simpler baseline | Fixed-rule and single-agent runs |
| Explain when to stop, retain disagreement, or ask a human | Timeout, unmet targets, impossible compound scenario |
| Functionality | Plans execute and change the simulated world |
| Innovation | Counterfactual negotiation and evidence-linked revision |
| Agent intelligence | Tool use, evidence exchange, autonomous objections |
| Engineering | Deterministic constraints, schemas, logs, replay |
| Demonstration | Short interactive scenario and visible outcomes |
| Learning and evidence | Paired results and candid failure analysis |

The PDF permits AGNTCY/coffeeAGNTCY or another framework; no particular framework, model, or platform is required. Do not claim to use sponsor infrastructure unless it is actually integrated.

Required submission items in the PDF:
- Working demonstration.
- Architecture overview.
- Technical implementation details.
- Results and lessons learned.

## 14. Why it could compete for Best Overall

- The problem is understandable immediately: limited resources, threatened communities, changing fire.
- The map connects AI decisions to visible consequences.
- Competing objectives produce a more interesting demo than agents simply dividing tasks.
- Tool-grounded negotiation makes the technical contribution inspectable.
- Escalation demonstrates judgment rather than forced success.
- Paired evidence provides something concrete beyond a polished story.

Risks to winning:
- Disaster coordination is already a challenge example.
- A visually impressive map cannot compensate for scripted agent behavior.
- A slow negotiation can undermine the live demo.
- Simplified simulation limits real-world claims.
- Multi-agent negotiation may not beat a well-designed single agent.

The strongest pitch is a working negotiation mechanism with honest measurements, not “AI firefighters save lives.”

## 15. Build sequence

Use dependency order, with approximate durations adjusted to team size and available time.

| Stage | Approximate effort | Completion gate |
| --- | --- | --- |
| 1. Lock scenario and schemas | 1-2 hours | Conflict and disruption specified |
| 2. Build deterministic simulator | 3-4 hours | Valid plans execute; invalid ones rejected |
| 3. Build fixed-rule baseline | 1-2 hours | Repeatable baseline trace |
| 4. Add one agent with tools | 2-3 hours | Valid structured proposal |
| 5. Add three actors and negotiation | 3-5 hours | Real challenge, revision, commit or escalation |
| 6. Wire minimal dashboard | 3-4 hours | Full scenario visible end to end |
| 7. Add disruption and replay | 2-3 hours | New evidence changes decisions |
| 8. Run comparisons and polish | 3-4 hours | Evidence and demo ready |

Tasks can overlap across team members, but integration gates must work before extra features are added. Total estimates are approximate and exclude setup surprises.

Suggested team ownership:
- Simulation and benchmark runner.
- Agent protocol and model tools.
- Frontend and visualization.
- Integration, evaluation, pitch, and submission.

For a smaller team, combine roles and reduce visuals before reducing the negotiation mechanism.

## 16. Acceptance checklist

- [ ] Agents hold separate objectives and local state.
- [ ] Initial proposals disagree over an actual constrained resource.
- [ ] At least one agent obtains evidence from another.
- [ ] Counterproposals change assignments or timing.
- [ ] Simulator checks all executed plans.
- [ ] Consensus requires matching plan hash and state version.
- [ ] New evidence invalidates stale decisions.
- [ ] Compound scenario preserves disagreement or escalates.
- [ ] Human intervention is labeled and logged.
- [ ] Baselines use paired conditions and disclosed budgets.
- [ ] Results include failures and costs.
- [ ] Reset and replay work.
- [ ] UI distinguishes predicted, executed, live, and replay states.
- [ ] README explains setup, architecture, limitations, and demo.
- [ ] Submission includes all four track deliverables.

Meaningful checks: double booking, closed-road routing, over-capacity shelter, stale consensus, unanimous commit, and paired reset reproducibility.

## 17. Demo resilience

- Save one complete trace of each preset.
- Provide a clearly labeled replay mode if model access fails.
- Keep the live world paused during deliberation.
- Bound negotiation and tool calls.
- Validate every structured response; give a bounded repair attempt.
- Log API errors and show escalation rather than fabricated acceptance.
- Make reset one click.
- Record a short backup demonstration if event submission supports video.

## 18. Pitch scripts

### 30-second pitch

“When a wildfire changes direction, evacuation teams, fire crews, and logistics teams all have reasonable priorities, but they are competing for the same limited resources. RescueMesh gives each one an independent AI agent. They test plans in a simulation, challenge each other with evidence, and negotiate a response. When the conditions change, they renegotiate. When no acceptable plan exists, they show exactly what a human needs to decide.”

### Demo narration

“Here are three communities and limited transport. The Evacuation Agent wants this vehicle to move people; Fire Operations wants it to move a crew. Logistics sees that their preferred route is blocked. Each proposal is tested, and the agents revise their plans using the results. Now they agree and the response begins. We change the wind and close a road: the agreement is invalid, so they must reconsider. In this final scenario, the shortage prevents agreement. The system explains the conflict and asks a human to choose among feasible options. Here is what happened against our two simpler baselines.”

Replace the final comparison with actual findings after measurement.

### Closing line

“RescueMesh makes disagreement useful: agents must support their plans with evidence, adapt when that evidence changes, and expose the trade-offs they cannot resolve.”

## 19. Open decisions before implementation

1. Team size and responsibilities.
2. Model provider, available credits, and latency.
3. Whether AGNTCY integration is practical during the event.
4. Final synthetic scenario parameters and acceptance targets.
5. Negotiation timeout and total inference budget.
6. Actual presentation time and submission format.
7. Best Overall rubric, if organizers publish one.

Proceed with the defaults above until an answer changes a concrete implementation choice.

## 20. Sources and claim boundaries

### Authoritative event source

“Track Challenges - UCSC AI Hackathon.pdf,” supplied by the user:
- Page 1: Cisco challenge, levels, Level 3 requirements and success conditions.
- Page 2: remaining judging criteria, required submission items, framework guidance, resources and track prizes.

Only this supplied challenge overview was inspected. Linked full challenge statements and external documentation were not independently reviewed for this brief.

### Resources listed by the challenge

- https://github.com/agntcy/coffeeAgntcy
- https://github.com/agntcy/coffeeAgntcy/blob/main/TUTORIAL.md
- https://docs.agntcy.org/coffee-agntcy/get-started
- https://github.com/agntcy/app-sdk
- https://github.com/agntcy
- https://outshift.cisco.com/internet-of-cognition

### Claim boundaries

- Forest-fire rules, populations, capacities, and agent policies are synthetic project design choices.
- Better simulated outcomes do not establish operational emergency-response effectiveness.
- No measured advantage exists until the benchmark is run.
- No evidence establishes that this is the most likely project to win overall.
- Broader disaster applications are future possibilities, not shipped capabilities.

