// https://www.xilinx.com/support/documentation/ip_documentation/ug586_7Series_MIS.pdf
// https://forum.digilentinc.com/topic/18555-arty-a7-and-mig/
// Controller Clock = 3000ps|333.33 MHz
// System / Input Clock = 6000ps|166.66MHz 
// Reference clock = which only accepts a 200MHz clock (common knowledge apparently)
// UI Clock output = Locked to 1/4 of controller clock = 83.33 MHz
// Memory Interface Generator (MIG) component

#include "compiler.h"
#include "wire.h"
#include "uintN_t.h"

#define XIL_MIG_MHZ 83.33 // UI CLK
#define xil_mig_addr_t uint28_t
#define XIL_MIG_MEM_SIZE 268435456 // 2^28 , 256MB DDR3 = 28b address
#define XIL_MIG_ADDR_MAX (XIL_MIG_MEM_SIZE-1) //268435455 //4095 //268435455 // 2^28-1 // 256MB DDR3 = 28b address
#define XIL_MIG_CMD_WRITE 0
#define XIL_MIG_CMD_READ 1
#define XIL_MIG_DATA_SIZE 16
typedef struct xil_app_to_mig_t
{
      xil_mig_addr_t  addr            ;
      uint3_t         cmd             ;
      uint1_t         en              ;
      uint8_t         wdf_data[XIL_MIG_DATA_SIZE];
      uint1_t         wdf_end         ;
      uint1_t         wdf_mask[XIL_MIG_DATA_SIZE];
      uint1_t         wdf_wren        ;
      uint1_t         sr_req          ;
      uint1_t         ref_req         ;
      uint1_t         zq_req          ;
}xil_app_to_mig_t;

xil_app_to_mig_t XIL_APP_TO_MIG_T_NULL()
{
  uint32_t i;
  xil_app_to_mig_t rv;
  rv.addr = 0;
  rv.cmd  = 0;
  rv.en = 0;
  for(i=0;i<XIL_MIG_DATA_SIZE;i+=1)
  {
    rv.wdf_data[i] = 0;
  }
  rv.wdf_end = 0;
  for(i=0;i<XIL_MIG_DATA_SIZE;i+=1)
  {
    rv.wdf_mask[i] = 0; // All bytes written
  }
  rv.wdf_wren = 0;
  rv.sr_req = 0;
  rv.ref_req = 0;
  rv.zq_req = 0;
  return rv;
}

typedef struct xil_mig_to_app_t
{
      uint8_t   rd_data[XIL_MIG_DATA_SIZE];
      uint1_t   rd_data_end           ;
      uint1_t   rd_data_valid         ;
      uint1_t   rdy                   ;
      uint1_t   wdf_rdy               ;
      uint1_t   sr_active             ;
      uint1_t   ref_ack               ;
      uint1_t   zq_ack                ;
      uint1_t   ui_clk_sync_rst       ;
      uint1_t   init_calib_complete   ;
}xil_mig_to_app_t;

// Internal globally visible 'ports' / 'wires' (a subset of clock domain crossing)
// Input
xil_app_to_mig_t xil_app_to_mig;
#include "xil_app_to_mig_t_array_N_t.h"
#include "xil_app_to_mig_clock_crossing.h"
// Output
xil_mig_to_app_t xil_mig_to_app;
#include "xil_mig_to_app_t_array_N_t.h"
#include "xil_mig_to_app_clock_crossing.h"

// Top level io connection to board generated memory interface
MAIN_MHZ(xil_mig_module,XIL_MIG_MHZ) // Set clock freq
xil_app_to_mig_t xil_mig_module(xil_mig_to_app_t mig_to_app)
{
  xil_app_to_mig_t app_to_mig;
  WIRE_READ(xil_app_to_mig_t, app_to_mig, xil_app_to_mig)
  WIRE_WRITE(xil_mig_to_app_t, xil_mig_to_app, mig_to_app)
  return app_to_mig;
}
