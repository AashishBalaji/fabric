/* Linker script for the lm3s6965evb as QEMU models it: 256K flash at 0,
 * 64K SRAM at 0x20000000. */
MEMORY
{
    FLASH (rx) : ORIGIN = 0x00000000, LENGTH = 256K
    SRAM  (rwx): ORIGIN = 0x20000000, LENGTH = 64K
}

SECTIONS
{
    .isr_vector : { KEEP(*(.isr_vector)) } > FLASH

    .text : {
        *(.text*)
        *(.rodata*)
    } > FLASH

    _sidata = LOADADDR(.data);
    .data : {
        _sdata = .;
        *(.data*)
        _edata = .;
    } > SRAM AT> FLASH

    .bss : {
        _sbss = .;
        *(.bss*)
        *(COMMON)
        _ebss = .;
    } > SRAM

    . = ALIGN(8);
    _estack = ORIGIN(SRAM) + LENGTH(SRAM);
}
