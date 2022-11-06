// include mem map for this count neighbors functionality
#include "mem_map.h"

#ifndef __PIPELINEC__
// Software access to hardware count neighbors fsm
int32_t count_live_neighbour_cells(int32_t r, int32_t c){
  // Set all input values
  COUNT_NEIGHBORS_HW_IN->x = r;
  COUNT_NEIGHBORS_HW_IN->y = c;
  // Set valid bit
  COUNT_NEIGHBORS_HW_IN->valid = 1;
  // (optionally wait for valid to be cleared indicating started work)
  // Then wait for valid output
  while(COUNT_NEIGHBORS_HW_OUT->valid==0){}
  // Read output
  return COUNT_NEIGHBORS_HW_OUT->count;
}
#endif

#ifdef __PIPELINEC__

TODO pull in code for FSM style frame frame_buffer
so wire up to a new port on frame buffer

// Pull in shared GoL software and hardware count_live_neighbour_cells code
#include "../main.c"
// Hooks to derive hardware FSMs from C code
// Derived fsm from func
#include "count_live_neighbour_cells_FSM.h"
// Wrap up main FSM as top level
#pragma MAIN count_live_neighbour_cells_wrapper
// With global wires for IO
count_live_neighbour_cells_INPUT_t count_neighbors_fsm_in;
count_live_neighbour_cells_OUTPUT_t count_neighbors_fsm_out;
void count_live_neighbour_cells_wrapper()
{
  count_neighbors_fsm_out = count_live_neighbour_cells_FSM(count_neighbors_fsm_in);
}
#endif
