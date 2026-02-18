#include "dvp.h"
#include "../../video/video_stream.h"
#include "global_fifo.h"

// TODO init done is input signal from CPU to pixel clock side
uint1_t cam_init_done;
#pragma ASYNC_WIRE cam_init_done

uint1_t cam_frame_size_valid;
#pragma ASYNC_WIRE cam_frame_size_valid

// FIFO of pixels to be read as output
GLOBAL_STREAM_FIFO(video_t, cam_input_video_fifo, 1024) // TODO size?

// Instance of dvp_rgb565_decoder source of stream of pixels
#include "cdc.h"
MAIN_MHZ(cam_pixel_test, CAM_PCLK_MHZ)
void cam_pixel_test(){
  // Wait for cam init done, a signal from SCCB clock domain
  uint1_t init_done = xil_cdc2_bit(cam_init_done);

  // Assume VSYNC polarity is positive
  uint1_t vsync_pol = 1;

  // Decode pixel data from DVP 8bit bus
  uint1_t cam_data[8] = {
    cam_d0,
    cam_d1,
    cam_d2,
    cam_d3,
    cam_d4,
    cam_d5,
    cam_d6,
    cam_d7
  };
  dvp_rgb565_decoder_t decoder = dvp_rgb565_decoder(
    cam_data,
    cam_hr,
    cam_vs,
    vsync_pol,
    init_done
  );

  // Only using frame valid output for now...
  cam_frame_size_valid = decoder.frame_size_valid;

  // Decoded video into FIFO
  cam_input_video_fifo_in.valid = decoder.pixel_valid & decoder.frame_size_valid;
  cam_input_video_fifo_in.data.data.a = 0;
  cam_input_video_fifo_in.data.data.r = decoder.r << 3;
  cam_input_video_fifo_in.data.data.g = decoder.g << 2;
  cam_input_video_fifo_in.data.data.b = decoder.b << 3;
  cam_input_video_fifo_in.data.eod[0] = decoder.x==(decoder.width-1);
  cam_input_video_fifo_in.data.eod[1] = decoder.y==(decoder.height-1);
  // no ready, just overflows
}
