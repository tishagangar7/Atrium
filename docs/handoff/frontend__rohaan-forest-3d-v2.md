# Handoff: frontend/rohaan-forest-3d-v2

| Field | Value |
|---|---|
| Branch | `frontend/rohaan-forest-3d-v2` |
| Owner | rohaan |
| Workstream / queue item | frontend (WS-D) / 3D hero |
| PRD sections | §9.1, §12.2 |

## Current state

**Status:** ready for review.

**Done:** WS-A's full Three.js forest app is the dashboard hero, isolated in its own page (`frontend/forest.html`, `src/forest-main.tsx`) and embedded via an iframe in `App.tsx`. Vite builds both pages. Rebased onto main after #38 (map mount) superseded #24.

**Next steps:** drive the 3D view from the backend world instead of WS-A's own physics (plan: `toForestSnapshot` adapter, WS-D only).

**Gotchas:** the hero shows WS-A's own simulation numbers; it is labeled as the illustrative 3D view, not the authoritative metrics (invariant 3).

**How to verify:** `cd frontend && npm run build && npx playwright test` (31 pass).

**Asks for other owners:** none.
