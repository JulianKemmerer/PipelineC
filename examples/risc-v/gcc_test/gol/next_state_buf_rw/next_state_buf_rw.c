#pragma once

// IO types
#define NEXT_STATE_LINE_WRITE 1
#define LINE_READ_FRAME_WRITE 0
typedef struct next_state_buf_rw_in_t{
  int32_t frame_x;
  int32_t frame_y;
  int32_t line_sel;
  int32_t op_sel;
}next_state_buf_rw_in_t;
typedef struct next_state_buf_rw_out_t{
  int32_t dummy; // unused
}next_state_buf_rw_out_t;
// IO _valid types wrapped with FSM handshake signals
FSM_IO_TYPES_WRAPPER(next_state_buf_rw)
// To-from bytes conversion funcs
#ifdef NEXT_STATE_BUF_RW_IS_MEM_MAPPED
#ifdef __PIPELINEC__
#include "next_state_buf_rw_in_valid_t_bytes_t.h"
#include "next_state_buf_rw_out_valid_t_bytes_t.h"
#endif
#endif

// If hardware then pull in software main.c like a header for cell_next_state
#ifdef __PIPELINEC__
#include "../main.c"
#endif

// Software version (or can be used to derived hardware FSM)
#ifndef __PIPELINEC__
#ifdef NEXT_STATE_BUF_RW_IS_MEM_MAPPED
#define NEXT_STATE_BUF_RW_IGNORE_C_CODE
#endif
#ifdef NEXT_STATE_BUF_RW_IS_HW
#define NEXT_STATE_BUF_RW_IGNORE_C_CODE
#endif
#endif
#ifndef NEXT_STATE_BUF_RW_IGNORE_C_CODE
next_state_buf_rw_out_t next_state_buf_rw(next_state_buf_rw_in_t inputs)
{
  next_state_buf_rw_out_t outputs;
  if(inputs.op_sel==NEXT_STATE_LINE_WRITE){
    __clk();
    int32_t cell_alive_next = cell_next_state(inputs.frame_x, inputs.frame_y);
    line_buf_write(inputs.line_sel, inputs.frame_x, cell_alive_next);  
  }else{ // LINE_READ_FRAME_WRITE
    __clk();
    int32_t rd_data = line_buf_read(inputs.line_sel, inputs.frame_x);
    frame_buf_write(inputs.frame_x, inputs.frame_y, rd_data);
  }
  return outputs;
}
#endif

// Hooks to derive hardware FSMs from C code function
#ifdef __PIPELINEC__
#ifdef NEXT_STATE_BUF_RW_IS_HW
#include "next_state_buf_rw_FSM.h"
#endif
#endif

// Memory mapped hardware functionality
#ifdef NEXT_STATE_BUF_RW_IS_MEM_MAPPED
// Wrap up main FSM as top level if mem mapped
FSM_MAIN_IO_WRAPPER(next_state_buf_rw)
// Define addresses:
/*#ifndef NEXT_STATE_BUF_RW_MEM_MAP_BASE_ADDR
#define NEXT_STATE_BUF_RW_MEM_MAP_BASE_ADDR 0
#endif*/
#define NEXT_STATE_BUF_RW_MEM_MAP_BASE_ADDR GOL_BASE_ADDR
#define NEXT_STATE_BUF_RW_HW_IN_ADDR NEXT_STATE_BUF_RW_MEM_MAP_BASE_ADDR
#define NEXT_STATE_BUF_RW_HW_OUT_ADDR (NEXT_STATE_BUF_RW_HW_IN_ADDR + sizeof(next_state_buf_rw_in_valid_t))
#define NEXT_STATE_BUF_RW_MEM_MAP_NEXT_ADDR (NEXT_STATE_BUF_RW_HW_IN_ADDR + sizeof(next_state_buf_rw_out_valid_t))
// Software access to hardware fsm
#ifndef __PIPELINEC__
// Declare memory mapped function and variables
FSM_MEM_MAP_FUNC_DECL(next_state_buf_rw, NEXT_STATE_BUF_RW_HW)
#endif
#endif