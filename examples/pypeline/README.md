# Pypeline Examples

See the [Pypeline language guide](../../docs/pypeline_guide.md) and
[getting started](../../docs/README.md) for background.

* [blink.py](blink.py) — blink an LED, the classic first hardware design (`@MAIN`, `Reg[T]`).
* [counter.py](counter.py) — a counter register with an extra `Output[T]` debug port, simulated
  natively, with cocotb+GHDL, or with Verilator using
  [counter_verilator_main.cpp](counter_verilator_main.cpp).
* [fsm.py](fsm.py) — a simple state machine (`@enum` state register, `@struct` outputs), its input
  driven in simulation by `@sim_input`.
* [pipeline.py](pipeline.py) — a minimal pure-function pipeline (float adder) showing auto-pipelining.
* [stream_pipeline.py](stream_pipeline.py) — a pipeline behind valid/ready stream handshakes
  (`make_stream_auto_pipeline`), connected to a producer and a consumer with global wires.
* [pico_ice/](pico_ice) — Makefile project building Pypeline designs into a bitstream for the
  pico-ice iCE40 board with open source tools (blinky, VGA PMOD test pattern).
* [arty/](arty) — Vivado project scripts building a Pypeline design into a bitstream for the Arty A7
  board (blinky + VGA PMOD test pattern).
* [vga_test_pattern.py](vga_test_pattern.py) — full worked example from the language guide: a VGA
  colour test pattern, driven to real board pins and viewable live in native simulation.
* [vga_donut.py](vga_donut.py) — a spinning 3D donut rendered to VGA.
* [float_sine.py](float_sine.py) — a from-scratch floating point `sinf` implementation.
* [dsp/](dsp) — DSP/FIR filter library examples with testbenches and plots:
  [fir_lowpass_tb.py](dsp/fir_lowpass_tb.py), [fir_decim_tb.py](dsp/fir_decim_tb.py),
  [fir_interp_tb.py](dsp/fir_interp_tb.py), and [fm_radio_decim.py](dsp/fm_radio_decim.py) (a
  synthesizable I/Q decimator pair for an SDR FM radio front end). See the
  [Pypeline DSP library guide](../../include/pypeline/dsp/pypeline_dsp_guide.md) for the library
  API these examples exercise.
* [chacha20poly1305/pypeline_sim_and_wireguard.md](chacha20poly1305/pypeline_sim_and_wireguard.md) —
  write-up on using Pypeline's native simulation to verify a full-scale ChaCha20-Poly1305 design
  from the [wireguard-fpga](https://github.com/chili-chips-ba/wireguard-fpga) project.
