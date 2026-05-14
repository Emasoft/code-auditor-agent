/* fixture for rtos_freertos — minimal FreeRTOSConfig.h required by the
 * primary glob fingerprint. The disambiguator content checks main.c
 * for xTaskCreate / vTaskStartScheduler / xQueueCreate.
 */
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#define configUSE_PREEMPTION                    1
#define configUSE_IDLE_HOOK                     0
#define configUSE_TICK_HOOK                     0
#define configCPU_CLOCK_HZ                      ( 16000000UL )
#define configTICK_RATE_HZ                      ( 1000 )
#define configMAX_PRIORITIES                    ( 5 )
#define configMINIMAL_STACK_SIZE                ( 128 )
#define configTOTAL_HEAP_SIZE                   ( 10 * 1024 )
#define configMAX_TASK_NAME_LEN                 ( 16 )

#endif /* FREERTOS_CONFIG_H */
