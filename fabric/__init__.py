"""Fabric: a QEMU-hosted SoC functional validation framework.

Boots real Cortex-M3 firmware under qemu-system-arm and drives it over its
emulated UART to exercise cross-IP interaction (UART0 RX interrupts,
SysTick, GPIO, NVIC priority) -- directed tests, constrained-random
stimulus, coverage tracking, and failure triage, all against a genuinely
running target rather than a simulated stand-in for one.
"""

__version__ = "0.1.0"
