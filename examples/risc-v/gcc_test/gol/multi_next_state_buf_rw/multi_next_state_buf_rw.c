#pragma once

// Pull in next_state_buf_rw.c like a header for next_state_buf_rw
#include "../next_state_buf_rw/next_state_buf_rw.c"

// IO types
typedef struct multi_next_state_buf_rw_in_t{
  next_state_buf_rw_in_t next_state_buf_rw_inputs;
}multi_next_state_buf_rw_in_t;
typedef struct multi_next_state_buf_rw_out_t{
  int32_t dummy; // Unused
}multi_next_state_buf_rw_out_t;
FSM_IO_TYPES_WRAPPER(multi_next_state_buf_rw)
#ifdef MULTI_NEXT_STATE_BUF_RW_IS_MEM_MAPPED
// To-from bytes conversion funcs
#ifdef __PIPELINEC__
#include "multi_next_state_buf_rw_in_valid_t_bytes_t.h"
#include "multi_next_state_buf_rw_out_valid_t_bytes_t.h"
#endif
#endif

// Software version
#ifndef __PIPELINEC__
#ifdef MULTI_NEXT_STATE_BUF_RW_IS_MEM_MAPPED
#define MULTI_NEXT_STATE_BUF_RW_IGNORE_C_CODE
#endif
#ifdef MULTI_NEXT_STATE_BUF_RW_IS_HW
#define MULTI_NEXT_STATE_BUF_RW_IGNORE_C_CODE
#endif
#endif
#ifndef MULTI_NEXT_STATE_BUF_RW_IGNORE_C_CODE
multi_next_state_buf_rw_out_t multi_next_state_buf_rw(multi_next_state_buf_rw_in_t inputs)
{
  next_state_buf_rw_in_t func_in = inputs.next_state_buf_rw_inputs;
  for (int i = 0; i < NUM_THREADS; i+=1)
  {
    func_in.frame_x = inputs.next_state_buf_rw_inputs.frame_x + i;
    next_state_buf_rw_out_t func_out;
    func_out = next_state_buf_rw(func_in);
    // No outputs to use
  }
  // No outputs
  multi_next_state_buf_rw_out_t outputs;
  return outputs;
}
#endif

// Memory mapped hardware functionality
#ifdef MULTI_NEXT_STATE_BUF_RW_IS_MEM_MAPPED

// Code like FSM_MAIN_IO_WRAPPER that instantiates N copies of next_state_buf_rw
// Isnt derived FSM function by can make look like one
// TODO MACROs
#ifdef __PIPELINEC__
typedef struct multi_next_state_buf_rw_INPUT_t{
  uint1_t input_valid;
  uint1_t output_ready;
  multi_next_state_buf_rw_in_t inputs;
}multi_next_state_buf_rw_INPUT_t;
typedef struct multi_next_state_buf_rw_OUTPUT_t{
  uint1_t output_valid;
  uint1_t input_ready;
  multi_next_state_buf_rw_out_t return_output;
}multi_next_state_buf_rw_OUTPUT_t;
multi_next_state_buf_rw_INPUT_t multi_next_state_buf_rw_fsm_in;
multi_next_state_buf_rw_OUTPUT_t multi_next_state_buf_rw_fsm_out;
#pragma MAIN multi_wrapper
void multi_wrapper()
{
  // IO for each FSM isntance, w/ extra registers
  static next_state_buf_rw_INPUT_t fsm_in_reg[NUM_THREADS];
  static next_state_buf_rw_OUTPUT_t fsm_out_reg[NUM_THREADS];

  // Inputs are only valid if all FSM instances ready to start
  uint1_t all_fsms_input_ready;
  // Only ready for output once all are done and valid
  uint1_t all_fsms_valid_output;
  // Were all FSMs ready/valid? (feedback)
  all_fsms_input_ready = 1;
  all_fsms_valid_output = 1;
  uint32_t i;
  for (i = 0; i < NUM_THREADS; i+=1)
  {
    all_fsms_input_ready &= fsm_out_reg[i].input_ready;
    all_fsms_valid_output &= fsm_out_reg[i].output_valid;
  }
  // Gated output valid ready
  multi_next_state_buf_rw_fsm_out.output_valid = all_fsms_valid_output;
  multi_next_state_buf_rw_fsm_out.input_ready = all_fsms_input_ready;

  // The N instances of FSM with input valid ready gated
  next_state_buf_rw_INPUT_t fsm_in[NUM_THREADS];
  for (i = 0; i < NUM_THREADS; i+=1)
  {
    fsm_in[i].input_valid = all_fsms_input_ready & multi_next_state_buf_rw_fsm_in.input_valid;
    fsm_in[i].output_ready = all_fsms_valid_output & multi_next_state_buf_rw_fsm_in.output_ready;
    fsm_in[i].inputs = multi_next_state_buf_rw_fsm_in.inputs.next_state_buf_rw_inputs;
    fsm_in[i].inputs.frame_x = multi_next_state_buf_rw_fsm_in.inputs.next_state_buf_rw_inputs.frame_x + i;
    fsm_out_reg[i] = next_state_buf_rw_FSM(fsm_in_reg[i]);
  }
  fsm_in_reg = fsm_in;
}
#endif

// Define addresses:
/*#ifndef MULTI_NEXT_STATE_BUF_RW_MEM_MAP_BASE_ADDR
#define MULTI_NEXT_STATE_BUF_RW_MEM_MAP_BASE_ADDR 0
#endif*/
#define MULTI_NEXT_STATE_BUF_RW_MEM_MAP_BASE_ADDR GOL_BASE_ADDR
#define MULTI_NEXT_STATE_BUF_RW_HW_IN_ADDR MULTI_NEXT_STATE_BUF_RW_MEM_MAP_BASE_ADDR
#define MULTI_NEXT_STATE_BUF_RW_HW_OUT_ADDR (MULTI_NEXT_STATE_BUF_RW_HW_IN_ADDR + sizeof(multi_next_state_buf_rw_in_valid_t))
#define MULTI_NEXT_STATE_BUF_RW_MEM_MAP_NEXT_ADDR (MULTI_NEXT_STATE_BUF_RW_HW_IN_ADDR + sizeof(multi_next_state_buf_rw_out_valid_t))
// Software access to hardware fsm
#ifndef __PIPELINEC__
// Declare memory mapped function and variables
FSM_MEM_MAP_FUNC_DECL(multi_next_state_buf_rw, MULTI_NEXT_STATE_BUF_RW_HW)
#endif
#endif