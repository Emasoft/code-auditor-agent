/* fixture for rtos_chibios — chconf.h is the primary glob trigger.
 * The disambiguator content check looks at main.c for the
 * chThdCreateStatic / chSysInit calls.
 */
#ifndef CHCONF_H
#define CHCONF_H

#define CH_CFG_ST_FREQUENCY         1000
#define CH_CFG_TIME_QUANTUM         0
#define CH_CFG_NO_IDLE_THREAD       FALSE

#endif /* CHCONF_H */
