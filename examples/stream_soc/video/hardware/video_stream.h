#include "ndarray.h"
#include "stream/stream.h"

//DECL_STREAM_TYPE(pixel_t)

// Video stream type for this design
DECL_NDARRAY_TYPE(2,pixel_t)
DECL_STREAM_TYPE(ndarray(2,pixel_t))
#define video_t ndarray(2,pixel_t)

// Frame position decoder module
typedef struct frame_decoder_t{
  stream(video_t) video_out;
  uint16_t dim[2]; // 2d x,y pos
  uint1_t ready_for_video_in;
}frame_decoder_t;
frame_decoder_t frame_decoder(
  stream(video_t) video_in,
  uint1_t ready_for_outputs
){
  frame_decoder_t o;
  // Dont need to pass video through with valid ready handshake?
  o.video_out = video_in;
  o.video_out.valid = 0;
  o.ready_for_video_in = ready_for_outputs;
  static uint1_t frame_syncd;
  uint1_t frame_syncd_next = frame_syncd;
  static uint16_t x;
  static uint16_t y;
  o.dim[0] = x;
  o.dim[1] = y;
  // Track x,y pos to sync with frame
  if(video_in.valid & o.ready_for_video_in)
  {
    x += 1;
    if(video_in.data.eod[0]){
      y += 1;
      x = 0;
      if(video_in.data.eod[1]){
        y = 0;
        frame_syncd_next = 1;
      }
    }
  }
  // Output video when synced
  if(frame_syncd)
  {
    o.video_out.valid = video_in.valid;
  }
  frame_syncd = frame_syncd_next;
  return o;
}
