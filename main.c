// xc7a35ticsg324-1l     Artix 7 (Arty)
// xcvu9p-flgb2104-2-i   Virtex Ultrascale Plus (AWS F1)
// xc7v2000tfhg1761-2    Virtex 7
// EP2AGX45CU17I3        Arria II GX
// 10CL120ZF780I8G       Cyclone 10 LP
// 10M50SCE144I7G        Max 10
// LFE5U-85F-6BG381C     ECP5U
// LFE5UM5G-85F-8BG756C  ECP5UM5G
// ICE40UP5K-SG48        ICE40UP
#pragma PART "xc7a35ticsg324-1l"

// Most recent (and likely working) examples towards the bottom of list \/
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
#include "examples/arty/src/eth/app.c"

/*
#include "uintN_t.h"
// Try to reach target fmax
#pragma MAIN_MHZ main 400.0  
uint128_t total;
uint128_t main(uint128_t inc, uint1_t en)
{
  if(en)
  {
    total += inc;
  }
  return total;
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
