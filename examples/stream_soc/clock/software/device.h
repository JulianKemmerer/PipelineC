#pragma once

void wait_ms(uint32_t ms){
  uint32_t clks_per_ms = CPU_CLK_MHZ * 1000;
  uint32_t start_clock = mm_regs->cpu_clock;
  while((mm_regs->cpu_clock - start_clock) < (ms * clks_per_ms)){}
}