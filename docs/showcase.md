# Showcase

Community projects, papers, articles, talks, and selected social media posts. Show me what you got.

For more code see [Pypeline examples](../examples/pypeline/)
and the old [PipelineC examples wiki](https://github.com/JulianKemmerer/PipelineC/wiki/Examples).

* **2026-07**: [High-Throughput ChaCha20-Poly1305 Accelerator for WireGuard VPN Using PipelineC](https://ieeexplore.ieee.org/document/11773138): Nikola Sokolović, and Enio Kaljić's HSI2026 paper describes the ChaCha20-Poly1305 accelerator in Chili.CHIPS' [WireGuard FPGA project](https://github.com/chili-chips/wireguard-fpga), which includes Pypeline and historical PipelineC implementations.

* **2026-02-11**: [Results from the Advent of FPGA Challenge](https://blog.janestreet.com/advent-of-fpga-challenge-2025-results/): Jane Street's competition roundup names PipelineC among the languages used to implement Advent of Code solutions in hardware.

* **2025-03-14**: [16-APSK Modulator on FPGA using PipelineC HDL](https://www.linkedin.com/pulse/16-apsk-modulator-fpga-using-pipelinec-hdl-paulo-dutra-79uce): Paulo Dutra walks through an ULX3S modulator with CIC interpolation, digital upconversion, a delta-sigma DAC, and measurements from the hardware.

* **2025-01-26**: [ULX3S GPU demonstration](https://www.linkedin.com/posts/paulo-henrique-dutra_pipelinec-fpga-ulx3s-activity-7289079564092215296-EvNL): Paulo Dutra shows a PipelineC rasterizer with fixed-point arithmetic, a block-RAM framebuffer, DVI output, and software and Verilator simulations.

* **2025-01-18**: [Introduction to PipelineC](https://www.youtube.com/watch?v=wWdvuAQXeS0): tutorial uses the pico-ice board and an open-source toolchain to introduce LED, UART, and VGA designs.

* **2025-01-10**: [CPU cache-controller simulation](https://www.linkedin.com/posts/paulo-henrique-dutra_pipelinec-cpu-riscv-activity-7283613982144237569-pMZx): Paulo Dutra demonstrates a PipelineC two-way set-associative cache controller with AXI-Lite memory access and an instruction-fetch test harness.

* **2024-11-08**: [A SoC in C: PipelineC HDL and RISC-V](https://docs.google.com/presentation/d/e/2PACX-1vTq_OBXkCZ7wBW3qIMDTh55j0FB8w0hHHSCR16SCR8G3qS5QIDEcL-aZhrrkgxP4fehcs-KFkOIVYVL/pub): slides from the [First Annual Soft RISC-V Systems Workshop](https://sites.google.com/view/srvs-workshop) introduce the use of PipelineC for a RISC-V system on chip.

* **2024-03-03**: [PipelineC: Easier hardware description between RTL and HLS](https://www.youtube.com/watch?v=Tyr7is7xwbw): [HAFDAL 2024 talk](https://haflang.github.io/workshops/hafdal24.html) presents the language's approach to hardware description and automatic pipelining.

* **2023-06**: [Modular Hardware Design with Timeline Types](https://www.cs.cornell.edu/~asampson/media/papers/filament-pldi2023-preprint.pdf): Rachit Nigam, Pedro Henrique Azevedo de Amorim, and Adrian Sampson's PLDI paper includes importing PipelineC-generated designs into Filament using timing-aware type signatures.

* **2023-03-26**: [PipelineC: Easier Hardware Description Between RTL and HLS](https://capra.cs.cornell.edu/latte23/paper/1.pdf): [LATTE 2023](https://capra.cs.cornell.edu/latte23/) [paper](LATTE23.pdf) and [short presentation](https://www.youtube.com/watch?v=uDYx7VfJ78o) explain the C-like HDL, automatic pipelining, state machines, and clock crossings.

* **2023-02-10** (latest linked coverage): [Sphery vs. Shapes](https://github.com/JulianKemmerer/PipelineC-Graphics): Victor Suarez Rovere's raytraced FPGA game uses CflexHDL and PipelineC, with a [YosysHQ implementation article](https://blog.yosyshq.com/p/3d-raytracing/), [gameplay video](https://www.youtube.com/watch?v=hn3sr3VMJQU), and coverage from [Adafruit](https://blog.adafruit.com/2023/02/10/a-3d-raytraced-game-with-open-source-c-to-fpga-toolchain-faming-fpga-opensource-yosyshq/) and [CNX Software](https://www.cnx-software.com/2022/09/28/3d-game-fpga-50x-more-efficient-x86-hardware/).

* **2022-11-03**: [PipelineC: Easy open-source hardware description between RTL and HLS](https://woset-workshop.github.io/PDFs/2022/17-Kemmerer-poster.pdf): [WOSET 2022](https://woset-workshop.github.io/WOSET2022.html#article-17) poster and [recorded presentation](https://www.youtube.com/watch?v=TyVDZG56pCQ) introduce the language and its place in an open-source hardware toolchain.

* **2022-10**: [Applying FPGA Runtime Reconfiguration to Multi-Hash Proof-of-Work Algorithms](https://cgi.cse.unsw.edu.au/~odiessel/papers/mphilwu.pdf): Tong Wu's UNSW MPhil thesis compares PipelineC, Vitis HLS, and manually designed Chisel pipelines for cryptographic algorithms.

* **2022-06-01**: [PipelineC Overview + FPGA Graphics Demo](https://www.youtube.com/watch?v=41nqzbSqBbA): This recorded CIRCT community talk introduces PipelineC and demonstrates its use for FPGA graphics.

* **2020-10-26**: [Tutorial Zybo Project](https://nuclearrambo.com/wordpress/pipelinec-brings-hls-to-non-xilinx-fpgas/): Nuclear Rambo's tutorial covers installation, generating an LED design, and integrating the generated VHDL into a Zybo project in Vivado.

* **2020-08-16**: [Write In PipelineC For FPGAs](https://hackaday.com/2020/08/16/write-in-pipelinec-for-fpgas/): Elliot Williams introduces PipelineC's C-like hardware description and automatic pipelining to Hackaday readers.
