// xc7a35ticsg324-1l     Artix 7 (Arty)
// xcvu9p-flgb2104-2-i   Virtex Ultrascale Plus (AWS F1)
// xcvu33p-fsvh2104-2L-e Virtex Ultrascale Plus
// xc7v2000tfhg1761-2    Virtex 7
// EP2AGX45CU17I3        Arria II GX
// 10CL120ZF780I8G       Cyclone 10 LP
// 5CGXFC9E7F35C8        Cyclone 5 GX
// 10M50SCE144I7G        Max 10
// LFE5U-85F-6BG381C     ECP5U
// LFE5UM5G-85F-8BG756C  ECP5UM5G
// ICE40UP5K-SG48        ICE40UP
#pragma PART "xcvu9p-flgb2104-2-i"

// Most recent (and more likely working) examples towards the bottom of list \/
//#include "examples/aws-fpga-dma/loopback.c"
//#include "examples/aws-fpga-dma/work.c"
//#include "examples/fosix/hello_world.c"
//#include "examples/fosix/bram_loopback.c"
//#include "examples/keccak.pc"
//#include "examples/arty/src/uart/uart_loopback_no_fc.c"
//#include "examples/arty/src/work/work.c"
//#include "examples/arty/src/fosix/main_bram_loopback.c"
//#include "examples/fir.c"
//#include "examples/arty/src/uart/uart_loopback_msg.c"
//#include "examples/arty/src/blink.c"
//#include "examples/clock_crossing.c"
//#include "examples/async_clock_crossing.c"
//#include "examples/arty/src/uart_ddr3_loopback/app.c"
//#include "examples/arty/src/ddr3/mig_app.c"
//#include "examples/arty/src/eth/loopback_app.c"
//#include "examples/arty/src/eth/work_app.c"
//#include "examples/spw_pkg_guard.c"
//#include "examples/arty/src/mnist/neural_network_fsm.c"
//#include "examples/littleriscy/riscv.c"
#include "examples/NexusProofOfWork/NXSTest_syn.c"

/*
#include "uintN_t.h"
#pragma MAIN_MHZ main 800.0
uint64_t main(uint32_t x, uint32_t y)
{
  return x * y;
}
*/

/*#pragma PART "xc7a35ticsg324-1l"
uint7_t main(uint6_t x, uint6_t y, uint1_t c)
{
  __vhdl__("\n\
  begin \n\
     return_output <= ('0'&x) + ('0'&y) + c;\n\
  ");
  // uint1 = (ns): 1.654 = 604.5949214026602 MHz
  // uint2 = (ns): 1.726 = 579.3742757821552 MHz
  // uint3 = (ns): 2.303 = 434.2162396873643 MHz
  // uint4 = (ns): 2.31 = 432.9004329004329 MHz
  // uint5 = (ns): 2.894 = 345.5425017277125 MHz (LUT3=1 LUT5=2)
  // uint6 = (ns): 2.25699 = 443.0660168365087 MHz (CARRY4=2 LUT2=1)
  // uint7 = (ns): 2.283 = 438.02014892685065 MHz
  // uint8 = (ns): 2.332 = 428.81646655231566 MHz
  // uint9 = (ns): 2.258 = 442.8697962798937 MHz
  // uint10 = (ns): 2.371 = 421.76296921130324 MHz
  // uint11 = (ns): 2.397002 = 417.18815185648725 MHz
  // uint12 = (ns): 2.4459999999999997 = 408.83074407195426 MHz
  // uint13 = (ns): 2.372 = 421.5851602023609 MHz
  // uint14 = (ns): 2.4850000000000003 = 402.41448692152915 MHz
  // uint15 = (ns): 2.511 = 398.24771007566704 MHz
  // uint16 = (ns): 2.56 = 390.625 MHz
  //return x + y + c;
}*/

/*
#include "uintN_t.h"
#pragma MAIN_MHZ main 1000.0
float main(float x, float y)
{
  return x + y;
}
*/

/*
uint32_t main(uint8_t addr, uint32_t wr_data, uint1_t wr_en)
{
  static uint32_t my_array[256];
  uint32_t rd_data = my_array[addr];
  if(wr_en)
  {
    my_array[addr] = wr_data;
  }
  return rd_data;
}
*/


/*
uint8_t the_ram[128];
 main()
{
  
  // A variable latency globally visible memory access
  
  // Async style send and wait two func and fsm?
  
  // IMplemented as pipeline c func replacing this?  
  the_ram[i] = x
  // How to put a state machine into a user design?
    
}
*/


/*
// Tag main func as being compiled as C code and run on RISCV cpu
// What does interaction with PipelineC main func look like?
#pragma MAIN_MHZ cpu_main 100.0
#pragma MAIN_THREAD cpu_main // Run this as a CPU style thread
void cpu_main()
{
  // CPU style control loop
  while(1)
  {
    // Running around sequentially reading and writing memory
    // / Memory mapped registers to interact with hardware
    // The key being in hardware the registers are at 100MHz as specified
    mem[i] = foo
  
  }
  
}

#pragma MAIN_MHZ fpga_main 100.0
void fpga_main()
{
  // Every ten nanoseconds a value from
  // the RISCV CPU registers can be read/write ~like a variable somehow?
  
  
}
*/






/*
#include "intN_t.h"
#include "uintN_t.h"
#define elem_t uint8_t
elem_t the_ram[8][8][8][8]; // 4096 elements
#pragma MAIN_MHZ main 100.0
elem_t main(uint1_t sel, uint3_t addr0, uint3_t addr1, uint3_t addr2, uint3_t addr3, elem_t write_data, uint1_t write_enable)
{
  //static elem_t the_ram[8][8][8][8]; // 4096 elements
  // Function name upon parsing becomes a mangled version of itself
  elem_t rv = 0;
  if(sel)
  {
    rv = the_ram_RAM_SP_RF_0(addr0, addr1, addr2, addr3, write_data, write_enable);
  }
  return rv;
}
*/

/*
#include "intN_t.h"
#include "uintN_t.h"


#pragma MAIN_MHZ main 1000.0
float main(float x, float y)
{
  return x + y;
}

*/

/*
#include "intN_t.h"
#include "uintN_t.h"
void my_printy(uint1_t sel, uint32_t x, int32_t y)
{
  if(sel)
  {
    printf("0x%X, %d ~jawns~\n", x, y);
  }
}
#pragma MAIN_MHZ main 100.0
void main(uint1_t sel, uint32_t x, int32_t y)
{
  my_printy(sel,x,y);
}
*/

/*
#include "uintN_t.h"
// Try to reach target fmax
#pragma MAIN_MHZ main 400.0  
// Standard multiplication embarrassingly parallel
#define data_t int8_t
#define N 8
// Built in binary tree array sum function
#define array_sum int8_array_sum8
// Array as struct for return
typedef struct an_array_t
{
	data_t a[N][N];
} an_array_t;
// Module with two matricies as input ports and one as output
an_array_t main(data_t mat1[N][N], data_t mat2[N][N])
{
    an_array_t res;
    uint32_t i;
    uint32_t j;
    uint32_t k;
    for (i = 0; i < N; i = i + 1) 
    { 
        for (j = 0; j < N; j = j + 1) 
        { 
            data_t products[N];
            for (k = 0; k < N; k = k + 1)
            {
                products[k] = mat1[i][k] * mat2[k][j];
            }
            res.a[i][j] = array_sum(products);
        } 
    }
    
    return res;
}
*/



    // uint1 = (ns): 1.654 = 604.5949214026602 MHz
  // uint2 = (ns): 1.726 = 579.3742757821552 MHz
  //uint6 = (ns): 2.25699 = 443.0660168365087 MHz   LUT6?
  // uint9 = (ns): 2.258 = 442.8697962798937 MHz
  // uint7 = (ns): 2.283 = 438.02014892685065 MHz
  // uint3 = (ns): 2.303 = 434.2162396873643 MHz
  // uint4 = (ns): 2.31 = 432.9004329004329 MHz
  // uint8 = (ns): 2.332 = 428.81646655231566 MHz
  // uint10 = (ns): 2.371 = 421.76296921130324 MHz
  // uint13 = (ns): 2.372 = 421.5851602023609 MHz
  // uint11 = (ns): 2.397002 = 417.18815185648725 MHz
  // uint12 = (ns): 2.4459999999999997 = 408.83074407195426 MHz
  // uint14 = (ns): 2.4850000000000003 = 402.41448692152915 MHz
  // uint15 = (ns): 2.511 = 398.24771007566704 MHz
  // uint16 = (ns): 2.56 = 390.625 MHz
  // uint5 = (ns): 2.894 = 345.5425017277125 MHz
  
  
  
  
  
  
  
  
  
  
  
