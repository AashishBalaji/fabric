"""Renders a plain-text summary: pass/fail counts, coverage closure and
gaps, and clustered failure findings with their suggested root causes.
No UI framework needed for this -- a CLI run's output is the whole
"dashboard" this project promises, and that's an honest match for what
was actually built."""
from __future__ import annotations

from .coverage import CoverageModel
from .triage import TriageEngine


def render(coverage: CoverageModel, triage: TriageEngine, total_runs: int) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("Fabric run report")
    lines.append("=" * 60)
    lines.append(f"Total scenario runs: {total_runs}")
    lines.append(f"Findings: {len(triage.findings)}")
    lines.append("")

    lines.append(f"Coverage closure: {coverage.closure():.0%}")
    gaps = sorted(coverage.gaps())
    if gaps:
        lines.append(f"Uncovered buckets ({len(gaps)}):")
        for g in gaps:
            lines.append(f"  - {g}")
    else:
        lines.append("No coverage gaps against the defined universe.")

    mismatches = coverage.mismatches()
    if mismatches:
        lines.append(f"Oracle/actual mismatches ({len(mismatches)}):")
        for m in mismatches:
            lines.append(f"  - {m}")
    lines.append("")

    clusters = triage.clusters()
    if clusters:
        lines.append("Failure clusters (by signature):")
        for signature, count in clusters.most_common():
            rep = triage.representative(signature)
            lines.append(f"  [{count}x] {signature}")
            if rep is not None:
                lines.append(f"      e.g. {rep.detail}")
                lines.append(f"      root cause: {rep.suggestion}")
    else:
        lines.append("No failures -- every run matched its oracle.")

    return "\n".join(lines)
