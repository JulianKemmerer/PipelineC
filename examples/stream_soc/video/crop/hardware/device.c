#include "../../video_stream.h"

// TEMP TEST PATTERN
// instead of camera image...
#define TPW 60
#define TPH 60
stream(video_t) test_pattern(
  uint1_t ready_for_video_out
){
  static uint16_t x;
  static uint16_t y;
  // test square rgb pattern
  stream(video_t) video_out;
  uint16_t color_width = TPW / 3;
  if(x < (1*color_width)){
    video_out.data.data.r = 255;
  }else if(x < (2*color_width)){
    video_out.data.data.g = 255;
  }else{
    video_out.data.data.b = 255;
  }
  video_out.valid = 1;
  video_out.data.eod[0] = x==(TPW-1); // last pixel / EOL
  video_out.data.eod[1] = y==(TPH-1); // last line / EOF
  if(video_out.valid & ready_for_video_out){
    x += 1;
    if(video_out.data.eod[0]){
      y += 1;
      x = 0;
      if(video_out.data.eod[1]){
        y = 0;
      }
    }
  }
  return video_out;
}

typedef struct crop2d_params_t{
  uint16_t top_left_x;
  uint16_t top_left_y;
  uint16_t bot_right_x;
  uint16_t bot_right_y;
}crop2d_params_t;

typedef struct crop2d_t{
  stream(video_t) video_out;
  uint1_t ready_for_video_in;
}crop2d_t;
crop2d_t crop2d(
  crop2d_params_t params,
  stream(video_t) video_in,
  uint1_t ready_for_video_out
){
  crop2d_t o;
  // Decode x,y positon of stream
  DECL_FEEDBACK_WIRE(uint1_t, ready_for_decoded)
  frame_decoder_t decoded = frame_decoder(
    video_in,
    ready_for_decoded
  );
  o.ready_for_video_in = decoded.ready_for_video_in;
  // Filter out pixels outside crop
  // todo make pipeline out of filter function?
  // Quick easy comb logic enough?
  // Pass through default, invalidated
  o.video_out = decoded.video_out;
  o.video_out.valid = 0;
  ready_for_decoded = ready_for_video_out;
  if(
    (decoded.dim[0] >= params.top_left_x) & 
    (decoded.dim[0] <= params.bot_right_x) &
    (decoded.dim[1] >= params.top_left_y) & 
    (decoded.dim[1] <= params.bot_right_y)
  ){
    o.video_out.valid = decoded.video_out.valid;
  }
  // Set new eod bits
  o.video_out.data.eod[0] = decoded.dim[0] == params.bot_right_x;
  o.video_out.data.eod[1] = decoded.dim[1] == params.bot_right_y;
  return o;
}

// Globally visible video bus for SoC
//stream(video_t) crop_video_in; // input
//uint1_t crop_video_in_ready; // output
stream(video_t) crop_video_out; // output
uint1_t crop_video_out_ready; // input

#pragma MAIN crop_main
void crop_main()
{
  // TEMP Test pattern
  DECL_FEEDBACK_WIRE(uint1_t, ready_for_tp_vid)
  stream(video_t) tp_vid = test_pattern(
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