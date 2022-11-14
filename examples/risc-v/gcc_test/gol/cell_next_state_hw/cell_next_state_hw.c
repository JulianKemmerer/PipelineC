// include mem map for this functionality
#ifdef CELL_NEXT_STATE_IS_MEM_MAPPED

#include "mem_map.h"

#ifndef __PIPELINEC__
// Software access to hardware fsm
int32_t cell_next_state(int32_t x, int32_t y){
  FSM_MEM_MAP_VARS_FUNC_BODY_2INPUTS(CELL_NEXT_STATE_HW, is_alive, x, y)
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
FSM_MAIN_IO_WRAPPER(cell_next_state)
#endif

#endif
