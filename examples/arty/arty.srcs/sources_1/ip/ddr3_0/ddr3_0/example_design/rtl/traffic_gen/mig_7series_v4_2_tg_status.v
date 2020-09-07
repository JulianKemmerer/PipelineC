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
//  /   /         Filename: tg_status.v
// /___/   /\     Date Last Modified: 
// \   \  /  \    Date Created: 
//  \___\/\___\
//
//Device: Spartan6
//Design Name: DDR/DDR2/DDR3/LPDDR 
//Purpose:  This module compare the memory read data agaisnt compare data that generated from data_gen module.
//          Error signal will be asserted if the comparsion is not equal.
//Reference:
//Revision History:
//*****************************************************************************

`timescale 1ps/1ps


module mig_7series_v4_2_tg_status #(
   parameter TCQ           = 100,  

   parameter DWIDTH = 32
    )
    (
      
   
   input                            clk_i  ,        
   input                            rst_i ,
   input                            manual_clear_error,
   input                            data_error_i ,  
   input [DWIDTH-1:0]               cmp_data_i,     
   input [DWIDTH-1:0]               rd_data_i ,     
   input [31:0]                     cmp_addr_i ,    
   input [5:0]                      cmp_bl_i ,      
   input                            mcb_cmd_full_i ,
   input                            mcb_wr_full_i,  
   input                            mcb_rd_empty_i, 
   output reg [64 + (2*DWIDTH - 1):0]   error_status,   
   output                           error                  
  );

reg data_error_r;
reg error_set;
assign  error = error_set;

always @ (posedge clk_i)
    data_error_r <= #TCQ  data_error_i;

always @ (posedge clk_i)
begin

if (rst_i || manual_clear_error) begin
   error_status <= #TCQ  'b0;
   error_set    <= #TCQ  1'b0;
end
else begin
  // latch the first error only
  if (data_error_i && ~data_error_r && ~error_set ) begin
     error_status[31:0]  <= #TCQ  cmp_addr_i;
     error_status[37:32] <= #TCQ  cmp_bl_i;
     error_status[40] <= #TCQ  mcb_cmd_full_i;
     error_status[41] <= #TCQ  mcb_wr_full_i;
     error_status[42] <= #TCQ  mcb_rd_empty_i;
     error_set <= #TCQ  1'b1;
     error_status[64 + (DWIDTH - 1)  :64]           <= #TCQ  cmp_data_i;
     error_status[64 + (2*DWIDTH - 1):64 + DWIDTH]  <= #TCQ  rd_data_i;
   
  end

  error_status[39:38]  <= #TCQ  'b0;    // reserved
  error_status[63:43] <= #TCQ  'b0;    // reserved


end end
    
endmodule 
