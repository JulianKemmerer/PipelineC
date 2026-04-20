// By default PipelineC names clock ports with the rate included
// ex. clk_12p0
// Override this behavior by creating an input with a constant name
// and telling the tool that input signal is a clock of specific rate
#include "compiler.h"
DECL_INPUT(uint1_t, pll_clk)
CLK_MHZ(pll_clk, PLL_CLK_MHZ)
DECL_INPUT(uint1_t, pll_locked)

uint32_t cpu_clock;
#pragma MAIN cpu_clock_main
void cpu_clock_main(){
  static uint32_t cycle_counter;
  cpu_clock = cycle_counter;
  cycle_counter = cycle_counter + 1;
}