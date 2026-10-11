# Handoff: frontend/rohaan-d2-panels-timeline

| Field | Value |
|---|---|
| Branch | `frontend/rohaan-d2-panels-timeline` |
| Owner | rohaan |
| Workstream / queue item | frontend / D2 |
| PRD sections | §9.3, §9.4, §12.3 D2; invariants 3 and 6 |
| Created | 2026-10-10T09:18Z |

## Goal

Fill D1's agent sidebar and Activity / Proposals / Resources tabs from stream data, uncluttered, on labeled fixtures. Done when both fixture flows render and `npx playwright test` passes.

## Current state  (REWRITE this whole section at every handoff)

**Status:** ready for PR (stacked on D1, PR #10; rebase onto main after #10 merges)

**Done:**
- `src/incident.ts`: pure display model built from accepted envelopes: plans, evaluations, messages, commits, agent turns, stale flag, escalation. Helpers: `acceptances` (only at the plan's own state_version), `authoritativeEval` (basis "authoritative" only), `agentStatus`, `describe` (readable Activity lines). Partial data is ignored rather than crashing the page.
- `src/fixtures/preview.ts`: FIXTURE flows built on `src/types.ts`. `normalFlow` (V1 conflict, Logistics shares E-LOG-01, P3 committed) and `disruptionFlow` (+ R3 closure, dp-2, FIRE degraded, escalation). Metric numbers are placeholders.
- `src/api.ts`: `previewApi.reset` returns the flow for the chosen preset (normal → normal, the others → disruption). `App.tsx` plays it back at 220 ms per event.
- `App.tsx` / `App.css`:
  - status line under each agent name (Accepts P3 / Objects to P1 / Thinking… / Unavailable – not counted), with the latest rationale and suggestion when expanded
  - stale and escalation banner
  - Proposals rows: state, 3 acceptance dots, Assisted %, fire extent, violations; click opens the Inspector
  - Resources: vehicles and crews with fuel bars, shelter occupancy, assisted residents waiting
  - Activity shows readable decisions, newest first
- Tests: new `e2e/incident.spec.ts` (6) and a D2 smoke test; updated D1 tests for the readable Activity text. 17 pass.

**In progress:** nothing.

**Next steps (ordered, concrete):**
1. After PR #10 merges: `git fetch && git rebase origin/main`, then open the D2 PR.
2. D3: snapshot reconciliation and reconnect/reset UI; mount Madhav's `IncidentViewer` in the incident area.
3. D4: wire Start negotiation / Step / inject to Tisha's endpoints when C4 lands; escalation panel with human choices.

**Decisions and why:**
- Activity hides bookkeeping envelopes (agent.turn, evaluation.created, plan.state, state.snapshot); they are still in "View event" data and the Inspector.
- Plans from an older decision point show their full id (dp-1:P3) so labels never collide.
- Status text is derived for display only; commit authority stays with the server (invariant 2).

**Gotchas / traps:**
- Playwright reuses any server already on port 5173 (`reuseExistingServer`). If a normal `npm run dev` is running, the connection tests fail with "Failed to fetch". Stop it before running tests.
- `uv` is still missing on this laptop, so `scripts/check.sh` stops at the backend tests.

**How to verify:**
```bash
cd frontend && npm run build && npm run lint && npx playwright test   # stop any dev server first
npm run dev   # pick "Compound failure", click Load preview
```

**Asks for other owners (file, owner, what, why):**
- Same as D1 (already emailed): Madhav `IncidentViewer`; Tisha agent targets in Snapshot; Tisha/Ali `agent.turn` status values.

**Open questions (with the PRD's provisional answer if any):**
- `agent.turn` statuses assumed thinking / done / silent / degraded.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T09:18Z · claude-code · rohaanvikram
**Status:** D2 panels done on fixtures; 17 tests pass
```text
HEAD cef5730 · behind origin/main: 0
-- commits on branch --
cef5730 feat(frontend): D1 command-center shell, API client and SSE stream
-- uncommitted --
 M frontend/e2e/resync.spec.ts
 M frontend/e2e/smoke.spec.ts
 M frontend/src/App.css
 M frontend/src/App.tsx
 M frontend/src/api.ts
?? docs/handoff/frontend__rohaan-d2-panels-timeline.md
?? frontend/e2e/incident.spec.ts
?? frontend/src/fixtures/
?? frontend/src/incident.ts
-- diffstat vs main --
 frontend/src/api.ts                          |   97 ++
 frontend/src/assets/hero.png                 |  Bin 0 -> 13057 bytes
 frontend/src/assets/react.svg                |    1 +
 frontend/src/assets/vite.svg                 |    1 +
 frontend/src/components/Icon.tsx             |   82 ++
 frontend/src/components/Inspector.tsx        |   47 +
 frontend/src/components/shell-data.ts        |  113 +++
 frontend/src/index.css                       |   88 ++
 frontend/src/main.tsx                        |   10 +
 frontend/src/stream.ts                       |  115 +++
 frontend/tsconfig.app.json                   |   26 +
 frontend/tsconfig.json                       |    7 +
 frontend/tsconfig.node.json                  |   23 +
 frontend/vite.config.ts                      |   17 +
 30 files changed, 4588 insertions(+)
```
