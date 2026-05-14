/* fixture for firmware_baremetal — generic Cortex-M linker script.
   The primary_content fingerprint for firmware_baremetal requires
   MEMORY, .text, and .bss substrings to appear in a **/*.ld file.
   The STM32-specific naming pattern (STM32*.ld) is deliberately
   avoided so this fixture doesn't accidentally trip firmware_stm32. */

MEMORY {
    FLASH (rx) : ORIGIN = 0x00000000, LENGTH = 256K
    RAM (rwx)  : ORIGIN = 0x20000000, LENGTH = 64K
}

ENTRY(Reset_Handler)

SECTIONS {
    .text : {
        KEEP(*(.vectors))
        *(.text*)
    } > FLASH

    .bss : {
        *(.bss*)
    } > RAM
}
