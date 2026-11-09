/* Fabric firmware: a bare-metal Cortex-M3 program exercising real
 * cross-IP interaction (UART0, SysTick, GPIO Port A, NVIC priority) on
 * QEMU's lm3s6965evb, dispatched by one-byte scenario commands sent over
 * the emulated serial link. The host (fabric/soc.py) is the only thing
 * that knows what "pass" means for a given run -- this firmware just
 * executes exactly what it's told and reports counters honestly,
 * including when that reveals something the host's oracle didn't expect
 * (a lost or delayed interrupt is a genuine finding, not something this
 * firmware tries to paper over).
 *
 * Every scenario that needs a UART "receive" event uses a real,
 * host-sent byte over the actual RX line, gated by an explicit 'R'
 * ready handshake printed once the firmware has actually enabled
 * whatever it needs enabled. An earlier version tried generating
 * stimulus bytes internally via the UART's loopback mode (CTL bit 7)
 * to avoid host/firmware timing races -- that turned out to race
 * QEMU's internal TX-to-RX latch instead (toggling loopback back off
 * too soon after the write silently lost the byte, with no error, in a
 * way that was still timing-dependent and just as hard to reason
 * about). The handshake-plus-real-byte approach proved reliable across
 * repeated runs for the directed scenario, so every scenario uses it
 * now, and nothing here depends on loopback mode at all.
 */
#include <stdint.h>
#include "regs.h"

/* ---- polled UART helpers: the control-plane path. Used for every byte
 * that selects a scenario or carries its parameters, so those are always
 * delivered regardless of what a scenario does to the RX interrupt mask. */
static void uart_init(void) {
    UART0_CTL = 0;
    /* BRD = UARTCLK / (16 * baud) = 6,000,000 / (16 * 115200) = 3.2552,
     * so IBRD=3, FBRD=round(0.2552*64)=16. An earlier IBRD=2/FBRD=45
     * was off by ~20% (BRD=2.7031 -> ~138.7kbaud) -- undetectable by
     * this harness since QEMU's UART model doesn't emulate bit-level
     * timing at all, which is itself a real limitation of this
     * methodology worth disclosing rather than leaving silently wrong. */
    UART0_IBRD = 3; UART0_FBRD = 16; /* 115200 @ 6MHz UARTCLK */
    UART0_LCRH = (3 << 5); /* 8N1, no FIFO */
    UART0_CTL = UART_CTL_UARTEN | UART_CTL_TXE | UART_CTL_RXE;
}

static void uart_putc(char c) {
    while (UART0_FR & UART_FR_TXFF) { }
    UART0_DR = (uint32_t)c;
}

static void uart_puts(const char *s) {
    while (*s) { uart_putc(*s++); }
}

static void uart_put_u32(uint32_t v) {
    char buf[11]; int i = 10; buf[10] = 0;
    if (v == 0) { uart_putc('0'); return; }
    while (v && i > 0) { buf[--i] = (char)('0' + (v % 10)); v /= 10; }
    uart_puts(&buf[i]);
}

static char uart_getc(void) {
    while (UART0_FR & UART_FR_RXFE) { }
    return (char)UART0_DR;
}

/* ---- SysTick ---- */
static volatile uint32_t g_tick_count = 0;
static volatile uint8_t g_nested_mode = 0;
/* Event log for the nested-priority scenario. Codes: 1=UART enter,
 * 2=UART exit, 3=SysTick enter, 4=SysTick exit. */
static volatile uint8_t g_log[8];
static volatile uint32_t g_log_len = 0;

static volatile uint8_t g_uart_exit_seen = 0;
/* True only while the UART handler's long busy-loop is actually running
 * -- gates whether SysTick logs itself below. Without this, SysTick
 * fires every 1500 cycles starting the moment systick_start() runs,
 * well before the host's trigger byte has even arrived over the
 * pipe (real round-trip latency, not firmware-controlled) -- so the
 * 8-entry g_log filled up with ordinary pre-UART tick pairs almost
 * every run, truncating away the UART_EXIT marker that
 * ticks_nested_inside_uart_handler actually depends on. Measured:
 * fewer than 1 in 30 runs ever reported a nonzero nested-tick count
 * as a result, even on runs where the UART handler ran successfully --
 * the scenario was rarely demonstrating the thing it exists to
 * measure. Only logging ticks that land during the UART handler's
 * actual window fixes that without touching the log's size. */
static volatile uint8_t g_uart_active = 0;

static void log_event(uint8_t code) {
    if (g_log_len < 8) { g_log[g_log_len++] = code; }
    if (code == 2) { g_uart_exit_seen = 1; } /* 2 = UART exit, see comment above */
}

void SysTick_Handler(void) {
    g_tick_count++;
    if (g_nested_mode && g_uart_active) {
        log_event(3);
        /* A deliberately short busy-loop so this handler has nonzero
         * duration to preempt INTO -- long enough to be observable,
         * short enough that the bounded spin budgets elsewhere don't
         * need to be huge. */
        for (volatile uint32_t i = 0; i < 200; i++) { }
        log_event(4);
    }
}

static void systick_start(uint32_t reload) {
    SYST_LOAD = reload;
    SYST_VAL = 0;
    SYST_CTRL = SYST_CTRL_CLKSRC | SYST_CTRL_TICKINT | SYST_CTRL_ENABLE;
}

static void systick_stop(void) {
    SYST_CTRL = 0;
}

/* ---- UART0 RX interrupt path: the device-under-test path, distinct
 * from the polled control-plane helpers above. ---- */
static volatile uint32_t g_rx_count = 0;

void UART0_Handler(void) {
    if (UART0_MIS & UART_MIS_RXMIS) {
        (void)UART0_DR; /* drain the byte */
        UART0_ICR = UART_ICR_RXIC;
        g_rx_count++;
        if (g_nested_mode) {
            log_event(1);
            g_uart_active = 1;
            /* A long busy-loop standing in for "a slow handler" -- long
             * enough that, if SysTick's higher priority is actually
             * honored, a tick lands and fully preempts somewhere in
             * here rather than queuing behind this handler's return. */
            for (volatile uint32_t i = 0; i < 20000; i++) { }
            g_uart_active = 0;
            log_event(2);
        }
    }
}

/* DSB/ISB after NVIC_ISER0/ICER0: an enable/disable write to NVIC isn't
 * guaranteed to be visible to the core's interrupt logic immediately on
 * a Cortex-M (it's a memory-mapped write, not an instruction) -- the
 * ARMv7-M architecture reference explicitly calls out needing a barrier
 * if subsequent code depends on the new state taking effect. QEMU's TCG
 * mode happens not to expose the gap this is standard hygiene against,
 * which is exactly why it's easy to leave out and still pass every test
 * here; real silicon is not guaranteed to be that forgiving. */
static void uart_irq_enable(void) {
    UART0_IM |= UART_IM_RXIM;
    NVIC_ISER0 = (1u << UART0_IRQ);
    __asm__ volatile ("dsb");
    __asm__ volatile ("isb");
}

static void uart_irq_disable(void) {
    NVIC_ICER0 = (1u << UART0_IRQ);
    __asm__ volatile ("dsb");
    __asm__ volatile ("isb");
    UART0_IM &= ~UART_IM_RXIM;
}

/* ---- GPIO Port A, output only ----
 * Stellaris GPIO aliases GPIODATA across offsets 0x000-0x3FC, using
 * address bits [9:2] as a per-access bit mask; regs.h's GPIOA_DATA
 * already points at the unmasked 0x3FC alias (see its comment -- the
 * first QEMU run caught a 0x000 alias there as a silent no-op). */
static void gpio_init(void) {
    GPIOA_DIR |= 0x01u;
    GPIOA_DEN |= 0x01u;
    GPIOA_DATA &= ~0x01u;
}

/* ================= scenario: 'D' directed_uart_timer ================= */
static void scenario_directed(void) {
    uint8_t n = (uint8_t)uart_getc();
    g_rx_count = 0; g_tick_count = 0;
    systick_start(20000); /* fires often enough to see several ticks per run */
    uart_irq_enable();
    /* Explicit ready handshake: without a hardware RX FIFO, a stimulus
     * byte that arrives before this enable takes effect is simply never
     * seen by the ISR (an early run undercounted 3 bytes as 1, for
     * exactly this reason). The host waits for 'R' before writing its N
     * stimulus bytes, closing the race instead of just reporting it. */
    uart_putc('R');
    /* No spin budget here on purpose: the host always sends exactly n
     * bytes after seeing 'R', and a fixed iteration-count budget raced
     * against real host round-trip latency (QEMU's busy-loop runs far
     * faster than the host can write over the pipe, so an early version
     * of this gave up before the bytes even arrived). The host's own
     * process-level timeout is the real safety net if it ever doesn't. */
    while (g_rx_count < n) { }
    uart_irq_disable();
    systick_stop();
    uart_puts("D "); uart_put_u32(g_rx_count); uart_putc(' ');
    uart_put_u32(g_tick_count); uart_putc('\n');
}

/* ================= scenario: 'G' gpio_during_burst ===================== */
static void scenario_gpio(void) {
    uint8_t n = (uint8_t)uart_getc();
    uint32_t ok = 0, fault = 0;
    for (uint8_t i = 0; i < n; i++) {
        GPIOA_DATA |= 0x01u;
        if (GPIOA_DATA & 0x01u) { ok++; } else { fault++; }
        uart_putc((char)('A' + (i % 26)));
        GPIOA_DATA &= ~0x01u;
        if (!(GPIOA_DATA & 0x01u)) { ok++; } else { fault++; }
    }
    uart_puts("G "); uart_put_u32(ok); uart_putc(' ');
    uart_put_u32(fault); uart_putc('\n');
}

/* ================= scenario: 'N' nested_priority =======================
 * One real byte from the host, sent only after seeing 'R', triggers the
 * UART handler; its deliberately long busy-loop gives SysTick (set to
 * the numerically-lower = higher priority) room to preempt into it at
 * least once before it returns, which is the entire point of this
 * scenario. */
static void scenario_nested(void) {
    g_log_len = 0;
    g_uart_exit_seen = 0;
    g_uart_active = 0;
    g_tick_count = 0;
    SCB_SHPR3 = (SCB_SHPR3 & 0x00FFFFFFu) | (0x00u << 24); /* SysTick byte = 0x00 (high prio) */
    NVIC_IPR1 = (NVIC_IPR1 & 0xFFFF00FFu) | (0xE0u << 8);  /* UART0 byte = 0xE0 (low prio) */
    g_nested_mode = 1;
    systick_start(1500); /* short reload: a tick should land mid-way through the long UART handler loop above */
    uart_irq_enable();
    uart_putc('R');
    /* Do NOT poll uart_getc() here for the host's trigger byte: the RX
     * interrupt is already armed above, listening for this exact same
     * byte. An earlier version did `uart_getc()` right here, which
     * raced the newly-armed ISR for who drains UART0_DR -- the ISR
     * almost always won (it preempts the tight polling loop as soon as
     * the byte arrives), leaving uart_getc()'s RXFE-poll spinning
     * forever on a register the ISR had already emptied. Confirmed:
     * this hung the scenario outright on a large fraction of runs, not
     * merely misreported it -- the same command/interrupt race class
     * already fixed in mask_stress below, reintroduced here. The byte
     * is simply left for the ISR; g_uart_exit_seen below already
     * encodes "the byte arrived and the handler ran to completion." */
    /* Wait specifically for the UART handler to actually RUN AND EXIT
     * (log code 2), not just for 4 log entries of any kind. The
     * previous `while (g_log_len < 4)` was a real bug: SysTick alone
     * (higher priority, firing every 1500 cycles) can produce 4 log
     * entries -- two full tick enter/exit pairs -- before the UART
     * interrupt ever fires at all, satisfying the old exit condition
     * and making the scenario misreport "no nesting" or even "handler
     * never fired", independent of whether the thing being tested
     * (priority preemption) actually happened. Confirmed: this made
     * the scenario fail on the majority of runs, not occasionally.
     * Bounded by a generous spin budget so a genuine "UART interrupt
     * never fired" case still terminates and is reported honestly. */
    uint32_t spin_budget = 20000000;
    while (!g_uart_exit_seen && spin_budget--) { }
    uart_irq_disable();
    systick_stop();
    g_nested_mode = 0;
    uart_puts("N ");
    for (uint32_t i = 0; i < g_log_len; i++) {
        uart_put_u32(g_log[i]);
        uart_putc(' ');
    }
    uart_putc('\n');
}

/* ================= scenario: 'M' mask_stress (random) ===================
 * The host sends a random sequence of k steps, each 'E' (enable RX
 * IRQ), 'D' (disable it), or 'T' (wait for the next SysTick tick) --
 * exercising arbitrary enable/disable/timing interleavings. Once the
 * sequence finishes, the firmware signals 'R' and the host sends exactly
 * one trailing byte over the real RX line; the report says whether it
 * was counted, which depends entirely on whatever mask state the random
 * sequence left behind. (An earlier design tried injecting a stimulus
 * byte at an arbitrary point *during* the sequence via loopback, self-
 * generated with no host involved; dropped in favor of this single,
 * well-defined trailing probe, which needs no loopback mode and reuses
 * the same proven ready-handshake pattern as every other scenario.) */
static void scenario_mask_stress(void) {
    uint8_t k = (uint8_t)uart_getc();
    /* Read the whole step sequence via polling BEFORE touching the RX
     * interrupt mask at all. An earlier version enabled/disabled the
     * IRQ step-by-step while still polling for the NEXT step byte in
     * the same loop -- the moment a step enabled the IRQ, the very
     * next header byte became a race between that poll and the
     * newly-armed ISR for the same incoming byte. Whichever won
     * determined whether a command byte got miscounted as stimulus,
     * desyncing the sequence (confirmed: any sequence containing "ED"
     * reliably left the probe counted even though the sequence should
     * have ended disabled). Reading everything up front, then acting
     * on it in a second pass with no further polling until the final
     * probe, removes the race entirely. */
    /* Sized to the wire protocol's actual limit (fabric/protocol.py's
     * encode_mask_stress permits up to 255 steps -- a uint8_t length
     * byte's full range), not an arbitrary smaller number. An earlier
     * version used a 64-byte buffer and silently truncated anything
     * longer: the host would still write its full (e.g. 200-byte)
     * sequence onto the wire, but the firmware only read back the
     * first 64 of those bytes here, leaving the rest sitting unread in
     * the pipe. Those leftover command bytes then got misread as
     * stimulus by whatever ran next on the same boot -- not merely a
     * wrong mask_stress result, but a permanently desynced UART stream
     * that hung every later scenario call too. Confirmed with
     * sequences over 64 bytes: 100% reproducible stream desync. Same
     * underlying lesson as the race fixed elsewhere in this function --
     * a buffer that's smaller than what the protocol actually allows
     * is just a quieter version of the same "don't let a declared
     * capacity and an enforced one drift apart" mistake. */
    char steps[255];
    uint8_t n = k;
    for (uint8_t i = 0; i < n; i++) { steps[i] = uart_getc(); }

    g_rx_count = 0; g_tick_count = 0;
    uint32_t tick_wait_timeouts = 0;
    uint8_t irq_armed = 0; /* mirrors the mask state the sequence leaves
                             * behind -- tracked here (not re-derived from
                             * UART0_IM) so the trailing probe below knows,
                             * without touching a register, whether the ISR
                             * is listening for the same byte it's about to
                             * wait for. */
    systick_start(6000);
    for (uint8_t i = 0; i < n; i++) {
        switch (steps[i]) {
            case 'E': uart_irq_enable(); irq_armed = 1; break;
            case 'D': uart_irq_disable(); irq_armed = 0; break;
            case 'T': { uint32_t before = g_tick_count;
                        uint32_t budget = 2000000;
                        while (g_tick_count == before && budget--) { }
                        /* An earlier version let this fall through
                         * silently on exhaustion, treating "gave up
                         * waiting" identically to "a tick actually
                         * arrived" -- exactly the kind of silent
                         * wrong-but-plausible result this project's
                         * own README warns against. Now it's counted
                         * and reported. */
                        if (g_tick_count == before) { tick_wait_timeouts++; }
                        break; }
            default: break; /* unrecognized command bytes are a no-op on purpose */
        }
    }
    uint32_t rx_before_probe = g_rx_count;
    uart_putc('R');
    if (irq_armed) {
        /* The RX interrupt is armed for this exact probe byte -- do not
         * poll uart_getc() here. An earlier version did, and that polling
         * read raced the armed ISR for who drains UART0_DR: the ISR
         * (correctly) almost always won, leaving uart_getc()'s RXFE-poll
         * spinning forever on an already-emptied register. Confirmed:
         * any sequence left enabled (e.g. just "E") hung on this line a
         * large fraction of the time -- exactly the same race class this
         * scenario's own header comment describes fixing for the step
         * sequence itself, reintroduced here for the trailing probe.
         * Wait on the ISR-driven counter instead, bounded so a probe that
         * genuinely never arrives still terminates and reports honestly. */
        uint32_t budget = 2000000;
        while (g_rx_count == rx_before_probe && budget--) { }
    } else {
        /* Mask is disabled: no ISR is listening for this byte, so it's
         * safe to poll for it directly -- there's no race to lose. */
        (void)uart_getc();
    }
    /* Give a pending-but-still-masked probe byte a moment to sit in the
     * holding register (matching real hardware: it arrived, it's just
     * not interrupt-driven), then read it ourselves if the ISR hasn't,
     * so the control channel stays clean for the next scenario command
     * either way. */
    for (volatile uint32_t i = 0; i < 20000; i++) { }
    if (!(UART0_FR & UART_FR_RXFE)) {
        (void)UART0_DR; /* was masked: drain without counting -- that's the finding */
    }
    uart_irq_disable();
    systick_stop();
    uart_puts("M "); uart_put_u32(g_rx_count); uart_putc(' ');
    uart_put_u32(g_tick_count); uart_putc(' ');
    uart_put_u32(tick_wait_timeouts); uart_putc('\n');
}

int main(void) {
    uart_init();
    gpio_init();
    for (;;) {
        char cmd = uart_getc();
        switch (cmd) {
            case 'D': scenario_directed(); break;
            case 'G': scenario_gpio(); break;
            case 'N': scenario_nested(); break;
            case 'M': scenario_mask_stress(); break;
            default: break;
        }
    }
}
