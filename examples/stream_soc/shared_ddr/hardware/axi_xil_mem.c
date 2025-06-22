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
#define XIL_MEM_ADDR_WIDTH 28
#define xil_mem_addr_t uint28_t
#define xil_mem_size_t uint29_t // Extra bit for counting over
#define XIL_MEM_SIZE 268435456 // 2^28 bytes , 256MB DDR3 = 28b address
#define XIL_MEM_32b_SIZE (XIL_MEM_SIZE/4) // Number of 32b words, 4 bytes each
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
PRAGMA_MESSAGE(FUNC_WIRES xil_mem_module)
app_to_xil_mem_t xil_mem_module(xil_mem_to_app_t mem_to_app)
{
  xil_mem_to_app = mem_to_app;
  xil_mem_rst_done = !xil_mem_to_app.ui_clk_sync_rst & xil_mem_to_app.init_calib_complete;
  return app_to_xil_mem;
}

// Include types for axi shared bus axi_shared_bus_t
#include "axi/axi_shared_bus.h"

// Decl multi host clock domain instance of shared bus axi_shared_bus_t
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_NAME          axi_xil_mem
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_TYPE_NAME     axi_shared_bus_t  
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_WR_REQ_TYPE   axi_write_req_t 
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_WR_DATA_TYPE  axi_write_data_t
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_WR_RESP_TYPE  axi_write_resp_t
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_RD_REQ_TYPE   axi_read_req_t
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_RD_DATA_TYPE  axi_read_data_t
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_DEV_PORTS     1
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_DEV_CLK_MHZ   XIL_MEM_MHZ
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_TOTAL_HOST_PORTS 3
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST0_NAME     cpu
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST0_PORTS    2
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST0_CLK_MHZ  62.5
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST1_NAME     i2s
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST1_PORTS    1
#define MULTI_HOST_CLK_SHARED_RESOURCE_BUS_HOST1_CLK_MHZ  22.579
#include "multi_host_clk_shared_resource_bus_decl.h"

// Connect Xilinx MIG example AXI types to shared bus AXI types
MAIN_MHZ(axi_shared_bus_dev_arb_connect, XIL_MEM_MHZ)

// Sometimes you want an special priority port, typically for reading
// ex. for streaming read data meeting a frame buffer display rate
// Global wires for the priority read port
axi_shared_bus_t_host_to_dev_t axi_xil_rd_pri_port_mem_host_to_dev_wire;
axi_shared_bus_t_dev_to_host_t axi_xil_rd_pri_port_mem_dev_to_host_wire;
void axi_shared_bus_dev_arb_connect()
{
  // Arbitrate M hosts to N devs
  SHARED_BUS_ARB_PIPELINED(axi_shared_bus_t, axi_xil_mem, 1)

  // Middle special 2->1 arb with priority for reads on one port
  axi_shared_bus_t_dev_to_host_t rd_pri_port_arb_dev_to_host_in;
  #pragma FEEDBACK rd_pri_port_arb_dev_to_host_in
  rd_pri_port_arb_t rd_pri_arb = rd_pri_port_arb(
    axi_xil_mem_from_host[0], axi_xil_rd_pri_port_mem_host_to_dev_wire,
    rd_pri_port_arb_dev_to_host_in
  );
  axi_xil_mem_to_host[0] = rd_pri_arb.to_other_host;
  axi_xil_rd_pri_port_mem_dev_to_host_wire = rd_pri_arb.to_rd_pri_host;

  // Connect devs to frame buffer ports
  axi_shared_bus_dev_ctrl_t port_ctrl
    = axi_shared_bus_dev_ctrl_pipelined(xil_mem_to_app.axi_dev_to_host, rd_pri_arb.to_dev);
  app_to_xil_mem.axi_host_to_dev = port_ctrl.to_axi32_dev;
  rd_pri_port_arb_dev_to_host_in = port_ctrl.to_host;
}

// Derived FSM style code, unused for now...
/*
// wrappers around shared_resource_bus.h read() and write() dealing with not-burst request types etc
uint32_t axi_read(uint32_t addr)
{
  axi_read_req_t req;
  req.araddr = addr;
  req.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  req.arsize = 2; // 2^2=4 bytes per transfer
  req.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer
  axi_read_data_t resp;
  resp = axi_xil_mem_read(req);
  uint32_t rv = uint8_array4_le(resp.rdata);
  return rv;
}
void axi_write(uint32_t addr, uint32_t data)
{
  axi_write_req_t req;
  req.awaddr = addr;
  req.awlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
  req.awsize = 2; // 2^2=4 bytes per transfer
  req.awburst = BURST_FIXED; // Not a burst, single fixed address per transfer 
  axi_write_data_t wr_data;
  // All 4 bytes are being transfered (uint to array)
  uint32_t i;
  for(i=0; i<4; i+=1)
  {
    wr_data.wdata[i] = data >> (i*8);
    wr_data.wstrb[i] = 1;
  }
  axi_write_resp_t resp; // dummy return resp val
  resp = axi_xil_mem_write(req, wr_data);
}
*/
