/* Register map for the peripherals this firmware touches, on the TI
 * Stellaris LM3S6965EVB (Cortex-M3) as modeled by QEMU's `lm3s6965evb`
 * machine. Two different trust levels here on purpose:
 *
 *  - SysTick and NVIC are part of the ARMv7-M core itself (CMSIS-standard
 *    addresses, identical on every Cortex-M3), not board-specific -- the
 *    safest registers to build on.
 *  - UART0 and GPIO Port A are the Stellaris peripheral block's own
 *    registers, at the addresses TI's datasheet (and every QEMU
 *    lm3s6965evb bare-metal example) uses.
 */
#ifndef FABRIC_REGS_H
#define FABRIC_REGS_H

#include <stdint.h>

#define REG32(addr) (*(volatile uint32_t *)(addr))

/* --- UART0 (Stellaris peripheral, IRQ 5) ------------------------------ */
#define UART0_BASE 0x4000C000u
#define UART0_DR   REG32(UART0_BASE + 0x000)
#define UART0_FR   REG32(UART0_BASE + 0x018)
#define UART0_IBRD REG32(UART0_BASE + 0x024)
#define UART0_FBRD REG32(UART0_BASE + 0x028)
#define UART0_LCRH REG32(UART0_BASE + 0x02C)
#define UART0_CTL  REG32(UART0_BASE + 0x030)
#define UART0_IM   REG32(UART0_BASE + 0x038)
#define UART0_MIS  REG32(UART0_BASE + 0x040)
#define UART0_ICR  REG32(UART0_BASE + 0x044)

#define UART_FR_TXFF (1u << 5)
#define UART_FR_RXFE (1u << 4)
#define UART_CTL_UARTEN (1u << 0)
#define UART_CTL_TXE    (1u << 8)
#define UART_CTL_RXE    (1u << 9)
#define UART_IM_RXIM    (1u << 4)
#define UART_MIS_RXMIS  (1u << 4)
#define UART_ICR_RXIC   (1u << 4)

/* --- GPIO Port A (Stellaris peripheral) -- used as an output only -----
 * Stellaris GPIO aliases GPIODATA across offsets 0x000-0x3FC, using
 * address bits [9:2] as a per-access bit MASK (so e.g. offset 0x004
 * only exposes/affects bit 0). Offset 0x000 means mask=0x00 -- touches
 * NO pins. The full, unmasked register is the one at 0x3FC. Using
 * 0x000 here originally made every DATA read/write a silent no-op,
 * which is exactly what the first QEMU run caught (a 5-ok/5-fault
 * split on a plain toggle instead of 10/0). */
#define GPIOA_BASE 0x40004000u
#define GPIOA_DATA REG32(GPIOA_BASE + 0x3FC)
#define GPIOA_DIR  REG32(GPIOA_BASE + 0x400)
#define GPIOA_DEN  REG32(GPIOA_BASE + 0x51C)

/* --- SysTick (ARMv7-M core, exception 15) ------------------------------ */
#define SYSTICK_BASE 0xE000E010u
#define SYST_CTRL REG32(SYSTICK_BASE + 0x00)
#define SYST_LOAD REG32(SYSTICK_BASE + 0x04)
#define SYST_VAL  REG32(SYSTICK_BASE + 0x08)

#define SYST_CTRL_ENABLE   (1u << 0)
#define SYST_CTRL_TICKINT  (1u << 1)
#define SYST_CTRL_CLKSRC   (1u << 2)
#define SYST_CTRL_COUNTFLAG (1u << 16)

/* --- NVIC (ARMv7-M core) ------------------------------------------------ */
#define NVIC_ISER0 REG32(0xE000E100u)
#define NVIC_ICER0 REG32(0xE000E180u)
#define NVIC_IPR1  REG32(0xE000E404u) /* covers IRQ4..7; UART0=IRQ5 is byte 1 */
#define SCB_SHPR3  REG32(0xE000ED20u) /* covers exceptions 12..15; SysTick=15 is byte 3 */

#define UART0_IRQ 5

#endif
