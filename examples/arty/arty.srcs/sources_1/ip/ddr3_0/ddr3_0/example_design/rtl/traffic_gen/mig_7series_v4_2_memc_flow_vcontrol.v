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
//  /   /         Filename: mcb_flow_control.v
// /___/   /\     Date Last Modified: $Date: 2011/06/02 08:37:21 $
// \   \  /  \    Date Created: 
//  \___\/\___\
//
//Device: Virtex 6
//Design Name: DDR2/DDR3
//Purpose: This module is the main flow control between cmd_gen.v, 
//         write_data_path and read_data_path modules.
//Reference:
//Revision History: 7/29/10  Support V6 Back-to-back commands over user interface.
//                          
//*****************************************************************************

`timescale 1ps/1ps

module mig_7series_v4_2_memc_flow_vcontrol #
  (
    parameter TCQ           = 100,
    parameter nCK_PER_CLK   = 4,
    parameter NUM_DQ_PINS   = 32,
    parameter BL_WIDTH      = 6,
    parameter MEM_BURST_LEN = 4,
    parameter FAMILY        = "SPARTAN6",
    parameter MEM_TYPE      = "DDR3"
    
  )
  ( 
   input                     clk_i, 
   input [9:0]               rst_i,
   input [3:0]               data_mode_i,
   input [5:0]               cmds_gap_delay_value,
   input                     mem_pattern_init_done_i,
   // interface to cmd_gen, pipeline inserter
   output reg                cmd_rdy_o, 
   input                     cmd_valid_i, 
   input [2:0]               cmd_i, 
   input [31:0]              addr_i, 
   input [BL_WIDTH - 1:0]    bl_i,

   // interface to mcb_cmd port
   input                     mcb_cmd_full,
   input                     mcb_wr_full_i,
   output reg [2:0]          cmd_o, 
   output [31:0]             addr_o, 
   output reg [BL_WIDTH-1:0] bl_o,
   output                    cmd_en_o,   // interface to write data path module
   // *** interface to qdr ****
   output reg                qdr_rd_cmd_o,
   // *************************
   input                     mcb_wr_en_i,
   input                     last_word_wr_i,
   input                     wdp_rdy_i, 
   output reg                wdp_valid_o, 
   output reg                wdp_validB_o, 
   output reg                wdp_validC_o,   
   output [31:0]             wr_addr_o, 
   output [BL_WIDTH-1:0]     wr_bl_o,
   // interface to read data path module
   input                     rdp_rdy_i, 
   output reg                rdp_valid_o, 
   output [31:0]             rd_addr_o, 
   output [BL_WIDTH-1:0]     rd_bl_o
   );
   
   //FSM State Defination
  localparam READY           = 4'b0001,
             READ            = 4'b0010,
             WRITE           = 4'b0100,
             CMD_WAIT        = 4'b1000;

  localparam RD              = 3'b001;
  localparam RDP             = 3'b011;
  localparam WR              = 3'b000;
  localparam WRP             = 3'b010;
  localparam REFRESH         = 3'b100;
  localparam NOP             = 3'b101; 


  reg                        cmd_fifo_rdy;
  reg                        push_cmd;
  reg                        cmd_rdy;
  reg [31:0]                 addr_r;
  reg [2:0]                  cmd_reg; 
  reg [31:0]                 addr_reg; 
  reg [BL_WIDTH-1:0]         bl_reg;
  reg [BL_WIDTH:0]           cmd_counts;
  reg                        rdp_valid;
(*EQUIVALENT_REGISTER_REMOVAL="NO"*) reg   wdp_valid,wdp_validB,wdp_validC;
  reg [3:0]                  current_state;
  reg [3:0]                  next_state;
  reg                        push_cmd_r;
  reg                        cmd_en_r1;
  reg                        wr_in_progress;
  reg                        wrcmd_in_progress;
  reg                        rdcmd_in_progress;
  reg [5:0]                  commands_delay_counters;
  reg                        goahead;
  reg                        cmd_en_r2;
  reg                        cmd_wr_pending_r1;  
  reg [3:0]                  addr_INC;
  reg                        COuta;
  wire                       cmd_rd;
  wire                       cmd_wr;        

  always @ (posedge clk_i) begin
    if (data_mode_i == 4'b1000 || FAMILY == "SPARTAN6")
      addr_INC <= #TCQ  0;
    else
      addr_INC <= #TCQ  MEM_BURST_LEN[3:0];
  end

// mcb_command bus outputs
  always @(posedge clk_i) begin    
    if (rst_i[0]) begin
      commands_delay_counters <= 6'b00000;
      goahead <= 1'b1;
    end
    else if (cmds_gap_delay_value == 5'd0)
      goahead <= 1'b1;
    else if (wr_in_progress || wrcmd_in_progress || 
             rdcmd_in_progress || cmd_rdy_o) begin
      commands_delay_counters <= 6'b00000;
      goahead <= 1'b0;
    end
    else if (commands_delay_counters == cmds_gap_delay_value) begin
      commands_delay_counters <= commands_delay_counters;
      goahead <= 1'b1;
    end
    else  
      commands_delay_counters <= commands_delay_counters + 1'b1;
  end

  assign cmd_en_o = (FAMILY == "VIRTEX6") ? cmd_en_r1 : (~cmd_en_r1 & cmd_en_r2) ;

  always @ (posedge clk_i)
    cmd_rdy_o <= #TCQ cmd_rdy;

  always @ (posedge clk_i) begin
    if (rst_i[8])
      cmd_en_r1 <= #TCQ 1'b0;
//    else if (cmd_counts == 1 && (!mcb_cmd_full &&  cmd_en_r1 || mcb_wr_full_i))
    else if (cmd_counts == 1 && (!mcb_cmd_full &&  cmd_en_r1 ))

      cmd_en_r1 <= #TCQ 1'b0;
    else if ((rdcmd_in_progress || wrcmd_in_progress && MEM_TYPE != "QDR2PLUS") ||
             (mcb_wr_en_i && MEM_TYPE == "QDR2PLUS"))
      cmd_en_r1 <= #TCQ 1'b1;
    else if (!mcb_cmd_full)
      cmd_en_r1 <= #TCQ 1'b0;
  end

  always @ (posedge clk_i)
    if (rst_i[8])
      cmd_en_r2 <= #TCQ 1'b0;
    else
      cmd_en_r2 <= cmd_en_r1;

// QDR read command generation
  always @ (posedge clk_i) begin
    if (rst_i[8])
      qdr_rd_cmd_o <= #TCQ 1'b0;
    else if (cmd_counts == 1 && !mcb_cmd_full && rdcmd_in_progress && cmd_en_r1)
      qdr_rd_cmd_o <= #TCQ 1'b0;
    else if (rdcmd_in_progress)
      qdr_rd_cmd_o <= #TCQ 1'b1;
    else if (!mcb_cmd_full)
      qdr_rd_cmd_o <= #TCQ  1'b0;
  end

  always @ (posedge clk_i) begin
    if (rst_i[9])
      cmd_fifo_rdy <= #TCQ  1'b1;
    else if (cmd_en_r1 || mcb_cmd_full)
      cmd_fifo_rdy <= #TCQ  1'b0;
    else if (!mcb_cmd_full)    
      cmd_fifo_rdy <= #TCQ  1'b1;
  end

  always @ (posedge clk_i) begin
    if (rst_i[9]) begin
      cmd_o  <= #TCQ 'b0;
      bl_o   <= #TCQ 'b0;
    end
    else if (push_cmd_r && current_state == READ) begin
      cmd_o  <= #TCQ cmd_i;
      bl_o   <= #TCQ bl_i - 'b1;
    end
    else if (push_cmd_r && current_state == WRITE) begin
      if (FAMILY == "SPARTAN6")
        cmd_o <= #TCQ cmd_reg;
      else
        cmd_o <= #TCQ {2'b00,cmd_reg[0]};
      bl_o  <= #TCQ bl_reg;
    end
  end

  always @ (posedge clk_i)
    if ((push_cmd && mem_pattern_init_done_i) | rst_i)
      addr_reg <= #TCQ addr_i;
    else if (push_cmd && !mem_pattern_init_done_i)
      addr_reg <= #TCQ addr_r;
        
  always @ (posedge clk_i) begin
    if (push_cmd && cmd_rd || rst_i[0])
      addr_r <= #TCQ  addr_i;
    else if (push_cmd_r && current_state != READ)
      addr_r <= #TCQ  addr_reg;
    else if ((wrcmd_in_progress || rdcmd_in_progress) &&
             cmd_en_r1 && ~mcb_cmd_full) begin
      if (MEM_TYPE == "QDR2PLUS")
        {COuta,addr_r[31:0]} <= addr_o + 1;
      else
        {COuta,addr_r[31:0]} <= addr_o + addr_INC;

    end
  end

  assign addr_o    = addr_r;
  assign wr_addr_o = addr_i;
  assign rd_addr_o = addr_i;
  assign rd_bl_o   = bl_i;
  assign wr_bl_o   = bl_i;

  always @ (posedge clk_i) begin
    wdp_valid_o  <= wdp_valid;
    wdp_validB_o <= wdp_validB;
    wdp_validC_o <= wdp_validC;
  end

  always @ (posedge clk_i)
    rdp_valid_o <= rdp_valid;

  always @(posedge clk_i)
    push_cmd_r  <= #TCQ push_cmd;

  always @(posedge clk_i)
    if (push_cmd) begin
      cmd_reg <= #TCQ cmd_i;
      bl_reg  <= #TCQ bl_i - 1'b1;
    end
 
  always @ (posedge clk_i)
  begin
    if (rst_i[8])
      cmd_counts <= #TCQ 'b0;
    else if (push_cmd_r) begin
      if (bl_i == 0) begin
        if (MEM_BURST_LEN == 8) begin
          if (nCK_PER_CLK == 4)
            cmd_counts <= #TCQ {2'b01, {BL_WIDTH-1{1'b0}}};
          else
            cmd_counts <= #TCQ {3'b001, {BL_WIDTH-2{1'b0}}};
        end        
        else
          cmd_counts <= {1'b0,{BL_WIDTH{1'b1}}} ;//- 2;//63;
      end     
      else begin
        if (MEM_BURST_LEN == 8) begin
          if (nCK_PER_CLK == 4)         
            cmd_counts <= {1'b0,bl_i};
          else
            cmd_counts <= {3'b000,bl_i[BL_WIDTH-2:1]}; 
        end        
        else 
          cmd_counts <= {1'b0,bl_i};//- 1 ;// {1'b0,bl_i[5:1]} -2;
      end     
    end
    else if ((wrcmd_in_progress  || rdcmd_in_progress) && cmd_en_r1 && ~mcb_cmd_full) begin
      if (cmd_counts > 0) begin
        if (FAMILY == "VIRTEX6")
          cmd_counts <= cmd_counts - 1'b1;
        else if (wrcmd_in_progress)
          cmd_counts <= cmd_counts - 1'b1;
        else
          cmd_counts <= 0;
      end
    end
  end  
 
  //--Command Decodes--
  assign cmd_wr = ((cmd_i == WR | cmd_i == WRP) & cmd_valid_i) ? 1'b1 : 1'b0;
  assign cmd_rd = ((cmd_i == RD | cmd_i == RDP) & cmd_valid_i) ? 1'b1 : 1'b0;

  always @ (posedge clk_i) begin
    if (rst_i[0])
      cmd_wr_pending_r1 <= #TCQ 1'b0;
    else if (last_word_wr_i)
      cmd_wr_pending_r1 <= #TCQ 1'b1;
    else if (push_cmd & cmd_wr)
      cmd_wr_pending_r1 <= #TCQ 1'b0;
  end    

  always @ (posedge clk_i) begin
    if (rst_i[0])
      wr_in_progress <= #TCQ 1'b0;
    else if (last_word_wr_i)   
      wr_in_progress <= #TCQ 1'b0;   
    else if (push_cmd && cmd_wr)   
      wr_in_progress <= #TCQ 1'b1;
  end

  always @ (posedge clk_i) begin
    if (rst_i[0])
      wrcmd_in_progress <= #TCQ 1'b0;
    else if (cmd_wr && push_cmd_r)   
      wrcmd_in_progress <= #TCQ 1'b1;   
    else if (cmd_counts == 0  || (cmd_counts == 1 && ~mcb_cmd_full))
      wrcmd_in_progress <= #TCQ 1'b0;
  end

  always @ (posedge clk_i) begin
    if (rst_i[0])
      rdcmd_in_progress <= #TCQ 1'b0;
    else if (cmd_rd && push_cmd_r)   
      rdcmd_in_progress <= #TCQ 1'b1;
    else if (cmd_counts <= 1)   
      rdcmd_in_progress <= #TCQ 1'b0;   
  end

// mcb_flow_control statemachine
  always @ (posedge clk_i)
    if (rst_i[0])
      current_state <= #TCQ  5'b00001;
    else
      current_state <= #TCQ next_state;

  always @ (*) begin
    push_cmd   = 1'b0;
    wdp_valid  = 1'b0;
    wdp_validB = 1'b0;
    wdp_validC = 1'b0;
    rdp_valid  = 1'b0;
    cmd_rdy    = 1'b0;
    next_state = current_state;

    case(current_state) // next state logic

      READY: begin // 5'h01  

        if (rdp_rdy_i && cmd_rd && ~mcb_cmd_full) begin
          next_state = READ;
          push_cmd   = 1'b1;
          rdp_valid  = 1'b1;
          cmd_rdy    = 1'b1;
        end
        else if (wdp_rdy_i && cmd_wr && ~mcb_cmd_full) begin
          next_state = WRITE;
          push_cmd   = 1'b1;
          wdp_valid  = 1'b1;
          wdp_validB = 1'b1;
          wdp_validC = 1'b1;
          cmd_rdy    = 1'b1;
        end 
        else begin
          next_state = READY;
          push_cmd   = 1'b0;
          cmd_rdy    = 1'b0;
        end
      end // READY
         
      READ: begin // 5'h02
   
        if (rdcmd_in_progress) begin
          next_state = READ;
          push_cmd   = 1'b0;
          rdp_valid  = 1'b0;
          wdp_valid  = 1'b0;
        end   
        else if (!rdp_rdy_i) begin
          next_state = READ; 
          push_cmd   = 1'b0;
          wdp_valid  = 1'b0;
          wdp_validB = 1'b0;
          wdp_validC = 1'b0;
          rdp_valid  = 1'b0;
        end                       
        else if (~cmd_fifo_rdy && ~rdcmd_in_progress && goahead) begin
          next_state = CMD_WAIT;
        end  
        else if (goahead && ~push_cmd_r) begin
          next_state = READY; 
          cmd_rdy    = 1'b0;
        end
        else
          next_state = READ; 
      end // READ

      WRITE: begin  // 5'h04

        if (wr_in_progress || wrcmd_in_progress || push_cmd_r) begin
          next_state = WRITE;
          wdp_valid  = 1'b0;
          wdp_validB = 1'b0;
          wdp_validC = 1'b0;
          push_cmd   = 1'b0;
        end               
        else if (!cmd_fifo_rdy && last_word_wr_i && goahead) begin
          next_state = CMD_WAIT;
          push_cmd   = 1'b0;
        end
        else if (goahead) begin
          next_state = READY;
        end
        else
          next_state = WRITE;
               
        cmd_rdy = 1'b0;
         
      end // WRITE

      CMD_WAIT: begin // 5'h08
       
        if (!cmd_fifo_rdy || wr_in_progress) begin
          next_state = CMD_WAIT;
          cmd_rdy    = 1'b0;
        end
        else if (cmd_fifo_rdy && rdp_rdy_i && cmd_rd) begin
          next_state = READY;
          push_cmd   = 1'b0;
          cmd_rdy    = 1'b0;
          rdp_valid  = 1'b0;
        end
        else if (cmd_fifo_rdy  && cmd_wr && goahead && 
                 cmd_wr_pending_r1) begin
          next_state = READY;
          push_cmd   = 1'b0;
          cmd_rdy    = 1'b0;
          wdp_valid  = 1'b0;
          wdp_validB = 1'b0;
          wdp_validC = 1'b0;
        end
        else begin
          next_state = CMD_WAIT;
          cmd_rdy    = 1'b0;
        end
      end // CMD_WAIT
 
      default: begin
        push_cmd     = 1'b0;
        wdp_valid    = 1'b0;
        wdp_validB   = 1'b0;
        wdp_validC   = 1'b0;
        next_state   = READY;              
      end
   
    endcase
  end
   
endmodule 
