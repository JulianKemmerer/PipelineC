// include mem map for this count neighbors functionality
#include "mem_map.h"

#ifndef __PIPELINEC__
// Software access to hardware fsm
int32_t cell_next_state(int32_t x, int32_t y){
  // Set all input values
  CELL_NEXT_STATE_HW_IN->x = x;
  CELL_NEXT_STATE_HW_IN->y = y;
  // Set valid bit
  CELL_NEXT_STATE_HW_IN->valid = 1;
  // (optionally wait for valid to be cleared indicating started work)
  // Then wait for valid output
  while(CELL_NEXT_STATE_HW_OUT->valid==0){}
  // Read outputs
  return CELL_NEXT_STATE_HW_OUT->is_alive;
}
#endif

#ifdef __PIPELINEC__
// Pull in FSM style hooks to frame buffer
#include "../../../frame_buffer.c"
// Pull in shared GoL software and hardware function code
#include "../main.c"
// Hooks to derive hardware FSMs from C code
// Derived fsm from func
#include "cell_next_state_FSM.h"
// Wrap up main FSM as top level
#pragma MAIN cell_next_state_wrapper
// With global wires for IO
cell_next_state_INPUT_t cell_next_state_fsm_in;
cell_next_state_OUTPUT_t cell_next_state_fsm_out;
void cell_next_state_wrapper()
{
  cell_next_state_fsm_out = cell_next_state_FSM(cell_next_state_fsm_in);
}
#endif
