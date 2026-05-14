// fixture for firmware_nordic_sdk
// The primary_content fingerprint for firmware_nordic_sdk matches the
// substring "nrf_" / "NRF_SDK" / "nrfx_" in any **/*.h file. Three
// occurrences below ensure the match fires on a single header.
#ifndef NRF_DRV_CONFIG_H
#define NRF_DRV_CONFIG_H

// NRF_SDK target version banner expected by every nRF SDK header.
#define NRF_SDK_VERSION_MAJOR 17
#define NRF_SDK_VERSION_MINOR 0

#include <stdint.h>

extern uint32_t nrfx_systick_get(void);
extern void     nrf_gpio_pin_set(uint32_t pin);

#endif
