#pragma once

void wait_ms(uint32_t ms){
  uint32_t clks_per_ms = MY_CPU_CLK_MHZ * 1000;
  uint32_t start_clock = my_mm_regs->cpu_clock;
  while((my_mm_regs->cpu_clock - start_clock) < (ms * clks_per_ms)){}
}