```
██████╗ ██╗██████╗ ███████╗██╗     ██╗███╗   ██╗███████╗ ██████╗
██╔══██╗██║██╔══██╗██╔════╝██║     ██║████╗  ██║██╔════╝██╔════╝
██████╔╝██║██████╔╝█████╗  ██║     ██║██╔██╗ ██║█████╗  ██║     
██╔═══╝ ██║██╔═══╝ ██╔══╝  ██║     ██║██║╚██╗██║██╔══╝  ██║     
██║     ██║██║     ███████╗███████╗██║██║ ╚████║███████╗╚██████╗
╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝ ╚═════╝
```

*Please feel free to message - very happy to make PipelineC work for you! Always looking for help as well.* -Julian

A C-like(1) hardware description language (HDL)(2) adding automatic pipelining(3) as an additional language construct/compiler feature.

1. Not actually regular C. But mostly compileable by gcc for doing 'simulation'.
2. Can reasonably replace Verilog/VHDL. Compiler produces synthesizable and somewhat human readable VHDL.
3. If a computation can be written as pure function without side effects (i.e. no global variables) then it will be autopipelined. 
   Conceptually similar to technologies like Intel's variable latency [Hyper-Pipelining](https://www.intel.com/content/www/us/en/programmable/documentation/jbr1444752564689.html#esc1445881961208) and Xilinx's [retiming options](https://www.xilinx.com/support/answers/65410.html).

By isolating complex logic into autopipelineable functions, and only writing literal clock by clock hardware description when absolutely necessary, PipelineC code need not be rewritten for each new target device / operating frequency. The hope is to build shared, high performance, device agnostic, hardware designs described in a somewhat familiar C language look.

Get started by reading the [wiki](https://github.com/JulianKemmerer/PipelineC/wiki) .

The PipelineC compiler pipelines pure functions as most industry High Level Synthesis (HLS) tools would. 

However, PipelineC is not HLS. It is not meant as some abstracted virtual machine with a memory model. Instead hardware pipelines are presented as C functions.

The spectrum of HLS-like tools tends to look like so:
```
A)
Pro: Highly abstracted and easy to use 
Con: Poor results (compared to hand written hardware description language)   
    to
B)
Pro: Excellent results
Con: So low level you might as well be writing in a hardware description language (but does often come with great test bench functionality)
```
On the A) side you make little to no modifications to the original code. Any software developer off the street can be up and running quickly. 

On the B) side of things you are likely doing a complete rewrite of the code to 'some ugly pragma ridden version of C'. You likely still require a hardware engineer on your team even if a skilled software developer is writing the code.

Right now PipelineC is closer to the B side of things - closer to writing hardware description language. I dont think I've made it too ugly yet and so far only basic hardware knowledge is required. For software folks I want writing PipelineC to feel like solving a programming puzzle in C, not a whole new programming language. The rules of the puzzle hide/imply hardware concepts. For hardware folks I want PipelineC to be a better hardware description language.

```
Currently Supported Tools (Linux only for now):
Simulation: Modelsim
Synthesis: Xilinx Vivado
```
