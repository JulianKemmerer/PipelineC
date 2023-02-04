![pipelinec_color](./docs/images/pipelinec_color.jpg)

```
██████╗ ██╗██████╗ ███████╗██╗     ██╗███╗   ██╗███████╗ ██████╗
██╔══██╗██║██╔══██╗██╔════╝██║     ██║████╗  ██║██╔════╝██╔════╝
██████╔╝██║██████╔╝█████╗  ██║     ██║██╔██╗ ██║█████╗  ██║     
██╔═══╝ ██║██╔═══╝ ██╔══╝  ██║     ██║██║╚██╗██║██╔══╝  ██║     
██║     ██║██║     ███████╗███████╗██║██║ ╚████║███████╗╚██████╗
╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝ ╚═════╝
```

*Please feel free to message - very happy to make PipelineC work for you! Always looking for help as well.* -Julian

# Getting Started

Get started by [reading the wiki](https://github.com/JulianKemmerer/PipelineC/wiki).

# What is PipelineC?

A C-like(1) hardware description language (HDL)(2) adding high level synthesis(HLS)-like automatic pipelining(3) as a language construct/compiler feature.

1. [Not actually regular C](https://en.wikipedia.org/wiki/C_to_HDL). But can be partly compiled by gcc/llvm for doing basic functional verification/'simulation'. Reach out if interested in developing more complex language syntax!
2. Can reasonably replace Verilog/VHDL. Compiler produces synthesizable and human readable+debuggable VHDL. Hooks exist for inserting raw VHDL / existing IP / black boxes.
3. If a computation can be written as a [pure function](https://en.wikipedia.org/wiki/Combinational_logic) without side effects (i.e. no global/static variables) then it will be autopipelined. 
   Conceptually similar to technologies like [Intel's variable latency Hyper-Pipelining](https://www.intel.com/content/www/us/en/programmable/documentation/jbr1444752564689.html#esc1445881961208)
   and [Xilinx's retiming options](https://www.xilinx.com/support/answers/65410.html). 
   Sharing some of the compiler driven pipelining design goals of [Google's XLS Project](https://google.github.io/xls/), the [DFiantHDL language](https://dfianthdl.github.io/), and certain [CIRCT](https://circt.llvm.org/) dialects as well.

# What is PipelineC not?

* High level synthesis of arbitrary C code with a global memory model / threads / etc:
  * Cannot do 'nested loops to a memory architecture' for you.
* Compiled C based hardware simulator:
  * Only _parts_ of PipelineC code can be compiled by C compilers and run (is encouraged).
  * But entire multi-module, multi-clock-domain, etc whole designs cannot simply be compiled and run like regular C programs.
* Meta-programming hardware-generator (ex. uses C type system and preprocessor).
* Stitching tool automating the build flow from code/modules to bitstream:
  * Tool does partially automate synthesis runs but automation to final bitstream is left to the user.

# Core Features/Benefits

_An easy to understand hardware description language with a powerful autopipelining compiler and growing set of real life hardware design inspired features._

* Familiar C syntax that eliminates many HDL quirks that beginners (and experts) can fall victim to (ex. blocking/nonblocking assignments, reasoning about the sequential ordering of combinatorial logic).
* Compatible with all HDL simulators. Ex. Can start Modelsim in seconds and imports human readable+debuggable VHDL w/ working printf's. Can also craft custom ultra-fast compiled C based 'simulations'. Conversion to Verilog is also included as needed, i.e. for Verilator.
* Helpful timing feedback derived from synthesis tool reports to help identify critical path logic that cannot be automatically pipelined - especially helpful for those new to digital logic design.
* Integrates with software side C easily; helpful built in code generation. (ex. for un/packing structs from de/serialized byte arrays when moving data from host<->FPGA).
* A full hardware description language replacement. Can start by cloning existing VHDL/Verilog designs or including raw VHDL - not forced to use entire language at all times.
* Globally visible point-to-point wires, multi-rate/width clock domain crossings, and complex derived FSMs, are just some of the growing list of composability features inspired by real life hardware design requirements/tasks.
* Automatic pipelining as a feature of the compiler. Basic use of the tool can be to generate single pipelines to drop into existing designs elsewhere. Eliminate the practice of pipelining logic by hand = not portable (relies on operating frequency and part).

Fundamental design elements are state machines/stateful elements(registers, rams, etc), auto-pipelined stateless pure functions, and interconnects (wires,cdc,async fifos,etc). Designs can be structured to look like 'communicating sequential processes/threads' as needed.

By isolating complex logic into autopipelineable functions, and only writing literal clock by clock hardware description when absolutely necessary, PipelineC designs do not need to be rewritten for each new target device / operating frequency.
The hope is to build shared, high performance, device agnostic, hardware designs described in a familiar and powerfully composable C language look.

For software folks writing PipelineC should feel like solving a programming puzzle in C - the rules of the puzzle hide/imply hardware concepts. For hardware folks PipelineC is a better hardware description language trying to find middle ground between traditional RTL and HLS. It is my language of choice as an FPGA engineer :).
