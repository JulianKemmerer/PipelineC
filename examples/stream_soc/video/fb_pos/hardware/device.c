// Include types for axi shared bus axi_shared_bus_t
#include "axi/axi_shared_bus.h"
#include "stream/stream.h"
#include "global_func_inst.h"

typedef struct fb_pos_params_t{
  uint16_t xpos;
  uint16_t ypos;
}fb_pos_params_t;

// Pipeline for position and address math
typedef struct fb_pos_addr_req_t{
  pixel_t p;
  uint16_t xpos;
  uint16_t ypos;
  fb_pos_params_t fb_pos;
}fb_pos_addr_req_t;
DECL_STREAM_TYPE(fb_pos_addr_req_t)
typedef struct fb_pos_addr_t{
  pixel_t p;
  uint32_t addr;
}fb_pos_addr_t;
DECL_STREAM_TYPE(fb_pos_addr_t)
fb_pos_addr_t fb_pos_addr(fb_pos_addr_req_t req){
  fb_pos_addr_t o;
  o.p = req.p;
  o.addr = pos_to_addr(req.fb_pos.xpos + req.xpos, req.fb_pos.ypos + req.ypos);
  return o;
}
GLOBAL_VALID_READY_PIPELINE_INST(fb_pos_addr_pipeline, fb_pos_addr_t, fb_pos_addr, fb_pos_addr_req_t, 16)

// Globally visible video bus
ndarray_stream_pixel_t_2 fb_pos_video_in; // input
uint1_t fb_pos_video_in_ready; // output
// Globally visible AXI bus for this module
axi_shared_bus_t_dev_to_host_t fb_pos_axi_host_from_dev;
axi_shared_bus_t_host_to_dev_t fb_pos_axi_host_to_dev;

#pragma MAIN fb_pos_main
void fb_pos_main()
{
  // Decode x,y positon of stream
  DECL_FEEDBACK_WIRE(uint1_t, ready_for_decoded)
  position_decoder_t decoded = position_decoder(
    fb_pos_video_in,
    ready_for_decoded
  );
  fb_pos_video_in_ready = decoded.ready_for_video_in;

  // Combine with postion params for final fb RAM addr
  fb_pos_params_t fb_pos_params; // TEMP const
  fb_pos_params.xpos = 640/2;
  fb_pos_params.ypos = 480/2;
  fb_pos_addr_pipeline_in.data.p = decoded.video_out.stream.data;
  fb_pos_addr_pipeline_in.data.xpos = decoded.dim[0];
  fb_pos_addr_pipeline_in.data.ypos = decoded.dim[1];
  fb_pos_addr_pipeline_in.data.fb_pos = fb_pos_params; // CSR 
  fb_pos_addr_pipeline_in.valid = decoded.video_out.stream.valid;
  ready_for_decoded = fb_pos_addr_pipeline_in_ready;

  // Stream pixels with address into ram
  uint8_t wr_bytes[4] = pixel_t_to_bytes(fb_pos_addr_pipeline_out.data.p);
  uint32_t word_in = uint8_array4_le(wr_bytes);
  axi_write_t axi_write_info = axi_addr_data_to_write(fb_pos_addr_pipeline_out.data.addr, word_in);
  fb_pos_axi_host_to_dev = axi_shared_bus_t_HOST_TO_DEV_NULL;
  fb_pos_addr_pipeline_out_ready = 0;
  if(fb_pos_addr_pipeline_out.valid){
    axi_shared_bus_t_write_start_logic_outputs_t write_start = 
      axi_shared_bus_t_write_start_logic(
      axi_write_info.req,
      axi_write_info.data, 
      1,
      fb_pos_axi_host_from_dev.write
    );
    fb_pos_axi_host_to_dev.write = write_start.to_dev;
    fb_pos_addr_pipeline_out_ready = write_start.ready_for_inputs;
  }

  // Drop all write responses
  fb_pos_axi_host_to_dev.write.resp_ready = 1;
}