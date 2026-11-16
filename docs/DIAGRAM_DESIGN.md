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
  - [Struct returns](#struct-returns)
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

The embedded JSON (`schema` 3). Every collection is sorted, so the same Pypeline
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
| `links` | `{src, dst, wire, name, t, async, crossing, role}`: one writer→reader connection of a global wire field (`t` is the field's type, `role` the [interface role](#types-and-interface-roles) of its data, left out when plain), or a clock crossing (`crossing: true`); `src`/`dst` are instance names or `pin:<name>` |
| `funcs` | function → see below |
| `inst_latency` | instance → total latency in clocks, for instances (operators included) whose latency is not 0 |
| `types` | list of `{c, bits, role, name, fields, interface, feedback}`, sorted by `c` ([Types and interface roles](#types-and-interface-roles)) |

A `funcs` entry has `kind`: `op` (operators and other built-ins), `vhdl` (a raw HDL
leaf), `wires` (`@wires`), `fsm` (the entity at an AUTO_FSM call site), `generated`
(source that is not a file on disk), `library` (under `include/`, or in `src/` itself
such as `pypeline.py`) or `user`. All kinds carry `delay_ns` (and
`delay_estimated`) when the function has a delay, and `wiring` (the reason) on a
wiring call site ([§4](#mains-clocks-and-the-wiring-flag)); a `sim_assert` operator
has `assert`. Non-operators add `file`, `line`, `def` (the Python or C name in the
source; for a generated function, the function it was made from,
[§4](#which-functions-are-drawn)), `inputs`/`outputs` as `[port, t]`, `mcp` and
`regs`. Every kind except `op`, `vhdl` and `fsm` adds
`graph`, and `offsets` when [§4](#latency-delay-and-offsets) allows.

### Function graphs

`graph.nodes` is a list sorted by id; each node has an `id` and a `kind`:

| id | kind | What |
|---|---|---|
| `i:<port>` / `o:<port>` | `in` / `out` | function ports, with `t` |
| `s:<local instance>` | `sub` | a call site: `name` (local name without its `[file_py_lN…]` origin), `callee`, `src` (call-site file and line), `auto_pipeline` / `auto_fsm` keys, `ref` on a constant field select or assembly, `op` on a call an operator was dispatched to |
| `rq:<reg>` / `rd:<reg>` | `reg` / `reg_next` | a register's current value (a source) and next value (a sink), with `t` |
| `gr:<wire>` / `gw:<wire>` | `wire_read` / `wire_write` | a global wire read or written here (a readback wire maps to its wire), with the `role` of the fields it reads or drives (`fb` when all are feedback data, `fwd` when one is forward); a write lists the field paths it drives in `driven` |
| `c:<wire>` | `const` | a constant, `name` is its value |
| `ce` | `ce` | the clock enable input |

`graph.edges` are arrays `[source node index, source port, driven node index,
driven port, t, names, fb]`, indices into `graph.nodes` (operator call sites have
long names and are named once). `t` is the driving wire's type, `names` the
variables on the way (the driving one first), `fb` 1 when the way passes through a
`Feedback` variable.

`ref` is `[variable, read path, [path per input port]]`, from
`ref_submodule_instance_to_ref_toks` and
`ref_submodule_instance_to_input_port_driven_ref_toks`: input `ref_toks_k` drives
the part of the variable at its path (field names, array indices), and the output
is the part at the read path. A select reads a part of one input (`p.second` from
`p`); an assembly builds a value from parts (`o` from `o.first` and `o.second`, a
global wire written field by field over its read-back value). The variable is the
source's name (a global wire's by its declared name), or null for an elaboration
temporary. `op` lists the op names dispatched to the callee
(`pypeline_operator_impl_ops`).

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

  An `@interface`'s `.wire_t` (the struct of a `Wire` of the interface itself)
  holds its fields plain, so it has the role its fields give it; its `feedback`
  lists the fields that are `Feedback` fields of the interface (the `.fb_t`'s,
  matched by the class's description). `_Types.path_role` gives the role of the
  data at a field path: `fb` inside such a field, else the role of the first type
  on the way with a role of its own (a half, a copy of one, a stream), else the
  leaf's.

  A half is recognized by its description (`pypeline_name_descriptions`, kind
  `interface_fwd` / `interface_fb`). A generated interface function types each
  `Feedback` with a plain copy of a half (`interface_func._plain_shape_of`) that
  keeps the half's fields but not its role; a struct whose fields equal the fields
  of halves that all have one role gets that role.
- `name`: the name the source uses, when it differs from `c`, with array
  dimensions: the user's `name=`, else the name the design's own modules give the
  type at module level (`_module_type_names`: a `@struct` or `@enum` class by its
  global's name, `byte_stream_t = make_stream_t(uint8_t)`; an `@interface`'s
  types as `<global>.fwd_t`, `.fb_t`, `.stream_t`, `.wire_t`; a type with several
  such names takes the one the most modules use, then the shortest), else the
  description's class name. The modules are the top file's (`top_level_module_globals`)
  and the non-library files of `file_to_module_prefix` found in `sys.modules`. A plain
  copy (`<half class>_plain`) is named after its half, `chan_if_t.fb_t_plain`; it is
  matched to the half whose C name starts with the copy's class name, since every
  stream interface's `.fb_t` has the same fields. Where several types in the page
  share a name, each adds its factory arguments (`stream_t<uint8_t>`), or its field
  types when it has none. Scalars and C types keep their C names.
- `fields`: a struct's fields as `[name, t]`, in declaration order, for the
  structs the data names (their own fields' rows have none).
- `interface`: the struct is one interface's own type (a half, a plain copy of one,
  a `{data, valid}` stream, a `.wire_t`): one port, never split
  ([Struct returns](#struct-returns)).

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
stream's `.stream.data` and `.ready` run in opposite directions, and the role of the
data at that path (`_Types.path_role`): a `.wire_t`'s `ready` is feedback data. Each
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
in `variable_names` and is not an elaboration temporary (the local an inline struct
constructor is built in, `PY_TO_LOGIC.INLINE_CTOR_PREFIX`), without repeats; a
call's output passed straight into another call has none. `fb` is set when the way passes through a `feedback_vars` variable.
`t` is the driving wire's type.

A generated function (kind `generated`: an interface function's hw_func, made by
`make_hw_func_from_interface_func` in a module with no file) shows the function it
was made from: elaboration records that function's description under the
generated function's key in `pypeline_name_descriptions` (kind `function`), and
its `symbol`, `source` and `line` become the entry's `def`, `file` and `line`
(`_generated_origin`), so the block reads `merge`, not `merge_if55c8d8ad`, and the
source link opens the interface function.

A call site's `op` comes from `pypeline_operator_impl_ops`, which elaboration fills
at every operator it dispatches to a registered implementation (unary, binary,
comparison, variable shift; `FuncElaborator._record_operator_impl`): the default
soft comparator, divider or shifter, or a design's own. The table is per callee, so
a direct call to the same specialization is drawn as an operator too.

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
  Pins that a hidden MAIN packs into one global wire (an I/O `@wires` MAIN's AXIS
  pins) stand for that wire's interface port and are drawn as one port, named by
  what the pins' names share up to a `_` (`decrypt_s_axis`), else by the wire; its
  edge carries one wire, the part of the global wire its pins' links share
  (`axis_in_if.stream`), with the role of the data there. Pins that a path reaches
  without passing a hidden MAIN, or that go on into more than one wire, stay pins.
  **File view** (`#file=<path>`, any other file): the file's MAINs and the MAINs of
  other files they connect to, drawn as ghosts, under a banner that links back to
  the whole design. The filters apply to the file's own MAINs as well.
- **Function view** (`#inst=<instance>`): one instance's function graph. Clicking a
  block with a graph descends; clicking a global wire stub goes to the instance at
  its other end. The breadcrumb and `location.hash` make browser back and forward
  work.
- Tooltips give full names, file:line, ports with their types, latency, delay, and
  for an edge its wire (or `N wires:` and a list) with types
  ([Edge labels](#edge-labels)), the other variables on the way, and the type of
  each `Feedback` or register it passes through. One color per clock, from a fixed
  palette in sorted clock order; an edge between clocks is red, an ASYNC one dotted,
  one through a `Feedback` or a passed-through register dashed.
- Hovering an edge (a 12 px invisible copy of it takes the mouse) draws it again in
  the highlight color, thicker, over the other edges, and highlights its label;
  hovering a block does that for every edge of the block.
- A block shows its instance name, then its def name where it differs, `L=n` and
  its delay, then how it is built (`AUTO_PIPELINE`, `AUTO_FSM`, `vhdl`, `MCP`);
  its registers and the wiring reason are in the tooltip. A call an operator was
  dispatched to shows the operator's symbol first (`<`, then `soft_cmp_prefix`).

### Filters

The defaults aim at the diagram a person draws of the block, one level of the
hierarchy at a time, to sit beside a description of it: the forward data path
between the blocks the code calls, without the handshake that goes back
(`ready`), the sideband beside the interfaces, or the operators and registers apart
from the logic they make up.

The **filters** panel sets, for each kind of node or edge, a mode:

- **show**;
- **group** (operators and registers): see [operator groups](#edge-contraction-and-operator-groups);
- **pass**: hidden, with its edges continuing through it;
- **drop**: hidden with its edges.

A node with no edges in (an input, a register's current value, a wire read) or none
out has no pass mode: its kind offers show and hide only.

| Kind | Applies to | Modes | Default |
|---|---|---|---|
| inputs | function inputs, Input pins | show, drop | drop, feedback and sideband |
| outputs | function outputs (a returned struct's fields), Output pins | show, drop | drop, feedback and sideband |
| registers | `reg` and `reg_next`; group puts both values in the logic block of what they connect to, pass joins the next value to the current value as one edge | show, group, pass, drop | group |
| global wire reads and writes | `wire_read` / `wire_write` stubs | show, drop | drop, feedback and sideband |
| feedback data | wires whose data is feedback ([Edge contraction](#edge-contraction-and-operator-groups)), design-view links with role `fb` | show, drop | drop |
| Feedback edges | function-graph edges with `fb` | show, drop | drop, feedback only |
| wiring | wiring MAINs and call sites ([§4](#mains-clocks-and-the-wiring-flag)) | show, pass, drop | pass |
| operators | `op` call sites that are not wiring, and calls with `op` | show, group, pass, drop | group |
| constants, clock enable | `const`, `ce` | show, drop | drop |
| other files' MAINs | a file view's ghosts | show, drop | show |

Inputs, outputs, registers, wire stubs and `Feedback` edges are typed: a second
setting picks which [interface roles](#types-and-interface-roles) the mode applies
to (every type, all but forward, forward only, feedback only, plain only, or
*feedback, and plain beside forward interfaces*), and the rest are shown. A node's
role is its type's (a wire stub's is the role of the fields it reads or drives, a
returned struct's output the field's); a `Feedback` edge's is the type of the edge.
The default for ports, *feedback, and plain beside forward interfaces*, takes
feedback ports always and plain ones in a view whose inputs (and wire reads) and
outputs (and wire writes) both include a forward interface port: there the plain
ones are sideband (an `aad_len` beside the streams). A view without forward
interfaces both ways keeps its plain ports. The design view does the same with its
pins, a pin group taking its wire's role ([Views](#views-and-navigation)). So
*inputs: hide, all but forward* keeps only stream and `.fwd_t` inputs, and the
default *Feedback edges: hide, feedback only* drops the `.fb_t` (ready) loops while
forward data fed back to an earlier call, and plain-typed `Feedback`s, stay. A
global FIFO's or a plain wire's `ready` field has no interface type, so the
feedback-data filter does not take it.

The panel's *wire label text* picks what a label says (the name by default), and
the header's **wire labels** box (on by default) shows every label
([Edge labels](#edge-labels)). Settings persist in the browser's storage
(`localStorage`, per browser profile, not per design), under a key that changes
when the defaults do (`filters.3`), so settings saved under old defaults do not
keep them; a page that cannot use it starts from the defaults.

### Edge contraction and operator groups

- Dropped nodes leave with their edges, before anything else; so do the `Feedback`
  edges the filter drops. A passed-through register adds an edge from its next
  value to its current value.
- In **group** mode, operators and registers joined by an edge, directly or through
  wiring in pass mode (a field select between two operators), form one group
  (union-find); a register's two values are in one group. Each group is one block
  with the id `g:<first member id>`. Edges between two members disappear into the
  group, keeping their variable names for its tooltip.
- In a function view, `tracePaths` then draws each pass-mode node out of the graph:
  from each drawn node it follows edges through hidden nodes to the next drawn ones,
  carrying where the path's data sits in its values ([Struct
  returns](#struct-returns)), one edge per pair, merging the wires of its paths
  ([Edge labels](#edge-labels)), their variables, widths (summed over the wires),
  and the types of the `Feedback` variables and registers on the way. A path is
  visited once per edge and state. The design view does the same with
  `contract()`, without data positions.
- A wire is **feedback data** when the part of its source's value it carries, or
  its part of the driven port, has the role `fb` (`pathRole`): a `ready` selected
  from an `.fb_t` input or from a `.wire_t`'s `ready` field, or a value fed into an
  `.fb_t` port. The feedback-data filter drops such wires from their edges, and an
  edge left with none. A port or wire stub left with no edge that way is hidden too.
  A logic block with no drawn output (one that fed only feedback, hidden ports or
  nothing at all, such as assertions) is hidden, again until none is left.
- A group is a cloud when it is known to be combinational: no member has a latency
  of its own (`inst_latency`), the function instance drawn has none either (a
  function with latency lines up its paths with registers between its submodules,
  which may fall among the group's operators), and it holds no register. Otherwise
  it is a dashed block marked with its operators' latency (`L=n`), the function's
  (`in L=n`) and its register count. The group's label lists the most common
  operators as symbols (`+`, `==`, `mux`, an operator dispatched to a call by its
  symbol, and `assert` for a `sim_assert` only after the hardware ones), or, with
  none, its registers' names; its
  tooltip counts every operator kind, lists the registers and the variables inside,
  and, where the function has `offsets`, the delay from the group's first start to
  its last end.
- In the design view, through a hidden MAIN a link continues only into the wires that
  MAIN's own graph drives from it (its graph contracted to wire reads and writes),
  so an I/O MAIN does not join every pin to every pin.

### Struct returns

A function returning a struct that is not one interface's own type (a `route_t` of
interface halves, a `pair_t`, a generated interface function's result) stands for
an output per field, as a Python function returning several values does. Its output
is drawn as one port per direct field (`o:return_output.<field>`, `splitOutputs`),
in declaration order, one level deep; inputs are never split. Each field port has
the field's type and role, its own filter mode, and its own hide key.

To know which field a path reaches, `fieldStep` carries a state along each path:
`src`, the part of the path's source value it carries (exact until a function on
the way computes from it); `dst`, its place in the current wire's value; and the
names the code gives it at its last field select and its last assembly. A constant
field select or assembly (a node's `ref`) moves the data by field paths: a select
whose read path is inside the data's place takes that part (the source part grows);
an assembly puts the data at its input's path inside the output; a path whose part
of the input the output does not hold ends. In an assembly, inputs with longer
paths override parts of one with a shorter path (a global wire written field by
field over its read-back value), so the path goes on as each field left. Any other
node (a function, a register passed through) outputs a value of its own. Paths deeper
than 16 tokens end (they come only from loops through registers).

A path arriving at a returned struct's port goes to the field its `dst` names, or,
when the whole value arrives, to every field (the source part growing by the field
when nothing computed from it). A global wire write takes only the parts the
function drives (its node's `driven`): the elaborated value also passes its other
fields through from the read-back, which no hardware drives.

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

An edge carries one wire, or a bundle: every path merged into it. A wire is named
as the code names it:

- in the design view, by the global wire fields it chains, `a → b` through a hidden
  MAIN (a pin group's edge by the part of the wire its pins share);
- in a function view, by the variable and fields of its path's last field select
  (`p.second`, `chacha.key_if`, `bcast.axis_out_if[1]`), else of its last assembly
  (`o.first`, a global wire's field `link.data`), else by its first variable; with
  none, by its ends, `source → destination`: the output it comes from (the call and
  the field of its returned struct, `make_pair.first`, an input or register and the
  part taken) and the input it feeds (the callee's argument, `mac_func.data_in_if`,
  an output's field, a register or global wire). A logic block's ports have no
  names, so a wire from or to one is named by its other end. A whole value reaching
  a returned struct's outputs adds the field to its name.

A wire's type is the type of its part of the driven port (`o.data` into a
`byte_stream_t` output is a `uint8_t`); a type shows its readable `name`, cut to 48
characters. The tooltip says the wire's name and type, or `N wires:` and one line
per wire. Labels show the names by default; the header's **wire labels** box hides
or shows every label, and right-clicking an edge (or its label) opens a menu that
shows or hides just its label; a choice that matches the box is dropped, so the
edge follows the box again. Those choices are stored per top file in the browser's storage, keyed
`<view>\u0001<source>\u0001<driven>` with the view `design` or the function; the
menu can return a view's labels to the box, and the filters panel resets them all.

A shown label names every wire, none left out, in the order of the ports they drive
(a call's arguments, as the code lists them), then by name. With the *wire label text* name
(the default), the fields one variable carries share a line, their common path and
then each field after it, wrapped between fields at 40 characters
(`prepared_if.stream: valid, data.context_v, data.r, …`; `nameLines`); with name
and type, or the type, a label has a line per wire, `name: type (bits)`, each cut
to 80 characters. Wires whose names differ only in one array index, with one type,
share an entry as index runs (`key_bytes[0..31]`, `k[0..1,3]`; `compactWires`),
here and in the tooltip. A label's text has an outline in the background color, so
an edge crossing it does not hide it. Labels are placed widest bus first, each at the first of five points along
its curve (the middle, then 35, 65, 25 and 75 % of the way; the middle of each place
of an edge that skips layers; the bottom of a back edge's loop) that overlaps no
block and no placed label, else where it overlaps least; a label above its curve grows upward, one below a loop downward. The gap
between layers widens to fit three quarters of the shown labels, up to 360 px.

### Layout

A small layered layout in the page (no library): cycles are broken by reversing the
narrower edge of each two-way pair (a stream's `ready` against its data), then DFS
back edges with wide edges explored first; a `Feedback` edge is laid out forward
unless its end already reaches its start (a value used before it is assigned need
not flow backwards). Layers are longest paths, with inputs, register current values
and wire reads forced first and outputs, register next values and wire writes last.
A forward edge that skips layers gets a place of its own (6 px high) in each layer it
crosses, ordered and placed with the blocks, and is drawn through those places, so
no block sits on its way. Eight barycenter sweeps order each
layer, alternately by its blocks' neighbors in all earlier layers and in all later
ones, a neighbor's position taken relative to its layer's size, so an edge that
skips layers (an input feeding a late block) counts. The layers' widths fix the
drawing's width; the gap between a layer's blocks then grows from 18 px until the
tallest layer is 85 % of that width times the pane's height over its width, up to
180 px, so a wide, flat view spreads out over the pane's height (fitting it is still
bound by its width). Each layer starts as a centered column; eight sweeps, from the
left and from the right in turn, then move each block level with the mean middle of
its neighbors, as far as its layer's order and gap allow (`placeLayer`: least
squares, by pool-adjacent-violators isotonic regression); the places of skipping
edges move the same way. A resized window lays the view out again. Edges are Bézier
curves, straight through their places; reversed edges loop underneath. Wheel zooms,
dragging pans, **fit** fits everything drawn (`getBBox`).

### Hardware scale

The **hardware scale** toggle sizes blocks as `PipelineMap.write_png` did: width is
the callee's delay, height the mean of its input and output bus widths (a block
without port data, an operator or a group, takes its widest edge). When the function
has `offsets`, x is the block's start time on a ns axis (inputs left, outputs right);
otherwise the layered x positions stay. Edges are then plain curves: the places kept
for edges that skip layers no longer line up with the blocks. An operator group spans from its first
member's start to its last member's end, or, without offsets, is as wide as its
slowest member.

### Search, source links and Mermaid text

- The search box matches instance paths (MAIN/local/local…, display names) of every
  non-operator instance and goes to the match's own view, or to its parent's view
  with the block highlighted.
- The header's **source** link opens the current function's definition as
  `vscode://file/<path>:<line>`; Ctrl- or Cmd-clicking a block sets it to the call
  site and opens it. Generated sources have no link.
- **copy as Mermaid** writes the current view as `flowchart LR` text to the
  clipboard, or into a text box where a `file://` page may not use the clipboard: the
  blocks' lines (a group as a round node; a MAIN without its source location, which
  goes stale in a README), the edges with the labels the view shows
  (dashed through a `Feedback`, red between clocks by `linkStyle`), `"`, `<` and
  `>` as Mermaid's `#quot;`, `#lt;` and `#gt;`. Mermaid's layout (dagre) ranks a
  block next to what it connects to, which puts an input that feeds a late block, or
  an output of an early one, in the middle; so the view's first-layer nodes (inputs,
  register current values, wire reads) go in one subgraph and its last-layer nodes
  in another, both untitled and unstyled: dagre keeps a subgraph's span of ranks
  small, so each becomes one column, left of everything the inputs feed and right of
  everything feeding the outputs (checked in VS Code's Mermaid renderer). In a view
  with loops dagre can still rank an output right after the block feeding it, before
  blocks of later layers, so invisible links (`~~~`) run from each block of the
  page's last middle layer to the first output, after the real edges (which keeps
  the `linkStyle` indices).

### Self-test

`#selftest` resets the filters to their defaults and nothing hidden (it reads and
writes no browser storage), checks that `layout` spreads a three-block layer
further apart for a square pane than for none, runs an edge that skips a layer
through a place clear of the block in that layer, lays a `Feedback` edge that
closes no cycle out forward, lists array elements as index runs, and puts the fields
of one variable on one name-label line, then draws:

- the design view, checking that no wiring MAIN and no feedback data is drawn,
  every edge's label is, a pin group holds more than one pin and none of its pins is drawn
  on its own, and there is no file banner; that the top file's link opens it; and
  every file view, checking each has its banner;
- each function with a graph three times: with the defaults, checking that no
  operator (a call with `op` included), wiring call site, register, constant or clock
  enable is drawn, every edge's label is, no returned struct is drawn as one output, no port
  or wire stub is feedback and, in a view with forward interfaces both ways, none is
  plain, no drawn edge passes a `Feedback` whose type is `fb` or carries feedback
  data, every logic block drawn has a drawn output, every edge ends at drawn nodes,
  and operators and registers joined by a remaining edge, directly or through
  wiring, share a group, as do a register's two values; with everything shown
  and wire labels on, checking that every graph node (a returned struct as its
  fields) is drawn, every wire has a name and every edge's label is drawn; and with
  everything hidden (pass where a kind has it, drop otherwise), checking that only
  non-operator, non-wiring call sites and no `Feedback` edges are drawn. The checks
  classify nodes from the data, not with the filters' own code;
- the hardware-scale view of each function with `offsets`;
- the design view with one MAIN hidden by hand through `setHidden`, as its menu
  does, pass and drop, checking it is not drawn and is drawn again once shown; a
  filter changed through `filtersChanged`, as the panel does; one edge's label hidden
  through `setLabel`, as its menu does, checking it alone is not drawn and has no
  label in the Mermaid text, then shown again, checking nothing stays set; an edge hovered,
  checking it alone is lit, and a block hovered, checking its edges are; the Mermaid
  text's inputs and outputs subgraphs, present exactly when the view has
  first-layer and last-layer nodes, and its invisible links to the outputs, present
  exactly when it has outputs and blocks before them; and, each checked to draw
  without an error, the
  hidden list, a node's and an edge's menu, the filters panel and a search.

It sets `data-ready="<views drawn>"` on `<body>`, or `data-error` with the failed
check or exception, and records what each default view drew (blocks, wire names,
edges by their ends' first lines, their label lines) in a `<script id="drawn">`
JSON element, so the
render test can check what a particular design's views show.

## 6. Sharing the page

`diagram.html` needs nothing else from the output directory: the data and the
viewer are inside it, and it loads nothing from the network. It holds the build
machine's absolute file paths (tooltips, file names, the source links) and every
function, wire and type name of the design. The `vscode://` source links open only
where the same paths exist.

## 7. Limits

- Wire pass-through of a hidden wiring MAIN and C links are whole-wire: a struct
  wire split into several output pins inside an `@wires` MAIN reaches each of them
  (a pin group's edge names the shared part instead of every pair).
- Variable names come from `variable_names`; a generated interface function's names
  show as they are (`rev3_if0df2bd50`).
- Field positions follow constant field selects and assemblies only: after a
  function on the way (a cast, an `@wires` function, a register passed through) a
  wire is named by what it was before it, and a variable index select ends nothing.
- A call is drawn as an operator when an operator was dispatched to its callee
  anywhere in the parse (`pypeline_operator_impl_ops` is per callee), so a direct
  call to the same specialization is drawn as one too.
- The Mermaid text's columns hold only for its first and last layers; dagre places
  the blocks between them by its own ranking and cycle breaking, which can differ
  from the page's.
- Type names that stay alike after factory arguments (the same class with arguments
  of the same name) are told apart only by their widths and tooltips.
- A function used at several instances has one graph; latencies are per instance,
  and hiding one of its nodes by hand hides it in every instance.
- `offsets` compose the callees' own delays, so a function synthesized as a whole can
  be faster than its time axis: on sky130 (DEVICE_MODELS), `built_hardware_core_design`'s
  `divide_body` measures 57.2 ns while its soft divider's composed delay is 244.5 ns.
- An operator group in a function instance with latency is marked `in L=n`
  without saying whether or where registers fall among its operators.
- Reversed edges (back edges, a cycle's `Feedback`) loop underneath without places
  of their own and can cross blocks.

## 8. Tests

| Test | Category | What |
|---|---|---|
| `inst/diagram_test.py` | elab_introspect | the data of four Pypeline designs and one C example, parsed in-process: files, clocks, links and their roles, graphs, edge names, `Feedback` edges and their types, type roles, names and fields (an interface wire's feedback fields), field selects and assemblies, operators dispatched to calls, a generated function's source function, wire stubs' roles and driven fields, wiring call sites, call-site kinds |
| `inst/diagram_build_test.py` | build_report_device_models | a sky130 build's latencies against `built_hardware.json`, delays and offsets, the pipelined divider's operator latencies, a `--no_synth` build, a failed build removing the page |
| `inst/diagram_render_test.py` | unit (needs `google-chrome`) | the [self-test](#self-test) of four designs' pages in headless Chrome, and what `diagram_interfaces_design.py`'s default views draw: a returned struct's outputs, wire names, sideband and feedback ports and data left out, an operator's call in a logic block, a global wire write taking only its fields, a label with one variable's fields on one line, packed pins as one port |

`inst/diagram_interfaces_design.py` is the fixture for interface roles, type names
(named and unnamed stream types), `Feedback` edges of both roles, wiring call sites,
sideband ports, returned structs (and two fields of one passed to a call), a soft comparison, a
`Wire` of an interface with `ready` flowing back, a plain struct `Wire` written
field by field from two MAINs,
and pins an I/O `@wires` MAIN packs into stream wires. See
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

**The defaults draw what a person draws.** A block's default view is meant to sit
beside a description of the block, so it shows what such a diagram does: the
forward interface data between the blocks of one level of the code's hierarchy
(no level skipped or merged), named as the code names it. Feedback data (`ready`)
is left implicit, as in a hand-drawn data path, unless it travels in a forward type;
sideband ports beside forward interfaces (an `aad_len`) are left out; a returned
struct is the several outputs it stands for; operators and registers make up logic
blocks, and logic that feeds nothing drawn goes with what it feeds; a compiler's
implementation of an operator is the operator; pins packed into one wire are the one
port they form. Every filter can bring the rest back.

**Wire labels show names by default.** Labels were off by default while they said
little a reader would write: a bundle's `N wires`, a wire with no variable labeled
with its type alone, then a type after every name. Once wires are named as the code
names them, by their field selects and by both ends, a label is what a hand-drawn
diagram writes on the line, so labels are on, with names only (types in the
tooltip), the fields of one variable on one line, and still every wire listed.
