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
$ python3 -m fabric.cli run --random 60 --seed 7 --fresh-coverage
============================================================
Fabric run report
============================================================
Total scenario runs: 60
Findings: 6

Coverage closure: 78%
Uncovered buckets (4):
  - gpio/n=small
  - mask_stress/len=tiny/final=enabled/matches_prediction
  - nested/ticks_inside=medium
  - nested/uart_handler_did_not_fire

Failure clusters (by signature):
  [6x] priority_not_honored
      e.g. log=(1, 2)
      root cause: The UART handler ran, but no SysTick interrupt fired during it...
```
This is a real, unedited run (not cherry-picked), but it's illustrative, not
reproducible verbatim: `--seed 7` makes the *stimulus* deterministic, not the
real QEMU timing each run interacts with, so a re-run with the exact same
command gets a different closure percentage and finding count (seeds 1-3
measured at closures of 83%/94%/78% and 10/7/3 findings, for reference) --
see "One finding is left in, on purpose" below for why `priority_not_honored`
fires on a real minority of `nested_priority` runs rather than being
suppressed or treated as flaky. That run-to-run variance is expected under
real QEMU timing, not a sign something's broken. What should stay true, and was measured rather than
assumed: across 30 consecutive `--nested` runs plus 42 `--mask-stress` runs
on sequences that specifically end with the RX interrupt armed (the case
most likely to expose a race), 0 timed out and the UART handler ran every
time -- see "A second, more severe race was still here" below for what
changed to get there.

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
  - A nested-priority exit-condition bug that was still here after the
    above: `scenario_nested()` used to exit as soon as 4 log entries had
    been recorded, on the assumption that meant "UART entered and
    exited, with SysTick nested inside." But SysTick fires continuously
    at a fixed period, so two ordinary tick enter/exit pairs could
    satisfy `log_len >= 4` before the UART interrupt had fired at all --
    on a majority of runs, not occasionally. Fixed by exiting on an
    explicit `g_uart_exit_seen` flag set only by the UART-exit log code,
    so the scenario actually waits for what it claims to measure.
  - A wrong UART baud divisor: `IBRD=2, FBRD=45` was programmed for
    115200 baud at a 6 MHz UARTCLK, which is off by about 20% from the
    correct `IBRD=3, FBRD=16` (`BRD = 6,000,000 / (16 * 115200) =
    3.2552`). QEMU's `lm3s6965evb` model doesn't emulate bit-level UART
    timing, so this had zero effect on any test result under emulation
    -- it's fixed here because it would matter on real silicon, and
    leaving an identifiably wrong divisor in "working" firmware is its
    own kind of bug.
  - A silently-swallowed timeout in `mask_stress`'s `'T'` (wait-for-tick)
    step: if a tick never arrived within budget, the firmware fell
    through and reported as if it had. Fixed by tracking and reporting
    `tick_wait_timeouts` as a 4th wire field, so the host can tell "a
    tick arrived" apart from "we gave up waiting" instead of silently
    treating them the same.
- **A second, more severe race was still here after the exit-condition
  fix above: `nested_priority` and `mask_stress`'s trailing probe were
  polling `uart_getc()` in the foreground for the exact same byte the
  just-armed RX interrupt was also listening for.** This is the same
  command/interrupt race class already fixed for `mask_stress`'s step
  sequence (above), reintroduced in two other places. The ISR almost
  always won the race, drained the byte, and left the foreground's
  `uart_getc()` poll spinning on an already-empty holding register
  forever, bounded only by the host's process-level timeout -- a real,
  reproducible hang, not a cosmetic issue: a second independent review
  measured this hanging 3 of 4 runs of this project's own integration
  test suite before the fix. Fixed by not polling for that byte at all
  when the interrupt is armed for it -- `nested_priority` already waits
  on `g_uart_exit_seen`, and `mask_stress` now tracks whether its last
  step left the mask enabled and waits on the ISR-driven `g_rx_count`
  instead of `uart_getc()` in that case. A related issue surfaced at
  the same time: the 8-entry event log for `nested_priority` was
  usually saturated by ordinary pre-UART SysTick tick pairs (SysTick
  starts well before the host's trigger byte physically arrives over
  the pipe), truncating away the UART-exit marker the nested-tick count
  depends on -- measured at well under 1-in-30 runs ever reporting a
  nonzero nested-tick count, even on runs where the handler ran
  successfully. Fixed by only logging SysTick events while the UART
  handler's busy-loop is actually executing, so the log's 8 slots are
  spent on the window that matters instead of irrelevant background
  ticks. Both fixes were verified empirically (30 `--nested` runs, 42
  `--mask-stress` runs on interrupt-armed-ending sequences), not just
  reasoned about -- see the run output above.
- **A third review round, specifically re-testing the race fix above
  under adversarial load, found a related latent bug it hadn't yet
  triggered:** `scenario_mask_stress`'s step-sequence buffer was sized
  at 64 bytes while the wire protocol (`encode_mask_stress`) permits
  sequences up to 255 -- a sequence over 64 steps got silently
  truncated firmware-side while the host still wrote the full sequence
  onto the wire, leaving the untruncated tail sitting unread in the
  pipe. Whatever ran next on the same boot then misread those leftover
  bytes as its own stimulus -- not just a wrong `mask_stress` result,
  but a 100%-reproducible UART stream desync that hung every later
  scenario on that boot. The project's own `--random` generator never
  exercised this (it caps sequences at 8 steps), so it had stayed
  latent through two prior review rounds. Fixed by sizing the buffer
  to the protocol's actual declared limit (255) instead of an
  arbitrary smaller number -- the same lesson as the race fixed above,
  one level down: a capacity enforced in code that's smaller than the
  capacity promised by the protocol is a quieter version of the same
  mistake.
- **An earlier design for self-generated stimulus (UART loopback mode)
  was abandoned, not fixed.** Looping TX back to RX internally seemed
  like a clean way to avoid host/firmware timing races, but introduced
  a *different* one (toggling loopback off before the internal latch
  settled silently lost the byte) that was just as timing-dependent and
  harder to reason about. Every scenario now uses one consistent,
  proven pattern instead: a real host-sent byte, gated by an explicit
  ready handshake. Simpler, and it's the pattern that's actually been
  exercised hundreds of times across this README's test runs.
- **One finding is left in, on purpose.** `nested_priority` sometimes
  reports that no SysTick tick landed inside the UART handler's window
  (`priority_not_honored`), even though the priorities are programmed
  correctly and the handler now reliably runs (see the exit-condition
  fix above). This reflects genuine timing alignment between a fixed
  tick period and a fixed handler duration, not a logic bug -- and
  surfacing it rather than suppressing it is the point of the
  triage/coverage model. What changed: before the exit-condition fix,
  the scenario mostly didn't even measure this honestly (it exited
  before the UART handler had necessarily run at all); after the fix,
  it reliably measures the real thing, and that real thing has genuine
  run-to-run variance.
- **Coverage is a persistent campaign metric, not a per-call snapshot.**
  `CoverageModel` loads from and saves to `~/.fabric_coverage.json` by
  default, so closure accumulates across separate invocations the way
  it would in a real regression campaign -- running the same command
  twice doesn't produce two unrelated percentages with no memory of
  each other. Pass `--fresh-coverage` to opt out and report closure for
  that invocation alone (used for this README's reproducible examples).
  Known limitation, disclosed rather than silently assumed away: `load()`/
  `save()` is a plain read-then-overwrite with no locking, so two `fabric
  run` invocations active at the same time can race and one's save can
  clobber the other's -- fine for the single-operator, run-one-at-a-time
  use this is built for, not safe for concurrent campaigns without adding
  real file locking first.
- **The random generator is actually constrained, not just uniform.**
  `--random` biases toward boundary values (`n` at its min/max,
  min/max-length mask sequences) and forces known bug-triggering corner
  cases (an `"ED"`/`"DE"` adjacency) a meaningful fraction of the time,
  rather than sampling uniformly and hoping corner cases show up by
  luck. The directed/gpio bucket universes were also widened to
  `tiny`/`small`/`medium`/`large` to match the generator's actual
  `1..12` range -- they used to stop at `medium` (`n<=8`), so roughly a
  third of generated stimulus was silently invisible to `closure()`.
- **What's simplified:** `mask_stress` tests one trailing probe byte
  against a random enable/disable/wait sequence, rather than injecting
  a byte at an arbitrary point mid-sequence. An earlier design tried the
  latter via loopback and ran into the issue above; this scope cut was
  deliberate, to keep the result trustworthy rather than clever.
  SysTick tick counts reported by `directed`/`mask_stress` are
  informational, not asserted exactly -- QEMU's TCG-mode timing isn't
  cycle-accurate wall-clock, so an oracle that demanded an exact tick
  count would be testing QEMU's scheduler, not the firmware.
- **What QEMU can't validate here, disclosed rather than implied away:**
  `lm3s6965evb` under TCG doesn't model bit-level UART timing (the wrong
  baud divisor above was invisible to every test for exactly this
  reason), bus-protocol-level AMBA/AHB compliance, power states, or
  anything DFT/bring-up related (scan chains, boundary scan, JTAG).
  This project validates functional register-level behavior and
  interrupt semantics against a software model of the SoC -- real
  value for exactly that layer, and a real gap versus what silicon
  validation also has to cover. The name "Fabric" refers to the
  project's scope (tying firmware, interrupts, and a host test
  framework together), not a claim of testing an actual on-chip
  interconnect -- there isn't one here; it's a single peripheral set on
  one core.
- **A batch of scenarios no longer dies silently on a timeout.** An
  earlier CLI let a QEMU/protocol timeout propagate as an unhandled
  traceback mid-batch, discarding every result already gathered. It
  now catches `SocTimeoutError`/`ProtocolError`, records it as an
  `infra_error` finding (distinct from an oracle mismatch -- it's a run
  failing, not a result disagreeing), and stops the batch rather than
  running further scenarios on a boot whose UART stream may now be
  desynced.

## Layout

```
firmware/   bare-metal C: regs.h, startup.c, main.c, stellaris.ld, Makefile
fabric/     host package: protocol.py, soc.py, coverage.py,
            random_gen.py, triage.py, report.py, cli.py
tests/
  unit/        fast, pure-Python, no QEMU (55 tests)
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
python3 -m fabric.cli run --random 60 --seed 7   # accumulates in ~/.fabric_coverage.json
python3 -m fabric.cli run --random 60 --seed 7 --fresh-coverage   # one-off, no persistence
```

## Tests

```bash
pip install pytest --break-system-packages
python3 -m pytest tests/unit -q           # fast, no QEMU, 55 tests
python3 -m pytest tests/integration -q -m qemu   # real QEMU boots, 10 tests
python3 -m pytest tests -q                # both, 65 tests
```
