#pragma PART "LFE5UM5G-85F-8BG756C"
// How to allow user defined fixed pipeline latencies?
// https://github.com/JulianKemmerer/PipelineC/issues/97
#include "uintN_t.h"
#include "compiler.h"

/*
#pragma FUNC_LATENCY small_op_delay 1
uint64_t small_op_delay(uint64_t x){
  static uint64_t the_reg;
  uint64_t rv = the_reg;
  the_reg = ~x;
  return rv;
}
typedef struct values_t{
  uint64_t user_delayed;
  uint64_t tool_delayed;
}values_t;
#pragma MAIN_MHZ main 400.0
values_t main(uint64_t x, uint64_t y){
  values_t outputs;
  outputs.tool_delayed = ~x + ~y;
  outputs.user_delayed = small_op_delay(x) + small_op_delay(y);
  return outputs;
}
*/

BUILT_IN_RAM_FUNC_LATENCY(my_func, my_bram_RAM_DP_RF_1, 1)
#pragma MAIN my_func
uint32_t my_func(uint32_t waddr, uint32_t wdata, uint32_t raddr)
{
  static uint32_t my_bram[128];
  //static uint32_t waddr = 0;
  //static uint32_t wdata = 0;
  //static uint32_t raddr = 0;
  uint32_t rdata = my_bram_RAM_DP_RF_1(raddr, waddr, wdata, 1);
  printf("Write: addr=%d,data=%d. Read addr=%d. Read data=%d\n",
         waddr, wdata, raddr, rdata);
  // Test pattern
  //if(wdata > 0){
  //  raddr += 1;
  //}
  //waddr += 1;
  //wdata += 1;
  return rdata; // Dummy
}

/*
// This func is not allowed since it doesnt make sense in terms of implemented hardware
// The static local variables describe clock by clock logic
// but the BUILT_IN_RAM_FUNC_LATENCY=1 of my_bram_RAM_DP_RF_1 describes a pipeline
#pragma MAIN my_bad_func
BUILT_IN_RAM_FUNC_LATENCY(my_bad_func, my_bram_RAM_DP_RF_1, 1)
uint32_t my_bad_func(uint32_t waddr, uint32_t wdata, uint32_t raddr)
{
  static uint32_t my_bram[128];
  static uint32_t accum_rd_data = 0;
  uint32_t rdata = my_bram_RAM_DP_RF_1(raddr, waddr, wdata, 1);
  accum_rd_data += rdata;
  return rdata + accum_rd_data;
}
*/
/*
#include "intN_t.h"
#pragma FUNC_LATENCY one_cycle_negate 1
int64_t one_cycle_negate(int64_t x){
  static int64_t the_reg;
  int64_t rv = the_reg;
  the_reg = -x;
  return rv;
}
#pragma MAIN_MHZ main 200.0
// Output should always be == input after some cycles
// But can be pipelined
int64_t main(int64_t x){
  int64_t nx = one_cycle_negate(x);
  int64_t z = x + nx;
  z = one_cycle_negate(z);
  return z + x;
}
*/