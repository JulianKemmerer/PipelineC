# pyright: reportInvalidTypeForm=none
"""Fixture for multi_clock_reset_ghdl_test.py and multi_clock_reset_synth_test.py:
two clock domains with their own resets, shaped like a soft-CPU SoC's.

- cpu_clk (100 MHz) resets with cpu_rst, a reset Wire: btn_sync synchronizes
  the asynchronous pin BTN with two registers (it is not reset itself).
  Every register of the cpu domain resets (reset_registers="all"), among
  them a same-clock global FIFO and a global instance, which take the
  clock's reset with no keyword.
- eth_clk (125 MHz, pin ETH_RX_CLK) resets with eth_rst, which eth_rst_gen
  makes from an IP-style raw vhdl() block's active-low rst_n, itself
  triggered by the synchronized asynchronous pin ETH_RST_REQ (and by power
  on). The eth domain resets only its Reg[T, RESET] registers ("requested"),
  and keeps a manual-only register (last_lr = lr) out of the reset.
- bump(), with a register, is called in both domains: one entity resets, the
  other does not.
- An ASYNC wire carries the eth domain's count to the cpu domain.

Pins: CPU_COUNT and ETH_COUNT count each domain's cycles since its reset,
ETH_SEEN is the eth count as the cpu domain last saw it, FIFO_SUM sums the
words the cpu domain's FIFO delivered since its reset.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    ASYNC,
    MAIN,
    RESET,
    Fifo,
    Inst,
    Input,
    Output,
    Reg,
    Wire,
    global_fifo,
    hw_func,
    make_clock,
    make_reset,
    uint1_t,
    uint8_t,
    uint16_t,
    vhdl,
)

cpu_rst: Wire[uint1_t] = make_reset()
cpu_clk = make_clock(100.0, name="cpu", reset=cpu_rst)
eth_rst: Wire[uint1_t] = make_reset()
eth_clk = make_clock(125.0, name="eth_rx", reset=eth_rst)
ETH_RX_CLK: Input[uint1_t] = eth_clk

BTN: Input[uint1_t, ASYNC]
ETH_RST_REQ: Input[uint1_t, ASYNC]
CPU_COUNT: Output[uint16_t]
ETH_COUNT: Output[uint16_t]
ETH_SEEN: Output[uint16_t]
FIFO_SUM: Output[uint16_t]
eth_pc: Wire[uint16_t, ASYNC]


@hw_func
def bump(x: uint8_t) -> uint8_t:
    total: Reg[uint8_t]
    total = total + x
    return total


@hw_func
def accum(x: uint8_t) -> uint16_t:
    acc: Reg[uint16_t]
    acc = acc + x
    return acc


words: Fifo[uint8_t] = global_fifo(4)
summer: Inst[accum]


# ── cpu domain ─────────────────────────────────────────────────────────


@MAIN(cpu_clk, reset=None)
def btn_sync():
    s0: Reg[uint1_t]
    s1: Reg[uint1_t]
    cpu_rst = s1
    s1 = s0
    s0 = BTN


@MAIN(cpu_clk, reset_registers="all")
def cpu_main():
    n: Reg[uint16_t]
    seen0: Reg[uint16_t]
    seen1: Reg[uint16_t]
    CPU_COUNT = n
    n = n + 1
    words.wr.stream.data = bump(1)
    words.wr.stream.valid = 1
    # The eth count through two registers: an async wire's reader synchronizes
    ETH_SEEN = seen1
    seen1 = seen0
    seen0 = eth_pc


@MAIN(cpu_clk, reset_registers="all")
def cpu_sink():
    words.rd.ready = 1
    summer.x = 0
    if words.rd.stream.valid:
        summer.x = words.rd.stream.data
    FIFO_SUM = summer.out


# ── eth domain ─────────────────────────────────────────────────────────


@hw_func
def ip_reset(req: uint1_t) -> uint1_t:
    """An IP block's reset output, active low: rst_n is 0 at power on and for
    eight cycles after a request."""
    vhdl(
        """
signal cnt : unsigned(2 downto 0) := (others => '0');
signal held : std_logic := '1';
begin
process(clk) begin
  if rising_edge(clk) then
    if req(0) = '1' then
      cnt <= (others => '0');
      held <= '1';
    elsif held = '1' then
      cnt <= cnt + 1;
      if cnt = 7 then
        held <= '0';
      end if;
    end if;
  end if;
end process;
return_output(0) <= not held;
"""
    )


@MAIN(eth_clk, reset=None)
def eth_rst_gen():
    s0: Reg[uint1_t]
    s1: Reg[uint1_t]
    rst_n: uint1_t = ip_reset(s1)
    eth_rst = ~rst_n
    s1 = s0
    s0 = ETH_RST_REQ


@MAIN(eth_clk)
def eth_main():
    pc: Reg[uint16_t, RESET]
    lr: Reg[uint8_t, RESET]
    last_lr: Reg[uint8_t]  # manual only: follows lr, never reset itself
    ETH_COUNT = pc
    eth_pc = pc
    pc = pc + 1
    last_lr = lr
    lr = bump(last_lr[0:0] + 1)
