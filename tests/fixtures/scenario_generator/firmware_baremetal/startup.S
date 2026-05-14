/* fixture for firmware_baremetal — minimal Cortex-M startup file.
   The primary_globs fingerprint matches **/startup.S exactly.
   The disambiguator content matches `_start:` / `Reset_Handler:`. */

    .syntax unified
    .cpu cortex-m4
    .thumb

    .section .vectors, "a", %progbits
    .word   _estack
    .word   Reset_Handler
    .word   NMI_Handler
    .word   HardFault_Handler

    .section .text._start, "ax", %progbits
    .global _start
_start:
    b       Reset_Handler

    .section .text.Reset_Handler, "ax", %progbits
    .global Reset_Handler
    .type   Reset_Handler, %function
Reset_Handler:
    bl      main
    b       .
