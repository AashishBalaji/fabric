"""Constrained-random stimulus generation.

Every generator takes an explicit random.Random instance rather than
touching the global random module, so a run is reproducible end to end
from a single seed -- the same thing a failure-triage workflow needs to
replay a failing case exactly.
"""
from __future__ import annotations

import random

from .protocol import MASK_STEPS


def gen_directed_n(rng: random.Random, lo: int = 1, hi: int = 12) -> int:
    return rng.randint(lo, hi)


def gen_gpio_n(rng: random.Random, lo: int = 1, hi: int = 12) -> int:
    return rng.randint(lo, hi)


def gen_mask_sequence(rng: random.Random, min_len: int = 1, max_len: int = 8) -> str:
    """A random sequence of E/D/T steps. Constrained only in length --
    every combination and ordering of E/D/T is a legal stimulus for this
    scenario, which is itself the point: the firmware has to behave
    sensibly under an arbitrary enable/disable/wait interleaving, not
    just the handful of orderings a directed test would think to write."""
    length = rng.randint(min_len, max_len)
    return "".join(rng.choice(MASK_STEPS) for _ in range(length))


Plan = tuple[str, tuple]
"""A (scenario, args) pair ready to hand to a Soc method via dispatch."""


def gen_plan(rng: random.Random) -> Plan:
    """Pick a random scenario and randomized arguments for it."""
    scenario = rng.choice(["directed", "gpio", "nested", "mask_stress"])
    if scenario == "directed":
        return ("directed", (gen_directed_n(rng),))
    if scenario == "gpio":
        return ("gpio", (gen_gpio_n(rng),))
    if scenario == "nested":
        return ("nested", ())
    return ("mask_stress", (gen_mask_sequence(rng),))


def gen_plans(seed: int, count: int) -> list[Plan]:
    rng = random.Random(seed)
    return [gen_plan(rng) for _ in range(count)]
