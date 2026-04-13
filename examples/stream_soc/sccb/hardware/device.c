#include "global_fifo.h"

// Board top levle IO for PMOD

#define CAM_SYS_CLK_MHZ 24 // TODO use VGA 25Mhz instead? or name with clock group to avoid confusion with pixel clock
CLK_MHZ(cam_sys_clk, CAM_SYS_CLK_MHZ)
#ifdef CAM_SYS_CLK_WIRE
DECL_INPUT(uint1_t, cam_sys_clk)
GLOBAL_OUT_WIRE_CONNECT(uint1_t, CAM_SYS_CLK_WIRE, cam_sys_clk)
MAIN_MHZ(PPCAT(CAM_SYS_CLK_WIRE,_connect), CAM_SYS_CLK_MHZ) // TODO make all three macros into one?
#else
DECL_OUTPUT(uint1_t, cam_sys_clk)
#endif

#ifdef SCCB_SIO_C_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, SCCB_SIO_C_WIRE, sccb_sio_c)
#else
DECL_OUTPUT_REG(uint1_t, sccb_sio_c)
#endif

#ifdef SCCB_SIO_D_I_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, sccb_sio_d_in, SCCB_SIO_D_I_WIRE)
#else
DECL_INPUT_REG(uint1_t, sccb_sio_d_in)
#endif

#ifdef SCCB_SIO_D_O_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, SCCB_SIO_D_O_WIRE, sccb_sio_d_out)
#else
DECL_OUTPUT_REG(uint1_t, sccb_sio_d_out)
#endif

#ifdef SCCB_SIO_D_T_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, SCCB_SIO_D_T_WIRE, sccb_sio_d_tristate_enable)
#else
DECL_OUTPUT_REG(uint1_t, sccb_sio_d_tristate_enable)
#endif

// SCCB control module
#include "../software/sccb_types.h"
#include "sccb/sccb.h"

// OV2640 init over SCCB bus
// Instance of sccb_ctrl with CDC FIFOs for start req and finish resps
GLOBAL_STREAM_FIFO(sccb_op_start_t, sccb_start_fifo, 16)
GLOBAL_STREAM_FIFO(sccb_op_finish_t, sccb_finish_fifo, 16)

MAIN_MHZ(cam_ctrl, CAM_SYS_CLK_MHZ)
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