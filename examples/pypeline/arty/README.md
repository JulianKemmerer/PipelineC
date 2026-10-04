# Arty A7 Pypeline example

Builds a Pypeline design into a bitstream for the
[Digilent Arty A7](https://digilent.com/reference/programmable-logic/arty-a7/start)
(Xilinx Artix-7 FPGA) with Vivado. [top.py](top.py) blinks RGB LED 0 and draws a
640x480 VGA test pattern on a 12-bit VGA PMOD plugged into PMOD headers JA and JB. It is
the Pypeline version of the [PipelineC Arty examples](../../arty).

For the bigger picture see
[Getting Started on a Dev Board](../../../docs/README.md#getting-started-on-a-dev-board).

## Build and program

Linux only for now. With `vivado` on the `PATH` (or `VIVADO=/path/to/vivado`), from this
directory:

```
make clean all && make prog
```

`make prog` loads `board.bit` into the FPGA over the board's USB cable (volatile: it is
lost at power off). For an Arty A7-100T, switch [top.py](top.py) to
`import board.arty.part100t` and build with `make clean all PART=xc7a100tcsg324-1`.
`PIPELINEC_REPO` is only needed if this directory is copied out of the PipelineC repo.

The Makefile:

1. Runs `pypelinec` on the design, writing the VHDL and a `read_vhdl.tcl` script that
   adds it to Vivado into `pypeline_output/`. The `--comb --no_synth` flags skip
   Pypeline's own timing-driven synthesis runs, which this design doesn't need.
2. Runs Vivado in batch mode on [build.tcl](build.tcl): reads the generated VHDL, the
   [board.vhd](board.vhd) wrapper, and the [arty.xdc](arty.xdc) pin constraints, then
   synthesizes, places, routes and writes `board.bit`, plus `utilization.rpt` and
   `timing_summary.rpt` reports.

Prefer the Vivado GUI? Make a new project for your part, add `board.vhd` and
`arty.xdc`, then in the Tcl console run `source pypeline_output/read_vhdl.tcl` and click
Generate Bitstream. Program the board from the
[Hardware Manager](https://digilent.com/reference/programmable-logic/guides/vivado-hardware-manager).

## Top level IO

The top-level IO has to match across three files:

1. [top.py](top.py): `Input[T]`/`Output[T]` names become top-level port names, for
   example `led0_b: Output[uint1_t]`. The imported `board.arty.vga_pmod_ja_jb` module
   declares the `ja_0`...`jb_5` VGA PMOD ports the same way.
2. [board.vhd](board.vhd): the top-level entity named `board`, with one port per board
   pin. It instantiates the PLL and the Pypeline generated `top` entity, and its
   `top_inst` port map connects them.
3. [arty.xdc](arty.xdc): which FPGA pin each `board` port uses, copied from Digilent's
   master `.xdc` files. Uncomment more lines from
   [Arty-A7-35-Master.xdc](../../arty/Arty-A7-35-Master.xdc) to add pins.

A 1-bit Pypeline port is a VHDL `unsigned(0 downto 0)`, so the port map connects its
single element, as in `led0_b(0) => led0_b`.

## Clocks

Every `@MAIN` in [top.py](top.py) runs at 25 MHz, so the generated top level has one
clock input named after that rate, `clk_25p0`. [board.vhd](board.vhd) makes the 25 MHz
clock from the board's 100 MHz `CLK100MHZ` with an `MMCME2_BASE` PLL primitive and passes
its `LOCKED` output in as `pll_locked`, which holds the blinking logic in reset until the
clock is stable. Changing the rate of a `@MAIN` changes the clock port name, so the PLL
settings and the port map need updating too. To pick a fixed clock port name instead,
see [`make_clock`](../../../docs/pypeline_guide.md#naming-a-clock-with-make_clock), as used
by the [pico-ice example](../pico_ice).

Vivado derives the 25 MHz clock's timing constraint from the 100 MHz `create_clock` in
`arty.xdc`. `pypeline_output/clocks.xdc` constrains `clk_25p0` as a top-level input pin,
which only applies when the generated `top` is itself the top level, so `build.tcl` does
not read it.
