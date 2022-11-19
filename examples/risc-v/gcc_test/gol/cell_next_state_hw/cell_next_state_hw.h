#pragma once

// Derive if C code is parsed+used
#ifndef __PIPELINEC__
#ifdef CELL_NEXT_STATE_IS_MEM_MAPPED
#define CELL_NEXT_STATE_IGNORE_C_CODE
#endif
#ifdef CELL_NEXT_STATE_IS_HW
#define CELL_NEXT_STATE_IGNORE_C_CODE
#endif
#endif

// IO types
typedef struct cell_next_state_in_t{
  int32_t x;
  int32_t y;
}cell_next_state_in_t;
typedef struct cell_next_state_out_t{
  int32_t is_alive;
}cell_next_state_out_t;
FSM_IO_TYPES_WRAPPER(cell_next_state)

// To-from bytes conversion funcs
#ifdef __PIPELINEC__
#include "cell_next_state_in_valid_t_bytes_t.h"
#include "cell_next_state_out_valid_t_bytes_t.h"
#endif

