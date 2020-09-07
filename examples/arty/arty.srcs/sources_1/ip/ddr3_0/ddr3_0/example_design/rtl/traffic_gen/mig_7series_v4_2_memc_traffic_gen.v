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
//  \   \         Application: MEMC
//  /   /         Filename: memc_traffic_gen.v
// /___/   /\     Date Last Modified: $Date:
// \   \  /  \    Date Created:
//  \___\/\___\
//
//Device: Spartan6/Virtex6
//Design Name: memc_traffic_gen
//Purpose: This is top level module of memory traffic generator which can
//         generate different CMD_PATTERN and DATA_PATTERN to Spartan 6
//         hard memory controller core.
//Reference:
//Revision History:     1.1    Brought out internal signals cmp_data and cmp_error as outputs.
//                      1.2    7/1/2009  Added EYE_TEST parameter for signal SI probing.
//                      1.3    10/1/2009 Added dq_error_bytelane_cmp,cumlative_dq_lane_error signals for V6.
//                                       Any comparison error on user read data bus are mapped back to 
//                                       dq bus.  The cumulative_dq_lane_error accumulate any errors on
//                                       DQ bus. And the dq_error_bytelane_cmp shows error during current 
//                                       command cycle. The error can be cleared by input signal "manual_clear_error".
//                      1.4    7/29/10  Support virtex Back-to-back commands over user interface.
//                  
//                             1/4/2012  Added vio_percent_write (instr_mode == 4) to
//                                       let user specify percentage of write commands out of mix
//                                       write/read commands. 

//*****************************************************************************
`timescale 1ps/1ps

module mig_7series_v4_2_memc_traffic_gen #
  (
   parameter TCQ           = 100,            // SIMULATION tCQ delay.
   parameter FAMILY        = "SPARTAN6",     // "VIRTEX6", "SPARTAN6"
   parameter MEM_TYPE      = "DDR3",
   parameter SIMULATION    = "FALSE",
   parameter tCK           = 2500,
   parameter nCK_PER_CLK   = 4,            // DRAM clock : MC clock
   
   parameter BL_WIDTH      = 6,
   parameter MEM_BURST_LEN = 8,               // For VIRTEX6 Only in this traffic gen.
                                              // This traffic gen doesn't support DDR3 OTF Burst mode.

   parameter PORT_MODE     = "BI_MODE",       // SPARTAN6: "BI_MODE", "WR_MODE", "RD_MODE"
                                              // VIRTEX6: "BI_MODE"
   parameter DATA_PATTERN  = "DGEN_ALL", // "DGEN__HAMMER", "DGEN_WALING1","DGEN_WALING0","DGEN_ADDR","DGEN_NEIGHBOR","DGEN_PRBS","DGEN_ALL"
   parameter CMD_PATTERN   = "CGEN_ALL",     // "CGEN_RPBS","CGEN_FIXED",  "CGEN_BRAM", "CGEN_SEQUENTIAL", "CGEN_ALL",

   parameter ADDR_WIDTH    = 30,             // Spartan 6 Addr width is 30

   parameter BANK_WIDTH    = 3,

   parameter CMP_DATA_PIPE_STAGES = 0,       // parameter for MPMC, it should always set to 0

   // memory type specific
   parameter MEM_COL_WIDTH = 10,             // memory column width
   parameter NUM_DQ_PINS   = 16,             // Spartan 6 Options: 4,8,16;
                                             // Virtex 6 DDR2/DDR3 Options: 8,16,24,32,.....144

   parameter SEL_VICTIM_LINE = 3,            // SEL_VICTIM_LINE LINE is one of the DQ pins is selected to be different than hammer pattern
                                             // SEL_VICTIM_LINE is only for V6.
                                             // Virtex 6 option: 8,9,16,17,32,36,64,72
   parameter DWIDTH        = NUM_DQ_PINS*2*nCK_PER_CLK,             //NUM_DQ_PINS*4,         // Spartan 6 Options: 32,64,128;
                                             // Virtex 6 Always: 4* NUM_DQ_PINS


   // the following parameter is to limit the range of generated PRBS Address
   //
   //      e.g PRBS_SADDR_MASK_POS = 32'h0000_7000   the bit 14:12 of PRBS_SADDR will be ORed with
   //          PRBS_SADDR          = 32'h0000_5000   the LFSR[14:12] to add the starting address offset.

   //          PRBS_EADDR          = 32'h0000_7fff
   //          PRBS_EADDR_MASK_POS = 32'hffff_7000 => mark all the leading 0's in PRBS_EADDR to 1 to
   //                                                 zero out the LFSR[31:15]

   parameter PRBS_EADDR_MASK_POS = 32'hFFFFD000,
   parameter PRBS_SADDR_MASK_POS =  32'h00002000,
   parameter PRBS_EADDR = 32'h00002000,
   parameter PRBS_SADDR = 32'h00005000,
   parameter EYE_TEST   = "FALSE"  // set EYE_TEST = "TRUE" to probe memory signals.
                                   // Traffic Generator will only write to one single location and no
                                   // read transactions will be generated.


 )

 (

   input                    clk_i,
   input                    rst_i,
   input                    run_traffic_i,
   input                    single_operation,
   input                    manual_clear_error,
   input [5:0]              cmds_gap_delay_value,  // control delay gap between each sucessive
   input [3:0]              vio_instr_mode_value,
   input [3:0]              vio_percent_write,
                                                   // burst commands.
   
  // *** runtime parameter ***
   input                    mem_pattern_init_done_i,
   input [31:0]             start_addr_i,   // define the start of address
   input [31:0]             end_addr_i,     // define upper limit addressboundary
   input [31:0]             cmd_seed_i,     // seed for cmd PRBS generators
   input [31:0]             data_seed_i,    // data seed will be added to generated address
                                            // for PRBS data generation
    // seed for cmd PRBS generators
   input                    load_seed_i,   //  when asserted the cmd_seed and data_seed inputs will be registered.

   // upper layer inputs to determine the command bus and data pattern
   // internal traffic generator initialize the memory with
   input [2:0]              addr_mode_i,  // "00" = bram; takes the address from bram interface
                                          // "01" = fixed address from the fixed_addr input
                                          // "10" = psuedo ramdom pattern; generated from internal 64 bit LFSR
                                          // "11" = sequential


  // for each instr_mode, traffic gen fill up with a predetermined pattern before starting the instr_pattern that defined
  // in the instr_mode input. The runtime mode will be automatically loaded inside when it is in
   input [3:0]              instr_mode_i, // "0000" = BRAM
                                          // "0001" = Fixed; takes instruction from bram output
                                          // "0010" = R/W
                                          // "0011" = RP/WP
                                          // "0100" = R/RP/W/WP
                                          // "0101" = R/RP/W/WP/REF
                                          // "0110" = PRBS
                                          // "1111" = Read Only from Address 0 . Expecting phy calibration data pattern.


   input [1:0]              bl_mode_i,    // "00" = bram;   takes the burst length from bram output
                                          // "01" = fixed , takes the burst length from the fixed_bl input
                                          // "10" = psuedo ramdom pattern; generated from internal 16 bit LFSR

   input [3:0]              data_mode_i,   // "000" = address as data
                                           // "001" = hammer
                                           // "010" = neighbour
                                           // "011" = prbs
                                           // "100" = walking 0's
                                           // "101" = walking 1's
                                           // "110" =
                                           // "111" =

   input                    wr_data_mask_gen_i,  //  "1": turn on wr_data_mask generation
                                              //  random follow by walking 1's
   input                    mode_load_i,

   // fixed pattern inputs interface
   input [BL_WIDTH - 1:0]              fixed_bl_i,      // range from 1 to 64
   input [2:0]              fixed_instr_i,   //RD              3'b001
                                             //RDP             3'b011
                                             //WR              3'b000
                                             //WRP             3'b010
                                             //REFRESH         3'b100


   input [31:0]             fixed_addr_i,       // only upper 30 bits will be used
   input [31:0]       fixed_data_i, // 

   input [31:0]             simple_data0 ,
   input [31:0]             simple_data1 ,
   input [31:0]             simple_data2 ,
   input [31:0]             simple_data3 ,
   input [31:0]             simple_data4 ,
   input [31:0]             simple_data5 ,
   input [31:0]             simple_data6 ,
   input [31:0]             simple_data7 ,


   // BRAM interface.
                                          //   bram bus formats:
                                          //   Only SP6 has been tested.
   input [38:0]             bram_cmd_i,   //  {{bl}, {cmd}, {address[28:2]}}
   input                    bram_valid_i,
   output                   bram_rdy_o,  //

   /////////////////////////////////////////////////////////////////////////////
   //  MCB INTERFACE
   // interface to mcb command port
   output                   memc_cmd_en_o,
   output [2:0]             memc_cmd_instr_o,
   output [31:0]            memc_cmd_addr_o,
   output [5:0]             memc_cmd_bl_o,      // this output is for Spartan 6

   input                    memc_cmd_full_i,
   // interface to qdr interface
   output                   qdr_wr_cmd_o,
   output                   qdr_rd_cmd_o,

   // interface to mcb wr data port
   output                   memc_wr_en_o,
   output [DWIDTH-1:0]      memc_wr_data_o,
   output                   memc_wr_data_end_o,
   output [(DWIDTH/8) - 1:0]  memc_wr_mask_o,

   input                    memc_wr_full_i,

   // interface to mcb rd data port
   output                   memc_rd_en_o,
   input [DWIDTH-1:0]       memc_rd_data_i,
   input                    memc_rd_empty_i,
   /////////////////////////////////////////////////////////////////////////////
   // status feedback
   input                    counts_rst,
   output reg [47:0]        wr_data_counts,
   output reg [47:0]        rd_data_counts,
   output                   cmp_error,
   output                   cmp_data_valid,
   output                   error,       // asserted whenever the read back data is not correct.
   output  [64 + (2*DWIDTH - 1):0]            error_status ,// TBD how signals mapped
   output [DWIDTH-1:0]      cmp_data,
   output [DWIDTH-1:0]      mem_rd_data,
   
   
   // **** V6 Signals
   output [NUM_DQ_PINS/8 - 1:0] dq_error_bytelane_cmp,   // V6: real time compare error byte lane
   output [NUM_DQ_PINS/8 - 1:0] cumlative_dq_lane_error,  // V6: latched error byte lane that occure on
                                                       //     first error
                                                       
  //************************************************
  // DQ bit error debug signals.
                                                       
   output [NUM_DQ_PINS - 1:0] cumlative_dq_r0_bit_error ,                                                   
   output [NUM_DQ_PINS - 1:0] cumlative_dq_f0_bit_error ,                                                   
   output [NUM_DQ_PINS - 1:0] cumlative_dq_r1_bit_error ,                                                   
   output [NUM_DQ_PINS - 1:0] cumlative_dq_f1_bit_error ,  
   
   output [NUM_DQ_PINS-1:0] dq_r0_bit_error_r, 
   output [NUM_DQ_PINS-1:0] dq_f0_bit_error_r, 
   output [NUM_DQ_PINS-1:0] dq_r1_bit_error_r, 
   output [NUM_DQ_PINS-1:0] dq_f1_bit_error_r, 
   
   
   
                                                  // 
   output  [NUM_DQ_PINS - 1:0] dq_r0_read_bit,   // rising 0 read bits from mc
   output  [NUM_DQ_PINS - 1:0] dq_f0_read_bit,   // falling 0 read bits from mc
   output  [NUM_DQ_PINS - 1:0] dq_r1_read_bit,   // rising 1 read bits from mc
   output  [NUM_DQ_PINS - 1:0] dq_f1_read_bit,   // falling 1 read bits from mc
   output  [NUM_DQ_PINS - 1:0] dq_r0_expect_bit, // rising 0 read bits from internal expect data generator  
   output  [NUM_DQ_PINS - 1:0] dq_f0_expect_bit, // falling 0 read bits from internal expect data generator   
   output  [NUM_DQ_PINS - 1:0] dq_r1_expect_bit, // rising 1 read bits from internal expect data generator   
   output  [NUM_DQ_PINS - 1:0] dq_f1_expect_bit, // falling 1 read bits from internal expect data generator  
   output  [31:0]              error_addr          //  the  command address of the returned data. 
                                                   //  Can use dq_rx_bit_error as write enable to latch the address.    
   


  );


   wire [DWIDTH-1:0]        rdpath_rd_data_i;
   wire                     rdpath_data_valid_i;
   wire                     memc_wr_en;
   wire                     cmd2flow_valid;
   wire [2:0]               cmd2flow_cmd;
   wire [31:0]              cmd2flow_addr;
   wire [BL_WIDTH-1:0]               cmd2flow_bl;
   wire                     last_word_wr;
   wire                     flow2cmd_rdy;
   wire [31:0]              wr_addr;
   wire [31:0]              rd_addr;
   wire [BL_WIDTH-1:0]               wr_bl;
   wire [BL_WIDTH-1:0]               rd_bl;
   reg                      run_traffic_reg;
wire wr_validB, wr_valid,wr_validC;
wire [31:0] bram_addr_i;
wire [2:0] bram_instr_i;
wire [5:0] bram_bl_i;
reg AC2_G_E2,AC1_G_E1,AC3_G_E3;
reg upper_end_matched;
reg [7:0] end_boundary_addr;
reg lower_end_matched;
wire [31:0] addr_o;
wire [31:0] m_addr;
wire dcount_rst;
wire [31:0] rd_addr_error;
wire rd_rdy;
//wire cmp_error;
wire  cmd_full;
wire rd_mdata_fifo_rd_en;
wire rd_mdata_fifo_afull;
reg memc_wr_en_r;
wire memc_wr_data_end;
reg  [DWIDTH-1:0]       memc_rd_data_r;

wire [DWIDTH-1:0] memc_wr_data;
reg [DWIDTH-1:0] memc_wr_data_r;


wire              wr_path_data_rdy_i;
//
wire [31:0]       cmp_addr;
wire [5:0]       cmp_bl;


reg [9:0]         rst_ra,rst_rb /* synthesis syn_maxfan = 10 */;
wire       mem_init_done;
reg [3:0] data_mode_r_a;
reg [3:0] data_mode_r_b;
reg [3:0] data_mode_r_c;
reg error_access_range = 1'b0;

wire [BL_WIDTH-1:0] memc_bl_o;

// generic parameters and need to be tested in both MCB mode and V7 Virtext Mode.


  initial begin
    if((MEM_BURST_LEN !== 4) && (MEM_BURST_LEN !== 8) && (MEM_BURST_LEN !== 2)) 
    begin: NO_OTF_Warning_Error
      $display("Current Traffic Generator logic does not support OTF (On The Fly) Burst Mode!");
      $stop;
    end
    else
    begin: Dummy1
    
    end
  end

always @ (memc_cmd_en_o,memc_cmd_addr_o,memc_cmd_bl_o,start_addr_i,end_addr_i)
if (memc_cmd_en_o && 
     ((FAMILY == "SPARTAN6" && memc_cmd_addr_o + 20) > end_addr_i[ADDR_WIDTH-1:0]) || 
     ((FAMILY == "VIRTEX6" && memc_cmd_addr_o ) > end_addr_i[ADDR_WIDTH-1:0])
    )
   begin
   $display("Error ! Command access beyond address range");
   $display("Assigned Address Space: Start_Address = 0x%h ; End_Addr = 0x%h",start_addr_i,end_addr_i); 
   $display("Attempted area = 0x%h",memc_cmd_addr_o + (memc_cmd_bl_o - 1) * (DWIDTH/8)); 
   
   $stop;
   end
else
begin: No_Error_Display
 
end

assign memc_cmd_bl_o = memc_bl_o[5:0];





always @ (posedge clk_i)
begin
    data_mode_r_a <= #TCQ data_mode_i;
    data_mode_r_b <= #TCQ data_mode_i;
    data_mode_r_c <= #TCQ data_mode_i;
end




//reg GSR = 1'b0;
   always @(rst_i)
   begin
         rst_ra = {rst_i,rst_i,rst_i,rst_i,rst_i,rst_i,rst_i,rst_i,rst_i,rst_i};
         rst_rb = {rst_i,rst_i,rst_i,rst_i,rst_i,rst_i,rst_i,rst_i,rst_i,rst_i};

   end
   // register it . Just in case the calling modules didn't syn with clk_i
   always @(posedge clk_i)
   begin
       run_traffic_reg <= #TCQ run_traffic_i;
   end

   assign bram_addr_i = {bram_cmd_i[29:0],2'b00};
   assign bram_instr_i = bram_cmd_i[32:30];
   assign bram_bl_i[5:0] = bram_cmd_i[38:33];  //41

//
//
reg COutc,COutd;

assign dcount_rst = counts_rst | rst_ra[0];
always @ (posedge clk_i)
begin
  if (dcount_rst)
      wr_data_counts <= #TCQ 'b0;
  else if (memc_wr_en)
      {COutc,wr_data_counts} <= #TCQ wr_data_counts + DWIDTH/8;

end

always @ (posedge clk_i)
begin
  if (dcount_rst)
      rd_data_counts <= #TCQ 'b0;
  else if (memc_rd_en_o)
      {COutd,rd_data_counts} <= #TCQ rd_data_counts + DWIDTH/8;

end



// ****  for debug
// this part of logic is to check there are no commands been duplicated or dropped
// in the cmd_flow_control logic
generate
if (SIMULATION == "TRUE") 
begin: cmd_check
wire fifo_error;
wire [31:0] xfer_addr;
wire [BL_WIDTH-1:0] xfer_cmd_bl;
wire cmd_fifo_rd;

assign cmd_fifo_wr =  flow2cmd_rdy & cmd2flow_valid;

assign fifo_error = ( xfer_addr != memc_cmd_addr_o) ? 1'b1: 1'b0;


wire cmd_fifo_empty;
//assign cmd_fifo_rd = memc_cmd_en_o & ~memc_cmd_full_i & ~cmd_fifo_empty;
assign cmd_fifo_rd = memc_cmd_en_o  & ~cmd_fifo_empty;


  mig_7series_v4_2_afifo #
   (.TCQ           (TCQ),
    .DSIZE         (32+BL_WIDTH),
    .FIFO_DEPTH    (16),
    .ASIZE         (4),
    .SYNC          (1)  // set the SYNC to 1 because rd_clk = wr_clk to reduce latency


   )
   cmd_fifo
   (
    .wr_clk        (clk_i),
    .rst           (rst_ra[0]),
    .wr_en         (cmd_fifo_wr),
    .wr_data       ({cmd2flow_bl,cmd2flow_addr}),
    .rd_en         (cmd_fifo_rd),
    .rd_clk        (clk_i),
    .rd_data       ({xfer_cmd_bl,xfer_addr}),
    .full          (cmd_fifo_full),
    .almost_full   (),
    .empty         (cmd_fifo_empty)

   );


end
else
begin
  assign fifo_error = 1'b0;
end

endgenerate

reg [31:0] end_addr_r;
 always @ (posedge clk_i)
    end_addr_r <= end_addr_i;


   mig_7series_v4_2_cmd_gen
     #(
       .TCQ                 (TCQ),
       .FAMILY              (FAMILY)     ,
       .MEM_TYPE           (MEM_TYPE),
       
       .BL_WIDTH            (BL_WIDTH),
       .nCK_PER_CLK       (nCK_PER_CLK),
       
       .MEM_BURST_LEN       (MEM_BURST_LEN),
       .PORT_MODE           (PORT_MODE),
       .BANK_WIDTH          (BANK_WIDTH),
       .NUM_DQ_PINS         (NUM_DQ_PINS),
       .DATA_PATTERN        (DATA_PATTERN),
       .CMD_PATTERN         (CMD_PATTERN),
       .ADDR_WIDTH          (ADDR_WIDTH),
       .DWIDTH              (DWIDTH),
       .MEM_COL_WIDTH       (MEM_COL_WIDTH),
       .PRBS_EADDR_MASK_POS (PRBS_EADDR_MASK_POS ),
       .PRBS_SADDR_MASK_POS (PRBS_SADDR_MASK_POS  ),
       .PRBS_EADDR          (PRBS_EADDR),
       .PRBS_SADDR          (PRBS_SADDR )

       )
   u_c_gen
     (
      .clk_i              (clk_i),
      .rst_i               (rst_ra),
      .reading_rd_data_i (memc_rd_en_o),
      .vio_instr_mode_value          (vio_instr_mode_value),
      .vio_percent_write             (vio_percent_write),
      .single_operation (single_operation),
      .run_traffic_i    (run_traffic_reg),
      .mem_pattern_init_done_i   (mem_pattern_init_done_i),
      .start_addr_i     (start_addr_i),
      .end_addr_i       (end_addr_r),
      .cmd_seed_i       (cmd_seed_i),
      .load_seed_i      (load_seed_i),
      .addr_mode_i      (addr_mode_i),
      .data_mode_i        (data_mode_r_a),

      .instr_mode_i     (instr_mode_i),
      .bl_mode_i        (bl_mode_i),
      .mode_load_i      (mode_load_i),
   // fixed pattern inputs interface
      .fixed_bl_i       (fixed_bl_i),
      .fixed_addr_i     (fixed_addr_i),
      .fixed_instr_i    (fixed_instr_i),
   // BRAM FIFO input :  Holist vector inputs

      .bram_addr_i      (bram_addr_i),
      .bram_instr_i     (bram_instr_i ),
      .bram_bl_i        (bram_bl_i ),
      .bram_valid_i     (bram_valid_i ),
      .bram_rdy_o       (bram_rdy_o   ),

      .rdy_i            (flow2cmd_rdy),
      .instr_o          (cmd2flow_cmd),
      .addr_o           (cmd2flow_addr),
      .bl_o             (cmd2flow_bl),
//      .m_addr_o         (m_addr),
      .cmd_o_vld        (cmd2flow_valid),
      .mem_init_done_o  (mem_init_done)

      );

assign memc_cmd_addr_o = addr_o;


assign qdr_wr_cmd_o = memc_wr_en_r;

assign cmd_full = memc_cmd_full_i;
   mig_7series_v4_2_memc_flow_vcontrol #
     (
       .TCQ           (TCQ),
       .nCK_PER_CLK       (nCK_PER_CLK),
       
       .BL_WIDTH          (BL_WIDTH),
       .MEM_BURST_LEN     (MEM_BURST_LEN),
       .NUM_DQ_PINS          (NUM_DQ_PINS),       
       .FAMILY  (FAMILY),
       .MEM_TYPE           (MEM_TYPE)
       
     )
   memc_control
     (
      .clk_i                   (clk_i),
      .rst_i                   (rst_ra),
      .data_mode_i             (data_mode_r_b),
      .cmds_gap_delay_value    (cmds_gap_delay_value),
      .mcb_wr_full_i           (memc_wr_full_i),
      .cmd_rdy_o               (flow2cmd_rdy),
      .cmd_valid_i             (cmd2flow_valid),
      .cmd_i                   (cmd2flow_cmd),
      

      .mem_pattern_init_done_i (mem_pattern_init_done_i),
      
      .addr_i                  (cmd2flow_addr),
      .bl_i                    (cmd2flow_bl),
      // interface to memc_cmd port
      .mcb_cmd_full            (cmd_full),
      .cmd_o                   (memc_cmd_instr_o),
      .addr_o                  (addr_o),
      .bl_o                    (memc_bl_o),
      .cmd_en_o                (memc_cmd_en_o),
      .qdr_rd_cmd_o            (qdr_rd_cmd_o), 
   // interface to write data path module
   
      .mcb_wr_en_i             (memc_wr_en),
      .last_word_wr_i          (last_word_wr),
      .wdp_rdy_i               (wr_rdy),//(wr_rdy),
      .wdp_valid_o             (wr_valid),
      .wdp_validB_o            (wr_validB),
      .wdp_validC_o            (wr_validC),

      .wr_addr_o               (wr_addr),
      .wr_bl_o                 (wr_bl),
   // interface to read data path module

      .rdp_rdy_i               (rd_rdy),// (rd_rdy),
      .rdp_valid_o             (rd_valid),
      .rd_addr_o               (rd_addr),
      .rd_bl_o                 (rd_bl)

      );


  /* afifo #
   (
   
    .TCQ           (TCQ),
    .DSIZE         (DWIDTH),
    .FIFO_DEPTH    (32),
    .ASIZE         (5),
    .SYNC          (1)  // set the SYNC to 1 because rd_clk = wr_clk to reduce latency 
   
   
   )
   rd_mdata_fifo
   (
    .wr_clk        (clk_i),
    .rst           (rst_rb[0]),
    .wr_en         (!memc_rd_empty_i),
    .wr_data       (memc_rd_data_i),
    .rd_en         (memc_rd_en_o),
    .rd_clk        (clk_i),
    .rd_data       (rd_v6_mdata),
    .full          (),
    .almost_full   (rd_mdata_fifo_afull),
    .empty         (rd_mdata_fifo_empty)
   
   );
*/

wire cmd_rd_en;

assign cmd_rd_en =  memc_cmd_en_o;




assign rdpath_data_valid_i =!memc_rd_empty_i ;
assign rdpath_rd_data_i = memc_rd_data_i ;


generate
if (PORT_MODE == "RD_MODE" || PORT_MODE == "BI_MODE") 
begin : RD_PATH
   mig_7series_v4_2_read_data_path
     #(
       .TCQ           (TCQ),
       .FAMILY            (FAMILY)  ,
       .MEM_TYPE           (MEM_TYPE),
       .BL_WIDTH          (BL_WIDTH),
       .nCK_PER_CLK       (nCK_PER_CLK),
       
       .MEM_BURST_LEN     (MEM_BURST_LEN),
       .START_ADDR        (PRBS_SADDR),
       .CMP_DATA_PIPE_STAGES (CMP_DATA_PIPE_STAGES),
       .ADDR_WIDTH        (ADDR_WIDTH),
       .SEL_VICTIM_LINE   (SEL_VICTIM_LINE),
       .DATA_PATTERN      (DATA_PATTERN),
       .DWIDTH            (DWIDTH),
       .NUM_DQ_PINS       (NUM_DQ_PINS),
       .MEM_COL_WIDTH     (MEM_COL_WIDTH),
       .SIMULATION        (SIMULATION)

       )
   read_data_path
     (
      .clk_i              (clk_i),
      .rst_i              (rst_rb),
      .manual_clear_error (manual_clear_error),
      .cmd_rdy_o          (rd_rdy),
      .cmd_valid_i        (rd_valid),
      .memc_cmd_full_i    (memc_cmd_full_i),
      .prbs_fseed_i         (data_seed_i),
      .cmd_sent                 (memc_cmd_instr_o),
      .bl_sent                  (memc_bl_o[5:0]),
      .cmd_en_i              (cmd_rd_en),
      .vio_instr_mode_value  (vio_instr_mode_value),

      .data_mode_i        (data_mode_r_b),
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

      .addr_i                 (rd_addr),
      .bl_i                   (rd_bl),
      .data_rdy_o             (memc_rd_en_o),
      
      .data_valid_i           (rdpath_data_valid_i),
      .data_i                 (rdpath_rd_data_i), 
      
      
      .data_error_o           (cmp_error),
      .cmp_data_valid         (cmp_data_valid),
      .cmp_data_o             (cmp_data),
      .rd_mdata_o             (mem_rd_data ),
      .cmp_addr_o             (cmp_addr),
      .cmp_bl_o               (cmp_bl),
      .dq_error_bytelane_cmp     (dq_error_bytelane_cmp),
      
      //****************************************************
      .cumlative_dq_lane_error_r   (cumlative_dq_lane_error),
      .cumlative_dq_r0_bit_error_r  (cumlative_dq_r0_bit_error),
      .cumlative_dq_f0_bit_error_r  (cumlative_dq_f0_bit_error),
      .cumlative_dq_r1_bit_error_r  (cumlative_dq_r1_bit_error),
      .cumlative_dq_f1_bit_error_r  (cumlative_dq_f1_bit_error),
      .dq_r0_bit_error_r               (dq_r0_bit_error_r),
      .dq_f0_bit_error_r               (dq_f0_bit_error_r),
      .dq_r1_bit_error_r               (dq_r1_bit_error_r),
      .dq_f1_bit_error_r               (dq_f1_bit_error_r),
      
      .dq_r0_read_bit_r              (dq_r0_read_bit),   
      .dq_f0_read_bit_r              (dq_f0_read_bit),   
      .dq_r1_read_bit_r              (dq_r1_read_bit),   
      .dq_f1_read_bit_r              (dq_f1_read_bit),   
      .dq_r0_expect_bit_r           (dq_r0_expect_bit),   
      .dq_f0_expect_bit_r           (dq_f0_expect_bit ),  
      .dq_r1_expect_bit_r           (dq_r1_expect_bit),   
      .dq_f1_expect_bit_r           (dq_f1_expect_bit ),
      .error_addr_o                 (error_addr)
      
      
      
      

      );

end
else
begin
  assign cmp_error  = 1'b0;
  assign cmp_data_valid = 1'b0;
  assign cmp_data ='b0;

end

endgenerate



assign wr_path_data_rdy_i = !(memc_wr_full_i ) ;//& (~memc_cmd_full_i);

generate
if (PORT_MODE == "WR_MODE" || PORT_MODE == "BI_MODE") 
begin : WR_PATH

   mig_7series_v4_2_write_data_path
     #(
     
       .TCQ           (TCQ),
       .FAMILY  (FAMILY),
       .nCK_PER_CLK       (nCK_PER_CLK),
       .MEM_TYPE           (MEM_TYPE),
       
       .START_ADDR        (PRBS_SADDR),
       .BL_WIDTH          (BL_WIDTH),
       .MEM_BURST_LEN     (MEM_BURST_LEN),
       .ADDR_WIDTH        (ADDR_WIDTH),
       .DATA_PATTERN      (DATA_PATTERN),
       .DWIDTH            (DWIDTH),
       .NUM_DQ_PINS       (NUM_DQ_PINS),
       .SEL_VICTIM_LINE   (SEL_VICTIM_LINE),
       .MEM_COL_WIDTH     (MEM_COL_WIDTH),
       .EYE_TEST          (EYE_TEST)

       )
   write_data_path
     (
      .clk_i(clk_i),
      .rst_i                (rst_rb),
      .cmd_rdy_o            (wr_rdy),
      .cmd_valid_i          (wr_valid),
      .cmd_validB_i         (wr_validB),
      .cmd_validC_i         (wr_validC),
      .prbs_fseed_i         (data_seed_i),
      .mode_load_i          (mode_load_i),
      .wr_data_mask_gen_i    (wr_data_mask_gen_i),
      .mem_init_done_i      (mem_init_done),
      
  
      .data_mode_i          (data_mode_r_c),
      .last_word_wr_o       (last_word_wr),
      .fixed_data_i         (fixed_data_i),
      .simple_data0       (simple_data0),
      .simple_data1       (simple_data1),
      .simple_data2       (simple_data2),
      .simple_data3       (simple_data3),
      .simple_data4       (simple_data4),
      .simple_data5       (simple_data5),
      .simple_data6       (simple_data6),
      .simple_data7       (simple_data7),
      
      
      .addr_i               (wr_addr),
      .bl_i                 (wr_bl),
      .memc_cmd_full_i      (memc_cmd_full_i),
      .data_rdy_i           (wr_path_data_rdy_i),
      .data_valid_o         (memc_wr_en),
      .data_o               (memc_wr_data),
      .data_mask_o          (memc_wr_mask_o),
      .data_wr_end_o        (memc_wr_data_end)
      );

end
else 
begin
   assign memc_wr_en       = 1'b0;
   assign memc_wr_data     = 'b0;
   assign memc_wr_mask_o   = 'b0;

end

endgenerate

generate
if (MEM_TYPE != "QDR2PLUS" && (FAMILY == "VIRTEX6" || FAMILY == "SPARTAN6" )) 
  begin: nonQDR_WR 
    assign  memc_wr_en_o       = memc_wr_en;
    assign  memc_wr_data_o     = memc_wr_data    ;
    assign  memc_wr_data_end_o = (nCK_PER_CLK == 4) ? memc_wr_data_end: memc_wr_data_end;
  end                                                                                                
// QDR 
else
  begin: QDR_WR 
                          
    always @ (posedge clk_i)
      memc_wr_data_r <= memc_wr_data;
                         
    assign  memc_wr_en_o       = memc_wr_en;
    assign  memc_wr_data_o     = memc_wr_data_r    ;

    assign  memc_wr_data_end_o = memc_wr_data_end;
  end
endgenerate

//QDR
always @ (posedge clk_i)
begin

if (memc_wr_full_i) 
   begin
   memc_wr_en_r       <= 1'b0;
   end
else 
   begin
   memc_wr_en_r       <= memc_wr_en;
   end

end

   mig_7series_v4_2_tg_status
     #(
     
       .TCQ           (TCQ),
       .DWIDTH            (DWIDTH)
       )
   tg_status
     (
      .clk_i              (clk_i),
      .rst_i              (rst_ra[2]),
      .manual_clear_error (manual_clear_error),
      .data_error_i       (cmp_error),
      .cmp_data_i         (cmp_data),
      .rd_data_i          (mem_rd_data ),
      .cmp_addr_i         (cmp_addr),
      .cmp_bl_i           (cmp_bl),
      .mcb_cmd_full_i     (memc_cmd_full_i),
      .mcb_wr_full_i      (memc_wr_full_i),          
      .mcb_rd_empty_i     (memc_rd_empty_i),
      .error_status       (error_status),
      .error              (error)
      );


endmodule // memc_traffic_gen
