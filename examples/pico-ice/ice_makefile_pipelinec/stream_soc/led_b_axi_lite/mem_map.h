#pragma once
typedef struct led_b_mm_regs_t{
  uint32_t led_on;
}led_b_mm_regs_t;
#ifdef __PIPELINEC__
#include "led_b_mm_regs_t_bytes_t.h"
#endif