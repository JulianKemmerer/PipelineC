```
██████╗ ██╗██████╗ ███████╗██╗     ██╗███╗   ██╗███████╗ ██████╗
██╔══██╗██║██╔══██╗██╔════╝██║     ██║████╗  ██║██╔════╝██╔════╝
██████╔╝██║██████╔╝█████╗  ██║     ██║██╔██╗ ██║█████╗  ██║     
██╔═══╝ ██║██╔═══╝ ██╔══╝  ██║     ██║██║╚██╗██║██╔══╝  ██║     
██║     ██║██║     ███████╗███████╗██║██║ ╚████║███████╗╚██████╗
╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝ ╚═════╝
```

*Please feel free to message - very happy to make PipelineC work for you! Always looking for help as well.* -Julian

Get started by reading the [wiki](https://github.com/JulianKemmerer/PipelineC/wiki).

# What is PipelineC?

A C-like(1) hardware description language (HDL)(2) adding high level synthesis(HLS)-like automatic pipelining(3) as a language construct/compiler feature.

1. [Not actually regular C](https://en.wikipedia.org/wiki/C_to_HDL). But mostly compileable by gcc for doing basic functional verification/'simulation'.
   This is for convenience as a familiar bare minimum language prototype, not as an ideal end goal. Reach out to help develop something more complex together!
2. Can reasonably replace Verilog/VHDL. Compiler produces synthesizable and human readable+debuggable VHDL. Hooks exist for inserting raw VHDL / existing IP / black boxes.
3. If a computation can be written as a [pure function](https://en.wikipedia.org/wiki/Combinational_logic) without side effects (i.e. no global/static variables) then it will be autopipelined. 
   Conceptually similar to technologies like [Intel's variable latency Hyper-Pipelining](https://www.intel.com/content/www/us/en/programmable/documentation/jbr1444752564689.html#esc1445881961208)
   and [Xilinx's retiming options](https://www.xilinx.com/support/answers/65410.html). 
   Sharing some of the compiler driven pipelining design goals of [Google's XLS Project](https://google.github.io/xls/) and the [DFiantHDL language](https://dfianthdl.github.io/) as well.

# What is PipelineC not?

* High level synthesis of arbitrary C code with a global memory model / threads / etc.
* Meta-programming hardware-generator (ex. uses C type system and preprocessor).

# Core Features/Benefits

_An easy to understand hardware description language with a powerful autopipelining compiler and growing set of real life hardware design inspired features._

* Familiar C syntax that eliminates many HDL quirks that beginners (and experts) can fall victim to (ex. blocking/nonblocking assignments, reasoning about the sequential ordering of combinatorial logic).
* Simulate your code in seconds, debug with printf's (tool imports human readable+debuggable VHDL into Modelsim - can also imagine custom C based simulation is within reach as well)
* Helpful timing feedback derived from synthesis tool reports to help identify critical path logic that cannot be automatically pipelined - especially helpful for those new to digital logic design.
* Integrates with software side C easily; helpful built in code generation. (ex. for un/packing structs from de/serialized byte arrays when moving data from host<->FPGA).
* A full hardware description language replacement. Can start by cloning existing VHDL/Verilog designs or including raw VHDL - not forced to use entire language at all times.
* Globally visible point-to-point wires, multi-rate/width clock domain crossings, inferred clock enable nested FSMs, are just some of the growing list of composability features inspired by real life hardware design requirements/tasks.
* Automatic pipelining as a feature of the compiler. Basic use of the tool can be to generate single pipelines to drop into existing designs elsewhere. Eliminate the practice of pipelining logic by hand = not portable (relies on operating frequency and part).

Fundamental design elements are state machines/stateful elements(registers, rams, etc), auto-pipelined stateless pure functions, and interconnects (wires,cdc,async fifos,etc).

By isolating complex logic into autopipelineable functions, and only writing literal clock by clock hardware description when absolutely necessary, PipelineC designs do not need to be rewritten for each new target device / operating frequency.
The hope is to build shared, high performance, device agnostic, hardware designs described in a familiar and powerfully composable C language look.

For software folks I want writing PipelineC to feel like solving a programming puzzle in C, not a whole new paradigm of programming languages.
The rules of the puzzle hide/imply hardware concepts. For hardware folks I want PipelineC to be a better hardware description language (it is my language of choice as an FPGA engineer :) ).

```
Currently Supported Tools (tested on Linux):
Synthesis: Xilinx Vivado, Intel Quartus, Lattice Diamond, GHDL+Yosys+nextpnr, Efinix Efinity
Simulation: Modelsim
```
