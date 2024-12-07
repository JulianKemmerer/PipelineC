#include "uintN_t.h"  // uintN_t types for any N

// Install+configure synthesis tool then specify part here
#pragma PART "ICE40UP5K-SG48" // ice40 (pico-ice)
//#pragma PART "xc7a100tcsg324-1" // Artix 7 100T (Arty)

typedef enum my_state_t{
  STATE_A,
  STATE_B,
  STATE_C
}my_state_t;



// 'Called'/'Executing' every 40ns (25MHz)
#pragma MAIN_MHZ main 25.0
typedef struct my_fsm_outputs_t{
  // Module output signals
  char some_output_signal;
}my_fsm_outputs_t;
my_fsm_outputs_t main(
  // Module input signals
  uint1_t some_input_signal
){
  // static = registers
  static my_state_t state; // state register
  // output wires
  my_fsm_outputs_t outputs;
  // State machine logic
  if(state==STATE_A){
    printf("State A!\n");
    outputs.some_output_signal = 'A';
    state = STATE_B;
  }else if(state==STATE_B){
    printf("State B!\n");
    outputs.some_output_signal = 'B';
    state = STATE_C;
  }else{// if(state==STATE_C){
    printf("State C!\n");
    outputs.some_output_signal = 'C';
    if(some_input_signal){
      state = STATE_A;
    }else{
      printf("Not starting over yet!\n");
    }
  }
  return outputs;
}
