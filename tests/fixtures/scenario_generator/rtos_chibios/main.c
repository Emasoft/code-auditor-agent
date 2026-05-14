/* fixture for rtos_chibios — exercises THD_FUNCTION (one RTOS_TASK per
 * function declared by the macro) plus chThdCreateStatic launch sites.
 * Two threads + main() gives the golden non-trivial coverage.
 */
#include "ch.h"
#include "hal.h"

static THD_WORKING_AREA(waBlinker, 128);
static THD_WORKING_AREA(waSampler, 256);

/* Toggles the heartbeat LED at 1 Hz. */
THD_FUNCTION(BlinkerThread, arg)
{
    (void)arg;
    while (true) {
        /* toggle */
    }
}

/* Reads the analog input, posts to the mailbox. */
THD_FUNCTION(SamplerThread, arg)
{
    (void)arg;
    while (true) {
        /* sample */
    }
}

int main(void)
{
    halInit();
    chSysInit();

    chThdCreateStatic(waBlinker, sizeof(waBlinker), NORMALPRIO, BlinkerThread, NULL);
    chThdCreateStatic(waSampler, sizeof(waSampler), NORMALPRIO + 1, SamplerThread, NULL);

    while (true) {
        /* main idle loop */
    }
    return 0;
}
