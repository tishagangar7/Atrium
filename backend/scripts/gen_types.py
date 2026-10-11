"""Generate `frontend/src/types.ts` from `backend/app/models.py` (PRD §7, §12.2).

Owner: Tisha / WS-C. `frontend/src/types.ts` is generated and never hand-edited; run
this script after any change to `models.py` and commit the regenerated output.

    uv run python scripts/gen_types.py        # from backend/

Deliberately dependency-free (no pydantic-to-typescript package): this walks our own
Pydantic models' field annotations directly, so output is deterministic, offline and
matches our exact field order with no extra runtime dependency for the event.

Mapping rules:
- Every field is emitted as a required TS property. Per PRD §7, optional fields are
  `None`/`null`, never a missing key, so TS types never use `?:` -- nullable fields get
  a `| null` union member instead.
- A module-level `Literal[...]` type alias (e.g. `AgentId = Literal["EVAC", ...]`) is
  rendered once as `export type AgentId = "EVAC" | ...;` and referenced by name from any
  field whose literal value set matches it. An inline `Literal[...]` with no matching
  alias (e.g. the single-value `"Synthetic simulation"` label) is rendered inline.
- A `BaseModel` subclass becomes a TS `interface` referenced by name.
"""

from __future__ import annotations

import sys
import types
import typing
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
OUTPUT_PATH = REPO_ROOT / "frontend" / "src" / "types.ts"

sys.path.insert(0, str(BACKEND_DIR))

import app.models as m  # noqa: E402
from pydantic import BaseModel  # noqa: E402

NoneType = type(None)


def _is_literal(tp: object) -> bool:
    return typing.get_origin(tp) is typing.Literal


def _is_union(tp: object) -> bool:
    origin = typing.get_origin(tp)
    return origin is typing.Union or origin is types.UnionType


def _collect_literal_aliases() -> dict[tuple, str]:
    """Module-level `Name = Literal[...]` assignments, keyed by their value tuple."""
    aliases: dict[tuple, str] = {}
    for name, value in vars(m).items():
        if name.startswith("_") or not _is_literal(value):
            continue
        args = typing.get_args(value)
        aliases.setdefault(args, name)
    return aliases


def _collect_models() -> list[type[BaseModel]]:
    seen: list[type[BaseModel]] = []
    for value in vars(m).values():
        if isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel:
            if value not in seen:
                seen.append(value)
    return seen


LITERAL_ALIASES = _collect_literal_aliases()
MODELS = _collect_models()
MODEL_NAMES = {cls.__name__ for cls in MODELS}


def ts_type(annotation: object) -> str:
    if annotation is NoneType:
        return "null"
    if annotation in (str,):
        return "string"
    if annotation in (int, float):
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation is dict:
        return "Record<string, unknown>"

    origin = typing.get_origin(annotation)

    if _is_literal(annotation):
        args = typing.get_args(annotation)
        alias = LITERAL_ALIASES.get(args)
        if alias:
            return alias
        return " | ".join(f'"{a}"' for a in args)

    if _is_union(annotation):
        members = typing.get_args(annotation)
        non_none = [a for a in members if a is not NoneType]
        rendered_members = list(dict.fromkeys(ts_type(a) for a in non_none))  # dedupe, keep order
        rendered = " | ".join(rendered_members)
        if len(non_none) != len(members):
            rendered += " | null"
        return rendered

    if origin is list or origin is set:
        (item,) = typing.get_args(annotation)
        return f"{ts_type(item)}[]"

    if origin is tuple:
        args = typing.get_args(annotation)
        return "[" + ", ".join(ts_type(a) for a in args) + "]"

    if origin is dict:
        key, value = typing.get_args(annotation)
        return f"Record<{ts_type(key)}, {ts_type(value)}>"

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation.__name__

    raise TypeError(f"gen_types.py: no TS mapping for annotation {annotation!r}")


def render_literal_alias(args: tuple, name: str) -> str:
    values = " | ".join(f'"{a}"' for a in args)
    return f"export type {name} = {values};"


def render_interface(cls: type[BaseModel]) -> str:
    lines = [f"export interface {cls.__name__} {{"]
    for field_name, field in cls.model_fields.items():
        lines.append(f"  {field_name}: {ts_type(field.annotation)};")
    lines.append("}")
    return "\n".join(lines)


def generate() -> str:
    parts = [
        "// GENERATED FILE -- do not hand-edit.",
        "// Source: backend/app/models.py. Regenerate with:",
        "//   cd backend && uv run python scripts/gen_types.py",
        "// Owner: Tisha / WS-C (AGENTS.md §12.2).",
        "",
    ]
    for args, name in LITERAL_ALIASES.items():
        parts.append(render_literal_alias(args, name))
    parts.append("")
    for cls in MODELS:
        parts.append(render_interface(cls))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(generate())
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
