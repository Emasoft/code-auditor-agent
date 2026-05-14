// Fixture: a minimal baremetal firmware app exercising the entry-point
// kinds the firmware_baremetal discoverer recognises.
//
// The disambiguator content requires _start, Reset_Handler, AND
// `void __attribute__((interrupt))` to appear in a **/*.c file —
// every keyword is present below.

#include <stdint.h>

extern uint32_t _estack;

// Reset_Handler — C-side reset entry referenced from the asm startup.
// Picked up as RESET_PATH.
void Reset_Handler(void)
{
    extern int main(void);
    main();
    while (1) { }
}

// HardFault_Handler — naked ARM-Cortex fault ISR. Picked up as
// ISR_VECTOR via the `__attribute__((interrupt))` annotation.
void __attribute__((interrupt)) HardFault_Handler(void)
{
    while (1) { }
}

// SysTick_Handler — periodic 1 kHz tick ISR. Picked up as ISR_VECTOR.
void __attribute__((interrupt)) SysTick_Handler(void)
{
    static volatile uint32_t ticks;
    ticks++;
}

// Helper called from _start (asm-side) when needed.
void _start(void)
{
    Reset_Handler();
}

// main — picked up as MAIN_FUNCTION.
int main(void)
{
    while (1) { }
    return 0;
}
