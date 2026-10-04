# pico-ice Pypeline example

A [Makefile](https://en.wikipedia.org/wiki/Make_%28software%29) project that builds a
Pypeline design into a bitstream for the [pico-ice](https://pico-ice.tinyvision.ai/) and
pico2-ice boards (Lattice iCE40 UltraPlus 5K FPGA). It is the Pypeline version of
[ice_makefile_pipelinec](../../pico-ice/ice_makefile_pipelinec), which in turn is based on
the pico-ice SDK's
[ice_makefile_blinky](https://github.com/tinyvision-ai-inc/pico-ice-sdk/tree/main/examples/ice_makefile_blinky).

For the bigger picture see
[Getting Started on a Dev Board](../../../docs/README.md#getting-started-on-a-dev-board).

## Build and program

Linux only for now. Install the [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build)
and point `OSS_CAD_SUITE` at it (see the pico-ice docs on
[programming the FPGA](https://pico-ice.tinyvision.ai/md_programming__the__fpga.html)).
From this directory:

```
make clean all OSS_CAD_SUITE=/path/to/oss-cad-suite && make prog_pico OSS_CAD_SUITE=/path/to/oss-cad-suite
```

`make prog_pico` uploads `gateware.bin` with `dfu-util` (using `sudo`). For the
pico2-ice use `make prog_pico2`, which copies the bitstream over with `mpremote`
(`pip3 install mpremote`). After a build, `make gateware.uf2` makes a UF2 image to
[program by drag-and-drop](https://pico-ice.tinyvision.ai/md_programming__the__fpga.html)
(needs `bin2uf2` on the `PATH`). `PIPELINEC_REPO` is only needed if this directory is copied out of the
PipelineC repo.

| Design | Command | What it does |
|---|---|---|
| [top.py](top.py) | `make clean all` | Blinks the red channel of the RGB LED once a second |
| [vga_top.py](vga_top.py) | `make clean all PYPELINE_TOP_FILE=vga_top.py` | 640x480 VGA test pattern on a 12-bit VGA PMOD plugged into PMOD0+PMOD1 |

## What the Makefile does

1. `pypelinec` turns the `.py` design into VHDL, listed in
   `pypeline_output/vhdl_files.txt`. The generated top-level module is named
   `pypeline_top` (`--top pypeline_top`). The `--comb --no_synth` flags skip
   Pypeline's own timing-driven synthesis runs, which a blinking LED doesn't need.
2. `icepll` writes `pll.v`, a PLL that makes `PLL_CLK_MHZ` from the board's 12 MHz clock.
3. GHDL (as a Yosys plugin) reads the VHDL, Yosys reads the [top.sv](top.sv) wrapper and
   `pll.v`, and `synth_ice40` writes a `.json` netlist.
4. `nextpnr-ice40` places and routes the netlist using the [ice40.pcf](ice40.pcf) pin
   constraints, writing an `.asc` file.
5. `icepack` converts the `.asc` file into the `gateware.bin` bitstream.

## Top level IO

The top-level IO has to match across three files:

1. The `.py` design: `Input[T]`/`Output[T]` names become top-level port names, for
   example `ICE_41: Output[uint1_t]` for the red LED.
2. [top.sv](top.sv): instantiates the PLL and the Pypeline generated `pypeline_top`,
   connecting ports to the same-named wires with the `.*` wildcard.
3. [ice40.pcf](ice40.pcf): which FPGA pin each top.sv port uses (for nextpnr).

`top.sv` and `ice40.pcf` already list every pin used by the pico-ice examples, so
using another of those pins is usually just one `Input`/`Output` declaration named after
the pin in the `.py` design. Pins not in that list need adding to all three files. The
`board.pico_ice.vga_pmod01` module that [vga_top.py](vga_top.py) imports declares its
PMOD pins this way.

## Clocks

The design runs on one clock, from a PLL, at `PLL_CLK_MHZ` (default `25.0`):

```
make clean all PLL_CLK_MHZ=16.0
```

The Makefile uses that one variable to:

1. Generate `pll.v` with `icepll`. `icepll` picks the closest rate it can make; the
   "Achieved output frequency" comment at the top of `pll.v` shows it.
2. Export `PLL_CLK_MHZ` to `pypelinec`. The design is plain Python, so it reads the rate
   with `os.environ` and uses it in `make_clock(PLL_CLK_MHZ)` and `@MAIN(PLL_CLK_MHZ)`.
   `make_clock` names the clock port `pll_clk` to match the wrapper, rather than the
   default rate-derived name such as `clk_25p0`.
3. Tell `nextpnr-ice40` the target clock rate (`--freq $(PLL_CLK_MHZ)`).

The PLL's `locked` output is the `pll_locked` input; [top.py](top.py) holds its logic in
reset until it goes high. [vga_top.py](vga_top.py) needs the 25 MHz VGA pixel clock and
stops with an error for any other `PLL_CLK_MHZ`.

If the design does not meet timing at `PLL_CLK_MHZ`, `nextpnr` fails with an error like:

```
ERROR: Max frequency for clock 'pll_clk_$glb_clk': 59.73 MHz (FAIL at 100.00 MHz)
```

A very complete `Makefile` example is provided for the UPduino v3 by Xark:
<https://github.com/XarkLabs/upduino-example/>
