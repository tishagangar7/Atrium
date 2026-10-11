# Handoff: contracts/tisha-current-snapshot-targets

| Branch | `contracts/tisha-current-snapshot-targets` |
| Workstream / queue item | Contract follow-up to Rohaan's #35 |
| PRD sections | §6.1, §6.11, §7.8, §8.5, §9.3, §9.7 |

## Current state

**Status:** Ready for stacked PR on #35; the full gate passes.

- #35 adds `Snapshot.targets` with a `Target[]` per EVAC/FIRE/LOG and `None` for non-PRD fixtures. That field shape matches the public targets contract. Its implementation reads initial scenario targets on every snapshot, so it loses logged `target.revised` aspirations and returns `null` after replay.
- `backend/app/run.py` now stores an independent current target set, applies validated public revisions, records it in snapshots, and restores it from the last saved snapshot on replay.
- `backend/app/main.py` updates and republishes the snapshot when `target.revised` is emitted.
- `backend/tests/test_controls_targets.py` checks a revision survives snapshot/replay without mutating initial scenario targets.
- The preview fixture now explicitly sets `targets: null`, consistent with its synthetic demo data rather than inventing target values.
- `scripts/check.sh`: 265 backend tests passed, frontend typecheck and build passed.

## Next steps

1. Open a stacked `[contract]` PR against #35 for both producer and consumer owners to review.
2. After #35 is merged, rebase this branch onto main and rerun `scripts/check.sh`.
3. Reconcile the WS-A EnvironmentalControls UI's `CALM` option with #35's endpoint, which rejects calm wind because the PRD simulator models speed classes 1–3.

## Gotchas

- This branch changes the frontend preview fixture to satisfy the new contract; the user explicitly authorized cross-workstream completion.

## Asks for other owners

- Rohaan / WS-D: review the preview fixture change and reconcile the controls' calm option with the simulator contract.

### 2026-10-10T23:44Z · codex · Tisha Gangar
**Status:** Snapshot targets revision/replay fixed in backend; #35 preview fixture blocks full gate
```text
HEAD 629ce80 · behind origin/main: 1
-- commits on branch --
629ce80 feat(contracts): Snapshot.targets, environment controls endpoint, unique run ids
01da992 feat(backend): share authoritative simulator with negotiation
a159977 feat(backend): connect real simulator reset and step transport
-- uncommitted --
 M backend/app/main.py
 M backend/app/run.py
 M backend/tests/test_controls_targets.py
?? docs/handoff/contracts__tisha-current-snapshot-targets.md
-- diffstat vs main --
 backend/app/main.py                                | 238 ++++++++++++++++++---
 backend/app/models.py                              |   3 +
 backend/app/negotiation_session.py                 |  61 +++++-
 backend/app/run.py                                 | 162 +++++++++++---
 backend/tests/test_controls_targets.py             | 107 +++++++++
 backend/tests/test_health.py                       |  16 ++
 backend/tests/test_run_simulator_integration.py    |  88 ++++++++
 backend/tests/test_shared_world.py                 | 107 +++++++++
 docs/handoff/backend__tisha-c4-shared-world.md     |  55 +++++
 .../backend__tisha-c7-simulator-integration.md     |  81 +++++++
 .../contracts__rohaan-snapshot-targets-controls.md |  23 ++
 frontend/src/types.ts                              |   1 +
 12 files changed, 882 insertions(+), 60 deletions(-)
```

### 2026-10-11T00:06Z · codex · Tisha Gangar
**Status:** Snapshot target revisions and preview fixture pass the full 265-test gate
```text
HEAD ff3937c · behind origin/main: 1
-- commits on branch --
ff3937c wip(contracts): preserve current targets through revisions and replay
629ce80 feat(contracts): Snapshot.targets, environment controls endpoint, unique run ids
01da992 feat(backend): share authoritative simulator with negotiation
a159977 feat(backend): connect real simulator reset and step transport
-- uncommitted --
 M docs/handoff/contracts__tisha-current-snapshot-targets.md
 M frontend/src/fixtures/preview.ts
-- diffstat vs main --
 backend/app/main.py                                | 238 ++++++++++++++++++---
 backend/app/models.py                              |   3 +
 backend/app/negotiation_session.py                 |  61 +++++-
 backend/app/run.py                                 | 162 +++++++++++---
 backend/tests/test_controls_targets.py             | 107 +++++++++
 backend/tests/test_health.py                       |  16 ++
 backend/tests/test_run_simulator_integration.py    |  88 ++++++++
 backend/tests/test_shared_world.py                 | 107 +++++++++
 docs/handoff/backend__tisha-c4-shared-world.md     |  55 +++++
 .../backend__tisha-c7-simulator-integration.md     |  81 +++++++
 .../contracts__rohaan-snapshot-targets-controls.md |  23 ++
 .../contracts__tisha-current-snapshot-targets.md   |  73 +++++++
 frontend/src/fixtures/preview.ts                   |   1 +
 frontend/src/types.ts                              |   1 +
 14 files changed, 956 insertions(+), 60 deletions(-)
```
