# Complexity review experiments

These probes support the individual reviews and [overall recommendations](REVIEW_COMPLEXITY.md). They run from the repository root, do not modify compiler source, and do not invoke synthesis or simulation tools. Mocked inputs establish narrow behaviors, not end-to-end hardware failures.

## Table of Contents

- [Measurement method](#measurement-method)
- [Scoped operator identity reuse](#scoped-operator-identity-reuse)
- [Constant evaluation outcomes](#constant-evaluation-outcomes)
- [Quartus clock command separators](#quartus-clock-command-separators)
- [Backend adapter probes](#backend-adapter-probes)
- [STA endpoint polarity](#sta-endpoint-polarity)
- [CIRCT availability](#circt-availability)
- [Limits](#limits)

## Measurement method

The prior session installed lizard, radon, pylint and vulture into the user's Python environment. This continuation reused those installations; it installed no additional tools. Observed versions: lizard 1.24.2, radon 6.0.1, pylint 3.2.7, vulture 2.14. The interpreter was Python 3.8.10.

[METRICS.json](METRICS.json) records physical lines, Lizard noncomment lines, function counts, CCN thresholds, the five highest-scoring functions and SHA-256 for each source file. CCN means cyclomatic complexity as counted by Lizard. Counts include nested functions; their scores should not be added as independent runtime paths. Extensionless `src/pipelinec` was analyzed as Python. Top-level driver control flow is not represented by its function CCN.

The 31 substantive nonlegacy top-level Python modules total **79,445 physical lines and 56,426 Lizard NLOC**, with **214 functions above CCN 15** and **24 above CCN 50**. The driver and C_TO_FSM scope assessment are recorded separately. The base commit is `9eafa7d8`; pre-existing working changes are included. This is a per-file snapshot, not a frozen atomic repository revision.

To reproduce a measurement:

```sh
python3 - <<'PY'
from pathlib import Path
import hashlib
import lizard

p = Path("src/SWEEP.py")
source = p.read_text()
result = lizard.analyze_file.analyze_source_code(str(p), source)
print("sha256", hashlib.sha256(source.encode()).hexdigest())
print("lines", len(source.splitlines()), "nloc", result.nloc)
for f in sorted(result.function_list,
                key=lambda f: f.cyclomatic_complexity, reverse=True)[:5]:
    print(f.name, f.start_line, f.end_line, f.cyclomatic_complexity)
PY
```

The handoff supplied a normalized-AST clone scan, a pylint duplicate-code report and a vulture report. The clone scan abstracts identifiers/constants and compares function structure and statement windows. Its matches were used to direct source reading; they are **not proofs of semantic equivalence**. Overlapping windows, especially OPEN_TOOLS templates, must not be summed as removable lines. Pylint helped corroborate cross-backend scaffolding; vulture's unused names were not treated as safe deletion instructions. Reflection, generated code and backend dispatch make static dead-code results unreliable without caller evidence.

The review prioritizes shared Python paths over high-scoring C-only methods. It is targeted source/design-doc analysis, not a line-by-line formal audit or a measured runtime profile.

## Scoped operator identity reuse

Run in a fresh process:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'PY'
import pypeline as p
from pypeline import uint8_t

def impl(x: uint8_t) -> uint8_t:
    return x

def register_temporary_scope():
    def scope(x: uint8_t) -> uint8_t:
        return x
    p.register_unary_operator("NEGATE", uint8_t, impl, scope=scope)
    return id(scope)

old_id = register_temporary_scope()

def unrelated(x: uint8_t) -> uint8_t:
    return x

print("reused:", id(unrelated) == old_id)
saved = p._push_scoped_registrations(unrelated)
print("unrelated got registration:", bool(saved))
p._pop_scoped_registrations(saved)
PY
```

Observed: `reused: True` and `unrelated got registration: True`. A function that never registered an operator acquired the dead function's scope entry.

Address reuse is allocator-dependent; a run printing False is inconclusive, not evidence that integer IDs are safe keys. The registry retains neither the scope object nor a weak identity check. No full miscompiled design was demonstrated. See [pypeline review](pypeline_COMPLEXITY_REVIEW.md).

## Constant evaluation outcomes

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'PY'
import ast
from types import SimpleNamespace
import PY_TO_LOGIC as P

context = SimpleNamespace(
    _refs_hw_local=lambda node: False,
    _make_eval_ns=lambda: {},
)
for text in ["1/0", "missing_name", "None", "2+3"]:
    node = ast.parse(text, mode="eval").body
    print(text, "=>", P.FuncElaborator._try_eval_const(context, node))
PY
```

Observed:

```text
1/0 => None
missing_name => None
None => None
2+3 => 5
```

This demonstrates loss of evaluation outcome/error information at the method boundary. The dummy context deliberately has no hardware locals. It does not show which final error a complete design would produce, nor prove incorrect hardware. The recommended tri-state result must still support intentional hardware-call detection. See [front-end review](PY_TO_LOGIC_COMPLEXITY_REVIEW.md).

## Quartus clock command separators

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'PY'
import io
from types import SimpleNamespace
from unittest.mock import patch
import SYN

class Capture(io.StringIO):
    def close(self):
        pass

output = Capture()
state = SimpleNamespace(FuncLogicLookupTable={})
with patch.object(SYN, "SYN_TOOL", SYN.QUARTUS), \
     patch.object(SYN, "GET_CLK_TO_MHZ_AND_CONSTRAINTS_PATH",
                  return_value=({"a": 100, "b": 50, "c": 25}, "memory.sdc")), \
     patch.object(SYN, "GET_ALL_USER_CLOCKS", return_value=set()), \
     patch("builtins.open", return_value=output):
    SYN.WRITE_CLK_CONSTRAINTS_FILE(None, state)
for line in output.getvalue().splitlines():
    if line.startswith("set_clock_groups"):
        print(line)
PY
```

Observed one line containing all three commands, with joins like:

```text
... [get_clocks b]set_clock_groups -asynchronous ...
```

The writer omitted a newline/semicolon between commands. This is a confirmed generated-output defect. It requires at least three clocks to expose concatenation between pairwise commands; two clocks produce only one pair. Actual Quartus execution was not tested. See [SYN review](SYN_COMPLEXITY_REVIEW.md).

## Backend adapter probes

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'PY'
import ast
from pathlib import Path
from types import SimpleNamespace
import CC_TOOLS

report = CC_TOOLS.ParsedTimingReport("no timing information")
print("empty report:",
      [(key, path.path_delay_ns) for key, path in report.path_reports.items()])

# Evaluate the actual f-string template in COCOTB.py without invoking DO_SIM.
tree = ast.parse(Path("src/COCOTB.py").read_text())
for node in ast.walk(tree):
    if isinstance(node, ast.JoinedStr) and any(
        isinstance(item, ast.Constant) and isinstance(item.value, str)
        and "if val_input:" in item.value for item in node.values
    ):
        source = eval(
            compile(ast.Expression(body=node), "<helper-template>", "eval"),
            {"debug_name": "drive", "debug_vhdl_name": "signal"},
        )
        namespace = {}
        exec(source, namespace)
        dut = SimpleNamespace(signal=7)
        namespace["drive"](dut, 0)
        print("signal after drive(0):", dut.signal)
        break
else:
    raise RuntimeError("Template changed; inspect the new generator")
PY
```

Observed:

```text
empty report: [(None, None)]
signal after drive(0): 7
```

The first confirms CC_TOOLS accepts a report with no usable timing. It does not show downstream acceptance of a complete build as passing. The second confirms the generated helper treats zero as absence and does not write it; no cocotb runtime behavior is assumed. See [CC_TOOLS](CC_TOOLS_COMPLEXITY_REVIEW.md) and [COCOTB](COCOTB_COMPLEXITY_REVIEW.md).

## STA endpoint polarity

This isolates the real endpoint-selection code with synthetic sequential-cell models. It avoids reading a netlist or changing the shipped Liberty data.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 - <<'PY'
from types import SimpleNamespace as NS
from unittest.mock import patch
import DEVICE_MODELS as D

launch = NS(
    is_sequential=True,
    output_pins={"Q": {}},
    input_pins={"CLK": {}},
    clock_pin=lambda: "CLK",
    table_lookup=lambda op, ip, kind, transition, load:
        (10.0, 1.0, False) if kind == "cell_rise" else (9.0, 10.0, False),
)
capture = NS(
    is_sequential=True,
    output_pins={},
    input_pins={"CLK": {}, "D": {}},
    clock_pin=lambda: "CLK",
    setup_requirement=lambda ip, cp, transition, clock_transition: transition,
)
cells = {
    "launch": {"type": "launch", "connections": {"CLK": [2], "Q": [1]}},
    "capture": {"type": "capture", "connections": {"CLK": [2], "D": [1]}},
}
empty_edges = {"launch": set(), "capture": set()}
with patch.object(D, "LOAD_LIBERTY",
                  return_value={"launch": launch, "capture": capture}), \
     patch.object(D, "_load_netlist_json", return_value=(cells, {})), \
     patch.object(D, "_build_graph",
                  return_value=({1: ("launch", "Q")},
                                {1: [("capture", "D")]}, {}, {1: 0}, 0)), \
     patch.object(D, "_build_cell_graph",
                  return_value=(empty_edges, empty_edges)):
    result = D.run_sta("unused.json")
print("reported:", result["worst_period_ns"])
print("complete endpoint maximum:", max(10 + 1, 9 + 10))
PY
```

Observed: reported period **11.0 ns**, versus **19 ns** for the larger arrival-plus-setup cost. Selecting by arrival before evaluating both setup costs is not generally correct when the two transition slews differ. This is a confirmed algorithmic counterexample, **not** a measured 8 ns error for any real design/library. It also does not validate the rest of the timing engine. See [DEVICE_MODELS review](DEVICE_MODELS_COMPLEXITY_REVIEW.md).

## CIRCT availability

```sh
python3 - <<'PY'
import importlib.util
import shutil
import sys

print(sys.version)
for module in ("circt", "mlir", "pycde"):
    print(module, importlib.util.find_spec(module) is not None)
for executable in ("circt-opt", "firtool", "arcilator",
                   "yosys", "ghdl", "verilator"):
    print(executable, bool(shutil.which(executable)))
PY
```

Observed: no CIRCT/MLIR/PyCDE importable modules or circt-opt/firtool/arcilator executables; Yosys, GHDL and Verilator were available. No CIRCT toolchain was installed, built or benchmarked. Python 3.8 compatibility of a particular current wheel was **not tested**, so this report does not claim that installation is impossible.

Official [Python bindings instructions](https://circt.llvm.org/docs/PythonBindings/) document a unified LLVM/MLIR/CIRCT build and wheel construction. The assessment in the [overall review](REVIEW_COMPLEXITY.md#mlir-and-circt-assessment) combines that documented capability with local source analysis. It is a migration recommendation, not a successful exporter prototype.

## Limits

All behavioral results above are fresh probes from this continuation, except the clone analysis which was inherited and spot-checked against source. All seven shell blocks were executed directly from this document in fresh subprocesses and completed successfully, reproducing the stated outputs. Source hashes matched the measurement record. No source fix was applied. No FPGA timing sweep, native-versus-VHDL regression suite, CIRCT lowering, OpenSTA comparison or code-deletion benchmark was performed. The documentation checks validate links and coverage, not compiler behavior.

Reproduction snippets are retained here so follow-up changes can turn them into focused regression tests. Shared issue inventory and source test runners were left to the ongoing source-work session; the review is confined to its own documentation directory.

