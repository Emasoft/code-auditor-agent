// Fixture: a minimal STM32 HAL application exercising the entry-point
// kinds the firmware_stm32 discoverer recognises. The "HAL_", "NVIC_",
// and "__HAL_RCC_" substrings are present below so the disambiguator
// content match for **/*.c fires.

#include "main.h"

// HAL UART RX callback — fired from inside the HAL UART interrupt path.
// Picked up as EVENT_LISTENER because it is a HAL_*Callback weak override.
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    (void)huart;
}

// HAL ADC conversion-complete callback — also a weak override.
void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *hadc)
{
    (void)hadc;
}

// Error_Handler — the canonical safe-state trap CubeIDE generates.
void Error_Handler(void)
{
    __disable_irq();
    while (1) { }
}

// main() — STM32 firmware boot entry. Picked up as MAIN_FUNCTION.
int main(void)
{
    HAL_Init();
    __HAL_RCC_GPIOA_CLK_ENABLE();
    NVIC_EnableIRQ(EXTI0_IRQn);
    while (1) { }
}
