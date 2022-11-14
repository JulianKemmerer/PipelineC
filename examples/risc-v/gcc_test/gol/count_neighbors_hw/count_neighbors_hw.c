// include mem map for this count neighbors functionality
#ifdef COUNT_NEIGHBORS_IS_MEM_MAPPED

#include "mem_map.h"

#ifndef __PIPELINEC__
// Software access to hardware count neighbors fsm
int32_t count_neighbors(int32_t x, int32_t y){
  FSM_MEM_MAP_VARS_FUNC_BODY_2INPUTS(COUNT_NEIGHBORS_HW, count, x, y)
}
#endif

#ifdef __PIPELINEC__
// Pull in FSM style hooks to frame buffer
#include "../../../frame_buffer.c"
// Pull in shared GoL software and hardware count_neighbors code
#include "../main.c"
// Hooks to derive hardware FSMs from C code
// Derived fsm from func
#include "count_neighbors_FSM.h"
// Wrap up main FSM as top level
FSM_MAIN_IO_WRAPPER(count_neighbors)
#endif

#endif
