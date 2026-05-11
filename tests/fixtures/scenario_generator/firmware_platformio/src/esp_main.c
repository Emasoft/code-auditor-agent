/* ESP-IDF entry point — used by firmware_platformio fixture. */

#include <stdio.h>

/* Forward declarations of the ESP-IDF symbols we reference. */
typedef int esp_err_t;
typedef const char *esp_event_base_t;
typedef int32_t (*esp_event_handler_t)(void *, esp_event_base_t, int32_t, void *);

extern esp_err_t esp_event_handler_register(
    esp_event_base_t event_base,
    int32_t event_id,
    esp_event_handler_t event_handler,
    void *event_handler_arg);

static const char *WIFI_EVENT = "WIFI_EVENT";

/* Wi-Fi event handler. */
static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    (void)base;
    (void)id;
    (void)data;
}

/* ESP-IDF application entry point. */
void app_main(void) {
    esp_event_handler_register(WIFI_EVENT, 0, &wifi_event_handler, NULL);
}
