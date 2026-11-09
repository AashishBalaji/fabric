"""Boots the Fabric firmware under qemu-system-arm and drives it over its
emulated UART. This is the only module in the package that touches a real
subprocess or a real clock -- everything else works on plain data so it
can be unit-tested without QEMU.
"""
from __future__ import annotations

import selectors
import subprocess
import time
from pathlib import Path

from . import protocol as proto

FIRMWARE_ELF = Path(__file__).resolve().parent.parent / "firmware" / "firmware.elf"


class SocTimeoutError(Exception):
    """The firmware didn't respond the way a given scenario expects
    within its timeout. This is always a real finding worth keeping
    (a QEMU hang, a lost interrupt, a hardware race) -- callers should
    report it, not swallow it."""


class Soc:
    """One QEMU boot of the firmware, with the UART wired to a pipe."""

    def __init__(self, qemu_binary: str = "qemu-system-arm", boot_timeout: float = 8.0):
        if not FIRMWARE_ELF.exists():
            raise FileNotFoundError(
                f"{FIRMWARE_ELF} not found -- run `make` in firmware/ first"
            )
        self._proc = subprocess.Popen(
            [
                qemu_binary, "-M", "lm3s6965evb", "-nographic", "-monitor", "none",
                "-kernel", str(FIRMWARE_ELF), "-serial", "stdio",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        self._sel = selectors.DefaultSelector()
        self._sel.register(self._proc.stdout, selectors.EVENT_READ)
        # QEMU prints one boot-time diagnostic line of its own
        # ("Timer with period zero, disabling") before the firmware has
        # done anything -- drain it (and give the firmware a moment to
        # reach main()) rather than let it desync the first real read.
        time.sleep(0.3)
        self._drain(boot_timeout)

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()  # reap it -- kill() alone leaves a zombie
        else:
            self._proc.wait()  # already exited but not yet reaped
        self._sel.close()

    def __enter__(self) -> "Soc":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- raw I/O -------------------------------------------------------

    def _write(self, data: bytes) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(data)
        self._proc.stdin.flush()

    def _write_paced(self, data: bytes, gap: float = 0.003) -> None:
        """Write bytes one at a time with a small gap between them.

        This UART has no hardware FIFO (one-entry holding register), and
        a scenario like mask_stress reads a whole multi-byte command
        header via plain polling rather than the RX interrupt. A single
        bulk write() of that whole header reliably overran the holding
        register in QEMU's model before the firmware's poll loop got a
        chance to drain each byte -- confirmed by reproducing it with a
        5-byte burst that left only the last byte readable, hanging the
        scenario forever waiting for bytes that had already been
        overwritten. Bytes drained by the RX *interrupt* (the directed
        scenario's stimulus) don't have this problem, since the ISR
        reacts to each arrival immediately; this pacing is only needed
        for multi-byte sequences a scenario reads by polling.
        """
        assert self._proc.stdin is not None
        for b in data:
            self._proc.stdin.write(bytes([b]))
            self._proc.stdin.flush()
            time.sleep(gap)

    def _read_byte(self, timeout: float) -> bytes:
        """Returns one byte, or b"" if `timeout` elapsed with nothing
        available. Raises SocTimeoutError directly on genuine EOF
        (QEMU's stdout closed) rather than returning b"" for that too --
        an earlier version conflated the two, so a plain timeout with
        the process still very much alive was misreported as "QEMU
        process ended", which it hadn't."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return b""
            events = self._sel.select(timeout=remaining)
            if events:
                assert self._proc.stdout is not None
                b = self._proc.stdout.read(1)
                if b:
                    return b
                raise SocTimeoutError("QEMU process ended unexpectedly (EOF on stdout)")

    def _read_until(self, target: bytes, timeout: float) -> bytes:
        buf = bytearray()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SocTimeoutError(
                    f"timed out waiting for {target!r}; got so far: {bytes(buf)!r}"
                )
            b = self._read_byte(remaining)
            if b:
                buf += b
                if buf.endswith(target):
                    return bytes(buf)
            # else: this attempt's own timeout elapsed with nothing
            # read; loop back and let the outer deadline check decide.

    def _drain(self, timeout: float) -> None:
        """Best-effort: read and discard anything already buffered (boot
        noise), without blocking if there's nothing there."""
        try:
            self._read_until(b"\n", timeout)
        except SocTimeoutError:
            pass

    def _read_line(self, timeout: float) -> str:
        raw = self._read_until(b"\n", timeout)
        return raw.decode("ascii", errors="replace").strip()

    def _wait_ready(self, timeout: float) -> None:
        """Block until the firmware's 'R' handshake byte, confirming it
        has actually armed whatever this scenario needs armed before we
        write any stimulus bytes. See protocol.py's module docstring for
        why this exists."""
        self._read_until(b"R", timeout)

    # ---- scenarios ------------------------------------------------------

    def run_directed(
        self, n: int, pattern: bytes | None = None, timeout: float = 8.0
    ) -> proto.DirectedResult:
        self._write(proto.encode_directed(n))
        self._wait_ready(timeout)
        # Paced for the same reason as mask_stress's header: this UART
        # has no hardware FIFO, just a one-entry holding register. The
        # RX *interrupt* drains it fast enough to usually survive a
        # bulk multi-byte write, but not reliably -- under real
        # (variable) host/QEMU scheduling a bulk write of N>1 bytes
        # intermittently overran it, undercounting (confirmed via a
        # temporary firmware breadcrumb: the ISR fired exactly once per
        # run instead of N times). Pacing removes the race instead of
        # just making it rare.
        self._write_paced(proto.directed_stimulus(n, pattern))
        return proto.parse_directed(self._read_line(timeout))

    def run_gpio(self, n: int, timeout: float = 8.0) -> proto.GpioResult:
        self._write(proto.encode_gpio(n))
        return proto.parse_gpio(self._read_line(timeout))

    def run_nested(self, timeout: float = 8.0) -> proto.NestedResult:
        self._write(proto.encode_nested())
        self._wait_ready(timeout)
        self._write(proto.nested_trigger_byte())
        return proto.parse_nested(self._read_line(timeout))

    def run_mask_stress(self, steps: str, timeout: float = 8.0) -> proto.MaskStressResult:
        # Multi-byte header, all read via polling -- paced to avoid the
        # holding-register overrun described on _write_paced.
        self._write_paced(proto.encode_mask_stress(steps))
        self._wait_ready(timeout)
        self._write(proto.mask_stress_probe_byte())
        return proto.parse_mask_stress(self._read_line(timeout))
