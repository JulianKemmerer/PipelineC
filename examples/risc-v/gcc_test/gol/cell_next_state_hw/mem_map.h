#pragma once

// Count neighbors module
#include "cell_next_state_hw.h"

/*#ifndef CELL_NEXT_STATE_MEM_MAP_BASE_ADDR
#define CELL_NEXT_STATE_MEM_MAP_BASE_ADDR 0
#endif*/

#define CELL_NEXT_STATE_HW_IN_ADDR CELL_NEXT_STATE_MEM_MAP_BASE_ADDR
#define CELL_NEXT_STATE_HW_OUT_ADDR (CELL_NEXT_STATE_HW_IN_ADDR + sizeof(cell_next_state_hw_in_t))
#define CELL_NEXT_STATE_MEM_MAP_NEXT_ADDR (CELL_NEXT_STATE_HW_OUT_ADDR + sizeof(cell_next_state_hw_out_t))

FSM_IO_MEM_MAP_VARS_DECL(
  CELL_NEXT_STATE_HW, 
  cell_next_state_hw_out_t, CELL_NEXT_STATE_HW_OUT_ADDR, 
  cell_next_state_hw_in_t, CELL_NEXT_STATE_HW_IN_ADDR)


