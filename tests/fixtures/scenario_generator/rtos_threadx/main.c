/* fixture for rtos_threadx — exercises tx_thread_create (one RTOS_TASK
 * per thread) and tx_kernel_enter (BOOT_PATH for the RTOS launch).
 * The discoverer should emit one RTOS_TASK per tx_thread_create site.
 */
#include "tx_api.h"
#include "tx_user.h"

static TX_THREAD producer_thread;
static TX_THREAD consumer_thread;
static UCHAR producer_stack[1024];
static UCHAR consumer_stack[1024];

/* Generates work items, posts them to the shared queue. */
static void producer_entry(ULONG input)
{
    (void)input;
    while (1) {
        /* produce */
    }
}

/* Drains the shared queue, executes work items. */
static void consumer_entry(ULONG input)
{
    (void)input;
    while (1) {
        /* consume */
    }
}

void tx_application_define(void *first_unused_memory)
{
    (void)first_unused_memory;

    tx_thread_create(&producer_thread, "producer", producer_entry, 0,
                     producer_stack, 1024,
                     10, 10, TX_NO_TIME_SLICE, TX_AUTO_START);

    tx_thread_create(&consumer_thread, "consumer", consumer_entry, 0,
                     consumer_stack, 1024,
                     11, 11, TX_NO_TIME_SLICE, TX_AUTO_START);
}

int main(void)
{
    tx_kernel_enter();
    return 0;
}
