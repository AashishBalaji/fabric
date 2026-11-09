/* Minimal Cortex-M3 startup: vector table + reset handler. No CMSIS, no
 * vendor HAL -- this project's whole point is validating real IP
 * interaction at the register level, not hiding it behind a framework. */
#include <stdint.h>

extern uint32_t _estack;
extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss;

void Reset_Handler(void);
void Default_Handler(void);
void SysTick_Handler(void);
void UART0_Handler(void);
int main(void);

__attribute__((used, section(".isr_vector")))
void (*const vector_table[])(void) = {
    (void (*)(void))&_estack, /* [0] initial MSP */
    Reset_Handler,            /* [1] */
    Default_Handler,          /* [2] NMI */
    Default_Handler,          /* [3] HardFault */
    Default_Handler, Default_Handler, Default_Handler, Default_Handler, /* 4-7 (reserved/MemManage/BusFault/UsageFault on M3, unused here) */
    Default_Handler, Default_Handler, Default_Handler,                  /* 8-10 reserved */
    Default_Handler,          /* [11] SVCall */
    Default_Handler, Default_Handler, /* 12-13 reserved/DebugMon */
    Default_Handler,          /* [14] PendSV */
    SysTick_Handler,          /* [15] SysTick */
    Default_Handler, Default_Handler, Default_Handler, Default_Handler, Default_Handler, /* IRQ0-4: GPIOA..GPIOE */
    UART0_Handler,            /* [21] IRQ5: UART0 */
};

void Default_Handler(void) {
    for (;;) { }
}

void Reset_Handler(void) {
    uint32_t *src = &_sidata, *dst = &_sdata;
    while (dst < &_edata) { *dst++ = *src++; }
    for (dst = &_sbss; dst < &_ebss; dst++) { *dst = 0; }
    main();
    for (;;) { }
}
