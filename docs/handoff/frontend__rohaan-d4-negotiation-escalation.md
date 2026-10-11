# Handoff: frontend/rohaan-d4-negotiation-escalation

| Field | Value |
|---|---|
| Branch | `frontend/rohaan-d4-negotiation-escalation` |
| Owner | rohaan |
| Workstream / queue item | frontend / D4 |
| PRD sections | §8.2, §9.4, §9.7, FR-051, invariant 8 |
| Created | 2026-10-10T10:30Z |

## Goal

Drive negotiation from the UI (start, cancel, disruptions), show live agent status and rounds, and let a human resolve an escalation by choosing only among the package's candidates or F0.

## Current state  (REWRITE this whole section at every handoff)

**Status:** ready for PR (stacked on D3, PR #18)

**Done:**
- `src/api.ts`: `negotiate`, `cancel`, `inject` (guarded by the negotiation session's version), `resolve` (candidate | fallback).
- `src/incident.ts`:
  - real `agent.turn` statuses from WS-B (`submitted / silent / degraded / failed / late / cancelled`, plus a local `working`)
  - `round` and `negotiationVersion` tracking
  - HUMAN DECISION / auto-fallback commit lines; `human.decision`, `target.revised` and `negotiation.cancelled` lines
- `src/components/EscalationPanel.tsx` (§9.7):
  - trigger, blocking constraints, unmet targets
  - only `EscalationPackage.candidates` plus F0, each with a choose button
  - the "cannot add vehicles or open closed roads" line
  - disabled in preview and replay
- `src/App.tsx`:
  - Start negotiation / Cancel, Wind shift + road closure, Compound failure
  - "Round n of 4"
  - notices for MODEL_UNAVAILABLE, NEGOTIATION_IN_PROGRESS, PLAN_INFEASIBLE and NO_ACTIVE_ESCALATION
  - 409 → refresh, no automatic retry
  - all commands disabled in replay (§9.4)
- Header shows TEST PROVIDER when agents respond while `/health` reports no model.
- **Bug fix (`src/stream.ts`):** the browser's own data-less `error` Event on every stream close was parsed as an envelope and showed "Invalid event received". It now ignores events without data, with a regression test.
- Tests: `e2e/negotiation.spec.ts` (5) + incident and smoke additions. 27 pass.

**In progress:** nothing.

**Next steps (ordered, concrete):**
1. After #18 merges: rebase onto main, open the D4 PR.
2. Relax-targets control in the escalation panel once Snapshot carries agent targets (asked Tisha).
3. Predicted/executed toggle once Madhav's map (#5) is mounted.
4. D5: replay controls (`POST /replay/{run_id}`, `GET /runs`), compact original vs revised comparison.

**Decisions and why:**
- TEST PROVIDER label inferred: C4 runs the labeled test provider, and `/health` always says `model_available: false`. Invariant 8 requires the label. This is better reported by `/health` itself (asked Tisha).
- The inject version comes from the latest negotiation envelope, because `/state`'s version is a different counter (documented in backend `main.py`).

**Gotchas / traps:**
- Mocked routes only; not run against a live backend (no `uv` here).

**How to verify:**
```bash
cd frontend && npm run build && npm run lint && npx playwright test   # 27 pass
```

**Asks for other owners (file, owner, what, why):**
- `/health`, Tisha: report the TEST PROVIDER (e.g. `provider: "test"`) when negotiation runs on it, so the UI label doesn't have to infer it (invariant 8).

**Open questions (with the PRD's provisional answer if any):**
- None new.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T10:30Z · claude-code · rohaanvikram
**Status:** D4 negotiation + escalation panel done; 27 tests
```text
HEAD 7a45d3e · behind origin/main: 0
-- commits on branch --
7a45d3e feat(frontend): D3 backend reset/step, reconnect and snapshot reconciliation
-- uncommitted --
 M frontend/e2e/backend.spec.ts
 M frontend/e2e/incident.spec.ts
 M frontend/e2e/smoke.spec.ts
 M frontend/src/App.css
 M frontend/src/App.tsx
 M frontend/src/api.ts
 M frontend/src/fixtures/preview.ts
 M frontend/src/incident.ts
 M frontend/src/stream.ts
?? docs/handoff/frontend__rohaan-d4-negotiation-escalation.md
?? frontend/e2e/negotiation.spec.ts
?? frontend/src/components/EscalationPanel.tsx
-- diffstat vs main --
 .../handoff/frontend__rohaan-d3-reconnect-reset.md |  91 ++++++
 frontend/e2e/backend.spec.ts                       |  95 +++++++
 frontend/e2e/incident.spec.ts                      |  22 ++
 frontend/e2e/smoke.spec.ts                         |  30 +-
 frontend/playwright.config.ts                      |   6 +-
 frontend/src/App.css                               |  88 ++++++
 frontend/src/App.tsx                               | 315 +++++++++++++++++----
 frontend/src/api.ts                                |  93 +++++-
 frontend/src/fixtures/preview.ts                   |   4 +-
 frontend/src/incident.ts                           |  87 +++++-
 frontend/src/stream.ts                             |  24 +-
 11 files changed, 771 insertions(+), 84 deletions(-)
```
