# Handoff: backend/rohaan-c6-real-methods

| Field | Value |
|---|---|
| Branch | `backend/rohaan-c6-real-methods` |
| Owner | rohaan (covering Tisha's C6 dispatch; team-approved) |
| Workstream / queue item | backend / C6 real benchmark methods |
| PRD sections | §11.2, §11.3, §10.5, AGENTS.md invariant 9 |

## Current state
**Status:** ready for PR. **Stacked on #25 (B6) and #26 (fixed-rule)**; merge those first.

**Done:**
- `app/bench/methods.py`:
  - `run_fixed_rule()` really runs the §11.2 policy on `SimulatorService`, with decision points at step 0 and after every event pause. It counts DPs, commits and invalid plans; metrics are `realized_metrics()` at the horizon.
  - `run_model_method()` runs `single_agent` (SingleAgentBaseline) or `rescuemesh` (NegotiationService, benchmark mode → F0) against a **live** provider only.
- `app/bench/runner.py`:
  - real dispatch per method
  - a method that can't run honestly (no live provider, TEST PROVIDER only, unknown or non-simulator preset) is **skipped and recorded** in the benchmark status `skipped` list; **no stub row is ever written**
  - the default presets are the four PRD presets (§11.3)
  - `cost_usd_estimate=None` (§10.5)
- `app/bench/report.py`: the markdown header says STUB only when rows are stubs.
- `tests/test_bench.py` updated: fixed_rule produces real rows (`invalid_executed == 0`), model methods are skipped without a provider. Backend: **261 passed**.

**Not done / next:**
- `inappropriate_consensus` / `justified_escalations` are still 0 (they need per-DP candidate scans; §11.1).
- Expose `skipped` in `GET /benchmarks/{id}` (`main.py`; left alone because Tisha's #21/#22 edit it).
- Live runs need a key in `backend/.env` (`RESCUEMESH_PROVIDER`, `RESCUEMESH_MODEL`, provider API key).
