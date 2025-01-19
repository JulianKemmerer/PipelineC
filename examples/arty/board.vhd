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
    led0_r : out std_logic;
    led0_g : out std_logic;
    led0_b : out std_logic;
    ck_io29 : inout std_logic;
    ck_io30 : inout std_logic;
    uart_rxd_out : out std_logic;
    uart_txd_in : in std_logic;
    ja : inout std_logic_vector(7 downto 0);
    jb : inout std_logic_vector(7 downto 0);
    jc : inout std_logic_vector(7 downto 0);
    jd : inout std_logic_vector(7 downto 0);
    --  ddr3_dq       : inout std_logic_vector(15 downto 0);
    --  ddr3_dqs_p    : inout std_logic_vector(1 downto 0);
    --  ddr3_dqs_n    : inout std_logic_vector(1 downto 0);
    --  ddr3_addr     : out   std_logic_vector(13 downto 0);
    --  ddr3_ba       : out   std_logic_vector(2 downto 0);
    --  ddr3_ras_n    : out   std_logic;
    --  ddr3_cas_n    : out   std_logic;
    --  ddr3_we_n     : out   std_logic;
    --  ddr3_reset_n  : out   std_logic;
    --  ddr3_ck_p     : out   std_logic_vector(0 downto 0); 
    --  ddr3_ck_n     : out   std_logic_vector(0 downto 0);
    --  ddr3_cke      : out   std_logic_vector(0 downto 0);
    --  ddr3_cs_n     : out   std_logic_vector(0 downto 0);
    --  ddr3_dm       : out   std_logic_vector(1 downto 0);
    --  ddr3_odt      : out   std_logic_vector(0 downto 0);
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
  pixel_clock          : out    std_logic;
  -- Status and control signals
  locked            : out    std_logic;
  -- Clock in ports
  sys_clk_100       : in     std_logic
 );
end component;

-- Phase/delay adjusted pixel clock
--signal vga_pixel_clk_delayed : std_logic;
--signal pixel_clk_delayed_reset_n : std_logic;
--signal vga_clocks_delayed_ready : std_logic;
--  component vga_clock_shift
--  port
--   (-- Clock in ports
--    -- Clock out ports
--    pixel_clk_shifted          : out    std_logic;
--    -- Status and control signals
--    locked            : out    std_logic;
--    pixel_clk           : in     std_logic
--   );
--  end component;

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
signal clk_83p33                 :    std_logic;
signal ddr_sys_clk_i :  STD_LOGIC;
signal ddr_clk_ref_i :  STD_LOGIC;
signal ddr_ui_clk :  STD_LOGIC; -- 83.33MHz 
signal ddr_ui_clk_sync_rst :  STD_LOGIC;
signal ddr_mmcm_locked :  STD_LOGIC;
signal ddr_aresetn :  STD_LOGIC;
signal ddr_app_sr_req :  STD_LOGIC;
signal ddr_app_ref_req :  STD_LOGIC;
signal ddr_app_zq_req :  STD_LOGIC;
signal ddr_app_sr_active :  STD_LOGIC;
signal ddr_app_ref_ack :  STD_LOGIC;
signal ddr_app_zq_ack :  STD_LOGIC;
signal ddr_s_axi_awid :  STD_LOGIC_VECTOR ( 15 downto 0 );
signal ddr_s_axi_awaddr :  STD_LOGIC_VECTOR ( 27 downto 0 );
signal ddr_s_axi_awlen :  STD_LOGIC_VECTOR ( 7 downto 0 );
signal ddr_s_axi_awsize :  STD_LOGIC_VECTOR ( 2 downto 0 );
signal ddr_s_axi_awburst :  STD_LOGIC_VECTOR ( 1 downto 0 );
signal ddr_s_axi_awlock :  STD_LOGIC_VECTOR ( 0 to 0 );
signal ddr_s_axi_awcache :  STD_LOGIC_VECTOR ( 3 downto 0 );
signal ddr_s_axi_awprot :  STD_LOGIC_VECTOR ( 2 downto 0 );
signal ddr_s_axi_awqos :  STD_LOGIC_VECTOR ( 3 downto 0 );
signal ddr_s_axi_awvalid :  STD_LOGIC;
signal ddr_s_axi_awready :  STD_LOGIC;
signal ddr_s_axi_wdata :  STD_LOGIC_VECTOR ( 31 downto 0 );
signal ddr_s_axi_wstrb :  STD_LOGIC_VECTOR ( 3 downto 0 );
signal ddr_s_axi_wlast :  STD_LOGIC;
signal ddr_s_axi_wvalid :  STD_LOGIC;
signal ddr_s_axi_wready :  STD_LOGIC;
signal ddr_s_axi_bready :  STD_LOGIC;
signal ddr_s_axi_bid :  STD_LOGIC_VECTOR ( 15 downto 0 );
signal ddr_s_axi_bresp :  STD_LOGIC_VECTOR ( 1 downto 0 );
signal ddr_s_axi_bvalid :  STD_LOGIC;
signal ddr_s_axi_arid :  STD_LOGIC_VECTOR ( 15 downto 0 );
signal ddr_s_axi_araddr :  STD_LOGIC_VECTOR ( 27 downto 0 );
signal ddr_s_axi_arlen :  STD_LOGIC_VECTOR ( 7 downto 0 );
signal ddr_s_axi_arsize :  STD_LOGIC_VECTOR ( 2 downto 0 );
signal ddr_s_axi_arburst :  STD_LOGIC_VECTOR ( 1 downto 0 );
signal ddr_s_axi_arlock :  STD_LOGIC_VECTOR ( 0 to 0 );
signal ddr_s_axi_arcache :  STD_LOGIC_VECTOR ( 3 downto 0 );
signal ddr_s_axi_arprot :  STD_LOGIC_VECTOR ( 2 downto 0 );
signal ddr_s_axi_arqos :  STD_LOGIC_VECTOR ( 3 downto 0 );
signal ddr_s_axi_arvalid :  STD_LOGIC;
signal ddr_s_axi_arready :  STD_LOGIC;
signal ddr_s_axi_rready :  STD_LOGIC;
signal ddr_s_axi_rid :  STD_LOGIC_VECTOR ( 15 downto 0 );
signal ddr_s_axi_rdata :  STD_LOGIC_VECTOR ( 31 downto 0 );
signal ddr_s_axi_rresp :  STD_LOGIC_VECTOR ( 1 downto 0 );
signal ddr_s_axi_rlast :  STD_LOGIC;
signal ddr_s_axi_rvalid :  STD_LOGIC;
signal ddr_init_calib_complete :  STD_LOGIC;
signal ddr_device_temp :  STD_LOGIC_VECTOR ( 11 downto 0 );
component ddr_axi_32b
  Port ( 
    ddr3_dq : inout STD_LOGIC_VECTOR ( 15 downto 0 );
    ddr3_dqs_n : inout STD_LOGIC_VECTOR ( 1 downto 0 );
    ddr3_dqs_p : inout STD_LOGIC_VECTOR ( 1 downto 0 );
    ddr3_addr : out STD_LOGIC_VECTOR ( 13 downto 0 );
    ddr3_ba : out STD_LOGIC_VECTOR ( 2 downto 0 );
    ddr3_ras_n : out STD_LOGIC;
    ddr3_cas_n : out STD_LOGIC;
    ddr3_we_n : out STD_LOGIC;
    ddr3_reset_n : out STD_LOGIC;
    ddr3_ck_p : out STD_LOGIC_VECTOR ( 0 to 0 );
    ddr3_ck_n : out STD_LOGIC_VECTOR ( 0 to 0 );
    ddr3_cke : out STD_LOGIC_VECTOR ( 0 to 0 );
    ddr3_cs_n : out STD_LOGIC_VECTOR ( 0 to 0 );
    ddr3_dm : out STD_LOGIC_VECTOR ( 1 downto 0 );
    ddr3_odt : out STD_LOGIC_VECTOR ( 0 to 0 );
    sys_clk_i : in STD_LOGIC;
    clk_ref_i : in STD_LOGIC;
    ui_clk : out STD_LOGIC;
    ui_clk_sync_rst : out STD_LOGIC;
    mmcm_locked : out STD_LOGIC;
    aresetn : in STD_LOGIC;
    app_sr_req : in STD_LOGIC;
    app_ref_req : in STD_LOGIC;
    app_zq_req : in STD_LOGIC;
    app_sr_active : out STD_LOGIC;
    app_ref_ack : out STD_LOGIC;
    app_zq_ack : out STD_LOGIC;
    s_axi_awid : in STD_LOGIC_VECTOR ( 15 downto 0 );
    s_axi_awaddr : in STD_LOGIC_VECTOR ( 27 downto 0 );
    s_axi_awlen : in STD_LOGIC_VECTOR ( 7 downto 0 );
    s_axi_awsize : in STD_LOGIC_VECTOR ( 2 downto 0 );
    s_axi_awburst : in STD_LOGIC_VECTOR ( 1 downto 0 );
    s_axi_awlock : in STD_LOGIC_VECTOR ( 0 to 0 );
    s_axi_awcache : in STD_LOGIC_VECTOR ( 3 downto 0 );
    s_axi_awprot : in STD_LOGIC_VECTOR ( 2 downto 0 );
    s_axi_awqos : in STD_LOGIC_VECTOR ( 3 downto 0 );
    s_axi_awvalid : in STD_LOGIC;
    s_axi_awready : out STD_LOGIC;
    s_axi_wdata : in STD_LOGIC_VECTOR ( 31 downto 0 );
    s_axi_wstrb : in STD_LOGIC_VECTOR ( 3 downto 0 );
    s_axi_wlast : in STD_LOGIC;
    s_axi_wvalid : in STD_LOGIC;
    s_axi_wready : out STD_LOGIC;
    s_axi_bready : in STD_LOGIC;
    s_axi_bid : out STD_LOGIC_VECTOR ( 15 downto 0 );
    s_axi_bresp : out STD_LOGIC_VECTOR ( 1 downto 0 );
    s_axi_bvalid : out STD_LOGIC;
    s_axi_arid : in STD_LOGIC_VECTOR ( 15 downto 0 );
    s_axi_araddr : in STD_LOGIC_VECTOR ( 27 downto 0 );
    s_axi_arlen : in STD_LOGIC_VECTOR ( 7 downto 0 );
    s_axi_arsize : in STD_LOGIC_VECTOR ( 2 downto 0 );
    s_axi_arburst : in STD_LOGIC_VECTOR ( 1 downto 0 );
    s_axi_arlock : in STD_LOGIC_VECTOR ( 0 to 0 );
    s_axi_arcache : in STD_LOGIC_VECTOR ( 3 downto 0 );
    s_axi_arprot : in STD_LOGIC_VECTOR ( 2 downto 0 );
    s_axi_arqos : in STD_LOGIC_VECTOR ( 3 downto 0 );
    s_axi_arvalid : in STD_LOGIC;
    s_axi_arready : out STD_LOGIC;
    s_axi_rready : in STD_LOGIC;
    s_axi_rid : out STD_LOGIC_VECTOR ( 15 downto 0 );
    s_axi_rdata : out STD_LOGIC_VECTOR ( 31 downto 0 );
    s_axi_rresp : out STD_LOGIC_VECTOR ( 1 downto 0 );
    s_axi_rlast : out STD_LOGIC;
    s_axi_rvalid : out STD_LOGIC;
    init_calib_complete : out STD_LOGIC;
    device_temp : out STD_LOGIC_VECTOR ( 11 downto 0 );
    sys_rst : in STD_LOGIC
  );
end component;


-- Internal signals
-- Clocks
signal sys_clk_100 : std_logic;
-- Modules with structs as IO
-- DDR3
--signal mem_to_app : xil_mem_to_app_t;
--signal app_to_mem : app_to_xil_mem_t;

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

-- Ethernet clock and reset and unused signals
eth_ref_clk <= clk_25;

--  -- I2S clocks based off of the board's CLK100MHZ 
--  i2s_clks_inst : i2s_clks
--  port map
--   (
--    -- Clock out ports
--    i2s_mclk => i2s_mclk,
--    -- Status and control signals
--    locked => i2s_clks_ready,
--    -- Clock in ports
--    sys_clk_100 => sys_clk_100
--   );
--  -- I2S PMOD JA MCLK outputs
--  ja(0) <= i2s_mclk;
--  ja(4) <= i2s_mclk;
--  clk_22p579 <= i2s_mclk;
--  -- Hold in reset until clocks are ready
--  i2s_rst_n <= i2s_clks_ready;


-- VGA clocks based off of the board's CLK100MHZ 
vga_clocks_inst : vga_clocks
port map
(
  -- Clock out ports
  pixel_clock => vga_pixel_clk,
  -- Status and control signals
  locked => vga_clocks_ready,
  -- Clock in ports
  sys_clk_100 => sys_clk_100
);
-- Hold in reset until clocks are ready
pixel_clk_reset_n <= vga_clocks_ready;

-- Phase shifted/delayed pixel clock
--  vga_clock_shift_inst : vga_clock_shift
--     port map ( 
--     -- Clock out ports  
--     pixel_clk_shifted => vga_pixel_clk_delayed,
--     -- Status and control signals                
--     locked => vga_clocks_delayed_ready,
--     -- Clock in ports
--     pixel_clk => vga_pixel_clk
--   );
--  -- Hold in reset until clocks are ready
--  pixel_clk_delayed_reset_n <= vga_clocks_delayed_ready;

--  -- DDR clocks based off of the board's CLK100MHZ 
--  ddr_clks_sys_clk_100_inst : ddr_clks_sys_clk_100
--     port map ( 
--     ddr_sys_clk => ddr_sys_clk, -- 166.66MHz 
--     locked => ddr_clks_ready,
--     sys_clk_100 => sys_clk_100
--   );
--  clk_166p66 <= ddr_sys_clk;
--  -- Hold in reset until clocks are ready
--  ddr_sys_rst <= rst or not ddr_clks_ready;
--  ddr_sys_rst_n <= not ddr_sys_rst;
--   
--  -- The board's DDR3 controller
--  ddr_inst : ddr_axi_32b
--  port map (
--     s_axi_awid =>    ddr_s_axi_awid , 
--     s_axi_awaddr =>  ddr_s_axi_awaddr , 
--     s_axi_awlen =>   ddr_s_axi_awlen, 
--     s_axi_awsize =>  ddr_s_axi_awsize , 
--     s_axi_awburst => ddr_s_axi_awburst , 
--     s_axi_awlock =>  (others => '0'), --ddr_s_axi_awlock , 
--     s_axi_awcache => (others => '0'), --ddr_s_axi_awcache , 
--     s_axi_awprot =>  (others => '0'), --ddr_s_axi_awprot , 
--     s_axi_awqos =>   (others => '0'), --ddr_s_axi_awqos , 
--     s_axi_awvalid => ddr_s_axi_awvalid , 
--     s_axi_awready => ddr_s_axi_awready , 
--     s_axi_wdata =>   ddr_s_axi_wdata , 
--     s_axi_wstrb =>   ddr_s_axi_wstrb , 
--     s_axi_wlast =>   ddr_s_axi_wlast ,
--     s_axi_wvalid =>  ddr_s_axi_wvalid , 
--     s_axi_wready =>  ddr_s_axi_wready ,
--     s_axi_bready =>  ddr_s_axi_bready ,
--     s_axi_bid =>     ddr_s_axi_bid ,
--     s_axi_bresp =>   ddr_s_axi_bresp ,
--     s_axi_bvalid =>  ddr_s_axi_bvalid ,
--     s_axi_arid =>    ddr_s_axi_arid ,
--     s_axi_araddr =>  ddr_s_axi_araddr , 
--     s_axi_arlen =>   ddr_s_axi_arlen , 
--     s_axi_arsize =>  ddr_s_axi_arsize , 
--     s_axi_arburst => ddr_s_axi_arburst , 
--     s_axi_arlock =>  (others => '0'), --ddr_s_axi_arlock , 
--     s_axi_arcache => (others => '0'), --ddr_s_axi_arcache , 
--     s_axi_arprot =>  (others => '0'), --ddr_s_axi_arprot , 
--     s_axi_arqos =>   (others => '0'), --ddr_s_axi_arqos , 
--     s_axi_arvalid => ddr_s_axi_arvalid , 
--     s_axi_arready => ddr_s_axi_arready , 
--     s_axi_rready =>  ddr_s_axi_rready , 
--     s_axi_rid =>     ddr_s_axi_rid ,
--     s_axi_rdata =>   ddr_s_axi_rdata , 
--     s_axi_rresp =>   ddr_s_axi_rresp , 
--     s_axi_rlast =>   ddr_s_axi_rlast ,
--     s_axi_rvalid =>  ddr_s_axi_rvalid , 
--     -- Memory interface ports
--     ddr3_addr                      => ddr3_addr,
--     ddr3_ba                        => ddr3_ba,
--     ddr3_cas_n                     => ddr3_cas_n,
--     ddr3_ck_n                      => ddr3_ck_n,
--     ddr3_ck_p                      => ddr3_ck_p,
--     ddr3_cke                       => ddr3_cke,
--     ddr3_ras_n                     => ddr3_ras_n,
--     ddr3_reset_n                   => ddr3_reset_n,
--     ddr3_we_n                      => ddr3_we_n,
--     ddr3_dq                        => ddr3_dq,
--     ddr3_dqs_n                     => ddr3_dqs_n,
--     ddr3_dqs_p                     => ddr3_dqs_p,
--     init_calib_complete            => ddr_init_calib_complete,
--     ddr3_cs_n                      => ddr3_cs_n,
--     ddr3_dm                        => ddr3_dm,
--     ddr3_odt                       => ddr3_odt,
--     -- Application interface ports
--     app_sr_req                     => ddr_app_sr_req,
--     app_ref_req                    => ddr_app_ref_req,
--     app_zq_req                     => ddr_app_zq_req,
--     app_sr_active                  => ddr_app_sr_active,
--     app_ref_ack                    => ddr_app_ref_ack,
--     app_zq_ack                     => ddr_app_zq_ack,
--     ui_clk                         => ddr_ui_clk, -- 83.33MHz
--     ui_clk_sync_rst                => ddr_ui_clk_sync_rst,
--     -- System Clock Ports
--     sys_clk_i                      => ddr_sys_clk, -- 166.66MHz 
--     -- Reference Clock Ports
--     clk_ref_i                      => clk_200, -- Ref always 200MHz
--     sys_rst                        => ddr_sys_rst_n, -- ACTIVE LOW - PORT NAME IS INCORRECT
--     aresetn => ddr_sys_rst_n
--  );
--  clk_83p33 <= ddr_ui_clk;

-- Un/pack IO struct types to/from flattened SLV board pins
-- TODO write most of conversion funcs in PipelineC instead...
-- Commented out wires as necessary
process(all) begin    
    --  -- DDR3 
    --  ddr_s_axi_awid <= std_logic_vector(app_to_mem.axi_host_to_dev.write.req.awid);
    --  ddr_s_axi_awaddr <= std_logic_vector(resize(app_to_mem.axi_host_to_dev.write.req.awaddr, ddr_s_axi_awaddr'length)); 
    --  ddr_s_axi_awlen <= std_logic_vector(app_to_mem.axi_host_to_dev.write.req.awlen);
    --  ddr_s_axi_awsize <= std_logic_vector(app_to_mem.axi_host_to_dev.write.req.awsize);
    --  ddr_s_axi_awburst <= std_logic_vector(app_to_mem.axi_host_to_dev.write.req.awburst);
    --  ddr_s_axi_awvalid <= app_to_mem.axi_host_to_dev.write.req.awvalid(0);
    --  ddr_s_axi_wlast <= app_to_mem.axi_host_to_dev.write.data.wlast(0);
    --  ddr_s_axi_wvalid <= app_to_mem.axi_host_to_dev.write.data.wvalid(0);
    --  ddr_s_axi_bready <= app_to_mem.axi_host_to_dev.write.bready(0);
    --  ddr_s_axi_arid <= std_logic_vector(app_to_mem.axi_host_to_dev.read.req.arid);
    --  ddr_s_axi_araddr <= std_logic_vector(resize(app_to_mem.axi_host_to_dev.read.req.araddr, ddr_s_axi_araddr'length));
    --  ddr_s_axi_arlen <= std_logic_vector(app_to_mem.axi_host_to_dev.read.req.arlen);
    --  ddr_s_axi_arsize <= std_logic_vector(app_to_mem.axi_host_to_dev.read.req.arsize);
    --  ddr_s_axi_arburst <= std_logic_vector(app_to_mem.axi_host_to_dev.read.req.arburst);
    --  ddr_s_axi_arvalid <= app_to_mem.axi_host_to_dev.read.req.arvalid(0);
    --  ddr_s_axi_rready <= app_to_mem.axi_host_to_dev.read.rready(0);
    --  mem_to_app.axi_dev_to_host.write.resp.bid <= unsigned(ddr_s_axi_bid) ;
    --  mem_to_app.axi_dev_to_host.write.resp.bresp <= unsigned(ddr_s_axi_bresp) ;
    --  mem_to_app.axi_dev_to_host.write.resp.bvalid(0) <= ddr_s_axi_bvalid ;
    --  mem_to_app.axi_dev_to_host.write.awready(0) <= ddr_s_axi_awready;
    --  mem_to_app.axi_dev_to_host.write.wready(0) <= ddr_s_axi_wready ;
    --  mem_to_app.axi_dev_to_host.read.resp.rid <= unsigned(ddr_s_axi_rid) ;
    --  mem_to_app.axi_dev_to_host.read.resp.rresp <= unsigned(ddr_s_axi_rresp) ; 
    --  mem_to_app.axi_dev_to_host.read.data.rlast(0) <= ddr_s_axi_rlast ;
    --  mem_to_app.axi_dev_to_host.read.data.rvalid(0) <= ddr_s_axi_rvalid ;
    --  mem_to_app.axi_dev_to_host.read.arready(0) <= ddr_s_axi_arready ;
    --  for i in 0 to (ddr_s_axi_wdata'length/8)-1 loop
    --      ddr_s_axi_wdata(((i+1)*8)-1 downto (i*8)) <= std_logic_vector(app_to_mem.axi_host_to_dev.write.data.wdata(i));
    --      ddr_s_axi_wstrb(i) <= app_to_mem.axi_host_to_dev.write.data.wstrb(i)(0);
    --      mem_to_app.axi_dev_to_host.read.data.rdata(i) <= unsigned(ddr_s_axi_rdata(((i+1)*8)-1 downto (i*8)) );
    --  end loop;
    --  ddr_app_sr_req   <= app_to_mem.sr_req(0);
    --  ddr_app_ref_req  <= app_to_mem.ref_req(0);
    --  ddr_app_zq_req   <= app_to_mem.zq_req(0);
    --  mem_to_app.sr_active(0) <= ddr_app_sr_active;
    --  mem_to_app.ref_ack(0) <= ddr_app_ref_ack;
    --  mem_to_app.zq_ack(0)  <= ddr_app_zq_ack;
    --  mem_to_app.ui_clk_sync_rst(0) <= ddr_ui_clk_sync_rst;
    --  mem_to_app.init_calib_complete(0) <= ddr_init_calib_complete;
    
    
end process;
    
-- The PipelineC generated entity
top_inst : entity work.top port map (   
    -- Generic main function clocks
    --clk_none => ,
    --clk_6p25 => clk_6p25,
    --clk_12p5 => clk_12p5,
    --clk_22p579 => clk_22p579,
    clk_25p0 => clk_25, -- 640x480 pixel clock
    --clk_40p0 => clk_40, -- 800x600 pixel clock
    --clk_45p0 => clk_45,
    --clk_50p0 => clk_50,
    --clk_62p5 => clk_62p5,
    --clk_65p0 => clk_65,
    --clk_75p0 => clk_75,
    --clk_83p33 => clk_83p33, -- XIL DDR DEV CLOCK
    --clk_100p0 => clk_100,
    --clk_120p0 => clk_120,
    --clk_166p66 => clk_166p66,
    --clk_200p0 => clk_200,
    --clk_240p0 => clk_240p0,
    --clk_300p0 => clk_300,

    -- Each main function's inputs and outputs
    --i2s_loopback_app_reset_n(0) => i2s_rst_n,
    --cpu_top_areset(0) => ddr_sys_rst or not ddr_init_calib_complete or not i2s_rst_n,
    --fft_aresetn_val_input(0) => not (ddr_sys_rst or not ddr_init_calib_complete or not i2s_rst_n),  
    
    -- LEDs
    --led0_module_return_output(0) => led(0),
    --led1_module_return_output(0) => led(1),
    --led2_module_return_output(0) => led(2),
    --led3_module_return_output(0) => led(3),
    
    -- RGB LEDs
    led0_r_return_output(0) => led0_r,
    led0_g_return_output(0) => led0_g,
    led0_b_return_output(0) => led0_b,
    
    -- -- Switches
    --switches_module_sw => unsigned(sw),
    
    -- Buttons
    --buttons_module_btn => unsigned(btn),

    -- UART
    --uart_module_data_in(0) => uart_txd_in,
    --uart_module_return_output(0) => uart_rxd_out,
    
    -- ChipKit headers
    --ck_29_val_input(0) => ck_io29,
    --ck_30_return_output(0) => ck_io30,
    
    -- DVI PMOD on PMODB+C specific
    --  pixel_clock(0) => vga_pixel_clk,
    --  clk_148p5_delayed_146p25deg => vga_pixel_clk_delayed,
    --  -- Double rate DVI PMOD clock, PMODC[2] c.jc2 = ddr_clk;
    --  dvi_pmod_shifted_clock_return_output(0) => jc(2),
    
    -- NEW PMOD CONNECTIONS
    jb_0_return_output(0) => jb(0),
    jb_1_return_output(0) => jb(1),
    jb_2_return_output(0) => jb(2),
    jb_3_return_output(0) => jb(3),
    jb_4_return_output(0) => jb(4),
    jb_5_return_output(0) => jb(5),
    jb_6_return_output(0) => jb(6),
    jb_7_return_output(0) => jb(7),
    jc_0_return_output(0) => jc(0),
    jc_1_return_output(0) => jc(1),
    jc_2_return_output(0) => jc(2),
    jc_3_return_output(0) => jc(3),
    jc_4_return_output(0) => jc(4),
    jc_5_return_output(0) => jc(5)
    
    -- OLD PMOD CONNECTIONS
    --  -- PMODA
    --  pmod_ja_return_output.ja0(0) => open, --ja(0), i2s mclk
    --  pmod_ja_return_output.ja1(0) => ja(1),
    --  pmod_ja_return_output.ja2(0) => ja(2),
    --  pmod_ja_return_output.ja3(0) => ja(3),
    --  pmod_ja_return_output.ja4(0) => open, --ja(4), i2s mclk
    --  pmod_ja_return_output.ja5(0) => ja(5),
    --  pmod_ja_return_output.ja6(0) => ja(6),
    --  pmod_ja_return_output.ja7(0) => open,
    --  pmod_ja_inputs.ja0(0) => '0', -- i2s unused pmod pins
    --  pmod_ja_inputs.ja1(0) => '0',
    --  pmod_ja_inputs.ja2(0) => '0',
    --  pmod_ja_inputs.ja3(0) => '0',
    --  pmod_ja_inputs.ja4(0) => '0',
    --  pmod_ja_inputs.ja5(0) => '0',
    --  pmod_ja_inputs.ja6(0) => '0',
    --  pmod_ja_inputs.ja7(0) => ja(7),
    --  -- PMODD
    --  --pmod_jd_return_output.jd0(0) => jd(0),
    --  --pmod_jd_return_output.jd1(0) => jd(1),
    --  --pmod_jd_return_output.jd2(0) => jd(2),
    --  --pmod_jd_return_output.jd3(0) => jd(3),
    --  --pmod_jd_return_output.jd4(0) => jd(4),
    --  --pmod_jd_return_output.jd5(0) => jd(5),
    --  --pmod_jd_return_output.jd6(0) => jd(6),
    --  --pmod_jd_return_output.jd7(0) => jd(7)
    
    -- DDR3
    --xil_mem_module_mem_to_app => mem_to_app,
    --xil_mem_module_return_output => app_to_mem
    
    --  -- Ethernet
    --  xil_temac_instance_reset_n(0) => rst_n,
    --  eth_rx_clk_val_input(0) => eth_rx_clk,
    --  eth_rxd_val_input => unsigned(eth_rxd),
    --  eth_rx_dv_val_input(0) => eth_rx_dv,
    --  eth_rxerr_val_input(0) => eth_rxerr,
    --  eth_tx_clk_val_input(0) => eth_tx_clk,
    --  unsigned(eth_txd_return_output) => eth_txd,
    --  eth_tx_en_return_output(0) => eth_tx_en,
    --  eth_mdc_return_output(0) => eth_mdc,
    --  eth_rstn_return_output(0) => eth_rstn
);

end arch;

