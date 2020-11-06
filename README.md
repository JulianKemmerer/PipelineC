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

A C-like(1) hardware description language (HDL)(2) adding automatic pipelining(3) as an additional language construct/compiler feature.

1. [Not actually regular C](https://en.wikipedia.org/wiki/C_to_HDL). But mostly compileable by gcc for doing basic functional verification/'simulation'.
   This is for convenience as a familiar bare minimum language prototype, not as an ideal end goal. Reach out to help develop something more complex together!
2. Can reasonably replace Verilog/VHDL. Compiler produces synthesizable and somewhat human readable VHDL. Hooks exist for inserting raw VHDL / black boxes.
3. If a computation can be written as a [pure function](https://en.wikipedia.org/wiki/Combinational_logic) without side effects (i.e. no global/static variables) then it will be autopipelined. 
   Conceptually similar to technologies like [Intel's variable latency Hyper-Pipelining](https://www.intel.com/content/www/us/en/programmable/documentation/jbr1444752564689.html#esc1445881961208)
   and [Xilinx's retiming options](https://www.xilinx.com/support/answers/65410.html). 
   Sharing some of the compiler driven pipelining design goals of [Google's XLS Project](https://google.github.io/xls/) and the [DFiantHDL language](https://dfianthdl.github.io/) as well.

# What is PipelineC not?

* High level synthesis of arbitrary C code with a global memory model / threads / etc.
* Meta-programming hardware-generator (ex. uses C type system and preprocessor).

# Core Features/Benefits

_A hardware description languge centered around pipelining_

* Automatic pipelining as a feature of the compiler. Basic use of the tool is to generate single pipelines to drop into existing designs. Eliminate the practice of pipelining logic by hand = not portable (relies on operating frequency and part).
* Compose complex portable designs consisting of multiple pipelines and controlling state machines.
* Can start by cloning existing VHDL/Verilog designs or including raw VHDL as a starting point - not forced to use automatic pipelining features - a full hardware description language replacement.
* Familiar C function syntax that eliminates many HDL quirks that beginners (and experts) can fall victim to (ex. blocking/nonblocking assignments).

The fundamental design elements are state machines, pipelines, and interconnects (wires,cdc,fifos,etc).

By isolating complex logic into autopipelineable functions, and only writing literal clock by clock hardware description when absolutely necessary, PipelineC designs do not need to be rewritten for each new target device / operating frequency. The hope is to build shared, high performance, device agnostic, hardware designs described in a somewhat familiar C language look.

For software folks I want writing PipelineC to feel like solving a programming puzzle in C, not a whole new paradigm of programming languages.
The rules of the puzzle hide/imply hardware concepts. For hardware folks I want PipelineC to be a better hardware description language.

```
Currently Supported Tools (tested on Linux):
Synthesis: Xilinx Vivado, Intel Quartus, Lattice Diamond
Simulation: Modelsim
```
