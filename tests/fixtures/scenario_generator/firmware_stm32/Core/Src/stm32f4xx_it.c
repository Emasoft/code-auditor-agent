// Fixture: STM32 IRQ handlers — every `*_IRQHandler` symbol below is
// a vector-table entry the firmware_stm32 discoverer should pick up as
// ISR_VECTOR. The "HAL_" substring is also present so this file
// disambiguates the firmware_stm32 fingerprint on its own.

#include "main.h"

extern UART_HandleTypeDef huart2;
extern TIM_HandleTypeDef htim2;

// EXTI line 0 IRQ — external interrupt from a GPIO PA0 push-button.
void EXTI0_IRQHandler(void)
{
    HAL_GPIO_EXTI_IRQHandler(GPIO_PIN_0);
}

// TIM2 IRQ — periodic timer overflow.
void TIM2_IRQHandler(void)
{
    HAL_TIM_IRQHandler(&htim2);
}

// USART2 IRQ — UART RX/TX/error.
void USART2_IRQHandler(void)
{
    HAL_UART_IRQHandler(&huart2);
}
