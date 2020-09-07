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
//  /   /         Filename: tb_cmd_gen.v
// /___/   /\     Date Last Modified: $Date: 2011/06/02 08:37:24 $
// \   \  /  \    Date Created: Fri Sep 01 2006
//  \___\/\___\
//
//Device: 7 Series
//Design Name: PRBS_Generator
//Purpose:       
// Overview:
//  Implements a "pseudo-PRBS" generator. Basically this is a standard
//  PRBS generator (using an linear feedback shift register) along with
//  logic to force the repetition of the sequence after 2^PRBS_WIDTH
//  samples (instead of 2^PRBS_WIDTH - 1). The LFSR is based on the design
//  from Table 1 of XAPP 210. Note that only 8- and 10-tap long LFSR chains
//  are supported in this code
// Parameter Requirements:
//  1. PRBS_WIDTH = 8 or 10
//  2. PRBS_WIDTH >= 2*nCK_PER_CLK
// Output notes:
//  The output of this module consists of 2*nCK_PER_CLK bits, these contain
//  the value of the LFSR output for the next 2*CK_PER_CLK bit times. Note
//  that prbs_o[0] contains the bit value for the "earliest" bit time. 
//Reference:
//Revision History:
//*****************************************************************************

`timescale 1ps/1ps

module mig_7series_v4_2_tg_prbs_gen #
  (
   parameter TCQ         = 100,        // clk->out delay (sim only)
   parameter PRBS_WIDTH  = 10,         // LFSR shift register length
   parameter nCK_PER_CLK = 4           // output:internal clock freq ratio
   )
  (
   input                      clk_i,          // input clock
   input                      clk_en_i,       // clock enable 
   input                      rst_i,          // synchronous reset
   input [PRBS_WIDTH-1:0]     prbs_seed_i,    // initial LFSR seed
   output [2*nCK_PER_CLK-1:0] prbs_o,         // generated address
   // ReSeedcounter used to indicate when pseudo-PRBS sequence has reached
   // the end of it's cycle. May not be needed, but for now included to
   // maintain compatibility with current TG code
   output [31:0]              ReSeedcounter_o 
  );

  //***************************************************************************

  function integer clogb2 (input integer size);
    begin
      size = size - 1;
      for (clogb2=1; size>1; clogb2=clogb2+1)
        size = size >> 1;
    end
  endfunction
  
  // Number of internal clock cycles before the PRBS sequence will repeat
  localparam PRBS_SEQ_LEN_CYCLES = (2**PRBS_WIDTH) / (2*nCK_PER_CLK);
  localparam PRBS_SEQ_LEN_CYCLES_BITS = clogb2(PRBS_SEQ_LEN_CYCLES);
  
  reg [PRBS_WIDTH-1:0]                lfsr_reg_r;
  wire [PRBS_WIDTH-1:0]               next_lfsr_reg;
  reg [PRBS_WIDTH-1:0]                reseed_cnt_r;
  reg                                 reseed_prbs_r;
  reg [PRBS_SEQ_LEN_CYCLES_BITS-1:0]  sample_cnt_r;

  genvar                              i;
  
  //***************************************************************************

  assign ReSeedcounter_o = {{(32-PRBS_WIDTH){1'b0}}, reseed_cnt_r};
  always @ (posedge clk_i)
    if (rst_i)
      reseed_cnt_r <= 'b0;
    else if (clk_en_i)
      if (reseed_cnt_r == {PRBS_WIDTH {1'b1}})
        reseed_cnt_r <= 'b0;
      else
        reseed_cnt_r <= reseed_cnt_r + 1;
  
  //***************************************************************************
  
  // Generate PRBS reset signal to ensure that PRBS sequence repeats after
  // every 2**PRBS_WIDTH samples. Basically what happens is that we let the
  // LFSR run for an extra cycle after "truly PRBS" 2**PRBS_WIDTH - 1
  // samples have past. Once that extra cycle is finished, we reseed the LFSR
  always @(posedge clk_i)
    if (rst_i) begin
      sample_cnt_r <= #TCQ 'b0;
      reseed_prbs_r   <= #TCQ 1'b0;
    end else if (clk_en_i) begin
      // The rollver count should always be [(power of 2) - 1]
      sample_cnt_r <= #TCQ sample_cnt_r + 1;
      // Assert PRBS reset signal so that it is simultaneously with the
      // last sample of the sequence
      if (sample_cnt_r == PRBS_SEQ_LEN_CYCLES - 2)
        reseed_prbs_r <= #TCQ 1'b1;
      else
        reseed_prbs_r <= #TCQ 1'b0;
    end

  // Load initial seed or update LFSR contents
  always @(posedge clk_i)
    if (rst_i)
      lfsr_reg_r <= #TCQ prbs_seed_i;
    else if (clk_en_i)
      if (reseed_prbs_r)
        lfsr_reg_r <= #TCQ prbs_seed_i;
      else begin
        lfsr_reg_r <= #TCQ next_lfsr_reg;
      end
  
  // Calculate next set of nCK_PER_CLK samplse for LFSR
  // Basically we calculate all PRBS_WIDTH samples in parallel, rather
  // than serially shifting the LFSR to determine future sample values.
  // Shifting is possible, but requires multiple shift registers to be
  // instantiated because the fabric clock frequency is running at a
  // fraction of the output clock frequency
  generate
    if (PRBS_WIDTH == 8) begin: gen_next_lfsr_prbs8
      if (nCK_PER_CLK == 2) begin: gen_ck_per_clk2
        assign next_lfsr_reg[7] = lfsr_reg_r[3];
        assign next_lfsr_reg[6] = lfsr_reg_r[2];
        assign next_lfsr_reg[5] = lfsr_reg_r[1];
        assign next_lfsr_reg[4] = lfsr_reg_r[0];
        assign next_lfsr_reg[3] = ~(lfsr_reg_r[7] ^ lfsr_reg_r[5] ^
                                    lfsr_reg_r[4] ^ lfsr_reg_r[3]);
        assign next_lfsr_reg[2] = ~(lfsr_reg_r[6] ^ lfsr_reg_r[4] ^
                                    lfsr_reg_r[3] ^ lfsr_reg_r[2]);
        assign next_lfsr_reg[1] = ~(lfsr_reg_r[5] ^ lfsr_reg_r[3] ^
                                    lfsr_reg_r[2] ^ lfsr_reg_r[1]);
        assign next_lfsr_reg[0] = ~(lfsr_reg_r[4] ^ lfsr_reg_r[2] ^
                                    lfsr_reg_r[1] ^ lfsr_reg_r[0]);
      end else if (nCK_PER_CLK == 4) begin: gen_ck_per_clk4
        assign next_lfsr_reg[7] = ~(lfsr_reg_r[7] ^ lfsr_reg_r[5] ^
                                    lfsr_reg_r[4] ^ lfsr_reg_r[3]);
        assign next_lfsr_reg[6] = ~(lfsr_reg_r[6] ^ lfsr_reg_r[4] ^
                                    lfsr_reg_r[3] ^ lfsr_reg_r[2]) ;
        assign next_lfsr_reg[5] = ~(lfsr_reg_r[5] ^ lfsr_reg_r[3] ^
                                    lfsr_reg_r[2] ^ lfsr_reg_r[1]);
        assign next_lfsr_reg[4] = ~(lfsr_reg_r[4] ^ lfsr_reg_r[2] ^
                                    lfsr_reg_r[1] ^ lfsr_reg_r[0]);
        assign next_lfsr_reg[3] = ~(lfsr_reg_r[3] ^ lfsr_reg_r[1] ^
                                    lfsr_reg_r[0] ^ next_lfsr_reg[7]);
        assign next_lfsr_reg[2] = ~(lfsr_reg_r[2]    ^ lfsr_reg_r[0] ^
                                    next_lfsr_reg[7] ^ next_lfsr_reg[6]);
        assign next_lfsr_reg[1] = ~(lfsr_reg_r[1]    ^ next_lfsr_reg[7] ^
                                    next_lfsr_reg[6] ^ next_lfsr_reg[5]);
        assign next_lfsr_reg[0] = ~(lfsr_reg_r[0]    ^ next_lfsr_reg[6] ^
                                    next_lfsr_reg[5] ^ next_lfsr_reg[4]);
      end
    end else if (PRBS_WIDTH == 10) begin: gen_next_lfsr_prbs10
      if (nCK_PER_CLK == 2) begin: gen_ck_per_clk2
        assign next_lfsr_reg[9] = lfsr_reg_r[5];
        assign next_lfsr_reg[8] = lfsr_reg_r[4];
        assign next_lfsr_reg[7] = lfsr_reg_r[3];
        assign next_lfsr_reg[6] = lfsr_reg_r[2];
        assign next_lfsr_reg[5] = lfsr_reg_r[1];
        assign next_lfsr_reg[4] = lfsr_reg_r[0];
        assign next_lfsr_reg[3] = ~(lfsr_reg_r[9] ^ lfsr_reg_r[6]);
        assign next_lfsr_reg[2] = ~(lfsr_reg_r[8] ^ lfsr_reg_r[5]);
        assign next_lfsr_reg[1] = ~(lfsr_reg_r[7] ^ lfsr_reg_r[4]);
        assign next_lfsr_reg[0] = ~(lfsr_reg_r[6] ^ lfsr_reg_r[3]);
      end else if (nCK_PER_CLK == 4) begin: gen_ck_per_clk4
        assign next_lfsr_reg[9] = lfsr_reg_r[1];
        assign next_lfsr_reg[8] = lfsr_reg_r[0];
        assign next_lfsr_reg[7] = ~(lfsr_reg_r[9] ^ lfsr_reg_r[6]);
        assign next_lfsr_reg[6] = ~(lfsr_reg_r[8] ^ lfsr_reg_r[5]);
        assign next_lfsr_reg[5] = ~(lfsr_reg_r[7] ^ lfsr_reg_r[4]);
        assign next_lfsr_reg[4] = ~(lfsr_reg_r[6] ^ lfsr_reg_r[3]);
        assign next_lfsr_reg[3] = ~(lfsr_reg_r[5] ^ lfsr_reg_r[2]);
        assign next_lfsr_reg[2] = ~(lfsr_reg_r[4] ^ lfsr_reg_r[1]);
        assign next_lfsr_reg[1] = ~(lfsr_reg_r[3] ^ lfsr_reg_r[0]);
        assign next_lfsr_reg[0] = ~(lfsr_reg_r[2] ^ next_lfsr_reg[7]);
      end
    end
  endgenerate

  // Output highest (2*nCK_PER_CLK) taps of LFSR - note that the "earliest"
  // tap is highest tap (e.g. for an 8-bit LFSR, tap[7] contains the first
  // data sent out the shift register), therefore tap[PRBS_WIDTH-1] must be 
  // routed to bit[0] of the output, tap[PRBS_WIDTH-2] to bit[1] of the
  // output, etc. 
  generate
    for (i = 0; i < 2*nCK_PER_CLK; i = i + 1) begin: gen_prbs_transpose
      assign prbs_o[i] = lfsr_reg_r[PRBS_WIDTH-1-i];
    end
  endgenerate


endmodule
   
         
