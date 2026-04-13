#include "dvp.h"
#include "../../video/hardware/video_stream.h"
#include "global_fifo.h"

// Board top level IO for PMOD

#ifdef CAM_PIXEL_CLK_WIRE
#define CAM_PCLK_MHZ 26.0 // TODO thought was 25? Is 24? but call 26 to avoid confusing with other clocks, use clock group names
CLK_MHZ(cam_pixel_clk, CAM_PCLK_MHZ)
GLOBAL_IN_WIRE_CONNECT(uint1_t, cam_pixel_clk, CAM_PIXEL_CLK_WIRE)
MAIN_MHZ(cam_pixel_clk_connect, CAM_PCLK_MHZ) // TODO make all three macros into one?
#else
DECL_INPUT(uint1_t, cam_pixel_clk)
#endif

#ifdef CAM_HR_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_hr, CAM_HR_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_hr)
#endif

#ifdef CAM_VS_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_vs, CAM_VS_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_vs)
#endif

#ifdef CAM_D7_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d7, CAM_D7_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d7)
#endif

#ifdef CAM_D5_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d5, CAM_D5_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d5)
#endif

#ifdef CAM_D3_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d3, CAM_D3_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d3)
#endif

#ifdef CAM_D1_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d1, CAM_D1_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d1)
#endif

#ifdef CAM_D6_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d6, CAM_D6_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d6)
#endif

#ifdef CAM_D4_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d4, CAM_D4_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d4)
#endif

#ifdef CAM_D2_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d2, CAM_D2_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d2)
#endif

#ifdef CAM_D0_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d0, CAM_D0_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d0)
#endif


// TODO init done is input signal from CPU to pixel clock side
uint1_t cam_init_done;
#pragma ASYNC_WIRE cam_init_done

uint1_t cam_frame_size_valid;
#pragma ASYNC_WIRE cam_frame_size_valid

// FIFO of pixels to be read as output
GLOBAL_STREAM_FIFO(video_t, cam_input_video_fifo, 16) // Can be small just for CDC

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

  // Frame size valid is status reg
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
  // dont want to drop EOD flags so upstream a better drop location
  // is asserting false ready=1 always and dropping in a safe way
}
