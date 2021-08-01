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
//#pragma PART "Ti60F225"

// Most recent (and more likely working) examples towards the bottom of list \/
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
//#include "examples/async_clock_crossing.c"
//#include "examples/clock_crossing.c"
//#include "examples/littleriscy/riscv.c"
//#include "examples/arty/src/eth/work_app.c"
//#include "examples/blink.c"
//#include "examples/NexusProofOfWork/NXSTest_syn.c"
//#include "examples/fir.c"
//#include "examples/arty/src/i2s/i2s_passthrough_app.c"
//#include "examples/arty/src/audio/distortion.c"
//#include "examples/arty/src/i2s/i2s_app.c"
//#include "examples/pipeline_and_fsm.c"
//#include "examples/fosix/main_bram_loopback.c"
//#include "examples/aes/aes.c"
//#include "examples/groestl/groestl.c"
#include "examples/fosix/main_game.c"


// Below is a bunch of recent scratch work - enjoy
/*
#pragma MAIN_MHZ main 900.0
float main(float x, float y)
{
  return x + y;
}
*/

/*
///
///
//READ/RHS OF INPUT implies comb. INPUT READY ASSERTIOn  (does not proceed FMS if not ready)
//RETURN OF OUTPUT implies comb OUTPUT VALID ASSERTION

#pragma MAIN_MHZ main 100.0
#pragma PART "xc7a35ticsg324-1l"
#include "uintN_t.h"
// Inputs 'sampled' at function entry 
//(input regs maybe with valid+ready handshaking)
// Return output 'valid' once when fsm reaches return
//(also maybe with handshaking)
uint8_t main(uint8_t x)
{
  __clk();
  // Equal to input port x 1 cycle ago
  return x; 
}


typedef enum main_STATE_t{
 // Number of states depends on by number of clk++ in code?
 // and while loops + certain functions are sub state machines
 CLK0, // Entry point?
 CLK1,
}main_STATE_t;
typdef struct main_OUTPUT_t
{
  uint1_t input_ready;
  uint8_t RETURN_OUTPUT;
  uint1_t output_valid;
}main_OUTPUT_t;
typdef struct main_INPUT_t
{
  uint1_t input_valid;
  uint8_t x;
  uint1_t output_ready;
}main_INPUT_t;
main_OUTPUT_t main_FSM(main_INPUT_t i)
{
  static main_STATE_t main_STATE;
  // All local vars are regs too 
  //(none here)
  main_OUTPUT_t o;
  o.input_ready = 0;
  o.RETURN_OUTPUT = 0;
  o.output_valid = 0;
  uint8_t RETURN_OUTPUT = 0;
  
  if(main_STATE == CLK0)
  {
    // Special first state signals ready, waits for start
    o.input_ready = 1;
    if(i.input_valid)
    {
      // Nothing to do, next state
      main_STATE = CLK1;
    }
  }
  else if(main_STATE == CLK1)
  {
    // Special last state signals done, waits for ready
    o.output_valid = 1;
    if(i.output_ready)
    {
      o.RETURN_OUTPUT = i.x;
      main_STATE = CLK1;
    }
  }
  
  return o;
}

// Do case with multiple inputs and outputs over duration of funciton call version
// 

// Volatile inputs change after each __clk();
// Such volatile funcs can have a multiple returns
// (hitting one between  __clk()'s)
uint8_t main(volatile uint8_t x)
{
  // Equal to input port x 'now'/comb logic
  return x; 
  __clk();
  // Equal to input port x 1 cycle later
  // still 'now'/comb logic wiring
  return x; 
}

// Need reading input, on RHS to mean something
// And multiple returns ?

// Every expression is a sub fsm of 0 or more cycles?
// Means adding start and done signals to logic from c code?
* // Need built in valid and output signals used by tool
// Like fosix syscall io start, input, output done regs
* // What is RETURN? is it a valid/done signal? built in for FSMs
// All local variables could be regs if used across __clk++'s ?
// Inputs sampled/read EACH STAGE/clock
uint8_t main(uint8_t x)
{
  uint8_t f = foo(x);
  return f;
  __clk();
  uint8_t b = bar(f, x); // x value a clock later
  return b;
}

main_OUTPUT_t main_FSM(main_INPUT_t i)
{
  static main_STATE_t main_STATE;
  // All local vars are regs too 
  static uint8_t f;
  static uint8_t b;
  static 
  main_OUTPUT_t o;
  o.input_ready = 0;
  o.RETURN_OUTPUT = 0;
  o.output_valid = 0;
  uint8_t RETURN_OUTPUT = 0;
  
  if(main_STATE == CLK0)
  {
    // Special first state signals ready, waits for start
    o.input_ready = 1;
    if(i.input_valid)
    {
      // If foo is __clk++ function then need to wrap foo usage
      // For now foo is regular pipelinec single cycle comb function
      f = foo(i.x);
      // Next state
      main_STATE = CLK1;
    }
  }
  else if(main_STATE == CLK1)
  {
    b = bar(f, i.x);
    RETURN_OUTPUT
    // Next state
    main_STATE = CLK2;
  }
  else if(main_STATE == CLK2)
  {
    // Special last state signals done, waits for ready
    o.output_valid = 1;
    if(i.output_ready)
    {
      o.RETURN_OUTPUT = i.x;
      main_STATE = CLK1;
    }
  }
  
  return o;
}
*/
/*
uint8_t main(i)
{
  while(i)
  {
    f = foo(i);
    __clk();
    b = bar(f, i); // i value a clock later
    return b;
  }
}
*/
/*
// Compiler sees this as a Silice function
// A big derived fsm
uint8_t main()
{
  uint8_t led;
  // a 28 bits unsigned integer register
  uint28_t counter = 0;
  
  // How does Silice derive?
  // "the loop takes exactly one cycle to execute:
  // we have one increment per cycle at 50 MHz the clock frequency"  
  while (1) {              // forever
    // LEDs updated every clock with the 8 most significant bits
    led = uint28_27_20(counter);
    counter = counter + 1; // increment counter
    // If its assumed comb logic unless clocks are inserted
    // Ex. :=  assign right to left at each rising clock
    //     ++: wait on clock
    // How to do that in PipelineC?
    __clk(); // Or something?
  }
  return led;
}

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
