"""Failure triage: turn a raw scenario result into a Finding (or nothing,
if it matched the oracle), classify it against a small catalog of known
failure signatures, and cluster repeated findings so a report shows "12
hits of one real bug" instead of 12 anonymous failures.

The oracles here are deliberately independent of the firmware's own
internal logic: each one predicts the expected outcome purely from the
stimulus the host sent, the same way a real verification environment's
reference model would, so a firmware bug actually shows up as a
mismatch rather than being rubber-stamped by reusing the firmware's own
arithmetic.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from . import protocol as proto

CATALOG: dict[str, str] = {
    "directed_undercount": (
        "Fewer bytes were counted than were sent. On this UART (no "
        "hardware FIFO), this almost always means a byte arrived before "
        "the RX interrupt was actually enabled, or two bytes arrived "
        "close enough together that the second overwrote the first in "
        "the one-entry holding register before the ISR drained it."
    ),
    "directed_overcount": (
        "More bytes were counted than were sent. Check for a spurious "
        "or double-firing RX interrupt (e.g. MIS not fully cleared "
        "before the next arrival) rather than assuming lost stimulus."
    ),
    "gpio_mismatch": (
        "A GPIO write didn't read back as expected. On this part, "
        "GPIODATA is aliased across its whole address range by a "
        "per-access bit mask (address bits [9:2]); an access at the "
        "wrong offset silently touches zero pins rather than erroring. "
        "Check the register offset before suspecting the pin logic."
    ),
    "priority_not_honored": (
        "The UART handler ran, but no SysTick interrupt fired during "
        "it, even though SysTick's priority number was programmed "
        "lower (= higher priority) than UART0's. Check SCB_SHPR3 / "
        "NVIC_IPR1 programming and confirm the handler is actually busy "
        "long enough for a tick to land inside its window."
    ),
    "uart_handler_did_not_fire": (
        "No UART RX interrupt was observed at all for this run. Check "
        "that the RX interrupt was enabled (UART0_IM / NVIC_ISER0) "
        "before the stimulus byte was sent, and that the byte actually "
        "reached the RX line."
    ),
    "infra_error": (
        "The run itself failed (a QEMU/protocol timeout or a malformed "
        "response), separate from any oracle mismatch. An earlier CLI "
        "version let this propagate as an unhandled traceback, silently "
        "discarding every result already gathered in the batch -- "
        "exactly the kind of lost information this project's own "
        "triage system exists to avoid. It's recorded as a finding "
        "(not swallowed) and the batch stops here, since a timeout "
        "mid-scenario can leave the UART byte stream desynced -- "
        "continuing to run further scenarios on the same boot risks "
        "garbage-in-garbage-out results that look legitimate but aren't."
    ),
    "mask_state_mismatch": (
        "A stimulus byte's fate (counted vs. not) didn't match what the "
        "final E/D state of the step sequence predicted. Either the "
        "mask isn't being applied when expected, or the byte arrived "
        "during a brief enable/disable transition race rather than "
        "cleanly after the sequence finished."
    ),
}


@dataclass(frozen=True)
class Finding:
    scenario: str
    args: Any
    signature: str
    detail: str
    observed: Any

    @property
    def suggestion(self) -> str:
        return CATALOG.get(self.signature, "No catalog entry for this signature yet.")


def check_directed(n: int, result: proto.DirectedResult) -> Finding | None:
    if result.rx_count == n:
        return None
    sig = "directed_undercount" if result.rx_count < n else "directed_overcount"
    return Finding(
        scenario="directed", args={"n": n}, signature=sig,
        detail=f"expected rx_count={n}, got {result.rx_count}", observed=result,
    )


def check_gpio(n: int, result: proto.GpioResult) -> Finding | None:
    expected_ok = 2 * n
    if result.ok == expected_ok and result.fault == 0:
        return None
    return Finding(
        scenario="gpio", args={"n": n}, signature="gpio_mismatch",
        detail=f"expected ok={expected_ok}/fault=0, got ok={result.ok}/fault={result.fault}",
        observed=result,
    )


def check_nested(result: proto.NestedResult) -> Finding | None:
    if not result.uart_handler_ran:
        return Finding(
            scenario="nested", args={}, signature="uart_handler_did_not_fire",
            detail="UART enter code never appeared in the event log", observed=result,
        )
    if result.ticks_nested_inside_uart_handler < 1:
        return Finding(
            scenario="nested", args={}, signature="priority_not_honored",
            detail=f"log={result.log}", observed=result,
        )
    return None


def check_mask_stress(steps: str, result: proto.MaskStressResult) -> Finding | None:
    predicted = proto.final_mask_state(steps)
    if predicted == result.probe_was_counted:
        return None
    return Finding(
        scenario="mask_stress", args={"steps": steps}, signature="mask_state_mismatch",
        detail=(
            f"steps={steps!r} predicts final_mask_enabled={predicted}, "
            f"but probe_was_counted={result.probe_was_counted}"
        ),
        observed=result,
    )


@dataclass
class TriageEngine:
    findings: list[Finding] = field(default_factory=list)

    def record(self, finding: Finding | None) -> None:
        if finding is not None:
            self.findings.append(finding)

    def clusters(self) -> Counter[str]:
        return Counter(f.signature for f in self.findings)

    def representative(self, signature: str) -> Finding | None:
        for f in self.findings:
            if f.signature == signature:
                return f
        return None
