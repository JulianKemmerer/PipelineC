# Pypeline Examples

See the [Pypeline language guide](../../docs/pypeline_guide.md) and
[getting started](../../docs/README.md) for background.

* [blink.py](blink.py) — blink an LED, the classic first hardware design (`@MAIN`, `Reg[T]`).
* [pipeline.py](pipeline.py) — a minimal pure-function pipeline (float adder) showing autopipelining.
* [vga_test_pattern.py](vga_test_pattern.py) — full worked example from the language guide: a VGA
  colour test pattern, driven to real board pins and viewable live in native simulation.
* [vga_donut.py](vga_donut.py) — a spinning 3D donut rendered to VGA.
* [float_sine.py](float_sine.py) — a from-scratch floating point `sinf` implementation.
* [dsp/](dsp) — DSP/FIR filter library examples with testbenches and plots:
  [fir_lowpass_tb.py](dsp/fir_lowpass_tb.py), [fir_decim_tb.py](dsp/fir_decim_tb.py),
  [fir_interp_tb.py](dsp/fir_interp_tb.py), and [fm_radio_decim.py](dsp/fm_radio_decim.py) (a
  synthesizable I/Q decimator pair for an SDR FM radio front end).
* [chacha20poly1305/pypeline_sim_and_wireguard.md](chacha20poly1305/pypeline_sim_and_wireguard.md) —
  write-up on using Pypeline's native simulation to verify a full-scale ChaCha20-Poly1305 design
  from the [wireguard-fpga](https://github.com/chili-chips-ba/wireguard-fpga) project.
