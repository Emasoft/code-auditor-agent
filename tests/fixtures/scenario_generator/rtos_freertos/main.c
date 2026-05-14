/* fixture for rtos_freertos — exercises xTaskCreate / xQueueCreate /
 * vTaskStartScheduler. Three task entry functions get registered:
 * sensor_task, comms_task, watchdog_task. The discoverer must emit
 * one RTOS_TASK per xTaskCreate call, plus one BOOT_PATH for main().
 */
#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"

static QueueHandle_t g_sensor_queue;

/* Reads ADC, posts sample to g_sensor_queue. High priority. */
static void sensor_task(void *params)
{
    (void)params;
    for (;;) {
        /* sample loop */
    }
}

/* Drains g_sensor_queue, ships frames over UART. Medium priority. */
static void comms_task(void *params)
{
    (void)params;
    for (;;) {
        /* tx loop */
    }
}

/* Kicks the hardware watchdog. Low priority, runs whenever idle has slack. */
static void watchdog_task(void *params)
{
    (void)params;
    for (;;) {
        /* tickle wdog */
    }
}

int main(void)
{
    g_sensor_queue = xQueueCreate(8, sizeof(uint32_t));

    xTaskCreate(sensor_task, "sensor", 256, NULL, 3, NULL);
    xTaskCreate(comms_task, "comms", 256, NULL, 2, NULL);
    xTaskCreate(watchdog_task, "watchdog", 128, NULL, 1, NULL);

    vTaskStartScheduler();
    for (;;) { }
    return 0;
}
