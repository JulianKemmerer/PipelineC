```
██████╗ ██╗   ██╗██████╗ ███████╗██╗     ██╗███╗   ██╗███████╗ ██████╗
██╔══██╗╚██╗ ██╔╝██╔══██╗██╔════╝██║     ██║████╗  ██║██╔════╝██╔════╝
██████╔╝ ╚████╔╝ ██████╔╝█████╗  ██║     ██║██╔██╗ ██║█████╗  ██║     
██╔═══╝   ╚██╔╝  ██╔═══╝ ██╔══╝  ██║     ██║██║╚██╗██║██╔══╝  ██║     
██║        ██║   ██║     ███████╗███████╗██║██║ ╚████║███████╗╚██████╗
╚═╝        ╚═╝   ╚═╝     ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝ ╚═════╝
```

# What is PypelineC?

A hardware description language (HDL) adding high level synthesis(HLS)-like automatic pipelining as a language construct/compiler feature. 

If a computation can be written as a [pure function](https://en.wikipedia.org/wiki/Combinational_logic) without side effects (i.e. no registers/static variables) then it can be autopipelined. Conceptually similar to technologies like [Intel's variable latency Hyper-Pipelining](https://www.intel.com/content/www/us/en/programmable/documentation/jbr1444752564689.html#esc1445881961208) and [Xilinx's retiming options](https://www.xilinx.com/support/answers/65410.html). Sharing some of the compiler driven pipelining design goals of [Google's XLS Project](https://google.github.io/xls/), the [DFiantHDL language](https://dfianthdl.github.io/), and certain [CIRCT](https://circt.llvm.org/) dialects as well.

PypelineC consists of [**Pypeline**](docs/README.md) (new, Python based) and [**PipelineC**](https://github.com/JulianKemmerer/PipelineC/wiki) (legacy, C based). Pypeline is a work in progress in becoming feature complete with PipelineC, but already has many new features that PipelineC lacks.

**Example code for blinking an LED:**

<table>
<tr>
<th>Pypeline (<a href="examples/pypeline/blink.py">examples/pypeline/blink.py</a>)</th>
<th>PipelineC (<a href="examples/blink.c">examples/blink.c</a>)</th>
</tr>
<tr>
<td valign="top">

```python
# 'Called'/'Executing' every 40ns (25MHz)
@MAIN(25.0)
def blink() -> uint1_t:
    # 25000000 iterations * 40ns each = 1 sec
    counter: Reg[uint32_t] = 0

    # LED on/off state
    led: Reg[uint1_t] = 0

    # If reached 1 second
    if counter == (25000000 - 1):
        led = ~led  # Toggle led
        counter = 0  # Reset counter
    else:
        counter += 1 # one 40ns increment

    return led
```

</td>
<td valign="top">

```c
// 'Called'/'Executing' every 40ns (25MHz)
#pragma MAIN_MHZ blink 25.0
uint1_t blink()
{
  // 25000000 iterations * 40ns each = 1sec
  static uint25_t counter = 0;

  // LED on off state
  static uint1_t led = 0;

  // If reached 1 second
  if(counter==(25000000-1))
  {
    // Toggle led
    led = !led;
    // Reset counter
    counter = 0;
  }
  else
  {
    counter += 1; // one 40ns increment
  }
  return led;
}
```

</td>
</tr>
</table>

| | Pypeline | PipelineC |
|---|---|---|
| **Getting started** | [/docs directory](docs/README.md) | [GitHub wiki](https://github.com/JulianKemmerer/PipelineC/wiki) |
| Easy to understand software-like syntax | [Yes](docs/pypeline_guide.md#1-what-is-pypeline) | Yes |
| Timing feedback from synthesis+pnr tools | [Yes](docs/pypeline_guide.md#5-top-level-entry-points) | Yes |
| Automatic pipelining of comb. logic | [Yes](docs/pypeline_guide.md#1-what-is-pypeline) | Yes |
| Dev board specific support packages | [Yes](docs/pypeline_guide.md#2-worked-example-vga-test-pattern) | Yes |
| VHDL Output | Yes (human readable) | Yes (human readable) |
| VHDL based existing module import | [Yes](docs/pypeline_guide.md#17-raw-vhdl-passthrough-vhdl) | Yes |
| Verilog Output | Yes (machine converted) | Yes (machine converted) |
| Verilog based existing module import | No | No |
| Traditional HDL simulator support | [Yes](docs/pypeline_guide.md#4-simulation) | Yes |
| Native Simulation | [Yes](docs/pypeline_guide.md#4-simulation) | No |
| Valid-Ready handshaking | [Yes](docs/pypeline_guide.md#the-stream-interface-validready-handshaking) | Yes |
| Globally visible point to point wires | [Yes](docs/pypeline_guide.md#14-global-signals) | Yes |
| Multiple clock domains / Clock domain crossings | No | Yes |
| Parameterized/Template Functions+Types | [Yes](docs/pypeline_guide.md#12-parametric-hardware-with-factory-functions) | No |
| Operator overloading | [Yes](docs/pypeline_guide.md#13-custom-operators) | Yes (hacky) |
| User visible automatic pipeline depths | [Yes](docs/pypeline_guide.md#15-tool-chosen-implementation-autopipeline-and-autofsm) | No |
| Automatic resource sharing (pure func → shared-resource FSM) | [Yes](docs/pypeline_guide.md#autofsm-the-opposite-trade-off) | No |
| SoC system bus helpers | No | Yes |
| Generates software Helper Code | No | Yes |
| Derived FSM style code | No | Yes |
| Documentation | Comprehensive, planned | Ad-hoc, organic |
| Compiler tests | Many, Automated | Limited, Hand-run |


Tools:
```
Currently Supported Tools (Linux only):
Synthesis: 
  Xilinx Vivado, 
  Intel Quartus, 
  Lattice Diamond, 
  GHDL+Yosys+nextpnr,
  Gowin EDA, 
  Efinix Efinity,
  Cologne Chip Toolchain,
  PyRTL Models
Simulation: 
  Modelsim, 
  Verilator,
  cocotb,
  CXXRTL, 
  EDAPlayground
```


_An easy to understand hardware description language with a powerful autopipelining compiler and growing set of real life hardware design inspired features._

* Familiar software-like syntax that eliminates many HDL quirks that beginners (and experts) can fall victim to (ex. blocking/nonblocking assignments, reasoning about the sequential ordering of combinatorial logic).
* Compatible with all HDL simulators. Ex. Can start Modelsim in seconds and imports human readable+debuggable VHDL w/ working print's. Pypeline allows native Python simulations to launch instantly. PipelineC can also craft custom ultra-fast compiled C based 'simulations'. Conversion to Verilog is also included as needed, i.e. for Verilator.
* Helpful timing feedback derived from synthesis tool reports to help identify critical path logic that cannot be automatically pipelined - especially helpful for those new to digital logic design.
* PipelineC integrates with software side C easily; helpful built in code generation. (ex. for un/packing structs from de/serialized byte arrays when moving data from host<->FPGA).
* A full hardware description language replacement. Can start by cloning existing VHDL/Verilog designs or including raw VHDL - not forced to use entire language at all times.
* Globally visible point-to-point wires, multi-rate/width clock domain crossings, and complex derived FSMs, are just some of the growing list of composability features inspired by real life hardware design requirements/tasks.
* Automatic pipelining as a feature of the compiler. Basic use of the tool can be to generate single pipelines to drop into existing designs elsewhere. Eliminate the practice of pipelining logic by hand = not portable (relies on operating frequency and part).

Fundamental design elements are state machines/stateful elements(registers, rams, etc), auto-pipelined stateless pure functions, and interconnects (wires,cdc,async fifos,etc). Designs can be structured to look like 'communicating sequential processes/threads' as needed.

By isolating complex logic into autopipelineable functions, and only writing literal clock by clock hardware description when absolutely necessary, PypelineC designs do not need to be rewritten for each new target device / operating frequency.
The hope is to build shared, high performance, device agnostic, hardware designs described in a familiar and powerfully composable software-like look.

For software folks writing PypelineC should feel like solving a programming puzzle - the rules of the puzzle hide/imply hardware concepts. For hardware folks PypelineC is a better hardware description language trying to find middle ground between traditional RTL and HLS. It is my language of choice as an FPGA engineer :).

