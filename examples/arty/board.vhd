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
  
-- Sync inputs to CLK100MHZ
signal sw_r, sw_rr : std_logic_vector(3 downto 0);
signal uart_txd_in_r, uart_txd_in_rr : std_logic;
  
-- IO type conversion
signal sys_clk_main_inputs : sys_clk_main_inputs_t;
signal sys_clk_main_outputs : sys_clk_main_outputs_t;
  
begin

-- Sync inputs to CLK100MHZ
process(CLK100MHZ) begin
    if rising_edge(CLK100MHZ) then
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
    uart_txd_in_rr,
    -- Outputs from PipelineC
    sys_clk_main_outputs
) begin
    -- Input
    --sys_clk_main_inputs.sw(0) <= sw_rr(0);
    --sys_clk_main_inputs.sw(1) <= sw_rr(1);
    --sys_clk_main_inputs.sw(2) <= sw_rr(2);
    --sys_clk_main_inputs.sw(3) <= sw_rr(3);
    sys_clk_main_inputs.uart_txd_in(0) <= uart_txd_in_rr;
    
    -- Outputs
    led(0) <= sys_clk_main_outputs.led(0)(0);
    led(1) <= sys_clk_main_outputs.led(1)(0);
    led(2) <= sys_clk_main_outputs.led(2)(0);
    led(3) <= sys_clk_main_outputs.led(3)(0);
    uart_rxd_out <= sys_clk_main_outputs.uart_rxd_out(0);
end process;

-- The PipelineC generated entity
top_inst : entity work.top port map (
    clk_sys_clk_main => CLK100MHZ,
    sys_clk_main_inputs => sys_clk_main_inputs,
    sys_clk_main_return_output => sys_clk_main_outputs
);

end arch;

