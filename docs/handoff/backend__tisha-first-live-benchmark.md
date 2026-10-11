# Handoff: backend/tisha-first-live-benchmark

| Branch | `backend/tisha-first-live-benchmark` |
| Workstream / queue item | C6/C7 — first live benchmark batch, `runs/results.csv` |
| PRD sections | §4.7, §8, §11.3, Appendix A.3 invariant 9 |

## Current state

> **Correction (Ali, 2026-10-11, branch `agents/ali-b7-normalize-before-validate`):** the `single_agent` "commits"
> below were F0 `AUTO_FALLBACK`s counted as commits by `bench/methods.py` (every row has `assisted_completion 0.0`,
> identical to the `rescuemesh` escalation rows). No model produced a valid plan in any of the 24 model runs of this
> batch. Root causes and fixes are in `docs/handoff/agents__ali-b7-normalize-before-validate.md`; this batch is kept
> at `docs/bench/results-2026-10-11-pre-b7-haiku-4-5.csv` as the "before". `runs/results.csv` now holds the new batch.

**Status:** Complete. 36 of 36 planned runs (PRD §11.3's full batch: 4 presets × 3 seeds ×
3 methods), every row real, verified non-zero tokens, no duplicates.

| Preset | fixed_rule | single_agent | rescuemesh |
|---|---|---|---|
| normal | 3/3 | 3/3 | 3/3 |
| wind_shift | 3/3 | 3/3 | 3/3 |
| road_closure | 3/3 | 3/3 | 3/3 |
| compound_failure | 3/3 | 3/3 | 3/3 |

**The headline result, now statistically clean across all 12 runs per method:**

| Method | Runs | Commits | Escalations |
|---|---|---|---|
| fixed_rule | 12 | 21 | 0 |
| single_agent | 12 | 21 | 0 |
| rescuemesh | 12 | **0** | **21** |

`rescuemesh` -- the real three-agent live negotiation -- escalated on every single decision
point, across all four presets, both providers (Anthropic and Gemini), and three different
models (`claude-haiku-4-5`, `gemini-3.8-flash`, `gemini-3.1-flash-lite`). `fixed_rule` and
`single_agent` both commit reliably under the identical scenarios. This is no longer "looks
like a tension worth checking" -- it is the full, complete, real result: as currently tuned,
live three-agent negotiation does not commit a plan under this protocol's call/time budgets,
regardless of provider.

**Done:**
- Fixed a real bug blocking every live Anthropic call (merged #45: `strict: true` tool schemas
  rejected outright when combined with structured output, regardless of schema size).
- Built and live-verified a Gemini provider (merged #48) as a free-tier option -- found and
  fixed two more real issues in the process: Gemini rejects combining `tools` with
  `response_schema` the same way Anthropic did (worked around by making the structured
  `AgentTurn` itself a callable tool, `submit_turn`), and requires `thought_signature` echoed
  back verbatim on multi-turn function calls or it 400s.
- Ran the real batch against `claude-haiku-4-5-20251001` (Anthropic): `normal`/`wind_shift`
  (18 rows) all genuine -- `fixed_rule`/`single_agent` commit in every seed; `rescuemesh`
  escalates in every seed (see the diagnosis below -- a live-latency/deadline tension, not a
  code defect).
- Ran two more real batches against Gemini (`gemini-3.8-flash`, then `gemini-3.1-flash-lite`
  after the first exhausted its own free-tier quota) to reach `road_closure`/`compound_failure`,
  which Anthropic credit hadn't gotten to yet. **Both models' free-tier quota ran out mid-batch**
  -- `gemini-3.8-flash` allows only 20 requests/day on this project, `gemini-3.1-flash-lite`
  lasted longer but still ran dry before covering every row. Every row that returned zero tokens
  despite a real `model_calls` count was discarded (confirmed by direct reproduction: HTTP 429
  quota-exceeded, not a code issue), same invariant-9 discipline as the earlier Anthropic
  billing discard. 27 real rows survived that round, deduplicated across three live batches.
- Once more Anthropic credit was added, ran the exact 9 missing (preset, seed, method) combos
  against `claude-haiku-4-5` with no overlap/waste: 6 `single_agent` runs (`road_closure` +
  `compound_failure`, all 3 seeds) and 3 targeted `rescuemesh` runs (the 2 missing
  `road_closure` seeds, the 1 missing `compound_failure` seed). All 9 came back with real,
  non-zero tokens. **36/36, complete.**

**Next steps:** none required for G3's "results generated" criterion -- it's met. The real open
question is the one below: live three-agent negotiation has never committed a plan across 36
real runs on three different models. The root cause is now precisely identified (not just
"deadline tuning" -- that was an earlier, superseded guess); see "Why `rescuemesh` escalates
every time" below, and the fix already landed (`agents/tisha-tool-batching-prompt`) for half
of it. The remaining half needs either a stronger model tier or further prompt/tool work, not
more benchmark runs.

**Why `rescuemesh` escalates every time -- the real cause, found from the saved traces:**

Ruled out by direct measurement: prompt size (near-identical ~16KB across all three agents) and
pure API latency variance (an earlier, now-superseded theory). The actual cause, found by
tracing every `tool.called` event against every `agent.turn` outcome across the 36-run batch:

Every agent calls `find_routes` once per resource it's checking (4 calls' worth of
reconnaissance) -- but `FIRE`'s model sometimes batches 2+ of those into one API response,
needing only 3 model calls total; `EVAC`/`LOG`'s models almost always call one tool per
response, burning all 4 of `MAX_MODEL_CALLS_PER_TURN` (`actor.py:56`) on reconnaissance alone,
with **zero calls left to ever call `validate_plan`, `evaluate_plan`, or submit a turn.**
Across every trace examined, no agent ever called `validate_plan` or `evaluate_plan` even
once -- only `find_routes`, then straight to a final answer attempt (or running out of budget
first). `MAX_TOOL_ITERATIONS = 2` (`actor.py:57`) means an agent that calls tools one at a time
can gather at most 2 pieces of information before tools are disabled for the rest of the turn.

**Fix landed:** an explicit prompt instruction (`agents/tisha-tool-batching-prompt`, merged) to
batch every `find_routes` call into round 1 and spend round 2 calling `validate_plan` on the
draft before proposing it. **Verified live** (3 single-turn test calls against `claude-haiku-4-5`,
not a full benchmark re-run): `EVAC` now reaches the planning stage in 3-4 calls instead of
exhausting its budget on recon alone -- the targeted bottleneck is fixed.

**What's still broken, found in the same test calls:** the plans `EVAC` constructs are often
invalid -- `RESOURCE_DOUBLE_BOOKED` (reusing a resource before its previous task ends),
`WRONG_LOCATION` (assigning a vehicle a leg from a node it isn't at). The model still skipped
calling `validate_plan` on its own draft even with the explicit instruction to. This reads as a
genuine planning-competence gap in the fast/cheap model tier for this task's combinatorial
resource-scheduling complexity -- not something a prompt wording change fixes by itself. Two
untried levers: a stronger model tier for `rescuemesh` specifically (traded for cost), or
restructuring the turn loop to force a `validate_plan` call before a `PROPOSE`/`COUNTERPROPOSE`
is accepted (a real code change, not a prompt change -- would need design discussion first,
since it changes §6.4's call-budget accounting).

**Gotchas:**
- `runs/results.csv` is the only file under `runs/` the `.gitignore` tracks (besides
  `runs/fixtures/`); the saved per-run `runs/<run_id>/events.jsonl` traces used to confirm the
  real tool calls and the billing error are not committed and are local-only.
- `RESCUEMESH_TURN_DEADLINE_S` and the real model/provider config live only in `backend/.env`
  (never committed, per invariant 10) -- this handoff names the values used but doesn't restore
  them for you.

**How to verify:**
```bash
cd backend && uv run pytest -q   # 313 pass
cat ../runs/results.csv          # 36 rows, 4 presets x 3 seeds x 3 methods; model column shows provider
```

**Asks for other owners:** Ali/WS-B: `rescuemesh`'s 0/21 commit rate across the full real batch,
on three different models, is worth your review -- is this turn-deadline tuning, or a deeper
protocol-timing issue? The diagnosis above is a starting point, not a conclusion.
