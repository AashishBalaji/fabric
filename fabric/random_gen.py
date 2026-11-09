"""Constrained-random stimulus generation.

Every generator takes an explicit random.Random instance rather than
touching the global random module, so a run is reproducible end to end
from a single seed -- the same thing a failure-triage workflow needs to
replay a failing case exactly.

An earlier version of this module generated uniformly (plain
`randint`/`choice` with no weighting at all) while calling itself
"constrained-random" -- real constrained-random stimulus is supposed to
bias toward the corners that actually find bugs, not just sample
uniformly with a seed. These generators now explicitly weight toward
boundary lengths/values and toward the specific adjacency ("ED"/"DE",
an enable immediately followed by a disable or vice versa) that found
the real command/interrupt race documented in firmware/main.c -- the
kind of corner a verification engineer would deliberately bias for,
not something a uniform sampler would reliably hit.
"""
from __future__ import annotations

import random

from .protocol import MASK_STEPS


def gen_directed_n(rng: random.Random, lo: int = 1, hi: int = 12) -> int:
    """Weighted toward the boundary values (lo, hi) -- the off-by-one
    and overrun bugs this project actually found both showed up at
    small/edge N, not in the middle of the range."""
    if rng.random() < 0.4:
        return rng.choice([lo, hi])
    return rng.randint(lo, hi)


def gen_gpio_n(rng: random.Random, lo: int = 1, hi: int = 12) -> int:
    if rng.random() < 0.4:
        return rng.choice([lo, hi])
    return rng.randint(lo, hi)


def gen_mask_sequence(rng: random.Random, min_len: int = 1, max_len: int = 8) -> str:
    """A sequence of E/D/T steps, biased toward three kinds of corners
    rather than sampled uniformly:

    - boundary lengths (min_len, max_len), oversampled vs. the middle
      of the range;
    - a forced E/D or D/E adjacency somewhere in the sequence -- this
      is the exact transition that triggered the real command/
      interrupt race (any sequence containing "ED" desynced the probe
      byte before the fix in scenario_mask_stress's two-pass read);
    - all-same-step sequences (all 'E', all 'D', or all 'T'), which
      uniform choice() rarely produces for longer lengths but which
      are a real corner (never toggling the mask at all).
    """
    if rng.random() < 0.3:
        length = rng.choice([min_len, max_len])
    else:
        length = rng.randint(min_len, max_len)

    roll = rng.random()
    if roll < 0.35 and length >= 2:
        # Force an E/D or D/E adjacency at a random position.
        pair = rng.choice(["ED", "DE"])
        pos = rng.randint(0, length - 2)
        steps = [rng.choice(MASK_STEPS) for _ in range(length)]
        steps[pos], steps[pos + 1] = pair[0], pair[1]
        return "".join(steps)
    if roll < 0.5:
        # All-same-step corner.
        return rng.choice(MASK_STEPS) * length
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
