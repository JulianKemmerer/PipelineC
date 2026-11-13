# Showcase

Papers, articles, talks, community projects, and selected social posts about
**Pypeline**, the HDL, and **PypelineC**, the tool, including work published under
the historical **PipelineC** name.

For more demos and code in this repository, see the [Pypeline examples](../examples/pypeline/)
and the [PipelineC examples wiki](https://github.com/JulianKemmerer/PipelineC/wiki/Examples).

Entries are newest first, using publication or event dates; announcement, sharing,
and repository creation dates are labeled where used instead, and month-only dates
reflect the available precision. Additions are welcome: link to the original
publication, recording, project, or substantial post and give it a one-sentence
description.

- **2026-10-09** (repository created) — [PipelineC Projects](https://github.com/alejandroo313/PipelineC-Projects): alejandroo313's Pypeline designs for the Tang Nano 20K include UART interfaces and several matrix-multiplication accelerators.

- **2026-10-05** — [protoemu: first prototype](https://github.com/B44ken/protoemu/releases/tag/prototype-2026-10-05): B44ken's protocol-emulator prototype uses a PipelineC-generated engine to execute programmable pin-control sequences, with simulation and verification artifacts accompanying the release.

- **2026-09-16** (repository created) — [fpgatool](https://github.com/billiegoose/fpgatool): billiegoose's build and programming wrapper combines PypelineC with a pinned Nix/OpenXC7 environment for the Basys 3 board.

- **2026-08-25** (repository created) — [Asgard](https://github.com/billiegoose/asgard): billiegoose's executable model of the THOR language includes a synthesizable RED2 reduction machine written in Pypeline.

- **2026-07** — [High-Throughput ChaCha20-Poly1305 Accelerator for WireGuard VPN Using PipelineC](https://doi.org/10.1109/HSI70218.2026.11773138): Nikola Sokolović, Julian Kemmerer, and Enio Kaljić's HSI2026 paper presents a PipelineC accelerator for WireGuard's ChaCha20-Poly1305 authenticated encryption.

- **2026-06-15** (announcement) — [Introducing Pypeline HDL](https://fosstodon.org/@pipelinec/116755103775698969): Julian Kemmerer introduces the Python front end with a simulation image and code, with more explanation in the [Reddit discussion](https://www.reddit.com/r/FPGA/comments/1u6lfe0/pypeline_hdl_a_new_python_frontend_for_pipelinec/).

- **2026-05-14** — [A SoC in C? StreamSoC FPGA real-time audio video project](https://www.youtube.com/watch?v=dzF3okigyog): This short video demonstrates music visualization and video feedback on the StreamSoC FPGA system.

- **2026-03-14** ([announcement](https://fosstodon.org/@pipelinec/116227966087388271)) — [WireGuard FPGA](https://github.com/chili-chips/wireguard-fpga): This mirror of Chili.CHIPS' open-source VPN hardware project includes ChaCha20-Poly1305 cores written in Pypeline and historical PipelineC alongside Ethernet and RISC-V components.

- **2026-02-11** — [Results from the Advent of FPGA Challenge](https://blog.janestreet.com/advent-of-fpga-challenge-2025-results/): Jane Street's competition roundup names PipelineC among the languages used to implement Advent of Code solutions in hardware.

- **2025-08-07** (shared) — [Software, FPGA Execution, a PipelineC response](https://fosstodon.org/@pipelinec/114989640078587298): Julian Kemmerer shares an illustrated [Reddit explanation](https://www.reddit.com/r/FPGA/comments/1mcezqx/software_fpga_execution_a_pipelinec_response/) of how sequential-looking code describes combinational logic, clock cycles, and pipelines.

- **2025-07-24** (shared) — [How to send a struct from one dev board to another?](https://fosstodon.org/@pipelinec/114910312453651498): This [design walkthrough](https://www.reddit.com/r/FPGA/comments/1m8gl5o/how_to_send_a_struct_from_one_dev_board_to_another/) carries stereo audio between iCE40 and Artix-7 boards over Ethernet, explaining serialization, handshakes, and clock-domain crossings.

- **2025-03-14** — [16-APSK Modulator on FPGA using PipelineC HDL](https://www.linkedin.com/pulse/16-apsk-modulator-fpga-using-pipelinec-hdl-paulo-dutra-79uce): Paulo Dutra walks through an ULX3S modulator with CIC interpolation, digital upconversion, a delta-sigma DAC, and measurements from the hardware.

- **2025-02-13** (repository created) — [pipeline-nim-gpu](https://github.com/fl4shk/pipeline-nim-gpu): fl4shk's work-in-progress fixed-function GPU explores a Nim-to-PipelineC route from a software 3D renderer to hardware.

- **2025-01-26** — [ULX3S GPU demonstration](https://www.linkedin.com/posts/paulo-henrique-dutra_pipelinec-fpga-ulx3s-activity-7289079564092215296-EvNL): Paulo Dutra shows a PipelineC rasterizer with fixed-point arithmetic, a block-RAM framebuffer, DVI output, and software and Verilator simulations.

- **2025-01-18** — [Introduction to PipelineC](https://www.youtube.com/watch?v=wWdvuAQXeS0): Julian Kemmerer's tutorial uses the pico-ice board and an open-source toolchain to introduce LED, UART, and VGA designs.

- **2025-01-10** — [CPU cache-controller simulation](https://www.linkedin.com/posts/paulo-henrique-dutra_pipelinec-cpu-riscv-activity-7283613982144237569-pMZx): Paulo Dutra demonstrates a PipelineC two-way set-associative cache controller with AXI-Lite memory access and an instruction-fetch test harness.

- **2024-11-08** — [A SoC in C: PipelineC HDL and RISC-V](https://docs.google.com/presentation/d/e/2PACX-1vTq_OBXkCZ7wBW3qIMDTh55j0FB8w0hHHSCR16SCR8G3qS5QIDEcL-aZhrrkgxP4fehcs-KFkOIVYVL/pub): Julian Kemmerer's slides from the [First Annual Soft RISC-V Systems Workshop](https://sites.google.com/view/srvs-workshop) introduce the use of PipelineC for a RISC-V system on chip.

- **2024-06-28** — [Next level project ideas with PipelineC](https://www.reddit.com/r/FPGA/comments/1dqoi5o/next_level_project_ideas_with_pipelinec/): This community roundup collects graphics, radio, neural-network, networking, and processor demonstrations with links to their creators' posts.

- **2024-05-19** — [Taking the CPU out of the graphics rendering loop](https://fosstodon.org/@pipelinec/112468752689096075): Julian Kemmerer shows a graphics experiment connecting the compute pipeline directly to DDR memory for DMA-style rendering.

- **2024-03-03** — [PipelineC: Easier hardware description between RTL and HLS](https://www.youtube.com/watch?v=Tyr7is7xwbw): Julian Kemmerer's [HAFDAL 2024 talk](https://haflang.github.io/workshops/hafdal24.html) presents the language's approach to hardware description and automatic pipelining.

- **2024-03-03** — [FM radio receiver on an FPGA](https://fosstodon.org/@pipelinec/112032926019910036): Julian Kemmerer demonstrates FM radio demodulation on Deepwave Digital's FPGA SDR hardware, with contributions from Paulo Dutra and Darkknight512.

- **2023-09-25** (repository created) — [hls4ml PipelineC testbench](https://github.com/JochiSt/hls4ml_pipelineC_test): JochiSt's experimental project contains neural-network training and conversion scripts configured to exercise a PipelineC backend for hls4ml.

- **2023-08-18** (repository created) — [icebreaker-pipelineC](https://github.com/JochiSt/icebreaker-pipelineC): JochiSt's iCEBreaker project demonstrates a PipelineC LED design built with GHDL, Yosys, and nextpnr.

- **2023-06** — [Modular Hardware Design with Timeline Types](https://www.cs.cornell.edu/~asampson/media/papers/filament-pldi2023-preprint.pdf): Rachit Nigam, Pedro Henrique Azevedo de Amorim, and Adrian Sampson's PLDI paper includes importing PipelineC-generated designs into Filament using timing-aware type signatures.

- **2023-04-26** — [Game of Life in FPGA](https://fosstodon.org/@pipelinec/110267516142782531): This video demonstrates an experimental adaptation of multithreaded C code using PipelineC-derived state machines and shared-resource buses.

- **2023-03-26** — [PipelineC: Easier Hardware Description Between RTL and HLS](https://capra.cs.cornell.edu/latte23/paper/1.pdf): Julian Kemmerer's [LATTE 2023](https://capra.cs.cornell.edu/latte23/) paper and [short presentation](https://www.youtube.com/watch?v=uDYx7VfJ78o) explain the C-like HDL, automatic pipelining, state machines, and clock crossings.

- **2023-02-10** — [A 3D raytraced game with open source C to FPGA toolchain](https://blog.adafruit.com/2023/02/10/a-3d-raytraced-game-with-open-source-c-to-fpga-toolchain-faming-fpga-opensource-yosyshq/): Adafruit highlights Sphery vs. Shapes and the open-source CflexHDL/PipelineC workflow behind its FPGA implementation.

- **2023-02-03** — [3D raytraced game with open source C to FPGA toolchain](https://blog.yosyshq.com/p/3d-raytracing/): Victor Suarez Rovere and Julian Kemmerer explain how CflexHDL, PipelineC, GHDL, Yosys, and nextpnr produce the Sphery vs. Shapes game on an ECP5 FPGA.

- **2022-11-03** — [PipelineC: Easy open-source hardware description between RTL and HLS](https://woset-workshop.github.io/PDFs/2022/17-Kemmerer-poster.pdf): Julian Kemmerer's [WOSET 2022](https://woset-workshop.github.io/WOSET2022.html#article-17) poster and [recorded presentation](https://www.youtube.com/watch?v=TyVDZG56pCQ) introduce the language and its place in an open-source hardware toolchain.

- **2022-10** — [Applying FPGA Runtime Reconfiguration to Multi-Hash Proof-of-Work Algorithms](https://cgi.cse.unsw.edu.au/~odiessel/papers/mphilwu.pdf): Tong Wu's UNSW MPhil thesis compares PipelineC, Vitis HLS, and manually designed Chisel pipelines for cryptographic algorithms.

- **2022-09-28** — [3D game running on FPGA shown to be 50x more efficient than on x86 hardware](https://www.cnx-software.com/2022/09/28/3d-game-fpga-50x-more-efficient-x86-hardware/): Jean-Luc Aufranc's CNX Software article covers Sphery vs. Shapes, its CflexHDL/PipelineC implementation, and the authors' energy-efficiency comparison.

- **2022-09-27** — [Sphery vs. Shapes](https://www.youtube.com/watch?v=hn3sr3VMJQU): Victor Suarez Rovere's gameplay video shows the interactive raytraced FPGA game implemented with CflexHDL and PipelineC.

- **2022-06-01** — [PipelineC Overview + FPGA Graphics Demo](https://www.youtube.com/watch?v=41nqzbSqBbA): This recorded CIRCT community talk introduces PipelineC and demonstrates its use for FPGA graphics.

- **2020-11-05** — [Program FPGAs in C: Blink LEDs Example](https://www.youtube.com/watch?v=UJYEon7NRSk): This early PipelineC video walks through a blinking-LED hardware design.

- **2020-10-26** — [PipelineC brings HLS to non-Xilinx FPGAs](https://nuclearrambo.com/wordpress/pipelinec-brings-hls-to-non-xilinx-fpgas/): Nuclear Rambo's tutorial covers installation, generating an LED design, and integrating the generated VHDL into a Zybo project in Vivado.

- **2020-08-16** — [Write In PipelineC For FPGAs](https://hackaday.com/2020/08/16/write-in-pipelinec-for-fpgas/): Elliot Williams introduces PipelineC's C-like hardware description and automatic pipelining to Hackaday readers.
