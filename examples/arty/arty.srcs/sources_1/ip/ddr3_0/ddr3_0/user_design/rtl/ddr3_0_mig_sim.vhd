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
--  /   /         Filename           : ddr3_0_mig.vhd
-- /___/   /\     Date Last Modified : $Date: 2011/06/02 08:35:03 $
-- \   \  /  \    Date Created       : Wed Feb 01 2012
--  \___\/\___\
--
-- Device           : 7 Series
-- Design Name      : DDR3 SDRAM
-- Purpose          :
--   Top-level  module. This module can be instantiated in the
--   system and interconnect as shown in user design wrapper file (user top module).
--   In addition to the memory controller, the module instantiates:
--     1. Clock generation/distribution, reset logic
--     2. IDELAY control block
--     3. Debug logic
-- Reference        :
-- Revision History :
--*****************************************************************************

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;


entity ddr3_0_mig is
  generic (
   --***************************************************************************
   -- The following parameters refer to width of various ports
   --***************************************************************************
   BANK_WIDTH            : integer := 3;
                                     -- # of memory Bank Address bits.
   CK_WIDTH              : integer := 1;
                                     -- # of CK/CK# outputs to memory.
   COL_WIDTH             : integer := 10;
                                     -- # of memory Column Address bits.
   CS_WIDTH              : integer := 1;
                                     -- # of unique CS outputs to memory.
   nCS_PER_RANK          : integer := 1;
                                     -- # of unique CS outputs per rank for phy
   CKE_WIDTH             : integer := 1;
                                     -- # of CKE outputs to memory.
   DATA_BUF_ADDR_WIDTH   : integer := 5;
   DQ_CNT_WIDTH          : integer := 4;
                                     -- = ceil(log2(DQ_WIDTH))
   DQ_PER_DM             : integer := 8;
   DM_WIDTH              : integer := 2;
                                     -- # of DM (data mask)
   DQ_WIDTH              : integer := 16;
                                     -- # of DQ (data)
   DQS_WIDTH             : integer := 2;
   DQS_CNT_WIDTH         : integer := 1;
                                     -- = ceil(log2(DQS_WIDTH))
   DRAM_WIDTH            : integer := 8;
                                     -- # of DQ per DQS
   ECC                   : string  := "OFF";
   ECC_TEST              : string  := "OFF";
   DATA_WIDTH            : integer := 16;
   PAYLOAD_WIDTH         : integer := 16;
   MEM_ADDR_ORDER        : string  := "BANK_ROW_COLUMN";
                                      --Possible Parameters
                                      --1.BANK_ROW_COLUMN : Address mapping is
                                      --                    in form of Bank Row Column.
                                      --2.ROW_BANK_COLUMN : Address mapping is
                                      --                    in the form of Row Bank Column.
                                      --3.TG_TEST : Scrambles Address bits
                                      --            for distributed Addressing.
   --nBANK_MACHS           : integer := 4;
   nBANK_MACHS           : integer := 4;
   RANKS                 : integer := 1;
                                     -- # of Ranks.
   ODT_WIDTH             : integer := 1;
                                     -- # of ODT outputs to memory.
   ROW_WIDTH             : integer := 14;
                                     -- # of memory Row Address bits.
   ADDR_WIDTH            : integer := 28;
                                     -- # = RANK_WIDTH + BANK_WIDTH
                                     --     + ROW_WIDTH + COL_WIDTH;
                                     -- Chip Select is always tied to low for
                                     -- single rank devices
   USE_CS_PORT          : integer := 1;
                                     -- # = 1, When Chip Select (CS#) output is enabled
                                     --   = 0, When Chip Select (CS#) output is disabled
                                     -- If CS_N disabled, user must connect
                                     -- DRAM CS_N input(s) to ground
   USE_DM_PORT           : integer := 1;
                                     -- # = 1, When Data Mask option is enabled
                                     --   = 0, When Data Mask option is disbaled
                                     -- When Data Mask option is disabled in
                                     -- MIG Controller Options page, the logic
                                     -- related to Data Mask should not get
                                     -- synthesized
   USE_ODT_PORT          : integer := 1;
                                     -- # = 1, When ODT output is enabled
                                     --   = 0, When ODT output is disabled
                                     -- Parameter configuration for Dynamic ODT support:
                                     -- USE_ODT_PORT = 0, RTT_NOM = "DISABLED", RTT_WR = "60/120".
                                     -- This configuration allows to save ODT pin mapping from FPGA.
                                     -- The user can tie the ODT input of DRAM to HIGH.
   PHY_CONTROL_MASTER_BANK : integer := 0;
                                     -- The bank index where master PHY_CONTROL resides,
                                     -- equal to the PLL residing bank
   MEM_DENSITY             : string  := "2Gb";
                                     -- Indicates the density of the Memory part
                                     -- Added for the sake of Vivado simulations
   MEM_SPEEDGRADE          : string  := "15E";
                                     -- Indicates the Speed grade of Memory Part
                                     -- Added for the sake of Vivado simulations
   MEM_DEVICE_WIDTH        : integer := 16;
                                     -- Indicates the device width of the Memory Part
                                     -- Added for the sake of Vivado simulations

   --***************************************************************************
   -- The following parameters are mode register settings
   --***************************************************************************
   AL                    : string  := "0";
                                     -- DDR3 SDRAM:
                                     -- Additive Latency (Mode Register 1).
                                     -- # = "0", "CL-1", "CL-2".
                                     -- DDR2 SDRAM:
                                     -- Additive Latency (Extended Mode Register).
   nAL                   : integer := 0;
                                     -- # Additive Latency in number of clock
                                     -- cycles.
   BURST_MODE            : string  := "8";
                                     -- DDR3 SDRAM:
                                     -- Burst Length (Mode Register 0).
                                     -- # = "8", "4", "OTF".
                                     -- DDR2 SDRAM:
                                     -- Burst Length (Mode Register).
                                     -- # = "8", "4".
   BURST_TYPE            : string  := "SEQ";
                                     -- DDR3 SDRAM: Burst Type (Mode Register 0).
                                     -- DDR2 SDRAM: Burst Type (Mode Register).
                                     -- # = "SEQ" - (Sequential),
                                     --   = "INT" - (Interleaved).
   CL                    : integer := 5;
                                     -- in number of clock cycles
                                     -- DDR3 SDRAM: CAS Latency (Mode Register 0).
                                     -- DDR2 SDRAM: CAS Latency (Mode Register).
   CWL                   : integer := 5;
                                     -- in number of clock cycles
                                     -- DDR3 SDRAM: CAS Write Latency (Mode Register 2).
                                     -- DDR2 SDRAM: Can be ignored
   OUTPUT_DRV            : string  := "LOW";
                                     -- Output Driver Impedance Control (Mode Register 1).
                                     -- # = "HIGH" - RZQ/7,
                                     --   = "LOW" - RZQ/6.
   RTT_NOM               : string  := "40";
                                     -- RTT_NOM (ODT) (Mode Register 1).
                                     --   = "120" - RZQ/2,
                                     --   = "60"  - RZQ/4,
                                     --   = "40"  - RZQ/6.
   RTT_WR                : string  := "OFF";
                                     -- RTT_WR (ODT) (Mode Register 2).
                                     -- # = "OFF" - Dynamic ODT off,
                                     --   = "120" - RZQ/2,
                                     --   = "60"  - RZQ/4,
   ADDR_CMD_MODE         : string  := "1T" ;
                                     -- # = "1T", "2T".
   REG_CTRL              : string  := "OFF";
                                     -- # = "ON" - RDIMMs,
                                     --   = "OFF" - Components, SODIMMs, UDIMMs.
   CA_MIRROR             : string  := "OFF";
                                     -- C/A mirror opt for DDR3 dual rank
   VDD_OP_VOLT           : string  := "135";
                                     -- # = "150" - 1.5V Vdd Memory part
                                     --   = "135" - 1.35V Vdd Memory part
   
   --***************************************************************************
   -- The following parameters are multiplier and divisor factors for PLLE2.
   -- Based on the selected design frequency these parameters vary.
   --***************************************************************************
   CLKIN_PERIOD          : integer := 6000;
                                     -- Input Clock Period
   CLKFBOUT_MULT         : integer := 8;
                                     -- write PLL VCO multiplier
   DIVCLK_DIVIDE         : integer := 1;
                                     -- write PLL VCO divisor
   CLKOUT0_PHASE         : real    := 0.0;
                                     -- Phase for PLL output clock (CLKOUT0)
   CLKOUT0_DIVIDE        : integer := 2;
                                     -- VCO output divisor for PLL output clock (CLKOUT0)
   CLKOUT1_DIVIDE        : integer := 4;
                                     -- VCO output divisor for PLL output clock (CLKOUT1)
   CLKOUT2_DIVIDE        : integer := 64;
                                     -- VCO output divisor for PLL output clock (CLKOUT2)
   CLKOUT3_DIVIDE        : integer := 16;
                                     -- VCO output divisor for PLL output clock (CLKOUT3)
   MMCM_VCO              : integer := 666;
                                     -- Max Freq (MHz) of MMCM VCO
   MMCM_MULT_F           : integer := 8;
                                     -- write MMCM VCO multiplier
   MMCM_DIVCLK_DIVIDE    : integer := 1;
                                     -- write MMCM VCO divisor

   --***************************************************************************
   -- Memory Timing Parameters. These parameters varies based on the selected
   -- memory part.
   --***************************************************************************
   tCKE                  : integer := 5625;
                                     -- memory tCKE paramter in pS
   tFAW                  : integer := 45000;
                                     -- memory tRAW paramter in pS.
   tPRDI                 : integer := 1000000;
                                     -- memory tPRDI paramter in pS.
   tRAS                  : integer := 36000;
                                     -- memory tRAS paramter in pS.
   tRCD                  : integer := 13500;
                                     -- memory tRCD paramter in pS.
   tREFI                 : integer := 7800000;
                                     -- memory tREFI paramter in pS.
   tRFC                  : integer := 160000;
                                     -- memory tRFC paramter in pS.
   tRP                   : integer := 13500;
                                     -- memory tRP paramter in pS.
   tRRD                  : integer := 7500;
                                     -- memory tRRD paramter in pS.
   tRTP                  : integer := 7500;
                                     -- memory tRTP paramter in pS.
   tWTR                  : integer := 7500;
                                     -- memory tWTR paramter in pS.
   tZQI                  : integer := 128000000;
                                     -- memory tZQI paramter in nS.
   tZQCS                 : integer := 64;--64;
                                     -- memory tZQCS paramter in clock cycles.

   --***************************************************************************
   -- Simulation parameters
   --***************************************************************************
   SIM_BYPASS_INIT_CAL   : string  := "FAST";
                                     -- # = "OFF" -  Complete memory init &
                                     --              calibration sequence
                                     -- # = "SKIP" - Not supported
                                     -- # = "FAST" - Complete memory init & use
                                     --              abbreviated calib sequence

   SIMULATION            : string  := "TRUE";
                                     -- Should be TRUE during design simulations and
                                     -- FALSE during implementations

   --***************************************************************************
   -- The following parameters varies based on the pin out entered in MIG GUI.
   -- Do not change any of these parameters directly by editing the RTL.
   -- Any changes required should be done through GUI and the design regenerated.
   --***************************************************************************
   BYTE_LANES_B0         : std_logic_vector(3 downto 0) := "1111";
                                     -- Byte lanes used in an IO column.
   BYTE_LANES_B1         : std_logic_vector(3 downto 0) := "0000";
                                     -- Byte lanes used in an IO column.
   BYTE_LANES_B2         : std_logic_vector(3 downto 0) := "0000";
                                     -- Byte lanes used in an IO column.
   BYTE_LANES_B3         : std_logic_vector(3 downto 0) := "0000";
                                     -- Byte lanes used in an IO column.
   BYTE_LANES_B4         : std_logic_vector(3 downto 0) := "0000";
                                     -- Byte lanes used in an IO column.
   DATA_CTL_B0           : std_logic_vector(3 downto 0) := "1100";
                                     -- Indicates Byte lane is data byte lane
                                     -- or control Byte lane. '1' in a bit
                                     -- position indicates a data byte lane and
                                     -- a '0' indicates a control byte lane
   DATA_CTL_B1           : std_logic_vector(3 downto 0) := "0000";
                                     -- Indicates Byte lane is data byte lane
                                     -- or control Byte lane. '1' in a bit
                                     -- position indicates a data byte lane and
                                     -- a '0' indicates a control byte lane
   DATA_CTL_B2           : std_logic_vector(3 downto 0) := "0000";
                                     -- Indicates Byte lane is data byte lane
                                     -- or control Byte lane. '1' in a bit
                                     -- position indicates a data byte lane and
                                     -- a '0' indicates a control byte lane
   DATA_CTL_B3           : std_logic_vector(3 downto 0) := "0000";
                                     -- Indicates Byte lane is data byte lane
                                     -- or control Byte lane. '1' in a bit
                                     -- position indicates a data byte lane and
                                     -- a '0' indicates a control byte lane
   DATA_CTL_B4           : std_logic_vector(3 downto 0) := "0000";
                                     -- Indicates Byte lane is data byte lane
                                     -- or control Byte lane. '1' in a bit
                                     -- position indicates a data byte lane and
                                     -- a '0' indicates a control byte lane
   PHY_0_BITLANES        : std_logic_vector(47 downto 0) := X"3FE3FEFFFBFF";
   PHY_1_BITLANES        : std_logic_vector(47 downto 0) := X"000000000000";
   PHY_2_BITLANES        : std_logic_vector(47 downto 0) := X"000000000000";

   -- control/address/data pin mapping parameters
   CK_BYTE_MAP
     : std_logic_vector(143 downto 0) := X"000000000000000000000000000000000000";
   ADDR_MAP
     : std_logic_vector(191 downto 0) := X"00000000000200400900700100500600301001201401101A";
   BANK_MAP   : std_logic_vector(35 downto 0) := X"01B017013";
   CAS_MAP    : std_logic_vector(11 downto 0) := X"015";
   CKE_ODT_BYTE_MAP : std_logic_vector(7 downto 0) := X"00";
   CKE_MAP    : std_logic_vector(95 downto 0) := X"000000000000000000000019";
   ODT_MAP    : std_logic_vector(95 downto 0) := X"000000000000000000000008";
   CS_MAP     : std_logic_vector(119 downto 0) := X"00000000000000000000000000000B";
   PARITY_MAP : std_logic_vector(11 downto 0) := X"000";
   RAS_MAP    : std_logic_vector(11 downto 0) := X"016";
   WE_MAP     : std_logic_vector(11 downto 0) := X"018";
   DQS_BYTE_MAP
     : std_logic_vector(143 downto 0) := X"000000000000000000000000000000000203";
   DATA0_MAP  : std_logic_vector(95 downto 0) := X"034032038035031037036033";
   DATA1_MAP  : std_logic_vector(95 downto 0) := X"023026022028025027021024";
   DATA2_MAP  : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA3_MAP  : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA4_MAP  : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA5_MAP  : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA6_MAP  : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA7_MAP  : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA8_MAP  : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA9_MAP  : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA10_MAP : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA11_MAP : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA12_MAP : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA13_MAP : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA14_MAP : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA15_MAP : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA16_MAP : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   DATA17_MAP : std_logic_vector(95 downto 0) := X"000000000000000000000000";
   MASK0_MAP  : std_logic_vector(107 downto 0) := X"000000000000000000000029039";
   MASK1_MAP  : std_logic_vector(107 downto 0) := X"000000000000000000000000000";

   SLOT_0_CONFIG         : std_logic_vector(7 downto 0) := "00000001";
                                     -- Mapping of Ranks.
   SLOT_1_CONFIG         : std_logic_vector(7 downto 0) := "00000000";
                                     -- Mapping of Ranks.

   --***************************************************************************
   -- IODELAY and PHY related parameters
   --***************************************************************************
   IBUF_LPWR_MODE        : string  := "OFF";
                                     -- to phy_top
   DATA_IO_IDLE_PWRDWN   : string  := "ON";
                                     -- # = "ON", "OFF"
   BANK_TYPE             : string  := "HR_IO";
                                     -- # = "HP_IO", "HPL_IO", "HR_IO", "HRL_IO"
   DATA_IO_PRIM_TYPE     : string  := "HR_LP";
                                     -- # = "HP_LP", "HR_LP", "DEFAULT"
   CKE_ODT_AUX           : string  := "FALSE";
   USER_REFRESH          : string  := "OFF";
   WRLVL                 : string  := "ON";
                                     -- # = "ON" - DDR3 SDRAM
                                     --   = "OFF" - DDR2 SDRAM.
   ORDERING              : string  := "NORM";
                                     -- # = "NORM", "STRICT", "RELAXED".
   CALIB_ROW_ADD         : std_logic_vector(15 downto 0) := X"0000";
                                     -- Calibration row address will be used for
                                     -- calibration read and write operations
   CALIB_COL_ADD         : std_logic_vector(11 downto 0) := X"000";
                                     -- Calibration column address will be used for
                                     -- calibration read and write operations
   CALIB_BA_ADD          : std_logic_vector(2 downto 0) := "000";
                                     -- Calibration bank address will be used for
                                     -- calibration read and write operations
   TCQ                   : integer := 100;
   IDELAY_ADJ            : string  := "OFF";
   FINE_PER_BIT          : string  := "OFF";
   CENTER_COMP_MODE      : string  := "OFF";
   PI_VAL_ADJ            : string  := "OFF";
      IODELAY_GRP0          : string  := "DDR3_0_IODELAY_MIG0";
                                     -- It is associated to a set of IODELAYs with
                                     -- an IDELAYCTRL that have same IODELAY CONTROLLER
                                     -- clock frequency (200MHz).
   IODELAY_GRP1          : string  := "DDR3_0_IODELAY_MIG1";
                                     -- It is associated to a set of IODELAYs with
                                     -- an IDELAYCTRL that have same IODELAY CONTROLLER
                                     -- clock frequency (300MHz/400MHz).
   SYSCLK_TYPE           : string  := "NO_BUFFER";
                                     -- System clock type DIFFERENTIAL, SINGLE_ENDED,
                                     -- NO_BUFFER
   REFCLK_TYPE           : string  := "NO_BUFFER";
                                     -- Reference clock type DIFFERENTIAL, SINGLE_ENDED
                                     -- NO_BUFFER, USE_SYSTEM_CLOCK
   SYS_RST_PORT          : string  := "FALSE";
                                     -- "TRUE" - if pin is selected for sys_rst
                                     --          and IBUF will be instantiated.
                                     -- "FALSE" - if pin is not selected for sys_rst

   FPGA_SPEED_GRADE      : integer := 1;
                                   -- FPGA speed grade
      
   CMD_PIPE_PLUS1        : string  := "ON";
                                     -- add pipeline stage between MC and PHY
   
   DRAM_TYPE             : string  := "DDR3";
   CAL_WIDTH             : string  := "HALF";
   STARVE_LIMIT          : integer := 2;
                                     -- # = 2,3,4.
   REF_CLK_MMCM_IODELAY_CTRL : string  := "FALSE";

   --***************************************************************************
   -- Referece clock frequency parameters
   --***************************************************************************
   REFCLK_FREQ           : real    := 200.0;
                                     -- IODELAYCTRL reference clock frequency
   DIFF_TERM_REFCLK      : string  := "TRUE";
                                     -- Differential Termination for idelay
                                     -- reference clock input pins
   --***************************************************************************
   -- System clock frequency parameters
   --***************************************************************************
   tCK                   : integer := 3000;
                                     -- memory tCK paramter.
                                     -- # = Clock Period in pS.
   nCK_PER_CLK           : integer := 4;
                                     -- # of memory CKs per fabric CLK
   DIFF_TERM_SYSCLK      : string  := "TRUE";
                                     -- Differential Termination for System
                                     -- clock input pins

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
   --***************************************************************************
   -- FPGA Voltage Type parameter
   --***************************************************************************
   FPGA_VOLT_TYPE           : string := "N";
                                     -- # = "L", "N". When FPGA VccINT is 0.9v,
                                     -- the value is "L", else it is "N"
      
   RST_ACT_LOW           : integer := 1
                                     -- =1 for active low reset,
                                     -- =0 for active high.
   );
  port (

   -- Inouts
   ddr3_dq                        : inout std_logic_vector(DQ_WIDTH-1 downto 0);
   ddr3_dqs_p                     : inout std_logic_vector(DQS_WIDTH-1 downto 0);
   ddr3_dqs_n                     : inout std_logic_vector(DQS_WIDTH-1 downto 0);

   -- Outputs
   ddr3_addr                      : out   std_logic_vector(ROW_WIDTH-1 downto 0);
   ddr3_ba                        : out   std_logic_vector(BANK_WIDTH-1 downto 0);
   ddr3_ras_n                     : out   std_logic;
   ddr3_cas_n                     : out   std_logic;
   ddr3_we_n                      : out   std_logic;
   ddr3_reset_n                   : out   std_logic;
   ddr3_ck_p                      : out   std_logic_vector(CK_WIDTH-1 downto 0);
   ddr3_ck_n                      : out   std_logic_vector(CK_WIDTH-1 downto 0);
   ddr3_cke                       : out   std_logic_vector(CKE_WIDTH-1 downto 0);
   ddr3_cs_n                      : out   std_logic_vector((CS_WIDTH*nCS_PER_RANK)-1 downto 0);
   ddr3_dm                        : out   std_logic_vector(DM_WIDTH-1 downto 0);
   ddr3_odt                       : out   std_logic_vector(ODT_WIDTH-1 downto 0);

   -- Inputs
   -- Single-ended system clock
   sys_clk_i                      : in    std_logic;
   -- Single-ended iodelayctrl clk (reference clock)
   clk_ref_i                                : in    std_logic;
   -- user interface signals
   app_addr             : in    std_logic_vector(ADDR_WIDTH-1 downto 0);
   app_cmd              : in    std_logic_vector(2 downto 0);
   app_en               : in    std_logic;
   app_wdf_data         : in    std_logic_vector((nCK_PER_CLK*2*PAYLOAD_WIDTH)-1 downto 0);
   app_wdf_end          : in    std_logic;
   app_wdf_mask         : in    std_logic_vector(((nCK_PER_CLK*2*PAYLOAD_WIDTH)/8)-1 downto 0)  ;
   app_wdf_wren         : in    std_logic;
   app_rd_data          : out   std_logic_vector((nCK_PER_CLK*2*PAYLOAD_WIDTH)-1 downto 0);
   app_rd_data_end      : out   std_logic;
   app_rd_data_valid    : out   std_logic;
   app_rdy              : out   std_logic;
   app_wdf_rdy          : out   std_logic;
   app_sr_req           : in    std_logic;
   app_ref_req          : in    std_logic;
   app_zq_req           : in    std_logic;
   app_sr_active        : out   std_logic;
   app_ref_ack          : out   std_logic;
   app_zq_ack           : out   std_logic;
   ui_clk               : out   std_logic;
   ui_clk_sync_rst      : out   std_logic;
   
      
   init_calib_complete  : out std_logic;
   
   device_temp                    : out std_logic_vector(11 downto 0);
      

   -- System reset - Default polarity of sys_rst pin is Active Low.
   -- System reset polarity will change based on the option 
   -- selected in GUI.
      sys_rst                     : in    std_logic
   );

end entity ddr3_0_mig;

architecture arch_ddr3_0_mig of ddr3_0_mig is


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
  end function;
  function ECCWIDTH return integer is
  begin
    if(ECC = "OFF") then
      return 0;
    else
      if(DATA_WIDTH <= 4) then
        return 4;
      elsif(DATA_WIDTH <= 10) then
        return 5;
      elsif(DATA_WIDTH <= 26) then
        return 6;
      elsif(DATA_WIDTH <= 57) then
        return 7;
      elsif(DATA_WIDTH <= 120) then
        return 8;
      elsif(DATA_WIDTH <= 247) then
        return 9;
      else
        return 10;
      end if;
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

  constant TAPSPERKCLK : integer := (56*MMCM_MULT_F)/nCK_PER_CLK;

  function TEMP_MON return string is
  begin
    if(SIMULATION = "TRUE") then
      return "ON";
    else
      return "OFF";
    end if;
  end function;
      
      


  constant BM_CNT_WIDTH : integer := clogb2(nBANK_MACHS);
  constant ECC_WIDTH             : integer := ECCWIDTH;
  constant DATA_BUF_OFFSET_WIDTH : integer := 1;
  constant MC_ERR_ADDR_WIDTH     : integer := XWIDTH + BANK_WIDTH + ROW_WIDTH
                                          + COL_WIDTH + DATA_BUF_OFFSET_WIDTH;
  constant APP_DATA_WIDTH        : integer := 2 * nCK_PER_CLK * PAYLOAD_WIDTH;
  constant APP_MASK_WIDTH        : integer := APP_DATA_WIDTH / 8;
  constant TEMP_MON_EN           : string  := TEMP_MON;
                                   -- Enable or disable the temp monitor module
  constant tTEMPSAMPLE : integer := 10000000; -- sample every 10 us
  constant XADC_CLK_PERIOD : integer := 5000; -- Use 200 MHz IODELAYCTRL clock
      
      

-- Start of User Design wrapper top component

  component ddr3_0
    port(
      sys_rst             : in std_logic
      );
  end component ddr3_0;

-- End of User Design wrapper top component



  component mig_7series_v4_2_iodelay_ctrl is
    generic(
      TCQ              : integer;
      IODELAY_GRP0     : string;
      IODELAY_GRP1     : string;
      REFCLK_TYPE      : string;
      SYSCLK_TYPE      : string;
      SYS_RST_PORT     : string;
      RST_ACT_LOW      : integer;
      DIFF_TERM_REFCLK : string;
      FPGA_SPEED_GRADE : integer;
      REF_CLK_MMCM_IODELAY_CTRL : string
      );
    port (
      clk_ref_p        : in  std_logic;
      clk_ref_n        : in  std_logic;
      clk_ref_i        : in  std_logic;
      sys_rst          : in  std_logic;
      clk_ref          : out std_logic_vector(1 downto 0);
      sys_rst_o        : out std_logic;
      iodelay_ctrl_rdy : out std_logic_vector(1 downto 0)
   );
  end component mig_7series_v4_2_iodelay_ctrl;

  component mig_7series_v4_2_clk_ibuf is
    generic (
      SYSCLK_TYPE      : string;
      DIFF_TERM_SYSCLK : string
      );
    port (
      sys_clk_p   : in  std_logic;
      sys_clk_n   : in  std_logic;
      sys_clk_i   : in  std_logic;
      mmcm_clk    : out std_logic
      );
  end component mig_7series_v4_2_clk_ibuf;

  component mig_7series_v4_2_infrastructure is
    generic (
      SIMULATION      : string := "TRUE";
      TCQ             : integer;
      CLKIN_PERIOD    : integer;
      nCK_PER_CLK     : integer;
      SYSCLK_TYPE     : string;
      UI_EXTRA_CLOCKS : string := "FALSE";
      CLKFBOUT_MULT   : integer;
      DIVCLK_DIVIDE   : integer;
      CLKOUT0_PHASE   : real;
      CLKOUT0_DIVIDE  : integer;
      CLKOUT1_DIVIDE  : integer;
      CLKOUT2_DIVIDE  : integer;
      CLKOUT3_DIVIDE  : integer;
      MMCM_VCO            : integer;
      MMCM_MULT_F         : integer;
      MMCM_DIVCLK_DIVIDE  : integer;
      MMCM_CLKOUT0_EN     : string := "FALSE";
      MMCM_CLKOUT1_EN     : string := "FALSE";
      MMCM_CLKOUT2_EN     : string := "FALSE";
      MMCM_CLKOUT3_EN     : string := "FALSE";
      MMCM_CLKOUT4_EN     : string := "FALSE";
      MMCM_CLKOUT0_DIVIDE : integer := 1;
      MMCM_CLKOUT1_DIVIDE : integer := 1;
      MMCM_CLKOUT2_DIVIDE : integer := 1;
      MMCM_CLKOUT3_DIVIDE : integer := 1;
      MMCM_CLKOUT4_DIVIDE : integer := 1;
      RST_ACT_LOW         : integer;
      tCK                 : integer;
      MEM_TYPE            : string
      );
    port (
      mmcm_clk          : in  std_logic;
      sys_rst           : in  std_logic;
      iodelay_ctrl_rdy  : in  std_logic_vector(1 downto 0);
      psen              : in  std_logic;
      psincdec          : in  std_logic;
      clk               : out std_logic;
      clk_div2          : out std_logic;
      rst_div2          : out std_logic;
      mem_refclk        : out std_logic;
      freq_refclk       : out std_logic;
      sync_pulse        : out std_logic;
      mmcm_ps_clk       : out std_logic;
      poc_sample_pd      : out std_logic;
      iddr_rst          : out std_logic;
      psdone            : out std_logic;
--      auxout_clk        : out std_logic;
      ui_addn_clk_0     : out std_logic;
      ui_addn_clk_1     : out std_logic;
      ui_addn_clk_2     : out std_logic;
      ui_addn_clk_3     : out std_logic;
      ui_addn_clk_4     : out std_logic;
      pll_locked        : out std_logic;
      mmcm_locked       : out std_logic;
      rstdiv0           : out std_logic;
      rst_phaser_ref    : out std_logic;
      ref_dll_lock      : in  std_logic
   );
  end component mig_7series_v4_2_infrastructure;
      
  component mig_7series_v4_2_tempmon is
    generic (
      TCQ              : integer;
      TEMP_MON_CONTROL : string;
      XADC_CLK_PERIOD  : integer;
      tTEMPSAMPLE      : integer
      );
    port (
      clk            : in  std_logic;
      xadc_clk       : in  std_logic;
      rst            : in  std_logic;
      device_temp_i  : in  std_logic_vector(11 downto 0);
      device_temp    : out std_logic_vector(11 downto 0)
      );
  end component mig_7series_v4_2_tempmon;

  component mig_7series_v4_2_memc_ui_top_std is
    generic (
      TCQ                   : integer;
      DDR3_VDD_OP_VOLT      : string := "135";
      PAYLOAD_WIDTH         : integer;
      ADDR_CMD_MODE         : string;
      AL                    : string;
      BANK_WIDTH            : integer;
      BM_CNT_WIDTH          : integer;
      BURST_MODE            : string;
      BURST_TYPE            : string;
      CA_MIRROR             : string;
      CK_WIDTH              : integer;
      CL                    : integer;
      COL_WIDTH             : integer;
      CMD_PIPE_PLUS1        : string;
      CS_WIDTH              : integer;
      CKE_WIDTH             : integer;
      CWL                   : integer;
      DATA_WIDTH            : integer;
      DATA_BUF_ADDR_WIDTH   : integer;
      DATA_BUF_OFFSET_WIDTH : integer := 1;
      DDR2_DQSN_ENABLE      : string := "YES";
      DM_WIDTH              : integer;
      DQ_CNT_WIDTH          : integer;
      DQ_WIDTH              : integer;
      DQS_CNT_WIDTH         : integer;
      DQS_WIDTH             : integer;
      DRAM_TYPE             : string;
      DRAM_WIDTH            : integer;
      ECC                   : string;
      ECC_WIDTH             : integer;
      ECC_TEST              : string;
      MC_ERR_ADDR_WIDTH     : integer;
      MASTER_PHY_CTL        : integer;
      nAL                   : integer;
      nBANK_MACHS           : integer;
      nCK_PER_CLK           : integer;
      nCS_PER_RANK          : integer;
      ORDERING              : string;
      IBUF_LPWR_MODE        : string;
      BANK_TYPE             : string;
      DATA_IO_PRIM_TYPE     : string;
      DATA_IO_IDLE_PWRDWN   : string;
      IODELAY_GRP0          : string;
      IODELAY_GRP1          : string;
      FPGA_SPEED_GRADE      : integer;
      OUTPUT_DRV            : string;
      REG_CTRL              : string;
      RTT_NOM               : string;
      RTT_WR                : string;
      STARVE_LIMIT          : integer;
      tCK                   : integer;
      tCKE                  : integer;
      tFAW                  : integer;
      tPRDI                 : integer;
      tRAS                  : integer;
      tRCD                  : integer;
      tREFI                 : integer;
      tRFC                  : integer;
      tRP                   : integer;
      tRRD                  : integer;
      tRTP                  : integer;
      tWTR                  : integer;
      tZQI                  : integer;
      tZQCS                 : integer;
      USER_REFRESH          : string;
      TEMP_MON_EN           : string;
      WRLVL                 : string;
      DEBUG_PORT            : string;
      CAL_WIDTH             : string;
      RANK_WIDTH            : integer;
      RANKS                 : integer;
      ODT_WIDTH             : integer;
      ROW_WIDTH             : integer;
      ADDR_WIDTH            : integer;
      APP_MASK_WIDTH        : integer;
      APP_DATA_WIDTH        : integer;
      BYTE_LANES_B0         : std_logic_vector(3 downto 0);
      BYTE_LANES_B1         : std_logic_vector(3 downto 0);
      BYTE_LANES_B2         : std_logic_vector(3 downto 0);
      BYTE_LANES_B3         : std_logic_vector(3 downto 0);
      BYTE_LANES_B4         : std_logic_vector(3 downto 0);
      DATA_CTL_B0           : std_logic_vector(3 downto 0);
      DATA_CTL_B1           : std_logic_vector(3 downto 0);
      DATA_CTL_B2           : std_logic_vector(3 downto 0);
      DATA_CTL_B3           : std_logic_vector(3 downto 0);
      DATA_CTL_B4           : std_logic_vector(3 downto 0);
      PHY_0_BITLANES        : std_logic_vector(47 downto 0);
      PHY_1_BITLANES        : std_logic_vector(47 downto 0);
      PHY_2_BITLANES        : std_logic_vector(47 downto 0);
      CK_BYTE_MAP           : std_logic_vector(143 downto 0);
      ADDR_MAP              : std_logic_vector(191 downto 0);
      BANK_MAP              : std_logic_vector(35 downto 0);
      CAS_MAP               : std_logic_vector(11 downto 0);
      CKE_ODT_BYTE_MAP      : std_logic_vector(7 downto 0);
      CKE_MAP               : std_logic_vector(95 downto 0);
      ODT_MAP               : std_logic_vector(95 downto 0);
      CKE_ODT_AUX           : string;
      CS_MAP                : std_logic_vector(119 downto 0);
      PARITY_MAP            : std_logic_vector(11 downto 0);
      RAS_MAP               : std_logic_vector(11 downto 0);
      WE_MAP                : std_logic_vector(11 downto 0);
      DQS_BYTE_MAP          : std_logic_vector(143 downto 0);
      DATA0_MAP             : std_logic_vector(95 downto 0);
      DATA1_MAP             : std_logic_vector(95 downto 0);
      DATA2_MAP             : std_logic_vector(95 downto 0);
      DATA3_MAP             : std_logic_vector(95 downto 0);
      DATA4_MAP             : std_logic_vector(95 downto 0);
      DATA5_MAP             : std_logic_vector(95 downto 0);
      DATA6_MAP             : std_logic_vector(95 downto 0);
      DATA7_MAP             : std_logic_vector(95 downto 0);
      DATA8_MAP             : std_logic_vector(95 downto 0);
      DATA9_MAP             : std_logic_vector(95 downto 0);
      DATA10_MAP            : std_logic_vector(95 downto 0);
      DATA11_MAP            : std_logic_vector(95 downto 0);
      DATA12_MAP            : std_logic_vector(95 downto 0);
      DATA13_MAP            : std_logic_vector(95 downto 0);
      DATA14_MAP            : std_logic_vector(95 downto 0);
      DATA15_MAP            : std_logic_vector(95 downto 0);
      DATA16_MAP            : std_logic_vector(95 downto 0);
      DATA17_MAP            : std_logic_vector(95 downto 0);
      MASK0_MAP             : std_logic_vector(107 downto 0);
      MASK1_MAP             : std_logic_vector(107 downto 0);
      SLOT_0_CONFIG         : std_logic_vector(7 downto 0);
      SLOT_1_CONFIG         : std_logic_vector(7 downto 0);
      MEM_ADDR_ORDER        : string;
      CALIB_ROW_ADD         : std_logic_vector(15 downto 0);
      CALIB_COL_ADD         : std_logic_vector(11 downto 0);
      CALIB_BA_ADD          : std_logic_vector(2 downto 0);
      SIM_BYPASS_INIT_CAL   : string;
      REFCLK_FREQ           : real;
      USE_CS_PORT           : integer;
      USE_DM_PORT           : integer;
      USE_ODT_PORT          : integer;
      IDELAY_ADJ            : string;
      FINE_PER_BIT          : string;
      CENTER_COMP_MODE      : string;
      PI_VAL_ADJ            : string;
      TAPSPERKCLK           : integer;
      SKIP_CALIB            : string;
      FPGA_VOLT_TYPE        : string
      );
    port (
      clk              : in    std_logic;
      clk_div2         : in    std_logic;
      rst_div2         : in    std_logic;
      clk_ref          : in    std_logic_vector(1 downto 0);
      mem_refclk       : in    std_logic;
      freq_refclk      : in    std_logic;
      pll_lock         : in    std_logic;
      sync_pulse       : in    std_logic;
      mmcm_ps_clk      : in    std_logic;
      poc_sample_pd    : in    std_logic;
      rst              : in    std_logic;

      ddr_dq       : inout std_logic_vector(DQ_WIDTH-1 downto 0);
      ddr_dqs_n    : inout std_logic_vector(DQS_WIDTH-1 downto 0);
      ddr_dqs      : inout std_logic_vector(DQS_WIDTH-1 downto 0);
      ddr_addr     : out   std_logic_vector(ROW_WIDTH-1 downto 0);
      ddr_ba       : out   std_logic_vector(BANK_WIDTH-1 downto 0);
      ddr_cas_n    : out   std_logic;
      ddr_ck_n     : out   std_logic_vector(CK_WIDTH-1 downto 0);
      ddr_ck       : out   std_logic_vector(CK_WIDTH-1 downto 0);
      ddr_cke      : out   std_logic_vector(CKE_WIDTH-1 downto 0);
      ddr_cs_n     : out   std_logic_vector((CS_WIDTH*nCS_PER_RANK)-1 downto 0);
      ddr_dm       : out   std_logic_vector(DM_WIDTH-1 downto 0);
      ddr_odt      : out   std_logic_vector(ODT_WIDTH-1 downto 0);
      ddr_ras_n    : out   std_logic;
      ddr_reset_n  : out   std_logic;
      ddr_parity   : out   std_logic;
      ddr_we_n     : out   std_logic;

      bank_mach_next                   : out   std_logic_vector(BM_CNT_WIDTH-1 downto 0);

      app_addr                         : in    std_logic_vector(ADDR_WIDTH-1 downto 0);
      app_cmd                          : in    std_logic_vector(2 downto 0);
      app_en                           : in    std_logic;
      app_hi_pri                       : in    std_logic;
      app_wdf_data                     : in    std_logic_vector((nCK_PER_CLK*2*PAYLOAD_WIDTH)-1 downto 0);
      app_wdf_end                      : in    std_logic;
      app_wdf_mask                     : in    std_logic_vector(((nCK_PER_CLK*2*PAYLOAD_WIDTH)/8)-1 downto 0);
      app_wdf_wren                     : in    std_logic;
      app_correct_en_i                 : in    std_logic;
      app_raw_not_ecc                  : in    std_logic_vector((2*nCK_PER_CLK)-1 downto 0);
      app_ecc_multiple_err             : out   std_logic_vector((2*nCK_PER_CLK)-1 downto 0);
      app_ecc_single_err               : out   std_logic_vector((2*nCK_PER_CLK)-1 downto 0);
      app_rd_data                      : out   std_logic_vector((nCK_PER_CLK*2*PAYLOAD_WIDTH)-1 downto 0);
      app_rd_data_end                  : out   std_logic;
      app_rd_data_valid                : out   std_logic;
      app_rdy                          : out   std_logic;
      app_wdf_rdy                      : out   std_logic;
      app_sr_req                       : in    std_logic;
      app_sr_active                    : out   std_logic;
      app_ref_req                      : in    std_logic;
      app_ref_ack                      : out   std_logic;
      app_zq_req                       : in    std_logic;
      app_zq_ack                       : out   std_logic;

      calib_tap_req                    : out std_logic;
      calib_tap_addr                   : in std_logic_vector(6 downto 0);
      calib_tap_load                   : in std_logic;
      calib_tap_val                    : in std_logic_vector(7 downto 0);
      calib_tap_load_done              : in std_logic;

      device_temp                      : in    std_logic_vector(11 downto 0);

      psen                             : out std_logic;
      psincdec                         : out std_logic;
      psdone                           : in  std_logic;

      dbg_idel_down_all                : in  std_logic;
      dbg_idel_down_cpt                : in  std_logic;
      dbg_idel_up_all                  : in  std_logic;
      dbg_idel_up_cpt                  : in  std_logic;
      dbg_sel_all_idel_cpt             : in  std_logic;
      dbg_sel_idel_cpt                 : in  std_logic_vector(DQS_CNT_WIDTH-1 downto 0);
      dbg_cpt_first_edge_cnt           : out std_logic_vector((6*DQS_WIDTH*RANKS)-1 downto 0);
      dbg_cpt_second_edge_cnt          : out std_logic_vector((6*DQS_WIDTH*RANKS)-1 downto 0);
      dbg_rd_data_edge_detect          : out std_logic_vector(DQS_WIDTH-1 downto 0);
      dbg_rddata                       : out std_logic_vector((2*nCK_PER_CLK*DQ_WIDTH)-1 downto 0);
      dbg_rdlvl_done                   : out std_logic_vector(1 downto 0);
      dbg_rdlvl_err                    : out std_logic_vector(1 downto 0);
      dbg_rdlvl_start                  : out std_logic_vector(1 downto 0);
      dbg_tap_cnt_during_wrlvl         : out std_logic_vector(5 downto 0);
      dbg_wl_edge_detect_valid         : out std_logic;
      dbg_wrlvl_done                   : out std_logic;
      dbg_wrlvl_err                    : out std_logic;
      dbg_wrlvl_start                  : out std_logic;
      dbg_final_po_fine_tap_cnt        : out std_logic_vector((6*DQS_WIDTH)-1 downto 0);
      dbg_final_po_coarse_tap_cnt      : out std_logic_vector((3*DQS_WIDTH)-1 downto 0);
      init_calib_complete              : out std_logic;
      dbg_sel_pi_incdec                : in  std_logic;
      dbg_sel_po_incdec                : in  std_logic;
      dbg_byte_sel                     : in  std_logic_vector(DQS_CNT_WIDTH downto 0);
      dbg_pi_f_inc                     : in  std_logic;
      dbg_pi_f_dec                     : in  std_logic;
      dbg_po_f_inc                     : in  std_logic;
      dbg_po_f_stg23_sel               : in  std_logic;
      dbg_po_f_dec                     : in  std_logic;
      dbg_cpt_tap_cnt                  : out std_logic_vector((6*DQS_WIDTH*RANKS)-1 downto 0);
      dbg_dq_idelay_tap_cnt            : out std_logic_vector((5*DQS_WIDTH*RANKS)-1 downto 0);
      dbg_rddata_valid                 : out std_logic;
      dbg_wrlvl_fine_tap_cnt           : out std_logic_vector((6*DQS_WIDTH)-1 downto 0);
      dbg_wrlvl_coarse_tap_cnt         : out std_logic_vector((3*DQS_WIDTH)-1 downto 0);
      rst_phaser_ref                   : in  std_logic;
      ref_dll_lock                     : out std_logic;
      iddr_rst                         : in  std_logic;
      dbg_rd_data_offset               : out std_logic_vector((6*RANKS)-1 downto 0);
      dbg_calib_top                    : out std_logic_vector(255 downto 0);
      dbg_phy_wrlvl                    : out std_logic_vector(255 downto 0);
      dbg_phy_rdlvl                    : out std_logic_vector(255 downto 0);
      dbg_phy_wrcal                    : out std_logic_vector(99 downto 0);
      dbg_phy_init                     : out std_logic_vector(255 downto 0);
      dbg_prbs_rdlvl                   : out std_logic_vector(255 downto 0);
      dbg_dqs_found_cal                : out std_logic_vector(255 downto 0);
      dbg_pi_counter_read_val          : out std_logic_vector(5 downto 0);
      dbg_po_counter_read_val          : out std_logic_vector(8 downto 0);
      dbg_pi_phaselock_start           : out std_logic;
      dbg_pi_phaselocked_done          : out std_logic;
      dbg_pi_phaselock_err             : out std_logic;
      dbg_pi_dqsfound_start            : out std_logic;
      dbg_pi_dqsfound_done             : out std_logic;
      dbg_pi_dqsfound_err              : out std_logic;
      dbg_wrcal_start                  : out std_logic;
      dbg_wrcal_done                   : out std_logic;
      dbg_wrcal_err                    : out std_logic;
      dbg_pi_dqs_found_lanes_phy4lanes : out std_logic_vector(11 downto 0);
      dbg_pi_phase_locked_phy4lanes    : out std_logic_vector(11 downto 0);
      dbg_calib_rd_data_offset_1       : out std_logic_vector((6*RANKS)-1 downto 0);
      dbg_calib_rd_data_offset_2       : out std_logic_vector((6*RANKS)-1 downto 0);
      dbg_data_offset                  : out std_logic_vector(5 downto 0);
      dbg_data_offset_1                : out std_logic_vector(5 downto 0);
      dbg_data_offset_2                : out std_logic_vector(5 downto 0);
      dbg_oclkdelay_calib_start        : out std_logic;
      dbg_oclkdelay_calib_done         : out std_logic;
      dbg_phy_oclkdelay_cal            : out std_logic_vector(255 downto 0);
      dbg_oclkdelay_rd_data            : out std_logic_vector((DRAM_WIDTH*16)-1 downto 0);
      dbg_prbs_final_dqs_tap_cnt_r     : out std_logic_vector((6*DQS_WIDTH*RANKS)-1 downto 0);
      dbg_prbs_first_edge_taps         : out std_logic_vector((6*DQS_WIDTH*RANKS)-1 downto 0);
      dbg_prbs_second_edge_taps        : out std_logic_vector((6*DQS_WIDTH*RANKS)-1 downto 0);
      dbg_poc                          : out std_logic_vector (1023 downto 0)
   );
  end component mig_7series_v4_2_memc_ui_top_std;
      

  -- Signal declarations
      
  signal bank_mach_next              : std_logic_vector(BM_CNT_WIDTH-1 downto 0);
  signal clk                         : std_logic;
  signal clk_ref              : std_logic_vector(1 downto 0);
  signal iodelay_ctrl_rdy     : std_logic_vector(1 downto 0);
  signal clk_ref_in           : std_logic;
  signal sys_rst_o            : std_logic;
  signal clk_div2                    : std_logic;
  signal rst_div2                    : std_logic;
  signal freq_refclk                 : std_logic;
  signal mem_refclk                  : std_logic;
  signal pll_locked                  : std_logic;
  signal sync_pulse                  : std_logic;
  signal mmcm_ps_clk                 : std_logic;
  signal poc_sample_pd                : std_logic;
  signal psen                        : std_logic;
  signal psincdec                    : std_logic;
  signal psdone                      : std_logic;
  signal iddr_rst                    : std_logic;
  signal ref_dll_lock                : std_logic;
  signal rst_phaser_ref              : std_logic;

  signal rst                         : std_logic;
  
  signal app_ecc_multiple_err        : std_logic_vector((2*nCK_PER_CLK)-1 downto 0);
  signal app_ecc_single_err          : std_logic_vector((2*nCK_PER_CLK)-1 downto 0);
  signal ddr3_parity          : std_logic;
      
  signal init_calib_complete_i       : std_logic;

  signal sys_clk_p       : std_logic;
  signal sys_clk_n          : std_logic;
  signal mmcm_clk           : std_logic;
  signal clk_ref_p               : std_logic;
  signal clk_ref_n               : std_logic;
  signal device_temp_s         : std_logic_vector(11 downto 0);
  signal device_temp_i           : std_logic_vector(11 downto 0);

  -- Debug port signals
  signal dbg_idel_down_all           : std_logic;
  signal dbg_idel_down_cpt           : std_logic;
  signal dbg_idel_up_all             : std_logic;
  signal dbg_idel_up_cpt             : std_logic;
  signal dbg_sel_all_idel_cpt        : std_logic;
  signal dbg_sel_idel_cpt            : std_logic_vector(DQS_CNT_WIDTH-1 downto 0);
  signal dbg_po_f_stg23_sel          : std_logic;
  signal dbg_sel_pi_incdec           : std_logic;
  signal dbg_sel_po_incdec           : std_logic;
  signal dbg_byte_sel                : std_logic_vector(DQS_CNT_WIDTH downto 0);
  signal dbg_pi_f_inc                : std_logic;
  signal dbg_po_f_inc                : std_logic;
  signal dbg_pi_f_dec                : std_logic;
  signal dbg_po_f_dec                : std_logic;
  signal dbg_pi_counter_read_val     : std_logic_vector(5 downto 0);
  signal dbg_po_counter_read_val     : std_logic_vector(8 downto 0);
  signal dbg_prbs_final_dqs_tap_cnt_r : std_logic_vector(11 downto 0);
  signal dbg_prbs_first_edge_taps     : std_logic_vector(11 downto 0);
  signal dbg_prbs_second_edge_taps    : std_logic_vector(11 downto 0);
  signal dbg_cpt_tap_cnt             : std_logic_vector((6*DQS_WIDTH*RANKS)-1 downto 0);
  signal dbg_dq_idelay_tap_cnt       : std_logic_vector((5*DQS_WIDTH*RANKS)-1 downto 0);
  signal dbg_calib_top               : std_logic_vector(255 downto 0);
  signal dbg_cpt_first_edge_cnt      : std_logic_vector((6*DQS_WIDTH*RANKS)-1 downto 0);
  signal dbg_cpt_second_edge_cnt     : std_logic_vector((6*DQS_WIDTH*RANKS)-1 downto 0);
  signal dbg_rd_data_offset          : std_logic_vector((6*RANKS)-1 downto 0);
  signal dbg_phy_rdlvl               : std_logic_vector(255 downto 0);
  signal dbg_phy_wrcal               : std_logic_vector(99 downto 0);
  signal dbg_final_po_fine_tap_cnt   : std_logic_vector((6*DQS_WIDTH)-1 downto 0);
  signal dbg_final_po_coarse_tap_cnt : std_logic_vector((3*DQS_WIDTH)-1 downto 0);
  signal dbg_phy_wrlvl               : std_logic_vector(255 downto 0);
  signal dbg_phy_init                : std_logic_vector(255 downto 0);
  signal dbg_prbs_rdlvl              : std_logic_vector(255 downto 0);
  signal dbg_dqs_found_cal           : std_logic_vector(255 downto 0);
  signal dbg_pi_phaselock_start      : std_logic;
  signal dbg_pi_phaselocked_done     : std_logic;
  signal dbg_pi_phaselock_err        : std_logic;
  signal dbg_pi_dqsfound_start       : std_logic;
  signal dbg_pi_dqsfound_done        : std_logic;
  signal dbg_pi_dqsfound_err         : std_logic;
  signal dbg_wrcal_start             : std_logic;
  signal dbg_wrcal_done              : std_logic;
  signal dbg_wrcal_err               : std_logic;
  signal dbg_pi_dqs_found_lanes_phy4lanes : std_logic_vector(11 downto 0);
  signal dbg_pi_phase_locked_phy4lanes    : std_logic_vector(11 downto 0);
  signal dbg_oclkdelay_calib_start   : std_logic;
  signal dbg_oclkdelay_calib_done    : std_logic;
  signal dbg_phy_oclkdelay_cal       : std_logic_vector(255 downto 0);
  signal dbg_oclkdelay_rd_data       : std_logic_vector((DRAM_WIDTH*16)-1 downto 0);
  signal dbg_rd_data_edge_detect     : std_logic_vector(DQS_WIDTH-1 downto 0);
  signal dbg_rddata                  : std_logic_vector((2*nCK_PER_CLK*DQ_WIDTH)-1 downto 0);
  signal dbg_rddata_valid            : std_logic;
  signal dbg_rdlvl_done              : std_logic_vector(1 downto 0);
  signal dbg_rdlvl_err               : std_logic_vector(1 downto 0);
  signal dbg_rdlvl_start             : std_logic_vector(1 downto 0);
  signal dbg_wrlvl_fine_tap_cnt      : std_logic_vector((6*DQS_WIDTH)-1 downto 0);
  signal dbg_wrlvl_coarse_tap_cnt    : std_logic_vector((3*DQS_WIDTH)-1 downto 0);
  signal dbg_tap_cnt_during_wrlvl    : std_logic_vector(5 downto 0);
  signal dbg_wl_edge_detect_valid    : std_logic;
  signal dbg_wrlvl_done              : std_logic;
  signal dbg_wrlvl_err               : std_logic;
  signal dbg_wrlvl_start             : std_logic;
  signal dbg_rddata_r                : std_logic_vector(63 downto 0);
  signal dbg_rddata_valid_r          : std_logic;
  signal ocal_tap_cnt                : std_logic_vector(53 downto 0);
  signal dbg_dqs                     : std_logic_vector(4 downto 0);
  signal dbg_bit                     : std_logic_vector(8 downto 0);
  signal rd_data_edge_detect_r       : std_logic_vector(8 downto 0);
  signal wl_po_fine_cnt              : std_logic_vector(53 downto 0);
  signal wl_po_coarse_cnt            : std_logic_vector(26 downto 0);
  signal dbg_calib_rd_data_offset_1  : std_logic_vector((6*RANKS)-1 downto 0);
  signal dbg_calib_rd_data_offset_2  : std_logic_vector((6*RANKS)-1 downto 0);
  signal dbg_data_offset             : std_logic_vector(5 downto 0);
  signal dbg_data_offset_1           : std_logic_vector(5 downto 0);
  signal dbg_data_offset_2           : std_logic_vector(5 downto 0);
  signal all_zeros                   : std_logic_vector((2*nCK_PER_CLK)-1 downto 0) := (others => '0');

  signal ddr3_ila_basic_int                    : std_logic_vector(119 downto 0);
  signal ddr3_ila_wrpath_int                   : std_logic_vector(390 downto 0);
  signal ddr3_ila_rdpath_int                   : std_logic_vector(1023 downto 0);
  signal dbg_prbs_final_dqs_tap_cnt_r_int : std_logic_vector(11 downto 0);
  signal dbg_prbs_first_edge_taps_int       : std_logic_vector(11 downto 0);
  signal dbg_prbs_second_edge_taps_int      : std_logic_vector(11 downto 0);
  

begin

--***************************************************************************





  ui_clk <= clk;
  ui_clk_sync_rst <= rst;
  
  sys_clk_p <= '0';
  sys_clk_n <= '0';
  clk_ref_p <= '0';
  clk_ref_n <= '0';
  init_calib_complete         <= init_calib_complete_i;
  device_temp <= device_temp_s;
      


  clk_ref_in_use_sys_clk : if (REFCLK_TYPE = "USE_SYSTEM_CLOCK") generate
    clk_ref_in <= mmcm_clk;
  end generate;

  clk_ref_in_others : if (REFCLK_TYPE /= "USE_SYSTEM_CLOCK") generate
    clk_ref_in <= clk_ref_i;
  end generate;

  u_iodelay_ctrl : mig_7series_v4_2_iodelay_ctrl
    generic map
    (
     TCQ              => TCQ,
     IODELAY_GRP0     => IODELAY_GRP0,
     IODELAY_GRP1     => IODELAY_GRP1,
     REFCLK_TYPE      => REFCLK_TYPE,
     SYSCLK_TYPE      => SYSCLK_TYPE,
     SYS_RST_PORT     => SYS_RST_PORT,
     RST_ACT_LOW      => RST_ACT_LOW,
     DIFF_TERM_REFCLK => DIFF_TERM_REFCLK,
     FPGA_SPEED_GRADE => FPGA_SPEED_GRADE,
     REF_CLK_MMCM_IODELAY_CTRL => REF_CLK_MMCM_IODELAY_CTRL
     )
    port map
      (
       -- Outputs
       iodelay_ctrl_rdy => iodelay_ctrl_rdy,
       sys_rst_o        => sys_rst_o,
       clk_ref          => clk_ref,
       -- Inputs
       clk_ref_p        => clk_ref_p,
       clk_ref_n        => clk_ref_n,
       clk_ref_i        => clk_ref_in,
       sys_rst          => sys_rst
       );
  u_ddr3_clk_ibuf : mig_7series_v4_2_clk_ibuf
    generic map
      (
       SYSCLK_TYPE      => SYSCLK_TYPE,
       DIFF_TERM_SYSCLK => DIFF_TERM_SYSCLK
       )
    port map
      (
       sys_clk_p        => sys_clk_p,
       sys_clk_n        => sys_clk_n,
       sys_clk_i        => sys_clk_i,
       mmcm_clk         => mmcm_clk
       );
  -- Temperature monitoring logic

  temp_mon_enabled : if (TEMP_MON_EN = "ON") generate
    u_tempmon : mig_7series_v4_2_tempmon
      generic map
        (
         TCQ              => TCQ,
         TEMP_MON_CONTROL => TEMP_MON_CONTROL,
         XADC_CLK_PERIOD  => XADC_CLK_PERIOD,
         tTEMPSAMPLE      => tTEMPSAMPLE
         )
      port map
        (
         clk            => clk,
         xadc_clk       => clk_ref(0),
         rst            => rst,
         device_temp_i  => device_temp_i,
         device_temp    => device_temp_s
         );
  end generate;

  temp_mon_disabled : if (TEMP_MON_EN /= "ON") generate
    device_temp_s <= (others => '0');
  end generate;
       

  u_ddr3_infrastructure : mig_7series_v4_2_infrastructure
    generic map
      (
       TCQ                => TCQ,
       nCK_PER_CLK        => nCK_PER_CLK,
       CLKIN_PERIOD       => CLKIN_PERIOD,
       SYSCLK_TYPE        => SYSCLK_TYPE,
       CLKFBOUT_MULT      => CLKFBOUT_MULT,
       DIVCLK_DIVIDE      => DIVCLK_DIVIDE,
       CLKOUT0_PHASE      => CLKOUT0_PHASE,
       CLKOUT0_DIVIDE     => CLKOUT0_DIVIDE,
       CLKOUT1_DIVIDE     => CLKOUT1_DIVIDE,
       CLKOUT2_DIVIDE     => CLKOUT2_DIVIDE,
       CLKOUT3_DIVIDE     => CLKOUT3_DIVIDE,
       MMCM_VCO           => MMCM_VCO,
       MMCM_MULT_F        => MMCM_MULT_F,
       MMCM_DIVCLK_DIVIDE => MMCM_DIVCLK_DIVIDE,
       RST_ACT_LOW        => RST_ACT_LOW,
       tCK                => tCK,
       MEM_TYPE           => DRAM_TYPE
       )
    port map
      (
       -- Outputs
       rstdiv0          => rst,
       clk              => clk,
       clk_div2         => clk_div2,
       rst_div2         => rst_div2,
       mem_refclk       => mem_refclk,
       freq_refclk      => freq_refclk,
       sync_pulse       => sync_pulse,
       psen             => psen,
       psincdec         => psincdec,
       mmcm_ps_clk      => mmcm_ps_clk,
       poc_sample_pd    => poc_sample_pd,
       iddr_rst         => iddr_rst,
       psdone           => psdone,
--       auxout_clk       => open,
       ui_addn_clk_0    => open,
       ui_addn_clk_1    => open,
       ui_addn_clk_2    => open,
       ui_addn_clk_3    => open,
       ui_addn_clk_4    => open,
       pll_locked       => pll_locked,
       mmcm_locked      => open,
       rst_phaser_ref   => rst_phaser_ref,
       -- Inputs
       mmcm_clk         => mmcm_clk,
       sys_rst          => sys_rst_o,
       iodelay_ctrl_rdy => iodelay_ctrl_rdy,
       ref_dll_lock     => ref_dll_lock
       );


  u_memc_ui_top_std : mig_7series_v4_2_memc_ui_top_std
    generic map (
      TCQ                              => TCQ,
      ADDR_CMD_MODE                    => ADDR_CMD_MODE,
      AL                               => AL,
      PAYLOAD_WIDTH                    => PAYLOAD_WIDTH,
      BANK_WIDTH                       => BANK_WIDTH,
      BM_CNT_WIDTH                     => BM_CNT_WIDTH,
      BURST_MODE                       => BURST_MODE,
      BURST_TYPE                       => BURST_TYPE,
      CA_MIRROR                        => CA_MIRROR,
      DDR3_VDD_OP_VOLT                 => VDD_OP_VOLT,
      CK_WIDTH                         => CK_WIDTH,
      COL_WIDTH                        => COL_WIDTH,
      CMD_PIPE_PLUS1                   => CMD_PIPE_PLUS1,
      CS_WIDTH                         => CS_WIDTH,
      nCS_PER_RANK                     => nCS_PER_RANK,
      CKE_WIDTH                        => CKE_WIDTH,
      DATA_WIDTH                       => DATA_WIDTH,
      DATA_BUF_ADDR_WIDTH              => DATA_BUF_ADDR_WIDTH,
      DM_WIDTH                         => DM_WIDTH,
      DQ_CNT_WIDTH                     => DQ_CNT_WIDTH,
      DQ_WIDTH                         => DQ_WIDTH,
      DQS_CNT_WIDTH                    => DQS_CNT_WIDTH,
      DQS_WIDTH                        => DQS_WIDTH,
      DRAM_TYPE                        => DRAM_TYPE,
      DRAM_WIDTH                       => DRAM_WIDTH,
      ECC                              => ECC,
      ECC_WIDTH                        => ECC_WIDTH,
      ECC_TEST                         => ECC_TEST,
      MC_ERR_ADDR_WIDTH                => MC_ERR_ADDR_WIDTH,
      REFCLK_FREQ                      => REFCLK_FREQ,
      nAL                              => nAL,
      nBANK_MACHS                      => nBANK_MACHS,
      CKE_ODT_AUX                      => CKE_ODT_AUX,
      nCK_PER_CLK                      => nCK_PER_CLK,
      ORDERING                         => ORDERING,
      OUTPUT_DRV                       => OUTPUT_DRV,
      IBUF_LPWR_MODE                   => IBUF_LPWR_MODE,
      DATA_IO_IDLE_PWRDWN              => DATA_IO_IDLE_PWRDWN,
      BANK_TYPE                        => BANK_TYPE,
      DATA_IO_PRIM_TYPE                => DATA_IO_PRIM_TYPE,
      IODELAY_GRP0                     => IODELAY_GRP0,
      IODELAY_GRP1                     => IODELAY_GRP1,
      FPGA_SPEED_GRADE                 => FPGA_SPEED_GRADE,
      REG_CTRL                         => REG_CTRL,
      RTT_NOM                          => RTT_NOM,
      RTT_WR                           => RTT_WR,
      CL                               => CL,
      CWL                              => CWL,
      tCK                              => tCK,
      tCKE                             => tCKE,
      tFAW                             => tFAW,
      tPRDI                            => tPRDI,
      tRAS                             => tRAS,
      tRCD                             => tRCD,
      tREFI                            => tREFI,
      tRFC                             => tRFC,
      tRP                              => tRP,
      tRRD                             => tRRD,
      tRTP                             => tRTP,
      tWTR                             => tWTR,
      tZQI                             => tZQI,
      tZQCS                            => tZQCS,
      USER_REFRESH                     => USER_REFRESH,
      TEMP_MON_EN                      => TEMP_MON_EN,
      WRLVL                            => WRLVL,
      DEBUG_PORT                       => DEBUG_PORT,
      CAL_WIDTH                        => CAL_WIDTH,
      RANK_WIDTH                       => RANK_WIDTH,
      RANKS                            => RANKS,
      ODT_WIDTH                        => ODT_WIDTH,
      ROW_WIDTH                        => ROW_WIDTH,
      ADDR_WIDTH                       => ADDR_WIDTH,
      APP_DATA_WIDTH                   => APP_DATA_WIDTH,
      APP_MASK_WIDTH                   => APP_MASK_WIDTH,
      SIM_BYPASS_INIT_CAL              => SIM_BYPASS_INIT_CAL,
      BYTE_LANES_B0                    => BYTE_LANES_B0,
      BYTE_LANES_B1                    => BYTE_LANES_B1,
      BYTE_LANES_B2                    => BYTE_LANES_B2,
      BYTE_LANES_B3                    => BYTE_LANES_B3,
      BYTE_LANES_B4                    => BYTE_LANES_B4,
      DATA_CTL_B0                      => DATA_CTL_B0,
      DATA_CTL_B1                      => DATA_CTL_B1,
      DATA_CTL_B2                      => DATA_CTL_B2,
      DATA_CTL_B3                      => DATA_CTL_B3,
      DATA_CTL_B4                      => DATA_CTL_B4,
      PHY_0_BITLANES                   => PHY_0_BITLANES,
      PHY_1_BITLANES                   => PHY_1_BITLANES,
      PHY_2_BITLANES                   => PHY_2_BITLANES,
      CK_BYTE_MAP                      => CK_BYTE_MAP,
      ADDR_MAP                         => ADDR_MAP,
      BANK_MAP                         => BANK_MAP,
      CAS_MAP                          => CAS_MAP,
      CKE_ODT_BYTE_MAP                 => CKE_ODT_BYTE_MAP,
      CKE_MAP                          => CKE_MAP,
      ODT_MAP                          => ODT_MAP,
      CS_MAP                           => CS_MAP,
      PARITY_MAP                       => PARITY_MAP,
      RAS_MAP                          => RAS_MAP,
      WE_MAP                           => WE_MAP,
      DQS_BYTE_MAP                     => DQS_BYTE_MAP,
      DATA0_MAP                        => DATA0_MAP,
      DATA1_MAP                        => DATA1_MAP,
      DATA2_MAP                        => DATA2_MAP,
      DATA3_MAP                        => DATA3_MAP,
      DATA4_MAP                        => DATA4_MAP,
      DATA5_MAP                        => DATA5_MAP,
      DATA6_MAP                        => DATA6_MAP,
      DATA7_MAP                        => DATA7_MAP,
      DATA8_MAP                        => DATA8_MAP,
      DATA9_MAP                        => DATA9_MAP,
      DATA10_MAP                       => DATA10_MAP,
      DATA11_MAP                       => DATA11_MAP,
      DATA12_MAP                       => DATA12_MAP,
      DATA13_MAP                       => DATA13_MAP,
      DATA14_MAP                       => DATA14_MAP,
      DATA15_MAP                       => DATA15_MAP,
      DATA16_MAP                       => DATA16_MAP,
      DATA17_MAP                       => DATA17_MAP,
      MASK0_MAP                        => MASK0_MAP,
      MASK1_MAP                        => MASK1_MAP,
      CALIB_ROW_ADD                    => CALIB_ROW_ADD,
      CALIB_COL_ADD                    => CALIB_COL_ADD,
      CALIB_BA_ADD                     => CALIB_BA_ADD,
      SLOT_0_CONFIG                    => SLOT_0_CONFIG,
      SLOT_1_CONFIG                    => SLOT_1_CONFIG,
      MEM_ADDR_ORDER                   => MEM_ADDR_ORDER,
      STARVE_LIMIT                     => STARVE_LIMIT,
      USE_CS_PORT                      => USE_CS_PORT,
      USE_DM_PORT                      => USE_DM_PORT,
      USE_ODT_PORT                     => USE_ODT_PORT,
      MASTER_PHY_CTL                   => PHY_CONTROL_MASTER_BANK,
      IDELAY_ADJ                       => IDELAY_ADJ,
      FINE_PER_BIT                     => FINE_PER_BIT,
      CENTER_COMP_MODE                 => CENTER_COMP_MODE,
      PI_VAL_ADJ                       => PI_VAL_ADJ,
      TAPSPERKCLK                      => TAPSPERKCLK,
      SKIP_CALIB                       => "FALSE",
      FPGA_VOLT_TYPE                   => FPGA_VOLT_TYPE
      )
      port map (
        clk                              => clk,
        clk_div2                         => clk_div2,
        rst_div2                         => rst_div2,
        clk_ref                          => clk_ref,
        mem_refclk                       => mem_refclk, --memory clock
        freq_refclk                      => freq_refclk,
        pll_lock                         => pll_locked,
        sync_pulse                       => sync_pulse,
        rst                              => rst,
        rst_phaser_ref                   => rst_phaser_ref,
        ref_dll_lock                     => ref_dll_lock,
        iddr_rst                         => iddr_rst,
        mmcm_ps_clk                      => mmcm_ps_clk,
        poc_sample_pd                    => poc_sample_pd,

-- Memory interface ports
        ddr_dq                           => ddr3_dq,
        ddr_dqs_n                        => ddr3_dqs_n,
        ddr_dqs                          => ddr3_dqs_p,
        ddr_addr                         => ddr3_addr,
        ddr_ba                           => ddr3_ba,
        ddr_cas_n                        => ddr3_cas_n,
        ddr_ck_n                         => ddr3_ck_n,
        ddr_ck                           => ddr3_ck_p,
        ddr_cke                          => ddr3_cke,
        ddr_cs_n                         => ddr3_cs_n,
        ddr_dm                           => ddr3_dm,
        ddr_odt                          => ddr3_odt,
        ddr_ras_n                        => ddr3_ras_n,
        ddr_reset_n                      => ddr3_reset_n,
        ddr_parity                       => ddr3_parity,
        ddr_we_n                         => ddr3_we_n,
        bank_mach_next                   => bank_mach_next,

-- Application interface ports
        app_addr                         => app_addr,
        app_cmd                          => app_cmd,
        app_en                           => app_en,
        app_hi_pri                       => '0',
        app_wdf_data                     => app_wdf_data,
        app_wdf_end                      => app_wdf_end,
        app_wdf_mask                     => app_wdf_mask,
        app_wdf_wren                     => app_wdf_wren,
        app_ecc_multiple_err             => app_ecc_multiple_err,
        app_ecc_single_err               => app_ecc_single_err,
        app_rd_data                      => app_rd_data,
        app_rd_data_end                  => app_rd_data_end,
        app_rd_data_valid                => app_rd_data_valid,
        app_rdy                          => app_rdy,
        app_wdf_rdy                      => app_wdf_rdy,
        app_sr_req                       => app_sr_req,
        app_sr_active                    => app_sr_active,
        app_ref_req                      => app_ref_req,
        app_ref_ack                      => app_ref_ack,
        app_zq_req                       => app_zq_req,
        app_zq_ack                       => app_zq_ack,
        app_raw_not_ecc                  => all_zeros,
        app_correct_en_i                 => '1',

        psen                             => psen,
        psincdec                         => psincdec,
        psdone                           => psdone,
        device_temp                      => device_temp_s,

        -- Ports to be used when SKIP_CALIB="TRUE"
        calib_tap_req                    => open,
        calib_tap_addr                   => (others => '0'),
        calib_tap_load                   => '0',
        calib_tap_val                    => (others => '0'),
        calib_tap_load_done              => '0',

-- Debug logic ports
        dbg_idel_up_all                  => dbg_idel_up_all,
        dbg_idel_down_all                => dbg_idel_down_all,
        dbg_idel_up_cpt                  => dbg_idel_up_cpt,
        dbg_idel_down_cpt                => dbg_idel_down_cpt,
        dbg_sel_idel_cpt                 => dbg_sel_idel_cpt,
        dbg_sel_all_idel_cpt             => dbg_sel_all_idel_cpt,
        dbg_sel_pi_incdec                => dbg_sel_pi_incdec,
        dbg_sel_po_incdec                => dbg_sel_po_incdec,
        dbg_byte_sel                     => dbg_byte_sel,
        dbg_pi_f_inc                     => dbg_pi_f_inc,
        dbg_pi_f_dec                     => dbg_pi_f_dec,
        dbg_po_f_inc                     => dbg_po_f_inc,
        dbg_po_f_stg23_sel               => dbg_po_f_stg23_sel,
        dbg_po_f_dec                     => dbg_po_f_dec,
        dbg_cpt_tap_cnt                  => dbg_cpt_tap_cnt,
        dbg_dq_idelay_tap_cnt            => dbg_dq_idelay_tap_cnt,
        dbg_calib_top                    => dbg_calib_top,
        dbg_cpt_first_edge_cnt           => dbg_cpt_first_edge_cnt,
        dbg_cpt_second_edge_cnt          => dbg_cpt_second_edge_cnt,
        dbg_rd_data_offset               => dbg_rd_data_offset,
        dbg_phy_rdlvl                    => dbg_phy_rdlvl,
        dbg_phy_wrcal                    => dbg_phy_wrcal,
        dbg_final_po_fine_tap_cnt        => dbg_final_po_fine_tap_cnt,
        dbg_final_po_coarse_tap_cnt      => dbg_final_po_coarse_tap_cnt,
        dbg_rd_data_edge_detect          => dbg_rd_data_edge_detect,
        dbg_rddata                       => dbg_rddata,
        dbg_rddata_valid                 => dbg_rddata_valid,
        dbg_rdlvl_done                   => dbg_rdlvl_done,
        dbg_rdlvl_err                    => dbg_rdlvl_err,
        dbg_rdlvl_start                  => dbg_rdlvl_start,
        dbg_wrlvl_fine_tap_cnt           => dbg_wrlvl_fine_tap_cnt,
        dbg_wrlvl_coarse_tap_cnt         => dbg_wrlvl_coarse_tap_cnt,
        dbg_tap_cnt_during_wrlvl         => dbg_tap_cnt_during_wrlvl,
        dbg_wl_edge_detect_valid         => dbg_wl_edge_detect_valid,
        dbg_wrlvl_done                   => dbg_wrlvl_done,
        dbg_wrlvl_err                    => dbg_wrlvl_err,
        dbg_wrlvl_start                  => dbg_wrlvl_start,
        dbg_phy_wrlvl                    => dbg_phy_wrlvl,
        dbg_phy_init                     => dbg_phy_init,
        dbg_prbs_rdlvl                   => dbg_prbs_rdlvl,
        dbg_dqs_found_cal                => dbg_dqs_found_cal,
        dbg_pi_counter_read_val          => dbg_pi_counter_read_val,
        dbg_po_counter_read_val          => dbg_po_counter_read_val,
        dbg_pi_phaselock_start           => dbg_pi_phaselock_start,
        dbg_pi_phaselocked_done          => dbg_pi_phaselocked_done,
        dbg_pi_phaselock_err             => dbg_pi_phaselock_err,
        dbg_pi_phase_locked_phy4lanes    => dbg_pi_phase_locked_phy4lanes,
        dbg_pi_dqsfound_start            => dbg_pi_dqsfound_start,
        dbg_pi_dqsfound_done             => dbg_pi_dqsfound_done,
        dbg_pi_dqsfound_err              => dbg_pi_dqsfound_err,
        dbg_pi_dqs_found_lanes_phy4lanes => dbg_pi_dqs_found_lanes_phy4lanes,
        dbg_calib_rd_data_offset_1       => dbg_calib_rd_data_offset_1,
        dbg_calib_rd_data_offset_2       => dbg_calib_rd_data_offset_2,
        dbg_data_offset                  => dbg_data_offset,
        dbg_data_offset_1                => dbg_data_offset_1,
        dbg_data_offset_2                => dbg_data_offset_2,
        dbg_wrcal_start                  => dbg_wrcal_start,
        dbg_wrcal_done                   => dbg_wrcal_done,
        dbg_wrcal_err                    => dbg_wrcal_err,
        dbg_phy_oclkdelay_cal            => dbg_phy_oclkdelay_cal,
        dbg_oclkdelay_rd_data            => dbg_oclkdelay_rd_data,
        dbg_oclkdelay_calib_start        => dbg_oclkdelay_calib_start,
        dbg_oclkdelay_calib_done         => dbg_oclkdelay_calib_done,
        dbg_prbs_final_dqs_tap_cnt_r     => dbg_prbs_final_dqs_tap_cnt_r_int,
        dbg_prbs_first_edge_taps         => dbg_prbs_first_edge_taps_int,
        dbg_prbs_second_edge_taps        => dbg_prbs_second_edge_taps_int,
        init_calib_complete              => init_calib_complete_i,
        dbg_poc                          => open
        );

      





  --*********************************************************************
  -- Resetting all RTL debug inputs as the debug ports are not enabled
  --*********************************************************************
  dbg_idel_down_all    <= '0';
  dbg_idel_down_cpt    <= '0';
  dbg_idel_up_all      <= '0';
  dbg_idel_up_cpt      <= '0';
  dbg_sel_all_idel_cpt <= '0';
  dbg_sel_idel_cpt     <= (others => '0');
  dbg_byte_sel         <= (others => '0');
  dbg_sel_pi_incdec    <= '0';
  dbg_pi_f_inc         <= '0';
  dbg_pi_f_dec         <= '0';
  dbg_po_f_inc         <= '0';
  dbg_po_f_dec         <= '0';
  dbg_po_f_stg23_sel   <= '0';
  dbg_sel_po_incdec    <= '0';

      

end architecture arch_ddr3_0_mig;



