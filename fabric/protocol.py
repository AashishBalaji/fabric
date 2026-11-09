"""Wire protocol for talking to the Fabric firmware over its UART.

Pure encode/decode logic, no I/O -- SoC.py owns the actual pipe. Keeping
the two separate means the protocol's framing (what bytes mean what) can
be unit-tested without ever booting QEMU, while soc.py's job is only
"get these exact bytes there and back reliably."

Every scenario that needs the firmware to receive a UART byte uses an
explicit ready handshake: the firmware prints 'R' once it has actually
armed whatever needs arming, and the host does not write stimulus bytes
before seeing it. This was not a nice-to-have -- the first version of the
directed scenario undercounted bytes sent before the RX interrupt was
actually enabled (there's no hardware FIFO backing it), and a fixed
busy-wait budget on the firmware side raced real host round-trip latency
in the other direction. The handshake removes both races.
"""
from __future__ import annotations

from dataclasses import dataclass


class ProtocolError(Exception):
    """The firmware's response didn't parse as this scenario expects."""


# ---- scenario: directed_uart_timer ('D') -----------------------------

def encode_directed(n: int) -> bytes:
    if not (0 <= n <= 255):
        raise ValueError("n must fit in one byte (0-255)")
    return b"D" + bytes([n])


def directed_stimulus(n: int, pattern: bytes | None = None) -> bytes:
    """The N stimulus bytes to send once 'R' is seen. Any bytes work --
    the firmware only counts arrivals, it doesn't interpret content."""
    if pattern is not None:
        if len(pattern) != n:
            raise ValueError("pattern length must equal n")
        return pattern
    return bytes((i % 26) + ord("a") for i in range(n))


@dataclass(frozen=True)
class DirectedResult:
    rx_count: int
    tick_count: int


def parse_directed(line: str) -> DirectedResult:
    parts = line.split()
    if len(parts) != 3 or parts[0] != "D":
        raise ProtocolError(f"bad directed response: {line!r}")
    return DirectedResult(rx_count=int(parts[1]), tick_count=int(parts[2]))


# ---- scenario: gpio_during_burst ('G') --------------------------------

def encode_gpio(n: int) -> bytes:
    if not (0 <= n <= 255):
        raise ValueError("n must fit in one byte (0-255)")
    return b"G" + bytes([n])


@dataclass(frozen=True)
class GpioResult:
    ok: int
    fault: int
    echoed: str


def parse_gpio(line: str) -> GpioResult:
    # The firmware writes n echo letters (A, B, C, ... wrapping at Z)
    # with no separators, immediately followed by "G <ok> <fault>".
    idx = line.find("G ")
    if idx < 0:
        raise ProtocolError(f"bad gpio response: {line!r}")
    echoed = line[:idx]
    parts = line[idx:].split()
    if len(parts) != 3 or parts[0] != "G":
        raise ProtocolError(f"bad gpio response: {line!r}")
    return GpioResult(ok=int(parts[1]), fault=int(parts[2]), echoed=echoed)


# ---- scenario: nested_priority ('N') ----------------------------------

UART_ENTER, UART_EXIT, TICK_ENTER, TICK_EXIT = 1, 2, 3, 4


@dataclass(frozen=True)
class NestedResult:
    log: tuple[int, ...]

    @property
    def uart_handler_ran(self) -> bool:
        return UART_ENTER in self.log

    @property
    def ticks_nested_inside_uart_handler(self) -> int:
        """How many full SysTick enter/exit pairs landed between the
        UART handler's enter and exit -- the actual thing this scenario
        is trying to observe (did the higher-priority tick preempt the
        lower-priority, long-running UART handler)."""
        if UART_ENTER not in self.log or UART_EXIT not in self.log:
            return 0
        start = self.log.index(UART_ENTER)
        end = self.log.index(UART_EXIT, start)
        inside = self.log[start + 1 : end]
        return inside.count(TICK_ENTER)


def encode_nested() -> bytes:
    return b"N"


def nested_trigger_byte() -> bytes:
    return b"x"


def parse_nested(line: str) -> NestedResult:
    parts = line.split()
    if not parts or parts[0] != "N":
        raise ProtocolError(f"bad nested response: {line!r}")
    return NestedResult(log=tuple(int(x) for x in parts[1:]))


# ---- scenario: mask_stress ('M') --------------------------------------

MASK_STEPS = ("E", "D", "T")  # enable RX IRQ, disable it, wait for a tick


def encode_mask_stress(steps: str) -> bytes:
    if not steps or any(s not in MASK_STEPS for s in steps):
        raise ValueError(f"steps must be a nonempty string drawn from {MASK_STEPS}")
    if len(steps) > 255:
        raise ValueError("step sequence must fit in one length byte (<=255)")
    return b"M" + bytes([len(steps)]) + steps.encode("ascii")


def mask_stress_probe_byte() -> bytes:
    return b"z"


@dataclass(frozen=True)
class MaskStressResult:
    rx_count: int
    tick_count: int

    @property
    def probe_was_counted(self) -> bool:
        return self.rx_count >= 1


def parse_mask_stress(line: str) -> MaskStressResult:
    parts = line.split()
    if len(parts) != 3 or parts[0] != "M":
        raise ProtocolError(f"bad mask_stress response: {line!r}")
    return MaskStressResult(rx_count=int(parts[1]), tick_count=int(parts[2]))


def final_mask_state(steps: str) -> bool:
    """What mask state a given step sequence leaves the RX IRQ in,
    computed the same way the host's oracle predicts probe_was_counted
    -- independent of anything the firmware reports, so the two can be
    compared. True = enabled."""
    enabled = False  # firmware starts each scenario with the IRQ disabled
    for s in steps:
        if s == "E":
            enabled = True
        elif s == "D":
            enabled = False
        # 'T' (wait for a tick) does not change the mask
    return enabled
