// TEMP fake 1x pass through scaler
/* 
#include "stream/stream.h"

typedef struct scale2d_params_t{

}scale2d_params_t;

typedef struct scale2d_t{
  ndarray_stream_pixel_t_2 video_out;
  uint1_t ready_for_video_in;
}scale2d_t;
scale2d_t scale2d(
  scale2d_params_t params,
  ndarray_stream_pixel_t_2 video_in,
  uint1_t ready_for_video_out
){
  // Need line buffers?
}
*/

// Globally visible video bus
ndarray_stream_pixel_t_2 scale_video_in; // input
uint1_t scale_video_in_ready; // output
ndarray_stream_pixel_t_2 scale_video_out; // output
uint1_t scale_video_out_ready; // input

#pragma MAIN scale_main
void scale_main(){
  scale_video_out = scale_video_in;
  scale_video_in_ready = scale_video_out_ready;
}