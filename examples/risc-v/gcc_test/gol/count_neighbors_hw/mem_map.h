#pragma once

// Count neighbors module
#include "count_neighbors_hw.h"

/*#ifndef COUNT_NEIGHBORS_MEM_MAP_BASE_ADDR
#define COUNT_NEIGHBORS_MEM_MAP_BASE_ADDR 0
#endif*/
#define COUNT_NEIGHBORS_MEM_MAP_BASE_ADDR GOL_BASE_ADDR
#define COUNT_NEIGHBORS_HW_IN_ADDR COUNT_NEIGHBORS_MEM_MAP_BASE_ADDR
#define COUNT_NEIGHBORS_HW_OUT_ADDR (COUNT_NEIGHBORS_HW_IN_ADDR + sizeof(count_neighbors_in_t))
#define COUNT_NEIGHBORS_MEM_MAP_NEXT_ADDR (COUNT_NEIGHBORS_HW_OUT_ADDR + sizeof(count_neighbors_out_t))

FSM_IO_MEM_MAP_VARS_DECL(
  COUNT_NEIGHBORS_HW, 
  count_neighbors_out_valid_t, COUNT_NEIGHBORS_HW_OUT_ADDR, 
  count_neighbors_in_valid_t, COUNT_NEIGHBORS_HW_IN_ADDR)