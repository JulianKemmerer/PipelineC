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
//  /   /         Filename: write_data_path.v
// /___/   /\     Date Last Modified: 
// \   \  /  \    Date Created: 
//  \___\/\___\
//
//Device: Spartan6
//Design Name: DDR/DDR2/DDR3/LPDDR 
//Purpose: This is top level of write path . 

//Reference:
//Revision History:
//*****************************************************************************

`timescale 1ps/1ps


module mig_7series_v4_2_write_data_path #(
   parameter TCQ           = 100,  
   parameter FAMILY = "SPARTAN6",
   parameter MEM_TYPE      = "DDR3",
   
   parameter ADDR_WIDTH = 32,
   parameter START_ADDR = 32'h00000000,
   parameter BL_WIDTH = 6,
   parameter nCK_PER_CLK   = 4,            // DRAM clock : MC clock
   parameter MEM_BURST_LEN = 8,
   parameter DWIDTH = 32,
   parameter DATA_PATTERN = "DGEN_ALL", //"DGEN__HAMMER", "DGEN_WALING1","DGEN_WALING0","DGEN_ADDR","DGEN_NEIGHBOR","DGEN_PRBS","DGEN_ALL"  
   parameter NUM_DQ_PINS   = 8,
   parameter SEL_VICTIM_LINE = 3,  // VICTIM LINE is one of the DQ pins is selected to be different than hammer pattern
   
   parameter MEM_COL_WIDTH = 10,
   parameter EYE_TEST   = "FALSE"
   
    )
    (
   
   input     clk_i, 
   input [9:0]    rst_i,
   output    cmd_rdy_o, 
   input     cmd_valid_i, 
   input     cmd_validB_i, 
   input     cmd_validC_i, 
   input [31:0] prbs_fseed_i,
   input [3:0]  data_mode_i,
   input        mem_init_done_i,
   input        wr_data_mask_gen_i,
 //  input [31:0] m_addr_i,
   
   input [31:0] simple_data0 ,
   input [31:0] simple_data1 ,
   input [31:0] simple_data2 ,
   input [31:0] simple_data3 ,
   input [31:0] simple_data4 ,
   input [31:0] simple_data5 ,
   input [31:0] simple_data6 ,
   input [31:0] simple_data7 ,
   
   input [31:0]     fixed_data_i,    
   input                    mode_load_i,

   input [31:0] addr_i, 
   input [BL_WIDTH-1:0]   bl_i,

//   input [5:0]            port_data_counts_i,// connect to data port fifo counts
   input                  memc_cmd_full_i,
   input                  data_rdy_i, 
   output                 data_valid_o,
   output                 last_word_wr_o,
   output [NUM_DQ_PINS*nCK_PER_CLK*2-1:0] data_o,   
   output [(NUM_DQ_PINS*nCK_PER_CLK*2/8) - 1:0] data_mask_o,
   output                    data_wr_end_o
   
   );

wire data_valid;
reg cmd_rdy;

  assign data_valid_o = data_valid;// & data_rdy_i;          
         

   mig_7series_v4_2_wr_data_gen #
     (
              .TCQ               (TCQ),
              .FAMILY            (FAMILY),
              .MEM_TYPE          (MEM_TYPE),
              .NUM_DQ_PINS       (NUM_DQ_PINS), 
              .MEM_BURST_LEN     (MEM_BURST_LEN),
              .BL_WIDTH          (BL_WIDTH),
              .START_ADDR        (START_ADDR),
              .nCK_PER_CLK       (nCK_PER_CLK),
              .SEL_VICTIM_LINE   (SEL_VICTIM_LINE),
              .DATA_PATTERN  (DATA_PATTERN),
              .DWIDTH           (DWIDTH),
              .COLUMN_WIDTH     (MEM_COL_WIDTH),
              .EYE_TEST         (EYE_TEST)
              
              )
   wr_data_gen(
            .clk_i              (clk_i          ),
            .rst_i              (rst_i[9:5]),
            .prbs_fseed_i       (prbs_fseed_i),
            .wr_data_mask_gen_i  (wr_data_mask_gen_i),
            .mem_init_done_i    (mem_init_done_i),
            .data_mode_i        (data_mode_i    ),
            .cmd_rdy_o          (cmd_rdy_o      ),
            .cmd_valid_i        (cmd_valid_i    ),
            .cmd_validB_i        (cmd_validB_i    ),
            .cmd_validC_i        (cmd_validC_i    ),
            
            .last_word_o        (last_word_wr_o ),
       //     .port_data_counts_i (port_data_counts_i),
       //     .m_addr_i             (m_addr_i         ),
            .fixed_data_i         (fixed_data_i),
            .simple_data0       (simple_data0),
            .simple_data1       (simple_data1),
            .simple_data2       (simple_data2),
            .simple_data3       (simple_data3),
            .simple_data4       (simple_data4),
            .simple_data5       (simple_data5),
            .simple_data6       (simple_data6),
            .simple_data7       (simple_data7),
            
            
            .mode_load_i        (mode_load_i),
       
            .addr_i             (addr_i         ),
            .bl_i               (bl_i           ),
            .memc_cmd_full_i      (memc_cmd_full_i),
            
            .data_rdy_i         (data_rdy_i     ),
            .data_valid_o       ( data_valid  ),
            .data_o             (data_o         ),
            .data_wr_end_o         (data_wr_end_o),
            .data_mask_o        (data_mask_o)
            );
   
   
   
endmodule 
