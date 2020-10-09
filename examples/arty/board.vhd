-- Top level file connecting board to PipelineC generated code

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use ieee.numeric_std.all;
library UNISIM;
use UNISIM.VCOMPONENTS.ALL;

-- PipelineC packages
use work.c_structs_pkg.all;

-- Connections to the board, see xdc files
entity board is
  port (
    CLK100MHZ : in std_logic;
    sw : in std_logic_vector(3 downto 0);
    led : out std_logic_vector(3 downto 0);
    uart_rxd_out : out std_logic;
    uart_txd_in : in std_logic;
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
    ddr3_odt      : out   std_logic_vector(0 downto 0)
  );
end board;

architecture arch of board is

-- General clocks based off of the board's CLK100MHZ
signal clk_25, clk_50, clk_100, clk_200, clk_400 : std_logic;
signal clks_ready: std_logic;
signal rst : std_logic;
component clks_sys_clk_100
port
 (
  -- Clock out ports
  clk_25          : out    std_logic;
  clk_50          : out    std_logic;
  clk_100         : out    std_logic;
  clk_200         : out    std_logic;
  clk_400         : out    std_logic;
  -- Status and control signals
  locked          : out    std_logic;
  -- Clock in ports
  sys_clk_100     : in     std_logic
 );
end component;

-- DDR clocks based off of the board's CLK100MHZ
signal ddr_sys_clk : std_logic;
signal ddr_clks_ready: std_logic;
signal ddr_sys_rst_n : std_logic;
component ddr_clks_sys_clk_100
port
 (
  -- Clock out ports
  ddr_sys_clk          : out    std_logic;
  -- Status and control signals
  locked            : out    std_logic;
  -- Clock in ports
  sys_clk_100           : in     std_logic
 );
end component;

-- The board's DDR3 controller
signal app_addr                  :     std_logic_vector(27 downto 0);
signal app_cmd                   :     std_logic_vector(2 downto 0);
signal app_en                    :     std_logic;
signal app_wdf_data              :     std_logic_vector(127 downto 0);
signal app_wdf_end               :     std_logic;
signal app_wdf_mask              :     std_logic_vector(15 downto 0);
signal app_wdf_wren              :     std_logic;
signal app_rd_data               :    std_logic_vector(127 downto 0);
signal app_rd_data_end           :    std_logic;
signal app_rd_data_valid         :    std_logic;
signal app_rdy                   :    std_logic;
signal app_wdf_rdy               :    std_logic;
signal app_sr_req                :     std_logic;
signal app_ref_req               :     std_logic;
signal app_zq_req                :     std_logic;
signal app_sr_active             :    std_logic;
signal app_ref_ack               :    std_logic;
signal app_zq_ack                :    std_logic;
signal ui_clk                    :    std_logic;
signal ui_clk_sync_rst           :    std_logic;
signal init_calib_complete       :    std_logic;
component ddr3_0
  port (
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
      app_wdf_mask              : in    std_logic_vector(15 downto 0);
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
      sys_clk_i                 : in    std_logic;
      -- Reference Clock Ports
      clk_ref_i                 : in    std_logic;
      sys_rst                   : in    std_logic -- ACTIVE LOW - PORT NAME IS INCORRECT
  );
end component ddr3_0;
 
-- Internal signals
-- Clocks
signal sys_clk_100 : std_logic;
-- Switches
signal sw_r, sw_rr : std_logic_vector(3 downto 0);
-- LEDs
signal leds_wire : unsigned(3 downto 0);
-- UART
signal uart_txd_in_r, uart_txd_in_rr : std_logic;
-- DDR3
signal mig_to_app : xil_mig_to_app_t;
signal app_to_mig : xil_app_to_mig_t;

begin

-- Connect board's CLK100MHZ pin to internal global clock buffer network
CLK100MHZ_bufg_inst: BUFG 
port map (
    I => CLK100MHZ, 
    O => sys_clk_100
);

-- General clocks based off of the board's CLK100MHZ
clks_sys_clk_100_inst : clks_sys_clk_100
   port map ( 
  -- Clock out ports  
   clk_25 => clk_25,
   clk_50 => clk_50,
   clk_100 => clk_100,
   clk_200 => clk_200,
   clk_400 => clk_400,
  -- Status and control signals                
   locked => clks_ready,
   -- Clock in ports
   sys_clk_100 => sys_clk_100
 );
-- Hold in reset until clocks are ready
rst <= not clks_ready;

-- Sync some inputs to clk_25 with double regs
process(clk_25) begin
    if rising_edge(clk_25) then
        sw_r <= sw;
        sw_rr <= sw_r;
        uart_txd_in_r <= uart_txd_in;
        uart_txd_in_rr <= uart_txd_in_r;
    end if;
end process;

-- DDR clocks based off of the board's CLK100MHZ 
ddr_clks_sys_clk_100_inst : ddr_clks_sys_clk_100
   port map ( 
   ddr_sys_clk => ddr_sys_clk,
   locked => ddr_clks_ready,
   sys_clk_100 => sys_clk_100
 );
-- Hold in reset until clocks are ready
ddr_sys_rst_n <= '0' when (rst or not ddr_clks_ready) else '1';
 
-- The board's DDR3 controller
ddr3_0_inst : ddr3_0
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
       init_calib_complete            => init_calib_complete,
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
       app_sr_req                     => app_sr_req,
       app_ref_req                    => app_ref_req,
       app_zq_req                     => app_zq_req,
       app_sr_active                  => app_sr_active,
       app_ref_ack                    => app_ref_ack,
       app_zq_ack                     => app_zq_ack,
       ui_clk                         => ui_clk,
       ui_clk_sync_rst                => ui_clk_sync_rst,
       app_wdf_mask                   => app_wdf_mask,
       -- System Clock Ports
       sys_clk_i                      => ddr_sys_clk,
       -- Reference Clock Ports
       clk_ref_i                      => clk_200, -- Ref always 200MHz
       sys_rst                        => ddr_sys_rst_n -- ACTIVE LOW - PORT NAME IS INCORRECT
    );


-- Un/pack IO struct types to/from flattened SLV board pins
-- TODO Code gen this...
process(all) begin
    -- LEDs
    led <= std_logic_vector(leds_wire);   
    
    -- Switches
    --sys_clk_main_inputs.sw(0) <= sw_rr(0);
    --sys_clk_main_inputs.sw(1) <= sw_rr(1);
    --sys_clk_main_inputs.sw(2) <= sw_rr(2);
    --sys_clk_main_inputs.sw(3) <= sw_rr(3);
    
    -- UART
    --sys_clk_main_inputs.uart_txd_in(0) <= uart_txd_in_rr;
    --uart_rxd_out <= sys_clk_main_outputs.uart_rxd_out(0);

    -- DDR3
    app_addr <= std_logic_vector(app_to_mig.addr);    --              : in    std_logic_vector(27 downto 0);
    app_cmd  <= std_logic_vector(app_to_mig.cmd);     --            : in    std_logic_vector(2 downto 0);
    app_en  <= std_logic(app_to_mig.en(0));        --          : in    std_logic;
    for byte_i in 0 to app_wdf_mask'length-1 loop
		app_wdf_data(((byte_i+1)*8)-1 downto (byte_i*8)) <= std_logic_vector(app_to_mig.wdf_data(byte_i));
	end loop;
    app_wdf_end  <= std_logic(app_to_mig.wdf_end(0));     --        : in    std_logic;
    for byte_i in 0 to app_wdf_mask'length-1 loop
		app_wdf_mask(byte_i) <= std_logic(app_to_mig.wdf_mask(byte_i)(0));
	end loop;
    app_wdf_wren <= std_logic(app_to_mig.wdf_wren(0));     --        : in    std_logic;
    for byte_i in 0 to app_wdf_mask'length-1 loop
        mig_to_app.rd_data(byte_i) <= unsigned(app_rd_data(((byte_i+1)*8)-1 downto (byte_i*8)));
	end loop;
    mig_to_app.rd_data_end(0) <= app_rd_data_end; --           : out   std_logic;
    mig_to_app.rd_data_valid(0) <= app_rd_data_valid; --         : out   std_logic;
    mig_to_app.rdy(0) <= app_rdy; --                   : out   std_logic;
    mig_to_app.wdf_rdy(0) <= app_wdf_rdy; --               : out   std_logic;
    app_sr_req   <= std_logic(app_to_mig.sr_req(0));   --          : in    std_logic;
    app_ref_req  <= std_logic(app_to_mig.ref_req(0));   --          : in    std_logic;
    app_zq_req   <= std_logic(app_to_mig.zq_req(0));    --         : in    std_logic;
    mig_to_app.sr_active(0) <= app_sr_active;--             : out   std_logic;
    mig_to_app.ref_ack(0) <= app_ref_ack; --               : out   std_logic;
    mig_to_app.zq_ack(0)  <= app_zq_ack; --                : out   std_logic;
    mig_to_app.ui_clk_sync_rst(0) <= ui_clk_sync_rst;--           : out   std_logic;
    mig_to_app.init_calib_complete(0) <= init_calib_complete; --       : out   std_logic;
end process;
    
-- The PipelineC generated entity
top_inst : entity work.top port map (
    -- Main function clocks
    clk_83p33 => ui_clk,
    -- Each main funciton's inputs and output
    -- LEDs
    leds_module_return_output => leds_wire,
    -- DDR3
    xil_mig_module_mig_to_app => mig_to_app,
    xil_mig_module_return_output => app_to_mig
);

end arch;

