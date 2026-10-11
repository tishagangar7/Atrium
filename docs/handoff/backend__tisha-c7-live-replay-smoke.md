# Handoff: backend/tisha-c7-live-replay-smoke

| Branch | `backend/tisha-c7-live-replay-smoke` |
| Workstream / queue item | Backend / C7 integration smoke |
| PRD sections | §8.2–§8.5, §11.5, §12.3; AC-012 |

## Current state

**Status:** One end-to-end transport check added and verified. This branch is stacked on Tisha's draft #22, which is stacked on #21. No live provider credentials were used; negotiation used the labeled TEST PROVIDER.

- `backend/tests/test_shared_world.py::test_ac012_full_commit_disruption_replay_preserves_final_world` resets a real `normal` preset, negotiates a unanimous commit, executes three simulator steps, injects a road closure, starts replay, and checks the replay world matches the recorded authoritative world except for the replay run ID. It also checks replay envelopes include the commit and event with `mode: replay`.
- `scripts/check.sh` passed: 256 backend tests, frontend typecheck/build, secret scan.

## Next steps

1. Review and merge #21, then #22, then this branch's PR after the required review.
2. Run a separate live-provider success/recovery/escalation rehearsal when credentials are available; save and inspect recordings. Do not treat TEST PROVIDER output as a live result.
3. After the frontend map and dashboard PRs land, perform the browser-level D7 smoke path against this backend.

## Gotchas

- The test verifies replayed state and event identity, not real model decisions or a browser rendering.
- No benchmark comparison is claimed until a complete `runs/results.csv` exists.

## Asks for other owners

- Rohaan: perform D7 browser smoke once his map/controls/results view is integrated.

### 2026-10-10T18:48Z · codex · Tisha Gangar
**Status:** C7 reset-commit-disruption-replay smoke passes; full check passed
```text
HEAD 01da992 · behind origin/main: 1
-- commits on branch --
01da992 feat(backend): share authoritative simulator with negotiation
a159977 feat(backend): connect real simulator reset and step transport
-- uncommitted --
 M backend/tests/test_shared_world.py
?? docs/handoff/backend__tisha-c7-live-replay-smoke.md
-- diffstat vs main --
 backend/app/main.py                                | 150 +++++++++++++++++----
 backend/app/negotiation_session.py                 |  61 ++++++++-
 backend/app/run.py                                 | 131 +++++++++++++-----
 backend/tests/test_health.py                       |  16 +++
 backend/tests/test_run_simulator_integration.py    |  88 ++++++++++++
 backend/tests/test_shared_world.py                 | 139 +++++++++++++++++++
 docs/handoff/backend__tisha-c4-shared-world.md     |  55 ++++++++
 .../backend__tisha-c7-simulator-integration.md     |  81 +++++++++++
 8 files changed, 662 insertions(+), 59 deletions(-)
```
