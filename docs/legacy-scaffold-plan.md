# RescueMesh UCSC Simulation Plan

## Goal

Build a hackathon-ready simulation slice for RescueMesh using UCSC campus as the concrete Santa Cruz redwood-interface example. The map is a real-place-inspired command surface, but all incident data, populations, resources, routes, fire behavior, and metrics are synthetic.

## Scenario

- Incident: redwood-edge wildfire starts in upper campus forest cells and moves east under moderate wind.
- Initial conflict: Evacuation wants the shared van for assisted residents at Crown/Merrill, while Fire Ops wants the same van to move a hand crew onto the redwood edge.
- Logistics objection: the shared van is double-booked and a narrow fire road is clearable, not immediately open.
- Consensus: stagger the van, split buses across shelters, and keep one crew on the western edge.
- Disruption: wind shifts southeast and Crown/Merrill Hill closes, voiding state v1 acceptances.
- Recovery: reroute via Science Hill, East Field, and Lower Campus shelter while Fire Ops holds the flank.
- Escalation: compound failure removes Bus B and closes another corridor, leaving feasible plans that miss different floors.

## UI Surface

- Full-screen command map with synthetic fire cells, UCSC-labeled nodes, constrained roads, resources, and accepted/revised plan overlays.
- Agent cards for Evacuation, Fire Ops, and Logistics.
- Proposal comparison cards with forecast exposure, fire extent, logistics risk, feasibility, and acceptance count.
- Message timeline with structured message types and evidence IDs.
- Controls for reset, negotiation, consensus, execution, wind plus closure disruption, renegotiation, and compound failure.

## Implementation Notes

- Frontend only for this branch: React, TypeScript, Vite, SVG map.
- No external basemap dependency so the demo can run offline after install.
- No real emergency guidance. Metrics are simulator-facing demo numbers only.
- Campus anchors are based on UCSC public map references, including the central campus, residential colleges, forested lands, and printable campus maps:
  - https://maps.ucsc.edu/home/
  - https://maps.ucsc.edu/printable-maps/
