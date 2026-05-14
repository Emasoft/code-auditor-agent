// Fixture: a minimal Nordic nRF5 SDK application exercising the
// entry-point kinds the firmware_nordic_sdk discoverer recognises.

#include "nrf_drv_config.h"

// BLE event handler — picked up as EVENT_LISTENER (ble_evt_handler).
static void ble_evt_handler(const void *p_ble_evt, void *p_context)
{
    (void)p_ble_evt;
    (void)p_context;
}

// App-timer callback — picked up as EVENT_LISTENER via app_timer_*
// registration. Symbol name matches the discoverer's _timeout_handler
// suffix convention.
static void heartbeat_timeout_handler(void *p_context)
{
    (void)p_context;
}

// GPIOTE callback — picked up as GPIO_INTERRUPT.
static void button_event_handler(uint8_t pin_no, uint8_t button_action)
{
    (void)pin_no;
    (void)button_action;
}

// Reference the NRF_LOG_INIT-style init symbol that confirms this is
// a stock nRF SDK build (the discoverer keys on the call site).
extern void NRF_LOG_INIT_stub(void);

int main(void)
{
    NRF_LOG_INIT_stub();
    app_timer_init();
    app_timer_create(NULL, 0, heartbeat_timeout_handler);
    ble_stack_init(ble_evt_handler);
    nrf_drv_gpiote_in_init_stub(button_event_handler);
    for (;;) { }
    return 0;
}
