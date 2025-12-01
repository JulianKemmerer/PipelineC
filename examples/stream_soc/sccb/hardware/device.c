#include "global_fifo.h"

// SCCB control module
#include "../software/sccb_types.h"
#include "sccb/sccb.h"

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