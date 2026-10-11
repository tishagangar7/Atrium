"""Call and tool ledgers (PRD §10.5) with key redaction (§10.4).

Actors produce rows and return them in `TurnOutcome`; the run controller / router owns persistence under
`runs/<run_id>/` (WS-C). `write_jsonl` is provided so that owner does not re-implement the row format.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

from app.agents.provider import CallLedgerRow
from app.agents.tools import ToolLedgerRow

# Anthropic / OpenAI key shapes plus anything that looks like one. Applied to every string before it is written.
_KEY_RE = re.compile(r"sk-(?:ant-)?[A-Za-z0-9_-]{8,}")
REDACTED = "sk-REDACTED"

T = TypeVar("T")


def redact(text: str) -> str:
    return _KEY_RE.sub(REDACTED, text)


@dataclass
class _Ledger(Generic[T]):
    rows: list[T] = field(default_factory=list)

    def append(self, row: T) -> None:
        self.rows.append(row)

    def extend(self, rows: list[T]) -> None:
        self.rows.extend(rows)

    def write_jsonl(self, path: Path, *, append: bool = True) -> int:
        """Append rows as JSON lines (redacted). Returns the number of rows written."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a" if append else "w", encoding="utf-8") as fh:
            for row in self.rows:
                fh.write(redact(json.dumps(asdict(row), separators=(",", ":"), ensure_ascii=False)) + "\n")
        return len(self.rows)


class CallLedger(_Ledger[CallLedgerRow]):
    """One row per model call (§10.5): provider, model, agent, purpose, tokens, latency, status, cancelled."""

    def totals(self) -> dict[str, Any]:
        return {
            "calls": len(self.rows),
            "ok": sum(r.status == "ok" for r in self.rows),
            "errors": sum(r.status == "error" for r in self.rows),
            "timeouts": sum(r.status == "timeout" for r in self.rows),
            "cancelled": sum(r.cancelled for r in self.rows),
            "tokens_in": sum(r.tokens_in or 0 for r in self.rows),
            "tokens_out": sum(r.tokens_out or 0 for r in self.rows),
            "latency_ms": sum(r.latency_ms for r in self.rows),
        }


class ToolLedger(_Ledger[ToolLedgerRow]):
    """One row per tool execution (§10.5): args_summary, result_summary, sim_ms, evaluation_id."""

    def totals(self) -> dict[str, Any]:
        return {"tool_calls": len(self.rows), "errors": sum(r.is_error for r in self.rows),
                "evaluations": sum(r.evaluation_id is not None for r in self.rows),
                "sim_ms": sum(r.sim_ms for r in self.rows)}
