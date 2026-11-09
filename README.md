# Fabric

A small SoC functional-validation framework: real bare-metal Cortex-M3
firmware, booted under `qemu-system-arm`, driven over its emulated UART
by a Python host that runs directed and constrained-random tests, tracks
functional coverage, and triages failures against a small catalog of
known signatures.

Built as a portfolio project targeting SoC/post-silicon validation work
(functional coverage, constrained-random stimulus, failure triage,
cross-IP interaction, interrupt priority) -- the kind of thing a
validation engineer actually does, not a simulated stand-in for it.

```
$ python3 -m fabric.cli run --random 60 --seed 7
============================================================
Fabric run report
============================================================
Total scenario runs: 60
Findings: 1

Coverage closure: 88%
Uncovered buckets (2):
  - directed/n=tiny
  - nested/uart_handler_did_not_run

Failure clusters (by signature):
  [1x] priority_not_honored
      e.g. log=(3, 4, 1, 2)
      root cause: The UART handler ran, but no SysTick interrupt fired during it...
```

## What's real

- **The firmware is real.** `firmware/main.c` is bare-metal C (no CMSIS,
  no vendor HAL) targeting a Cortex-M3, cross-compiled with
  `arm-none-eabi-gcc` and booted under QEMU's `lm3s6965evb` machine --
  the same toolchain and target a real embedded validation job would
  use, just emulated instead of on a dev board.
- **The bugs it found are real.** Every one below was caught by actually
  running the thing, not by reasoning about the code:
  - A GPIO register-offset bug: this part aliases its DATA register
    across its whole address range using a per-access bit *mask*
    (address bits 9:2); the unmasked, "touch all pins" access lives at
    offset `0x3FC`, not `0x000`. Using `0x000` made every GPIO write a
    silent no-op -- confirmed by a 5-ok/5-fault split on a plain toggle
    where 10-ok/0-fault was expected.
  - An interrupt-enable race: this UART has no hardware FIFO (a
    one-entry holding register), so a stimulus byte sent before the RX
    interrupt is actually armed is simply never seen. Fixed with an
    explicit `'R'` ready handshake the firmware prints once the
    interrupt is armed, rather than a timing assumption.
  - A FIFO-less overrun: a multi-byte burst written in a single
    `write()` call can overwrite that same one-entry holding register
    before the firmware drains each byte -- true for a scenario that
    reads its header via polling, and (confirmed with a temporary
    firmware breadcrumb) occasionally true even for the RX-interrupt
    path under real host/QEMU scheduling variance. Fixed by pacing
    multi-byte writes on the host side instead of papering over it with
    a longer timeout.
  - A command/interrupt race in the random mask-stress scenario:
    enabling the RX interrupt mid-sequence made every *subsequent*
    header byte (still being read by polling, in the same loop) race
    the newly-armed ISR for the same incoming byte -- reliably
    corrupting any sequence containing "enable then disable" (`"ED"`).
    Fixed by reading the whole step sequence via polling first, then
    executing it in a second pass with the interrupt mask untouched
    until parsing is done.
- **An earlier design for self-generated stimulus (UART loopback mode)
  was abandoned, not fixed.** Looping TX back to RX internally seemed
  like a clean way to avoid host/firmware timing races, but introduced
  a *different* one (toggling loopback off before the internal latch
  settled silently lost the byte) that was just as timing-dependent and
  harder to reason about. Every scenario now uses one consistent,
  proven pattern instead: a real host-sent byte, gated by an explicit
  ready handshake. Simpler, and it's the pattern that's actually been
  exercised hundreds of times across this README's test runs.
- **One occasional "finding" is left in, on purpose.**
  `nested_priority` sometimes reports that no SysTick tick landed inside
  the UART handler's window (`priority_not_honored`), even though the
  priorities are programmed correctly. This reflects genuine timing
  alignment between a fixed tick period and a fixed handler duration,
  not a logic bug -- and surfacing it rather than suppressing it is the
  point of the triage/coverage model.
- **What's simplified:** `mask_stress` tests one trailing probe byte
  against a random enable/disable/wait sequence, rather than injecting
  a byte at an arbitrary point mid-sequence. An earlier design tried the
  latter via loopback and ran into the issue above; this scope cut was
  deliberate, to keep the result trustworthy rather than clever.
  SysTick tick counts reported by `directed`/`mask_stress` are
  informational, not asserted exactly -- QEMU's TCG-mode timing isn't
  cycle-accurate wall-clock, so an oracle that demanded an exact tick
  count would be testing QEMU's scheduler, not the firmware.

## Layout

```
firmware/   bare-metal C: regs.h, startup.c, main.c, stellaris.ld, Makefile
fabric/     host package: protocol.py, soc.py, coverage.py,
            random_gen.py, triage.py, report.py, cli.py
tests/
  unit/        fast, pure-Python, no QEMU (49 tests)
  integration/ real QEMU boots, marked `qemu` (10 tests)
```

## The four scenarios

| Command | What it exercises |
|---|---|
| `directed_uart_timer` (`D`) | UART0 RX interrupt counting while SysTick runs concurrently -- directed: host picks exactly N stimulus bytes. |
| `gpio_during_burst` (`G`) | GPIO Port A toggled N times, read back each time -- a plain polled-peripheral sanity check. |
| `nested_priority` (`N`) | SysTick programmed to a higher NVIC priority than UART0; does a tick actually preempt a deliberately slow UART handler? |
| `mask_stress` (`M`) | Constrained-random: a random sequence of enable/disable/wait-for-tick steps, then one trailing probe byte -- does its fate match what the sequence predicts? |

## Running it

```bash
cd firmware && make                      # arm-none-eabi-gcc + qemu-system-arm required
cd ..
python3 -m fabric.cli run --directed 5
python3 -m fabric.cli run --gpio 5 --nested
python3 -m fabric.cli run --mask-stress EDT
python3 -m fabric.cli run --random 60 --seed 7
```

## Tests

```bash
pip install pytest --break-system-packages
python3 -m pytest tests/unit -q           # fast, no QEMU, 49 tests
python3 -m pytest tests/integration -q -m qemu   # real QEMU boots, 10 tests
python3 -m pytest tests -q                # both, 59 tests
```
