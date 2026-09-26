# Open issues: what's broken and where to start

This lists every open [PipelineC issue][issues], most serious first, for contributors looking for something to fix. Each entry says which front end it affects (C, Python, or both), what goes wrong, where the relevant code is, how to reproduce it, and a workaround where one exists.

Feature ideas and design questions live in [Discussions][discussions]. Before starting on code, read [`CONTRIBUTING.md`](../CONTRIBUTING.md): changes usually start with a discussion.

- **Baseline:** commit `5d2a9ca62616932aa401c8a3b07973afbb357ce5` (2026-09-25), with issues as of 2026-09-26. Every `file:line` reference points into that commit.
- **Verified** means reproduced on that commit, in some cases by simulating the generated VHDL in GHDL. Unverified entries come from reading the code or from the issue thread.

## Before you start

### How the two front ends fit together

The C front end (`src/C_TO_LOGIC.py`) and the Python front end, Pypeline (`src/PY_TO_LOGIC.py`), build the same `Logic` objects. Everything after that is shared: pipelining (`AUTO_PIPELINE`, `SWEEP`), VHDL emission (`VHDL`, `RAW_VHDL`), timing (`SYN` plus the synthesis-tool backends), HDL simulation (`SIM`) and the command line (`src/pipelinec`, also run as `src/pypelinec`).

Python never reaches the C parser, `C_TO_FSM` derived FSMs, `SW_LIB` C code generation, or `cpp`. Its operators, floats, fixed point and RAMs are Python libraries under `include/pypeline/`. So a bug in shared code affects both front ends, and a bug in the C-only layers affects only C. Python also has its own native simulator (`src/pypeline.py`, `src/pypeline_sim.py`), whose bugs affect only simulation results, not the generated hardware.

### Reproducing

Most issues reproduce without a synthesis tool:

```
./src/pipelinec design.c --comb --no_synth --out_dir out_c
./src/pypelinec design.py --comb --no_synth --out_dir out_py
```

For a top-level function named `top`, the function body is in `<out_dir>/top/top_0CLK_*.vhd`. Use a new `--out_dir` for every C build: reusing one silently builds stale code ([#82][i82]).

To check or simulate the generated VHDL with GHDL, run the commands below in the output directory. `vhdl_files.txt` is not in dependency order, so let GHDL sort it. To only check that the VHDL compiles, leave out `tb.vhd` and build the generated top level, `top`, instead of `tb`:

```
cd out_c
mkdir ghdl_work
ghdl -i --std=08 --workdir=ghdl_work $(cat vhdl_files.txt) tb.vhd
ghdl -m --std=08 --workdir=ghdl_work tb
ghdl -r --std=08 --workdir=ghdl_work tb
```

The testbenches below instantiate the function's entity directly. Replace `ENTITY` with the name of the `top/top_0CLK_*.vhd` file, without `.vhd`.

Python designs also run in the native simulator. Save a script like this in the same directory as `design.py` and run it from the repository root:

```python
import sys

sys.path.insert(0, "src")
from pypeline import sim_call
import design

print(int(sim_call(design.top, 5)))
```

For a clocked Python testbench (one using `sim_print`/`sim_finish`), compare the native and GHDL runs:

```
./src/pypelinec tb.py --sim --comb --run all
./src/pypelinec tb.py --sim --comb --cocotb --ghdl --run all
```

Issues #353 and later include their reproducers in the issue itself.

### Tests

- `python3 src/tests/pypeline_tests/run_all.py` runs the Python suites. It accepts `-j N` and `--category …`.
- `src/tests/c_tests/test_builds.sh "--comb --no_synth"` builds the C examples.
- `python3 src/tests/pypeline_tests/known_issues_tests.py` runs expect-fail reproducers of known Python-side bugs, including those for [#361][i361] and [#364][i364]. A fixed bug shows up as XPASS.

## Ranking

Issues are ordered by what goes wrong:

1. wrong hardware, or simulation disagrees with hardware
2. invalid HDL, a crash, or a misleading error
3. a missing feature that blocks designs
4. slower builds, and reports not yet reproduced

Within each group, bugs that affect both front ends come first, problems in the hardware come before problems only in simulation, and Python-only bugs come before C-only ones.

| Rank | Issue | Front ends | Problem | Verified |
|---|---|---|---|---|
| 1 | [#202][i202] | Both | Signed `%` gives the wrong sign when the divisor is negative | Yes, GHDL |
| 2 | [#318][i318] | Unknown | Vivado removes logic it treats as a timing loop | No, needs Vivado |
| 3 | [#60][i60] | Both | `a = b = x`: C crashes; Python drives only `a` | Yes |
| 4 | [#122][i122] | Both | Clock enables and FEEDBACK ready signals are pipelined like data | No |
| 5 | [#367][i367] | C | An explicit cast that narrows a signed value gives the wrong result | Yes, GHDL |
| 6 | [#82][i82] | C | Reusing `--out_dir` silently builds the old code | Yes |
| 7 | [#192][i192] | C | A FEEDBACK variable with no default assignment becomes an undriven net | Yes |
| 8 | [#146][i146] | C | A `static` declared inside an `if` never updates | Yes, GHDL |
| 9 | [#353][i353] | Python | Two calls to one stateful function on one line share state in native simulation | Yes, GHDL |
| 10 | [#354][i354] | Python | Native simulation runs `@MAIN`s with different clock rates in lockstep | Yes |
| 11 | [#355][i355] | Python | `@sim_input` ignores its arguments within a cycle | Yes |
| 12 | [#356][i356] | Both | String literals containing `_` produce invalid VHDL | Yes, GHDL |
| 13 | [#357][i357] | Both | A `char` register with an integer initial value: invalid VHDL in C, rejected in Python | Yes, GHDL |
| 14 | [#175][i175] | Both | IO registers on functions that touch global wires break the build | No |
| 15 | [#288][i288] | Both | A function with no timing path stops vendor-tool builds | No |
| 16 | [#137][i137] | Both | Internal user clocks are left unconstrained in Quartus | No |
| 17 | [#168][i168] | Both | Enum literals shared by two enum types can produce invalid VHDL | No |
| 18 | [#71][i71] | Both | `f().x` crashes the elaborator | Yes |
| 19 | [#304][i304] | Both | A missing input file gives an unhelpful error | Yes |
| 20 | [#360][i360] | Both | `sim_print`/`printf` values of 2³¹ or more overflow in VHDL simulation | Yes, GHDL |
| 21 | [#358][i358] | Python | `@enum` members named like VHDL reserved words produce invalid VHDL | Yes, GHDL |
| 22 | [#359][i359] | Python | An array of a different length is accepted and produces invalid VHDL | Yes, GHDL |
| 23 | [#362][i362] | Python | Unsupported constructs crash with internal errors | Yes |
| 24 | [#363][i363] | Python | Builds fail without the C preprocessor | Yes |
| 25 | [#361][i361] | Python | `sim_print` on the `sim_finish()` cycle is missing from VHDL simulation output | Yes, GHDL |
| 26 | [#286][i286] | C | The tool does not run on macOS | No, from the thread |
| 27 | [#52][i52] | C | A typedef alias gives a misleading type error | Yes |
| 28 | [#76][i76] | Both | No `switch` (C) or `match` (Python) | C yes; Python from the code |
| 29 | [#364][i364] | Python | Operator-library delays are measured every build instead of cached | Yes |
| 30 | [#365][i365] | Both | `--coarse --sweep` may crash on narrow leaves | Not reproduced |
| 31 | [#366][i366] | Python | AUTO_FSM deeply opened schedules may fail to elaborate | No, needs a long AUTO_FSM search |

## Wrong hardware, or simulation disagrees with hardware

### 1. [#202][i202]: signed integer `%` gives the wrong sign when the divisor is negative

- **Front ends:** both.
- **What happens:** signed `%` negates the remainder whenever exactly one operand is negative, which is the rule for division. C's `%` takes the sign of the dividend and Python's takes the sign of the divisor; the hardware matches neither:

  | Case | Hardware | C `%` | Python `%` |
  |---|---|---|---|
  | `7 % -2` | -1 | 1 | -1 |
  | `-7 % 2` | -1 | -1 | 1 |
  | `-7 % -2` | 1 | -1 | -1 |

  In Python, a bare `sim_call` computes the C result, so it disagrees with the hardware. `pypelinec --sim` registers the same soft operator first (`src/pypeline_sim.py:437`) and matches the hardware (verified).
- **Where to look:** C: `SW_LIB.GET_BIN_OP_MOD_INT_N_C_CODE` (`src/SW_LIB.py:8621-8625`). Python: the signed wrappers in `include/pypeline/operators/soft_div.py`, whose docstring explains why they copied the C rule. Native simulation: `SimVal.__mod__` (`src/pypeline.py:851`).
- **Reproduce:** the same function in both front ends, `smod.py` and `smod_c.c`:

  ```python
  from pypeline import *


  @MAIN(25.0)
  def top(a: int8_t, b: int8_t) -> int8_t:
      r: int8_t = a % b
      return r
  ```

  ```c
  #include "intN_t.h"
  #pragma MAIN_MHZ top 25.0
  int8_t top(int8_t a, int8_t b)
  {
    int8_t r = a % b;
    return r;
  }
  ```

  Build each with `--comb --no_synth` and simulate with this testbench. Both print the "Hardware" column above:

  ```vhdl
  library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;
  entity tb is end tb;
  architecture sim of tb is
    signal a, b, r : signed(7 downto 0);
    type pair_t is array (0 to 1) of integer;
    type pairs_t is array (natural range <>) of pair_t;
    constant cases : pairs_t := ((7, -2), (-7, 2), (-7, -2), (7, 2));
  begin
    dut : entity work.ENTITY port map (a => a, b => b, return_output => r);
    process
    begin
      for i in cases'range loop
        a <= to_signed(cases(i)(0), 8);
        b <= to_signed(cases(i)(1), 8);
        wait for 1 ns;
        report "hardware: " & integer'image(cases(i)(0)) & " % " & integer'image(cases(i)(1)) & " = " & integer'image(to_integer(r));
      end loop;
      wait;
    end process;
  end sim;
  ```

- **Workaround:** compute the remainder from the quotient, `q = a / b; r = a - q * b;`. Verified in C with the same testbench.

### 2. [#318][i318]: Vivado removes logic it treats as a timing loop

- **Front ends:** unknown. The reproducer is C float math. Python shares the VHDL emitter but uses a different float library.
- **What happens:** Vivado alone reports `CRITICAL WARNING: [Synth 8-326] inferred exception to break timing loop`, and the bitstream misbehaves (confirmed on hardware in the thread). Quartus and yosys with nextpnr find no loop.
- **Where to look:** the root cause is unknown. PipelineC already notices the warning: `src/VIVADO.py:80` prints it and `:187` prints `TIMING LOOPS!`, but the build carries on.
- **Reproduce:** needs Vivado.

  ```c
  #pragma PART "xc7a100tcsg324-1"
  #include "uintN_t.h"
  #pragma MAIN main
  float main(float a, float b, uint16_t x)
  {
    float fconst = 1.23;
    float fx = (float)x;
    float mults = (fx * fconst) * a;
    float rv = mults + b;
    return rv;
  }
  ```

- **Workaround:** reorder the expression. `fx * (fconst * a)` does not trigger it.

### 3. [#60][i60]: chained assignment `a = b = x`

- **Front ends:** both, and Python is worse.
- **What happens:** C fails with an internal `KeyError`. Python builds without error but drives only the first target, while native simulation assigns every target, so simulation and hardware disagree.
- **Where to look:** C: `C_AST_CONSTANT_LHS_ASSIGNMENT_TO_LOGIC` (`src/C_TO_LOGIC.py:3385`). Python: `_elab_assign` (`src/PY_TO_LOGIC.py:3008`) reads only `stmt.targets[0]`.
- **Reproduce:** `chained.py`:

  ```python
  from pypeline import *


  @MAIN(25.0)
  def top(x: uint8_t) -> uint8_t:
      a: uint8_t = 0
      b: uint8_t = 0
      a = b = x
      return b
  ```

  The build exits 0 with no warning. The generated function returns `b`'s initial value and never reads `x`:

  ```vhdl
       VAR_b_chained_py_l7_c17_ec18 := resize(to_unsigned(0, 1), 8);
       VAR_return_output := VAR_b_chained_py_l7_c17_ec18;
  ```

  Native simulation of `top(5)` returns 5. The C version (`uint8_t a = 0; uint8_t b = 0; a = b = x; return b;`) fails with `KeyError: 'a_chained_c_c_l7_c3_9a46'`.
- **Workaround:** write two assignments.

### 4. [#122][i122]: clock enables and FEEDBACK ready signals in autopipelined logic

- **Front ends:** both.
- **What happens:** in an autopipelined function, the clock enable and FEEDBACK variables are sampled in the first stage and delayed along with the data. So a downstream ready signal cannot stall the pipeline. Python's pipelined native simulation shows the delay; C's `--sim_comb` simulates the unpipelined logic and hides it.
- **Where to look:** `src/AUTO_PIPELINE.py:978-980`, where the clock enable and feedback variables are recorded as stage-0 inputs, and `:4657`, where the clock enable is taken from the input registers.
- **Reproduce:** the example in the issue. Not re-run here.
- **Workaround:** put a FIFO with an in-flight counter after the pipeline. Both front ends provide this as a library: `GLOBAL_VALID_READY_PIPELINE_INST` in `include/global_func_inst.h` (C) and `make_stream_auto_pipeline` in `include/pypeline/stream/stream_auto_pipeline.py` (Python).

### 5. [#367][i367]: an explicit cast that narrows a signed value gives the wrong result

- **Front ends:** C only. Python casts use a different lowering and are correct.
- **What happens:** the explicit-cast entity resizes the signed value to the target width before converting it, and `numeric_std`'s signed `resize` keeps the sign bit when it truncates. So `(uint8_t)x` is wrong whenever `x` does not fit the target type, while the implicit conversion `uint8_t y = x;` is right:

  | `x` (`int16_t`) | `(uint8_t)x` in hardware | `uint8_t y = x;` in hardware | C |
  |---|---|---|---|
  | 200 | 72 | 200 | 200 |
  | -129 | 255 | 127 | 127 |

- **Where to look:** `RAW_VHDL.GET_CAST_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT` (`src/RAW_VHDL.py:4165`) emits `unsigned(std_logic_vector(resize(rhs,8)))`. `VHDL.TYPE_RESOLVE_ASSIGNMENT_RHS` (`src/VHDL.py:5604`) converts first and is correct. A fix changes the VHDL of every existing C design that narrows a signed value through a cast (see `docs/pypeline_DESIGN.md`, scalar casting).
- **Reproduce:** in the issue: two C functions and a GHDL testbench.
- **Workaround:** narrow with an assignment instead of a cast.

### 6. [#82][i82]: reusing `--out_dir` silently builds the old C code

- **Front ends:** C only. Python re-parses on every run.
- **What happens:** `PARSE_FILE` first looks for `<out_dir>/<file>.parsed` and, if it exists, uses it without checking whether the source changed. The build prints `Already parsed C code for … using cache …`, exits 0, and generates hardware for the old source. The default output directory is new for every run, so this only bites when `--out_dir` is reused.
- **Where to look:** `C_TO_LOGIC.PARSE_FILE` (`src/C_TO_LOGIC.py:10556-10562`) and `GET_PARSER_STATE_CACHE_FILEPATH` (`:10392`), which keys the cache on the file's base name only.
- **Reproduce:**

  ```c
  #include "uintN_t.h"
  #pragma MAIN_MHZ top 25.0
  uint8_t top(uint8_t x)
  {
    return x + 1;
  }
  ```

  Build it with `--comb --no_synth --out_dir out`. Change `x + 1` to `x + 2` and build again with the same `--out_dir`. `out/top/top_0CLK_*.vhd` still contains `to_unsigned(1, 1)`.
- **Workaround:** a new `--out_dir` for every build, or delete `<out_dir>/<file>.parsed` first.

### 7. [#192][i192]: FEEDBACK variable with no default assignment

- **Front ends:** C only. Python connects each feedback wire's final value (`src/PY_TO_LOGIC.py:2567`).
- **What happens:** assigning a FEEDBACK variable only inside an `if`/`else` generates `feedback_vars.reg_wr_data <= feedback_vars.reg_wr_data;`, an undriven self-assignment, and the function returns it. The values from both branches are dropped. Synthesis only warns about a net with no driver.
- **Where to look:** the `FEEDBACK` pragma is parsed at `src/C_TO_LOGIC.py:12367` and applied at `:2400-2403`. Compare with Python's final-value connection above.
- **Reproduce:**

  ```c
  #include "uintN_t.h"
  #pragma MAIN_MHZ top 25.0
  uint8_t top(uint1_t thing)
  {
    uint8_t reg_wr_data;
    #pragma FEEDBACK reg_wr_data
    if(thing)
      reg_wr_data = 1;
    else
      reg_wr_data = 0;
    return reg_wr_data;
  }
  ```

- **Workaround:** assign a default before the `if` (`reg_wr_data = 0; if(thing) reg_wr_data = 1;`). Verified: the feedback wire is then driven from the mux.

### 8. [#146][i146]: a `static` declared inside an `if` never updates

- **Front ends:** C only. Python's equivalent, a `Reg[T]` declared inside an `if`, fails loudly with `No covering wire found for ('count',)`.
- **What happens:** the design used to be rejected; now it builds, but the register never takes the updated value. In the generated VHDL the incremented value only feeds the output, and `REG_VAR_count` keeps the old one.
- **Where to look:** `C_AST_STATIC_NON_CONST_DECL_TO_LOGIC` (`src/C_TO_LOGIC.py:5455`), reached from the static-declaration check in `C_AST_DECL_TO_LOGIC` (`:5654`).
- **Reproduce:**

  ```c
  #include "uintN_t.h"
  #pragma MAIN_MHZ top 25.0
  uint8_t top(uint1_t en)
  {
    uint8_t rv = 0;
    if(en){
      static uint8_t count;
      count += 1;
      rv = count;
    }
    return rv;
  }
  ```

  With this testbench, the output is 1 on every cycle; C gives 1, 2, 3, 4. Moving only the `static` line above the `if` gives 1, 2, 3, 4.

  ```vhdl
  library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;
  entity tb is end tb;
  architecture sim of tb is
    signal clk : std_logic := '0';
    signal en : unsigned(0 downto 0) := "1";
    signal r : unsigned(7 downto 0);
  begin
    dut : entity work.ENTITY port map (clk => clk, CLOCK_ENABLE => "1", en => en, return_output => r);
    process
    begin
      for i in 1 to 4 loop
        wait for 1 ns;
        report "cycle " & integer'image(i) & ": en=1 rv=" & integer'image(to_integer(r));
        clk <= '1'; wait for 1 ns; clk <= '0';
      end loop;
      wait;
    end process;
  end sim;
  ```

- **Workaround:** declare the `static` at the top of the function.

### 9. [#353][i353]: two calls to one stateful function on one line share state in native simulation

- **Front ends:** Python, native simulation only. The generated hardware is correct.
- **What happens:** native simulation identifies a call to a function with `Reg[T]` or `Feedback[T]` state by its source file and line. `acc(1) + acc(10)` on one line shares one register in simulation but builds two in hardware: the issue's testbench prints `s` = 11, 31, 51 natively and 11, 22, 33 in GHDL, with no warning. Two calls of one `AUTO_PIPELINE` object on one line share one delay line the same way.
- **Where to look:** the register-aware wrapper in `src/pypeline.py:7596-7625` keys `_sim_inst_stack` on `(filename, lineno)`. `SIM_TRACE_LOCATIONS = True` adds the column, but only on Python 3.11 and later, and it is off by default. Elaboration names instances by line and column (`PY_TO_LOGIC._loc_str`), and `_SimLoopInstanceRewriter` already gives loop iterations their own identity in simulation.
- **Reproduce:** in the issue.
- **Workaround:** put each call on its own line.

### 10. [#354][i354]: native simulation runs `@MAIN`s with different clock rates in lockstep

- **Front ends:** Python, native simulation only.
- **What happens:** `@MAIN`s at different rates build with separate clocks, but native simulation steps every `@MAIN` once per cycle whatever its rate, with no warning, so a 50 MHz counter advances in step with a 100 MHz one. The cocotb flow refuses such designs ("Only single clock designs supported for cocotb template testbench gen!", `src/COCOTB.py:90`), so no simulation shows the real behavior.
- **Where to look:** `_run_clock_cycle` (`src/pypeline_sim.py:268`). Moving data between clock domains is a separate feature request, [Discussion #342][d342].
- **Reproduce:** in the issue.
- **Workaround:** none for simulation. The generated hardware is not affected.

### 11. [#355][i355]: `@sim_input` ignores its arguments within a cycle

- **Front ends:** Python, native simulation only (`@sim_input` does not exist in hardware).
- **What happens:** a `@sim_input` function runs at most once per cycle through a cache keyed by the function alone, so `sample(0)` and `sample(1)` in one cycle both return `sample(0)`'s value.
- **Where to look:** `sim_input` in `src/pypeline.py:1578-1584` (`key = id(wrapper)`).
- **Reproduce:** in the issue.
- **Workaround:** use a separate `@sim_input` function for each value.

## Invalid HDL, crashes and misleading errors

### 12. [#356][i356]: string literals containing `_` produce invalid VHDL

- **Front ends:** both. Python's native simulation is correct, so the problem only shows up in GHDL or synthesis.
- **What happens:** a string constant's text is stored in its constant wire's name and read back by splitting that name on `_`. A literal containing `_` is cut at the first underscore and loses its closing quote: `"ab_cd"` is emitted as `to_byte_array("ab, 8)`, and GHDL reports "string cannot be multi-line, use concatenation".
- **Where to look:** `C_TO_LOGIC.GET_VAL_STR_FROM_CONST_WIRE` (`src/C_TO_LOGIC.py:5230`; the split is at `:5251-5253`). Python builds the wire in `PY_TO_LOGIC._elab_str_literal` (`src/PY_TO_LOGIC.py:4291`).
- **Reproduce:** in the issue, for both front ends.
- **Workaround:** avoid `_` in string literals, or initialize the `char` array numerically.

### 13. [#357][i357]: a `char` register with an integer initial value

- **Front ends:** both, one root cause.
- **What happens:** the `char` branch of `VHDL.CONST_VAL_STR_TO_VHDL` expects a quoted character literal such as `'A'`. Given an integer it emits `to_unsigned(character'pos('65'), 8)`, which GHDL rejects. In C, `static char c = 65;` builds and produces that VHDL; `static char c = 'A';` works. Python rejects any explicit initializer on a `Reg[T]` whose element type is `char_t` with a clear `ElaborationError`, so Python char registers can only start at zero.
- **Where to look:** `src/VHDL.py:5892-5901`. Python's guard is in `PY_TO_LOGIC._elab_ann_assign` (`src/PY_TO_LOGIC.py:3386`) and can go once the backend is fixed.
- **Reproduce:** in the issue.
- **Workaround:** C: use a character literal. Python: zero-initialize, or keep the register as `uint8_t`.

### 14. [#175][i175]: IO registers on functions that touch global wires

- **Front ends:** both, but only C has a workaround.
- **What happens:** the autopipeliner can add IO registers to a function that reads or writes global wires. Input registers only cover ports and the clock enable, so the result is broken VHDL (per the issue; not re-run here).
- **Where to look:** input registers at `src/AUTO_PIPELINE.py:4801`; `Logic.CAN_HAVE_ADDED_LATENCY` (`src/C_TO_LOGIC.py:1749`), which does not exclude global wires; `src/SWEEP.py:4493`, where the sweep honors `FUNC_NO_ADD_IO_REGS`.
- **Workaround:** C: `#pragma FUNC_NO_ADD_IO_REGS <function>`. Python has no equivalent.

### 15. [#288][i288]: a function with no timing path stops vendor-tool builds

- **Front ends:** both.
- **What happens:** when a function synthesizes to a netlist with no timing path (for example, it returns a constant), vendor-tool builds stop with `No timing paths reported!`. The PyRTL and sky130 backends already fail with a clear message that suggests marking the function as wires.
- **Where to look:** `src/SYN.py:2198`. The clearer message is `PYRTL.NO_TIMING_PATHS_ERROR_TEXT` (`src/PYRTL.py:30`). Open [PR #310][p310] changes related zero-delay handling.
- **Workaround:** `#pragma FUNC_WIRES <function>` in C, `@wires` in Python.

### 16. [#137][i137]: internal user clocks are left unconstrained in Quartus

- **Front ends:** both.
- **What happens:** clocks generated inside the design (C `CLK_MHZ`, Python `make_clock` on a `Wire`) are constrained with `create_clock … [get_nets {clk_…}]`. Quartus cannot match those names, so the clock stays unconstrained. Vivado accepts them.
- **Where to look:** `SYN.WRITE_CLK_CONSTRAINTS_FILE` (`src/SYN.py:534`, `get_nets` at `:574`).
- **Workaround:** per the issue thread, Quartus accepts the full hierarchical net name of the register driving the clock; edit the constraint by hand.

### 17. [#168][i168]: enum literals shared by two enum types

- **Front ends:** both. Python users hit it more naturally, because Python enums namespace their members.
- **What happens:** literals are emitted bare into each VHDL enum type, so a literal used by two types can be ambiguous. Common uses do work: `IDLE` appears in both state enums of the PDW example, and `src/tests/pypeline_tests/inst/enum_test.py` has two enums with the same members; both pass GHDL and Vivado. The construct that fails has not been pinned down.
- **Where to look:** `src/VHDL.py:4207`.
- **Workaround:** give members unique names across enums.

### 18. [#71][i71]: field access on a call result, `f().x`

- **Front ends:** both.
- **What happens:** C crashes on a deliberate `print(0 / 0)` placeholder with `ZeroDivisionError`. Python raises `NotImplementedError: Cannot parse ref toks from: Call(…)`.
- **Where to look:** C: `C_AST_REF_TO_TOKENS_TO_LOGIC` (`src/C_TO_LOGIC.py:4398`). Python: `_parse_ref_toks` (`src/PY_TO_LOGIC.py:5876`).
- **Reproduce:**

  ```python
  from typing import NamedTuple
  from pypeline import *


  @struct
  class point_t(NamedTuple):
      x: uint8_t
      y: uint8_t


  @hw_func
  def get_point(v: uint8_t) -> point_t:
      p: point_t = point_t(x=v, y=v)
      return p


  @MAIN(25.0)
  def top(v: uint8_t) -> uint8_t:
      r: uint8_t = get_point(v).x
      return r
  ```

  The C version with `uint8_t r = get_point(v).x;` fails the same way.
- **Workaround:** assign the result to a local first (`p: point_t = get_point(v)`, then `p.x`). Verified in Python.

### 19. [#304][i304]: a missing input file gives an unhelpful error

- **Front ends:** both.
- **What happens:** the command line only checks the file extension. A missing `.c` file shows a traceback ending in a failed `cpp -MM -MG …` command; a missing `.py` file shows a `FileNotFoundError` traceback from Python's import system.
- **Where to look:** `src/pipelinec:315`.
- **Reproduce:** `./src/pipelinec does_not_exist.c` or `./src/pypelinec does_not_exist.py`.

### 20. [#360][i360]: `sim_print` and `printf` values of 2³¹ or more overflow in VHDL simulation

- **Front ends:** both (the lowering is shared); reproduced with Python.
- **What happens:** `%d` and `%u` values print through VHDL `integer'image(to_integer(x))`, and VHDL's `integer` is 32-bit signed. A value of 2³¹ or more stops GHDL with "overflow detected". Native simulation prints it correctly.
- **Where to look:** `src/C_TO_LOGIC.py:7983-7987`, where printf arguments get their `integer'image` conversion. Hex output uses `to_hstring` (`:7993`) and does not overflow.
- **Reproduce:** in the issue.
- **Workaround:** mask or narrow the value, or print it with `hex(...)`.

### 21. [#358][i358]: `@enum` members named like VHDL reserved words produce invalid VHDL

- **Front ends:** Python. (Closed #129 covered reserved-word names in general, including C.)
- **What happens:** Pypeline renames locals, struct fields and functions whose names are VHDL reserved words, but emits `@enum` member names unchanged. A member such as `RELEASE`, `ON`, `OPEN`, `OUT`, `NEXT` or `SIGNAL` builds and simulates natively, then GHDL rejects the generated `c_structs_pkg.pkg.vhd`.
- **Where to look:** `PY_TO_LOGIC._register_enum` (`src/PY_TO_LOGIC.py:6574`) passes member names through; the other names go through `_sanitize_vhdl_name` (`:1231`). VHDL enum emission is at `src/VHDL.py:4207`. At minimum, a clear elaboration error would catch this before GHDL does.
- **Reproduce:** in the issue.
- **Workaround:** rename the member.

### 22. [#359][i359]: an array of a different length is accepted and produces invalid VHDL

- **Front ends:** Python.
- **What happens:** elaboration does not compare array lengths. Assigning a `uint2_t[4]` to a `uint2_t[16]` local, or returning it from a function declared `-> uint2_t[16]`, builds without error. Native simulation passes the 4-element value through, and GHDL rejects the VHDL ("type of element not compatible with the expected type"). AUTO_FSM can hit this without the user writing it: `make_operand_mux(t, n)` declares its choices as `t[n]`, which for an array `t` is the wrong shape under C-order indexing.
- **Where to look:** `_write_ref` (`src/PY_TO_LOGIC.py:6214`) and `_elab_return` (`:3607`) connect array wires without comparing their types. The operand mux is in `include/pypeline/operators/auto_fsm_mux.py:48`.
- **Reproduce:** in the issue.
- **Workaround:** keep array lengths equal.

### 23. [#362][i362]: unsupported Python constructs crash with internal errors

- **Front ends:** Python.
- **What happens:** several natural constructs that Pypeline does not support fail with an internal exception instead of an error naming the construct and its line:

  | Construct | Error today | Where it comes from |
  |---|---|---|
  | `x[i]` with a hardware index `i` | `ValueError: substring not found` | `_array_elem_type` (`src/PY_TO_LOGIC.py:110`), via `_elab_ref_read` (`:4348`) |
  | `state_t(...)` inside a hardware function, even `state_t(1)` | `TypeError: <enum 'state_t'> is a built-in class` | `_elab_call` (`src/PY_TO_LOGIC.py:5057`) treats the enum class as a function and calls `inspect.getsourcelines` on it (`:5633`) |
  | An array of enums, `state_t[4]` | `KeyError: 4` when the module is imported | `@enum` (`src/pypeline.py:1330`) installs no `__class_getitem__`, so the subscript is `IntEnum` member lookup |
  | `@struct` on a class that does not subclass `NamedTuple` | `AttributeError: type object … has no attribute '_fields'` | `struct` (`src/pypeline.py:1305`) |

  Supporting a hardware bit index is a feature request of its own, [Discussion #323][d323].
- **Reproduce:** in the issue.
- **Workarounds:** `x[i]`: `bits: uint1_t[8] = uint_to_array_le(x, 1)`, then `bits[i]`. Enums: use the members (`state_t.RUN`), and wrap an enum in a `@struct` to make an array of it. Structs: subclass `NamedTuple`.

### 24. [#363][i363]: Python builds fail without the C preprocessor

- **Front ends:** Python.
- **What happens:** `pypelinec` imports the C front end, which raises at import time if `cpp` is not on `PATH` ("'cpp' C preprocessor is not installed!"). That stops `.py` builds, which never run `cpp`.
- **Where to look:** `src/C_TO_LOGIC.py:26-28`. Checking when `cpp` is first run, rather than at import, would limit the requirement to C builds. Related: [Discussion #326][d326] (preprocessors other than `cpp`).
- **Reproduce:** run any `.py` build with a `PATH` that contains `python3` but not `cpp`.
- **Workaround:** install `cpp`.

### 25. [#361][i361]: `sim_print` on the `sim_finish()` cycle is missing from VHDL simulation output

- **Front ends:** Python (`sim_finish()` is Pypeline's).
- **What happens:** a `sim_print` that runs on the same cycle as `sim_finish()` appears in native simulation but not in the cocotb+GHDL output, and the run still exits 0. The print's write and `std.env.finish` happen on the same clock edge, and the finish wins. This affects plain prints as well as `debug=True` ones, so it also breaks the native-versus-VHDL cycle diff.
- **Where to look:** `VHDL.GET_PRINTF_MODULE_TEXT` (`src/VHDL.py:4927`) and `GET_SIM_FINISH_MODULE_TEXT` (`:5046`). Delaying the finish by one cycle in the generated VHDL is one option.
- **Reproduce:** in the issue, or `sim_finish_debug_print_race_test` in `src/tests/pypeline_tests/known_issues_tests.py` (it passes while the bug is present).
- **Workaround:** call `sim_finish()` one cycle after the last print.

### 26. [#286][i286]: the tool does not run on macOS

- **Front ends:** C only. Python never runs `cpp`, and Apple's `cpp` satisfies the import-time check ([#363][i363]).
- **What happens (from the thread):** Apple's `cpp` is clang, which does not behave like the GNU preprocessor PipelineC expects; comments in headers break preprocessing. Using `clang -E` and `clang -MM -MG` got the examples through elaboration.
- **Where to look:** `preprocess_file`, `preprocess_text` and `get_included_files` in `src/C_TO_LOGIC.py` (around `:138`, `:183` and `:224-230`), and the import-time `cpp` check at `:26`.
- **Not verified here:** needs a Mac.

### 27. [#52][i52]: a typedef alias gives a misleading type error

- **Front ends:** C only. A Python type alias is a plain assignment.
- **What happens:** `typedef uint8_t byte_t;` is skipped silently, and later code fails with a misleading error such as `Unsupported binary operation between types (explicit casting required for now): byte_t + uint1_t`. The warning that used to explain this, `WARN_NO_RENAMING_TYPEDEFS` (`src/C_TO_LOGIC.py:11853`), is commented out.
- **Where to look:** typedef handling in `src/C_TO_LOGIC.py`, starting from the commented-out warning above.
- **Reproduce:**

  ```c
  #include "uintN_t.h"
  typedef uint8_t byte_t;
  #pragma MAIN_MHZ top 25.0
  byte_t top(byte_t x)
  {
    byte_t r = x + 1;
    return r;
  }
  ```

- **Workaround:** `#define byte_t uint8_t`. Verified.

## Missing features that block designs

### 28. [#76][i76]: no `switch` or `match` statement

- **Front ends:** both.
- **What happens:** C `switch` fails with the internal error "C ast node cannot be parsed to logic" (verified). Python has no handling for `match` (Python 3.10 and later), so elaboration stops with "Unsupported statement" (from the code).
- **Where to look:** C: `C_AST_NODE_TO_LOGIC` (`src/C_TO_LOGIC.py:2394`). Python: `_elab_stmt` (`src/PY_TO_LOGIC.py:2648`).
- **Workaround:** an `if`/`else if` chain in C, `if`/`elif` in Python.

## Slower builds, and reports not yet reproduced

### 29. [#364][i364]: operator-library delays are measured every build instead of cached

- **Front ends:** Python. Build time only; timing results are unaffected.
- **What happens:** `SYN._IS_PYPELINE_OPERATOR_LIBRARY_CODE` is meant to recognize entities from `include/pypeline/operators/` (the soft operators and AUTO_FSM's operand multiplexers) so their measured delays go into `cache/delay`. It calls `inspect.getsourcefile` on the `@hw_func` wrapper instead of the wrapped function, so it always sees `pypeline.py` and never fires.
- **Where to look:** `src/SYN.py:1569`. `docs/SYN_DESIGN.md` §10 suggests `inspect.unwrap` at that lookup.
- **Reproduce:** `python3 src/tests/pypeline_tests/known_issues_tests.py -k never_fires` reports XFAIL while the bug is present.

### 30. [#365][i365]: `--coarse --sweep` may crash on narrow leaves

- **Front ends:** both (shared pipelining code).
- **What happens (from the docs):** on a design with many 1-3 bit leaves at a high cut count, `--coarse --sweep` can raise `GET_BITS_PER_STAGE_DICT: interior zero-bit stage … for a 2-bit op`. The planned sweep caps legal cuts at the leaf's width minus one (`SWEEP.SliceLandscape.finalize()`); the coarse path uses `RAW_VHDL.LEAF_MAX_SPLIT_SLICES`, which returns no cap for bit-split leaves.
- **Where to look:** `src/RAW_VHDL.py:103-117` and the check at `:2255`.
- **Reproduce:** not reproduced yet. A chain of four `uint2_t` adds built with `--syn_tool pyrtl --coarse --start 12 --stop 12` completed normally.
- **Workaround:** use the default planned sweep.

### 31. [#366][i366]: AUTO_FSM deeply opened schedules may fail to elaborate

- **Front ends:** Python (AUTO_FSM is Python-only and experimental).
- **What happens (from the docs):** rescheduling the donut design (`examples/pypeline/vga_donut.py`) under a tightened budget produced a 412-operation, 131-state plan whose generated source failed to elaborate with "Bit index [14:14] out of range for uint9_t". The default control path avoids it only by meeting timing before the search opens the schedule that far.
- **Where to look:** AUTO_FSM's source generation for opened operations in `src/AUTO_FSM.py`; `docs/AUTO_FSM_DESIGN.md` §6.
- **Reproduce:** not re-run here; it needs a long AUTO_FSM search.

[issues]: https://github.com/JulianKemmerer/PipelineC/issues
[discussions]: https://github.com/JulianKemmerer/PipelineC/discussions
[i52]: https://github.com/JulianKemmerer/PipelineC/issues/52
[i60]: https://github.com/JulianKemmerer/PipelineC/issues/60
[i71]: https://github.com/JulianKemmerer/PipelineC/issues/71
[i76]: https://github.com/JulianKemmerer/PipelineC/issues/76
[i82]: https://github.com/JulianKemmerer/PipelineC/issues/82
[i122]: https://github.com/JulianKemmerer/PipelineC/issues/122
[i137]: https://github.com/JulianKemmerer/PipelineC/issues/137
[i146]: https://github.com/JulianKemmerer/PipelineC/issues/146
[i168]: https://github.com/JulianKemmerer/PipelineC/issues/168
[i175]: https://github.com/JulianKemmerer/PipelineC/issues/175
[i192]: https://github.com/JulianKemmerer/PipelineC/issues/192
[i202]: https://github.com/JulianKemmerer/PipelineC/issues/202
[i286]: https://github.com/JulianKemmerer/PipelineC/issues/286
[i288]: https://github.com/JulianKemmerer/PipelineC/issues/288
[i304]: https://github.com/JulianKemmerer/PipelineC/issues/304
[i318]: https://github.com/JulianKemmerer/PipelineC/issues/318
[i353]: https://github.com/JulianKemmerer/PipelineC/issues/353
[i354]: https://github.com/JulianKemmerer/PipelineC/issues/354
[i355]: https://github.com/JulianKemmerer/PipelineC/issues/355
[i356]: https://github.com/JulianKemmerer/PipelineC/issues/356
[i357]: https://github.com/JulianKemmerer/PipelineC/issues/357
[i358]: https://github.com/JulianKemmerer/PipelineC/issues/358
[i359]: https://github.com/JulianKemmerer/PipelineC/issues/359
[i360]: https://github.com/JulianKemmerer/PipelineC/issues/360
[i361]: https://github.com/JulianKemmerer/PipelineC/issues/361
[i362]: https://github.com/JulianKemmerer/PipelineC/issues/362
[i363]: https://github.com/JulianKemmerer/PipelineC/issues/363
[i364]: https://github.com/JulianKemmerer/PipelineC/issues/364
[i365]: https://github.com/JulianKemmerer/PipelineC/issues/365
[i366]: https://github.com/JulianKemmerer/PipelineC/issues/366
[i367]: https://github.com/JulianKemmerer/PipelineC/issues/367
[d323]: https://github.com/JulianKemmerer/PipelineC/discussions/323
[d326]: https://github.com/JulianKemmerer/PipelineC/discussions/326
[d342]: https://github.com/JulianKemmerer/PipelineC/discussions/342
[p310]: https://github.com/JulianKemmerer/PipelineC/pull/310
