"""CLI entrypoint.

    python -m fabric.cli run --directed 3
    python -m fabric.cli run --gpio 5
    python -m fabric.cli run --nested
    python -m fabric.cli run --mask-stress EDT
    python -m fabric.cli run --random 50 --seed 1234
"""
from __future__ import annotations

import argparse
import sys

from . import coverage as cov
from . import random_gen as rg
from . import report as rpt
from . import triage as tri
from .soc import Soc


def execute_plan(soc: Soc, scenario: str, args: tuple, coverage: cov.CoverageModel, triage: tri.TriageEngine) -> None:
    if scenario == "directed":
        (n,) = args
        result = soc.run_directed(n)
        coverage.record(cov.directed_bucket(n))
        triage.record(tri.check_directed(n, result))
    elif scenario == "gpio":
        (n,) = args
        result = soc.run_gpio(n)
        coverage.record(cov.gpio_bucket(n))
        triage.record(tri.check_gpio(n, result))
    elif scenario == "nested":
        result = soc.run_nested()
        coverage.record(cov.nested_bucket(result))
        triage.record(tri.check_nested(result))
    elif scenario == "mask_stress":
        (steps,) = args
        result = soc.run_mask_stress(steps)
        coverage.record(cov.mask_stress_bucket(steps, result))
        triage.record(tri.check_mask_stress(steps, result))
    else:
        raise ValueError(f"unknown scenario {scenario!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fabric")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run one or more scenarios and print a report")
    run_p.add_argument("--directed", type=int, metavar="N", help="run directed_uart_timer with N stimulus bytes")
    run_p.add_argument("--gpio", type=int, metavar="N", help="run gpio_during_burst with N toggles")
    run_p.add_argument("--nested", action="store_true", help="run nested_priority once")
    run_p.add_argument("--mask-stress", type=str, metavar="STEPS", help="run mask_stress with an explicit E/D/T step string")
    run_p.add_argument("--random", type=int, metavar="COUNT", help="run COUNT randomly generated scenarios")
    run_p.add_argument("--seed", type=int, default=0, help="seed for --random (default 0)")

    args = parser.parse_args(argv)

    if args.command == "run":
        plans: list[rg.Plan] = []
        if args.directed is not None:
            plans.append(("directed", (args.directed,)))
        if args.gpio is not None:
            plans.append(("gpio", (args.gpio,)))
        if args.nested:
            plans.append(("nested", ()))
        if args.mask_stress is not None:
            plans.append(("mask_stress", (args.mask_stress,)))
        if args.random is not None:
            plans.extend(rg.gen_plans(args.seed, args.random))

        if not plans:
            print("Nothing to run -- pass at least one of --directed/--gpio/--nested/--mask-stress/--random", file=sys.stderr)
            return 2

        coverage = cov.CoverageModel()
        triage = tri.TriageEngine()
        with Soc() as soc:
            for scenario, scenario_args in plans:
                execute_plan(soc, scenario, scenario_args, coverage, triage)

        print(rpt.render(coverage, triage, total_runs=len(plans)))
        return 1 if triage.findings else 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
