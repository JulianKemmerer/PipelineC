-- Arty A7 top level: connects the board to the Pypeline generated top level (top.vhd).
-- Every port here must exist in arty.xdc. The port map of top_inst must match the
-- Input[T]/Output[T] ports and clocks of the Pypeline design (top.py).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library unisim;
use unisim.vcomponents.all;

entity board is
  port (
    CLK100MHZ : in std_logic;
    led0_r : out std_logic;
    led0_g : out std_logic;
    led0_b : out std_logic;
    ja : out std_logic_vector(7 downto 0);
    jb : out std_logic_vector(5 downto 0)
  );
end board;

architecture arch of board is
  signal clk_fb : std_logic;
  signal clk_25_unbuffered : std_logic;
  signal clk_25 : std_logic;
  signal clk_25_locked : std_logic;
begin

  -- PLL (an MMCM) making a 25 MHz clock from the board's 100 MHz clock:
  -- 100 MHz * 10.0 = 1000 MHz VCO, 1000 MHz / 40.0 = 25 MHz
  mmcm_inst : MMCME2_BASE
    generic map (
      CLKIN1_PERIOD => 10.0,
      DIVCLK_DIVIDE => 1,
      CLKFBOUT_MULT_F => 10.0,
      CLKOUT0_DIVIDE_F => 40.0
    )
    port map (
      CLKIN1 => CLK100MHZ,
      CLKFBIN => clk_fb,
      CLKFBOUT => clk_fb,
      CLKOUT0 => clk_25_unbuffered,
      LOCKED => clk_25_locked,
      PWRDWN => '0',
      RST => '0'
    );
  clk_25_bufg : BUFG
    port map (
      I => clk_25_unbuffered,
      O => clk_25
    );

  -- The Pypeline generated entity
  top_inst : entity work.top
    port map (
      -- Clock for @MAIN(25.0) functions
      clk_25p0 => clk_25,
      -- Input[uint1_t] ports
      pll_locked(0) => clk_25_locked,
      -- Output[uint1_t] ports
      led0_r(0) => led0_r,
      led0_g(0) => led0_g,
      led0_b(0) => led0_b,
      ja_0(0) => ja(0),
      ja_1(0) => ja(1),
      ja_2(0) => ja(2),
      ja_3(0) => ja(3),
      ja_4(0) => ja(4),
      ja_5(0) => ja(5),
      ja_6(0) => ja(6),
      ja_7(0) => ja(7),
      jb_0(0) => jb(0),
      jb_1(0) => jb(1),
      jb_2(0) => jb(2),
      jb_3(0) => jb(3),
      jb_4(0) => jb(4),
      jb_5(0) => jb(5)
    );

end arch;
