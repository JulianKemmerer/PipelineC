# ice_makefile_pipelinec

Example project using a standard [Makefile](https://en.wikipedia.org/wiki/Make_%28software%29)
to build a project that can be loaded onto the board.

It needs [oss-cad-suite](https://github.com/YosysHQ/oss-cad-suite-build) installed.
See the [doc](https://pico-ice.tinyvision.ai/using_oss_cad_suite.html) for more.

Build with `make` and deploy it to the pico-ice with `make prog_pico`, and `make gateware.uf2` to generate an
[uf2 image](https://pico-ice.tinyvision.ai/programming_the_fpga.html#using-a-drag-drop-or-file-copy-scheme)
to program with drag-and-drop.

If your design does not meet the default 12MHz timing, `nextpnr` will fail with an error like:
`ERROR: Max frequency for clock 'clk_12p0$SB_IO_IN_$glb_clk': XX.XX MHz (FAIL at 12.00 MHz)`.

A very complete `Makefile` example is provided for the UPduino v3 by Xark:
<https://github.com/XarkLabs/upduino-example/>

# PipelineC Specific

Linux only for now.

For more information check out [dev board setup info](https://github.com/JulianKemmerer/PipelineC/wiki/Dev-Board-Setup).

Clone the PipelineC repo:
`git clone https://github.com/JulianKemmerer/PipelineC.git`

Set `PIPELINEC_REPO` environment variable expected by make flow.

Ex. `make clean all PIPELINEC_REPO=/path/to/PipelineC OSS_CAD_SUITE=/path/to/oss-cad-suite && sudo make prog_pico OSS_CAD_SUITE=/path/to/oss-cad-suite`

See more example build command lines at the top of `Makefile`.

## Top Level IO
For now top level IO configuration needs to match across three files:
1) `top.h` (for PipelineC build)
2) `top.sv` pins on the PipelineC output HDL instance (for yosys build)
3) `ice40.pcf` (for nextpnr build)

When changing the top level pinout in `top.h`, you may need to manually update wrapper `top.sv` and `ice40.pcf` to match.

## Clocks
This design has been setup to work with at a single clock rate `PLL_CLK_MHZ`.

A `Makefile` variable exists to specify the target rate, ex. `PLL_CLK_MHZ = 25.0`.

Critically this variable is used to:
1) Invoke PipelineC with the expected constant in code
  * `echo "#define PLL_CLK_MHZ $(PLL_CLK_MHZ)\n" > pipelinec_makefile_config.h`
2) Generate Verilog for the `pll.v` module using `icepll`
  * ex. `$(ICEPLL) -q -i 12 -o $(PLL_CLK_MHZ) -p -m -f pll.v`
  * If the file name has changes from `pll.v` then the yosys commandline in `Makefile` needs to be updated with new pll file name.
3) Inform `nextpnr-ice40` of the target clock frequency
  * `--freq $(PLL_CLK_MHZ)` argument

##Demos - see make file for more info
1) Pong
2) Ethernet
3) Risc-v


