# Handoff: frontend/rohaan-d3-reconnect-reset

| Field | Value |
|---|---|
| Branch | `frontend/rohaan-d3-reconnect-reset` |
| Owner | rohaan |
| Workstream / queue item | frontend / D3 (non-map part) |
| PRD sections | §8.1, §8.2, §8.4, §12.3 D3 |
| Created | 2026-10-10T09:32Z |

## Goal

Drive Tisha's real backend from the UI (reset, step) and keep the screen consistent across resets, reconnects and version conflicts. The map mount is left for after Madhav's PR #5 merges (owner's call).

## Current state  (REWRITE this whole section at every handoff)

**Status:** ready for PR (stacked on D2, which is stacked on D1 / PR #10)

**Done:**
- `src/api.ts`: `ApiError.code` from the backend `{error:{code}}` body; `isStale()` for 409 STATE_VERSION_MISMATCH / RUN_MISMATCH; `reset()` returns the snapshot; new `step()` sends `run_id`, `expected_state_version`, `steps`, `request_id`.
- `src/App.tsx`, backend mode:
  - "Reset scenario" and "Step" buttons; the preset picker is enabled in both modes
  - `follow(snapshot)` adopts a snapshot and streams from its `last_seq`; used by connect, reset, resync and conflict refresh
  - a step conflict refetches `/state` and shows "changed elsewhere – refreshed"
  - Step is disabled while negotiating
  - "Start negotiation" stays disabled ("unlocks when the agents are connected"; `/negotiate` is not on main)
  - mount-point comment for `IncidentViewer` in the incident area
- `src/stream.ts`: the backend closes the SSE stream after each batch; "Reconnecting…" only shows if reconnecting takes over 4 s.
- `playwright.config.ts`: tests run on port 5174 so a normal `npm run dev` on 5173 no longer breaks them.
- `e2e/backend.spec.ts`: reset, step payload, 409 refresh (mocked routes). 20 tests pass.

**In progress:** nothing.

**Next steps (ordered, concrete):**
1. When Madhav's PR #5 is on main: mount `IncidentViewer({snapshot: world, selectedPlan, evaluation, mode})` where the comment is; mount `EnvironmentalControls` and forward `onCommand` (needs a backend endpoint for those commands; ask Tisha).
2. Rebase this stack onto main after #10 merges; open the D2 and D3 PRs in order.
3. D4: wire Start negotiation when `/negotiate` lands (Tisha C4 + Ali B4).

**Decisions and why:**
- After a reset, the response snapshot becomes the base state, and stream envelopes at or below its `last_seq` are skipped (§8.4).
- The fixture preview flow is unchanged and still labeled FIXTURE.

**Gotchas / traps:**
- Not tested against a real backend: `uv` is missing on this laptop, so the backend can't run here. Backend paths are covered by mocked-route tests only.
- `POST /simulation/step` with `until` returns 422 on main (not implemented), so the UI only sends `steps`.

**How to verify:**
```bash
cd frontend && npm run build && npm run lint && npx playwright test
# with Tisha's backend on :8000 → npm run dev → Connect simulator → Reset scenario → Step
```

**Asks for other owners (file, owner, what, why):**
- Backend endpoint for Madhav's `EnvironmentalControls` commands (`set_wind`, `set_road_status`, `set_resource_available`, `inject_preset`), Tisha: PRD §8.2 only has `POST /events/inject` with preset names. Needed to forward `onCommand`.

**Open questions (with the PRD's provisional answer if any):**
- None new.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T09:32Z · claude-code · rohaanvikram
**Status:** D3 non-map: reset/step/reconnect done; map waits for PR #5
```text
HEAD ed12d7f · behind origin/main: 0
-- commits on branch --
ed12d7f feat(frontend): D2 agent status, proposals, resources and readable activity
cef5730 feat(frontend): D1 command-center shell, API client and SSE stream
-- uncommitted --
 M frontend/playwright.config.ts
 M frontend/src/App.tsx
 M frontend/src/api.ts
 M frontend/src/stream.ts
?? docs/handoff/frontend__rohaan-d3-reconnect-reset.md
?? frontend/e2e/backend.spec.ts
-- diffstat vs main --
 frontend/src/assets/react.svg                      |    1 +
 frontend/src/assets/vite.svg                       |    1 +
 frontend/src/components/Icon.tsx                   |   82 ++
 frontend/src/components/Inspector.tsx              |   47 +
 frontend/src/components/shell-data.ts              |  113 ++
 frontend/src/fixtures/preview.ts                   |  269 ++++
 frontend/src/incident.ts                           |  319 +++++
 frontend/src/index.css                             |   88 ++
 frontend/src/main.tsx                              |   10 +
 frontend/src/stream.ts                             |  130 ++
 frontend/tsconfig.app.json                         |   26 +
 frontend/tsconfig.json                             |    7 +
 frontend/tsconfig.node.json                        |   23 +
 frontend/vite.config.ts                            |   17 +
 34 files changed, 5493 insertions(+)
```
