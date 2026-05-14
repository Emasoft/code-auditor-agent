// SPDX-License-Identifier: Apache-2.0
// Fixture: a minimal ESP-IDF application exercising every entry-point
// kind that the firmware_espidf discoverer recognises.

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_event.h"
#include "esp_log.h"

static const char *TAG = "fixture";

// Long-running sensor task — picked up as RTOS_TASK (via xTaskCreate).
static void sensor_task(void *arg)
{
    (void)arg;
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

// Wi-Fi event handler — picked up as RTOS_TASK (via xTaskCreate target).
static void uplink_task(void *arg)
{
    (void)arg;
    while (1) {
        ESP_LOGI(TAG, "uplink heartbeat");
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

// Generic ESP event handler — referenced for fingerprint disambiguation
// (esp_event_handler substring); not a discoverable entry point itself.
static void esp_event_handler_cb(void *handler_arg, esp_event_base_t base,
                                  int32_t id, void *event_data)
{
    (void)handler_arg;
    (void)base;
    (void)id;
    (void)event_data;
}

// app_main — ESP-IDF boot entry, picked up as BOOT_PATH.
void app_main(void)
{
    xTaskCreate(sensor_task, "sensor", 2048, NULL, 5, NULL);
    xTaskCreate(uplink_task, "uplink", 4096, NULL, 4, NULL);
    (void)esp_event_handler_cb;
}
