// Include types for axi shared bus axi_shared_bus_t
#include "axi/axi_shared_bus.h"
#include "stream/stream.h"
#include "global_func_inst.h"


/*typedef struct pixel_t{
 uint8_t a, b, g, r; 
}pixel_t;*/
DECL_STREAM_TYPE(pixel_t)
#include "pixel_t_bytes_t.h"
// ndarray_stream(type, NDIMS)
// one tlast bit per dimension, eod, 
typedef struct ndarray_stream_pixel_t_2{
  stream(pixel_t) stream;
  uint1_t eod[2];
}ndarray_stream_pixel_t_2;


ndarray_stream_pixel_t_2 test_pattern(
  uint1_t ready_for_video_out
){
  static uint16_t x;
  static uint16_t y;
  // 60x60 test square rgb pattern
  ndarray_stream_pixel_t_2 video_out;
  uint16_t color_width = 60 / 3;
  if(x < (1*color_width)){
    video_out.stream.data.r = 255;
  }else if(x < (2*color_width)){
    video_out.stream.data.g = 255;
  }else{
    video_out.stream.data.b = 255;
  }
  video_out.stream.valid = 1;
  video_out.eod[0] = x==(60-1); // last pixel / EOL
  video_out.eod[1] = y==(60-1); // last line / EOF
  if(video_out.stream.valid & ready_for_video_out){
    x += 1;
    if(video_out.eod[0]){
      y += 1;
      x = 0;
      if(video_out.eod[1]){
        y = 0;
      }
    }
  }
  return video_out;
}


typedef struct position_decoder_t{
  ndarray_stream_pixel_t_2 video_out;
  uint16_t dim[2]; // 2d x,y pos
  uint1_t ready_for_video_in;
}position_decoder_t;
position_decoder_t position_decoder(
  ndarray_stream_pixel_t_2 video_in,
  uint1_t ready_for_outputs
){
  position_decoder_t o;
  // Dont need to pass video through with valid ready handshake?
  o.video_out = video_in;
  o.video_out.stream.valid = 0;
  o.ready_for_video_in = ready_for_outputs;
  static uint1_t frame_syncd;
  uint1_t frame_syncd_next = frame_syncd;
  static uint16_t x;
  static uint16_t y;
  o.dim[0] = x;
  o.dim[1] = y;
  // Track x,y pos to sync with frame
  if(video_in.stream.valid & o.ready_for_video_in)
  {
    x += 1;
    if(video_in.eod[0]){
      y += 1;
      x = 0;
      if(video_in.eod[1]){
        y = 0;
        frame_syncd_next = 1;
      }
    }
  }
  // Output video when synced
  if(frame_syncd)
  {
    o.video_out.stream.valid = video_in.stream.valid;
  }
  frame_syncd = frame_syncd_next;
  return o;
}


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


// Globally visible AXI bus for this module
axi_shared_bus_t_dev_to_host_t fb_pos_axi_host_from_dev;
axi_shared_bus_t_host_to_dev_t fb_pos_axi_host_to_dev;

#pragma MAIN fb_pos_main
void fb_pos_main()
{
  // Test pattern
  DECL_FEEDBACK_WIRE(uint1_t, ready_for_tp_vid)
  ndarray_stream_pixel_t_2 tp_vid = test_pattern(
    ready_for_tp_vid
  );
  
  // Decode x,y positon of stream
  DECL_FEEDBACK_WIRE(uint1_t, ready_for_decoded)
  position_decoder_t decoded = position_decoder(
    tp_vid,
    ready_for_decoded
  );
  ready_for_tp_vid = decoded.ready_for_video_in;

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