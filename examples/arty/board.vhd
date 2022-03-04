-- Top level file connecting board to PipelineC generated code

-- Standard libs
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use ieee.numeric_std.all;
library UNISIM;
use UNISIM.VCOMPONENTS.ALL;

-- PipelineC packages
use work.c_structs_pkg.all;

-- Connections to the board, see board io in xdc files, un/commment things as needed
entity board is
  port (
    CLK100MHZ : in std_logic;
    sw : in std_logic_vector(3 downto 0);
    btn : in std_logic_vector(3 downto 0);
    led : out std_logic_vector(3 downto 0);
    uart_rxd_out : out std_logic;
    uart_txd_in : in std_logic;
    ja : inout std_logic_vector(7 downto 0);
    jb : inout std_logic_vector(7 downto 0);
    jc : inout std_logic_vector(7 downto 0);
    ddr3_dq       : inout std_logic_vector(15 downto 0);
    ddr3_dqs_p    : inout std_logic_vector(1 downto 0);
    ddr3_dqs_n    : inout std_logic_vector(1 downto 0);
    ddr3_addr     : out   std_logic_vector(13 downto 0);
    ddr3_ba       : out   std_logic_vector(2 downto 0);
    ddr3_ras_n    : out   std_logic;
    ddr3_cas_n    : out   std_logic;
    ddr3_we_n     : out   std_logic;
    ddr3_reset_n  : out   std_logic;
    --ddr3_ck_p     : out   std_logic_vector(0 downto 0); -- Uncomment to use DDR3
    --ddr3_ck_n     : out   std_logic_vector(0 downto 0); -- Uncomment to use DDR3
    ddr3_cke      : out   std_logic_vector(0 downto 0);
    ddr3_cs_n     : out   std_logic_vector(0 downto 0);
    ddr3_dm       : out   std_logic_vector(1 downto 0);
    ddr3_odt      : out   std_logic_vector(0 downto 0);
    eth_col     : in std_logic;
    eth_crs     : in std_logic;
    eth_mdc     : out std_logic;
    eth_mdio    : inout std_logic;
    eth_ref_clk : out std_logic; -- A 25 MHz clock needs to be generated for the X1 pin of the external PHY, labeled ETH_REF_CLK
    eth_rstn    : out std_logic;
    eth_rx_clk  : in std_logic;
    eth_rx_dv   : in std_logic;
    eth_rxd     : in std_logic_vector(3 downto 0);
    eth_rxerr   : in std_logic;
    eth_tx_clk  : in std_logic;
    eth_tx_en   : out std_logic;
    eth_txd     : out std_logic_vector(3 downto 0)
  );
end board;

architecture arch of board is

-- General clocks+reset based off of the board's CLK100MHZ
signal clk_6p25, clk_12p5, clk_25, clk_50, clk_100, clk_200, clk_300 : std_logic;
signal clks_ready: std_logic;
signal rst : std_logic;
signal rst_n : std_logic;
component clks_sys_clk_100
port
 (
  -- Clock out ports
  clk_25          : out    std_logic;
  clk_50          : out    std_logic;
  clk_100         : out    std_logic;
  clk_200         : out    std_logic;
  clk_300         : out    std_logic;
  clk_12p5        : out    std_logic;
  clk_6p25        : out    std_logic;
  -- Status and control signals
  locked          : out    std_logic;
  -- Clock in ports
  sys_clk_100     : in     std_logic
 );
end component;

-- I2S clock+reset based off of the board's CLK100MHZ
signal i2s_mclk : std_logic; -- 22.579MHz
signal clk_22p579 : std_logic;
signal i2s_clks_ready : std_logic;
signal i2s_rst_n : std_logic;
component i2s_clks
port
 (
  -- Clock out ports
  i2s_mclk          : out    std_logic;
  -- Status and control signals
  locked            : out    std_logic;
  -- Clock in ports
  sys_clk_100       : in     std_logic
 );
end component;

-- Adjustable VGA clock+reset based off of the board's CLK100MHZ
signal vga_pixel_clk : std_logic;
signal vga_clocks_ready : std_logic;
signal pixel_clk_reset_n : std_logic;
component vga_clocks
port
 (
  -- Clock out ports
  pixel_clk          : out    std_logic;
  -- Status and control signals
  locked            : out    std_logic;
  -- Clock in ports
  sys_clk_100       : in     std_logic
 );
end component;

-- DDR clocks based off of the board's CLK100MHZ
signal ddr_sys_clk : std_logic; -- 166.66MHz 
signal clk_166p66 : std_logic;
signal ddr_clks_ready: std_logic;
signal ddr_sys_rst_n : std_logic;
signal ddr_sys_rst : std_logic;
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
signal ui_clk                    :    std_logic; -- 83.33MHz 
signal clk_83p33                 :    std_logic;
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

-- The boards ethernet mac
signal clk_25_eth_rx : std_logic;
signal clk_25_eth_tx : std_logic;
signal rx_statistics_vector :  STD_LOGIC_VECTOR(27 DOWNTO 0);
signal rx_statistics_valid :  STD_LOGIC;
signal rx_mac_aclk :  STD_LOGIC;
signal rx_reset :  STD_LOGIC;
signal rx_enable :  STD_LOGIC;
signal rx_axis_mac_tdata :  STD_LOGIC_VECTOR(7 DOWNTO 0);
signal rx_axis_mac_tvalid :  STD_LOGIC;
signal rx_axis_mac_tlast :  STD_LOGIC;
signal rx_axis_mac_tuser :  STD_LOGIC;
signal tx_ifg_delay :  STD_LOGIC_VECTOR(7 DOWNTO 0);
signal tx_statistics_vector :  STD_LOGIC_VECTOR(31 DOWNTO 0);
signal tx_statistics_valid :  STD_LOGIC;
signal tx_mac_aclk :  STD_LOGIC;
signal tx_reset :  STD_LOGIC;
signal tx_enable :  STD_LOGIC;
signal tx_axis_mac_tdata :  STD_LOGIC_VECTOR(7 DOWNTO 0);
signal tx_axis_mac_tvalid :  STD_LOGIC;
signal tx_axis_mac_tlast :  STD_LOGIC;
signal tx_axis_mac_tuser :  STD_LOGIC_VECTOR(0 DOWNTO 0);
signal tx_axis_mac_tready :  STD_LOGIC;
signal pause_req :  STD_LOGIC;
signal pause_val :  STD_LOGIC_VECTOR(15 DOWNTO 0);
signal speedis100 :  STD_LOGIC;
signal speedis10100 :  STD_LOGIC;
signal rx_configuration_vector :  STD_LOGIC_VECTOR(79 DOWNTO 0);
signal tx_configuration_vector :  STD_LOGIC_VECTOR(79 DOWNTO 0);
COMPONENT tri_mode_ethernet_mac_0
  PORT (
    glbl_rstn : IN STD_LOGIC;
    rx_axi_rstn : IN STD_LOGIC;
    tx_axi_rstn : IN STD_LOGIC;
    rx_statistics_vector : OUT STD_LOGIC_VECTOR(27 DOWNTO 0);
    rx_statistics_valid : OUT STD_LOGIC;
    rx_mac_aclk : OUT STD_LOGIC;
    rx_reset : OUT STD_LOGIC;
    rx_enable : OUT STD_LOGIC;
    rx_axis_mac_tdata : OUT STD_LOGIC_VECTOR(7 DOWNTO 0);
    rx_axis_mac_tvalid : OUT STD_LOGIC;
    rx_axis_mac_tlast : OUT STD_LOGIC;
    rx_axis_mac_tuser : OUT STD_LOGIC;
    tx_ifg_delay : IN STD_LOGIC_VECTOR(7 DOWNTO 0);
    tx_statistics_vector : OUT STD_LOGIC_VECTOR(31 DOWNTO 0);
    tx_statistics_valid : OUT STD_LOGIC;
    tx_mac_aclk : OUT STD_LOGIC;
    tx_reset : OUT STD_LOGIC;
    tx_enable : OUT STD_LOGIC;
    tx_axis_mac_tdata : IN STD_LOGIC_VECTOR(7 DOWNTO 0);
    tx_axis_mac_tvalid : IN STD_LOGIC;
    tx_axis_mac_tlast : IN STD_LOGIC;
    tx_axis_mac_tuser : IN STD_LOGIC_VECTOR(0 DOWNTO 0);
    tx_axis_mac_tready : OUT STD_LOGIC;
    pause_req : IN STD_LOGIC;
    pause_val : IN STD_LOGIC_VECTOR(15 DOWNTO 0);
    speedis100 : OUT STD_LOGIC;
    speedis10100 : OUT STD_LOGIC;
    mii_tx_clk : IN STD_LOGIC;
    mii_txd : OUT STD_LOGIC_VECTOR(3 DOWNTO 0);
    mii_tx_en : OUT STD_LOGIC;
    mii_tx_er : OUT STD_LOGIC;
    mii_rxd : IN STD_LOGIC_VECTOR(3 DOWNTO 0);
    mii_rx_dv : IN STD_LOGIC;
    mii_rx_er : IN STD_LOGIC;
    mii_rx_clk : IN STD_LOGIC;
    rx_configuration_vector : IN STD_LOGIC_VECTOR(79 DOWNTO 0);
    tx_configuration_vector : IN STD_LOGIC_VECTOR(79 DOWNTO 0)
  );
END COMPONENT;
 
-- Internal signals
-- Clocks
signal sys_clk_100 : std_logic;
-- Modules with structs as IO
-- DDR3
--signal mig_to_app : xil_mig_to_app_t;
--signal app_to_mig : xil_app_to_mig_t;
-- Ethernet
--signal temac_to_rx : xil_temac_to_rx_t;
--signal rx_to_temac : xil_rx_to_temac_t;
--signal temac_to_tx : xil_temac_to_tx_t;
--signal tx_to_temac : xil_tx_to_temac_t;

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
   clk_6p25 => clk_6p25,  
   clk_12p5 => clk_12p5,
   clk_25 => clk_25,
   clk_50 => clk_50,
   clk_100 => clk_100,
   clk_200 => clk_200,
   clk_300 => clk_300,
  -- Status and control signals                
   locked => clks_ready,
   -- Clock in ports
   sys_clk_100 => sys_clk_100
 );
-- Hold in reset until clocks are ready
rst <= not clks_ready;
rst_n <= clks_ready;

-- -- I2S clocks based off of the board's CLK100MHZ 
-- i2s_clks_inst : i2s_clks
-- port map
--  (
--   -- Clock out ports
--   i2s_mclk => i2s_mclk,
--   -- Status and control signals
--   locked => i2s_clks_ready,
--   -- Clock in ports
--   sys_clk_100 => sys_clk_100
--  );
-- -- I2S PMOD JA MCLK outputs
-- ja(0) <= i2s_mclk;
-- ja(4) <= i2s_mclk;
-- clk_22p579 <= i2s_mclk;
-- -- Hold in reset until clocks are ready
-- i2s_rst_n <= i2s_clks_ready;


-- VGA clocks based off of the board's CLK100MHZ 
vga_clocks_inst : vga_clocks
port map
(
  -- Clock out ports
  pixel_clk => vga_pixel_clk,
  -- Status and control signals
  locked => vga_clocks_ready,
  -- Clock in ports
  sys_clk_100 => sys_clk_100
);
-- Hold in reset until clocks are ready
pixel_clk_reset_n <= vga_clocks_ready;

-- -- DDR clocks based off of the board's CLK100MHZ 
-- ddr_clks_sys_clk_100_inst : ddr_clks_sys_clk_100
--    port map ( 
--    ddr_sys_clk => ddr_sys_clk, -- 166.66MHz 
--    locked => ddr_clks_ready,
--    sys_clk_100 => sys_clk_100
--  );
-- clk_166p66 <= ddr_sys_clk;
-- -- Hold in reset until clocks are ready
-- ddr_sys_rst <= rst or not ddr_clks_ready;
-- ddr_sys_rst_n <= not ddr_sys_rst;
--  
-- -- The board's DDR3 controller
--  ddr3_0_inst : ddr3_0
--      port map (
--         -- Memory interface ports
--         ddr3_addr                      => ddr3_addr,
--         ddr3_ba                        => ddr3_ba,
--         ddr3_cas_n                     => ddr3_cas_n,
--         --ddr3_ck_n                      => ddr3_ck_n,
--         --ddr3_ck_p                      => ddr3_ck_p,
--         ddr3_cke                       => ddr3_cke,
--         ddr3_ras_n                     => ddr3_ras_n,
--         ddr3_reset_n                   => ddr3_reset_n,
--         ddr3_we_n                      => ddr3_we_n,
--         ddr3_dq                        => ddr3_dq,
--         ddr3_dqs_n                     => ddr3_dqs_n,
--         ddr3_dqs_p                     => ddr3_dqs_p,
--         init_calib_complete            => init_calib_complete,
--  	   ddr3_cs_n                      => ddr3_cs_n,
--         ddr3_dm                        => ddr3_dm,
--         ddr3_odt                       => ddr3_odt,
--         -- Application interface ports
--         app_addr                       => app_addr,
--         app_cmd                        => app_cmd,
--         app_en                         => app_en,
--         app_wdf_data                   => app_wdf_data,
--         app_wdf_end                    => app_wdf_end,
--         app_wdf_wren                   => app_wdf_wren,
--         app_rd_data                    => app_rd_data,
--         app_rd_data_end                => app_rd_data_end,
--         app_rd_data_valid              => app_rd_data_valid,
--         app_rdy                        => app_rdy,
--         app_wdf_rdy                    => app_wdf_rdy,
--         app_sr_req                     => app_sr_req,
--         app_ref_req                    => app_ref_req,
--         app_zq_req                     => app_zq_req,
--         app_sr_active                  => app_sr_active,
--         app_ref_ack                    => app_ref_ack,
--         app_zq_ack                     => app_zq_ack,
--         ui_clk                         => ui_clk, -- 83.33MHz
--         ui_clk_sync_rst                => ui_clk_sync_rst,
--         app_wdf_mask                   => app_wdf_mask,
--         -- System Clock Ports
--         sys_clk_i                      => ddr_sys_clk, -- 166.66MHz 
--         -- Reference Clock Ports
--         clk_ref_i                      => clk_200, -- Ref always 200MHz
--         sys_rst                        => ddr_sys_rst_n -- ACTIVE LOW - PORT NAME IS INCORRECT
--      );
-- clk_83p33 <= ui_clk;

-- -- The board's ethernet MAC
-- eth_ref_clk <= clk_25;
-- eth_rstn <= rst_n;
-- eth_mdc <= '0';
-- --eth_mdio <= '0';
-- tri_mode_ethernet_mac_0_inst : tri_mode_ethernet_mac_0
--   PORT MAP (
--     glbl_rstn => rst_n,
--     rx_axi_rstn => rst_n,
--     tx_axi_rstn => rst_n,
--     rx_statistics_vector => rx_statistics_vector,
--     rx_statistics_valid => rx_statistics_valid,
--     rx_mac_aclk => clk_25_eth_rx,
--     rx_reset => rx_reset,
--     rx_enable => rx_enable,
--     rx_axis_mac_tdata => rx_axis_mac_tdata,
--     rx_axis_mac_tvalid => rx_axis_mac_tvalid,
--     rx_axis_mac_tlast => rx_axis_mac_tlast,
--     rx_axis_mac_tuser => rx_axis_mac_tuser,
--     tx_ifg_delay => tx_ifg_delay,
--     tx_statistics_vector => tx_statistics_vector,
--     tx_statistics_valid => tx_statistics_valid,
--     tx_mac_aclk => clk_25_eth_tx,
--     tx_reset => tx_reset,
--     tx_enable => tx_enable,
--     tx_axis_mac_tdata => tx_axis_mac_tdata,
--     tx_axis_mac_tvalid => tx_axis_mac_tvalid,
--     tx_axis_mac_tlast => tx_axis_mac_tlast,
--     tx_axis_mac_tuser => tx_axis_mac_tuser,
--     tx_axis_mac_tready => tx_axis_mac_tready,
--     pause_req => pause_req,
--     pause_val => pause_val,
--     speedis100 => speedis100,
--     speedis10100 => speedis10100,
--     mii_tx_clk => eth_tx_clk,
--     mii_txd => eth_txd,
--     mii_tx_en => eth_tx_en,
--     mii_tx_er => open,
--     mii_rxd => eth_rxd,
--     mii_rx_dv => eth_rx_dv,
--     mii_rx_er => eth_rxerr,
--     mii_rx_clk => eth_rx_clk,
--     rx_configuration_vector => rx_configuration_vector,
--     tx_configuration_vector => tx_configuration_vector
--   );


-- Un/pack IO struct types to/from flattened SLV board pins
-- TODO Code gen this...
-- Commented out wires as necessary
process(all) begin    
    -- DDR3
    -- app_addr <= std_logic_vector(app_to_mig.addr);
    -- app_cmd  <= std_logic_vector(app_to_mig.cmd);
    -- app_en  <= std_logic(app_to_mig.en(0));
    -- for byte_i in 0 to app_wdf_mask'length-1 loop
	-- 	app_wdf_data(((byte_i+1)*8)-1 downto (byte_i*8)) <= std_logic_vector(app_to_mig.wdf_data(byte_i));
	-- end loop;
    -- app_wdf_end  <= std_logic(app_to_mig.wdf_end(0));
    -- for byte_i in 0 to app_wdf_mask'length-1 loop
	-- 	app_wdf_mask(byte_i) <= std_logic(app_to_mig.wdf_mask(byte_i)(0));
	-- end loop;
    -- app_wdf_wren <= std_logic(app_to_mig.wdf_wren(0));
    -- for byte_i in 0 to app_wdf_mask'length-1 loop
    --     mig_to_app.rd_data(byte_i) <= unsigned(app_rd_data(((byte_i+1)*8)-1 downto (byte_i*8)));
	-- end loop;
    -- mig_to_app.rd_data_end(0) <= app_rd_data_end; 
    -- mig_to_app.rd_data_valid(0) <= app_rd_data_valid;
    -- mig_to_app.rdy(0) <= app_rdy;
    -- mig_to_app.wdf_rdy(0) <= app_wdf_rdy; 
    -- app_sr_req   <= std_logic(app_to_mig.sr_req(0));
    -- app_ref_req  <= std_logic(app_to_mig.ref_req(0));
    -- app_zq_req   <= std_logic(app_to_mig.zq_req(0));
    -- mig_to_app.sr_active(0) <= app_sr_active;
    -- mig_to_app.ref_ack(0) <= app_ref_ack;
    -- mig_to_app.zq_ack(0)  <= app_zq_ack;
    -- mig_to_app.ui_clk_sync_rst(0) <= ui_clk_sync_rst;
    -- mig_to_app.init_calib_complete(0) <= init_calib_complete;
    
    -- Ethernet     
    --  temac_to_rx.rx_statistics_vector <= unsigned(rx_statistics_vector) ;
    --  temac_to_rx.rx_statistics_valid(0) <= rx_statistics_valid ;                     
    --  temac_to_rx.rx_reset(0)<= rx_reset ;                             
    --  temac_to_rx.rx_enable(0)<= rx_enable ;                               
    --  temac_to_rx.rx_axis_mac.data(0) <= unsigned(rx_axis_mac_tdata) ;
    --  temac_to_rx.rx_axis_mac.valid(0) <= rx_axis_mac_tvalid ;                
    --  temac_to_rx.rx_axis_mac.last(0) <= rx_axis_mac_tlast ;                   
    --  --temac_to_rx.<= rx_axis_mac_tuser ;                        
    --  tx_ifg_delay <= std_logic_vector(tx_to_temac.tx_ifg_delay);     
    --  temac_to_tx.tx_statistics_vector<= unsigned(tx_statistics_vector);
    --  temac_to_tx.tx_statistics_valid(0)<= tx_statistics_valid ;                                        
    --  temac_to_tx.tx_reset(0)<= tx_reset ;                                
    --  temac_to_tx.tx_enable(0)<= tx_enable ;                               
    --  tx_axis_mac_tdata <= std_logic_vector(tx_to_temac.tx_axis_mac.data(0));  
    --  tx_axis_mac_tvalid <= tx_to_temac.tx_axis_mac.valid(0);                    
    --  tx_axis_mac_tlast <= tx_to_temac.tx_axis_mac.last(0);                       
    --  tx_axis_mac_tuser <= (others => '0');     
    --  temac_to_tx.tx_axis_mac_ready(0)<= tx_axis_mac_tready ;            
    --  pause_req <= rx_to_temac.pause_req(0);                                 
    --  pause_val <= std_logic_vector(rx_to_temac.pause_val);                                                
    --  rx_configuration_vector <= std_logic_vector(rx_to_temac.rx_configuration_vector);
    --  tx_configuration_vector <= std_logic_vector(tx_to_temac.tx_configuration_vector);
    --  temac_to_rx.speedis100(0)<= speedis100 ;                           
    --  temac_to_rx.speedis10100(0)<= speedis10100 ;
    --  temac_to_tx.speedis100(0)<= speedis100 ;                              
    --  temac_to_tx.speedis10100(0)<= speedis10100 ;
end process;
    
-- The PipelineC generated entity
top_inst : entity work.top port map (   
    -- Generic main function clocks
    --clk_6p25 => clk_6p25,
    --clk_22p579 => clk_22p579,
    clk_148p5 => vga_pixel_clk,
    --clk_50p0 => clk_50,
    --clk_83p33 => clk_83p33,
    --clk_100p0 => clk_100,
    --clk_150p0 => clk_100,
    --clk_166p66 => clk_166p66,
    --clk_200p0 => clk_200,
    --clk_300p0 => clk_300,
        
    -- Each main function's inputs and outputs
    --app_reset_n(0) => rst_n,   
    
    -- LEDs
    --led0_module_return_output(0) => led(0),
    --led1_module_return_output(0) => led(1),
    --led2_module_return_output(0) => led(2),
    --led3_module_return_output(0) => led(3),
    
    -- Switches
    --switches_module_sw => unsigned(sw),
    
    -- Buttons
    --buttons_module_btn => unsigned(btn),

    -- UART
    --uart_module_data_in(0) => uart_txd_in,
    --uart_module_return_output(0) => uart_rxd_out
    
    -- PMODA
    ----pmod_ja_return_output.ja0(0) => ja(0),
    --pmod_ja_return_output.ja1(0) => ja(1),
    --pmod_ja_return_output.ja2(0) => ja(2),
    --pmod_ja_return_output.ja3(0) => ja(3),
    ----pmod_ja_return_output.ja4(0) => ja(4),
    --pmod_ja_return_output.ja5(0) => ja(5),
    --pmod_ja_return_output.ja6(0) => ja(6),
    --pmod_ja_inputs.ja7(0) => ja(7),
    -- PMODB
    pmod_jb_return_output.jb0(0) => jb(0),
    pmod_jb_return_output.jb1(0) => jb(1),
    pmod_jb_return_output.jb2(0) => jb(2),
    pmod_jb_return_output.jb3(0) => jb(3),
    pmod_jb_return_output.jb4(0) => jb(4),
    pmod_jb_return_output.jb5(0) => jb(5),
    pmod_jb_return_output.jb6(0) => jb(6),
    pmod_jb_return_output.jb7(0) => jb(7),
    -- PMODC
    pmod_jc_return_output.jc0(0) => jc(0),
    pmod_jc_return_output.jc1(0) => jc(1),
    pmod_jc_return_output.jc2(0) => jc(2),
    pmod_jc_return_output.jc3(0) => jc(3),
    pmod_jc_return_output.jc4(0) => jc(4),
    pmod_jc_return_output.jc5(0) => jc(5),
    pmod_jc_return_output.jc6(0) => jc(6),
    pmod_jc_return_output.jc7(0) => jc(7)
    
    -- DDR3
    --xil_mig_module_mig_to_app => mig_to_app,
    --xil_mig_module_return_output => app_to_mig,
    
    -- Ethernet
    --clk_25p0_xil_temac_rx => clk_25_eth_rx,
    --clk_25p0_xil_temac_tx => clk_25_eth_tx,
    --xil_temac_rx_module_temac_to_rx => temac_to_rx,
    --xil_temac_rx_module_return_output => rx_to_temac,
    --xil_temac_tx_module_temac_to_tx => temac_to_tx, 
    --xil_temac_tx_module_return_output => tx_to_temac    
);

end arch;

