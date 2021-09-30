// Full part string examples:
// xc7a35ticsg324-1l     Artix 7 (Arty)
// xcvu9p-flgb2104-2-i   Virtex Ultrascale Plus (AWS F1)
// xcvu33p-fsvh2104-2-e  Virtex Ultrascale Plus
// xc7v2000tfhg1761-2    Virtex 7
// EP2AGX45CU17I3        Arria II GX
// 10CL120ZF780I8G       Cyclone 10 LP
// 5CGXFC9E7F35C8        Cyclone 5 GX
// 10M50SCE144I7G        Max 10
// LFE5U-85F-6BG381C     ECP5U
// LFE5UM5G-85F-8BG756C  ECP5UM5G 
// ICE40UP5K-SG48        ICE40UP
// T8F81                 Trion T8 (Xyloni)
// Ti60F225              Titanium
//#pragma PART "xc7a35ticsg324-1l"

// Most recent (and more likely working) examples towards the bottom of list \/
// Please see: https://github.com/JulianKemmerer/PipelineC/wiki/Examples
//#include "examples/aws-fpga-dma/loopback.c"
//#include "examples/aws-fpga-dma/work.c"
//#include "examples/fosix/hello_world.c"
//#include "examples/fosix/bram_loopback.c"
//#include "examples/arty/src/uart/uart_loopback_no_fc.c"
//#include "examples/arty/src/work/work.c"
//#include "examples/arty/src/uart_ddr3_loopback/app.c"
//#include "examples/arty/src/ddr3/mig_app.c"
//#include "examples/arty/src/eth/loopback_app.c"
//#include "examples/arty/src/mnist/neural_network_fsm.c"
//#include "examples/arty/src/uart/uart_loopback_msg.c"
//#include "examples/arty/src/blink.c"
//#include "examples/littleriscy/riscv.c"
//#include "examples/arty/src/eth/work_app.c"
//#include "examples/NexusProofOfWork/NXSTest_syn.c"
//#include "examples/fir.c"
//#include "examples/arty/src/i2s/i2s_passthrough_app.c"
//#include "examples/arty/src/audio/distortion.c"
//#include "examples/arty/src/i2s/i2s_app.c"
//#include "examples/fosix/main_bram_loopback.c"
//#include "examples/groestl/groestl.c"
//#include "examples/aes/aes.c"
//#include "examples/async_clock_crossing.c"
//#include "examples/clock_crossing.c"
//#include "examples/pipeline_and_fsm.c"
//#include "examples/edaplay.c"
//#include "examples/fosix/main_game_clk_step.c"
#include "examples/blink.c"
//#include "examples/llvm/rsqrtf.c"
//#include "examples/arty/src/vga/test_pattern.c"

// Below is a bunch of recent scratch work - enjoy

/*
#pragma PART "EP4CE22F17C6"
#include "uintN_t.h"
#pragma MAIN my_mult
uint48_t my_mult(uint24_t a, uint24_t b)
{
  return a * b;
}
*/

/*
#include "uintN_t.h"

// A single cycle comb. logic doing:
//  Input/entry handshake
//  Comb. logic add
//  Update a storage register
//  Output/return handshake 
uint8_t atomic_add(uint8_t val, uint8_t tid)
{
  static uint8_t the_reg;
  uint8_t new_reg_val = the_reg + val;
  printf("Thread %d incremented value from %d -> %d.\n",
    tid, the_reg, new_reg_val);
  the_reg = new_reg_val;
  return the_reg;
}
// Signal to tool to derive a single instance
// FSM region, ex. only one 8b the_reg in the design
// shared among N calling instances
#include "atomic_add_SINGLE_INST.h"

// A 'thread'/FSM instance definition
// trying to repeatedly increment the_reg
uint8_t incrementer_thread(uint8_t tid)
{
  while(1)
  {
    // Try to do atomic add 
    uint8_t local_reg_val = atomic_add(1, tid);
    // Output val so doesnt synthesize away
    __out(local_reg_val); 
  }
}
// Derive FSM from above function
#include "incrementer_thread_FSM.h"

// Top level N parallel instances of incrementer_thread
#define N_THREADS 10
// Connect FSM outputs to top level output
// So doesnt synthesize away
typedef struct n_thread_outputs_t
{
  incrementer_thread_OUTPUT_t data[N_THREADS];
}n_thread_outputs_t;
#pragma MAIN_MHZ main 100.0
n_thread_outputs_t main()
{
  // Registers keeping time count and knowning when done
  static uint32_t clk_cycle_count;
  
  // N parallel instances of incrementer_thread
  uint8_t tid;
  incrementer_thread_INPUT_t inputs[N_THREADS];
  n_thread_outputs_t outputs;
  for(tid=0; tid<N_THREADS; tid+=1)
  {
    inputs[tid].tid = tid;
    inputs[tid].input_valid = 1;
    inputs[tid].output_ready = 1;
    outputs.data[tid] = incrementer_thread_FSM(inputs[tid]);
    if(outputs.data[tid].input_ready)
    {
      printf("Clock# %d: Thread %d starting.\n",
        clk_cycle_count, tid);  
    }
    if(outputs.data[tid].output_valid)
    {
      printf("Clock# %d: Thread %d output value = %d.\n",
        clk_cycle_count, tid, outputs.data[tid].return_output);
    }
  }
  
  // Func occuring each clk cycle
  clk_cycle_count += 1;
  
  // Wire up outputs
  return outputs;
}
*/

/*
#include "uintN_t.h"

uint8_t shared_region(uint8_t val, uint8_t wr_en)
{
  static uint8_t the_reg;
  uint8_t rd_data = the_reg;
  if(wr_en)
  {
    the_reg = val;
  }
  return rd_data;
}
// A single instance region, ex. only one 8b the_reg
#include "shared_region_SINGLE_INST.h"

void incrementer_thread()
{
  static uint8_t local_reg;
  while(1)
  {
    local_reg = shared_region(local_reg, 1);
    local_reg += 1;
  }
}
#include "incrementer_thread_FSM.h"

// First instance of thread
#pragma MAIN_MHZ main_0 100.0
incrementer_thread_OUTPUT_t main_0(incrementer_thread_INPUT_t i)
{
  incrementer_thread_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  incrementer_thread_OUTPUT_t o = incrementer_thread_FSM(i);
  return o;
}
// Second instance of thread
#pragma MAIN_MHZ main_1 100.0
incrementer_thread_OUTPUT_t main_1(incrementer_thread_INPUT_t i)
{
  incrementer_thread_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  incrementer_thread_OUTPUT_t o = incrementer_thread_FSM(i);
  return o;
}
*/

/*
#include "uintN_t.h"

// Include Arty modules
// with globally visible port/wires like
// 'leds' and 'switches'
#include "examples/arty/src/leds/leds.c"
#include "examples/arty/src/switches/switches.c"

// Since multiple 'main' instances w/ WIRE_WRITE
// Identify which instance drives the LEDsfi
// Just need any part of hierarchical path
// that can uniquely idenitify an inst
#pragma ID_INST leds main_1/my_inst[1]

// Full path from main instance on would work too

// A func driving global 'leds' wire
// and reading global 'switches' wire
void duplicated_read_write_func()
{
  static uint4_t leds_reg;
  // leds = leds_reg;
  WIRE_WRITE(uint4_t, leds, leds_reg)
  // leds_reg = switches;
  WIRE_READ(uint4_t, leds_reg, switches)
}

#pragma MAIN_MHZ main_0 100.0
void main_0()
{
  #pragma INST_NAME my_inst[0]
  duplicated_read_write_func();
}

#pragma MAIN_MHZ main_1 100.0
void main_1()
{
  #pragma INST_NAME my_inst[1]
  duplicated_read_write_func();
}
*/

/*
// N instances of the func
#define N 2
#pragma MAIN_MHZ rw_n_times 100.0
void rw_n_times(uint4_t x[N])
{
  uint32_t i;
  for(i=0;i<N;i+=1)
  {
    #pragma INST_NAME my_inst i
    read_write_func(x[i]);
  }
}*/


/*
#include "intN_t.h"
#include "uintN_t.h"

#pragma MAIN func_a
uint8_t func_a(uint8_t x)
{
  // Two instances of func b
  for(i=0;i<2;i+=1)
  {
    #pragma INST_NAME func_b i
    .. func_b(x) ...
  }
}

// A globally visible port/wire
uint8_t global_wire_b_to_c;
#pragma WIRE global_wire_b_to_c func_a.func_b[0]

uint8_t func_b(uint8_t x)
{

  // Driver side of wire
  WRITE(global_wire_b_to_c, some_value);

}
uint8_t func_c(...)
{

  // Reading side of wire
  some_value = READ(global_wire_b_to_c);

}
*/

/*
#pragma PART "LFE5U-45F-8BG256I"

#include "uintN_t.h"

#pragma MAIN_MHZ popcount 440.0
uint8_t popcount(uint1_t bits[64*12])
{
  // Built in binary tree operators on arrays
  uint8_t result = uint1_array_sum768(bits);
  return result;
}
*/


/*
#include "intN_t.h"
#include "uintN_t.h"
#pragma MAIN_MHZ main2 100.0

int32_t main2(uint1_t sel0)
{
  int32_t temp;
  
  if(sel0)
  {
    int32_t unused;
    unused = sel0 + 1;
    temp = unused + 1;
  }
  else
  {
    int32_t unused;
    unused = 2;
  }
  return temp;
}


int32_t main(uint2_t sel,int32_t in0,int32_t in1,int32_t in2,int32_t in3)
{
  // Layer 0
    
  // Get sel bit
  uint1_t sel0;
  sel0 = uint2_0_0(sel);

  int32_t layer0_node0;
  // Do regular mux
  if(sel0)
  {
    layer0_node0 = in1;
  }
  else
  {
    layer0_node0 = in0;
  }
  
  int32_t layer0_node1;
  // Do regular mux
  if(sel0)
  {
    layer0_node1 = in3;
  }
  else
  {
    layer0_node1 = in2;
  }
  
  // Layer 1
    
  // Get sel bit
  uint1_t sel1;
  sel1 = uint2_1_1(sel);

  int32_t layer1_node0;
  // Do regular mux
  if(sel1)
  {
    layer1_node0 = layer0_node1;
  }
  else
  {
    layer1_node0 = layer0_node0;
  }
   
  return layer1_node0;
}
*/

/*
#include "uintN_t.h"
typedef struct point_t
{
  uint8_t x;
  uint8_t y;
}point_t;
typedef struct square_t
{
  point_t tl;
  point_t bl;
}square_t;
//#include "uint8_t_array_N_t.h"
//#include "uint8_t_bytes_t.h"
//#include "uint32_t_bytes_t.h"
#include "square_t_bytes_t.h"

#pragma MAIN_MHZ main 100.0
square_t main(square_t s)
{
  return s;
}
*/

/*
#include "uintN_t.h"
#pragma MAIN_MHZ main 100.0
uint8_t main(uint8_t inc_val, uint1_t inc)
{
  static uint8_t accum = 0;
  if(inc)
  {
    uint8_t accum = accum + inc_val;
  }
  return accum; 
}
*/
/*
#include "uintN_t.h"
#pragma MAIN_MHZ main 100.0
typedef struct point_t
{
  uint8_t dims[3];
}point_t;
typedef struct point_2_t
{
  point_t a;
  point_t b;
}point_2_t;
point_2_t main()
{
  point_2_t rv = {0};
  return rv;
}
*/

/*
#include "uintN_t.h"
uint8_t bar_comb(uint8_t f, uint8_t x)
{
  return f + x;
}
uint8_t foo_clk_fsm(uint8_t x)
{
  static uint8_t accum = 0;
  accum += x;
  x = accum;
  while(x > 0)
  {
    x -= 1;
    __clk();
  }
  __clk();
  return accum;
}
uint8_t main(uint8_t x)
{
  // An FSM that uses __clk() and
  // takes multiple cycles
  uint8_t f1 = foo_clk_fsm(x); 
  // A function without __clk() that
  // is same cycle comb logic
  uint8_t b = bar_comb(f1, x);
  // Second instance is going back to same state
  uint8_t f2 = foo_clk_fsm(b);
  return f2;
}
// Including this header auto generates a derived
// finite state machine (in PipelineC) from main_clk_fsm
#include "main_FSM.h"
// The top level 'main' wrapper instantiation
// IO port types from generated code
#pragma MAIN_MHZ main_wrapper 100.0
main_OUTPUT_t main_wrapper(main_INPUT_t i)
{
  return main_FSM(i);
}
*/

/*
//#pragma MAIN_MHZ main_FSM 100.0
#pragma MAIN_MHZ tb 100.0
void tb()
{
  static uint8_t x;
  
  main_INPUT_t i;
  i.input_valid = 1;
  i.x = x;
  i.output_ready = 1;
  
  main_OUTPUT_t o = main_FSM(i);
  
  if(o.input_ready)
  {
    // Next input
    x += 1;
  }  
}
*/

/*
#include "uintN_t.h"

// Include Arty leds module
// with globally visible port/wire 'leds'
#include "examples/arty/src/leds/leds.c"

void main()
{
  // a 28 bits unsigned integer register
  uint28_t counter = 0;
  while (1) {
    // LEDs updated every clock
    // with the 4 most significant bits
    uint4_t led = uint28_27_24(counter);
    // Drive the 'leds' global wire
    WIRE_WRITE(uint4_t, leds, led) // leds = led;
    counter = counter + 1;
    __clk();
  }
}
// Including this header auto generates a derived
// finite state machine (in PipelineC) from main
#include "main_FSM.h"
// The top level 'main' wrapper instantiation
// IO port types from generated code
#pragma MAIN_MHZ main_wrapper 100.0
void main_wrapper()
{
  main_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  main_OUTPUT_t o = main_FSM(i);
}
*/

/*
// Output 4b wired to LEDs
// Regular HDL style
uint4_t main()
{
  // a 28 bits unsigned integer register
  static uint28_t counter = 0;
  // LEDs updated every clock
  // with the 4 most significant bits
  uint4_t led = uint28_27_24(counter);
  counter = counter + 1;
  return led;
}
*/

/*
#include "uintN_t.h"
// Output 4b wired to LEDs
// Derived FSM style
uint4_t main()
{
  // a 28 bits unsigned integer register
  uint28_t counter = 0;
  while (1) {
    // LEDs updated every clock
    // with the 4 most significant bits
    uint4_t led = uint28_27_24(counter);
    counter = counter + 1;
    __out(led);
  }
}
// Including this header auto generates a derived
// finite state machine (in PipelineC) from main
#include "main_FSM.h"
// The top level 'main' wrapper instantiation
// IO port types from generated code
#pragma MAIN_MHZ main_wrapper 100.0
uint4_t main_wrapper()
{
  main_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  main_OUTPUT_t o = main_FSM(i);
  return o.return_output;
}
*/

/*
#include "uintN_t.h"

uint8_t worker_thread(uint8_t wait_cycles)
{
  // Wait some number of cycles then return
  while(wait_cycles > 0)
  {
    wait_cycles -= 1;
    __clk();
  }
  return wait_cycles;
}
// Including this header auto generates a derived
// finite state machine (in PipelineC)
#include "worker_thread_FSM.h"

// The top level 'main' instantiation
#pragma MAIN_MHZ main 400.0
#define NUM_THREADS 10
uint32_t main()
{
  static uint32_t cycle_counter;
  static uint1_t thread_stopped[NUM_THREADS];
  uint1_t rv = uint1_array_or10(thread_stopped);
  // N parallel instances of worker_thread FSM
  uint32_t i;
  for(i=0; i <NUM_THREADS; i+=1)
  {
    if(!thread_stopped[i])
    {
      worker_thread_INPUT_t inputs;
      inputs.wait_cycles = i;
      inputs.input_valid = 1;
      inputs.output_ready = 1;
      worker_thread_OUTPUT_t outputs = worker_thread_FSM(inputs);
      if(outputs.input_ready)
      {
        printf("Thread %d started in cycle %d\n", i, cycle_counter);
      }
      if(outputs.output_valid)
      {
        printf("Thread %d ended in cycle %d\n", i, cycle_counter);
        thread_stopped[i] = 1;
      }
    }
  }
  cycle_counter += 1;
  return rv;
}
*/

/*
#include "uintN_t.h"
#pragma MAIN_MHZ main 400.0
uint32_t main(uint32_t x)
{
  uint32_t rv = {0};
  if(x > 0)
  {
    uint32_t temp;
    temp = temp + 1;
    rv = temp + 1;
  }
  else
  {
    uint32_t temp;
    temp = temp + 2;
    rv = temp + 2;
  }
  
  if(x > 1)
  {
    uint32_t temp = x + 3;
    rv = temp + 3;
  }
  else
  {
    uint32_t temp = x + 4;
    rv = temp + 4;
  }
  
  if(x > 2)
  {
    uint32_t temp = x + 5;
    rv = temp + 5;
  }
  else
  {
    uint32_t temp = x + 6;
    rv = temp + 6;
  }
  
  return rv;
}
*/

/*
// How to un-re-roll differently in time? Aetherling style
// N ratio faster and slower clocks
// Like double pumping dsps?
// 2x faster clock = as low as half resources(iter resource sharing) used iteratively 
//                   OR double throughput
// 2x slower clock = 2x resources 
//                   OR half throughput
uint8_t accum;
uint8_t main(uint1_t en)
{
  if(en) accum += 1;
  return accum;
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
