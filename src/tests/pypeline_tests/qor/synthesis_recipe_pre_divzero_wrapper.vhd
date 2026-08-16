library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity pre_divzero is
port(
  dividend : in unsigned(31 downto 0);
  divisor : in unsigned(31 downto 0);
  left_eff : out unsigned(31 downto 0)
);
end pre_divzero;

architecture arch of pre_divzero is
  signal divisor_nonzero : unsigned(0 downto 0);
  constant ALL_ONES : unsigned(31 downto 0) := (others => '1');
begin
  neq : entity work.BIN_OP_NEQ_uint32_t_uint1_t_0CLK_de264c78
    port map(
      left => divisor,
      right => to_unsigned(0, 1),
      return_output => divisor_nonzero
    );
  choose_left : entity work.MUX_uint32_t_0CLK_de264c78
    port map(
      cond => divisor_nonzero,
      iftrue => dividend,
      iffalse => ALL_ONES,
      return_output => left_eff
    );
end arch;
