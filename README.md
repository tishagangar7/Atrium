# RescueMesh

Three independent AI agents (Evacuation, Fire Operations, Logistics) negotiate a wildfire
response inside a synthetic deterministic simulator. See `AGENTS.md` for team rules and
`docs/RescueMesh_Technical_PRD.md` for the full spec.

## Backend (WS-C)

Requires Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync                                        # install deps, create backend/.venv
cp .env.example .env                           # fill in locally; never commit .env
uv run uvicorn app.main:app --reload --port 8000
uv run pytest -q
```

Regenerate `frontend/src/types.ts` from `backend/app/models.py` after any contract change
(the file is generated and never hand-edited):

```bash
cd backend
uv run python scripts/gen_types.py
```

Live endpoints: `GET /health`, `POST /scenarios/{id}/reset`, `GET /state`,
`POST /simulation/step`, `GET /events/stream` (SSE) and `GET /events` (polling fallback),
`POST /replay/{run_id}` and `GET /runs*` (replay/history), `POST /negotiate` and the rest of
the negotiation endpoints (real three-actor negotiation under the labeled TEST PROVIDER --
no live model credentials exist yet, PRD OPEN-05), and `POST /benchmarks/run` (headless
batch runner; every method currently runs an identical stub loop until real baselines land).

## Frontend (WS-D)

```bash
cd frontend
npm ci
npm run dev
```

See [`frontend/README.md`](frontend/README.md) for the command-center shell's own details
(fixture vs. live mode, `VITE_API_BASE`, keyboard navigation).

## Simulation (WS-A)

Two parts, kept separate and never numerically mixed:

- **The authoritative PRD simulator** (`backend/app/sim/**`, consumed by the backend above)
  -- the real engine (A1-A3, taken over from Madhav by team decision and built by Ali):
  deterministic fire/resource step engine, validator, cloned evaluation, belief views,
  metrics. Scenario data lives in [`scenarios/`](scenarios/README.md), tuneable without
  touching code; see [`scenarios/CHANGELOG.md`](scenarios/CHANGELOG.md) for tuning history.
- **The standalone browser demo**, run via `cd frontend && npm ci && npm run dev` --
  a self-contained 3D wildfire visualization (`ucsc-visual-v1`, served at `frontend/forest.html` and embedded in
  the command center) plus the PRD incident scene (`IncidentViewer`) built ahead of the real backend, reading its
  own fixture copies of the PRD scenario data under `scenarios/ucsc-demo/` (renamed there
  once the real `scenarios/*.json` above claimed those filenames). **Not connected to the
  live backend or agents** (tests: `cd frontend && npm run test:sim`) -- no negotiation, dispatch outcome or benchmark result here is
  real. See [`frontend/src/simulation/README.md`](frontend/src/simulation/README.md) for
  how to run it and [`docs/simulation-integration.md`](docs/simulation-integration.md) for
  the A→D contract (`IncidentViewer`, `EnvironmentalControls`) it implements ahead of real
  wiring into the command-center shell above.
