# Handoff: frontend/rohaan-d5-replay-compare

| Field | Value |
|---|---|
| Branch | `frontend/rohaan-d5-replay-compare` |
| Owner | rohaan |
| Workstream / queue item | frontend / D5 |
| PRD sections | §8.2, §9.4 Replay, §13.3, §12.3 D5 |
| Created | 2026-10-10T10:37Z |

## Goal

Play back saved runs, clearly labeled REPLAY, and show a compact before/after comparison of the committed plans around a disruption. The human-choice UI shipped in D4.

## Current state  (REWRITE this whole section at every handoff)

**Status:** ready for PR (stacked on D4, PR #19)

**Done:**
- `src/api.ts`: `runs()` (excludes `replay-of-*`, newest first) and `replay(runId, speed)`.
- `src/App.tsx`:
  - "Replay a run" picker + speed (1×/2×/4×) + Play in the control bar (backend mode)
  - playing a replay subscribes from seq 0, since the snapshot's `last_seq` is the end of the recording
  - header shows REPLAY plus "▶ preset · recorded <date>"; diagonal REPLAY watermark on the incident area
  - all commands except Reset disabled, including Cancel (that was a bug)
  - preset description hidden in backend mode to keep the bar uncluttered
- `src/incident.ts`: `comparison()` returns the commit before the latest `event.applied` and the first commit after it, each with its authoritative evaluation. The Proposals tab shows them side by side. No metric math.
- Tests: `e2e/replay.spec.ts` + a comparison unit test. 29 pass.

**In progress:** nothing.

**Next steps (ordered, concrete):**
1. After #19 merges: rebase onto main, open the D5 PR.
2. D6: results view from `GET /benchmarks/{id}` / `runs/results.csv`; accessibility and responsive pass.
3. Mount Madhav's map (#5) when it lands; then the predicted/executed toggle.

**Decisions and why:**
- Replay starts with no base snapshot, so recorded `state.snapshot` envelopes rebuild the screen in order.

**Gotchas / traps:**
- Mocked routes only; not run against a live backend (no `uv` here).

**How to verify:**
```bash
cd frontend && npm run build && npm run lint && npx playwright test   # 29 pass
```

**Asks for other owners (file, owner, what, why):**
- None new.

**Open questions (with the PRD's provisional answer if any):**
- None.

## Session log  (append-only; `scripts/handoff.sh` adds entries)

### 2026-10-10T10:37Z · claude-code · rohaanvikram
**Status:** D5 replay + before/after done; 29 tests
```text
HEAD 7db6652 · behind origin/main: 0
-- commits on branch --
7db6652 feat(frontend): D4 negotiation controls, live agent status and escalation panel
-- uncommitted --
 M frontend/e2e/incident.spec.ts
 M frontend/src/App.css
 M frontend/src/App.tsx
 M frontend/src/api.ts
 M frontend/src/incident.ts
?? docs/handoff/frontend__rohaan-d5-replay-compare.md
?? frontend/e2e/replay.spec.ts
-- diffstat vs main --
 .../frontend__rohaan-d4-negotiation-escalation.md  | 100 +++++++
 frontend/e2e/backend.spec.ts                       |   2 +-
 frontend/e2e/incident.spec.ts                      |  35 +++
 frontend/e2e/negotiation.spec.ts                   | 158 ++++++++++
 frontend/e2e/smoke.spec.ts                         |  30 +-
 frontend/src/App.css                               | 153 ++++++++++
 frontend/src/App.tsx                               | 317 +++++++++++++++++++--
 frontend/src/api.ts                                |  72 ++++-
 frontend/src/components/EscalationPanel.tsx        | 126 ++++++++
 frontend/src/fixtures/preview.ts                   |   4 +-
 frontend/src/incident.ts                           | 103 ++++++-
 frontend/src/stream.ts                             |   3 +
 12 files changed, 1053 insertions(+), 50 deletions(-)
```
