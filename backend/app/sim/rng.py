"""Common random numbers (PRD §5.5, FR-014, D-13).

    u(seed, step, cell) = first 8 bytes of SHA-256("{seed}:{step}:{cell}") / 2^64

The draw depends only on seed, step and cell id, so every method and every counterfactual sees identical ignition
draws for the same cell at the same step: differences between runs come from decisions, not luck. No other
randomness exists inside the simulator (AGENTS.md §7).
"""

from __future__ import annotations

import hashlib

_TWO_64 = float(2**64)


def draw(seed: int, step: int, cell_id: str) -> float:
    digest = hashlib.sha256(f"{seed}:{step}:{cell_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / _TWO_64
