// Full part string examples:
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
#pragma PART "xc7a35ticsg324-1l"

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
//#include "examples/arty/src/fosix/main_bram_loopback.c"
//#include "examples/aes/aes.c"
//#include "examples/groestl/groestl.c"
#include "examples/arty/src/fosix/main_game.c"

// Below is a bunch of recent scratch work - enjoy

/*
#pragma MAIN_MHZ array_test 100.0
#pragma PART "xc7a35ticsg324-1l"
#include "uintN_t.h"
typedef struct my_out_array_t
{
  uint8_t data[32];
}my_out_array_t;
my_out_array_t array_test(uint8_t data[64]) {
__vhdl__("\
begin \n\
  -- a uint8_t_64 assigning to a uint8_t_32 \n\
  return_output.data <= data; \n\
");
}
*/

  /*
  uint8_t out_data[32] = data;
  my_out_array_t rv;
  rv.data = out_data;
  return rv;*/



/*
#include "uintN_t.h"
#pragma MAIN_MHZ single_pattern_recognizer_tb 100.0

#define PATTERN_SIZE 4
#define pattern_or_tree uint1_array_or4
#define PATTERN {1,5,6,2}
typedef struct single_pattern_recognizer_t
{
  uint1_t error;
  uint32_t occurences;
}single_pattern_recognizer_t;
single_pattern_recognizer_t single_pattern_recognizer(uint8_t num)
{
  static uint8_t pattern[PATTERN_SIZE] = PATTERN;
  static uint32_t pattern_pos_counter[PATTERN_SIZE];
  static uint32_t occurences;

  // Logic for matching first num in pattern is always active
  pattern_pos_counter[0] = 1;
  
  // Does new number match any active part of pattern
  uint1_t pattern_pos_active_and_matching[PATTERN_SIZE];
  uint32_t i;
  for(i=0; i<PATTERN_SIZE;i+=1)
  {
    pattern_pos_active_and_matching[i] = 
      (pattern[i]==num) & (pattern_pos_counter[i]>0);
  }
  
  // Binary tree ORing bits together for single match flag
  uint1_t found_match = pattern_or_tree(pattern_pos_active_and_matching);
  
  // Update next pattern position counts/active state
  // based on current positions that were active and matching
  for(i=0; i<PATTERN_SIZE;i+=1)
  {
    if(pattern_pos_active_and_matching[i])
    {
      // Decrement count at current pos
      pattern_pos_counter[i] -= 1;
      // Is this the last num in pattern sequence?
      if(i==(PATTERN_SIZE-1))
      {
        // This this was an full occurance of the pattern
        occurences += 1;
      }
      else
      {
        // Increment count at next pos
        pattern_pos_counter[i+1] += 1;
      }
    }
  }
  
  single_pattern_recognizer_t o;
  o.error = !found_match;
  o.occurences = occurences;
  return o;  
}

void single_pattern_recognizer_tb()
{
  #define INPUT_SIZE 12
  static uint8_t nums[INPUT_SIZE] = {1,3,5,1,5,6,2,3,6,2,4,4};
  static uint32_t i;
  
  single_pattern_recognizer_t spr = single_pattern_recognizer(nums[i]);
  printf("Input[%d] %d, Error? %d, Total Occurences %d\n",
    i, nums[i], spr.error, spr.occurences);
  i+=1;
}
*/

/*
pattern_recognizer()
{
  
  for pattern_i len patterns
  {
    pattern_match_positions[pattern_i] = pattern_pos_matches(patterns[pattern_i], num)
    
    // Is this pattern pos active?
    
    for pattern_match_pos_i in 
    {
      if(pattern_pos_active_count[pattern_i][pattern_match_pos_i] > 0)
      {
        pattern_pos_active_count[pattern_i][pattern_match_pos_i] -= 1;
        
      }
    }
    if(pattern_pos_active[i]
    
  }
  
  
  For eahc pattern see if next num matches any positons, can match multiple
  (multiple instances of pattern)
  
  
  
  like open close paren pairs? ish?
  Then check if there is an active fsm waiting waiting on that pos in pattern
  bit flag
  if active increment counter for num of insts of that/next? position
  if not start by setting bit to later check?
  
  
  
}
*/

/*
#include "uintN_t.h"
#pragma MAIN_MHZ my_strlen_tb 100.0
#define SIZE 16
typedef struct my_str_t
{
  char chars[SIZE];
}my_str_t;
void my_strlen_tb()
{
  my_str_t inputs[3];
  inputs[0].chars = "yes";
  inputs[1].chars = "no";
  inputs[2].chars = "PipelineC";
  
  uint32_t i;
  for(i=0; i<3; i+=1)
  {
    uint32_t len = strlen(inputs[i].chars);
    printf("%s len is %d\n", inputs[i].chars, len);
  }
}
*/

/*
// What is RETURN? is it a valid/done signal? built in for FSMs
// ...yeah?
// Are inputs fixed/registered?
// Need built in valid and output signals used by tool
uint8_t main(uint8_t i)
{
  __clk++;
  return i;
}
*/
/*
// Every expression is a sub fsm of 0 or more cycles?
// Means adding start and done signals to logic from c code?
// All local variables could be regs if used across __clk++'s ?
// Inputs sampled/read in first stage, can be reread in later clocks for new data
uint8_t main(i)
{
  f = foo(i);
  __clk++;
  b = bar(f, i); // i value a clock later
  return b;
}

typedef enum main_STATE_t{
 // Number of states depends on by number of clk++ in code?
 // while loops are sub state machines
 // functions are sub state machines
 CLK0, // Entry point? Comb logic from inputs into through CLK0 logic
 CLK1,
}main_STATE_t;
uint8_t main(i)
{
  static main_STATE_t main_STATE;
  uint8_t RETURN_OUTPUT = 0;
  // All local vars are regs
  static f, b;
  
  if(main_STATE == CLK0)
  {
    f = foo(i);
    // HOW TO KNOW WHEN FOO FSM IS DONE?
    // RETURN becomes done signal/regs? inputs too?
    // What is return val here? default zeros?
  }
  else if(main_STATE == CLK1)
  {
    b = bar(f, i); // i value a clock later
    RETURN_OUTPUT = b;
  }
  
  return RETURN_OUTPUT;
}


uint8_t main(i)
{
  while(i)
  {
    f = foo(i);
    __clk++;
    b = bar(f, i); // i value a clock later
    return b;
  }
}




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
    __clk++; // Or something?
  }
  return led;
}


/*
#include "uintN_t.h"
//#pragma FUNC_MULT_STYLE mult_tree fabric
#define N 1024
#define LOG2_N 10
#pragma MAIN_MHZ mult_tree 940.0
uint16_t mult_tree(uint16_t input[N])
{
  // A binary tree of ops 
  // This binary tree has 
  //    N elements at the base
  //    LOG2_N + 1 levels in the tree
  // Oversized 2D array, unused elements optimize away
  uint16_t tree_nodes[LOG2_N+1][N];
  // Ex. N=16 
  // Calculate 'as parallel as possible' using a binary tree 
  //    Level 0: 16 input values  
  //    Level 1: 8 ops in parallel 
  //    Level 2: 4 ops in parallel 
  //    Level 3: 2 ops in parallel 
  //    Level 4: 1 final op  

  // The first level of the tree is input values
  uint32_t i;
  for(i=0; i < N; i+=1)
  {
    tree_nodes[0][i] = input[i];
  }
    
  // Binary tree compuation starting at level 1
  uint32_t n_ops = N/2; 
  uint32_t level; 
  for(level=1; level<(LOG2_N+1); level+=1) 
  {   
    // Parallel ops  
    for(i=0; i<n_ops; i+=1)  
    { 
      tree_nodes[level][i] = tree_nodes[level-1][i*2] * tree_nodes[level-1][(i*2)+1]; 
    } 
      
    // Each level decreases ops by half  
    n_ops = n_ops / 2;  
  } 
    
  // Result is last node in tree
  uint16_t rv = tree_nodes[LOG2_N][0];
    
  return rv;
}
*/

/*
#include "uintN_t.h"
#pragma MAIN_MHZ mult 800.0
#pragma FUNC_MULT_STYLE my_func inferred
uint32_t my_func(uint16_t a, uint16_t b) {
  return a * b;
}
*/
/*
#include "arrays.h"
uint1_t and_xor(uint1_t c_i, uint1_t a_j, uint1_t b_ij){
  return c_i ^ (a_j & b_ij);
}
#pragma MAIN_MHZ clmul 1000.0
uint128_t clmul(uint1_t a[64], uint1_t b[64]) {
    uint1_t c[128];
    ARRAY_SET(c, 0, 128)

    uint32_t i, j;
    for (i = 0; i < 64; i += 1) {
        c[i] = a[0] & b[i];
        for (j = 1; j < i; j += 1) {
            c[i] = and_xor(c[i], a[j], b[i - j]);
        }
    }

    for (i = 64; i < 127; i += 1) {
        c[i] = 0;
        for (j = i - 63; j < 63; j += 1) {
            c[i] = and_xor(c[i], a[j], b[i - j]);
        }
    }

    return uint1_array128_be(c);
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
