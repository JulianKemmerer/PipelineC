--*****************************************************************************
-- (c) Copyright 2009 - 2012 Xilinx, Inc. All rights reserved.
--
-- This file contains confidential and proprietary information
-- of Xilinx, Inc. and is protected under U.S. and
-- international copyright and other intellectual property
-- laws.
--
-- DISCLAIMER
-- This disclaimer is not a license and does not grant any
-- rights to the materials distributed herewith. Except as
-- otherwise provided in a valid license issued to you by
-- Xilinx, and to the maximum extent permitted by applicable
-- law: (1) THESE MATERIALS ARE MADE AVAILABLE "AS IS" AND
-- WITH ALL FAULTS, AND XILINX HEREBY DISCLAIMS ALL WARRANTIES
-- AND CONDITIONS, EXPRESS, IMPLIED, OR STATUTORY, INCLUDING
-- BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, NON-
-- INFRINGEMENT, OR FITNESS FOR ANY PARTICULAR PURPOSE; and
-- (2) Xilinx shall not be liable (whether in contract or tort,
-- including negligence, or under any other theory of
-- liability) for any loss or damage of any kind or nature
-- related to, arising under or in connection with these
-- materials, including for any direct, or any indirect,
-- special, incidental, or consequential loss or damage
-- (including loss of data, profits, goodwill, or any type of
-- loss or damage suffered as a result of any action brought
-- by a third party) even if such damage or loss was
-- reasonably foreseeable or Xilinx had been advised of the
-- possibility of the same.
--
-- CRITICAL APPLICATIONS
-- Xilinx products are not designed or intended to be fail-
-- safe, or for use in any application requiring fail-safe
-- performance, such as life-support or safety devices or
-- systems, Class III medical devices, nuclear facilities,
-- applications related to the deployment of airbags, or any
-- other applications that could lead to death, personal
-- injury, or severe property or environmental damage
-- (individually and collectively, "Critical
-- Applications"). Customer assumes the sole risk and
-- liability of any use of Xilinx products in Critical
-- Applications, subject only to applicable laws and
-- regulations governing limitations on product liability.
--
-- THIS COPYRIGHT NOTICE AND DISCLAIMER MUST BE RETAINED AS
-- PART OF THIS FILE AT ALL TIMES.
--
--*****************************************************************************
--   ____  ____
--  /   /\/   /
-- /___/  \  /    Vendor             : Xilinx
-- \   \   \/     Version            : 4.2
--  \   \         Application        : MIG
--  /   /         Filename           : example_top.vhd
-- /___/   /\     Date Last Modified : $Date: 2011/06/02 08:35:03 $
-- \   \  /  \    Date Created       : Wed Feb 01 2012
--  \___\/\___\
--
-- Device           : 7 Series
-- Design Name      : DDR3 SDRAM
-- Purpose          :
--   Top-level  module. This module serves as an example,
--   and allows the user to synthesize a self-contained design,
--   which they can be used to test their hardware.
--   In addition to the memory controller, the module instantiates:
--     1. Synthesizable testbench - used to model user's backend logic
--        and generate different traffic patterns
-- Reference        :
-- Revision History :
--*****************************************************************************

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;


entity example_top is
  generic (
   --***************************************************************************
   -- Traffic Gen related parameters
   --***************************************************************************
   BL_WIDTH              : integer := 10;
   PORT_MODE             : string  := "BI_MODE";
   DATA_MODE             : std_logic_vector(3 downto 0) := "0010";
   TST_MEM_INSTR_MODE    : string  := "R_W_INSTR_MODE";
   EYE_TEST              : string  := "FALSE";
                                     -- set EYE_TEST = "TRUE" to probe memory
                                     -- signals. Traffic Generator will only
                                     -- write to one single location and no
                                     -- read transactions will be generated.
   DATA_PATTERN          : string  := "DGEN_ALL";
                                      -- For small devices, choose one only.
                                      -- For large device, choose "DGEN_ALL"
                                      -- "DGEN_HAMMER", "DGEN_WALKING1",
                                      -- "DGEN_WALKING0","DGEN_ADDR","
                                      -- "DGEN_NEIGHBOR","DGEN_PRBS","DGEN_ALL"
   CMD_PATTERN           : string  := "CGEN_ALL";
                                      -- "CGEN_PRBS","CGEN_FIXED","CGEN_BRAM",
                                      -- "CGEN_SEQUENTIAL", "CGEN_ALL"
   BEGIN_ADDRESS         : std_logic_vector(31 downto 0) := X"00000000";
   END_ADDRESS           : std_logic_vector(31 downto 0) := X"00ffffff";
   PRBS_EADDR_MASK_POS   : std_logic_vector(31 downto 0) := X"ff000000";
   CMD_WDT               : std_logic_vector(31 downto 0) := X"000003ff";
   WR_WDT                : std_logic_vector(31 downto 0) := X"00001fff";
   RD_WDT                : std_logic_vector(31 downto 0) := X"000003ff";
   --***************************************************************************
   -- The following parameters refer to width of various ports
   --***************************************************************************
   COL_WIDTH             : integer := 10;
                                     -- # of memory Column Address bits.
   CS_WIDTH              : integer := 1;
                                     -- # of unique CS outputs to memory.
   DM_WIDTH              : integer := 2;
                                     -- # of DM (data mask)
   DQ_WIDTH              : integer := 16;
                                     -- # of DQ (data)
   DQS_CNT_WIDTH         : integer := 1;
                                     -- = ceil(log2(DQS_WIDTH))
   DRAM_WIDTH            : integer := 8;
                                     -- # of DQ per DQS
   ECC_TEST              : string  := "OFF";
   RANKS                 : integer := 1;
                                     -- # of Ranks.
   ROW_WIDTH             : integer := 14;
                                     -- # of memory Row Address bits.
   ADDR_WIDTH            : integer := 28;
                                     -- # = RANK_WIDTH + BANK_WIDTH
                                     --     + ROW_WIDTH + COL_WIDTH;
                                     -- Chip Select is always tied to low for
                                     -- single rank devices
   --***************************************************************************
   -- The following parameters are mode register settings
   --***************************************************************************
   BURST_MODE            : string  := "8";
                                     -- DDR3 SDRAM:
                                     -- Burst Length (Mode Register 0).
                                     -- # = "8", "4", "OTF".
                                     -- DDR2 SDRAM:
                                     -- Burst Length (Mode Register).
                                     -- # = "8", "4".
   
   --***************************************************************************
   -- Simulation parameters
   --***************************************************************************
   SIMULATION            : string  := "FALSE";
                                     -- Should be TRUE during design simulations and
                                     -- FALSE during implementations

   --***************************************************************************
   -- IODELAY and PHY related parameters
   --***************************************************************************
   TCQ                   : integer := 100;
   
   DRAM_TYPE             : string  := "DDR3";

   
   --***************************************************************************
   -- System clock frequency parameters
   --***************************************************************************
   nCK_PER_CLK           : integer := 4;
                                     -- # of memory CKs per fabric CLK

   --***************************************************************************
   -- Debug parameters
   --***************************************************************************
   DEBUG_PORT            : string  := "OFF";
                                     -- # = "ON" Enable debug signals/controls.
                                     --   = "OFF" Disable debug signals/controls.

   --***************************************************************************
   -- Temparature monitor parameter
   --***************************************************************************
   TEMP_MON_CONTROL         : string  := "INTERNAL";
                                     -- # = "INTERNAL", "EXTERNAL"
      
   RST_ACT_LOW           : integer := 1
                                     -- =1 for active low reset,
                                     -- =0 for active high.
   );
  port (

   -- Inouts
   ddr3_dq                        : inout std_logic_vector(15 downto 0);
   ddr3_dqs_p                     : inout std_logic_vector(1 downto 0);
   ddr3_dqs_n                     : inout std_logic_vector(1 downto 0);

   -- Outputs
   ddr3_addr                      : out   std_logic_vector(13 downto 0);
   ddr3_ba                        : out   std_logic_vector(2 downto 0);
   ddr3_ras_n                     : out   std_logic;
   ddr3_cas_n                     : out   std_logic;
   ddr3_we_n                      : out   std_logic;
   ddr3_reset_n                   : out   std_logic;
   ddr3_ck_p                      : out   std_logic_vector(0 downto 0);
   ddr3_ck_n                      : out   std_logic_vector(0 downto 0);
   ddr3_cke                       : out   std_logic_vector(0 downto 0);
   ddr3_cs_n                      : out   std_logic_vector(0 downto 0);
   ddr3_dm                        : out   std_logic_vector(1 downto 0);
   ddr3_odt                       : out   std_logic_vector(0 downto 0);

   -- Inputs
   -- Single-ended system clock
   sys_clk_i                      : in    std_logic;
   -- Single-ended iodelayctrl clk (reference clock)
   clk_ref_i                                : in    std_logic;
   
   tg_compare_error              : out std_logic;
   init_calib_complete           : out std_logic;
   
      

   -- System reset - Default polarity of sys_rst pin is Active Low.
   -- System reset polarity will change based on the option 
   -- selected in GUI.
      sys_rst                     : in    std_logic
   );

end entity example_top;

architecture arch_example_top of example_top is


  -- clogb2 function - ceiling of log base 2
  function clogb2 (size : integer) return integer is
    variable base : integer := 1;
    variable inp : integer := 0;
  begin
    inp := size - 1;
    while (inp > 1) loop
      inp := inp/2 ;
      base := base + 1;
    end loop;
    return base;
  end function;function STR_TO_INT(BM : string) return integer is
  begin
   if(BM = "8") then
     return 8;
   elsif(BM = "4") then
     return 4;
   else
     return 0;
   end if;
  end function;

  constant RANK_WIDTH : integer := clogb2(RANKS);

  function XWIDTH return integer is
  begin
    if(CS_WIDTH = 1) then
      return 0;
    else
      return RANK_WIDTH;
    end if;
  end function;
  


  constant CMD_PIPE_PLUS1        : string  := "ON";
                                     -- add pipeline stage between MC and PHY
--  constant ECC_TEST              : string  := "OFF";

  constant tPRDI                 : integer := 1000000;
                                     -- memory tPRDI paramter in pS.
  constant DATA_WIDTH            : integer := 16;
  constant PAYLOAD_WIDTH         : integer := DATA_WIDTH;
  constant BURST_LENGTH          : integer := STR_TO_INT(BURST_MODE);
  constant APP_DATA_WIDTH        : integer := 2 * nCK_PER_CLK * PAYLOAD_WIDTH;
  constant APP_MASK_WIDTH        : integer := APP_DATA_WIDTH / 8;

  --***************************************************************************
  -- Traffic Gen related parameters (derived)
  --***************************************************************************
  constant  TG_ADDR_WIDTH        : integer := XWIDTH + 3 + ROW_WIDTH + COL_WIDTH;
  constant MASK_SIZE             : integer := DATA_WIDTH/8;
      

-- Start of User Design wrapper top component

  component ddr3_0
    port(
      ddr3_dq       : inout std_logic_vector(15 downto 0);
      ddr3_dqs_p    : inout std_logic_vector(1 downto 0);
      ddr3_dqs_n    : inout std_logic_vector(1 downto 0);

      ddr3_addr     : out   std_logic_vector(13 downto 0);
      ddr3_ba       : out   std_logic_vector(2 downto 0);
      ddr3_ras_n    : out   std_logic;
      ddr3_cas_n    : out   std_logic;
      ddr3_we_n     : out   std_logic;
      ddr3_reset_n  : out   std_logic;
      ddr3_ck_p     : out   std_logic_vector(0 downto 0);
      ddr3_ck_n     : out   std_logic_vector(0 downto 0);
      ddr3_cke      : out   std_logic_vector(0 downto 0);
      ddr3_cs_n     : out   std_logic_vector(0 downto 0);
      ddr3_dm       : out   std_logic_vector(1 downto 0);
      ddr3_odt      : out   std_logic_vector(0 downto 0);
      app_addr                  : in    std_logic_vector(27 downto 0);
      app_cmd                   : in    std_logic_vector(2 downto 0);
      app_en                    : in    std_logic;
      app_wdf_data              : in    std_logic_vector(127 downto 0);
      app_wdf_end               : in    std_logic;
      app_wdf_mask         : in    std_logic_vector(15 downto 0);
      app_wdf_wren              : in    std_logic;
      app_rd_data               : out   std_logic_vector(127 downto 0);
      app_rd_data_end           : out   std_logic;
      app_rd_data_valid         : out   std_logic;
      app_rdy                   : out   std_logic;
      app_wdf_rdy               : out   std_logic;
      app_sr_req                : in    std_logic;
      app_ref_req               : in    std_logic;
      app_zq_req                : in    std_logic;
      app_sr_active             : out   std_logic;
      app_ref_ack               : out   std_logic;
      app_zq_ack                : out   std_logic;
      ui_clk                    : out   std_logic;
      ui_clk_sync_rst           : out   std_logic;
      init_calib_complete       : out   std_logic;
      -- System Clock Ports
      sys_clk_i                      : in    std_logic;
      -- Reference Clock Ports
      clk_ref_i                                : in    std_logic;
      device_temp     : out std_logic_vector(11 downto 0);
      sys_rst             : in std_logic
      );
  end component ddr3_0;

-- End of User Design wrapper top component



  component mig_7series_v4_2_traffic_gen_top
    generic (
      TCQ                      : integer;
      SIMULATION               : string;
      FAMILY                   : string;
      MEM_TYPE                 : string;
      TST_MEM_INSTR_MODE       : string;
      --BL_WIDTH                 : integer;
      nCK_PER_CLK              : integer;
      NUM_DQ_PINS              : integer;
      MEM_BURST_LEN            : integer;
      MEM_COL_WIDTH            : integer;
      DATA_WIDTH               : integer;
      ADDR_WIDTH               : integer;
      MASK_SIZE                : integer := 8;
      DATA_MODE                : std_logic_vector(3 downto 0);
      BEGIN_ADDRESS            : std_logic_vector(31 downto 0);
      END_ADDRESS              : std_logic_vector(31 downto 0);
      PRBS_EADDR_MASK_POS      : std_logic_vector(31 downto 0);
      CMDS_GAP_DELAY           : std_logic_vector(5 downto 0) := "000000";
      SEL_VICTIM_LINE          : integer := 8;
      CMD_WDT                  : std_logic_vector(31 downto 0) := X"000003ff";
      WR_WDT                   : std_logic_vector(31 downto 0) := X"00001fff";
      RD_WDT                   : std_logic_vector(31 downto 0) := X"000003ff";
      EYE_TEST                 : string;
      PORT_MODE                : string;
      DATA_PATTERN             : string;
      CMD_PATTERN              : string
      );
    port (
      clk                    : in   std_logic;
      rst                    : in   std_logic;
      tg_only_rst            : in   std_logic;
      manual_clear_error     : in   std_logic;
      memc_init_done         : in   std_logic;
      memc_cmd_full          : in   std_logic;
      memc_cmd_en            : out  std_logic;
      memc_cmd_instr         : out  std_logic_vector(2 downto 0);
      memc_cmd_bl            : out  std_logic_vector(5 downto 0);
      memc_cmd_addr          : out  std_logic_vector(31 downto 0);
      memc_wr_en             : out  std_logic;
      memc_wr_end            : out  std_logic;
      memc_wr_mask           : out  std_logic_vector((DATA_WIDTH/8)-1 downto 0);
      memc_wr_data           : out  std_logic_vector(DATA_WIDTH-1 downto 0);
      memc_wr_full           : in   std_logic;
      memc_rd_en             : out  std_logic;
      memc_rd_data           : in   std_logic_vector(DATA_WIDTH-1 downto 0);
      memc_rd_empty          : in   std_logic;
      qdr_wr_cmd_o           : out  std_logic;
      qdr_rd_cmd_o           : out  std_logic;
      vio_pause_traffic      : in   std_logic;
      vio_modify_enable      : in   std_logic;
      vio_data_mode_value    : in   std_logic_vector(3 downto 0);
      vio_addr_mode_value    : in   std_logic_vector(2 downto 0);
      vio_instr_mode_value   : in   std_logic_vector(3 downto 0);
      vio_bl_mode_value      : in   std_logic_vector(1 downto 0);
      vio_fixed_bl_value     : in   std_logic_vector(9 downto 0);
      vio_fixed_instr_value  : in   std_logic_vector(2 downto 0);
      vio_data_mask_gen      : in   std_logic;
      fixed_addr_i           : in   std_logic_vector(31 downto 0);
      fixed_data_i           : in   std_logic_vector(31 downto 0);
      simple_data0           : in   std_logic_vector(31 downto 0);
      simple_data1           : in   std_logic_vector(31 downto 0);
      simple_data2           : in   std_logic_vector(31 downto 0);
      simple_data3           : in   std_logic_vector(31 downto 0);
      simple_data4           : in   std_logic_vector(31 downto 0);
      simple_data5           : in   std_logic_vector(31 downto 0);
      simple_data6           : in   std_logic_vector(31 downto 0);
      simple_data7           : in   std_logic_vector(31 downto 0);
      wdt_en_i               : in   std_logic;
      bram_cmd_i             : in   std_logic_vector(38 downto 0);
      bram_valid_i           : in   std_logic;
      bram_rdy_o             : out  std_logic;
      cmp_data               : out  std_logic_vector(DATA_WIDTH-1 downto 0);
      cmp_data_valid         : out  std_logic;
      cmp_error              : out  std_logic;
      wr_data_counts         : out   std_logic_vector(47 downto 0);
      rd_data_counts         : out   std_logic_vector(47 downto 0);
      dq_error_bytelane_cmp  : out  std_logic_vector((NUM_DQ_PINS/8)-1 downto 0);
      error                  : out  std_logic;
      error_status           : out  std_logic_vector((64+(2*DATA_WIDTH))-1 downto 0);
      cumlative_dq_lane_error : out  std_logic_vector((NUM_DQ_PINS/8)-1 downto 0);
      cmd_wdt_err_o          : out std_logic;
      wr_wdt_err_o           : out std_logic;
      rd_wdt_err_o           : out std_logic;
      mem_pattern_init_done   : out  std_logic
      );
  end component mig_7series_v4_2_traffic_gen_top;
      

  -- Signal declarations
      
  signal app_ecc_multiple_err        : std_logic_vector((2*nCK_PER_CLK)-1 downto 0);
  signal app_ecc_single_err          : std_logic_vector((2*nCK_PER_CLK)-1 downto 0);
  signal app_addr                    : std_logic_vector(ADDR_WIDTH-1 downto 0);
  signal app_addr_i                  : std_logic_vector(31 downto 0);
  signal app_cmd                     : std_logic_vector(2 downto 0);
  signal app_en                      : std_logic;
  signal app_rdy                     : std_logic;
  signal app_rdy_i                   : std_logic;
  signal app_rd_data                 : std_logic_vector(APP_DATA_WIDTH-1 downto 0);
  signal app_rd_data_end             : std_logic;
  signal app_rd_data_valid           : std_logic;
  signal app_rd_data_valid_i         : std_logic;
  signal app_wdf_data                : std_logic_vector(APP_DATA_WIDTH-1 downto 0);
  signal app_wdf_end                 : std_logic;
  signal app_wdf_mask                : std_logic_vector(APP_MASK_WIDTH-1 downto 0);
  signal app_wdf_rdy                 : std_logic;
  signal app_wdf_rdy_i               : std_logic;
  signal app_sr_active               : std_logic;
  signal app_ref_ack                 : std_logic;
  signal app_zq_ack                  : std_logic;
  signal app_wdf_wren                : std_logic;
  signal error_status                : std_logic_vector((64 + (4*PAYLOAD_WIDTH*nCK_PER_CLK))-1 downto 0);
  signal cumlative_dq_lane_error     : std_logic_vector((PAYLOAD_WIDTH/8)-1 downto 0);
  signal mem_pattern_init_done       : std_logic_vector(0 downto 0);
  signal modify_enable_sel           : std_logic;
  signal data_mode_manual_sel        : std_logic_vector(2 downto 0);
  signal addr_mode_manual_sel        : std_logic_vector(2 downto 0);
  signal cmp_data                    : std_logic_vector((PAYLOAD_WIDTH*2*nCK_PER_CLK)-1 downto 0);
  signal cmp_data_r                  : std_logic_vector(63 downto 0);
  signal cmp_data_valid              : std_logic;
  signal cmp_data_valid_r            : std_logic;
  signal cmp_error                   : std_logic;
  signal tg_wr_data_counts           : std_logic_vector(47 downto 0);
  signal tg_rd_data_counts           : std_logic_vector(47 downto 0);
  signal dq_error_bytelane_cmp       : std_logic_vector((PAYLOAD_WIDTH/8)-1 downto 0);
  signal init_calib_complete_i       : std_logic;
  signal tg_compare_error_i          : std_logic;
  signal tg_rst                      : std_logic;
  signal po_win_tg_rst               : std_logic;
  signal manual_clear_error          : std_logic_vector(0 downto 0);

  signal clk                         : std_logic;
  signal rst                         : std_logic;

  signal vio_modify_enable           : std_logic_vector(0 downto 0);
  signal vio_data_mode_value         : std_logic_vector(3 downto 0);
  signal vio_pause_traffic           : std_logic_vector(0 downto 0);
  signal vio_addr_mode_value         : std_logic_vector(2 downto 0);
  signal vio_instr_mode_value        : std_logic_vector(3 downto 0);
  signal vio_bl_mode_value           : std_logic_vector(1 downto 0);
  signal vio_fixed_bl_value          : std_logic_vector(BL_WIDTH-1 downto 0);
  signal vio_fixed_instr_value       : std_logic_vector(2 downto 0);
  signal vio_data_mask_gen           : std_logic_vector(0 downto 0);
  signal dbg_clear_error             : std_logic_vector(0 downto 0);
  signal vio_tg_rst                  : std_logic_vector(0 downto 0);
  signal dbg_sel_pi_incdec           : std_logic_vector(0 downto 0);
  signal dbg_pi_f_inc                : std_logic_vector(0 downto 0);
  signal dbg_pi_f_dec                : std_logic_vector(0 downto 0);
  signal dbg_sel_po_incdec           : std_logic_vector(0 downto 0);
  signal dbg_po_f_inc                : std_logic_vector(0 downto 0);
  signal dbg_po_f_stg23_sel          : std_logic_vector(0 downto 0);
  signal dbg_po_f_dec                : std_logic_vector(0 downto 0);
  signal vio_dbg_sel_pi_incdec           : std_logic_vector(0 downto 0);
  signal vio_dbg_pi_f_inc                : std_logic_vector(0 downto 0);
  signal vio_dbg_pi_f_dec                : std_logic_vector(0 downto 0);
  signal vio_dbg_sel_po_incdec           : std_logic_vector(0 downto 0);
  signal vio_dbg_po_f_inc                : std_logic_vector(0 downto 0);
  signal vio_dbg_po_f_stg23_sel          : std_logic_vector(0 downto 0);
  signal vio_dbg_po_f_dec                : std_logic_vector(0 downto 0);
  signal all_zeros1                  : std_logic_vector(31 downto 0):= (others => '0');
  signal all_zeros2                  : std_logic_vector(38 downto 0):= (others => '0');
  signal wdt_en_w                    : std_logic_vector(0 downto 0);
  signal cmd_wdt_err_w               : std_logic;
  signal wr_wdt_err_w                : std_logic;
  signal rd_wdt_err_w                : std_logic;
  signal device_temp                           : std_logic_vector(11 downto 0);
  


begin

--***************************************************************************


  init_calib_complete <= init_calib_complete_i;
  tg_compare_error <= tg_compare_error_i;


  app_rdy_i                   <= not(app_rdy);
  app_wdf_rdy_i               <= not(app_wdf_rdy);
  app_rd_data_valid_i         <= not(app_rd_data_valid);
  app_addr                    <= app_addr_i(ADDR_WIDTH-1 downto 0);
      




      

-- Start of User Design top instance
--***************************************************************************
-- The User design is instantiated below. The memory interface ports are
-- connected to the top-level and the application interface ports are
-- connected to the traffic generator module. This provides a reference
-- for connecting the memory controller to system.
--***************************************************************************

  u_ddr3_0 : ddr3_0
      port map (
       -- Memory interface ports
       ddr3_addr                      => ddr3_addr,
       ddr3_ba                        => ddr3_ba,
       ddr3_cas_n                     => ddr3_cas_n,
       ddr3_ck_n                      => ddr3_ck_n,
       ddr3_ck_p                      => ddr3_ck_p,
       ddr3_cke                       => ddr3_cke,
       ddr3_ras_n                     => ddr3_ras_n,
       ddr3_reset_n                   => ddr3_reset_n,
       ddr3_we_n                      => ddr3_we_n,
       ddr3_dq                        => ddr3_dq,
       ddr3_dqs_n                     => ddr3_dqs_n,
       ddr3_dqs_p                     => ddr3_dqs_p,
       init_calib_complete  => init_calib_complete_i,
       device_temp                    => device_temp,
       ddr3_cs_n                      => ddr3_cs_n,
       ddr3_dm                        => ddr3_dm,
       ddr3_odt                       => ddr3_odt,
-- Application interface ports
       app_addr                       => app_addr,
       app_cmd                        => app_cmd,
       app_en                         => app_en,
       app_wdf_data                   => app_wdf_data,
       app_wdf_end                    => app_wdf_end,
       app_wdf_wren                   => app_wdf_wren,
       app_rd_data                    => app_rd_data,
       app_rd_data_end                => app_rd_data_end,
       app_rd_data_valid              => app_rd_data_valid,
       app_rdy                        => app_rdy,
       app_wdf_rdy                    => app_wdf_rdy,
       app_sr_req                     => '0',
       app_ref_req                    => '0',
       app_zq_req                     => '0',
       app_sr_active                  => app_sr_active,
       app_ref_ack                    => app_ref_ack,
       app_zq_ack                     => app_zq_ack,
       ui_clk                         => clk,
       ui_clk_sync_rst                => rst,
       app_wdf_mask                   => app_wdf_mask,
-- System Clock Ports
       sys_clk_i                       => sys_clk_i,
-- Reference Clock Ports
       clk_ref_i                      => clk_ref_i,
        sys_rst                        => sys_rst
        );
-- End of User Design top instance


--***************************************************************************
-- The traffic generation module instantiated below drives traffic (patterns)
-- on the application interface of the memory controller
--***************************************************************************

  tg_rst <= vio_tg_rst(0) or po_win_tg_rst;

  u_traffic_gen_top : mig_7series_v4_2_traffic_gen_top
    generic map (
      TCQ                 => TCQ,
      SIMULATION          => SIMULATION,
      FAMILY              => "VIRTEX7",
      MEM_TYPE            => DRAM_TYPE,
      TST_MEM_INSTR_MODE  => TST_MEM_INSTR_MODE,
      --BL_WIDTH            => BL_WIDTH,
      nCK_PER_CLK         => nCK_PER_CLK,
      NUM_DQ_PINS         => PAYLOAD_WIDTH,
      MEM_BURST_LEN       => BURST_LENGTH,
      MEM_COL_WIDTH       => COL_WIDTH,
      PORT_MODE           => PORT_MODE,
      DATA_PATTERN        => DATA_PATTERN,
      CMD_PATTERN         => CMD_PATTERN,
      ADDR_WIDTH          => TG_ADDR_WIDTH,
      DATA_WIDTH          => APP_DATA_WIDTH,
      BEGIN_ADDRESS       => BEGIN_ADDRESS,
      DATA_MODE           => DATA_MODE,
      END_ADDRESS         => END_ADDRESS,
      PRBS_EADDR_MASK_POS => PRBS_EADDR_MASK_POS,
      CMD_WDT             => CMD_WDT,
      RD_WDT              => RD_WDT,
      WR_WDT              => WR_WDT,
      EYE_TEST            => EYE_TEST
      )
      port map (
        clk                  => clk,
        rst                  => rst,
        tg_only_rst          => tg_rst,
        manual_clear_error   => manual_clear_error(0),
        memc_init_done       => init_calib_complete_i,
        memc_cmd_full        => app_rdy_i,
        memc_cmd_en          => app_en,
        memc_cmd_instr       => app_cmd,
        memc_cmd_bl          => open,
        memc_cmd_addr        => app_addr_i,
        memc_wr_en           => app_wdf_wren,
        memc_wr_end          => app_wdf_end,
        memc_wr_mask         => app_wdf_mask(((PAYLOAD_WIDTH*2*nCK_PER_CLK)/8)-1 downto 0),
        memc_wr_data         => app_wdf_data((PAYLOAD_WIDTH*2*nCK_PER_CLK)-1 downto 0),
        memc_wr_full         => app_wdf_rdy_i,
        memc_rd_en           => open,
        memc_rd_data         => app_rd_data((PAYLOAD_WIDTH*2*nCK_PER_CLK)-1 downto 0),
        memc_rd_empty        => app_rd_data_valid_i,
        qdr_wr_cmd_o         => open,
        qdr_rd_cmd_o         => open,
        vio_pause_traffic    => vio_pause_traffic(0),
        vio_modify_enable    => vio_modify_enable(0),
        vio_data_mode_value  => vio_data_mode_value,
        vio_addr_mode_value  => vio_addr_mode_value,
        vio_instr_mode_value => vio_instr_mode_value,
        vio_bl_mode_value    => vio_bl_mode_value,
        vio_fixed_bl_value   => vio_fixed_bl_value,
        vio_fixed_instr_value=> vio_fixed_instr_value,
        vio_data_mask_gen    => vio_data_mask_gen(0),
        fixed_addr_i         => all_zeros1,
        fixed_data_i         => all_zeros1,
        simple_data0         => all_zeros1,
        simple_data1         => all_zeros1,
        simple_data2         => all_zeros1,
        simple_data3         => all_zeros1,
        simple_data4         => all_zeros1,
        simple_data5         => all_zeros1,
        simple_data6         => all_zeros1,
        simple_data7         => all_zeros1,
        wdt_en_i             => wdt_en_w(0),
        bram_cmd_i           => all_zeros2,
        bram_valid_i         => '0',
        bram_rdy_o           => open,
        cmp_data             => cmp_data,
        cmp_data_valid       => cmp_data_valid,
        cmp_error            => cmp_error,
        wr_data_counts       => tg_wr_data_counts,
        rd_data_counts       => tg_rd_data_counts,
        dq_error_bytelane_cmp => dq_error_bytelane_cmp,
        error                => tg_compare_error_i,
        error_status         => error_status,
        cumlative_dq_lane_error => cumlative_dq_lane_error,
        cmd_wdt_err_o        => cmd_wdt_err_w,
        wr_wdt_err_o         => wr_wdt_err_w,
        rd_wdt_err_o         => rd_wdt_err_w,
        mem_pattern_init_done   => mem_pattern_init_done(0)
        );


  --*****************************************************************
  -- Default values are assigned to the debug inputs of the traffic
  -- generator
  --*****************************************************************
  vio_modify_enable(0)      <= '0';
  vio_data_mode_value       <= "0010";
  vio_addr_mode_value       <= "011";
  vio_instr_mode_value      <= "0010";
  vio_bl_mode_value         <= "10";
  vio_fixed_bl_value        <= "0000010000";
  vio_data_mask_gen(0)      <= '0';
  vio_pause_traffic(0)      <= '0';
  vio_fixed_instr_value     <= "001";
  dbg_clear_error(0)        <= '0';
  po_win_tg_rst             <= '0';
  vio_tg_rst(0)             <= '0';
  wdt_en_w(0)               <= '1';

  dbg_sel_pi_incdec(0)      <= '0';
  dbg_sel_po_incdec(0)      <= '0';
  dbg_pi_f_inc(0)           <= '0';
  dbg_pi_f_dec(0)           <= '0';
  dbg_po_f_inc(0)           <= '0';
  dbg_po_f_dec(0)           <= '0';
  dbg_po_f_stg23_sel(0)     <= '0';

      

end architecture arch_example_top;


