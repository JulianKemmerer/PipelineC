// xc7a35ticsg324-1l    Artix 7 (Arty)
// xcvu9p-flgb2104-2-i  Virtex Ultrascale Plus (AWS F1)
// xc7v2000tfhg1761-2   Virtex 7
// EP2AGX45CU17I3       Arria II GX
// 10CL120ZF780I8G      Cyclone 10 LP
// 10M50SCE144I7G       Max 10
// LFE5U-85F-6BG381C    ECP5U
#pragma PART "xc7a35ticsg324-1l"

//#include "examples/aws-fpga-dma/loopback.c"
//#include "examples/aws-fpga-dma/work.c"
//#include "examples/fosix/hello_world.c"
//#include "examples/fosix/bram_loopback.c"
//#include "examples/keccak.pc"
//#include "examples/arty/src/uart/uart_loopback_no_fc.c"
//#include "examples/arty/src/uart/uart_loopback_msg.c"
//#include "examples/arty/src/work/work.c"
//#include "examples/arty/src/fosix/main_bram_loopback.c"
//#include "examples/fir.c"
#include "examples/arty/src/blink.c"
//#include "examples/arty/src/ddr3/mig_app.c"

/*
#include "uintN_t.h"
#pragma MAIN_MHZ main 1000.0
uint32_t main(uint32_t x, uint32_t y)
{
  return x/y;
}
*/

/*
#pragma MAIN_MHZ fast 300.0
#pragma MAIN_MHZ slow 100.0

// Stream of uint64_t values
#include "uintN_t.h"
typedef struct uint64_s
{
  uint64_t data;
  uint1_t valid;  
} uint64_s;
#include "uint64_s_array_N_t.h" // Auto generated

volatile uint64_s fast_to_slow;
#include "fast_to_slow_clock_crossing.h" // Auto generated

volatile uint64_s slow_to_fast;
#include "slow_to_fast_clock_crossing.h" // Auto generated

uint64_s fast(uint64_s in_data)
{
  // Send data into slow domain
  fast_to_slow_write_t to_slow_array;
  to_slow_array.data[0] = in_data;
  fast_to_slow_WRITE(to_slow_array);
  
  // Get data from slow domain
  slow_to_fast_read_t from_slow_array;
  from_slow_array = slow_to_fast_READ();
  uint64_s out_data = from_slow_array.data[0];
  
  return out_data;
}

void slow()
{
  // Get datas from fast domain
  fast_to_slow_read_t from_fast_array;
  from_fast_array = fast_to_slow_READ();
  
  // Square all the values in parallel
  slow_to_fast_write_t to_fast_array;
  uint32_t i;
  for(i=0;i<slow_to_fast_RATIO;i+=1)
  {
    to_fast_array.data[i].data = from_fast_array.data[i].data * from_fast_array.data[i].data;
    to_fast_array.data[i].valid = from_fast_array.data[i].valid;
  }
  
  // Send data into fast domain
  slow_to_fast_WRITE(to_fast_array);
}
*/
