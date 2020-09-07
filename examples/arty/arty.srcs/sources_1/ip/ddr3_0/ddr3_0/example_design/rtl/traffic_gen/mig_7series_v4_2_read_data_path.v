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
//
//*****************************************************************************
//   ____  ____
//  /   /\/   /
// /___/  \  /    Vendor: Xilinx
// \   \   \/     Version: %version
//  \   \         Application: MIG
//  /   /         Filename: read_data_path.v
// /___/   /\     Date Last Modified: 
// \   \  /  \    Date Created: 
//  \___\/\___\
//
//Device: Spartan6
//Design Name: DDR/DDR2/DDR3/LPDDR 
//Purpose: This is top level of read path and also consist of comparison logic
//         for read data. 
//Reference:
//Revision History:  11/18 /2011  Fixed a localparam ER_WIDTH bug for QDR2+ case.	
//                   03/15/2012   Registered error_byte, error_bit   to avoid false
//                                comparison when data_valid_i is deasserted.
//*****************************************************************************

`timescale 1ps/1ps

module mig_7series_v4_2_read_data_path #(
   parameter TCQ           = 100,
   parameter START_ADDR = 32'h00000000,
   parameter nCK_PER_CLK   = 4,            // DRAM clock : MC clock
   
   parameter MEM_TYPE      = "DDR3",       
   parameter FAMILY = "VIRTEX6",
   parameter BL_WIDTH = 6,   
   parameter MEM_BURST_LEN = 8,
   parameter ADDR_WIDTH = 32,
   parameter CMP_DATA_PIPE_STAGES = 3,
   parameter DATA_PATTERN = "DGEN_ALL", //"DGEN__HAMMER", "DGEN_WALING1","DGEN_WALING0","DGEN_ADDR","DGEN_NEIGHBOR","DGEN_PRBS","DGEN_ALL"  
   parameter NUM_DQ_PINS   = 8,
   parameter DWIDTH = nCK_PER_CLK * 2 * NUM_DQ_PINS,
   
   parameter SEL_VICTIM_LINE = 3,  // VICTIM LINE is one of the DQ pins is selected to be different than hammer pattern
   
   parameter MEM_COL_WIDTH = 10,
   parameter SIMULATION = "FALSE"
   
    )
    (
      
   
   input                  clk_i, 
   input [9:0]                 rst_i,
   input                  manual_clear_error,
   output                 cmd_rdy_o, 
   input                  cmd_valid_i, 
   input                  memc_cmd_full_i,
   input [31:0]           prbs_fseed_i,
   input                    mode_load_i,
   input [3:0]              vio_instr_mode_value,
   
   input [3:0]            data_mode_i,
   input [2:0]           cmd_sent, 
   input [5:0]           bl_sent  ,
   input                 cmd_en_i ,
//   input [31:0]           m_addr_i, 
   
   input [31:0] simple_data0 ,
   input [31:0] simple_data1 ,
   input [31:0] simple_data2 ,
   input [31:0] simple_data3 ,
   input [31:0] simple_data4 ,
   input [31:0] simple_data5 ,
   input [31:0] simple_data6 ,
   input [31:0] simple_data7 ,
   
   input [31:0]     fixed_data_i,    
   input [31:0]           addr_i, 
   input [BL_WIDTH-1:0]            bl_i,
   
   
   output                 data_rdy_o, 
   input                  data_valid_i,
   input [NUM_DQ_PINS*nCK_PER_CLK*2-1:0]     data_i,
   output                 data_error_o,                  //data_error on user data bus side
   output [DWIDTH-1:0]    cmp_data_o,
   output [DWIDTH-1:0]    rd_mdata_o ,
   output                 cmp_data_valid,
   output [31:0]          cmp_addr_o,
   output [5 :0]          cmp_bl_o,
   output [NUM_DQ_PINS/8 - 1:0] dq_error_bytelane_cmp,   // V6: real time compare error byte lane
   output [NUM_DQ_PINS/8 - 1:0] cumlative_dq_lane_error_r,  // V6: latched error byte lane that occure on
                                                       //     first error
   output reg [NUM_DQ_PINS - 1:0] cumlative_dq_r0_bit_error_r ,                                                   
   output reg [NUM_DQ_PINS - 1:0] cumlative_dq_f0_bit_error_r ,                                                   
   output reg [NUM_DQ_PINS - 1:0] cumlative_dq_r1_bit_error_r ,                                                   
   output reg [NUM_DQ_PINS - 1:0] cumlative_dq_f1_bit_error_r ,  
   
   output reg [NUM_DQ_PINS-1:0] dq_r0_bit_error_r, 
   output reg [NUM_DQ_PINS-1:0] dq_f0_bit_error_r, 
   output reg [NUM_DQ_PINS-1:0] dq_r1_bit_error_r, 
   output reg [NUM_DQ_PINS-1:0] dq_f1_bit_error_r, 

   
   output reg [NUM_DQ_PINS - 1:0] dq_r0_read_bit_r,   
   output reg [NUM_DQ_PINS - 1:0] dq_f0_read_bit_r,   
   output reg [NUM_DQ_PINS - 1:0] dq_r1_read_bit_r,   
   output reg [NUM_DQ_PINS - 1:0] dq_f1_read_bit_r,   
   output reg [NUM_DQ_PINS - 1:0] dq_r0_expect_bit_r,   
   output reg [NUM_DQ_PINS - 1:0] dq_f0_expect_bit_r,   
   output reg [NUM_DQ_PINS - 1:0] dq_r1_expect_bit_r,   
   output reg [NUM_DQ_PINS - 1:0] dq_f1_expect_bit_r,
   output  [31:0] error_addr_o
                                                       
    
   );

   wire                   gen_rdy; 
   wire                   gen_valid; 
   wire [31:0]  gen_addr; 
   wire [BL_WIDTH-1:0]    gen_bl;

   wire                   cmp_rdy; 
   wire                   cmp_valid; 
   wire [31:0]  cmp_addr; 
   wire [5:0]    cmp_bl;

   reg                    data_error;
   wire [NUM_DQ_PINS*nCK_PER_CLK*2-1:0]      cmp_data;
   wire [31:0]                               tg_st_addr_o;
   reg  [NUM_DQ_PINS*nCK_PER_CLK*2-1:0]      cmp_data_r1,cmp_data_r2;
   reg                    last_word_rd;
   reg [5:0]              bl_counter;
   wire                   cmd_rdy;
   wire                   user_bl_cnt_is_1;
   wire                   data_rdy;
   reg [DWIDTH:0] delayed_data;
   wire                  rd_mdata_en;
   reg [NUM_DQ_PINS*nCK_PER_CLK*2-1:0]      rd_data_r1;
   reg [NUM_DQ_PINS*nCK_PER_CLK*2-1:0]      rd_data_r2;
   reg                   force_wrcmd_gen;
   reg                   wait_bl_end;
   reg                   wait_bl_end_r1;
reg l_data_error ;
reg u_data_error;
reg v6_data_cmp_valid;
wire [DWIDTH -1 :0] rd_v6_mdata;
reg [DWIDTH -1 :0] cmpdata_r;
wire [DWIDTH -1 :0] rd_mdata;
 reg cmp_data_en;

localparam ER_WIDTH = ( MEM_TYPE == "QDR2PLUS" && nCK_PER_CLK == 2) ? (NUM_DQ_PINS*MEM_BURST_LEN)/9 : 
                      ( MEM_TYPE != "QDR2PLUS" && nCK_PER_CLK == 2) ? NUM_DQ_PINS/2  :  NUM_DQ_PINS;

reg [ER_WIDTH - 1:0] error_byte;   
reg [ER_WIDTH - 1:0] error_byte_r1;   

reg [NUM_DQ_PINS*nCK_PER_CLK*2 - 1:0] error_bit;
reg [NUM_DQ_PINS*nCK_PER_CLK*2 -1:0]   error_bit_r1;

wire [NUM_DQ_PINS-1:0]   dq_bit_error;
wire [NUM_DQ_PINS-1:0]   cumlative_dq_bit_error_c;

wire [ NUM_DQ_PINS/8-1:0] dq_lane_error;
reg [ NUM_DQ_PINS/8-1:0] dq_lane_error_r1;
reg [ NUM_DQ_PINS/8-1:0] dq_lane_error_r2;
reg [NUM_DQ_PINS-1:0] dq_bit_error_r1;
wire [NUM_DQ_PINS-1:0] cumlative_dq_r0_bit_error_c;
wire [NUM_DQ_PINS-1:0] cumlative_dq_f0_bit_error_c;
wire [NUM_DQ_PINS-1:0] cumlative_dq_r1_bit_error_c;
wire [NUM_DQ_PINS-1:0] cumlative_dq_f1_bit_error_c;


wire [ NUM_DQ_PINS/8-1:0] cum_dq_lane_error_mask;
wire [ NUM_DQ_PINS/8-1:0] cumlative_dq_lane_error_c;
reg [ NUM_DQ_PINS/8-1:0] cumlative_dq_lane_error_reg;


 reg [NUM_DQ_PINS - 1:0] dq_r0_read_bit_rdlay1;   
 reg [NUM_DQ_PINS - 1:0] dq_f0_read_bit_rdlay1;   
 reg [NUM_DQ_PINS - 1:0] dq_r1_read_bit_rdlay1;   
 reg [NUM_DQ_PINS - 1:0] dq_f1_read_bit_rdlay1;   
 reg [NUM_DQ_PINS - 1:0] dq_r0_expect_bit_rdlay1;  
 reg [NUM_DQ_PINS - 1:0] dq_f0_expect_bit_rdlay1;  
 reg [NUM_DQ_PINS - 1:0] dq_r1_expect_bit_rdlay1;  
 reg [NUM_DQ_PINS - 1:0] dq_f1_expect_bit_rdlay1;
 wire [NUM_DQ_PINS-1:0] dq_r0_bit_error ;
 wire [NUM_DQ_PINS-1:0] dq_f0_bit_error ;
 wire [NUM_DQ_PINS-1:0] dq_r1_bit_error ;
 wire [NUM_DQ_PINS-1:0] dq_f1_bit_error ;
 reg  [31:0] error_addr_r1;
 reg  [31:0] error_addr_r2;
 reg  [31:0] error_addr_r3;
 reg data_valid_r1;
 reg data_valid_r2;
 wire cmd_start_i;


  
      always @ (posedge clk_i) begin
             wait_bl_end_r1 <= #TCQ wait_bl_end;
             rd_data_r1 <= #TCQ data_i;
             rd_data_r2 <= #TCQ rd_data_r1;
      end
  
  reg [7:0]         force_wrcmd_timeout_cnts ;

   always @ (posedge clk_i) begin
    if (rst_i[0])
         force_wrcmd_gen <= #TCQ 1'b0;
    else if ((wait_bl_end == 1'b0 &&  wait_bl_end_r1 == 1'b1) || force_wrcmd_timeout_cnts == 8'b11111111)
         force_wrcmd_gen <= #TCQ 1'b0;
   
    else if ((cmd_valid_i && bl_i > 16) || wait_bl_end )
         force_wrcmd_gen <= #TCQ 1'b1;
    end

  
   always @ (posedge clk_i) begin
    if (rst_i[0])
        force_wrcmd_timeout_cnts <= #TCQ 'b0;
    else if (wait_bl_end == 1'b0 &&  wait_bl_end_r1 == 1'b1)
        force_wrcmd_timeout_cnts <= #TCQ 'b0;
        
    else if (force_wrcmd_gen)
        force_wrcmd_timeout_cnts <= #TCQ force_wrcmd_timeout_cnts + 1'b1;
   end
   
   always @ (posedge clk_i)
    if (rst_i[0])
         wait_bl_end <= #TCQ 1'b0;
    else if (force_wrcmd_timeout_cnts == 8'b11111111)
         wait_bl_end <= #TCQ 1'b0;
    
    else if (gen_rdy && gen_valid && gen_bl > 16)
         wait_bl_end <= #TCQ 1'b1;
    else if (wait_bl_end && user_bl_cnt_is_1)
         wait_bl_end <= #TCQ 1'b0;
   
   
   assign cmd_rdy_o = cmd_rdy;
   mig_7series_v4_2_read_posted_fifo #
     (
           .TCQ               (TCQ),
           .FAMILY        (FAMILY),               
           .nCK_PER_CLK   (nCK_PER_CLK),
           .MEM_BURST_LEN (MEM_BURST_LEN),
           .ADDR_WIDTH    (32),
           .BL_WIDTH      (BL_WIDTH)
           )
   read_postedfifo(
                    .clk_i              (clk_i),
                    .rst_i                (rst_i[0]),
                    .cmd_rdy_o          (cmd_rdy      ),
                    .cmd_valid_i        (cmd_valid_i    ),
                    .data_valid_i         (data_rdy        ),  // input to
                    .addr_i             (addr_i         ),
                    .bl_i               (bl_i           ),
                    .cmd_start_i        (cmd_start),
                    .cmd_sent           (cmd_sent),
                    .bl_sent            (bl_sent ),
                    .cmd_en_i           (cmd_en_i),
                    .memc_cmd_full_i    (memc_cmd_full_i), 
                    .gen_valid_o        (gen_valid      ),
                    .gen_addr_o         (gen_addr       ),
                    .gen_bl_o           (gen_bl         ),
                    .rd_mdata_en            (rd_mdata_en)
                    );


 
   
   mig_7series_v4_2_rd_data_gen #
     (
              .TCQ               (TCQ),
              .FAMILY  (FAMILY),
              .MEM_TYPE       (MEM_TYPE),
              
              .BL_WIDTH          (BL_WIDTH),
              .nCK_PER_CLK       (nCK_PER_CLK),
              
              .MEM_BURST_LEN    (MEM_BURST_LEN),
              .NUM_DQ_PINS (NUM_DQ_PINS), 
              .SEL_VICTIM_LINE   (SEL_VICTIM_LINE),
              .START_ADDR        (START_ADDR),
   
              .DATA_PATTERN  (DATA_PATTERN),
              .DWIDTH(DWIDTH),
              .COLUMN_WIDTH     (MEM_COL_WIDTH)
              
              )
   rd_datagen(
            .clk_i              (clk_i          ),
            .rst_i              (rst_i[4:0]),            
            .prbs_fseed_i       (prbs_fseed_i),
            .data_mode_i        (data_mode_i    ),            
            .vio_instr_mode_value  (vio_instr_mode_value),
            
            .cmd_rdy_o          (gen_rdy        ),
            .cmd_valid_i        (gen_valid      ),  
            .mode_load_i        (mode_load_i),
            .cmd_start_o        (cmd_start),
       //     .m_addr_i           (m_addr_i       ),
            .simple_data0       (simple_data0),
            .simple_data1       (simple_data1),
            .simple_data2       (simple_data2),
            .simple_data3       (simple_data3),
            .simple_data4       (simple_data4),
            .simple_data5       (simple_data5),
            .simple_data6       (simple_data6),
            .simple_data7       (simple_data7),
            
            
            .fixed_data_i         (fixed_data_i),
            
            .addr_i             (gen_addr       ),
            .bl_i               (gen_bl         ),
            .user_bl_cnt_is_1_o   (user_bl_cnt_is_1),
            .data_rdy_i         (data_valid_i        ),  // input to
            .data_valid_o       (cmp_valid      ),
            .tg_st_addr_o       (tg_st_addr_o),
            .data_o             (cmp_data       )
            );

   mig_7series_v4_2_afifo #
   (
    .TCQ           (TCQ),
    .DSIZE         (DWIDTH),
    .FIFO_DEPTH    (32),
    .ASIZE         (4),
    .SYNC          (1)  // set the SYNC to 1 because rd_clk = wr_clk to reduce latency 
   
   
   )
   rd_mdata_fifo
   (
    .wr_clk        (clk_i),
    .rst           (rst_i[0]),
    .wr_en         (data_valid_i),
    .wr_data       (data_i),
    .rd_en         (rd_mdata_en),
    .rd_clk        (clk_i),
    .rd_data       (rd_v6_mdata),
    .full          (),
    .empty         (),
    .almost_full   ()
   );

always @ (posedge clk_i)
begin
//    delayed_data <= #TCQ {cmp_valid & data_valid_i,cmp_data};
    cmp_data_r1 <= #TCQ cmp_data;
    cmp_data_r2 <= #TCQ cmp_data_r1;
end
assign rd_mdata_o = rd_mdata;

assign rd_mdata = (FAMILY == "SPARTAN6") ? rd_data_r1: 
                  (FAMILY == "VIRTEX6" && MEM_BURST_LEN == 4)? rd_v6_mdata:
                  rd_data_r2;

assign cmp_data_valid = (FAMILY == "SPARTAN6") ? cmp_data_en :
                        (FAMILY == "VIRTEX6" && MEM_BURST_LEN == 4)? v6_data_cmp_valid :data_valid_i;



   
assign        cmp_data_o  = cmp_data_r2;
assign        cmp_addr_o  = tg_st_addr_o;//gen_addr;
assign        cmp_bl_o    = gen_bl[5:0];


   
assign data_rdy_o = data_rdy;
assign data_rdy = cmp_valid & data_valid_i;

 always @ (posedge clk_i)
    v6_data_cmp_valid <= #TCQ rd_mdata_en;


 always @ (posedge clk_i)
       cmp_data_en <= #TCQ data_rdy;


genvar i;

 generate
 if (FAMILY == "SPARTAN6") 
 begin: gen_error_sp6
   always @ (posedge clk_i)
     begin
       if (cmp_data_en)
           l_data_error <= #TCQ (rd_data_r1[DWIDTH/2-1:0] != cmp_data_r1[DWIDTH/2-1:0]);           
        else
           l_data_error <= #TCQ 1'b0;

       if (cmp_data_en)
           u_data_error <= #TCQ (rd_data_r1[DWIDTH-1:DWIDTH/2] != cmp_data_r1[DWIDTH-1:DWIDTH/2]);           
        else
           u_data_error <= #TCQ 1'b0;

       data_error <= #TCQ l_data_error | u_data_error;
      //synthesis translate_off
      if (data_error)
        $display ("ERROR at time %t" , $time);
      //synthesis translate_on
        
     end

end
else
// if (FAMILY == "VIRTEX6" ) 
 begin: gen_error_v7
  if (nCK_PER_CLK == 2) 
  begin
    if (MEM_TYPE == "QDR2PLUS")
    begin: qdr_design
      for (i = 0; i < (NUM_DQ_PINS*MEM_BURST_LEN)/9; i = i + 1)
      begin: gen_cmp_2
             always @ (posedge clk_i)
                //synthesis translate_off
                if (data_valid_i & (SIMULATION=="TRUE"))
                       error_byte[i]  <= (data_i[9*(i+1)-1:9*i] !== cmp_data[9*(i+1)-1:9*i]) ;  
                else 
	       //synthesis translate_on
		   if (data_valid_i)
                      error_byte[i]  <= (data_i[9*(i+1)-1:9*i] != cmp_data[9*(i+1)-1:9*i]) ;  
                   else
                      error_byte[i]  <= 1'b0;
      end
      for (i = 0; i < NUM_DQ_PINS*MEM_BURST_LEN; i = i + 1) 
      begin: gen_cmp_bit_2
             always @ (posedge clk_i)
                //synthesis translate_off
                if (data_valid_i & (SIMULATION=="TRUE"))               
                    error_bit[i] <= (data_i[i] !== cmp_data[i]) ;  
                else 
	       //synthesis translate_on
		   if (data_valid_i)               
                       error_bit[i] <= (data_i[i] != cmp_data[i]) ;  
                   else
                       error_bit[i] <= 1'b0;
      end
    end
    else
    begin: ddr_design
      for (i = 0; i < NUM_DQ_PINS/2; i = i + 1)
      begin: gen_cmp_2
             always @ (posedge clk_i)
                //synthesis translate_off
                if (data_valid_i & (SIMULATION=="TRUE"))
                    error_byte[i]  <= (data_i[8*(i+1)-1:8*i] !== cmp_data[8*(i+1)-1:8*i]) ;  
                else 
	       //synthesis translate_on
		   if (data_valid_i)
                       error_byte[i]  <= (data_i[8*(i+1)-1:8*i] != cmp_data[8*(i+1)-1:8*i]) ;  
                   else
                       error_byte[i]  <= 1'b0;
      end
      for (i = 0; i < NUM_DQ_PINS*4; i = i + 1) 
      begin: gen_cmp_bit_2
             always @ (posedge clk_i)
                //synthesis translate_off
                if (data_valid_i & (SIMULATION=="TRUE"))               
                    error_bit[i] <= ( (data_i[i] !== cmp_data[i]) ) ;  
                else 
	       //synthesis translate_on
		   if (data_valid_i)               
                       error_bit[i] <= ( (data_i[i] != cmp_data[i]) ) ;  
                   else 
                       error_bit[i] <= 1'b0;
          end
        end
  end
  else  //nCK_PER_CLK == 4
  begin
    for (i = 0; i < NUM_DQ_PINS; i = i + 1) 
    begin: gen_cmp_4
             always @ (posedge clk_i)
                //synthesis translate_off
                if (data_valid_i & (SIMULATION=="TRUE"))
                   error_byte[i]  <= (data_i[8*(i+1)-1:8*i] !== cmp_data[8*(i+1)-1:8*i]) ;  
                else 
	       //synthesis translate_on
                   if (data_valid_i)
                      error_byte[i]  <= (data_i[8*(i+1)-1:8*i] != cmp_data[8*(i+1)-1:8*i]) ;  
                   else
                       error_byte[i]  <= 1'b0;
    end
    
    for (i = 0; i < NUM_DQ_PINS*8; i = i + 1) 
    begin: gen_cmp_bit_4
             always @ (posedge clk_i)
                //synthesis translate_off
                if (data_valid_i & (SIMULATION=="TRUE"))               
                   error_bit[i] <= (data_i[i] !== cmp_data[i]) ; 
                else 
	       //synthesis translate_on
	           if (data_valid_i)               
                      error_bit[i] <= (data_i[i] != cmp_data[i]) ; 
                   else
                       error_bit[i] <= 1'b0;
    end
  end
    
always @ (posedge clk_i)
begin
    dq_r0_read_bit_rdlay1 <= #TCQ   data_i[NUM_DQ_PINS*1 - 1:0];
    dq_f0_read_bit_rdlay1 <= #TCQ   data_i[NUM_DQ_PINS*2 - 1:NUM_DQ_PINS*1];
    dq_r1_read_bit_rdlay1 <= #TCQ   data_i[NUM_DQ_PINS*3 - 1:NUM_DQ_PINS*2];
    dq_f1_read_bit_rdlay1 <= #TCQ   data_i[NUM_DQ_PINS*4 - 1:NUM_DQ_PINS*3];
    
    dq_r0_expect_bit_rdlay1 <= #TCQ cmp_data[NUM_DQ_PINS*1 - 1:0];
    dq_f0_expect_bit_rdlay1 <= #TCQ cmp_data[NUM_DQ_PINS*2 - 1:NUM_DQ_PINS*1];
    dq_r1_expect_bit_rdlay1 <= #TCQ cmp_data[NUM_DQ_PINS*3 - 1:NUM_DQ_PINS*2];
    dq_f1_expect_bit_rdlay1 <= #TCQ cmp_data[NUM_DQ_PINS*4 - 1:NUM_DQ_PINS*3];
    
    dq_r0_read_bit_r   <= #TCQ   dq_r0_read_bit_rdlay1  ;
    dq_f0_read_bit_r   <= #TCQ   dq_f0_read_bit_rdlay1  ;
    dq_r1_read_bit_r   <= #TCQ   dq_r1_read_bit_rdlay1  ;
    dq_f1_read_bit_r   <= #TCQ   dq_f1_read_bit_rdlay1  ;
    
    dq_r0_expect_bit_r <= #TCQ   dq_r0_expect_bit_rdlay1;
    dq_f0_expect_bit_r <= #TCQ   dq_f0_expect_bit_rdlay1;
    dq_r1_expect_bit_r <= #TCQ   dq_r1_expect_bit_rdlay1;
    dq_f1_expect_bit_r <= #TCQ   dq_f1_expect_bit_rdlay1;
    
    
    
    
    
end   
always @ (posedge clk_i)
begin
    if (rst_i[1] || manual_clear_error) begin
    
      error_byte_r1 <= #TCQ 'b0;
      error_bit_r1 <= #TCQ  'b0;
      
      end
	else if (data_valid_r1) begin

    error_byte_r1 <= #TCQ error_byte;
    error_bit_r1 <= #TCQ  error_bit;
         end 
      else
         begin
         error_byte_r1 <= #TCQ 'b0;
         error_bit_r1 <= #TCQ  'b0;
         end
end
always @ (posedge clk_i)
begin
    if (rst_i[1] || manual_clear_error)
      data_error <= #TCQ 1'b0;
	else if (data_valid_r2)
    data_error <= #TCQ | error_byte_r1;
      else
        data_error <= #TCQ 1'b0;
    
      //synthesis translate_off
    if (data_error)
        $display ("ERROR: Expected data=%h, Received data=%h @ %t" ,cmp_data_r2, rd_data_r2, $time);
      //synthesis translate_on
      
    end

localparam NUM_OF_DQS = (MEM_TYPE == "QDR2PLUS") ? 9 : 8 ;

  if (MEM_TYPE == "QDR2PLUS") begin: qdr_design_error_calc

    if (MEM_BURST_LEN == 4) begin: bl4_design
      for ( i = 0; i < NUM_DQ_PINS/NUM_OF_DQS; i = i+1) begin: gen_dq_error_map
          assign dq_lane_error[i] = (error_byte_r1[i] | 
                                     error_byte_r1[i + (NUM_DQ_PINS/NUM_OF_DQS)] |
                                     error_byte_r1[i + (NUM_DQ_PINS*2/NUM_OF_DQS)] | 
                                     error_byte_r1[i + (NUM_DQ_PINS*3/NUM_OF_DQS)] ) ? 1'b1 : 1'b0 ;
                                
          assign cumlative_dq_lane_error_c[i] =  cumlative_dq_lane_error_r[i] | dq_lane_error_r1[i];
      end
    end else begin: bl2_design
      for ( i = 0; i < NUM_DQ_PINS/NUM_OF_DQS; i = i+1) begin: gen_dq_error_map
          assign dq_lane_error[i] = (error_byte_r1[i] | 
                                     error_byte_r1[i + (NUM_DQ_PINS/NUM_OF_DQS)] ) ? 1'b1 : 1'b0 ;
                                
          assign cumlative_dq_lane_error_c[i] =  cumlative_dq_lane_error_r[i] | dq_lane_error_r1[i];
      end
    end

  end else begin: ddr_design_error_calc

    if (nCK_PER_CLK == 4) begin: ck_4to1_design
      for ( i = 0; i < NUM_DQ_PINS/NUM_OF_DQS; i = i+1) begin: gen_dq_error_map
          assign dq_lane_error[i] = (error_byte_r1[i] | 
                                     error_byte_r1[i + (NUM_DQ_PINS/NUM_OF_DQS)] |
                                     error_byte_r1[i + (NUM_DQ_PINS*2/NUM_OF_DQS)] | 
                                     error_byte_r1[i + (NUM_DQ_PINS*3/NUM_OF_DQS)] | 
                                     error_byte_r1[i + (NUM_DQ_PINS*4/NUM_OF_DQS)] | 
                                     error_byte_r1[i + (NUM_DQ_PINS*5/NUM_OF_DQS)] | 
                                     error_byte_r1[i + (NUM_DQ_PINS*6/NUM_OF_DQS)] | 
                                     error_byte_r1[i + (NUM_DQ_PINS*7/NUM_OF_DQS)] ) ? 1'b1 : 1'b0 ;
                                
          assign cumlative_dq_lane_error_c[i] =  cumlative_dq_lane_error_r[i] | dq_lane_error_r1[i];
      end
    end else if (nCK_PER_CLK == 2) begin: ck_2to1_design
      for ( i = 0; i < NUM_DQ_PINS/NUM_OF_DQS; i = i+1) begin: gen_dq_error_map
          assign dq_lane_error[i] = (error_byte_r1[i] | 
                                     error_byte_r1[i + (NUM_DQ_PINS/NUM_OF_DQS)] |
                                     error_byte_r1[i + (NUM_DQ_PINS*2/NUM_OF_DQS)] | 
                                     error_byte_r1[i + (NUM_DQ_PINS*3/NUM_OF_DQS)] ) ? 1'b1 : 1'b0 ;
                                
          assign cumlative_dq_lane_error_c[i] =  cumlative_dq_lane_error_r[i] | dq_lane_error_r1[i];
      end
    end
  end

   // mapped the user bits error to dq bits error

    // mapper the error to rising 0
    for ( i = 0; i < NUM_DQ_PINS; i = i+1) 
    begin: gen_dq_r0_error_mapbit
        assign dq_r0_bit_error[i] = (error_bit_r1[i]);
        assign cumlative_dq_r0_bit_error_c[i] =  cumlative_dq_r0_bit_error_r[i] | dq_r0_bit_error[i];
        
    end
    // mapper the error to falling 0
    for ( i = 0; i < NUM_DQ_PINS; i = i+1) 
    begin: gen_dq_f0_error_mapbit
        assign dq_f0_bit_error[i] = (error_bit_r1[i+NUM_DQ_PINS*1] );
        assign cumlative_dq_f0_bit_error_c[i] =  cumlative_dq_f0_bit_error_r[i] | dq_f0_bit_error[i];
        
    end

    // mapper the error to rising 1
    for ( i = 0; i < NUM_DQ_PINS; i = i+1) 
    begin: gen_dq_r1_error_mapbit
        assign dq_r1_bit_error[i] = (error_bit_r1[i+ (NUM_DQ_PINS*2)]);
        assign cumlative_dq_r1_bit_error_c[i] =  cumlative_dq_r1_bit_error_r[i] | dq_r1_bit_error[i];
        
    end

    // mapper the error to  falling 1
    for ( i = 0; i < NUM_DQ_PINS; i = i+1) 
    begin: gen_dq_f1_error_mapbit
        assign dq_f1_bit_error[i] = ( error_bit_r1[i+ (NUM_DQ_PINS*3)]);
        assign cumlative_dq_f1_bit_error_c[i] =  cumlative_dq_f1_bit_error_r[i] | dq_f1_bit_error[i];
    end                         
reg COuta;
always @ (posedge clk_i)
begin
    if (rst_i[1] || manual_clear_error) begin
      dq_bit_error_r1     <= #TCQ 'b0;
      dq_lane_error_r1 <= #TCQ 'b0;
      dq_lane_error_r2 <= #TCQ 'b0;
      data_valid_r1 <= #TCQ 1'b0;
	  data_valid_r2 <= #TCQ 1'b0;
      dq_r0_bit_error_r <= #TCQ 'b0;
      dq_f0_bit_error_r <= #TCQ 'b0;
      dq_r1_bit_error_r <= #TCQ 'b0;
      dq_f1_bit_error_r <= #TCQ 'b0;
      
      cumlative_dq_lane_error_reg <= #TCQ 'b0;
      cumlative_dq_r0_bit_error_r <= #TCQ  'b0;
      cumlative_dq_f0_bit_error_r <= #TCQ  'b0;
      cumlative_dq_r1_bit_error_r <= #TCQ  'b0;
      cumlative_dq_f1_bit_error_r <= #TCQ  'b0;
      error_addr_r1                <= #TCQ 'b0;
      error_addr_r2                <= #TCQ 'b0;
      error_addr_r3                <= #TCQ 'b0;
      
      end
    else begin
      data_valid_r1 <= #TCQ data_valid_i;
	  data_valid_r2 <= #TCQ data_valid_r1;
      dq_lane_error_r1 <= #TCQ dq_lane_error;
      dq_bit_error_r1  <= #TCQ dq_bit_error;
      
      cumlative_dq_lane_error_reg <= #TCQ cumlative_dq_lane_error_c;
      cumlative_dq_r0_bit_error_r <= #TCQ  cumlative_dq_r0_bit_error_c;
      
      cumlative_dq_f0_bit_error_r <= #TCQ  cumlative_dq_f0_bit_error_c;
      cumlative_dq_r1_bit_error_r <= #TCQ  cumlative_dq_r1_bit_error_c;
      cumlative_dq_f1_bit_error_r <= #TCQ  cumlative_dq_f1_bit_error_c;
      dq_r0_bit_error_r <= #TCQ dq_r0_bit_error;
      dq_f0_bit_error_r <= #TCQ dq_f0_bit_error;
      dq_r1_bit_error_r <= #TCQ dq_r1_bit_error;     
      dq_f1_bit_error_r <= #TCQ dq_f1_bit_error;  
      error_addr_r2 <= #TCQ error_addr_r1;
      error_addr_r3 <= #TCQ error_addr_r2;
      
      if (rd_mdata_en)
        error_addr_r1 <= #TCQ gen_addr;
      else if (data_valid_i)
        {COuta,error_addr_r1} <= #TCQ error_addr_r1 + 4;
      
    end
end

end
endgenerate
    
assign cumlative_dq_lane_error_r = cumlative_dq_lane_error_reg;     
assign dq_error_bytelane_cmp = dq_lane_error_r1;     
assign data_error_o = data_error;
assign error_addr_o = error_addr_r3;

     
endmodule 
