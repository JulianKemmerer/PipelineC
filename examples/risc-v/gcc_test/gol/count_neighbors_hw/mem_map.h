#pragma once

// Count neighbors module
#include "count_neighbors_hw.h"
/*#ifndef COUNT_NEIGHBORS_MEM_MAP_BASE_ADDR
#define COUNT_NEIGHBORS_MEM_MAP_BASE_ADDR 0
#endif*/
#define COUNT_NEIGHBORS_HW_IN_ADDR COUNT_NEIGHBORS_MEM_MAP_BASE_ADDR
static volatile count_neighbors_hw_in_t* COUNT_NEIGHBORS_HW_IN = (count_neighbors_hw_in_t*)COUNT_NEIGHBORS_HW_IN_ADDR;
#define COUNT_NEIGHBORS_HW_OUT_ADDR (COUNT_NEIGHBORS_HW_IN_ADDR + sizeof(count_neighbors_hw_in_t))
static volatile count_neighbors_hw_out_t* COUNT_NEIGHBORS_HW_OUT = (count_neighbors_hw_out_t*)COUNT_NEIGHBORS_HW_OUT_ADDR;

#define COUNT_NEIGHBORS_MEM_MAP_NEXT_ADDR (COUNT_NEIGHBORS_HW_OUT_ADDR + sizeof(count_neighbors_hw_out_t))