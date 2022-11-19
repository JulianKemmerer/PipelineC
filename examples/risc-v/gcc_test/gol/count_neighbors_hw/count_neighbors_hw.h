#pragma once

// Derive if C code is parsed+used
#ifndef __PIPELINEC__
#ifdef COUNT_NEIGHBORS_IS_MEM_MAPPED
#define COUNT_NEIGHBORS_IGNORE_C_CODE
#endif
#ifdef COUNT_NEIGHBORS_IS_HW
#define COUNT_NEIGHBORS_IGNORE_C_CODE
#endif
#endif

// IO types
typedef struct count_neighbors_in_t{
  int32_t x;
  int32_t y;
}count_neighbors_in_t;
typedef struct count_neighbors_out_t{
  int32_t count;
}count_neighbors_out_t;
FSM_IO_TYPES_WRAPPER(count_neighbors)

// To-from bytes conversion funcs
#ifdef __PIPELINEC__
#include "count_neighbors_in_valid_t_bytes_t.h"
#include "count_neighbors_out_valid_t_bytes_t.h"
#endif

