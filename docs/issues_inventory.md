# Open issues: what's broken and where to start

This lists every open [PipelineC issue][issues], most serious first, for contributors looking for something to fix. Each entry says which front end it affects (C, Python, or both), what goes wrong, where the relevant code is, how to reproduce it, and a workaround where one exists.

Feature ideas and design questions live in [Discussions][discussions]. Before starting on code, read [`CONTRIBUTING.md`](../CONTRIBUTING.md): changes usually start with a discussion.

- **Baseline:** commit `5d2a9ca62616932aa401c8a3b07973afbb357ce5`. Every `file:line` reference points into that commit. The entries for [#369][i369], [#370][i370], [#371][i371] and [#372][i372] cite code newer than that commit, so they name functions instead.
- **Verified** means reproduced on that commit, in some cases by simulating the generated VHDL in GHDL. Unverified entries come from reading the code or from the issue thread.

## Before you start

### How the two front ends fit together

The C front end (`src/C_TO_LOGIC.py`) and the Python front end, Pypeline (`src/PY_TO_LOGIC.py`), build the same `Logic` objects (`src/LOGIC.py`). Everything after that is shared: pipelining (`AUTO_PIPELINE`, `SWEEP`), VHDL emission (`VHDL`, `RAW_VHDL`), timing (`SYN` plus the synthesis-tool backends), HDL simulation (`SIM`) and the command line (`src/pipelinec`, also run as `src/pypelinec`).

Python never reaches the C parser, `C_TO_FSM` derived FSMs, the C front end's C code generation, or `cpp`. Its operators, floats, fixed point and RAMs are Python libraries under `include/pypeline/`. So a bug in shared code affects both front ends, and a bug in the C-only layers affects only C. Python also has its own native simulator (`src/pypeline.py`, `src/pypeline_sim.py`), whose bugs affect only simulation results, not the generated hardware.

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
- `python3 src/tests/pypeline_tests/known_issues_tests.py` runs expect-fail reproducers of known Python-side bugs, including those for [#361][i361], [#369][i369], [#370][i370], [#371][i371] and [#372][i372]. A fixed bug shows up as XPASS.

## Ranking

Issues are ordered by what goes wrong:

1. wrong hardware, or simulation disagrees with hardware
2. invalid HDL, a crash, or a misleading error
3. a missing feature that blocks designs
4. slower builds, extra hardware, and reports not yet reproduced

Within each group, bugs that affect both front ends come first, problems in the hardware come before problems only in simulation, and Python-only bugs come before C-only ones.

| Rank | Issue | Front ends | Problem | Verified |
|---|---|---|---|---|
| 1 | [#202][i202] | Both | Signed `%` gives the wrong sign when the divisor is negative | Yes, GHDL |
| 2 | [#318][i318] | Unknown | Vivado removes logic it treats as a timing loop | No, needs Vivado |
| 3 | [#60][i60] | Both | `a = b = x`: C crashes; Python drives only `a` | Yes |
| 4 | [#122][i122] | Both | Clock enables and FEEDBACK ready signals are pipelined like data | No |
| 5 | [#370][i370] | Python | Factory calls that differ only inside a numpy array of over 1000 elements elaborate as one function | Yes |
| 6 | [#369][i369] | Python | A top-level function that folds a `.latency` constant can keep its pass-1 VHDL in pass 2 | Yes, in-process |
| 7 | [#367][i367] | C | An explicit cast that narrows a signed value gives the wrong result | Yes, GHDL |
| 8 | [#82][i82] | C | Reusing `--out_dir` silently builds the old code | Yes |
| 9 | [#192][i192] | C | A FEEDBACK variable with no default assignment becomes an undriven net | Yes |
| 10 | [#146][i146] | C | A `static` declared inside an `if` never updates | Yes, GHDL |
| 11 | [#353][i353] | Python | Two calls to one stateful function on one line share state in native simulation | Yes, GHDL |
| 12 | [#354][i354] | Python | Native simulation runs `@MAIN`s with different clock rates in lockstep | Yes |
| 13 | [#355][i355] | Python | `@sim_input` ignores its arguments within a cycle | Yes |
| 14 | [#356][i356] | Both | String literals containing `_` produce invalid VHDL | Yes, GHDL |
| 15 | [#357][i357] | Both | A `char` register with an integer initial value: invalid VHDL in C, rejected in Python | Yes, GHDL |
| 16 | [#371][i371] | Both | `@pipeline_latency`/`FUNC_LATENCY` on a wire-only body produces invalid VHDL | Yes, GHDL |
| 17 | [#175][i175] | Both | IO registers on functions that touch global wires break the build (Python fixed) | No |
| 18 | [#288][i288] | Both | A function with no timing path stops vendor-tool builds | No |
| 19 | [#137][i137] | Both | Internal user clocks are left unconstrained in Quartus | No |
| 20 | [#168][i168] | Both | Enum literals shared by two enum types can produce invalid VHDL | No |
| 21 | [#71][i71] | Both | `f().x` crashes the elaborator | Yes |
| 22 | [#304][i304] | Both | A missing input file gives an unhelpful error | Yes |
| 23 | [#360][i360] | Both | `sim_print`/`printf` values of 2³¹ or more overflow in VHDL simulation | Yes, GHDL |
| 24 | [#358][i358] | Python | `@enum` members named like VHDL reserved words produce invalid VHDL | Yes, GHDL |
| 25 | [#359][i359] | Python | An array of a different length is accepted and produces invalid VHDL | Yes, GHDL |
| 26 | [#362][i362] | Python | Unsupported constructs crash with internal errors | Yes |
| 27 | [#363][i363] | Python | Builds fail without the C preprocessor | Yes |
| 28 | [#361][i361] | Python | `sim_print` on the `sim_finish()` cycle is missing from VHDL simulation output | Yes, GHDL |
| 29 | [#286][i286] | C | The tool does not run on macOS | No, from the thread |
| 30 | [#52][i52] | C | A typedef alias gives a misleading type error | Yes |
| 31 | TBD | C | A float `+` in `examples/tool_tests/open_tools.c` stops the build at `GET_RAW_HDL_WIRES_DECL_TEXT` | Yes |
| 32 | [#76][i76] | Both | No `switch` (C) or `match` (Python) | C yes; Python from the code |
| 33 | [#365][i365] | Both | `--coarse --sweep` may crash on narrow leaves | Not reproduced |
| 34 | [#372][i372] | Python | `AUTO_PIPELINE(latency=N)` adds N cuts when `@pipeline_latency` calls already supply N cycles | Yes |
| 35 | [#366][i366] | Python | AUTO_FSM deeply opened schedules may fail to elaborate | No, needs a long AUTO_FSM search |
| 36 | Not yet filed | Python | `AUTO_PIPELINE(f)` on an imported function sweeps worse than tagging a local wrapper | Yes, in process |

## Wrong hardware, or simulation disagrees with hardware

### 1. [#202][i202]: signed integer `%` gives the wrong sign when the divisor is negative

- **Front ends:** both.
- **What happens:** signed `%` negates the remainder whenever exactly one operand is negative, which is the rule for division. C's `%` takes the sign of the dividend and Python's takes the sign of the divisor; the hardware matches neither:

  | Case | Hardware | C `%` | Python `%` |
  |---|---|---|---|
  | `7 % -2` | -1 | 1 | -1 |
  | `-7 % 2` | -1 | -1 | 1 |
  | `-7 % -2` | 1 | -1 | -1 |

  In Python, a bare `sim_call` computes the C result, so it disagrees with the hardware. `pypelinec --sim` registers the same soft operator first (`src/pypeline_sim.py:439`) and matches the hardware (verified).
- **Where to look:** C: `C_TO_LOGIC.GET_BIN_OP_MOD_INT_N_C_CODE` (`src/C_TO_LOGIC.py:17647-17651`). Python: the signed wrappers in `include/pypeline/operators/soft_div.py`, whose docstring explains why they copied the C rule. Native simulation: `SimVal.__mod__` (`src/pypeline.py:851`).
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
- **Where to look:** the root cause is unknown. PipelineC already notices the warning: `src/VIVADO.py:79` prints it and `:186` prints `TIMING LOOPS!`, but the build carries on.
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
- **Where to look:** C: `C_AST_CONSTANT_LHS_ASSIGNMENT_TO_LOGIC` (`src/C_TO_LOGIC.py:1464`). Python: `_elab_assign` (`src/PY_TO_LOGIC.py:3009`) reads only `stmt.targets[0]`.
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
- **Where to look:** `src/AUTO_PIPELINE.py:980-982`, where the clock enable and feedback variables are recorded as stage-0 inputs, and `:4695`, where the clock enable is taken from the input registers.
- **Reproduce:** the example in the issue. Not re-run here.
- **Workaround:** put a FIFO with an in-flight counter after the pipeline. Both front ends provide this as a library: `GLOBAL_VALID_READY_PIPELINE_INST` in `include/global_func_inst.h` (C) and `make_stream_auto_pipeline` in `include/pypeline/stream/stream_auto_pipeline.py` (Python).

### 5. [#370][i370]: factory calls that differ only inside a large numpy array elaborate as one function

- **Front ends:** Python.
- **What happens:** a factory specialization's identity falls back to `repr()` for a numpy array argument, and numpy's repr leaves out the middle of any array of over 1000 elements (`np.get_printoptions()["threshold"]`). Two calls whose arrays differ only there get one identity, and the second becomes a `_DUPLICATE_` instance of the first, with no warning. In the issue's example the VHDL uses the first array for both calls, while native simulation uses each call's own array.
- **Where to look:** `pypeline._stable_key` (`src/pypeline.py`), which has no numpy case. The RAM generators in `include/pypeline/ram.py` hash their contents themselves and are not affected. A content case (dtype, shape and a SHA-256 of the bytes) renames the entities of every factory specialized on a numpy array, once.
- **Reproduce:** in the issue, or `python3 src/tests/pypeline_tests/known_issues_tests.py -k numpy_factory_arg_identity` (XFAIL while the bug is present).
- **Workaround:** pass a tuple (`tuple(int(v) for v in table)`) or a precomputed digest instead of the array.

### 6. [#369][i369]: a top-level function that folds a `.latency` constant can keep its pass-1 VHDL

- **Front ends:** Python. `.latency` is Pypeline's; the file writing is shared.
- **What happens:** a top-level `@hw_func` that is itself pipelined and reads a module-level value derived from `AUTO_PIPELINE(...).latency` can keep pass 1's entity file when pin-and-confirm needs pass 2. The re-elaborated design has the new constant, while the written file, and so its synthesis, has the old one, with no error. This needs the entity name to stay the same in both passes: the constant keeps its bit width (2 → 3, for example), and pass 2 replays pass 1's slices.
- **Where to look:** `AUTO_PIPELINE.WRITE_ALL_NON_ZERO_CLK_VHDL_FILES` writes each entity file once per process (`_NON_ZERO_CLK_FILES_WRITTEN`). A top-level function's `TimingParams.BUILD_HASH_EXT` covers its children's names and its slices, not its own body. Clearing the set on every re-elaboration renames nothing, and `VHDL.WRITE_TEXT_IF_CHANGED` already leaves identical files alone.
- **Reproduce:** in the issue, or `python3 src/tests/pypeline_tests/known_issues_tests.py -k latency_constant_entity_reuse` (XFAIL while the bug is present). The reproducer elaborates twice in one process, the way pass 2 does, instead of running a sweep.
- **Workaround:** produce the function from a factory that takes the value as an argument (`make_folds_latency(lat)`), so a changed value renames it. Factory closures that capture the value are renamed this way already, which is why `make_stream_auto_pipeline`'s FIFO sizing and AUTO_MULTI_CYCLE handshakes are not affected.

### 7. [#367][i367]: an explicit cast that narrows a signed value gives the wrong result

- **Front ends:** C only. Python casts use a different lowering and are correct.
- **What happens:** the explicit-cast entity resizes the signed value to the target width before converting it, and `numeric_std`'s signed `resize` keeps the sign bit when it truncates. So `(uint8_t)x` is wrong whenever `x` does not fit the target type, while the implicit conversion `uint8_t y = x;` is right:

  | `x` (`int16_t`) | `(uint8_t)x` in hardware | `uint8_t y = x;` in hardware | C |
  |---|---|---|---|
  | 200 | 72 | 200 | 200 |
  | -129 | 255 | 127 | 127 |

- **Where to look:** `RAW_VHDL.GET_CAST_C_BUILT_IN_C_ENTITY_WIRES_DECL_AND_PROCESS_STAGES_TEXT` (`src/RAW_VHDL.py:4160`) emits `unsigned(std_logic_vector(resize(rhs,8)))`. `VHDL.TYPE_RESOLVE_ASSIGNMENT_RHS` (`src/VHDL.py:5604`) converts first and is correct. A fix changes the VHDL of every existing C design that narrows a signed value through a cast (see `docs/pypeline_DESIGN.md`, scalar casting).
- **Reproduce:** in the issue: two C functions and a GHDL testbench.
- **Workaround:** narrow with an assignment instead of a cast.

### 8. [#82][i82]: reusing `--out_dir` silently builds the old C code

- **Front ends:** C only. Python re-parses on every run.
- **What happens:** `PARSE_FILE` first looks for `<out_dir>/<file>.parsed` and, if it exists, uses it without checking whether the source changed. The build prints `Already parsed C code for … using cache …`, exits 0, and generates hardware for the old source. The default output directory is new for every run, so this only bites when `--out_dir` is reused.
- **Where to look:** `C_TO_LOGIC.PARSE_FILE` (`src/C_TO_LOGIC.py:7697-7706`) and `GET_PARSER_STATE_CACHE_FILEPATH` (`:7529`), which keys the cache on the file's base name only.
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

### 9. [#192][i192]: FEEDBACK variable with no default assignment

- **Front ends:** C only. Python connects each feedback wire's final value (`src/PY_TO_LOGIC.py:2568`).
- **What happens:** assigning a FEEDBACK variable only inside an `if`/`else` generates `feedback_vars.reg_wr_data <= feedback_vars.reg_wr_data;`, an undriven self-assignment, and the function returns it. The values from both branches are dropped. Synthesis only warns about a net with no driver.
- **Where to look:** the `FEEDBACK` pragma is parsed at `src/C_TO_LOGIC.py:532-538` and applied at `:648`. Compare with Python's final-value connection above.
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

### 10. [#146][i146]: a `static` declared inside an `if` never updates

- **Front ends:** C only. Python's equivalent, a `Reg[T]` declared inside an `if`, fails loudly with `No covering wire found for ('count',)`.
- **What happens:** the design used to be rejected; now it builds, but the register never takes the updated value. In the generated VHDL the incremented value only feeds the output, and `REG_VAR_count` keeps the old one.
- **Where to look:** `C_AST_STATIC_NON_CONST_DECL_TO_LOGIC` (`src/C_TO_LOGIC.py:3384`), reached from the static-declaration check in `C_AST_DECL_TO_LOGIC` (`:3583`).
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

### 11. [#353][i353]: two calls to one stateful function on one line share state in native simulation

- **Front ends:** Python, native simulation only. The generated hardware is correct.
- **What happens:** native simulation identifies a call to a function with `Reg[T]` or `Feedback[T]` state by its source file and line. `acc(1) + acc(10)` on one line shares one register in simulation but builds two in hardware: the issue's testbench prints `s` = 11, 31, 51 natively and 11, 22, 33 in GHDL, with no warning. Two calls of one `AUTO_PIPELINE` object on one line share one delay line the same way.
- **Where to look:** the register-aware wrapper in `src/pypeline.py:7596-7625` keys `_sim_inst_stack` on `(filename, lineno)`. `SIM_TRACE_LOCATIONS = True` adds the column, but only on Python 3.11 and later, and it is off by default. Elaboration names instances by line and column (`PY_TO_LOGIC._loc_str`), and `_SimLoopInstanceRewriter` already gives loop iterations their own identity in simulation.
- **Reproduce:** in the issue.
- **Workaround:** put each call on its own line.

### 12. [#354][i354]: native simulation runs `@MAIN`s with different clock rates in lockstep

- **Front ends:** Python, native simulation only.
- **What happens:** `@MAIN`s at different rates build with separate clocks, but native simulation steps every `@MAIN` once per cycle whatever its rate, with no warning, so a 50 MHz counter advances in step with a 100 MHz one. The cocotb flow refuses such designs ("Only single clock designs supported for cocotb template testbench gen!", `src/COCOTB.py:90`), so no simulation shows the real behavior.
- **Where to look:** `_run_clock_cycle` (`src/pypeline_sim.py:270`). Moving data between clock domains is a separate feature request, [Discussion #342][d342].
- **Reproduce:** in the issue.
- **Workaround:** none for simulation. The generated hardware is not affected.

### 13. [#355][i355]: `@sim_input` ignores its arguments within a cycle

- **Front ends:** Python, native simulation only (`@sim_input` does not exist in hardware).
- **What happens:** a `@sim_input` function runs at most once per cycle through a cache keyed by the function alone, so `sample(0)` and `sample(1)` in one cycle both return `sample(0)`'s value.
- **Where to look:** `sim_input` in `src/pypeline.py:1578-1584` (`key = id(wrapper)`).
- **Reproduce:** in the issue.
- **Workaround:** use a separate `@sim_input` function for each value.

## Invalid HDL, crashes and misleading errors

### 14. [#356][i356]: string literals containing `_` produce invalid VHDL

- **Front ends:** both. Python's native simulation is correct, so the problem only shows up in GHDL or synthesis.
- **What happens:** a string constant's text is stored in its constant wire's name and read back by splitting that name on `_`. A literal containing `_` is cut at the first underscore and loses its closing quote: `"ab_cd"` is emitted as `to_byte_array("ab, 8)`, and GHDL reports "string cannot be multi-line, use concatenation".
- **Where to look:** `LOGIC.GET_VAL_STR_FROM_CONST_WIRE` (`src/LOGIC.py:2134`; the split is at `:2154-2157`). Python builds the wire in `PY_TO_LOGIC._elab_str_literal` (`src/PY_TO_LOGIC.py:4292`).
- **Reproduce:** in the issue, for both front ends.
- **Workaround:** avoid `_` in string literals, or initialize the `char` array numerically.

### 15. [#357][i357]: a `char` register with an integer initial value

- **Front ends:** both, one root cause.
- **What happens:** the `char` branch of `VHDL.CONST_VAL_STR_TO_VHDL` expects a quoted character literal such as `'A'`. Given an integer it emits `to_unsigned(character'pos('65'), 8)`, which GHDL rejects. In C, `static char c = 65;` builds and produces that VHDL; `static char c = 'A';` works. Python rejects any explicit initializer on a `Reg[T]` whose element type is `char_t` with a clear `ElaborationError`, so Python char registers can only start at zero.
- **Where to look:** `src/VHDL.py:5892-5901`. Python's guard is in `PY_TO_LOGIC._elab_ann_assign` (`src/PY_TO_LOGIC.py:3387`) and can go once the backend is fixed.
- **Reproduce:** in the issue.
- **Workaround:** C: use a character literal. Python: zero-initialize, or keep the register as `uint8_t`.

### 16. [#371][i371]: `@pipeline_latency` on a wire-only body produces invalid VHDL

- **Front ends:** both (C: `#pragma FUNC_LATENCY`).
- **What happens:** a function declared with a latency of 1 or more whose body is only wiring (no registers, no operators) gets an entity named `…_1CLK_…`. Its process sensitivity list ends in a dangling comment: `x,` then `-- Register)`. GHDL rejects it ("name expected here, found 'is'"), so simulation and synthesis fail. The declaration is trusted, so a body that does not implement the latency is allowed, but its VHDL should still be legal. A body with any operator compiles.
- **Where to look:** the sensitivity-list text in `AUTO_PIPELINE.GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT`. The ` -- Registers` header is emitted whenever `VHDL.LOGIC_NEEDS_REGS` holds, and the final two-character cut assumes the list ends with a comma.
- **Reproduce:** in the issue, or `python3 src/tests/pypeline_tests/known_issues_tests.py -k pipeline_latency_wire_body` (XFAIL while the bug is present; needs GHDL).
- **Workaround:** implement the latency with a `Reg` in the body, or declare `@pipeline_latency(0)` for pure wiring.

### 17. [#175][i175]: IO registers on functions that touch global wires

- **Front ends:** both, but only C has a workaround.
- **What happens:** the autopipeliner can add IO registers to a function that reads or writes global wires. Input registers only cover ports and the clock enable, so the result is broken VHDL (per the issue; not re-run here).
- **Python, fixed:** Pypeline globals are aligned with the function's arguments/return value, so they ride in the IO banks. `AUTO_PIPELINE.ALIGNED_GLOBAL_READS`/`ALIGNED_GLOBAL_WRITES` join `input_registers_t`/`output_registers_t`. `IO_REG_BANKS` declares a bank only when it holds something, so a function whose only IO is global wires no longer declares `io_registers_t` signals without the type. See [AUTO_PIPELINE_DESIGN.md](AUTO_PIPELINE_DESIGN.md#global-wires-in-pipelines).
- **C:** the empty-bank declaration fix applies too, but C ("legacy") globals still bypass the banks. That case was not re-run.
- **Where to look:** `IO_REG_BANKS` and the bank records in `GET_PIPELINE_ARCH_DECL_TEXT` (`src/AUTO_PIPELINE.py`); `src/SWEEP.py`, where the sweep honors `FUNC_NO_ADD_IO_REGS`.
- **Workaround:** C: `#pragma FUNC_NO_ADD_IO_REGS <function>`.

### 18. [#288][i288]: a function with no timing path stops vendor-tool builds

- **Front ends:** both.
- **What happens:** when a function synthesizes to a netlist with no timing path (for example, it returns a constant), vendor-tool builds stop with `No timing paths reported!`. The PyRTL and sky130 backends already fail with a clear message that suggests marking the function as wires.
- **Where to look:** `src/SYN.py:2197`. The clearer message is `PYRTL.NO_TIMING_PATHS_ERROR_TEXT` (`src/PYRTL.py:30`). Open [PR #310][p310] changes related zero-delay handling.
- **Workaround:** `#pragma FUNC_WIRES <function>` in C, `@wires` in Python.

### 19. [#137][i137]: internal user clocks are left unconstrained in Quartus

- **Front ends:** both.
- **What happens:** clocks generated inside the design (C `CLK_MHZ`, Python `make_clock` on a `Wire`) are constrained with `create_clock … [get_nets {clk_…}]`. Quartus cannot match those names, so the clock stays unconstrained. Vivado accepts them.
- **Where to look:** `SYN.WRITE_CLK_CONSTRAINTS_FILE` (`src/SYN.py:533`, `get_nets` at `:573`).
- **Workaround:** per the issue thread, Quartus accepts the full hierarchical net name of the register driving the clock; edit the constraint by hand.

### 20. [#168][i168]: enum literals shared by two enum types

- **Front ends:** both. Python users hit it more naturally, because Python enums namespace their members.
- **What happens:** literals are emitted bare into each VHDL enum type, so a literal used by two types can be ambiguous. Common uses do work: `IDLE` appears in both state enums of the PDW example, and `src/tests/pypeline_tests/inst/enum_test.py` has two enums with the same members; both pass GHDL and Vivado. The construct that fails has not been pinned down.
- **Where to look:** `src/VHDL.py:4207`.
- **Workaround:** give members unique names across enums.

### 21. [#71][i71]: field access on a call result, `f().x`

- **Front ends:** both.
- **What happens:** C crashes on a deliberate `print(0 / 0)` placeholder with `ZeroDivisionError`. Python raises `NotImplementedError: Cannot parse ref toks from: Call(…)`.
- **Where to look:** C: `C_AST_REF_TO_TOKENS_TO_LOGIC` (`src/C_TO_LOGIC.py:2386`). Python: `_parse_ref_toks` (`src/PY_TO_LOGIC.py:5877`).
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

### 22. [#304][i304]: a missing input file gives an unhelpful error

- **Front ends:** both.
- **What happens:** the command line only checks the file extension. A missing `.c` file shows a traceback ending in a failed `cpp -MM -MG …` command; a missing `.py` file shows a `FileNotFoundError` traceback from Python's import system.
- **Where to look:** `src/pipelinec:315`.
- **Reproduce:** `./src/pipelinec does_not_exist.c` or `./src/pypelinec does_not_exist.py`.

### 23. [#360][i360]: `sim_print` and `printf` values of 2³¹ or more overflow in VHDL simulation

- **Front ends:** both (the lowering is shared); reproduced with Python.
- **What happens:** `%d` and `%u` values print through VHDL `integer'image(to_integer(x))`, and VHDL's `integer` is 32-bit signed. A value of 2³¹ or more stops GHDL with "overflow detected". Native simulation prints it correctly.
- **Where to look:** `LOGIC.PRTINTF_STRING_TO_FORMATS` (`src/LOGIC.py:2321-2325`), where printf arguments get their `integer'image` conversion. Hex output uses `to_hstring` (`:2331`) and does not overflow.
- **Reproduce:** in the issue.
- **Workaround:** mask or narrow the value, or print it with `hex(...)`.

### 24. [#358][i358]: `@enum` members named like VHDL reserved words produce invalid VHDL

- **Front ends:** Python. (Closed #129 covered reserved-word names in general, including C.)
- **What happens:** Pypeline renames locals, struct fields and functions whose names are VHDL reserved words, but emits `@enum` member names unchanged. A member such as `RELEASE`, `ON`, `OPEN`, `OUT`, `NEXT` or `SIGNAL` builds and simulates natively, then GHDL rejects the generated `c_structs_pkg.pkg.vhd`.
- **Where to look:** `PY_TO_LOGIC._register_enum` (`src/PY_TO_LOGIC.py:6575`) passes member names through; the other names go through `_sanitize_vhdl_name` (`:1232`). VHDL enum emission is at `src/VHDL.py:4207`. At minimum, a clear elaboration error would catch this before GHDL does.
- **Reproduce:** in the issue.
- **Workaround:** rename the member.

### 25. [#359][i359]: an array of a different length is accepted and produces invalid VHDL

- **Front ends:** Python.
- **What happens:** elaboration does not compare array lengths. Assigning a `uint2_t[4]` to a `uint2_t[16]` local, or returning it from a function declared `-> uint2_t[16]`, builds without error. Native simulation passes the 4-element value through, and GHDL rejects the VHDL ("type of element not compatible with the expected type"). AUTO_FSM can hit this without the user writing it: `make_operand_mux(t, n)` declares its choices as `t[n]`, which for an array `t` is the wrong shape under C-order indexing.
- **Where to look:** `_write_ref` (`src/PY_TO_LOGIC.py:6215`) and `_elab_return` (`:3608`) connect array wires without comparing their types. The operand mux is in `include/pypeline/operators/auto_fsm_mux.py:49`.
- **Reproduce:** in the issue.
- **Workaround:** keep array lengths equal.

### 26. [#362][i362]: unsupported Python constructs crash with internal errors

- **Front ends:** Python.
- **What happens:** several natural constructs that Pypeline does not support fail with an internal exception instead of an error naming the construct and its line:

  | Construct | Error today | Where it comes from |
  |---|---|---|
  | `x[i]` with a hardware index `i` | `ValueError: substring not found` | `_array_elem_type` (`src/PY_TO_LOGIC.py:111`), via `_elab_ref_read` (`:4349`) |
  | `state_t(...)` inside a hardware function, even `state_t(1)` | `TypeError: <enum 'state_t'> is a built-in class` | `_elab_call` (`src/PY_TO_LOGIC.py:5058`) treats the enum class as a function and calls `inspect.getsourcelines` on it (`:5634`) |
  | An array of enums, `state_t[4]` | `KeyError: 4` when the module is imported | `@enum` (`src/pypeline.py:1330`) installs no `__class_getitem__`, so the subscript is `IntEnum` member lookup |
  | `@struct` on a class that does not subclass `NamedTuple` | `AttributeError: type object … has no attribute '_fields'` | `struct` (`src/pypeline.py:1305`) |

  Supporting a hardware bit index is a feature request of its own, [Discussion #323][d323].
- **Reproduce:** in the issue.
- **Workarounds:** `x[i]`: `bits: uint1_t[8] = uint_to_array_le(x, 1)`, then `bits[i]`. Enums: use the members (`state_t.RUN`), and wrap an enum in a `@struct` to make an array of it. Structs: subclass `NamedTuple`.

### 27. [#363][i363]: Python builds fail without the C preprocessor

- **Front ends:** Python.
- **What happens:** `pypelinec` imports the C front end, which raises at import time if `cpp` is not on `PATH` ("'cpp' C preprocessor is not installed!"). That stops `.py` builds, which never run `cpp`.
- **Where to look:** `src/C_TO_LOGIC.py:28-30`. Checking when `cpp` is first run, rather than at import, would limit the requirement to C builds. Related: [Discussion #326][d326] (preprocessors other than `cpp`).
- **Reproduce:** run any `.py` build with a `PATH` that contains `python3` but not `cpp`.
- **Workaround:** install `cpp`.

### 28. [#361][i361]: `sim_print` on the `sim_finish()` cycle is missing from VHDL simulation output

- **Front ends:** Python (`sim_finish()` is Pypeline's).
- **What happens:** a `sim_print` that runs on the same cycle as `sim_finish()` appears in native simulation but not in the cocotb+GHDL output, and the run still exits 0. The print's write and `std.env.finish` happen on the same clock edge, and the finish wins. This affects plain prints as well as `debug=True` ones, so it also breaks the native-versus-VHDL cycle diff.
- **Where to look:** `VHDL.GET_PRINTF_MODULE_TEXT` (`src/VHDL.py:4927`) and `GET_SIM_FINISH_MODULE_TEXT` (`:5046`). Delaying the finish by one cycle in the generated VHDL is one option.
- **Reproduce:** in the issue, or `sim_finish_debug_print_race_test` in `src/tests/pypeline_tests/known_issues_tests.py` (it passes while the bug is present).
- **Workaround:** call `sim_finish()` one cycle after the last print.

### 29. [#286][i286]: the tool does not run on macOS

- **Front ends:** C only. Python never runs `cpp`, and Apple's `cpp` satisfies the import-time check ([#363][i363]).
- **What happens (from the thread):** Apple's `cpp` is clang, which does not behave like the GNU preprocessor PipelineC expects; comments in headers break preprocessing. Using `clang -E` and `clang -MM -MG` got the examples through elaboration.
- **Where to look:** `preprocess_file`, `preprocess_text` and `get_included_files` in `src/C_TO_LOGIC.py` (around `:76`, `:121` and `:162-168`), and the import-time `cpp` check at `:28`.
- **Not verified here:** needs a Mac.

### 30. [#52][i52]: a typedef alias gives a misleading type error

- **Front ends:** C only. A Python type alias is a plain assignment.
- **What happens:** `typedef uint8_t byte_t;` is skipped silently, and later code fails with a misleading error such as `Unsupported binary operation between types (explicit casting required for now): byte_t + uint1_t`. The warning that used to explain this, `WARN_NO_RENAMING_TYPEDEFS` (`src/C_TO_LOGIC.py:8560`), is commented out.
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

### 31. TBD: a float `+` in `examples/tool_tests/open_tools.c` stops the build at `GET_RAW_HDL_WIRES_DECL_TEXT`

- **Front ends:** C only. Python floats are library code under `include/pypeline/`.
- **What happens:** the design parses, then the build exits with status 255 while writing the zero-added-clocks VHDL, after printing `GET_RAW_HDL_WIRES_DECL_TEXT for float_uint8_uint23 ?`. `float_uint8_uint23` is the bit-manipulation helper that the generated C for `BIN_OP_PLUS_float_float` calls to pack sign, exponent and mantissa. The other C examples that `src/tests/c_tests/test_builds.sh` builds first (blink, pipeline_and_fsm, global_fifo, clock_crossing, async_clock_crossing, internal_clocks, user_func_latency) build.
- **Where to look:** the final `else` of `RAW_VHDL.GET_RAW_HDL_WIRES_DECL_TEXT` (`src/RAW_VHDL.py:255`), which none of its branches reaches for this function. `LOGIC.IS_BIT_MANIP_NAME`'s float patterns (`float_[0-9]+_[0-9]+`) do not match the name.
- **Reproduce:** `src/pipelinec examples/tool_tests/open_tools.c --comb --no_synth`.
- **Workaround:** none known.

## Missing features that block designs

### 32. [#76][i76]: no `switch` or `match` statement

- **Front ends:** both.
- **What happens:** C `switch` fails with the internal error "C ast node cannot be parsed to logic" (verified). Python has no handling for `match` (Python 3.10 and later), so elaboration stops with "Unsupported statement" (from the code).
- **Where to look:** C: `C_AST_NODE_TO_LOGIC` (`src/C_TO_LOGIC.py:444`). Python: `_elab_stmt` (`src/PY_TO_LOGIC.py:2649`).
- **Workaround:** an `if`/`else if` chain in C, `if`/`elif` in Python.

## Slower builds, extra hardware, and reports not yet reproduced

### 33. [#365][i365]: `--coarse --sweep` may crash on narrow leaves

- **Front ends:** both (shared pipelining code).
- **What happens (from the docs):** on a design with many 1-3 bit leaves at a high cut count, `--coarse --sweep` can raise `GET_BITS_PER_STAGE_DICT: interior zero-bit stage … for a 2-bit op`. The planned sweep caps legal cuts at the leaf's width minus one (`SWEEP.SliceLandscape.finalize()`); the coarse path uses `RAW_VHDL.LEAF_MAX_SPLIT_SLICES`, which returns no cap for bit-split leaves.
- **Where to look:** `src/RAW_VHDL.py:98-112` and the check at `:2250`.
- **Reproduce:** not reproduced yet. A chain of four `uint2_t` adds built with `--syn_tool pyrtl --coarse --start 12 --stop 12` completed normally.
- **Workaround:** use the default planned sweep.

### 34. [#372][i372]: `AUTO_PIPELINE(func, latency=N)` adds cuts its `@pipeline_latency` calls make unnecessary

- **Front ends:** Python. The planner is shared; C's `#pragma AUTOPIPELINE N` was not checked.
- **What happens:** when `func`'s `@pipeline_latency` calls already supply the N cycles, the planner still places N cuts. They survive only where they add no latency: in logic running parallel to those calls. That branch gets registers it does not need, and anything leaving it before the return value (a `VOLATILE` or C global write) appears later. The hardware meets the declared latency, but it is larger than it needs to be.
- **Where to look:** `AUTO_PIPELINE.ENFORCE_AUTO_PIPELINE_REGIONS` and `BUILD_FIXED_AUTO_PIPELINE_TIMING_PARAMS`. A fixed region gets N cuts, and the check after lowering looks only at the realized total latency.
- **Reproduce:** in the issue, or `python3 src/tests/pypeline_tests/known_issues_tests.py -k fixed_auto_pipeline_extra_cuts` (XFAIL while the bug is present).
- **Workaround:** leave `latency=` off when the calls already supply it, or move the parallel logic out of the tagged function.

### 35. [#366][i366]: AUTO_FSM deeply opened schedules may fail to elaborate

- **Front ends:** Python (AUTO_FSM is Python-only and experimental).
- **What happens (from the docs):** rescheduling the donut design (`examples/pypeline/vga_donut.py`) under a tightened budget produced a 412-operation, 131-state plan whose generated source failed to elaborate with "Bit index [14:14] out of range for uint9_t". The default control path avoids it only by meeting timing before the search opens the schedule that far.
- **Where to look:** AUTO_FSM's source generation for opened operations in `src/AUTO_FSM.py`; `docs/AUTO_FSM_DESIGN.md` §6.
- **Reproduce:** not re-run here; it needs a long AUTO_FSM search.

### 36. Not yet filed: `AUTO_PIPELINE(f)` on an imported function sweeps worse than a wrapper

- **Front ends:** Python.
- **What happens:** the call's instance is labeled with the bare Python name (`square`), while the callee's function name is module-prefixed (`imported_math_square`). The sweep attributes a critical path by finding function names inside its register names, so a path through the region root matches nothing and the sweep replans the whole MAIN blindly. Separately, the sweep never mini-sweeps a region root, only functions inside a region. Seen on WireGuard: tagging `poly1305_body` directly built the bodies 6 and 12 deep and overflowed the device's DSPs, where tagging a one-line wrapper built 8 and 8.
- **Where to look:** `SWEEP.RANK_PATH_FUNC_CANDIDATES` and `ATTRIBUTION_BASIS` (name matching); `SYN.PATH_CELLS_BY_MAIN` already maps path names to instances through the emitted hierarchy. The region-root exclusion is the `hotspot_func != region.func_name` test in `SWEEP.DO_PLANNED_THROUGHPUT_SWEEP`.
- **Reproduce:** `python3 src/tests/pypeline_tests/known_issues_tests.py -k imported_auto_pipeline_attribution` (XFAIL while the bug is present).
- **Workaround:** tag a small local wrapper that calls the function, so the function sits inside the region.

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
[i365]: https://github.com/JulianKemmerer/PipelineC/issues/365
[i366]: https://github.com/JulianKemmerer/PipelineC/issues/366
[i367]: https://github.com/JulianKemmerer/PipelineC/issues/367
[i369]: https://github.com/JulianKemmerer/PipelineC/issues/369
[i370]: https://github.com/JulianKemmerer/PipelineC/issues/370
[i371]: https://github.com/JulianKemmerer/PipelineC/issues/371
[i372]: https://github.com/JulianKemmerer/PipelineC/issues/372
[d323]: https://github.com/JulianKemmerer/PipelineC/discussions/323
[d326]: https://github.com/JulianKemmerer/PipelineC/discussions/326
[d342]: https://github.com/JulianKemmerer/PipelineC/discussions/342
[p310]: https://github.com/JulianKemmerer/PipelineC/pull/310
