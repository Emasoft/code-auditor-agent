/* fixture for rtos_zephyr — exercises K_THREAD_DEFINE (one RTOS_TASK
 * per thread) and K_WORK_DEFINE (one EVENT_LISTENER per work item).
 * Two threads + one work item gives the golden non-trivial coverage.
 */
#include <zephyr/kernel.h>

#define SENSOR_STACK_SIZE 1024
#define CONTROL_STACK_SIZE 1024
#define SENSOR_PRIORITY 5
#define CONTROL_PRIORITY 6

/* Drains the I2C bus, publishes samples on g_samples_queue. */
static void sensor_thread(void *p1, void *p2, void *p3)
{
    (void)p1; (void)p2; (void)p3;
    while (1) {
        /* read sensor */
    }
}

/* Consumes samples, runs the PID loop, drives the actuator. */
static void control_thread(void *p1, void *p2, void *p3)
{
    (void)p1; (void)p2; (void)p3;
    while (1) {
        /* control step */
    }
}

K_THREAD_DEFINE(sensor_tid, SENSOR_STACK_SIZE,
                sensor_thread, NULL, NULL, NULL,
                SENSOR_PRIORITY, 0, 0);

K_THREAD_DEFINE(control_tid, CONTROL_STACK_SIZE,
                control_thread, NULL, NULL, NULL,
                CONTROL_PRIORITY, 0, 0);

/* Deferred shutdown handler — runs in the system workqueue on signal. */
static void shutdown_work_handler(struct k_work *work)
{
    (void)work;
    /* graceful shutdown */
}

K_WORK_DEFINE(shutdown_work, shutdown_work_handler);

int main(void)
{
    /* Kernel takes over after main() returns. */
    return 0;
}
