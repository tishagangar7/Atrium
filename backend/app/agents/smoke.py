"""T05 provider smoke test: structured AgentTurn calls, latency and token measurement (PRD §3.5, §12.3 B1).

    cd backend && python -m app.agents.smoke --provider all --n 3

For each provider whose key is present (ANTHROPIC_API_KEY / OPENAI_API_KEY, loaded from backend/.env) it sends `n`
representative round-1 Logistics turns built by the real prompt builder (§6.13: system per role, Observation from
the simulator stub, empty inbox, the four tool specs, the sentinel AgentTurn schema) and reports p50/p95 latency,
tokens and whether the output parsed and passed semantic validation. Results go to runs/provider_smoke.json
(git-ignored) and stdout; copy the numbers into the handoff doc. A provider without a key is reported as PENDING,
never faked (§12.3 B1 completion evidence).

Selection criteria recorded for §3.5: (2) schema-constrained output works, (3) median latency for a ~6k-token
prompt with a ~600-token answer under ~4 s. Criterion (1) credits and (4) cost are team decisions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.prompt import DEFAULT_TARGETS, build_observation, build_system_prompt, build_user_prompt
from app.agents.provider import (
    ProviderError,
    ProviderRequest,
    UserText,
    backend_dir,
    load_backend_env,
)
from app.agents.schema import TurnContext, parse_turn, turn_output_schema, validate_turn
from app.agents.sim_stub import StubSim
from app.agents.tools import tool_specs

KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
AGENT = "LOG"


def build_request(sim: StubSim, timeout_s: float) -> tuple[ProviderRequest, TurnContext]:
    view = sim.build_belief_view(AGENT)
    system = build_system_prompt(AGENT, DEFAULT_TARGETS)
    observation = build_observation(AGENT, view, run_id=view.world["run_id"], dp_id="dp-1", round_=1,
                                    targets=DEFAULT_TARGETS)
    user = build_user_prompt(observation, [], [], round_=1, time_left_s=30)
    req = ProviderRequest(system=system, messages=(UserText(user),), tools=tool_specs(),
                          output_schema=turn_output_schema(), max_output_tokens=2048, timeout_s=timeout_s,
                          purpose="smoke", agent_id=AGENT)
    ctx = TurnContext(agent_id=AGENT, round=1, step=view.step, horizon=60,
                      held_evidence_ids={e.evidence_id for e in view.held_evidence},
                      own_targets=DEFAULT_TARGETS[AGENT], known_resource_ids=set(view.world["resources"]))
    return req, ctx


async def run_provider(name: str, model: str, n: int, timeout_s: float) -> dict[str, Any]:
    if not os.environ.get(KEY_ENV[name]):
        return {"provider": name, "model": model, "status": "PENDING", "reason": f"{KEY_ENV[name]} not set"}
    if name == "anthropic":
        from app.agents.provider_anthropic import AnthropicProvider
        provider: Any = AnthropicProvider(model=model, effort=os.environ.get("RESCUEMESH_EFFORT") or None)
    else:
        from app.agents.provider_openai import OpenAIProvider
        provider = OpenAIProvider(model=model, effort=os.environ.get("RESCUEMESH_EFFORT") or None)

    sim = StubSim()
    req, ctx = build_request(sim, timeout_s)
    calls: list[dict[str, Any]] = []
    for i in range(n):
        row: dict[str, Any] = {"i": i}
        try:
            resp = await provider.complete(req)
            row.update(kind=resp.kind, latency_ms=resp.latency_ms, tokens_in=resp.tokens_in,
                       tokens_out=resp.tokens_out, stop_reason=resp.stop_reason, request_id=resp.request_id)
            if resp.kind == "output":
                try:
                    turn = parse_turn(resp.output_json or {}, agent_id=AGENT, dp_id="dp-1")
                    errors = validate_turn(turn, ctx)
                    row.update(parsed=True, semantic_errors=errors,
                               message_types=[m.message_type for m in turn.messages])
                except Exception as e:  # noqa: BLE001 — report, don't crash the smoke run
                    row.update(parsed=False, parse_error=str(e)[:300])
            elif resp.kind == "tool_calls":
                row.update(parsed=True, tool_calls=[c.name for c in resp.tool_calls])
            else:
                row.update(parsed=False, output_text=resp.output_text[:300])
        except ProviderError as e:
            row.update(kind="error", error=str(e), retryable=e.retryable, status=e.status)
        calls.append(row)
        print(f"  {name} call {i + 1}/{n}: {row.get('kind')} {row.get('latency_ms', '-')} ms "
              f"in={row.get('tokens_in')} out={row.get('tokens_out')} parsed={row.get('parsed')}", flush=True)

    latencies = [c["latency_ms"] for c in calls if "latency_ms" in c]
    ok = [c for c in calls if c.get("parsed") and not c.get("semantic_errors")]
    return {
        "provider": name, "model": model, "status": "OK" if ok else "FAILED", "n": n,
        "structured_ok": len(ok), "p50_ms": statistics.median(latencies) if latencies else None,
        "p95_ms": (sorted(latencies)[max(0, int(round(0.95 * len(latencies))) - 1)] if latencies else None),
        "tokens_in": [c.get("tokens_in") for c in calls], "tokens_out": [c.get("tokens_out") for c in calls],
        "calls": calls,
    }


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--provider", choices=["anthropic", "openai", "all", "env"], default="env",
                    help="'env' uses RESCUEMESH_PROVIDER; 'all' tries both")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=30.0, help="per-call timeout (smoke, not the 8 s turn deadline)")
    ap.add_argument("--out", type=Path, default=backend_dir().parent / "runs" / "provider_smoke.json")
    args = ap.parse_args(argv)
    load_backend_env()

    model = os.environ.get("RESCUEMESH_MODEL", "")
    providers = ["anthropic", "openai"] if args.provider == "all" else (
        [os.environ.get("RESCUEMESH_PROVIDER", "")] if args.provider == "env" else [args.provider])
    providers = [p for p in providers if p in KEY_ENV]
    if not providers:
        print("No live provider selected. Set RESCUEMESH_PROVIDER=anthropic|openai or pass --provider.")
        return 2
    if not model:
        print("RESCUEMESH_MODEL is not set (backend/.env). Refusing to guess a model id (AGENTS.md §5).")
        return 2

    report: dict[str, Any] = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "label": "T05 provider smoke — synthetic simulation, stub observation",
                              "results": []}
    for p in providers:
        print(f"→ {p} ({model})")
        report["results"].append(await run_provider(p, model, args.n, args.timeout))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(f"\n{'provider':10} {'status':8} {'n':>3} {'ok':>3} {'p50 ms':>8} {'p95 ms':>8}  model")
    for r in report["results"]:
        print(f"{r['provider']:10} {r['status']:8} {r.get('n', '-'):>3} {r.get('structured_ok', '-'):>3} "
              f"{str(r.get('p50_ms', '-')):>8} {str(r.get('p95_ms', '-')):>8}  {r['model']}"
              + (f"  ({r['reason']})" if r.get("reason") else ""))
    print(f"written: {args.out}")
    return 0 if any(r["status"] == "OK" for r in report["results"]) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
