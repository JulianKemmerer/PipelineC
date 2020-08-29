-- Top level file connecting to PipelineC generated code

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
library UNISIM;
use UNISIM.VCOMPONENTS.ALL;

-- PipelineC packages
use work.c_structs_pkg.all;

entity board is
  port (
    CLK100MHZ : in std_logic;
    sw : in std_logic_vector(3 downto 0);
    led : out std_logic_vector(3 downto 0);
    uart_rxd_out : out std_logic;
    uart_txd_in : in std_logic 
  );
end board;

architecture arch of board is

-- Clocks based off of the board's CLK100MHZ
signal clk_25, clk_50, clk_100, clk_200, clk_400 : std_logic;
signal clks_ready: std_logic;
component clks_sys_clk_100
port
 (-- Clock in ports
  -- Clock out ports
  clk_25          : out    std_logic;
  clk_50          : out    std_logic;
  clk_100          : out    std_logic;
  clk_200          : out    std_logic;
  clk_400          : out    std_logic;
  -- Status and control signals
  locked            : out    std_logic;
  sys_clk_100           : in     std_logic
 );
end component;
  
-- Sync inputs to a clock
signal sw_r, sw_rr : std_logic_vector(3 downto 0);
signal uart_txd_in_r, uart_txd_in_rr : std_logic;
  
begin

-- Clocks based off of the board's CLK100MHZ
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
   sys_clk_100 => CLK100MHZ
 );

-- Sync inputs to clk_25 with double regs
process(clk_25) begin
    if rising_edge(clk_25) then
        sw_r <= sw;
        sw_rr <= sw_r;
        uart_txd_in_r <= uart_txd_in;
        uart_txd_in_rr <= uart_txd_in_r;
    end if;
end process;

-- IO type conversion
process(
    -- Inputs to module
    sw_rr,
    uart_txd_in_rr
    -- Outputs from PipelineC
    --sys_clk_main_outputs
) begin
    -- Input
    --sys_clk_main_inputs.sw(0) <= sw_rr(0);
    --sys_clk_main_inputs.sw(1) <= sw_rr(1);
    --sys_clk_main_inputs.sw(2) <= sw_rr(2);
    --sys_clk_main_inputs.sw(3) <= sw_rr(3);
    --sys_clk_main_inputs.uart_txd_in(0) <= uart_txd_in_rr;
    
    -- Outputs
    --led(0) <= sys_clk_main_outputs.led(0)(0);
    --led(1) <= sys_clk_main_outputs.led(1)(0);
    --led(2) <= sys_clk_main_outputs.led(2)(0);
    --led(3) <= sys_clk_main_outputs.led(3)(0);
    --uart_rxd_out <= sys_clk_main_outputs.uart_rxd_out(0);
end process;

-- The PipelineC generated entity
top_inst : entity work.top port map (
clk_uart_rx_msg_main => clk_25,
uart_rx_msg_main_mac_data_in(0) => uart_txd_in_rr, 
uart_rx_msg_main_return_output(0) => led(0),
clk_uart_tx_msg_main => clk_25,
uart_tx_msg_main_return_output(0) => uart_rxd_out,
clk_sys_host => clk_25,
clk_sys_bram => clk_25,
clk_fosix => clk_25,
clk_main => clk_25
);

end arch;

