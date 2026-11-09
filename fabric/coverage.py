"""A small functional-coverage model: named buckets, a record of which
have been hit at least once, and a closure percentage against the full
universe of buckets this project defines. This is the actual "did we
test enough of the state space" signal -- pass/fail on individual runs
answers a different question (did this one stimulus behave correctly).

CoverageModel persists to a JSON file (load/save) so closure is a real
campaign metric, not a per-invocation snapshot. An earlier version only
ever held hits in memory, reset fresh on every CLI call -- "88% closure"
was only ever true within one process's lifetime; running the exact
same command twice produced two unrelated 88%s with no notion of a
regression campaign accumulating coverage over time, which is the whole
point of a coverage model in real verification work.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from . import protocol as proto

DEFAULT_COVERAGE_DB = Path.home() / ".fabric_coverage.json"


def _bucket(n: int, edges: tuple[int, ...]) -> str:
    """Classify n into one of len(edges)+1 named size buckets."""
    labels = ["tiny", "small", "medium", "large", "huge"]
    for edge, label in zip(edges, labels):
        if n <= edge:
            return label
    return labels[len(edges)] if len(edges) < len(labels) else "huge"


# Bucket edges and the universes below must stay consistent with
# random_gen.py's generator ranges -- they previously weren't:
# gen_directed_n/gen_gpio_n draw n in 1..12, but these universes only
# listed tiny/small/medium (n<=8), so any generated n in 9..12 bucketed
# to "large" and was silently invisible to closure()/gaps() -- not a
# gap, not a hit, just dropped. ~32% of generated stimulus was affected.
def directed_bucket(n: int) -> str:
    return f"directed/n={_bucket(n, (1, 3, 8))}"


DIRECTED_UNIVERSE = {f"directed/n={b}" for b in ("tiny", "small", "medium", "large")}


def gpio_bucket(n: int) -> str:
    return f"gpio/n={_bucket(n, (1, 3, 8))}"


GPIO_UNIVERSE = {f"gpio/n={b}" for b in ("tiny", "small", "medium", "large")}


def nested_bucket(result: proto.NestedResult) -> str:
    if not result.uart_handler_ran:
        return "nested/uart_handler_did_not_fire"
    k = result.ticks_nested_inside_uart_handler
    return f"nested/ticks_inside={_bucket(k, (0, 1, 2))}"


NESTED_UNIVERSE = {
    "nested/uart_handler_did_not_fire",
    "nested/ticks_inside=tiny",  # 0 ticks nested in -- priority NOT honored
    "nested/ticks_inside=small",  # 1 tick nested in
    "nested/ticks_inside=medium",  # 2+ ticks nested in
}


def mask_stress_bucket(steps: str, result: proto.MaskStressResult) -> str:
    predicted = proto.final_mask_state(steps)
    actual = result.probe_was_counted
    agreement = "matches_prediction" if predicted == actual else "MISMATCH"
    length_bucket = _bucket(len(steps), (1, 3, 8))
    return f"mask_stress/len={length_bucket}/final={'enabled' if predicted else 'disabled'}/{agreement}"


def mask_stress_universe() -> set[str]:
    universe = set()
    for length_bucket in ("tiny", "small", "medium"):
        for final in ("enabled", "disabled"):
            universe.add(f"mask_stress/len={length_bucket}/final={final}/matches_prediction")
    return universe


FULL_UNIVERSE: set[str] = (
    DIRECTED_UNIVERSE | GPIO_UNIVERSE | NESTED_UNIVERSE | mask_stress_universe()
)


class CoverageModel:
    def __init__(self) -> None:
        self.hits: Counter[str] = Counter()

    def record(self, bucket: str) -> None:
        self.hits[bucket] += 1

    def closure(self, universe: set[str] = FULL_UNIVERSE) -> float:
        if not universe:
            return 1.0
        hit = sum(1 for b in universe if self.hits[b] > 0)
        return hit / len(universe)

    def gaps(self, universe: set[str] = FULL_UNIVERSE) -> set[str]:
        return {b for b in universe if self.hits[b] == 0}

    def mismatches(self) -> list[str]:
        """Buckets recording an oracle/actual disagreement -- these are
        findings, not coverage gaps, and should surface in reports even
        if a bucket like this has plenty of hits."""
        return sorted(b for b in self.hits if b.endswith("/MISMATCH") and self.hits[b] > 0)

    @classmethod
    def load(cls, path: Path = DEFAULT_COVERAGE_DB) -> "CoverageModel":
        """Load accumulated hits from a prior campaign, if any. Missing
        or unreadable files just start a fresh (empty) model -- this is
        a convenience cache, not a source of truth worth failing over."""
        model = cls()
        try:
            data = json.loads(path.read_text())
            model.hits.update(data)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        return model

    def save(self, path: Path = DEFAULT_COVERAGE_DB) -> None:
        try:
            path.write_text(json.dumps(dict(self.hits), indent=2, sort_keys=True))
        except OSError:
            pass  # best-effort; a failed save shouldn't fail the run
