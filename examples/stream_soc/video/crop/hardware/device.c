// TODO break into library .h defs vs instances in .c
// Rest of SoC uses pixel_t 24b rgb so video built around
#include "stream/stream.h"

DECL_STREAM_TYPE(pixel_t)
#include "pixel_t_bytes_t.h"
// ndarray_stream(type, NDIMS)
// one tlast bit per dimension, eod, 
typedef struct ndarray_stream_pixel_t_2{
  stream(pixel_t) stream;
  uint1_t eod[2];
}ndarray_stream_pixel_t_2;

#define TPW 60
#define TPH 60
ndarray_stream_pixel_t_2 test_pattern(
  uint1_t ready_for_video_out
){
  static uint16_t x;
  static uint16_t y;
  // test square rgb pattern
  ndarray_stream_pixel_t_2 video_out;
  uint16_t color_width = TPW / 3;
  if(x < (1*color_width)){
    video_out.stream.data.r = 255;
  }else if(x < (2*color_width)){
    video_out.stream.data.g = 255;
  }else{
    video_out.stream.data.b = 255;
  }
  video_out.stream.valid = 1;
  video_out.eod[0] = x==(TPW-1); // last pixel / EOL
  video_out.eod[1] = y==(TPH-1); // last line / EOF
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

typedef struct crop2d_params_t{
  uint16_t top_left_x;
  uint16_t top_left_y;
  uint16_t bot_right_x;
  uint16_t bot_right_y;
}crop2d_params_t;

typedef struct crop2d_t{
  ndarray_stream_pixel_t_2 video_out;
  uint1_t ready_for_video_in;
}crop2d_t;
crop2d_t crop2d(
  crop2d_params_t params,
  ndarray_stream_pixel_t_2 video_in,
  uint1_t ready_for_video_out
){
  crop2d_t o;
  // Decode x,y positon of stream
  DECL_FEEDBACK_WIRE(uint1_t, ready_for_decoded)
  position_decoder_t decoded = position_decoder(
    video_in,
    ready_for_decoded
  );
  o.ready_for_video_in = decoded.ready_for_video_in;
  // Filter out pixels outside crop
  // todo make pipeline out of filter function?
  // Quick easy comb logic enough?
  // Pass through default, invalidated
  o.video_out = decoded.video_out;
  o.video_out.stream.valid = 0;
  ready_for_decoded = ready_for_video_out;
  if(
    (decoded.dim[0] >= params.top_left_x) & 
    (decoded.dim[0] <= params.bot_right_x) &
    (decoded.dim[1] >= params.top_left_y) & 
    (decoded.dim[1] <= params.bot_right_y)
  ){
    o.video_out.stream.valid = decoded.video_out.stream.valid;
  }
  // Set new eod bits
  o.video_out.eod[0] = decoded.dim[0] == params.bot_right_x;
  o.video_out.eod[1] = decoded.dim[1] == params.bot_right_y;
  return o;
}

// Globally visible video bus
//ndarray_stream_pixel_t_2 crop_video_in; // input
//uint1_t crop_video_in_ready; // output
ndarray_stream_pixel_t_2 crop_video_out; // output
uint1_t crop_video_out_ready; // input

#pragma MAIN crop_main
void crop_main()
{
  // TEMP Test pattern
  DECL_FEEDBACK_WIRE(uint1_t, ready_for_tp_vid)
  ndarray_stream_pixel_t_2 tp_vid = test_pattern(
    ready_for_tp_vid
  );  

  // Crop based on x,y positon
  crop2d_params_t params;
  // TEMP const
  params.top_left_x = 0;
  params.top_left_y = 0;
  params.bot_right_x = TPW-1;
  params.bot_right_y = TPH/2;
  crop2d_t crop = crop2d(
    params,
    tp_vid,
    crop_video_out_ready
  );
  ready_for_tp_vid = crop.ready_for_video_in;
  crop_video_out = crop.video_out;
}