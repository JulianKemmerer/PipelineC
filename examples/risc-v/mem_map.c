// GoL accelerators are enabled inside hw.c (some or none)
#include "gcc_test/gol/hw.c"

// Memory mapped IO addresses to drive hardware wires
// ex. debug ports, devices, accelerator FSMs
#include "mem_map.h"

// Debug ports for simulation
DEBUG_OUTPUT_DECL(uint1_t, halt) // Stop/done signal
DEBUG_OUTPUT_DECL(int32_t, main_return) // Output from main()
#include "leds/leds_port.c"
typedef struct mem_map_out_t
{
  uint1_t addr_is_mapped;
  uint32_t rd_data;
}mem_map_out_t;
mem_map_out_t mem_map_module(
  uint32_t addr,
  uint32_t wr_data,
  uint1_t wr_byte_ens[4])
{
  // Outputs
  mem_map_out_t o;

  // Extra registers as needed
  #ifdef FRAME_BUFFER
  #ifndef FRAME_BUFFER_DISABLE_CPU_PORT
  VALID_PULSE_IO_REGS_DECL(
    cpu_frame_buffer, frame_buffer_outputs_t, frame_buffer_inputs_t)
  VALID_PULSE_IO_REGS_DECL(
    cpu_line_bufs, line_bufs_outputs_t, line_bufs_inputs_t)
  #endif
  #endif
  // GoL accelerators
  #ifdef COUNT_NEIGHBORS_IS_MEM_MAPPED
  FSM_IO_REGS_DECL_2INPUTS(
    count_neighbors, count_neighbors_out_valid_t,
    count_neighbors_in_valid_t, x, y)
  #endif
  #ifdef CELL_NEXT_STATE_IS_MEM_MAPPED
  FSM_IO_REGS_DECL_2INPUTS(
    cell_next_state, cell_next_state_out_valid_t,
    cell_next_state_in_valid_t, x, y)
  #endif
  #ifdef NEXT_STATE_BUF_RW_IS_MEM_MAPPED
  FSM_IO_REGS_DECL(next_state_buf_rw)
  #endif
  #ifdef MULTI_NEXT_STATE_BUF_RW_IS_MEM_MAPPED
  FSM_IO_REGS_DECL(multi_next_state_buf_rw)
  #endif

  // Memory muxing/select logic
  if(addr==RETURN_OUTPUT_ADDR){
    // The return/halt debug signal
    o.addr_is_mapped = 1;
    o.rd_data = 0;
    if(wr_byte_ens[0]){
      main_return = wr_data;
      halt = 1;
    }
  }
  WORD_MM_ENTRY(LEDS_ADDR, leds)
  #ifdef FRAME_BUFFER
  #ifndef FRAME_BUFFER_DISABLE_CPU_PORT
  IN_REG_WORD_MM_ENTRY(FRAME_BUF_X_ADDR, cpu_frame_buffer, x)
  IN_REG_WORD_MM_ENTRY(FRAME_BUF_Y_ADDR, cpu_frame_buffer, y)
  VALID_PULSE_RW_DATA_WORD_MM_ENTRY(FRAME_BUF_DATA_ADDR, cpu_frame_buffer)
  IN_REG_WORD_MM_ENTRY(LINE_BUF_SEL_ADDR, cpu_line_bufs, line_sel)
  IN_REG_WORD_MM_ENTRY(LINE_BUF_X_ADDR, cpu_line_bufs, x)
  VALID_PULSE_RW_DATA_WORD_MM_ENTRY(LINE_BUF_DATA_ADDR, cpu_line_bufs)
  #endif
  #endif
  // GoL accelerators
  #ifdef COUNT_NEIGHBORS_IS_MEM_MAPPED
  FSM_IO_REG_STRUCT_MM_ENTRY(COUNT_NEIGHBORS_HW, count_neighbors)
  #endif
  #ifdef CELL_NEXT_STATE_IS_MEM_MAPPED
  FSM_IO_REG_STRUCT_MM_ENTRY(CELL_NEXT_STATE_HW, cell_next_state)
  #endif
  #ifdef NEXT_STATE_BUF_RW_IS_MEM_MAPPED
  FSM_IO_REG_STRUCT_MM_ENTRY(NEXT_STATE_BUF_RW_HW, next_state_buf_rw)
  #endif
  #ifdef MULTI_NEXT_STATE_BUF_RW_IS_MEM_MAPPED
  FSM_IO_REG_STRUCT_MM_ENTRY(MULTI_NEXT_STATE_BUF_RW_HW, multi_next_state_buf_rw)
  #endif

  // Output registers as needed
  #ifdef FRAME_BUFFER
  #ifndef FRAME_BUFFER_DISABLE_CPU_PORT
  // Connect frame buffer outputs to registers for better fmax
  OUT_REG(cpu_frame_buffer)
  OUT_REG(cpu_line_bufs)
  #endif
  #endif
  // GoL accelerators
  #ifdef COUNT_NEIGHBORS_IS_MEM_MAPPED
  FSM_OUT_REG_1OUTPUT(count_neighbors, count)
  #endif
  #ifdef CELL_NEXT_STATE_IS_MEM_MAPPED
  FSM_OUT_REG_1OUTPUT(cell_next_state, is_alive)
  #endif
  #ifdef NEXT_STATE_BUF_RW_IS_MEM_MAPPED
  FSM_OUT_REG(next_state_buf_rw)
  #endif
  #ifdef MULTI_NEXT_STATE_BUF_RW_IS_MEM_MAPPED
  FSM_OUT_REG(multi_next_state_buf_rw)
  #endif

  return o;
}