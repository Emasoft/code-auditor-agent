// SPDX-License-Identifier: Apache-2.0
// Fixture: a minimal Zephyr application exercising every entry-point
// kind that the firmware_zephyr discoverer recognises.

#include <zephyr/kernel.h>
#include <zephyr/init.h>

#define WORKER_STACK_SIZE 1024
#define WORKER_PRIORITY 5

// Worker thread body — picked up as RTOS_TASK via K_THREAD_DEFINE.
static void worker_thread_entry(void *p1, void *p2, void *p3)
{
    ARG_UNUSED(p1);
    ARG_UNUSED(p2);
    ARG_UNUSED(p3);
    while (1) {
        k_sleep(K_MSEC(1000));
    }
}

// Work-queue handler — picked up as EVENT_LISTENER via K_WORK_DEFINE.
static void sensor_work_handler(struct k_work *work)
{
    ARG_UNUSED(work);
}

// SYS_INIT registration — picked up as BOOT_PATH.
static int board_setup(void)
{
    return 0;
}

K_THREAD_DEFINE(worker_tid, WORKER_STACK_SIZE, worker_thread_entry,
                NULL, NULL, NULL, WORKER_PRIORITY, 0, 0);

K_WORK_DEFINE(sensor_work, sensor_work_handler);

SYS_INIT(board_setup, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);

// Cooperative main — picked up as MAIN_FUNCTION.
int main(void)
{
    k_work_submit(&sensor_work);
    return 0;
}
