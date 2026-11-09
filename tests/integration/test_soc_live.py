"""Tests that actually boot qemu-system-arm and talk to the real firmware
over its emulated UART. Slower and occasionally subject to real
scheduling variance in a shared/sandboxed host (see soc.py's generous
timeouts) -- but these are the tests that caught every real bug this
project found: the GPIO register-offset bug, the directed-scenario
enable race, the UART holding-register overrun under bursty writes, and
the mask_stress command/interrupt race. Pure-Python unit tests cannot
catch any of those; only running the real thing can.
"""
import pytest

from fabric import protocol as proto
from fabric.soc import Soc


@pytest.fixture
def soc():
    s = Soc()
    yield s
    s.close()


@pytest.mark.qemu
def test_directed_counts_exactly_what_was_sent(soc):
    r = soc.run_directed(5)
    assert r.rx_count == 5


@pytest.mark.qemu
def test_gpio_toggle_has_no_faults(soc):
    r = soc.run_gpio(6)
    assert r.fault == 0
    assert r.ok == 2 * 6


@pytest.mark.qemu
def test_nested_priority_handler_runs(soc):
    r = soc.run_nested()
    assert r.uart_handler_ran


@pytest.mark.qemu
@pytest.mark.parametrize("steps", ["D", "E", "ED", "DE", "EDT", "DDEE"])
def test_mask_stress_matches_its_own_prediction(soc, steps):
    r = soc.run_mask_stress(steps)
    assert r.probe_was_counted == proto.final_mask_state(steps)


@pytest.mark.qemu
def test_a_batch_of_scenarios_on_one_boot_all_complete(soc):
    # Regression coverage for the two real bugs that only showed up
    # across multiple scenarios sharing one boot: a leftover selector
    # EOF/timeout mixup, and mask_stress's command/interrupt race.
    assert soc.run_directed(2).rx_count == 2
    assert soc.run_gpio(2).fault == 0
    assert soc.run_nested().uart_handler_ran
    assert soc.run_mask_stress("ED").probe_was_counted is False
