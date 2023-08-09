#pragma once
// https://www.xilinx.com/support/documentation/ip_documentation/ug586_7Series_MIS.pdf
// https://forum.digilentinc.com/topic/18555-arty-a7-and-mig/
// Controller Clock = 3000ps|333.33 MHz
// System / Input Clock = 6000ps|166.66MHz 
// Reference clock = which only accepts a 200MHz clock (common knowledge apparently)
// UI Clock output = Locked to 1/4 of controller clock = 83.33 MHz
// Memory Interface Generator (MIG) component

/*
// System Clock Ports
.sys_clk_i                       (sys_clk_i),
// Reference Clock Ports
.clk_ref_i                      (clk_ref_i),
.sys_rst                        (sys_rst) // input sys_rst
// Application interface ports
.ui_clk                         (ui_clk),  // output			ui_clk
.ui_clk_sync_rst                (ui_clk_sync_rst),  // output			ui_clk_sync_rst
.mmcm_locked                    (mmcm_locked),  // output			mmcm_locked
.aresetn                        (aresetn),  // input			aresetn
.app_sr_req                     (app_sr_req),  // input			app_sr_req
.app_ref_req                    (app_ref_req),  // input			app_ref_req
.app_zq_req                     (app_zq_req),  // input			app_zq_req
.app_sr_active                  (app_sr_active),  // output			app_sr_active
.app_ref_ack                    (app_ref_ack),  // output			app_ref_ack
.app_zq_ack                     (app_zq_ack),  // output			app_zq_ack
.init_calib_complete            (init_calib_complete),  // output			init_calib_complete
...
and AXI device port...
*/

#include "uintN_t.h"
#include "compiler.h"
#include "axi/axi.h"

#define XIL_MEM_MHZ 83.33 // UI CLK
#define xil_mem_addr_t uint28_t
#define xil_mem_size_t uint29_t // Extra bit for counting over
#define XIL_MEM_SIZE 268435456 // 2^28 , 256MB DDR3 = 28b address
#define XIL_MEM_ADDR_MAX (XIL_MEM_SIZE-1) //268435455 //4095 //268435455 // 2^28-1 // 256MB DDR3 = 28b address

typedef struct app_to_xil_mem_t
{
  axi32_host_to_dev_t axi_host_to_dev;
  //UNUSED uint1_t         aresetn;
  uint1_t         sr_req          ;
  uint1_t         ref_req         ;
  uint1_t         zq_req          ;
}app_to_xil_mem_t;
app_to_xil_mem_t NULL_APP_TO_XIL_MEM = {0};

typedef struct xil_mem_to_app_t
{
  axi32_dev_to_host_t axi_dev_to_host;
  uint1_t   sr_active             ;
  uint1_t   ref_ack               ;
  uint1_t   zq_ack                ;
  uint1_t   ui_clk_sync_rst       ;
  uint1_t   init_calib_complete   ;
}xil_mem_to_app_t;
xil_mem_to_app_t NULL_XIL_MEM_TO_APP = {0};

// Internal globally visible wires
// Input
app_to_xil_mem_t app_to_xil_mem;
// Output
xil_mem_to_app_t xil_mem_to_app;
// Special async wire output
uint1_t xil_mem_rst_done;
#pragma ASYNC_WIRE xil_mem_rst_done

// Top level io connection to board generated memory interface
MAIN_MHZ(xil_mem_module, XIL_MEM_MHZ) // Set clock freq
app_to_xil_mem_t xil_mem_module(xil_mem_to_app_t mem_to_app)
{
  xil_mem_to_app = mem_to_app;
  xil_mem_rst_done = !xil_mem_to_app.ui_clk_sync_rst & xil_mem_to_app.init_calib_complete;
  return app_to_xil_mem;
}
