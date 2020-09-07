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
//  /   /         Filename: rd_data_gen.v
// /___/   /\     Date Last Modified: 
// \   \  /  \    Date Created: 
//  \___\/\___\
//
//Device: Spartan6
//Design Name: DDR/DDR2/DDR3/LPDDR 
//Purpose: This module has all the timing control for generating "compare data" 
//         to compare the read data from memory.
//Reference:
//Revision History:
//*****************************************************************************

`timescale 1ps/1ps

module mig_7series_v4_2_rd_data_gen #
   (
   parameter TCQ           = 100,
   parameter FAMILY = "VIRTEX7", // "SPARTAN6", "VIRTEX6"
   parameter MEM_TYPE = "DDR3",
   parameter nCK_PER_CLK   = 4,            // DRAM clock : MC clock
   
   parameter MEM_BURST_LEN = 8,
   parameter START_ADDR = 32'h00000000,

   parameter ADDR_WIDTH = 32,
   parameter BL_WIDTH = 6,
   parameter DWIDTH = 32,
   parameter DATA_PATTERN = "DGEN_ALL", //"DGEN__HAMMER", "DGEN_WALING1","DGEN_WALING0","DGEN_ADDR","DGEN_NEIGHBOR","DGEN_PRBS","DGEN_ALL"  
   parameter NUM_DQ_PINS   = 8,
   parameter SEL_VICTIM_LINE = 3,  // VICTIM LINE is one of the DQ pins is selected to be different than hammer pattern
   
   parameter COLUMN_WIDTH = 10
   
 )
 (
   input   clk_i,                 //
   input [4:0]  rst_i, 
   input [31:0] prbs_fseed_i,
   input [3:0]  data_mode_i,   // "00" = bram; 
   input        mode_load_i,
   input [3:0]  vio_instr_mode_value,
   
   output  cmd_rdy_o,             // ready to receive command. It should assert when data_port is ready at the                                        // beginning and will be deasserted once see the cmd_valid_i is asserted. 
                                  // And then it should reasserted when 
                                  // it is generating the last_word.
   input   cmd_valid_i,           // when both cmd_valid_i and cmd_rdy_o is high, the command  is valid.
   output reg cmd_start_o,
//   input [ADDR_WIDTH-1:0] m_addr_i, // generated address used to determine data pattern.

   input [31:0] simple_data0 ,
   input [31:0] simple_data1 ,
   input [31:0] simple_data2 ,
   input [31:0] simple_data3 ,
   input [31:0] simple_data4 ,
   input [31:0] simple_data5 ,
   input [31:0] simple_data6 ,
   input [31:0] simple_data7 ,

   
   input [31:0] fixed_data_i,   
   input [ADDR_WIDTH-1:0] addr_i, // generated address used to determine data pattern.
   input [BL_WIDTH-1:0]   bl_i,   // generated burst length for control the burst data
   output                 user_bl_cnt_is_1_o,
   input   data_rdy_i,           // connect from mcb_wr_full when used as wr_data_gen in sp6
                                 // connect from mcb_rd_empty when used as rd_data_gen in sp6
                                 // connect from rd_data_valid in v6
                                 // When both data_rdy and data_valid is asserted, the ouput data is valid.
   output   reg data_valid_o,       // connect to wr_en or rd_en and is asserted whenever the 
                                 // pattern is available.
//   output  [DWIDTH-1:0] data_o // generated data pattern    NUM_DQ_PINS*nCK_PER_CLK*2-1
   output  [31:0] tg_st_addr_o,
   output  [NUM_DQ_PINS*nCK_PER_CLK*2-1:0] data_o // generated data pattern    NUM_DQ_PINS*nCK_PER_CLK*2-1
   
);  
// 



wire [31:0]       prbs_data; 
reg              cmd_start;
reg [31:0]        adata; 
reg [31:0]        hdata; 
reg [31:0]        ndata; 
reg [31:0]        w1data; 
reg [NUM_DQ_PINS*4-1:0]        v6_w1data; 

reg [31:0]        w0data; 
reg [DWIDTH-1:0] data;
reg               cmd_rdy;
reg [BL_WIDTH:0]user_burst_cnt;
reg [31:0] w3data;
reg        prefetch;
assign data_port_fifo_rdy = data_rdy_i;

      


reg user_bl_cnt_is_1;
assign user_bl_cnt_is_1_o = user_bl_cnt_is_1;
always @ (posedge clk_i)
begin
if (data_port_fifo_rdy)
    if ((user_burst_cnt == 2  && FAMILY == "SPARTAN6")
        || (user_burst_cnt == 2  &&  FAMILY == "VIRTEX6")
        )

         user_bl_cnt_is_1 <= #TCQ 1'b1;
    else
        user_bl_cnt_is_1 <= #TCQ 1'b0;
end


//reg cmd_start_b;
always @(cmd_valid_i,data_port_fifo_rdy,cmd_rdy,user_bl_cnt_is_1,prefetch)
begin

       cmd_start = cmd_valid_i   & cmd_rdy  & ( data_port_fifo_rdy | prefetch) ;
       cmd_start_o = cmd_valid_i & cmd_rdy & ( data_port_fifo_rdy | prefetch) ;

end




// counter to count user burst length
// verilint STARC-2.2.3.3 off
always @( posedge clk_i)
begin
  if ( rst_i[0] )
    user_burst_cnt <= #TCQ   'd0;
  else if(cmd_valid_i && cmd_rdy && ( data_port_fifo_rdy | prefetch) )  begin
      
   //  SPATAN6 has maximum of burst length of 64.
       if (FAMILY == "SPARTAN6" && bl_i[5:0] == 6'b000000)
          begin
             user_burst_cnt[6:0] <= #TCQ 7'd64;
             user_burst_cnt[BL_WIDTH:7] <= 'b0;
          end
       else if (FAMILY == "VIRTEX6" && bl_i[BL_WIDTH - 1:0] == {BL_WIDTH {1'b0}})
          user_burst_cnt <= #TCQ {1'b1, {BL_WIDTH{1'b0}}};      
       else
          user_burst_cnt <= #TCQ {1'b0,bl_i };
       end
  else if(data_port_fifo_rdy) 
     if (user_burst_cnt != 6'd0)
        user_burst_cnt <= #TCQ   user_burst_cnt - 1'b1;
     else
        user_burst_cnt <= #TCQ   'd0;
        
end 
// verilint STARC-2.2.3.3 on

// cmd_rdy_o assert when the dat fifo is not full and deassert once cmd_valid_i
// is assert and reassert during the last data

//data_valid_o logic

always @( posedge clk_i)
begin
  if ( rst_i[0] )
    prefetch <= #TCQ   1'b1;
  else if (data_port_fifo_rdy || cmd_start)
    prefetch <= #TCQ   1'b0;

  else if (user_burst_cnt == 0 && ~data_port_fifo_rdy)
    prefetch <= #TCQ   1'b1;
  
end
assign cmd_rdy_o = cmd_rdy  ;

always @( posedge clk_i)
begin
  if ( rst_i[0] )
    cmd_rdy <= #TCQ   1'b1;
   
  else if (cmd_valid_i && cmd_rdy && (data_port_fifo_rdy || prefetch ))
       cmd_rdy <= #TCQ   1'b0;
  else if  ((data_port_fifo_rdy && user_burst_cnt == 2 && vio_instr_mode_value != 7 )  || 
            (data_port_fifo_rdy && user_burst_cnt == 1 && vio_instr_mode_value == 7 ))

      cmd_rdy <= #TCQ   1'b1;
  

end




always @ (data_port_fifo_rdy)
if (FAMILY == "SPARTAN6")
    data_valid_o = data_port_fifo_rdy;
else
    data_valid_o = data_port_fifo_rdy;


/*
generate
if (FAMILY == "SPARTAN6") 
begin : SP6_DGEN
s7ven_data_gen #
 
(  
   .TCQ               (TCQ),
   .DMODE           ("READ"),
   .nCK_PER_CLK       (nCK_PER_CLK),
   .FAMILY          (FAMILY),
   
   .ADDR_WIDTH      (32 ),
   .BL_WIDTH        (BL_WIDTH       ),    
   .MEM_BURST_LEN   (MEM_BURST_LEN),
   .DWIDTH          (DWIDTH       ),
   .DATA_PATTERN    (DATA_PATTERN  ),
   .NUM_DQ_PINS      (NUM_DQ_PINS  ),
   .SEL_VICTIM_LINE   (SEL_VICTIM_LINE),
   .START_ADDR        (START_ADDR),
   
   .COLUMN_WIDTH     (COLUMN_WIDTH)
   
 )
 s7ven_data_gen
 (
   .clk_i              (clk_i         ),        
   .rst_i              (rst_i[1]      ),
   .data_rdy_i         (data_rdy_i    ),
   .mem_init_done_i    (1'b1),
   .wr_data_mask_gen_i (1'b0),

   .prbs_fseed_i       (prbs_fseed_i),
   .mode_load_i        (mode_load_i),
   .data_mode_i        (data_mode_i   ),  
   .cmd_startA         (cmd_start    ),  
   .cmd_startB         (cmd_start    ),   
   .cmd_startC         (cmd_start    ),   
   .cmd_startD         (cmd_start    ),   
   .cmd_startE         (cmd_start    ),   
   .m_addr_i           (addr_i),//(m_addr_i        ), 
   
   .simple_data0       (simple_data0),
   .simple_data1       (simple_data1),
   .simple_data2       (simple_data2),
   .simple_data3       (simple_data3),
   .simple_data4       (simple_data4),
   .simple_data5       (simple_data5),
   .simple_data6       (simple_data6),
   .simple_data7       (simple_data7),
   .fixed_data_i       (fixed_data_i),
                       
   .addr_i             (addr_i        ),       
   .user_burst_cnt     (user_burst_cnt),
   .fifo_rdy_i         (data_port_fifo_rdy    ),   
   .data_o             (data_o        ),
   .data_mask_o        (),
   
   .bram_rd_valid_o    ()
  );

end

endgenerate*/
//generate
//if (FAMILY == "VIRTEX6") 
//begin : V_DGEN
mig_7series_v4_2_s7ven_data_gen #
(  
   .TCQ               (TCQ),
   .DMODE           ("READ"),
   .nCK_PER_CLK       (nCK_PER_CLK),
   .FAMILY          (FAMILY),
   .MEM_TYPE       (MEM_TYPE),
   
   .ADDR_WIDTH      (32 ),
   .BL_WIDTH        (BL_WIDTH       ),    
   .MEM_BURST_LEN   (MEM_BURST_LEN),
   .DWIDTH          (DWIDTH       ),
   .DATA_PATTERN    (DATA_PATTERN  ),
   .NUM_DQ_PINS      (NUM_DQ_PINS  ),
   .SEL_VICTIM_LINE   (SEL_VICTIM_LINE),
   .START_ADDR        (START_ADDR),
   
   .COLUMN_WIDTH     (COLUMN_WIDTH)
   
 )
 s7ven_data_gen
 (
   .clk_i              (clk_i         ),        
   .rst_i              (rst_i[1]      ),
   .data_rdy_i         (data_rdy_i    ),
   .mem_init_done_i    (1'b1),
   .wr_data_mask_gen_i (1'b0),

   .prbs_fseed_i       (prbs_fseed_i),
   .mode_load_i        (mode_load_i),
   .data_mode_i        (data_mode_i   ),  
   .cmd_startA         (cmd_start    ),  
   .cmd_startB         (cmd_start    ),   
   .cmd_startC         (cmd_start    ),   
   .cmd_startD         (cmd_start    ),   
   .cmd_startE         (cmd_start    ),   
   .m_addr_i           (addr_i),//(m_addr_i        ), 
   
   .simple_data0       (simple_data0),
   .simple_data1       (simple_data1),
   .simple_data2       (simple_data2),
   .simple_data3       (simple_data3),
   .simple_data4       (simple_data4),
   .simple_data5       (simple_data5),
   .simple_data6       (simple_data6),
   .simple_data7       (simple_data7),
   .fixed_data_i       (fixed_data_i),
                       
   .addr_i             (addr_i        ),       
   .user_burst_cnt     (user_burst_cnt),
   .fifo_rdy_i         (data_port_fifo_rdy    ),   
   .data_o             (data_o        ),
   .tg_st_addr_o       (tg_st_addr_o),
   .data_mask_o        (),
   
   .bram_rd_valid_o    ()
  );

//end
//endgenerate





endmodule 
