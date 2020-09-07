//*****************************************************************************
// (c) Copyright 2008-2010 Xilinx, Inc. All rights reserved.
//
// This file contains confidential and proprietary information
// of Xilinx, Inc. and is protected under U.S. and
// international copyright and other intellectual property
// laws.
//
// DISCLAIMER
// This disclaimer is not a license and does not grant any
// rights to the materials distributed herewith. Except as
// otherwise provided in a valid license issued to you by
// Xilinx, and to the maximum extent permitted by applicable
// law: (1) THESE MATERIALS ARE MADE AVAILABLE "AS IS" AND
// WITH ALL FAULTS, AND XILINX HEREBY DISCLAIMS ALL WARRANTIES
// AND CONDITIONS, EXPRESS, IMPLIED, OR STATUTORY, INCLUDING
// BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, NON-
// INFRINGEMENT, OR FITNESS FOR ANY PARTICULAR PURPOSE; and
// (2) Xilinx shall not be liable (whether in contract or tort,
// including negligence, or under any other theory of
// liability) for any loss or damage of any kind or nature
// related to, arising under or in connection with these
// materials, including for any direct, or any indirect,
// special, incidental, or consequential loss or damage
// (including loss of data, profits, goodwill, or any type of
// loss or damage suffered as a result of any action brought
// by a third party) even if such damage or loss was
// reasonably foreseeable or Xilinx had been advised of the
// possibility of the same.
//
// CRITICAL APPLICATIONS
// Xilinx products are not designed or intended to be fail-
// safe, or for use in any application requiring fail-safe
// performance, such as life-support or safety devices or
// systems, Class III medical devices, nuclear facilities,
// applications related to the deployment of airbags, or any
// other applications that could lead to death, personal
// injury, or severe property or environmental damage
// (individually and collectively, "Critical
// Applications"). Customer assumes the sole risk and
// liability of any use of Xilinx products in Critical
// Applications, subject only to applicable laws and
// regulations governing limitations on product liability.
//
// THIS COPYRIGHT NOTICE AND DISCLAIMER MUST BE RETAINED AS
// PART OF THIS FILE AT ALL TIMES.
//
//*****************************************************************************
//   ____  ____
//  /   /\/   /
// /___/  \  /    Vendor: Xilinx
// \   \   \/     Version: %version
//  \   \         Application: MIG
//  /   /         Filename: read_posted_fifo.v
// /___/   /\     Date Last Modified: 
// \   \  /  \    Date Created: 
//  \___\/\___\
//
//Device: Spartan6
//Design Name: DDR/DDR2/DDR3/LPDDR 
//Purpose: This module instantiated by read_data_path module and sits between 
//         mcb_flow_control module and read_data_gen module to buffer up the 
//         commands that has sent to memory controller.
//Reference:
//Revision History:     3/14/2012   Adding support for "nCK_PER_CLK == 2" abd  MEM_BURST_LEN == 2 " 
//*****************************************************************************
`timescale 1ps/1ps
   
  module mig_7series_v4_2_read_posted_fifo #
  (
   parameter TCQ           = 100,  
   parameter FAMILY     = "SPARTAN6",  
   parameter nCK_PER_CLK   = 4,
   parameter MEM_BURST_LEN = 4,

   parameter ADDR_WIDTH = 32,
   parameter BL_WIDTH = 6
  )
  (
   input                   clk_i, 
   input                   rst_i,
   output reg                 cmd_rdy_o, 
   input                   memc_cmd_full_i,
   input                   cmd_valid_i, 
   input                   data_valid_i,
   input                   cmd_start_i,
   input [ADDR_WIDTH-1:0]  addr_i, 
   input [BL_WIDTH-1:0]    bl_i,
   input [2:0]           cmd_sent, 
   input [5:0]           bl_sent  ,
   input                 cmd_en_i ,
   
   
   output                  gen_valid_o, 
   output [ADDR_WIDTH-1:0] gen_addr_o, 
   output [BL_WIDTH-1:0]   gen_bl_o,
   output                  rd_mdata_en

   ); 
  
//reg empty_r;
  reg rd_en_r;
   wire full;
   wire empty;
   wire wr_en;
   reg mcb_rd_fifo_port_almost_full;
    reg [6:0] buf_avail_r;
    reg [6:0] rd_data_received_counts;
    reg [6:0] rd_data_counts_asked;
    
      reg dfifo_has_enough_room;
    reg [1:0] wait_cnt;
    reg wait_done;

  assign rd_mdata_en = rd_en_r;
   
 generate
 if (FAMILY == "SPARTAN6") 
 begin: gen_sp6_cmd_rdy
 
 always @ (posedge clk_i)
     cmd_rdy_o <= #TCQ !full  & dfifo_has_enough_room ;//& wait_done;
 end

// if ((FAMILY == "VIRTEX7") || (FAMILY == "7SERIES") || (FAMILY == "KINTEX7") || (FAMILY == "ARTIX7") ||
//                          (FAMILY == "VIRTEX6") ) 
 else 
 begin: gen_v6_cmd_rdy
   
   always @ (posedge clk_i)
       cmd_rdy_o <= #TCQ !full & wait_done &  dfifo_has_enough_room;
 end
 endgenerate
 
   always @ (posedge clk_i)
   begin
   if (rst_i)
       wait_cnt <= #TCQ 'b0;
   else if (cmd_rdy_o && cmd_valid_i)
       wait_cnt <= #TCQ 2'b10;
   else if (wait_cnt > 0)
         wait_cnt <= #TCQ wait_cnt - 1'b1;
       
   end
   
   always @(posedge clk_i)
   begin
   if (rst_i)
      wait_done <= #TCQ 1'b1;
   else if (cmd_rdy_o && cmd_valid_i)
      wait_done <= #TCQ 1'b0;
   else if (wait_cnt == 0)
      wait_done <= #TCQ 1'b1;
   else
      wait_done <= #TCQ 1'b0;
   
   end
   
   reg dfifo_has_enough_room_d1;
   always @ (posedge clk_i)
   begin
       dfifo_has_enough_room <=  #TCQ (buf_avail_r >= 32  ) ? 1'b1: 1'b0;
       dfifo_has_enough_room_d1 <= #TCQ dfifo_has_enough_room ;
   end
   
   // remove the dfifo_has_enough_room term. Just need to push pressure to the front to stop
   // sending more read commands but still accepting it if there is one coming.
   assign wr_en    = cmd_valid_i & !full  & wait_done;

   
 
 always @ (posedge clk_i)
 begin
 if (rst_i) begin
    rd_data_counts_asked <= #TCQ 'b0;
    end
 else if (cmd_en_i && cmd_sent[0] == 1 && ~memc_cmd_full_i) begin
   if (FAMILY == "SPARTAN6")
    rd_data_counts_asked <= #TCQ rd_data_counts_asked + (bl_sent + 7'b0000001) ;
   else
 //     if (nCK_PER_CLK == 2 )
 //        rd_data_counts_asked <= #TCQ rd_data_counts_asked + 2'b10 ;
 //     else
 //        rd_data_counts_asked <= #TCQ rd_data_counts_asked + 1'b1 ;

      if (nCK_PER_CLK == 4 || (nCK_PER_CLK == 2 && (MEM_BURST_LEN == 4 || MEM_BURST_LEN == 2 ) ))
         rd_data_counts_asked <= #TCQ rd_data_counts_asked + 1'b1 ;
      else if (nCK_PER_CLK == 2 && MEM_BURST_LEN == 8)
         rd_data_counts_asked <= #TCQ rd_data_counts_asked + 2'b10 ;


   
    end
 end

 always @ (posedge clk_i)
 begin
 if (rst_i) begin
     rd_data_received_counts <= #TCQ 'b0;
     end
 else if (data_valid_i) begin
     rd_data_received_counts <= #TCQ rd_data_received_counts + 1'b1;
     end     
 end
 
 // calculate how many buf still available
 always @ (posedge clk_i)
    if (rd_data_received_counts[6] == rd_data_counts_asked[6])
      buf_avail_r <= #TCQ (rd_data_received_counts[5:0] - rd_data_counts_asked[5:0] + 7'd64 );

    else
      buf_avail_r <= #TCQ  ( rd_data_received_counts[5:0] - rd_data_counts_asked[5:0] );
 
   
   always @ (posedge clk_i) begin
        rd_en_r <= #TCQ cmd_start_i;
   end
   
       
   
   assign gen_valid_o = !empty;
   mig_7series_v4_2_afifo #
   (
    .TCQ               (TCQ),
    .DSIZE         (BL_WIDTH+ADDR_WIDTH),
    .FIFO_DEPTH    (16),
    .ASIZE         (4),
    .SYNC          (1)  // set the SYNC to 1 because rd_clk = wr_clk to reduce latency 
   
   
   )
   rd_fifo
   (
    .wr_clk        (clk_i),
    .rst           (rst_i),
    .wr_en         (wr_en),
    .wr_data       ({bl_i,addr_i}),
    .rd_en         (rd_en_r),
    .rd_clk        (clk_i),
    .rd_data       ({gen_bl_o,gen_addr_o}),
    .full          (full),
    .empty         (empty),
    .almost_full   ()
   
   );
   
   
   
   
   
endmodule 
