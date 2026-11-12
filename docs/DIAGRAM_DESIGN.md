# DIAGRAM — the design diagram page

How every build writes `diagram.html`: one self-contained, offline web page in
`--out_dir` that shows the design's files, its MAINs joined by global wires, and one
graph per function of the call hierarchy, labeled with latency, measured delay and
clock domain.

- Implementation: [`src/DIAGRAM.py`](../src/DIAGRAM.py) (data extraction and the
  writer) and [`src/diagram/viewer.html`](../src/diagram/viewer.html) (the page:
  HTML, CSS and plain JavaScript, with a placeholder the design data replaces).
- User-facing description: [Viewing the design](README.md#viewing-the-design) in
  `docs/README.md`.

> **Reference, not a logbook.** Describe the system as it is now, in the present
> tense. No dated entries, no session write-ups — `git log` is the change record.
> When behavior changes, edit the affected section in place; when the *reason* is
> worth keeping, revise the matching entry in this file's `History` section, if it
> has one, rather than appending a new one. See
> [documentation conventions](pypeline_DESIGN.md#documentation-conventions).

## Table of Contents

- [1. Who does what](#1-who-does-what)
- [2. When the page is written](#2-when-the-page-is-written)
- [3. Data model](#3-data-model)
  - [Function graphs](#function-graphs)
- [4. Extraction rules](#4-extraction-rules)
  - [Files and imports](#files-and-imports)
  - [MAINs, clocks and the wiring flag](#mains-clocks-and-the-wiring-flag)
  - [Wire links](#wire-links)
  - [Which functions are drawn](#which-functions-are-drawn)
  - [Latency, delay and offsets](#latency-delay-and-offsets)
- [5. The viewer](#5-the-viewer)
  - [Views and navigation](#views-and-navigation)
  - [Filters and edge contraction](#filters-and-edge-contraction)
  - [Layout](#layout)
  - [Hardware scale](#hardware-scale)
  - [Search, source links and Mermaid text](#search-source-links-and-mermaid-text)
  - [Self-test](#self-test)
- [6. Limits](#6-limits)
- [7. Tests](#7-tests)
- [History](#history)

---

## 1. Who does what

| Piece | Owner |
|---|---|
| When the page is written or removed | `src/pipelinec` (three named calls, see [§2](#2-when-the-page-is-written)) |
| What the page shows (the design data) | `DIAGRAM._design_data` and its helpers |
| Import edges between design files | `PY_TO_LOGIC._discover_and_queue_module`, into `ParserState.pypeline_file_imports` |
| Drawing, layout, filters, navigation | `src/diagram/viewer.html` |

`DIAGRAM.py` only reads what parsing and timing already computed: the shared
`Logic` and `ParserState` tables both front ends fill, plus the Pypeline-only tables
where they exist (import edges, `pypeline_clock_names`, `pypeline_global_insts`,
`pypeline_wire_decls`, the field-level `global_wire_driven_paths` /
`global_wire_read_paths`, `main_resets`). It changes no compiler state and writes
only `diagram.html`.

## 2. When the page is written

The driver makes three calls ([build driver](SYN_DESIGN.md#the-build-driver-srcpipelinec)):

1. `DIAGRAM.FORGET_DIAGRAM(out_dir)` right after the up-to-date and
   built-hardware-simulation shortcuts. A build that stops before writing its own
   page leaves no page describing other hardware. A build with nothing to do (up
   to date) keeps the current page.
2. In a `--no_synth` build: `DIAGRAM.WRITE_DIAGRAM(parser_state, comb_timing_params,
   src_file)` after `AUTO_PIPELINE.WRITE_COMB_FINAL_FILES`, before any `--comb`
   simulation.
3. In a synthesizing build: `DIAGRAM.WRITE_DIAGRAM(parser_state,
   multimain_timing_params, src_file)` after `SWEEP.WRITE_SWEEP_RESULTS` and before
   the timing check, so a build that misses timing also has a page.

So a build writes the page exactly once, from its final parse and final timing
params, before any `--sim`.

`WRITE_DIAGRAM` serializes the data with `json.dumps(sort_keys=True)`, escapes
`</` (so no string can end the `<script>` block), and replaces the one
`__DIAGRAM_DESIGN_JSON__` placeholder of `viewer.html` with it. The page loads
nothing from the network and opens from `file://`. It prints
`Design diagram: <path>`.

## 3. Data model

The embedded JSON (`schema` 1). Every collection is sorted, so the same Pypeline
design gives a byte-identical page (C instance names carry per-parse hash suffixes,
so a C page is not reproducible).

| Key | Contents |
|---|---|
| `build` | top file, `front_end` (`pypeline` or `c`), part, synthesis tool module, `delays_known` (functions with a delay) |
| `files` | absolute path → `kind` (`design`, `library`, `generated`), `top`, `imports` (files with hardware it imports), `mains` |
| `clocks` | clock id (`"125 MHz eth_rx"`, `"no clock"`) → `mhz`, `group`, Python `name`, `goal_mhz` |
| `mains` | MAIN → `clock`, `latency`, `kind` (`main`, `global_inst`, `fifo`), `file`, `line`, `wiring` (reason or null), `reset`; global instances add `name`, `decl` and, for an async FIFO's two side MAINs, a shared `group` |
| `pins` | top-level Input/Output → `dir`, `bits`, Python `name`, `loc`, `clock_pin` |
| `wires` | global wire → Python `name`, `loc`, `bits`, `async` |
| `links` | `{src, dst, wire, name, bits, async, crossing}`: one writer→reader connection of a global wire field, or a clock crossing (`crossing: true`); `src`/`dst` are instance names or `pin:<name>` |
| `funcs` | function → see below |
| `inst_latency` | instance → total latency in clocks, for non-operator instances whose latency is not 0 |

A `funcs` entry has `kind`: `op` (operators and other built-ins), `vhdl` (a raw HDL
leaf), `wires` (`@wires`), `fsm` (the entity at an AUTO_FSM call site), `generated`
(source that is not a file on disk), `library` (under `include/`, or in `src/` itself
such as `pypeline.py`) or `user`. All kinds carry `delay_ns` (and
`delay_estimated`) when the function has a delay. Non-operators add `file`, `line`,
`def` (the Python or C name in the source), `inputs`/`outputs` as `[port, bits]`,
`mcp` and `regs`. Every kind except `op`, `vhdl` and `fsm` adds `graph`, and
`offsets` when [§4](#latency-delay-and-offsets) allows.

### Function graphs

`graph.nodes` is a list sorted by id; each node has an `id` and a `kind`:

| id | kind | What |
|---|---|---|
| `i:<port>` / `o:<port>` | `in` / `out` | function ports |
| `s:<local instance>` | `sub` | a call site: `name` (local name without its `[file_py_lN…]` origin), `callee`, `src` (call-site file and line), `auto_pipeline` / `auto_fsm` keys |
| `rq:<reg>` / `rd:<reg>` | `reg` / `reg_next` | a register's current value (a source) and next value (a sink) |
| `gr:<wire>` / `gw:<wire>` | `wire_read` / `wire_write` | a global wire read or written here (a readback wire maps to its wire) |
| `c:<wire>` | `const` | a constant, `name` is its value |
| `ce` | `ce` | the clock enable input |

`graph.edges` are arrays `[source node index, source port, driven node index,
driven port, bits, label, fb]`, indices into `graph.nodes`: operator call sites
have long names and are named once.

## 4. Extraction rules

### Files and imports

Pypeline design files are `parser_state.file_to_module_prefix` (every file that has
hardware), plus the top file and each MAIN's file. Every import of a `.py` file that
`_process_imports` follows records `(importer, imported)` in
`pypeline_file_imports`, files without hardware included. A file's `imports` lists
the files with hardware it reaches, through files without any (a factory wrapper
importing the real module). A C design is the files its MAINs are defined in.

A file is `generated` when its path is not on disk (`/pypeline_generated_*/…`,
`ifgen_*`), `library` when it is under `include/` or directly in `src/`.

### MAINs, clocks and the wiring flag

A MAIN's clock id comes from `main_mhz` and `main_clk_group`; the clock's Python
name from `pypeline_clock_names`, its goal from `SYN.GET_TARGET_MHZ` (the syn_mhz on
a synthesis-only tool). A MAIN named by a `pypeline_global_insts` declaration's
`main_names` is a `global_inst` or `fifo`, located at its declaration.

`wiring` marks a MAIN that only connects wires, for the viewer's clutter filter:
`@wires` MAINs, and MAINs with no registers anywhere in their hierarchy
(`LOGIC.LOGIC_NEEDS_CLOCK_ENABLE`) and no raw VHDL that
`SYN.LOGIC_IS_ZERO_DELAY(allow_none_delay=True)` calls zero delay (only wiring and
zero-delay operators). Global instance and FIFO MAINs are never wiring.

### Wire links

The writer and reader rules follow `VHDL.WRITE_MULTIMAIN_TOP`'s "Directly connected
global wires" section. For each global wire, over its `used_in_funcs`:

- a **writer** is each instance of a function with the wire in
  `write_only_global_wires` (or as a state reg, C), driving the paths in
  `global_wire_driven_paths` (the whole wire when empty);
- a **reader** is each instance of a function with the wire in
  `read_only_global_wires`, or a writer that reads it back
  (`readback_global_wires`), reading the paths in `global_wire_read_paths` (the
  whole wire when empty, as in C);
- an Input with no writer is a `pin:` writer; an Output is a `pin:` reader.

A reader path links to each other writer whose driven paths overlap it
(`PY_TO_LOGIC._path_overlaps`); the link carries the longer of the two paths, so a
stream's `.stream.data` and `.ready` run in opposite directions. Each
`clk_cross_var_info` entry adds write-MAIN → read-MAIN links with `crossing: true`:
C clock crossings, and the internal crossing between an async FIFO's two side MAINs.

`_assign_clocks`, `_check_global_insts`, `_check_clock_crossings` and
`VHDL.WRITE_MULTIMAIN_TOP` compute the same writers and readers each for itself;
see the [PY_TO_LOGIC review](code_reviews/complexity_review/PY_TO_LOGIC_COMPLEXITY_REVIEW.md).

### Which functions are drawn

`_funcs` walks the instance hierarchy from every MAIN. Every function it reaches
gets an entry, built once; operators and `vhdl` leaves are not entered. The walk
does not enter an AUTO_FSM call site: the callee gets a `fsm` entry and no graph,
since the schedule it implements is generated, not the user's hierarchy.

A graph follows `wire_drives` from each driving endpoint (an input, a register's
current value, a global wire read, a constant, the clock enable, a call site's
output port) through plain wires (variables and their aliases) to each driven
endpoint (an output, a register's next value, a global wire write, a call site's
input port), memoized per wire, iteratively. An edge's label is the first wire on
the way whose original variable (`alias_to_orig_var_name`) is in `variable_names`;
`fb` is set when the way passes through a `feedback_vars` variable. `bits` is the
width of the driving wire's type (`VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM`, memoized;
null for a type with no width).

### Latency, delay and offsets

Latencies come from the final timing params the build used, or, with none (a
`--no_synth` build without fixed latencies), from
`AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP`, which still counts
`@pipeline_latency` and other fixed latencies. MAIN latency is
`TimingParams.GET_TOTAL_LATENCY`, the value `built_hardware.json` records.

`delay_ns` is `logic.delay / SYN.DELAY_UNIT_MULT`. `offsets` maps each call site to
`[start_ns, end_ns]` from the compiler's own
`AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_PIPELINE_MAP` (`zero_clk_submodule_start_offset`
/ `_end_offset`), for exactly the functions it can map: stateless, no Feedback,
not raw VHDL, a positive delay, every submodule delay known, and
`FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL`. The viewer computes no arrival
times of its own.

## 5. The viewer

### Views and navigation

- **Tree pane:** the top file, then its import tree (each file once, under its first
  importer); library files without MAINs collapse under one node and generated files
  without MAINs are hidden. A file lists its MAINs (clock color, latency, kind,
  wiring reason, a checkbox to hide it from the design view); a MAIN expands lazily
  into its non-operator instances.
- **Design view** (`#design`): MAINs and connected pins joined by aggregated wire
  links; an async FIFO's two sides are one node. **File view** (`#file=<path>`): the
  file's MAINs and their neighbors, drawn as ghosts.
- **Function view** (`#inst=<instance>`): one instance's function graph. Clicking a
  block with a graph descends; clicking a global wire stub goes to the instance at
  its other end. The breadcrumb and `location.hash` make browser back and forward
  work.
- Tooltips give full names, file:line, ports and bits, latency, delay and the wires
  of an edge. One color per clock, from a fixed palette in sorted clock order; an
  edge between clocks is red, an ASYNC one dotted.

### Filters and edge contraction

- **hide wiring MAINs** (on): wiring MAINs are left out and links continue through
  them. Through a hidden MAIN a link continues only into the wires that MAIN's own
  graph drives from it (its graph contracted to wire reads and writes), so an I/O
  MAIN does not join every pin to every pin.
- **show operators** (off): operator call sites, constants and the clock enable are
  hidden and edges continue through them; the view notes how many were hidden.
- **hide feedback edges**: drops `fb` edges (drawn dashed otherwise).
- Hiding works by `contract()`: from each drawn node, follow edges through hidden
  nodes to the next drawn ones, one edge per pair, merging labels and widths.

### Layout

A small layered layout in the page (no library): cycles are broken by reversing
`fb` edges, then the narrower edge of each two-way pair (a stream's `ready` against
its data), then DFS back edges with wide edges explored first. Layers are longest
paths, with inputs, register current values and wire reads forced first and outputs,
register next values and wire writes last; six barycenter sweeps order each layer.
Edges are Bézier curves; reversed edges loop underneath. Wheel zooms, dragging pans,
**fit** resets.

### Hardware scale

The **hardware scale** toggle sizes blocks as `PipelineMap.write_png` did: width is
the callee's delay, height the mean of its input and output bus widths. When the
function has `offsets`, x is the block's start time on a ns axis (inputs left,
outputs right); otherwise the layered x positions stay.

### Search, source links and Mermaid text

- The search box matches instance paths (MAIN/local/local…, display names) of every
  non-operator instance and goes to the match's own view, or to its parent's view
  with the block highlighted.
- The header's **source** link opens the current function's definition as
  `vscode://file/<path>:<line>`; Ctrl- or Cmd-clicking a block sets it to the call
  site and opens it. Generated sources have no link.
- **copy as Mermaid** writes the current view as `flowchart LR` text to the
  clipboard, or into a text box where a `file://` page may not use the clipboard.

### Self-test

`#selftest` draws the design view, every file view, one function view per function
with a graph (and its hardware-scale view when it has offsets), the Mermaid text and
a search, then sets `data-ready="<views drawn>"` on `<body>`, or `data-error` with
the exception.

## 6. Limits

- Wire pass-through of a hidden wiring MAIN and C links are whole-wire: a struct
  wire split into several output pins inside an `@wires` MAIN reaches each of them.
- Labels come from variable names; a generated interface function's names show as
  they are (`rev3_if0df2bd50`).
- A function used at several instances has one graph; latencies are per instance.
- `offsets` compose the callees' own delays, so a function synthesized as a whole can
  be faster than its time axis: on sky130 (DEVICE_MODELS), `built_hardware_core_design`'s
  `divide_body` measures 57.2 ns while its soft divider's composed delay is 244.5 ns.
- The layout does not route around blocks; long edges can cross them.

## 7. Tests

| Test | Category | What |
|---|---|---|
| `inst/diagram_test.py` | elab_introspect | the data of three Pypeline designs and one C example, parsed in-process |
| `inst/diagram_build_test.py` | build_report_device_models | a sky130 build's latencies against `built_hardware.json`, delays and offsets, a `--no_synth` build, a failed build removing the page |
| `inst/diagram_render_test.py` | unit (needs `google-chrome`) | every view of three designs draws in headless Chrome |

See [`pypeline_TESTS.md`](pypeline_TESTS.md).

## History

**Replaces the graphviz pipeline map.** `SYN.ADD_PATH_DELAY_TO_LOOKUP` used to write
`pipeline_map.log` and, with graphviz installed, `PipelineMap.write_png` rendered
`pipeline_map.gv.png` into each pipelinable function's output directory: one
function level, nodes sized by delay and bus width, skipped above 128 submodules,
and turned off in the test suite because `dot` cost more than many builds. The
diagram's function views, constants and clock enable (with operators shown),
`offsets` and hardware scale carry the same information for every function, in one
page, with no extra dependency.
