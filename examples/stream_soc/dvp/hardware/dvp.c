#include "global_fifo.h"

// SCCB control module
#include "../software/sccb_types.h"
#include "sccb.h"

// OV2640 init over SCCB bus
// Instance of sccb_ctrl with CDC FIFOs for start req and finish resps
GLOBAL_STREAM_FIFO(sccb_op_start_t, sccb_start_fifo, 16)
GLOBAL_STREAM_FIFO(sccb_op_finish_t, sccb_finish_fifo, 16)

MAIN_MHZ(cam_ctrl, CAM_SYS_CLK_MHZ)
//#pragma FUNC_MARK_DEBUG cam_init_test
void cam_ctrl(){
  sccb_ctrl_t ctrl_fsm = sccb_ctrl(
    sccb_start_fifo_out.data.id,
    sccb_start_fifo_out.data.is_read,
    sccb_start_fifo_out.data.addr,
    sccb_start_fifo_out.data.write_data,
    sccb_start_fifo_out.valid,
    //
    sccb_finish_fifo_in_ready,
    //
    sccb_sio_d_in
  );
  sccb_start_fifo_out_ready = ctrl_fsm.ready_for_inputs;
  //
  sccb_finish_fifo_in.data.read_data = ctrl_fsm.output_read_data;
  sccb_finish_fifo_in.valid = ctrl_fsm.output_valid;
  //
  sccb_sio_d_out = ctrl_fsm.sio_d_out;
  sccb_sio_d_tristate_enable = ~ctrl_fsm.sio_d_out_enable;
  sccb_sio_c = ctrl_fsm.sio_c;
}

#include "dvp.h"

// TODO init done is input signal from CPU to pixel clock side
uint1_t cam_init_done;
#pragma ASYNC_WIRE cam_init_done

uint1_t cam_frame_size_valid;
#pragma ASYNC_WIRE cam_frame_size_valid

// Instance of dvp_rgb565_decoder source of stream of pixels
#include "cdc.h"
MAIN_MHZ(cam_pixel_test, CAM_PCLK_MHZ)
//#pragma FUNC_MARK_DEBUG cam_pixel_test
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
}
