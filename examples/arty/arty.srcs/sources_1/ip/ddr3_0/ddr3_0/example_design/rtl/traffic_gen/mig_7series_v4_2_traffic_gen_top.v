//*****************************************************************************
// (c) Copyright 2009-2010 Xilinx, Inc. All rights reserved.
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
// /___/  \  /    Vendor             : Xilinx
// \   \   \/     Application        : MIG                          
//  \   \         Filename           : traffic_gen_top.v
//  /   /         Date Last Modified : $Date: 2011/06/02 08:37:25 $
// /___/   /\     Date Created       : Fri Mar 26 2010
// \   \  /  \    
//  \___\/\___\
//
//Device           : Virtex-7
//Design Name      : DDR/DDR2/DDR3/LPDDR
//Purpose          : This Traffic Gen supports both nCK_PER_CLK x4 mode and nCK_PER_CLK x2 mode for
//                   7series MC UI Interface.  The user bus datawidth has a equation: 2*nCK_PER_CLK*DQ_WIDTH.
//                   
//Reference        :
//Revision History :  11/17/2011 Adding CMD_GAP_DELAY to allow control of next command generation after current
//                          completion of burst command in user interface port. 
//                    1/4/2012  Added vio_percent_write in memc_traffic_gen module to let user specify percentage
//                              of write commands out of mix write/read commands. User can
//                              modify this file and bring the signals to  top level to use it.
//                              The value is between 1(10 percent) through 10 (100 percent).
//                              The signal value is only used if vio_instr_mode_value == 4.
//                     5/21/2012  Removed BL_WIDTH parameter and forced internally to 10.
//                               
//*****************************************************************************

`timescale 1ps/1ps

module mig_7series_v4_2_traffic_gen_top #(
   parameter TCQ           = 100,            // SIMULATION tCQ delay.
   
   parameter SIMULATION             = "FALSE",   
   parameter FAMILY                   = "VIRTEX7",         //  "VIRTEX6", "VIRTEX7"
   parameter MEM_TYPE                 = "DDR3",
   
   parameter TST_MEM_INSTR_MODE       =  "R_W_INSTR_MODE", // Spartan6 Available commands: 
                                                           // "FIXED_INSTR_R_MODE", "FIXED_INSTR_W_MODE"
                                                           // "R_W_INSTR_MODE", "RP_WP_INSTR_MODE 
                                                           // "R_RP_W_WP_INSTR_MODE", "R_RP_W_WP_REF_INSTR_MODE"
                                                    // *******************************
                                                    // Virtex 6 Available commands:
                                                    // "R_W_INSTR_MODE"
                                                    // "FIXED_INSTR_R_MODE" - Only Read commands will be generated.
                                                    // "FIXED_INSTR_W_MODE" -- Only Write commands will be generated.
                                                    // "FIXED_INSTR_R_EYE_MODE"  Only Read commands will be generated 
                                                    //                           with lower 10 bits address in sequential increment.
                                                    //                           This mode is for Read Eye measurement.
                                                    
 //  parameter BL_WIDTH                 = 10,             // Define User Interface Burst length width. 
 //                                                       // For a maximum 128 continuous back_to_back command, set this to 8.
   parameter nCK_PER_CLK              = 4,              // Memory Clock ratio to fabric clock.
   parameter NUM_DQ_PINS              = 8,              // Total number of memory dq pins in the design.
   parameter MEM_BURST_LEN            = 8,              // MEMROY Burst Length    
   parameter MEM_COL_WIDTH            = 10,             // Memory component column width.
   parameter DATA_WIDTH               = NUM_DQ_PINS*2*nCK_PER_CLK,             // User Interface Data Width      
   parameter ADDR_WIDTH               = 29,             // Command Address Bus width
   parameter MASK_SIZE                = DATA_WIDTH/8,   // 
   parameter DATA_MODE                = 4'b0010,        // Default Data mode is set to Address as Data pattern.

   // parameters define the address range
   parameter BEGIN_ADDRESS            = 32'h00000100,
   parameter END_ADDRESS              = 32'h000002ff,
   parameter PRBS_EADDR_MASK_POS      = 32'hfffffc00,
   // debug parameters
   parameter CMDS_GAP_DELAY           = 6'd0,   // CMDS_GAP_DELAY is used in memc_flow_vcontrol module to insert delay between 
                                                // each sucessive burst commands. The maximum delay is 32 clock cycles 
                                                // after the last  command.
   parameter SEL_VICTIM_LINE          = NUM_DQ_PINS,      // VICTIM LINE is one of the DQ pins is selected to be always asserted when
                                                          // DATA MODE is hammer pattern. No VICTIM_LINE will be selected if
                                                          // SEL_VICTIM_LINE = NUM_DQ_PINS.
   parameter CMD_WDT                  = 'h3FF,
   parameter WR_WDT                   = 'h1FFF,
   parameter RD_WDT                   = 'hFF,

   parameter EYE_TEST                 = "FALSE",
   // S6 Only parameters
   parameter PORT_MODE                = "BI_MODE",      
   parameter DATA_PATTERN             = "DGEN_ALL",     // Default is to generate all data pattern circuits.
   parameter CMD_PATTERN              = "CGEN_ALL"     // Default is to generate all commands pattern circuits.
   
  )
  (
   input                           clk, 
   input                           rst, 
   input                           tg_only_rst, 
   input                           manual_clear_error,
   input                           memc_init_done, 

   input                           memc_cmd_full,
   output                          memc_cmd_en,
   output [2:0]                    memc_cmd_instr,
   output [5:0]                    memc_cmd_bl,
   output [31:0]                   memc_cmd_addr,

   output                          memc_wr_en,
   output                          memc_wr_end,
   
   output [DATA_WIDTH/8 - 1:0]     memc_wr_mask,
   output [DATA_WIDTH - 1:0]       memc_wr_data,
   input                           memc_wr_full,

   output                          memc_rd_en,
   input [DATA_WIDTH - 1:0]        memc_rd_data,
   input                           memc_rd_empty,

   // interface to qdr interface
   output                          qdr_wr_cmd_o,
   output                          qdr_rd_cmd_o,


   // Signal declarations that can be connected to vio module 
   input                           vio_pause_traffic,     //  Pause traffic on the fly.
   input                           vio_modify_enable,
   input [3:0]                     vio_data_mode_value,
   input [2:0]                     vio_addr_mode_value,
   input [3:0]                     vio_instr_mode_value,
   input [1:0]                     vio_bl_mode_value,
   input [9:0]          vio_fixed_bl_value,
   input [2:0]                     vio_fixed_instr_value,       // Allows upper level control write only or read only
                                                            // on the fly. 
                                                            // Set the vio_instr_mode_value to "0001" .
                                                            // User has control of the type of commands to be generated  
                                                            // after memory has been filled with selected data pattern.
                                                            // vio_fixed_instr_value = 3'b000:  Write command
                                                            // vio_fixed_instr_value = 3'b001:  Read command
   input                           vio_data_mask_gen,  // data_mask generation is only supported 
                                                       // when data mode = address as data . 
                                                       // 
   input [31:0]                    fixed_addr_i,
   
   // User Specific data pattern interface that used when vio_data_mode vale = 1.4.9.
   input [31:0]                    fixed_data_i,
   input [31:0]                    simple_data0,
   input [31:0]                    simple_data1, 
   input [31:0]                    simple_data2, 
   input [31:0]                    simple_data3, 
   input [31:0]                    simple_data4, 
   input [31:0]                    simple_data5, 
   input [31:0]                    simple_data6, 
   input [31:0]                    simple_data7, 
   input                           wdt_en_i,
   
   // BRAM interface.
                                          //   bram bus formats:
                                          //   Only SP6 has been tested.
   input [38:0]                    bram_cmd_i,   //  {{bl}, {cmd}, {address[28:2]}}
   input                           bram_valid_i,
   output                          bram_rdy_o,  //
   

   // status feedback
   output [DATA_WIDTH-1:0]         cmp_data,
   output                          cmp_data_valid,
   output                          cmp_error,
   output [47:0]                   wr_data_counts,
   output [47:0]                   rd_data_counts,
   output [NUM_DQ_PINS/8 - 1:0]    dq_error_bytelane_cmp,
   output                          error,       // asserted whenever the read back data is not correct.
   output [64 + (2*DATA_WIDTH - 1):0]     error_status,
   output [NUM_DQ_PINS/8 - 1:0] cumlative_dq_lane_error,
   output reg                     cmd_wdt_err_o,
   output reg                     wr_wdt_err_o,
   output reg                     rd_wdt_err_o,

   output            mem_pattern_init_done

  );

  
  

//p0 wire declarations
   wire            tg_run_traffic; 
   wire            tg_data_mask_gen; 
   wire            run_traffic;
   wire [31:0]     tg_start_addr;
   wire [31:0]     tg_end_addr;
   wire [31:0]     tg_cmd_seed; 
   wire [31:0]     tg_data_seed;
   wire            tg_load_seed;
   wire [2:0]      tg_addr_mode;
   wire [3:0]      tg_instr_mode;
   wire [1:0]      tg_bl_mode;
   wire [3:0]      tg_data_mode;
   wire            tg_mode_load;
   wire [9:0]      tg_fixed_bl;
   wire [2:0]      tg_fixed_instr;                        
   wire            tg_addr_order;
   wire [5:0]      cmds_gap_delay_value;
   wire            tg_memc_wr_en;
   wire [63:0]     mem_tg_tstpoints;
   wire [9:0] lcl_v_fixed_bl_value;   

   wire             single_operation;
   wire [3:0]       tg_instr_mode_value;
   wire [3:0]       instr_mode_value;
   reg tg_rst;
   localparam  ADDR_WIDTH_MASK    =  {{31-ADDR_WIDTH{1'b0}}, {ADDR_WIDTH-1{1'b1}}};
   localparam  ADDR_WIDTH_MASK_1  =  {{30-ADDR_WIDTH{1'b0}}, {ADDR_WIDTH{1'b1}}};
   localparam  BEGIN_ADDRESS_MASK = ADDR_WIDTH_MASK & BEGIN_ADDRESS;
   localparam  END_ADDRESS_MASK   = ADDR_WIDTH_MASK_1 & END_ADDRESS;
   
   localparam SHIFT_COUNT = (31-ADDR_WIDTH) ;
   localparam BEGIN_ADDRESS_INT = (BEGIN_ADDRESS_MASK >= END_ADDRESS_MASK) ? (BEGIN_ADDRESS >> SHIFT_COUNT) : BEGIN_ADDRESS_MASK ;
   localparam END_ADDRESS_INT   = (BEGIN_ADDRESS_MASK >= END_ADDRESS_MASK) ? (END_ADDRESS >> SHIFT_COUNT) : END_ADDRESS_MASK ;
   localparam  TG_INIT_DATA_MODE   =  (DATA_PATTERN == "DGEN_ADDR")     ?  4'b0010 :
                                      (DATA_PATTERN == "DGEN_HAMMER")   ?  4'b0011 :
                                      (DATA_PATTERN == "DGEN_WALKING1") ?  4'b0101 :
                                      (DATA_PATTERN == "DGEN_WALKING0") ?  4'b0110 :
                                      (DATA_PATTERN == "DGEN_PRBS")     ?  4'b0111 :
                                       DATA_MODE ;

assign single_operation = 1'b0;   // Disable this for 13.3 release

     
// cmds_gap_delay_value is used in memc_flow_vcontrol module to insert delay between 
// each sucessive burst commands. The maximum delay is 32 clock cycles after the last  command.
  function integer clogb2 (input integer size);
    begin
      size = size - 1;
      for (clogb2=1; size>1; clogb2=clogb2+1)
        size = size >> 1;
    end
  endfunction

  localparam CMD_WDT_WIDTH = clogb2(CMD_WDT);
  localparam RD_WDT_WIDTH  = clogb2(RD_WDT);
  localparam WR_WDT_WIDTH  = clogb2(WR_WDT);

assign cmds_gap_delay_value = CMDS_GAP_DELAY;

localparam TG_FAMILY = ((FAMILY == "VIRTEX6") || (FAMILY == "VIRTEX7") || (FAMILY == "7SERIES") 
                         || (FAMILY == "KINTEX7") || (FAMILY == "ARTIX7") ) ? "VIRTEX6" : "SPARTAN6";

assign tg_memc_wr_en        = (TG_FAMILY == "VIRTEX6") ?memc_cmd_en & ~memc_cmd_full : memc_wr_en ;
assign lcl_v_fixed_bl_value = (vio_data_mode_value == 4) ? 32:vio_fixed_bl_value;
assign tg_run_traffic       = (run_traffic & ((vio_modify_enable == 1'b1) ? ~vio_pause_traffic : 1'b1)) ;
assign tg_data_mask_gen     = (vio_modify_enable == 1'b1) ? vio_data_mask_gen : 1'b0 ;
assign instr_mode_value     = (vio_modify_enable == 1'b1) ? vio_instr_mode_value : 4'b0010;
assign tg_instr_mode_value  = (single_operation == 1'b1) ? 4'b0111: instr_mode_value;

reg [CMD_WDT_WIDTH-1 : 0] cmd_wdt;
reg [RD_WDT_WIDTH-1  : 0] rd_wdt;
reg [WR_WDT_WIDTH-1  : 0] wr_wdt;

// The following 'generate' statement activates the traffic generator for
   // init_mem_pattern_ctr module instantiation for Port-0
   mig_7series_v4_2_init_mem_pattern_ctr #
     (
      .TCQ                           (TCQ),
      .DWIDTH                        (DATA_WIDTH), 
      
      .TST_MEM_INSTR_MODE            (TST_MEM_INSTR_MODE),
      .nCK_PER_CLK                   (nCK_PER_CLK),
      .MEM_BURST_LEN                 (MEM_BURST_LEN),
      .NUM_DQ_PINS                   (NUM_DQ_PINS), 
      .MEM_TYPE                      (MEM_TYPE),
      
      .FAMILY                        (TG_FAMILY),
      .BL_WIDTH                      (10),
      .ADDR_WIDTH                    (ADDR_WIDTH),
      .BEGIN_ADDRESS                 (BEGIN_ADDRESS_INT),
      .END_ADDRESS                   (END_ADDRESS_INT),
      .CMD_SEED_VALUE                (32'h56456783),
      .DATA_SEED_VALUE               (32'h12345678),  
      .DATA_MODE                     (TG_INIT_DATA_MODE), 
      .PORT_MODE                     (PORT_MODE) 
    )
   u_init_mem_pattern_ctr
     (
      .clk_i                         (clk),   
      .rst_i                         (tg_rst),     
      .memc_cmd_en_i                 (memc_cmd_en),   
      .memc_wr_en_i                  (tg_memc_wr_en), 
      .single_write_button           (1'b0),               // tie off these group of signals for 13.3
      .single_read_button            (1'b0),
      .slow_write_read_button        (1'b0),
      .single_operation              (1'b0),
      .vio_modify_enable             (vio_modify_enable),   
      .vio_instr_mode_value          (tg_instr_mode_value),
      .vio_data_mode_value           (vio_data_mode_value),  
      .vio_addr_mode_value           (vio_addr_mode_value),
      .vio_bl_mode_value             (vio_bl_mode_value),  // always set to PRBS_BL mode
      .vio_fixed_bl_value            (lcl_v_fixed_bl_value),  // always set to 64 in order to run PRBS data pattern
      .vio_data_mask_gen             (vio_data_mask_gen),
      .vio_fixed_instr_value         (vio_fixed_instr_value),
      .memc_init_done_i               (memc_init_done),
      .cmp_error                     (error),
      .run_traffic_o                 (run_traffic),  
      .start_addr_o                  (tg_start_addr),
      .end_addr_o                    (tg_end_addr), 
      .cmd_seed_o                    (tg_cmd_seed),  
      .data_seed_o                   (tg_data_seed), 
      .load_seed_o                   (tg_load_seed), 
      .addr_mode_o                   (tg_addr_mode), 
      .instr_mode_o                  (tg_instr_mode), 
      .bl_mode_o                     (tg_bl_mode), 
      .data_mode_o                   (tg_data_mode), 
      .mode_load_o                   (tg_mode_load), 
      .fixed_bl_o                    (tg_fixed_bl), 
      .fixed_instr_o                 (tg_fixed_instr),
      .mem_pattern_init_done_o         (mem_pattern_init_done)
     );
   
   // traffic generator instantiation for Port-0
   mig_7series_v4_2_memc_traffic_gen #
     (
      .TCQ                           (TCQ),
      .MEM_BURST_LEN                 (MEM_BURST_LEN),  
      .MEM_COL_WIDTH                 (MEM_COL_WIDTH),  
      .NUM_DQ_PINS                   (NUM_DQ_PINS), 
      .nCK_PER_CLK                   (nCK_PER_CLK),
      
      .PORT_MODE                     (PORT_MODE),     
      .DWIDTH                        (DATA_WIDTH),
      .FAMILY                        (TG_FAMILY),    
      .MEM_TYPE                      (MEM_TYPE),
      .SIMULATION                    (SIMULATION),   
      .DATA_PATTERN                  (DATA_PATTERN),  
      .CMD_PATTERN                   (CMD_PATTERN ),  
      .ADDR_WIDTH                    (ADDR_WIDTH),  
      .BL_WIDTH                      (10),
      .SEL_VICTIM_LINE               (SEL_VICTIM_LINE),
      .PRBS_SADDR_MASK_POS           (BEGIN_ADDRESS_INT), 
      .PRBS_EADDR_MASK_POS           (PRBS_EADDR_MASK_POS),
      .PRBS_SADDR                    (BEGIN_ADDRESS_INT), 
      .PRBS_EADDR                    (END_ADDRESS_INT),
      .EYE_TEST                      (EYE_TEST)
     )  
   u_memc_traffic_gen 
     (  
      .clk_i                         (clk),     
      .rst_i                         (tg_rst),     
      .run_traffic_i                 (tg_run_traffic),                  
      .manual_clear_error            (manual_clear_error),   
      .cmds_gap_delay_value         (cmds_gap_delay_value),
      .vio_instr_mode_value          (tg_instr_mode_value),
      .vio_percent_write             ('b0),                                      // bring this to top if want to specify percentage of write commands
                                                             // instr_mode_i has to be == 4 if want to use this command pattern
      // runtime parameter  
      .mem_pattern_init_done_i       (mem_pattern_init_done),
      .single_operation              (1'b0),
      
      .start_addr_i                  (tg_start_addr),                  
      .end_addr_i                    (tg_end_addr),                  
      .cmd_seed_i                    (tg_cmd_seed),                  
      .data_seed_i                   (tg_data_seed),                  
      .load_seed_i                   (tg_load_seed),                
      .addr_mode_i                   (tg_addr_mode),                
      .instr_mode_i                  (tg_instr_mode),                  
      .bl_mode_i                     (tg_bl_mode),                  
      .data_mode_i                   (tg_data_mode),                  
      .mode_load_i                   (tg_mode_load), 
      .wr_data_mask_gen_i             (tg_data_mask_gen),
      // fixed pattern inputs interface  
      .fixed_bl_i                    (tg_fixed_bl),                     
      .fixed_instr_i                 (tg_fixed_instr),                     
      .fixed_addr_i                  (fixed_addr_i),                 
      .fixed_data_i                  (fixed_data_i), 
      // BRAM interface. 
      .bram_cmd_i                    (bram_cmd_i),
   //   .bram_addr_i                   (bram_addr_i ),
   //   .bram_instr_i                  ( bram_instr_i),
      .bram_valid_i                  (bram_valid_i),
      .bram_rdy_o                    (bram_rdy_o),  
      
      //  MCB INTERFACE  
      .memc_cmd_en_o                  (memc_cmd_en),                 
      .memc_cmd_instr_o               (memc_cmd_instr),                    
      .memc_cmd_bl_o                  (memc_cmd_bl),                 
      .memc_cmd_addr_o                (memc_cmd_addr),                   
      .memc_cmd_full_i                (memc_cmd_full),                   
   
      .memc_wr_en_o                   (memc_wr_en),     
      .memc_wr_data_end_o             (memc_wr_end), 
      .memc_wr_mask_o                 (memc_wr_mask),                  
      .memc_wr_data_o                 (memc_wr_data),                 
      .memc_wr_full_i                 (memc_wr_full),                  
   
      .memc_rd_en_o                   (memc_rd_en),                
      .memc_rd_data_i                 (memc_rd_data),                  
      .memc_rd_empty_i                (memc_rd_empty),                   
      
      .qdr_wr_cmd_o                  (qdr_wr_cmd_o),
      .qdr_rd_cmd_o                  (qdr_rd_cmd_o),
      // status feedback  
      .counts_rst                    (tg_rst),     
      .wr_data_counts                (wr_data_counts), 
      .rd_data_counts                (rd_data_counts), 
      .error                         (error),  // asserted whenever the read back data is not correct.  
      .error_status                  (error_status),  // TBD how signals mapped  
      .cmp_data                      (cmp_data),            
      .cmp_data_valid                (cmp_data_valid),                  
      .cmp_error                     (cmp_error),             
      .mem_rd_data                   (), 
      .simple_data0                  (simple_data0),
      .simple_data1                  (simple_data1),
      .simple_data2                  (simple_data2),
      .simple_data3                  (simple_data3),
      .simple_data4                  (simple_data4),
      .simple_data5                  (simple_data5),
      .simple_data6                  (simple_data6),
      .simple_data7                  (simple_data7),
      .dq_error_bytelane_cmp         (dq_error_bytelane_cmp), 
      .cumlative_dq_lane_error       (cumlative_dq_lane_error),
      .cumlative_dq_r0_bit_error     (),
      .cumlative_dq_f0_bit_error     (),
      .cumlative_dq_r1_bit_error     (),
      .cumlative_dq_f1_bit_error     (),
      .dq_r0_bit_error_r             (),
      .dq_f0_bit_error_r             (),
      .dq_r1_bit_error_r             (),
      .dq_f1_bit_error_r             (),
      .dq_r0_read_bit                (),
      .dq_f0_read_bit                (),
      .dq_r1_read_bit                (),
      .dq_f1_read_bit                (),
      .dq_r0_expect_bit              (),
      .dq_f0_expect_bit              (),
      .dq_r1_expect_bit              (),
      .dq_f1_expect_bit              (),
      .error_addr                    ()
     );

  reg [8:0] wr_cmd_cnt;
  reg [8:0] dat_cmd_cnt;
  reg rst_remem;
  reg [2:0] app_cmd1;
  reg [2:0] app_cmd2;
  reg [2:0] app_cmd3;
  reg [2:0] app_cmd4;

       reg [8:0] rst_cntr;

         always @(posedge clk) begin
           if (rst) begin
             rst_remem <= 1'b0;
           end else if (tg_only_rst) begin
             rst_remem <= 1'b1;
           end else if (rst_cntr == 9'h0) begin
             rst_remem <= 1'b0;
           end
         end

       
         always @(posedge clk) begin
           if (rst) begin
             tg_rst <= 1'b1;
           end else begin
             tg_rst <= (rst_cntr != 9'h1ff);
           end
         end
       
         always @ (posedge clk)
         begin
           if (rst)
             rst_cntr <= 9'h1ff;
           else if (rst_remem & (wr_cmd_cnt==dat_cmd_cnt) & (app_cmd3==3'h1) & (app_cmd4==3'h0))
             rst_cntr <= 9'h0;
           else if (rst_cntr != 9'h1ff)
             rst_cntr <= rst_cntr + 1'b1;
         end

         always @(posedge clk) begin
           if (rst | tg_rst) begin
             wr_cmd_cnt <= 1'b0;
           end else if (memc_cmd_en & (!memc_cmd_full)& (memc_cmd_instr == 3'h0)) begin
             wr_cmd_cnt <= wr_cmd_cnt + 1'b1;
           end
         end

         always @(posedge clk) begin
           if (rst| tg_rst) begin
             dat_cmd_cnt <= 1'b0;
           end else if (memc_wr_en & (!memc_wr_full)) begin
             dat_cmd_cnt <= dat_cmd_cnt + 1'b1;
           end
         end

         always @(posedge clk) begin
           if (rst| tg_rst) begin
             app_cmd1 <= 'b0;
             app_cmd2 <= 'b0;
             app_cmd3 <= 'b0;
             app_cmd4 <= 'b0;
           end else if (memc_cmd_en & (!memc_cmd_full)) begin
             app_cmd1 <= memc_cmd_instr;
             app_cmd2 <= app_cmd1;
             app_cmd3 <= app_cmd2;
             app_cmd4 <= app_cmd3;
            end
         end
         always @(posedge clk) begin
           if (rst| tg_rst) begin
             cmd_wdt <= 1'b0;
           end else if (memc_init_done & (cmd_wdt!=CMD_WDT) & (memc_cmd_full | (!memc_cmd_en)) & wdt_en_i) begin
                     //  init_calib_done                      !app_rdy           app_en 
             cmd_wdt <=  cmd_wdt + 1'b1;
//           end else if (memc_init_done & (cmd_wdt!=CMD_WDT) & (!memc_cmd_full) & memc_cmd_en & wdt_en_w) begin
           end else if ((!memc_cmd_full) & memc_cmd_en) begin
                     //  init_calib_done                        !app_rdy           app_en 
             cmd_wdt <=  'b0;
           end
         end


         always @(posedge clk) begin
           if (rst| tg_rst) begin
             rd_wdt <= 1'b0;
           end else if (mem_pattern_init_done & (rd_wdt != RD_WDT) & (memc_rd_empty) & wdt_en_i) begin
                     //                                               !app_rd_data_valid
             rd_wdt <= rd_wdt + 1'b1;
           end else if (!memc_rd_empty) begin
                     //  !app_rd_data_valid
             rd_wdt <= 'b0;
           end
         end

         always @(posedge clk) begin
           if (rst| tg_rst) begin
             wr_wdt <= 1'b0;
           end else if (mem_pattern_init_done & (wr_wdt != WR_WDT) & (!memc_wr_en) & wdt_en_i) begin
                     //                                                app_wdf_wren
             wr_wdt <= wr_wdt + 1'b1;
           end else if (memc_wr_en) begin
                     // app_wdf_wren
             wr_wdt <= 'b0;
           end
         end

         always @(posedge clk) begin
           if (rst| tg_rst) begin
             cmd_wdt_err_o <= 'b0; 
             rd_wdt_err_o  <= 'b0; 
             wr_wdt_err_o  <= 'b0; 
           end else begin
             cmd_wdt_err_o <= cmd_wdt == CMD_WDT; 
             rd_wdt_err_o  <= rd_wdt  == RD_WDT;
             wr_wdt_err_o  <= wr_wdt  == WR_WDT;  
           end
         end


//synthesis translate_off
initial
begin
@ (posedge cmd_wdt_err_o);
$display ("ERROR: COMMAND Watch Dog Timer Expired");
repeat (20) @ (posedge clk);
$finish;
end

initial
begin
@ (posedge rd_wdt_err_o);
$display ("ERROR: READ Watch Dog Timer Expired");
repeat (20) @ (posedge clk);
$finish;
end
           
initial
begin
@ (posedge wr_wdt_err_o)
$display ("ERROR: WRITE Watch Dog Timer Expired");
repeat (20) @ (posedge clk);
$finish;
end

initial
begin
@ (posedge error)
repeat (20) @ (posedge clk);
$finish;
end
//synthesis translate_on


endmodule
