#include "axi/axi_shared_bus.h"
#include "stream/stream.h"
#include "global_func_inst.h"
#include "pixel_t_bytes_t.h"
#include "../types.h"

// FSM that reads from draw rect command fifo
// and outputs pixels and write addresses to draw the rect into frame buffer
//  need a pipeline for pos_to_addr? for now NO...
typedef struct gpu_rect_iter_fsm_t{
  uint1_t ready_for_cmd_in;
  pixel_t p;
  uint32_t addr;
  uint1_t valid_out;
}gpu_rect_iter_fsm_t;
gpu_rect_iter_fsm_t gpu_rect_iter_fsm(
  stream(draw_rect_t) cmd_in,
  uint1_t ready_for_pixel_and_addr
){
  gpu_rect_iter_fsm_t o;
  static uint1_t state_is_GET_CMD = 1;
  static draw_rect_t cmd;
  static uint16_t i;
  static uint16_t j;
  if(state_is_GET_CMD){
    o.ready_for_cmd_in = 1;
    if(cmd_in.valid & o.ready_for_cmd_in){
      cmd = cmd_in.data;
      i = cmd.start_x;
      j = cmd.start_y;
      state_is_GET_CMD = 0;
    }
  }else{ /*state is iterating output pixels*/
    o.p = cmd.color;
    o.addr = pos_to_addr(i, j);
    o.valid_out = 1;
    if(o.valid_out & ready_for_pixel_and_addr){
      // Increment to iterate over rectangle bounds
      // for (int32_t i = start_x; i < end_x; i++)
      //   for (int32_t j = start_y; j < end_y; j++)
      if(i<(cmd.end_x-1)){
        i += 1;
      }else{
        i = cmd.start_x;
        if(j<(cmd.end_y-1)){
          j += 1;
        }else{
          //j = cmd.start_y;
          state_is_GET_CMD = 1;
        }
      }
    }
  }
  return o;
}

// Globally visible fifo of commands that CPU will load
GLOBAL_STREAM_FIFO(draw_rect_t, gpu_draw_cmd_fifo, 16)

// Globally visible AXI bus for this module to talk to frame buffer
axi_shared_bus_t_dev_to_host_t gpu_axi_host_from_dev;
axi_shared_bus_t_host_to_dev_t gpu_axi_host_to_dev;

#pragma MAIN gpu_main
void gpu_main()
{
  // Take commands and produce stream of pixels and addresses
  DECL_FEEDBACK_WIRE(uint1_t, ready_for_pixel_and_addr)
  gpu_rect_iter_fsm_t rect_iter = gpu_rect_iter_fsm(
    gpu_draw_cmd_fifo_out,
    ready_for_pixel_and_addr
  );
  gpu_draw_cmd_fifo_out_ready = rect_iter.ready_for_cmd_in;
  
  // Stream pixels with address into ram with some type conversion and helper FSM
  uint8_t wr_bytes[4] = pixel_t_to_bytes(rect_iter.p);
  uint32_t word_in = uint8_array4_le(wr_bytes);
  axi_write_t axi_write_info = axi_addr_data_to_write(rect_iter.addr, word_in);
  gpu_axi_host_to_dev = axi_shared_bus_t_HOST_TO_DEV_NULL;
  ready_for_pixel_and_addr = 0;
  if(rect_iter.valid_out){
    axi_shared_bus_t_write_start_logic_outputs_t write_start = 
      axi_shared_bus_t_write_start_logic(
      axi_write_info.req,
      axi_write_info.data, 
      1,
      gpu_axi_host_from_dev.write
    );
    gpu_axi_host_to_dev.write = write_start.to_dev;
    ready_for_pixel_and_addr = write_start.ready_for_inputs;
  }

  // Drop all write responses
  gpu_axi_host_to_dev.write.resp_ready = 1;
}