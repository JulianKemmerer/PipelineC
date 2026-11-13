# DIAGRAM — the design diagram page

How every build writes `diagram.html`: one self-contained, offline web page in
`--out_dir` that shows the design's files, its MAINs joined by global wires, and one
graph per function of the call hierarchy, labeled with latency, measured delay, clock
domain and the types the wires carry.

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
  - [Types and interface roles](#types-and-interface-roles)
- [4. Extraction rules](#4-extraction-rules)
  - [Files and imports](#files-and-imports)
  - [MAINs, clocks and the wiring flag](#mains-clocks-and-the-wiring-flag)
  - [Wire links](#wire-links)
  - [Which functions are drawn](#which-functions-are-drawn)
  - [Latency, delay and offsets](#latency-delay-and-offsets)
- [5. The viewer](#5-the-viewer)
  - [Views and navigation](#views-and-navigation)
  - [Filters](#filters)
  - [Edge contraction and operator groups](#edge-contraction-and-operator-groups)
  - [Hiding single nodes](#hiding-single-nodes)
  - [Edge labels](#edge-labels)
  - [Layout](#layout)
  - [Hardware scale](#hardware-scale)
  - [Search, source links and Mermaid text](#search-source-links-and-mermaid-text)
  - [Self-test](#self-test)
- [6. Sharing the page](#6-sharing-the-page)
- [7. Limits](#7-limits)
- [8. Tests](#8-tests)
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
`global_wire_read_paths`, `main_resets`, the type descriptions
`pypeline_name_descriptions`). It changes no compiler state and writes only
`diagram.html`.

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

The embedded JSON (`schema` 2). Every collection is sorted, so the same Pypeline
design gives a byte-identical page (C instance names carry per-parse hash suffixes,
so a C page is not reproducible). Wherever the data names a type it holds `t`, an
index into `types`.

| Key | Contents |
|---|---|
| `build` | top file, `front_end` (`pypeline` or `c`), part, synthesis tool module, `delays_known` (functions with a delay) |
| `files` | absolute path → `kind` (`design`, `library`, `generated`), `top`, `imports` (files with hardware it imports), `mains` |
| `clocks` | clock id (`"125 MHz eth_rx"`, `"no clock"`) → `mhz`, `group`, Python `name`, `goal_mhz` |
| `mains` | MAIN → `clock`, `latency`, `kind` (`main`, `global_inst`, `fifo`), `file`, `line`, `wiring` (reason or null), `reset`; global instances add `name`, `decl` and, for an async FIFO's two side MAINs, a shared `group` |
| `pins` | top-level Input/Output → `dir`, `t`, Python `name`, `loc`, `clock_pin` |
| `wires` | global wire → Python `name`, `loc`, `t`, `async` |
| `links` | `{src, dst, wire, name, t, async, crossing}`: one writer→reader connection of a global wire field (`t` is the field's type), or a clock crossing (`crossing: true`); `src`/`dst` are instance names or `pin:<name>` |
| `funcs` | function → see below |
| `inst_latency` | instance → total latency in clocks, for instances (operators included) whose latency is not 0 |
| `types` | list of `{c, bits, role, name}`, sorted by `c` ([Types and interface roles](#types-and-interface-roles)) |

A `funcs` entry has `kind`: `op` (operators and other built-ins), `vhdl` (a raw HDL
leaf), `wires` (`@wires`), `fsm` (the entity at an AUTO_FSM call site), `generated`
(source that is not a file on disk), `library` (under `include/`, or in `src/` itself
such as `pypeline.py`) or `user`. All kinds carry `delay_ns` (and
`delay_estimated`) when the function has a delay, and `wiring` (the reason) on a
wiring call site ([§4](#mains-clocks-and-the-wiring-flag)). Non-operators add
`file`, `line`, `def` (the Python or C name in the source), `inputs`/`outputs` as
`[port, t]`, `mcp` and `regs`. Every kind except `op`, `vhdl` and `fsm` adds
`graph`, and `offsets` when [§4](#latency-delay-and-offsets) allows.

### Function graphs

`graph.nodes` is a list sorted by id; each node has an `id` and a `kind`:

| id | kind | What |
|---|---|---|
| `i:<port>` / `o:<port>` | `in` / `out` | function ports, with `t` |
| `s:<local instance>` | `sub` | a call site: `name` (local name without its `[file_py_lN…]` origin), `callee`, `src` (call-site file and line), `auto_pipeline` / `auto_fsm` keys |
| `rq:<reg>` / `rd:<reg>` | `reg` / `reg_next` | a register's current value (a source) and next value (a sink), with `t` |
| `gr:<wire>` / `gw:<wire>` | `wire_read` / `wire_write` | a global wire read or written here (a readback wire maps to its wire) |
| `c:<wire>` | `const` | a constant, `name` is its value |
| `ce` | `ce` | the clock enable input |

`graph.edges` are arrays `[source node index, source port, driven node index,
driven port, t, names, fb]`, indices into `graph.nodes` (operator call sites have
long names and are named once). `t` is the driving wire's type, `names` the
variables on the way (the driving one first), `fb` 1 when the way passes through a
`Feedback` variable.

### Types and interface roles

`DIAGRAM._Types` collects every type the data names and writes one row per type:

- `c`: the C type name the compiler uses (`wire_to_c_type`,
  `struct_to_field_type_dict`).
- `bits`: its width (`VHDL.C_TYPE_STR_TO_VHDL_SLV_LEN_NUM`), null for a type with
  no width.
- `role`: the type's [interface](pypeline_guide.md#bidirectional-ports-interface)
  role, left out when plain:
  - `fwd`: an `@interface`'s `.fwd_t`, a plain `{data, valid}` stream
    ([`stream.make_stream_t`](pypeline_guide.md#streams-stream_t), and any C
    struct of that shape), or a type that holds one in a field or as array
    elements;
  - `fb`: an `.fb_t`, or a type that holds one and nothing forward.

  A half is recognized by its description (`pypeline_name_descriptions`, kind
  `interface_fwd` / `interface_fb`). A generated interface function types each
  `Feedback` with a plain copy of a half (`interface_func._plain_shape_of`) that
  keeps the half's fields but not its role; a struct whose fields equal the fields
  of halves that all have one role gets that role.
- `name`: the name the source uses, when it differs from `c`: the description's
  class name (or the user's `name=`), with array dimensions. A plain copy
  (`<half class>_plain`) is named after its half, `chan_intrf_fb_t_plain`; it is
  matched to the half whose C name starts with the copy's class name, since every
  stream interface's `.fb_t` has the same fields. Where several types in the page
  share a name, each adds its factory arguments (`stream_t<uint8_t>`), or its field
  types when it has none. Scalars and C types keep their C names.

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

`wiring` marks what only connects wires, for the viewer's wiring filter
(`_wiring_reason`):

- MAINs: `@wires` MAINs, and MAINs with no registers anywhere in their hierarchy
  (`LOGIC.LOGIC_NEEDS_CLOCK_ENABLE`) and no raw VHDL that
  `SYN.LOGIC_IS_ZERO_DELAY(allow_none_delay=True)` calls zero delay (only wiring and
  zero-delay operators). Global instance and FIFO MAINs are never wiring.
- Call sites: `@wires` functions (the casts a design declares or the stream
  library generates among them), and operators the same zero-delay rule passes:
  constant field and index selects (`CONST_REF_RD`), bit slices and concatenations,
  constant shifts, VHDL function and expression helpers. A clock crossing or black
  box never is. A user's own function with no logic is not marked: it stays a block
  of the hierarchy (see [History](#history)).

In a synthesizing build `LOGIC_IS_ZERO_DELAY` also counts measured 0 ns delays, so a
MAIN can be wiring there and not in a `--no_synth` build.

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
input port), memoized per wire, iteratively. An edge's `names` are the wires on the
way, the driving wire first, whose original variable (`alias_to_orig_var_name`) is
in `variable_names`, without repeats; a call's output passed straight into another
call has none. `fb` is set when the way passes through a `feedback_vars` variable.
`t` is the driving wire's type.

### Latency, delay and offsets

Latencies come from the final timing params the build used, or, with none (a
`--no_synth` build without fixed latencies), from
`AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP`, which still counts
`@pipeline_latency` and other fixed latencies. MAIN latency is
`TimingParams.GET_TOTAL_LATENCY`, the value `built_hardware.json` records.
Operators are listed too: pipelining puts its registers into operators (and raw
VHDL), so an operator instance with a latency is where they are. A function's own
`TimingParams` carries no slices; its latency comes from its submodules'.

`delay_ns` is `logic.delay / SYN.DELAY_UNIT_MULT`. `offsets` maps each call site to
`[start_ns, end_ns]` from the compiler's own
`AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_PIPELINE_MAP` (`zero_clk_submodule_start_offset`
/ `_end_offset`), for exactly the functions it can map: stateless, no Feedback,
not raw VHDL, a positive delay, every submodule delay known, and
`FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL`. The viewer computes no arrival
times of its own.

## 5. The viewer

### Views and navigation

- **Tree pane:** a *whole design* entry, then the top file and its import tree
  (each file once, under its first importer); library files without MAINs collapse
  under one node and generated files without MAINs are hidden. A file lists its
  MAINs (clock color, latency, kind, wiring reason, a checkbox to hide it from the
  design view); a MAIN expands lazily into its non-operator instances. Wiring
  instances leave the tree while the wiring filter hides them.
- **Design view** (`#design`): MAINs and connected pins joined by aggregated wire
  links; an async FIFO's two sides are one node. The top file's link opens it too.
  **File view** (`#file=<path>`, any other file): the file's MAINs and the MAINs of
  other files they connect to, drawn as ghosts, under a banner that links back to
  the whole design. The filters apply to the file's own MAINs as well.
- **Function view** (`#inst=<instance>`): one instance's function graph. Clicking a
  block with a graph descends; clicking a global wire stub goes to the instance at
  its other end. The breadcrumb and `location.hash` make browser back and forward
  work.
- Tooltips give full names, file:line, ports with their types, latency, delay, and
  for an edge its variables (or, with none, its two endpoints), its type, and the
  type of each `Feedback` or register it passes through. One color per clock, from
  a fixed palette in sorted clock order; an edge between clocks is red, an ASYNC one
  dotted, one through a `Feedback` or a passed-through register dashed.

### Filters

The **filters** panel sets, for each kind of node or edge, a mode:

- **show**;
- **group** (operators only): see [operator groups](#edge-contraction-and-operator-groups);
- **pass**: hidden, with its edges continuing through it;
- **drop**: hidden with its edges.

A node with no edges in (an input, a register's current value, a wire read) or none
out has no pass mode: its kind offers show and hide only.

| Kind | Applies to | Modes | Default |
|---|---|---|---|
| inputs | function inputs, Input pins | show, drop | show |
| outputs | function outputs, Output pins | show, drop | show |
| registers | `reg` and `reg_next`; pass joins a register's next value to its current value as one edge | show, pass, drop | show |
| global wire reads and writes | `wire_read` / `wire_write` stubs | show, drop | show |
| Feedback edges | function-graph edges with `fb` | show, drop | drop, feedback only |
| wiring | wiring MAINs and call sites ([§4](#mains-clocks-and-the-wiring-flag)) | show, pass, drop | pass |
| operators | `op` call sites that are not wiring | show, group, pass, drop | group |
| constants, clock enable | `const`, `ce` | show, drop | drop |
| other files' MAINs | a file view's ghosts | show, drop | show |

The first five kinds are typed: a second setting picks which [interface
roles](#types-and-interface-roles) the mode applies to (every type, all but
forward, forward only, feedback only, plain only), and the rest are shown. A node's
role is its type's (a wire stub's is its wire's); a `Feedback` edge's is the type
of the edge. So *inputs: hide, all but forward* keeps only stream and `.fwd_t`
inputs, and the default *Feedback edges: hide, feedback only* drops the `.fb_t`
(ready) loops while forward data fed back to an earlier call, and plain-typed
`Feedback`s, stay. Design-view links are not filtered by role: a global FIFO's or a
plain wire's `ready` field has no interface type.

A label setting picks what edge labels show ([Edge labels](#edge-labels)).
Settings persist in the browser's storage (`localStorage`, per browser profile, not
per design); a page that cannot use it starts from the defaults.

### Edge contraction and operator groups

- Dropped nodes leave with their edges, before anything else; so do the `Feedback`
  edges the filter drops. A passed-through register adds an edge from its next
  value to its current value.
- In **group** mode, operators joined by an edge form one group (union-find over
  the remaining edges between grouped operators); each group is one block with the
  id `g:<first member id>`. Edges between two members disappear into the group,
  keeping their variable names for its tooltip.
- `contract()` then draws each pass-mode node out of the graph: from each drawn node
  it follows edges through hidden nodes to the next drawn ones, one edge per pair,
  merging their variables, the type into the driven port, widths, and the types of
  the `Feedback` variables and registers on the way.
- A group is a cloud when it is known to be combinational: no member has a latency
  of its own (`inst_latency`) and the function instance drawn has none either (a
  function with latency lines up its paths with registers between its submodules,
  which may fall among the group's operators). Otherwise it is a dashed block marked
  with its operators' latency (`L=n`), or the function's (`in L=n`). The group's label lists
  the most common operators as symbols (`+`, `==`, `mux`); its tooltip counts every
  operator kind, lists the variables inside, and, where the function has
  `offsets`, the delay from the group's first start to its last end.
- In the design view, through a hidden MAIN a link continues only into the wires that
  MAIN's own graph drives from it (its graph contracted to wire reads and writes),
  so an I/O MAIN does not join every pin to every pin.

### Hiding single nodes

Right-clicking a block, port or pin opens a menu with its hide modes (pass and drop,
or just hide for a node with no pass mode). Hiding a register hides both its values,
hiding an operator group hides each of its operators, hiding a design-view node
hides each MAIN of it. The tree's MAIN checkboxes hide with pass. The keys
(`<function>\u0001<node id>`, `main\u0001<MAIN>`, `pin\u0001<pin>`) are stored per
top file in the browser's storage; the header's **N hidden** button lists them with
a *show* link each and *show all*. A hidden function-graph node is hidden in every
instance of that function.

### Edge labels

An edge's label is its first variable and the type into its driven port,
`name: type (bits)`, or just the type when it has no variable; the label setting can
show the name, the type or nothing. A type shows its readable `name`, cut to 30
characters. Labels are placed widest bus first, each at the first of three points
along its curve (the middle, then a third of the way from each end; the bottom of a
back edge's loop) that overlaps no block and no placed label; one that fits nowhere
is left to the tooltip. The gap between layers widens to fit three quarters of the
labels, up to 220 px. Views with more edges (40 in the design view, 60 in a function
view) and the hardware scale show no labels, only tooltips.

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
the callee's delay, height the mean of its input and output bus widths (a block
without port data, an operator or a group, takes its widest edge). When the function
has `offsets`, x is the block's start time on a ns axis (inputs left, outputs right);
otherwise the layered x positions stay. An operator group spans from its first
member's start to its last member's end, or, without offsets, is as wide as its
slowest member.

### Search, source links and Mermaid text

- The search box matches instance paths (MAIN/local/local…, display names) of every
  non-operator instance and goes to the match's own view, or to its parent's view
  with the block highlighted.
- The header's **source** link opens the current function's definition as
  `vscode://file/<path>:<line>`; Ctrl- or Cmd-clicking a block sets it to the call
  site and opens it. Generated sources have no link.
- **copy as Mermaid** writes the current view as `flowchart LR` text (a group as a
  round node) to the clipboard, or into a text box where a `file://` page may not use
  the clipboard.

### Self-test

`#selftest` resets the filters to their defaults and nothing hidden (it reads and
writes no browser storage), then draws:

- the design view, checking that no wiring MAIN is drawn and there is no file
  banner, that the top file's link opens it, and every file view, checking each has
  its banner;
- each function with a graph three times: with the defaults, checking that no
  operator, wiring call site, constant or clock enable is drawn, no drawn edge passes
  a `Feedback` whose type is `fb`, every edge ends at drawn nodes, and two operators
  joined by a remaining edge share a group; with everything shown, checking that every
  graph node is drawn; and with everything hidden (pass where a kind has it, drop
  otherwise), checking that only non-operator, non-wiring call sites and no
  `Feedback` edges are drawn. The checks classify nodes from the data, not with the
  filters' own code;
- the hardware-scale view of each function with `offsets`;
- the design view with one MAIN hidden by hand through `setHidden`, as its menu
  does, pass and drop, checking it is not drawn and is drawn again once shown; a
  filter changed through `filtersChanged`, as the panel does; and, each checked to
  draw without an error, the hidden list, a node's menu, the filters panel, the
  Mermaid text and a search.

It sets `data-ready="<views drawn>"` on `<body>`, or `data-error` with the failed
check or exception.

## 6. Sharing the page

`diagram.html` needs nothing else from the output directory: the data and the
viewer are inside it, and it loads nothing from the network. It holds the build
machine's absolute file paths (tooltips, file names, the source links) and every
function, wire and type name of the design. The `vscode://` source links open only
where the same paths exist.

## 7. Limits

- Wire pass-through of a hidden wiring MAIN and C links are whole-wire: a struct
  wire split into several output pins inside an `@wires` MAIN reaches each of them.
- Variable names come from `variable_names`; a generated interface function's names
  show as they are (`rev3_if0df2bd50`).
- Type names that stay alike after factory arguments (the same class with arguments
  of the same name) are told apart only by their widths and tooltips.
- A function used at several instances has one graph; latencies are per instance,
  and hiding one of its nodes by hand hides it in every instance.
- `offsets` compose the callees' own delays, so a function synthesized as a whole can
  be faster than its time axis: on sky130 (DEVICE_MODELS), `built_hardware_core_design`'s
  `divide_body` measures 57.2 ns while its soft divider's composed delay is 244.5 ns.
- An operator group in a function instance with latency is marked `in L=n`
  without saying whether or where registers fall among its operators.
- The layout does not route around blocks; long edges can cross them.

## 8. Tests

| Test | Category | What |
|---|---|---|
| `inst/diagram_test.py` | elab_introspect | the data of four Pypeline designs and one C example, parsed in-process: files, clocks, links, graphs, edge names, `Feedback` edges and their types, type roles and names, wiring call sites, call-site kinds |
| `inst/diagram_build_test.py` | build_report_device_models | a sky130 build's latencies against `built_hardware.json`, delays and offsets, the pipelined divider's operator latencies, a `--no_synth` build, a failed build removing the page |
| `inst/diagram_render_test.py` | unit (needs `google-chrome`) | the [self-test](#self-test) of four designs' pages in headless Chrome |

`inst/diagram_interfaces_design.py` is the fixture for interface roles, type names,
`Feedback` edges of both roles and wiring call sites. See
[`pypeline_TESTS.md`](pypeline_TESTS.md).

## History

**Replaces the graphviz pipeline map.** `SYN.ADD_PATH_DELAY_TO_LOOKUP` used to write
`pipeline_map.log` and, with graphviz installed, `PipelineMap.write_png` rendered
`pipeline_map.gv.png` into each pipelinable function's output directory: one
function level, nodes sized by delay and bus width, skipped above 128 submodules,
and turned off in the test suite because `dot` cost more than many builds. The
diagram's function views, constants and clock enable (shown by the filter),
`offsets` and hardware scale carry the same information for every function, in one
page, with no extra dependency.

**Wiring call sites are `@wires` functions and wiring operators only.** Marking
every call site whose function `LOGIC_IS_ZERO_DELAY` passes, as for MAINs, hid user
functions that only route fields, such as the routing half of a feedforward loop in
an interface function (`diagram_interfaces_design.py`'s `route`), and with it the
loop. A MAIN with no logic is top-level glue; a function with none is still part of
the hierarchy its author wrote.
