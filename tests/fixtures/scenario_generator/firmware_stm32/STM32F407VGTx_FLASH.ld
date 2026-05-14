/* fixture for firmware_stm32 — minimal linker script that satisfies
   the primary_globs **/STM32*.ld fingerprint. Real CubeIDE linker
   scripts are far longer; this is enough to trigger detection. */

MEMORY {
    FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 1024K
    RAM (rwx)  : ORIGIN = 0x20000000, LENGTH = 128K
}

ENTRY(Reset_Handler)
