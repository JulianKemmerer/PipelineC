//*****************************************************************************
// (c) Copyright 2008-2009 Xilinx, Inc. All rights reserved.
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
//  /   /         Filename: cmd_gen.v
// /___/   /\     Date Last Modified: $Date: 2011/06/02 08:37:19 $
// \   \  /  \    Date Created: Oct 21 2008
//  \___\/\___\
//
//Device: Spartan6
//Design Name: DDR/DDR2/DDR3/LPDDR
//Purpose:  This module genreates different type of commands, address,
//          burst_length to mcb_flow_control module.
//Reference:
//Revision History:
//                  Nov14 2008. Added constraints  for generating PRBS_BL when
//                         generated address is too close to end of address space.
//                         The BL will be force to 1 to avoid across other port's space.
//                  April 2 2009 Fixed Sequential Address Circuit to avoide generate any address
//                               beyond the allowed address range.                
//                  Oct 22 2009  Fixed BRAM interface.
//                               Fixed run_traffic stop and go problem.
//                               Merged V6 and SP6 specific requirements.
//                               Modified syntax for VHDL Formality comparison.
//                  Dec 1  2011  Fixed Simple Data mode address generation problem.      
//                  Jan 4  2012  Added percent write instruction mode ( mode == 4) to
//                               let user specify percentage of write commands out of mix
//                               write/read commands. 

//*****************************************************************************



`timescale 1ps/1ps



`define RD              3'b001;

`define RDP             3'b011;

`define WR              3'b000;

`define WRP             3'b010;

`define REFRESH         3'b100;



(* use_dsp48 = "no" *)

module mig_7series_v4_2_cmd_gen #

  (

   parameter TCQ           = 100,



   parameter FAMILY = "SPARTAN6",

   parameter MEM_TYPE      = "DDR3",

   

   parameter BL_WIDTH      = 6,          // User Commands Burst length that send over User Interface.

   parameter MEM_BURST_LEN = 8,

   parameter nCK_PER_CLK   = 4,

   parameter PORT_MODE = "BI_MODE",

   parameter NUM_DQ_PINS   = 8,

   parameter DATA_PATTERN  = "DGEN_ALL", // "DGEN__HAMMER", "DGEN_WALING1","DGEN_WALING0","DGEN_ADDR","DGEN_NEIGHBOR","DGEN_PRBS","DGEN_ALL"

   parameter CMD_PATTERN  = "CGEN_ALL",    // "CGEN_RPBS","CGEN_FIXED",  "CGEN_BRAM", "CGEN_SEQUENTIAL", "CGEN_ALL",

   parameter ADDR_WIDTH    = 30,

   parameter BANK_WIDTH    = 3,

   parameter DWIDTH        = 32,

   parameter PIPE_STAGES   = 0,

   parameter MEM_COL_WIDTH = 10,       // memory column width

   parameter PRBS_EADDR_MASK_POS = 32'hFFFFD000,

   parameter PRBS_SADDR_MASK_POS =  32'h00002000,

   parameter PRBS_EADDR = 32'h00002000,

   parameter PRBS_SADDR  = 32'h00002000

   )

  (

   input           clk_i,

   input [9:0]          rst_i,

   input           run_traffic_i,

   input [3:0]     vio_instr_mode_value,
   input [3:0]     vio_percent_write,
   input           single_operation,

  // runtime parameter

   input                    mem_pattern_init_done_i,

   input [31:0]             start_addr_i,   // define the start of address

   input [31:0]             end_addr_i,

   input [31:0]             cmd_seed_i,    // same seed apply to all addr_prbs_gen, bl_prbs_gen, instr_prbs_gen

   input                    load_seed_i,   //

   // upper layer inputs to determine the command bus and data pattern

   // internal traffic generator initialize the memory with

   input [2:0]              addr_mode_i,  // "00" = bram; takes the address from bram output

                                          // "01" = fixed address from the fixed_addr input

                                          // "10" = psuedo ramdom pattern; generated from internal 64 bit LFSR

                                          // "11" = sequential



   input [3:0]              data_mode_i,  // 4'b0010:address as data

                                          // 4'b0011:DGEN_HAMMER

                                          // 4'b0100:DGEN_NEIGHBOUR

                                          // 4'b0101:DGEN_WALKING1

                                          // 4'b0110:DGEN_WALKING0

                                          // 4'b0111:PRBS_DATA



  // for each instr_mode, traffic gen fill up with a predetermined pattern before starting the instr_pattern that defined

  // in the instr_mode input. The runtime mode will be automatically loaded inside when it is in

   input [3:0]              instr_mode_i, // "0000" = bram; takes instruction from bram output

                                          // "0001" = fixed instr from fixed instr input

                                          // "0010" = R/W

                                          // "0011" = RP/WP

                                          // "0100" = R/RP/W/WP

                                          // "0101" = R/RP/W/WP/REF

                                          // "0110" = PRBS





   input [1:0]              bl_mode_i,  // "00" = bram;   takes the burst length from bram output

                                        // "01" = fixed , takes the burst length from the fixed_bl input

                                        // "10" = psuedo ramdom pattern; generated from internal 16 bit LFSR



   input                    mode_load_i,



   // fixed pattern inputs interface

   input [BL_WIDTH - 1:0]              fixed_bl_i,      // range from 1 to 64

   input [2:0]              fixed_instr_i,   //RD              3'b001

                                            //RDP             3'b011

                                            //WR              3'b000

                                            //WRP             3'b010

                                            //REFRESH         3'b100

   input [31:0]             fixed_addr_i, // only upper 30 bits will be used

   // BRAM FIFO input

   input [31:0]             bram_addr_i,  //

   input [2:0]              bram_instr_i,

   input [5:0]              bram_bl_i,

   input                    bram_valid_i,

   output                   bram_rdy_o,



   input                    reading_rd_data_i,

   // mcb_flow_control interface

   input           rdy_i,



   output  [31:0]  addr_o,     // generated address

   output  [2:0]   instr_o,    // generated instruction

   output  [BL_WIDTH - 1:0]   bl_o,       // generated instruction

//   output reg [31:0]  m_addr_o,

   output          cmd_o_vld  ,    // valid commands when asserted

   output  reg     mem_init_done_o

  );



   localparam PRBS_ADDR_WIDTH = 32;

   localparam INSTR_PRBS_WIDTH = 16;

   localparam BL_PRBS_WIDTH    = 16;



localparam BRAM_DATAL_MODE       =    4'b0000;

localparam FIXED_DATA_MODE       =    4'b0001;

localparam ADDR_DATA_MODE        =    4'b0010;

localparam HAMMER_DATA_MODE      =    4'b0011;

localparam NEIGHBOR_DATA_MODE    =    4'b0100;

localparam WALKING1_DATA_MODE    =    4'b0101;

localparam WALKING0_DATA_MODE    =    4'b0110;

localparam PRBS_DATA_MODE        =    4'b0111;

localparam DWIDTH_BY_8           =    (DWIDTH >> 3); 

localparam LOGB2_MEM_BURST_INT   =    (MEM_BURST_LEN == 8)? 3:2;



reg [BL_WIDTH+DWIDTH_BY_8-1:0] bl_x_DWIDTH_BY_8;

reg [BL_WIDTH+2:0] INC_COUNTS /* synthesis syn_dspstyle = logic */ ;   

reg [2:0]  addr_mode_reg;

reg [1:0]  bl_mode_reg;

reg [31:0] addr_counts /* synthesis syn_dspstyle = logic */ ;

reg [31:0] addr_counts_next_r;

reg [BANK_WIDTH-1:0] bank_counts;

wire  [14:0]  prbs_bl;

reg [2:0] instr_out;

wire [14:0] prbs_instr_a;

wire [14:0] prbs_instr_b;

reg  [BL_WIDTH - 1:0]   prbs_brlen;

wire [31:0] prbs_addr;

wire [31:0] seq_addr;

wire [31:0] fixed_addr;

reg [31:0] addr_out ;

reg [BL_WIDTH - 1:0]  bl_out;   

reg [BL_WIDTH + DWIDTH/8 - 1:0]cal_blout;

reg [BL_WIDTH - 1:0] bl_out_reg;

reg mode_load_d1;

reg mode_load_d2;

reg mode_load_pulse;

wire [BL_WIDTH+35:0] pipe_data_o;

wire     cmd_clk_en;

wire     pipe_out_vld;

reg force_bl1;

reg bl_out_clk_en;

reg [BL_WIDTH+35:0] pipe_data_in;

reg instr_vld;

reg bl_out_vld;

reg gen_addr_larger ;

reg gen_bl_larger;

reg [7:0] buf_avail_r;

reg [6:0] rd_data_received_counts;

reg [6:0] rd_data_counts_asked;

reg instr_vld_dly1;

reg first_load_pulse;

reg mem_init_done;

reg refresh_cmd_en ;

reg [9:0] refresh_timer;

reg       refresh_prbs;

reg       cmd_vld;

reg run_traffic_r;

reg cmd_clk_en_r;

reg finish_init;

reg mem_init_done_r;   

reg first_mode_load_pulse_r1;

reg first_mode_load_pulse_set;

reg mode_load_pulse_r1;

reg n_gen_write_only;

reg [9:0]force_rd_counts;

reg force_rd;

reg bl_64;

reg force_wrcmd_gen;
reg toggle_rw;
reg [3:0] write_percent_cnt;



always @ (posedge clk_i)

 if (rst_i[0])

     mem_init_done_o <= #TCQ 1'b0;

 else if (cmd_clk_en_r)

     mem_init_done_o <= #TCQ mem_init_done_r;


always @ (posedge clk_i)
begin

     run_traffic_r <= #TCQ run_traffic_i;

end     


// commands go through pipeline inserters

assign addr_o       = pipe_data_o[31:0];

assign instr_o      = pipe_data_o[34:32];



assign bl_o         = pipe_data_o[(BL_WIDTH - 1 + 35):35];







                     // most significant bit

assign cmd_o_vld    = pipe_data_o[BL_WIDTH  + 35] & run_traffic_r;

assign pipe_out_vld = pipe_data_o[BL_WIDTH  + 35] & run_traffic_r;





assign pipe_data_o = pipe_data_in;



always @(posedge clk_i) begin                    



     instr_vld        <=  #TCQ  (cmd_clk_en | (mode_load_pulse & first_load_pulse));

     bl_out_clk_en    <=  #TCQ  (cmd_clk_en | (mode_load_pulse & first_load_pulse));

     bl_out_vld       <=  #TCQ  bl_out_clk_en;

 end



always @ (posedge clk_i) begin

 if (rst_i[0] || single_operation)

    first_load_pulse <= #TCQ 1'b1;

 else if (mode_load_pulse)

    first_load_pulse <= #TCQ 1'b0;

 else

    first_load_pulse <= #TCQ first_load_pulse;

 end

 



always @(posedge clk_i) begin 

if (CMD_PATTERN == "CGEN_BRAM")

    cmd_vld          <=  #TCQ (cmd_clk_en ); 

else  //if (CMD_PATTERN != "CGEN_BRAM") 

    cmd_vld          <=  #TCQ (cmd_clk_en | (mode_load_pulse & first_load_pulse )); 



end



 

assign cmd_clk_en =  ( rdy_i & pipe_out_vld & run_traffic_i ||  mode_load_pulse && (CMD_PATTERN == "CGEN_BRAM"));

 



 

integer i;

always @ (posedge clk_i)

if (rst_i[1])

   bl_64 <= 1'b0;

else if (data_mode_i == 7 || data_mode_i == 8 || data_mode_i == 9)

   bl_64 <= 1'b1;

else

   bl_64 <= 1'b0;





    always @ (posedge clk_i) begin

    if (rst_i[1])

      if (vio_instr_mode_value == 4'h7)

         pipe_data_in[31:0] <= #TCQ    fixed_addr_i;

      else

       pipe_data_in[31:0] <= #TCQ    start_addr_i;

    else if (instr_vld)

       // In order to simplify all different test pattern, the V6 generated

       // seed address from cmd_gen are  aligned to burst length. The PRBS 

       // burst length for write always 64 else it will break.

      //   if (MEM_BURST_LEN == 8)

           if (data_mode_i == 5 || data_mode_i == 6)

            // for walking 1's / walking 0's pattern, the least 8 bits starting address 

            // has to be all zero. This is to force the DQ pattern of each starting burst

            // starts from DQ0.

               if (FAMILY == "VIRTEX6")

                 pipe_data_in[31:0] <= #TCQ    {addr_out[31:6], 6'h00};



               else

                   pipe_data_in[31:0] <= #TCQ    {addr_out[31:6], 6'h00};  // DWIDTH = 64





           else if (data_mode_i == 4)

                // pipe_data_in[31:0] <= #TCQ    {addr_out[31:3], 3'b000};

                 pipe_data_in[31:0] <= #TCQ    {addr_out[31:6], 6'b000};

                

           else if (bl_64)

            // nCK_PER_CLK = 4 && PRBS Length = 8

            //force the least 11 bits starting address is always zero to align

            // PRBS sequence.

            if  (nCK_PER_CLK == 4)

                  if (FAMILY == "VIRTEX6")

                 pipe_data_in[31:0] <= #TCQ    {addr_out[31:11], 11'h000};

            else

                     pipe_data_in[31:0] <= #TCQ     {addr_out[31:9], 9'h000};

                  

               else

                  if (FAMILY == "VIRTEX6")

                 pipe_data_in[31:0] <= #TCQ    {addr_out[31:10], 10'h000};

                  else

                     pipe_data_in[31:0] <= #TCQ     {addr_out[31:9], 9'h000};

         else if (gen_addr_larger && mem_init_done)// && (addr_mode_reg == 3'b100 || addr_mode_reg == 3'b010)) 

              pipe_data_in[31:0] <= #TCQ  {end_addr_i[31:8],8'h0};

           else           

            pipe_data_in[31:0] <= #TCQ    {addr_out[31:2], 2'b00};

     //    else

     //       pipe_data_in[31:0] <= #TCQ    {addr_out[31:2],2'b00000};

         

end



//end endgenerate





   always @ (posedge clk_i) begin

    if (rst_i[0])

         force_wrcmd_gen <= #TCQ  1'b0;

    else if (buf_avail_r == 63)

         force_wrcmd_gen <= #TCQ  1'b0;

    else if (instr_vld_dly1 && pipe_data_in[32]== 1 && pipe_data_in[41:35] > 16)

         force_wrcmd_gen <= #TCQ  1'b1;

    end

reg [3:0]instr_mode_reg;

 always @ (posedge clk_i)

 begin

      instr_mode_reg <= #TCQ  instr_mode_i;

 end 

 always @ (posedge clk_i)

 begin

    if (rst_i[2]) begin

       pipe_data_in[40:32] <= #TCQ    'b0;

       end

    else if (instr_vld) begin

      if (instr_mode_reg == 0) begin

              pipe_data_in[34:32] <= #TCQ    instr_out;

              end

      else if (instr_out[2]) begin

              pipe_data_in[34:32] <= #TCQ    3'b100;

              end

        //

      else if ( FAMILY == "SPARTAN6" && PORT_MODE == "RD_MODE")

      begin

            pipe_data_in[34:32] <= #TCQ  {instr_out[2:1],1'b1};

              end

            

      else if ((force_wrcmd_gen || buf_avail_r <=  15) && FAMILY == "SPARTAN6" &&  PORT_MODE != "RD_MODE")

      begin

            pipe_data_in[34:32] <= #TCQ    {instr_out[2],2'b00};

              end

      else begin

             pipe_data_in[34:32] <= #TCQ    instr_out; 

              end



   //********* condition the generated bl value except if TG is programmed for BRAM interface'

   // if the generated address is close to end address range, the bl_out will be altered to 1.

        if (data_mode_i == 7 ) 

           pipe_data_in[BL_WIDTH-1+35:35] <=   #TCQ  bl_out;

       

        else if (data_mode_i == 4 ) 

     

           pipe_data_in[BL_WIDTH-1+35:35] <=   #TCQ  10'd32;

           

           

        else  

          if (gen_bl_larger && mem_pattern_init_done_i)  // this condition is needed 

             

                    pipe_data_in[BL_WIDTH-1+35:35] <=   #TCQ  10'd8;

          else if (force_bl1 && mem_pattern_init_done_i)

                    pipe_data_in[BL_WIDTH-1+35:35] <=  #TCQ   10'd2; // for V6

          

          else

                    pipe_data_in[BL_WIDTH-1+35:35] <=   #TCQ  bl_out;  // 8:2'  4:4



   end  //else instr_vld

 end // always



reg COut;



always @ (posedge clk_i) 

begin

     if (rst_i[2])

        pipe_data_in[BL_WIDTH   + 35] <=  #TCQ   'b0;

     else if (cmd_vld)

        pipe_data_in[BL_WIDTH  + 35] <=  #TCQ   instr_vld;//instr_vld;

     else if (rdy_i && pipe_out_vld)

        pipe_data_in[BL_WIDTH + 35] <=  #TCQ   1'b0;

 end



 always @ (posedge clk_i)

    instr_vld_dly1  <=  #TCQ instr_vld;





reg COutA;

always @ (posedge clk_i) begin

 if (rst_i[0]) begin

    rd_data_counts_asked <= #TCQ  'b0;

  end else if (instr_vld_dly1 && pipe_data_in[32]== 1) begin

    if (pipe_data_in[(BL_WIDTH  +35):35] == 0)

       {COutA,rd_data_counts_asked} <=  #TCQ rd_data_counts_asked + (10'd64) ;

    else

       {COutA,rd_data_counts_asked} <=  #TCQ rd_data_counts_asked + (pipe_data_in[41:35]) ;



    end

 end



always @ (posedge clk_i) begin

 if (rst_i[0]) begin

     rd_data_received_counts <= #TCQ  'b0;

  end else if(reading_rd_data_i) begin

     rd_data_received_counts <= #TCQ  rd_data_received_counts + 1'b1;

     end

 end





reg COut_d;

 always @ (posedge clk_i)

 if (FAMILY == "SPARTAN6") 

    {COut_d, buf_avail_r} <= #TCQ  ( rd_data_received_counts[6:0] - rd_data_counts_asked[6:0] + 7'd64);

 else  // Virtex 6 MC has no need to generate such constraints .

    buf_avail_r <= #TCQ 8'd64;

    

localparam BRAM_ADDR       = 2'b00;

localparam FIXED_ADDR      = 2'b01;

localparam PRBS_ADDR       = 2'b10;

localparam SEQUENTIAL_ADDR = 2'b11;



// registered the mode settings

always @ (posedge clk_i) begin

   if (rst_i[3])

        if (CMD_PATTERN == "CGEN_BRAM")

         addr_mode_reg  <= #TCQ    3'b000;

        else                                     

         addr_mode_reg  <= #TCQ    3'b011;

   else if (mode_load_pulse)

         addr_mode_reg  <= #TCQ    addr_mode_i;

end



always @ (posedge clk_i) begin

   if (mode_load_pulse) begin

        bl_mode_reg    <= #TCQ    bl_mode_i ;

   end

//   mode_load_d1         <= #TCQ    mode_load_i;
//
//   mode_load_d2         <= #TCQ    mode_load_d1;

end

always @ (posedge clk_i)
begin
  if (rst_i[0])
  begin
   mode_load_d1         <= #TCQ    'b0;
   mode_load_d2         <= #TCQ    'b0;
  end
  else
  begin
   mode_load_d1         <= #TCQ   mode_load_i ;
   mode_load_d2         <= #TCQ   mode_load_d1 ;
  end
end



always @ (posedge clk_i)

     mode_load_pulse <= #TCQ  mode_load_d1 & ~mode_load_d2;



// MUX the addr pattern out depending on the addr_mode setting



// "000" = bram; takes the address from bram output

// "001" = fixed address from the fixed_addr input

// "010" = psuedo ramdom pattern; generated from internal 64 bit LFSR

// "011" = sequential

// "100" = mode that used for prbs addr , prbs bl and prbs data

//always @(addr_mode_reg,prbs_addr,seq_addr,fixed_addr,bram_addr_i,data_mode_i)

always @ (posedge clk_i) begin

if (rst_i[3])

 

  addr_out <= #TCQ    start_addr_i;

else if  (vio_instr_mode_value == 4'h7)

      addr_out <= #TCQ    fixed_addr_i;



else

   case({addr_mode_reg})

         3'b000: addr_out <= #TCQ    bram_addr_i;

         3'b001: addr_out <= #TCQ    fixed_addr;

//         3'b010: addr_out <= #TCQ    {prbs_addr[31:10], 10'h00}; // this is specific to

                                                                 // data mode = PRBS

                                                                 

         3'b010: if (FAMILY == "VIRTEX6")

                    if (data_mode_i == 5)        // ??? optimize this

                         addr_out <= #TCQ    {prbs_addr[31:BL_WIDTH+1], {BL_WIDTH+1{1'b0}}}; // this is specific to

                    else

                     addr_out <= #TCQ    {prbs_addr[31:BL_WIDTH], {BL_WIDTH{1'b0}}}; // this is specific to

                 else

                     addr_out <= #TCQ    {prbs_addr}; 

                 

                                                                 

         3'b011: addr_out <= #TCQ    {2'b0,seq_addr[29:0]};

         3'b100: addr_out <= #TCQ    {3'b000,seq_addr[6:2],seq_addr[23:0]};//{prbs_addr[31:6],6'b000000} ;

         3'b101: addr_out <= #TCQ    {prbs_addr[31:20],seq_addr[19:0]} ;



         default : addr_out <= #TCQ    'b0;

   endcase

end



//  ADDR PRBS GENERATION

generate

if (CMD_PATTERN == "CGEN_PRBS" || CMD_PATTERN == "CGEN_ALL" )

  begin: gen_prbs_addr

  mig_7series_v4_2_cmd_prbs_gen #
   ( 

    .TCQ               (TCQ),
    .FAMILY            (FAMILY),
    .ADDR_WIDTH        (32),
    .DWIDTH            (DWIDTH),
    .MEM_BURST_LEN     (MEM_BURST_LEN),
    .PRBS_WIDTH        (32),
    .SEED_WIDTH        (32),
    .PRBS_EADDR_MASK_POS (PRBS_EADDR_MASK_POS),
    .PRBS_SADDR_MASK_POS (PRBS_SADDR_MASK_POS),
    .PRBS_EADDR        (PRBS_EADDR),
    .PRBS_SADDR        (PRBS_SADDR)
   )

   addr_prbs_gen

  (

   .clk_i            (clk_i),

   .clk_en           (cmd_clk_en),

   .prbs_seed_init   (mode_load_pulse),

   .prbs_seed_i      (cmd_seed_i[31:0]),

   .prbs_o           (prbs_addr)

  );

  end  

  else 

  begin: no_prbs

  assign prbs_addr = 'b0;

 

  end

endgenerate



always @ (posedge clk_i) begin

if (addr_out[31:8] >= end_addr_i[31:8])

    gen_addr_larger <=     1'b1;

else

    gen_addr_larger <=     1'b0;

end

wire [23:0] calc_end_addr /* synthesis syn_dspstyle = logic */ ;
assign calc_end_addr = (bl_out*(DWIDTH/8) + addr_out[31:8]) ;

always @ (posedge clk_i) begin
if (instr_mode_i == 4 && mem_init_done)
    gen_bl_larger <=     1'b0;

else if ( calc_end_addr >= end_addr_i[31:8] )
    gen_bl_larger <=     1'b1;
else
    gen_bl_larger <=     1'b0;
end



//converting string to integer

//localparam MEM_BURST_INT = (MEM_BURST_LEN == "8")? 8 : 4;

localparam MEM_BURST_INT = MEM_BURST_LEN ;


generate

if (FAMILY == "SPARTAN6") begin : INC_COUNTS_S 

  always @ (posedge clk_i)

    if (mem_init_done)
      INC_COUNTS <= #TCQ  (DWIDTH/8)*(bl_out_reg);
    else  begin
      if (fixed_bl_i == 0)
        INC_COUNTS <= #TCQ  (DWIDTH/8)*(64);
      else
        INC_COUNTS <= #TCQ  (DWIDTH/8)*(fixed_bl_i);
    end

  end

else begin : INC_COUNTS_V

  always @ (posedge clk_i) begin
    if (rst_i[3]) begin
      INC_COUNTS[BL_WIDTH-1:0] <= fixed_bl_i * (DWIDTH)/16;
      INC_COUNTS[BL_WIDTH+2:BL_WIDTH]  <= 'b0;
    end
    else
      if (nCK_PER_CLK == 4 && MEM_BURST_LEN != 2)
        INC_COUNTS <= #TCQ  (bl_out << LOGB2_MEM_BURST_INT);
      else begin  
        if (MEM_TYPE != "QDR2PLUS") begin //nCK_PER_CK == 2
          if (MEM_BURST_LEN == 8 || MEM_BURST_LEN == 2) // 13:11
            INC_COUNTS <= #TCQ  (bl_out << (LOGB2_MEM_BURST_INT - 1));
          else
            INC_COUNTS <= #TCQ  (bl_out << LOGB2_MEM_BURST_INT);
        end
        else begin
          INC_COUNTS[BL_WIDTH-1:0] <= #TCQ  bl_out;
          INC_COUNTS[BL_WIDTH+2:BL_WIDTH]  <= 'b0;
        end
      end    
  end

end

endgenerate


generate

// Sequential Address pattern
// It is generated when rdy_i is valid and write command is valid and bl_cmd is valid.
if (CMD_PATTERN == "CGEN_SEQUENTIAL" || CMD_PATTERN == "CGEN_ALL" ) 

  begin : seq_addr_gen

    assign seq_addr = addr_counts;

    always @ (posedge clk_i)
    begin                     

       if (rst_i[2])

            first_mode_load_pulse_set <= 1'b0;

       else if (mode_load_pulse_r1)

            first_mode_load_pulse_set <= #TCQ  1'b1;
    end

    always @ (posedge clk_i)
    begin

        mode_load_pulse_r1 <= #TCQ  mode_load_pulse;
        first_mode_load_pulse_r1 <= #TCQ  mode_load_pulse & ~first_mode_load_pulse_set;
    end

    always @ (posedge clk_i) 
    begin

       if (rst_i[4])

           mem_init_done_r <= #TCQ    1'b0  ;

       else if (cmd_clk_en_r)

           mem_init_done_r <= #TCQ    mem_init_done  ;
    end
    

    reg COut_b,COut_c;
    wire [32:0] addr_counts_added;
    assign addr_counts_added =  addr_counts + INC_COUNTS /* synthesis syn_dspstyle = logic */ ;

    always @ (posedge clk_i)

        addr_counts_next_r <= #TCQ addr_counts_added ;


    always @ (posedge clk_i)

      cmd_clk_en_r <= #TCQ  cmd_clk_en;
      

    always @ (posedge clk_i)
    begin

       if (rst_i[4]) begin

         addr_counts <= #TCQ    start_addr_i;
         mem_init_done <= #TCQ  1'b0;

       end 

       else if (cmd_clk_en_r || first_mode_load_pulse_r1)

          if(addr_counts_next_r >= end_addr_i  ) begin

               addr_counts <= #TCQ    start_addr_i;
               mem_init_done <= #TCQ  1'b1;

          end 

          else  // address counts get incremented by burst_length and port size each wr command generated

                {COut_c,addr_counts} <= #TCQ addr_counts_added ;
    end

 end

 else

  begin: no_gen_seq_addr

   assign seq_addr = 'b0;

  end

endgenerate

always @ (posedge clk_i) begin

   if (rst_i[4]) 

         n_gen_write_only <= 1'b0;

   else if (~n_gen_write_only && addr_counts_next_r>= end_addr_i)

         n_gen_write_only <= 1'b1;

   

   else if(addr_counts_next_r>= end_addr_i && instr_out[0] == 1'b0) 

         n_gen_write_only <= 1'b0;
end    

generate

// Fixed Address pattern
if (CMD_PATTERN == "CGEN_FIXED" || CMD_PATTERN == "CGEN_ALL" ) 

  begin : fixed_addr_gen

    assign fixed_addr = (DWIDTH == 32)?  {fixed_addr_i[31:2],2'b0} :

                        (DWIDTH == 64)?  {fixed_addr_i[31:3],3'b0}:

                        (DWIDTH <= 128)? {fixed_addr_i[31:4],4'b0}:

                        (DWIDTH <= 256)? {fixed_addr_i[31:5],5'b0}:

                                         {fixed_addr_i[31:6],6'b0};

  end

else 

  begin : no_fixed_addr_gen

    assign fixed_addr = 'b0;

  end

endgenerate


generate

// BRAM Address pattern
if (CMD_PATTERN == "CGEN_BRAM" || CMD_PATTERN == "CGEN_ALL" ) 

  begin : bram_addr_gen

     assign bram_rdy_o = run_traffic_i & cmd_clk_en & bram_valid_i | mode_load_pulse;

  end

else

  begin: no_bram_addr_gen

     assign bram_rdy_o = 1'b0;

  end   

endgenerate



///////////////////////////////////////////////////////////////////////////

//  INSTR COMMAND GENERATION



// tap points are 3,2

//`define RD              3'b001

//`define RDP             3'b011

//`define WR              3'b000

//`define WRP             3'b010

//`define REFRESH         3'b100

// use 14 stages  1 sr16; tap position 1,3,5,14



always @ (posedge clk_i) begin

if (rst_i[4])

    force_rd_counts <= #TCQ  'b0;

else if (instr_vld) begin

    force_rd_counts <= #TCQ  force_rd_counts + 1'b1;

    end

end



always @ (posedge clk_i) begin

if (rst_i[4])

    force_rd <= #TCQ  1'b0;

else if (force_rd_counts[3])

    force_rd <= #TCQ  1'b1;

else

    force_rd <= #TCQ  1'b0;

end

// adding refresh timer to limit the amount of issuing refresh command.

always @ (posedge clk_i) begin

if (rst_i[4])

   refresh_timer <= #TCQ  'b0;

else

   refresh_timer <= #TCQ  refresh_timer + 1'b1;

end


always @ (posedge clk_i) begin

if (rst_i[4])

   refresh_cmd_en <= #TCQ  'b0;

//else if (refresh_timer >= 12'hff0 && refresh_timer <= 12'hfff)

else if (refresh_timer == 10'h3ff)

   refresh_cmd_en <= #TCQ  'b1;

else if (cmd_clk_en && refresh_cmd_en)

   refresh_cmd_en <= #TCQ  'b0;
end   

always @ (posedge clk_i) begin

if (FAMILY == "SPARTAN6")

    refresh_prbs <= #TCQ  prbs_instr_b[3] & refresh_cmd_en;

else

    refresh_prbs <= #TCQ  1'b0;

end    

always @ (posedge clk_i)
begin
if (rst_i[4])
    write_percent_cnt <= 'b0;
else if (cmd_clk_en_r)
    if ( write_percent_cnt == 9)
        write_percent_cnt <= 'b0;
    else
        write_percent_cnt <= write_percent_cnt + 1'b1;
end          
always @ (posedge clk_i)
begin
if (rst_i[4])
          toggle_rw <= 1'b0;
else if (cmd_clk_en_r && mem_init_done)
    if (write_percent_cnt >= vio_percent_write)
          toggle_rw <= 1'b1;
    else
          toggle_rw <= 1'b0;
end  

always @ (posedge clk_i) begin

   case(instr_mode_i)

         0: instr_out <= #TCQ    bram_instr_i;

         1: instr_out <= #TCQ    fixed_instr_i;

         2: instr_out <= #TCQ    {2'b00,(prbs_instr_a[0] | force_rd)};
         3: instr_out <= #TCQ    {2'b00,prbs_instr_a[0]};  //:  WP/RP
         4: instr_out <= #TCQ    {2'b00,toggle_rw};  //  percent write


         // may be add another PRBS for generating REFRESH

//         5: instr_out <= #TCQ    {prbs_instr_b[3],prbs_instr_b[0], prbs_instr_a[0]};  // W/WP/R/RP/REFRESH W/WP/R/RP/REFRESH

         5: instr_out <= #TCQ    {refresh_prbs ,prbs_instr_b[0], prbs_instr_a[0]};  // W/WP/R/RP/REFRESH W/WP/R/RP/REFRESH





         default : instr_out <= #TCQ    {2'b00,1'b1};

   endcase

end



generate  // PRBS INSTRUCTION generation

// use two PRBS generators and tap off 1 bit from each to create more randomness for

// generating actual read/write commands

if (CMD_PATTERN == "CGEN_PRBS" || CMD_PATTERN == "CGEN_ALL" ) 

  begin: gen_prbs_instr

   mig_7series_v4_2_cmd_prbs_gen #
     (

       .TCQ               (TCQ),

       .PRBS_CMD    ("INSTR"),

       .DWIDTH     (DWIDTH),

       

       .ADDR_WIDTH  (32),

       .SEED_WIDTH  (15),

       .PRBS_WIDTH  (20)

      )

      instr_prbs_gen_a

     (

      .clk_i              (clk_i),

      .clk_en             (cmd_clk_en),

      .prbs_seed_init     (load_seed_i),

      .prbs_seed_i        (cmd_seed_i[14:0]),

      .prbs_o             (prbs_instr_a)

     );

   mig_7series_v4_2_cmd_prbs_gen #
     (

       .PRBS_CMD    ("INSTR"),

       .DWIDTH     (DWIDTH),

       

       .SEED_WIDTH  (15),

       .PRBS_WIDTH  (20)

      )
      instr_prbs_gen_b
     (

      .clk_i              (clk_i),

      .clk_en             (cmd_clk_en),

      .prbs_seed_init     (load_seed_i),

      .prbs_seed_i        (cmd_seed_i[16:2]),

      .prbs_o             (prbs_instr_b)

     );

  end

 else

  begin: no_prbs_instr_gen

     assign prbs_instr_a = 'b0;

     assign prbs_instr_b = 'b0;

  end     

endgenerate



///////////////////////////////////////////////////////////////////////////////////////////////////////////////

// BURST LENGTH GENERATION

// burst length code = user burst length input - 1

// mcb_flow_control does the minus before sending out to mcb\

// when filling up the memory, need to make sure bl doesn't go beyound its upper limit boundary

//assign force_bl1 = (addr_out[31:0] >= (end_addr_i[31:0] - 4*64)) ? 1'b1: 1'b0;

// for neighbour pattern, need to limit the bl to make sure it is within column size boundary.



// This is required in S6 .



always  @ (posedge clk_i)

begin

if (rst_i[4] )

        cal_blout <= 'b0;

else

    cal_blout <= bl_out* (DWIDTH/8);

end

wire [31:0] dummy;
wire [32:0] dummy_sub;

assign dummy = (addr_out + cal_blout);
assign dummy_sub = (dummy - end_addr_i);

always @(*) begin

    force_bl1 = 1'b0;
    if (rst_i[6] || (mem_init_done && instr_mode_i == 4))
        force_bl1 = 1'b0;
    else if ((dummy_sub[32] == 0) || (buf_avail_r <= 50 && PORT_MODE == "RD_MODE"))
        force_bl1 = 1'b1;

end

//always @(addr_out,mem_init_done, instr_mode_i,bl_out,cal_blout,end_addr_i,rst_i,buf_avail_r,bl_x_DWIDTH_BY_8) begin

//    if (rst_i[6])
//        force_bl1 =   1'b0;
//    else if (mem_init_done && instr_mode_i == 4)
//        force_bl1 =   1'b0;

//    else if (((addr_out + cal_blout) >= end_addr_i) || (buf_avail_r  <= 50 && PORT_MODE == "RD_MODE"))

//        force_bl1 =   1'b1;

//    else

//        force_bl1 =   1'b0; 
//end

always @(posedge clk_i) begin

   if (rst_i[6])

       bl_out_reg <= #TCQ    fixed_bl_i;

   else if (bl_out_vld)

       bl_out_reg <= #TCQ    bl_out;

end

// BurstLength defination in Traffic Gen is the  consecutive write/read commands

// that sent to Memory Controller User Interface. In V6, cmd_gen module sends

// the number of burst length to rd_data_gen, wr_data_gen  and mcb_flow_control_v6.

// The mcb_flow_control takes the base address of the first burst and the bl value,

// it automatically increment the next consecutive address of the back-to-back commands

// until the burst counts decrement to 0.

//verilint STARC-2.2.3.3 off
always @ (posedge clk_i) begin

   if (mode_load_pulse || rst_i[3])

      if (data_mode_i == 4)

         bl_out <= #TCQ  10'd32 ;

      else

        bl_out <= #TCQ    fixed_bl_i ;

   else if (cmd_clk_en) begin

     case({bl_mode_reg})

         0:  begin

                 bl_out[5:0] <= #TCQ  bram_bl_i  ;

                 bl_out[BL_WIDTH-1:6] <= #TCQ  'b0  ;

                 

             end

         1: if (data_mode_i == 4)

                bl_out <= #TCQ  10'd32 ;

            else

                bl_out <= #TCQ  fixed_bl_i ;

         2: bl_out <= #TCQ  prbs_brlen;

         default : begin

                    bl_out[5:0] <= #TCQ    6'h1;

                    bl_out[BL_WIDTH - 1:6] <= #TCQ  'b0;

                    

                   end

     endcase

   end

end
//verilint STARC-2.2.3.3 off


  //synthesis translate_off

//always @ (bl_out)

//  if(bl_out >2 && FAMILY == "VIRTEX6") begin

//   $display("Error ! Not valid burst length");

//   $stop;

//   end

  //synthesis translate_on



generate

if (CMD_PATTERN == "CGEN_PRBS" || CMD_PATTERN == "CGEN_ALL" ) 

   begin: gen_prbs_bl

       mig_7series_v4_2_cmd_prbs_gen #
          (

        .TCQ               (TCQ),      

        .FAMILY      (FAMILY),

        .PRBS_CMD    ("BLEN"),

        .ADDR_WIDTH  (32),

        .SEED_WIDTH  (15),

        .PRBS_WIDTH  (20)

       )

       bl_prbs_gen

      (

       .clk_i             (clk_i),

       .clk_en            (cmd_clk_en),

       .prbs_seed_init    (load_seed_i),

       .prbs_seed_i       (cmd_seed_i[16:2]),

       .prbs_o            (prbs_bl)

      );

      

    always @ (prbs_bl)

     if (FAMILY == "SPARTAN6" || FAMILY == "MCB")  // supports 1 throug 64

       prbs_brlen[5:0]  =  (prbs_bl[5:1] == 5'b00000) ? 6'b000010: {prbs_bl[5:1],1'b0};

     else // VIRTEX6 only supports 1 or 2 burst on user ports

       prbs_brlen =  (prbs_bl[BL_WIDTH-1:1] == 5'b00000) ? {{BL_WIDTH-2{1'b0}},2'b10}: {prbs_bl[BL_WIDTH-1:1],1'b0};

  end

 else

    begin: no_gen_prbs_bl

       assign prbs_bl = 'b0;

    end

endgenerate

endmodule
