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
//  /   /         Filename: data_prbs_gen.v
// /___/   /\     Date Last Modified: $Date: 2011/06/02 08:37:19 $
// \   \  /  \    Date Created: Fri Sep 01 2006
//  \___\/\___\
//
//Device: Spartan6
//Design Name: DDR/DDR2/DDR3/LPDDR 
//Purpose:  This module is used LFSR to generate random data for memory 
//          data write or memory data read comparison.The first data is 
//          seeded by the input prbs_seed_i which is connected to memory address.
//Reference:
//Revision History:
//*****************************************************************************

`timescale 1ps/1ps

module mig_7series_v4_2_data_prbs_gen #
  (
    parameter TCQ           = 100,

    parameter EYE_TEST   = "FALSE",
    parameter PRBS_WIDTH = 32,                                                                       // "SEQUENTIAL_BUrst_i"
    parameter SEED_WIDTH = 32    
   )
  (
   input           clk_i,
   input           clk_en,
   input           rst_i,
   input           prbs_seed_init,  // when high the prbs_x_seed will be loaded
   input [PRBS_WIDTH - 1:0]  prbs_seed_i,
   
   output  [PRBS_WIDTH - 1:0]  prbs_o     // generated address
  );
  
reg [PRBS_WIDTH - 1 :0] prbs;  
reg [PRBS_WIDTH :1] lfsr_q;
integer i;



always @ (posedge clk_i)
begin
   if (prbs_seed_init && EYE_TEST == "FALSE"  || rst_i )  //reset it to a known good state to prevent it locks up
//   if (rst_i )  //reset it to a known good state to prevent it locks up

      begin
        lfsr_q[4:1] <= #TCQ   prbs_seed_i[3:0] | 4'h5;
       // lfsr_q[PRBS_WIDTH-1:4] <= #TCQ  prbs_seed_i[PRBS_WIDTH-1:4] ;
         
        lfsr_q[PRBS_WIDTH:5] <= #TCQ  prbs_seed_i[PRBS_WIDTH-1:4] ;
      end
   else   if (clk_en) begin
     
        lfsr_q[32:9] <= #TCQ  lfsr_q[31:8];
        lfsr_q[8]    <= #TCQ  lfsr_q[32] ^ lfsr_q[7];
        lfsr_q[7]    <= #TCQ  lfsr_q[32] ^ lfsr_q[6];
        lfsr_q[6:4]  <= #TCQ  lfsr_q[5:3];
        
        lfsr_q[3]    <= #TCQ  lfsr_q[32] ^ lfsr_q[2];
        lfsr_q[2]    <= #TCQ  lfsr_q[1] ;
        lfsr_q[1]    <= #TCQ  lfsr_q[32];
       
        
         end
end
 
always @ (lfsr_q[PRBS_WIDTH:1]) begin
       prbs = lfsr_q[PRBS_WIDTH:1];
end

assign prbs_o = prbs;

endmodule
   
         
