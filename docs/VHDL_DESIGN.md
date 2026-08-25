# VHDL entity and pipeline lowering

`src/VHDL.py` turns the elaborated `Logic` graph plus its final
`TimingParamsLookupTable` into packages, entities, architectures, and the
top-level design. It does not decide how many pipeline stages are desirable;
the throughput sweep does that first. It is responsible for making every
chosen placement into cycle-correct VHDL.

See [`RAW_VHDL_DESIGN.md`](RAW_VHDL_DESIGN.md) for built-in leaf operators,
[`SYN_DESIGN.md`](SYN_DESIGN.md) for placement and timing feedback, and
[`DEVICE_MODELS_DESIGN.md`](DEVICE_MODELS_DESIGN.md) for sky130 mapping and
STA.

## Artifact layers

A normal build emits:

- `c_structs_pkg.pkg.vhd`, which declares translated structs, arrays, enums,
  and helper conversions;
- `global_wires_pkg.pkg.vhd`, which declares the records connecting MAINs and
  global wires;
- built-in support entities such as FIFO implementations when referenced;
- one or more generated entities for each distinct logic/timing shape;
- a final `top/top.vhd`; and
- `vhdl_files.txt`, the exact dependency-ordered file list for the final
  artifact.

Downstream simulation and synthesis should consume `vhdl_files.txt`, not a
directory glob. Intermediate sweep candidates can coexist in the output
tree, and a glob can silently combine entities from different timing shapes.

## Entity identity and reuse

`WRITE_LOGIC_ENTITY` renders one implementation and
`GET_ENTITY_NAME` names the timing-specific shape. Generated combinational
entities use names of the form `func_<latency>CLK_<hash>`. The hash includes
the timing structure that affects rendered content: local slices, exact
integer bit-boundary groups, I/O registers, and referenced child entity
identities. Identical shapes are
reused; different placements cannot alias merely because their total latency
matches.

Sweep-time top entities are likewise hashed so cached synthesis artifacts are
tied to one design shape. `WRITE_MULTIMAIN_TOP(..., is_final_top=True)` emits
the stable public `top` entity after the final timing table is selected.
`CHECK_VHDL_FILES_CONSISTENCY` checks that every referenced generated entity
has a definition in the final file list.

Pipeline-map graph frontiers and shared-global emission are sorted before
rendering. Source-coordinate fragments in generated `_DUPLICATE_<hash>` names
(from `C_TO_LOGIC.py`'s duplicate-submodule-collapsing pass) are sorted the
same way: the pass collects one `ASTMeta` per collapsed source location into a
set, and `ASTMeta.__hash__` is a `PYTHONHASHSEED`-salted string hash, so
iterating that set directly used to make the same design spell the fragment
`_py_l35_l34_` in one process and `_py_l34_l35_` in another -- same entity
hash, different VHDL bytes, an intermittent miss on a byte-hash synthesis
cache. The coordinates are now sorted by `(src_file, line, col, end_col)`
before rendering, not by the string each `ASTMeta` hashes on, which for the C
frontend embeds a per-process memory address and would not be stable across
processes. Regression-tested by `duplicate_collapse_naming_test.py`, which
pins two `PYTHONHASHSEED` values confirmed to disagree pre-fix.

## Building a pipelined architecture

For hierarchical logic, `GET_PIPELINE_MAP` assigns each wire and submodule
connection to a stage from data dependencies and child latencies.
`GET_PIPELINE_ARCH_DECL_TEXT` declares stage records/signals, while
`GET_PIPELINE_LOGIC_COMB_PROCESS_TEXT` and the clocked portions of the
architecture implement the stage-to-stage transfers. Names containing
`REG_STAGE<n>` are rendered alignment/storage wires, not evidence that each
source-level variable owns an independent physical delay chain; synthesis may
merge equivalent registers.

`io_registers_r` (the record holding a clocked function's input/output register
banks) and `REG_STAGE<n>_<wire>` are deliberately GENERIC signal names -- they
carry no reference to source location or the variable's Python name, unlike the
generated entity/instance names elsewhere in this build (see
[PY_TO_LOGIC_DESIGN.md](PY_TO_LOGIC_DESIGN.md)'s "Canonical function name
format"). This is intentional, not an oversight: `SWEEP.py`'s critical-path
attribution parses `stage(\d+)` back out of a register name
(`_PATH_REPORT_STAGE_INFO`) to report local pipeline-stage info, and a Vivado/
yosys timing report cross-references these exact strings, so renaming them would
require updating both. To find the source construct a specific `io_registers_r`/
`REG_STAGE<n>` field belongs to, read the ENCLOSING hierarchical instance path
instead -- that path segment does carry a `_py_lNN` location suffix, and
`name_index.log` (see [SYN_DESIGN.md](SYN_DESIGN.md)) decodes it further.

Reconvergent branches and bypass inputs are aligned to the stage at which
their consumer runs. An operation-output placement creates a register at that
instance boundary; values which remain live across it are delayed through the
same pipeline map. A genuine bit-internal placement delegates the split to
the raw leaf generator. Exact placements carry their integer boundary group
through `TimingParams`; every built-in MUX can therefore render a different
packed output bit chunk in each local stage while the pipeline map aligns its
condition, data inputs, and partial output. Integer/signed/vector MUXes select
their native vectors directly. Composite MUXes use the generated
`<type>_to_slv` functions at stage 0 and `slv_to_<type>` after the final
chunk, so structs, arrays, enums, floats, and nested combinations use the same
canonical packed layout as all other VHDL connections. These cases remain
distinct through lowering, so an output boundary does not get recursively
pushed into every descendant.

The SLV alternatives and partial result are fields of the raw leaf's pipeline
record. They consequently participate in the same register transfer and live
wire alignment as native typed values. Slice coordinates, exact packed-bit
boundaries, and the composite type all remain part of entity hashing; two
typed entities may share a width-keyed timing-cache result without becoming
the same VHDL entity or losing their type-specific conversion functions.

`TimingParams._has_input_regs` and `_has_output_regs` implement independent
entity-boundary registers. They participate in latency, hashing,
clock/clock-enable requirements, and wire alignment just like internal
stages. The sweep may therefore put a shared direct connection's register on
the producer output *or* the consumer input; it must not render both merely
because adjacent helper instances were independently mini-swept. PipelineMap
still aligns every other input and bypass at the selected consumer stage. A
design with `N` serial register slices has `N + 1` combinational pipeline
stages. The fresh WireGuard shared build validates this lowering on ten
serial `chacha20_block_step` instances: one internal slice per helper plus
nine producer-output banks rendered as 19 slices / 20 stages, with no
redundant output-to-input register pairs.

## Type conversion on a mismatched connection

`TYPE_RESOLVE_ASSIGNMENT_RHS` wraps the RHS expression whenever a connection's
two wires carry different C types — an ordinary assignment across a width/
signedness change, and (Pypeline only) a scalar `T(x)` cast, which lowers to
the identical connection (see `pypeline_DESIGN.md`/`PY_TO_LOGIC_DESIGN.md`'s
Casting sections). Every quadrant (same-signedness resize; unsigned driving
signed; signed driving unsigned, either direction) is meant to match C's
conversion rule: take the low `Wd` bits of the source's two's-complement
representation and reinterpret per the destination's signedness. Signed→
signed narrowing did not — `numeric_std.resize` on a `SIGNED` value is
sign-preserving (keeps the sign bit, not the low bit), not C's rule — fixed
by routing that one case through `unsigned` first, the same shape already
used for signed→unsigned narrowing. `nested_truncate_test.py` is the
regression, confirmed against real GHDL.

## Flat code and hierarchy

Pypeline and C source functions are elaboration boundaries, not mandatory
pipeline boundaries. A completely flat function still contains operation
instances and driver/consumer relationships, so output boundaries and legal
bit-internal splits can be scheduled without the user first refactoring the
source into one-helper-per-stage form. Conversely, preserving a helper does
not force a register on its boundary unless timing/placement selects it or the
interface explicitly requests an I/O register.

Hierarchy remains relevant for entity reuse, readable generated output, and
coherent-boundary tie-breaking. Correctness must not depend on whether an
equivalent dataflow was written flat or split among helper functions.

## Top-level clocks and records

The multimain writer constructs the clock ports required by the selected
MAIN frequencies, instantiates each MAIN, and connects global-wire records.
Pypeline stream interfaces commonly appear at the final top as record ports
(`input.data`, `input.valid`, `output.data`, `output.valid`) plus explicit
ready signals. A stream type's generated hash is intentionally not a stable
API; testbenches should discover types from `c_structs_pkg` or bind through a
small wrapper with scalar ports.

PipelineC does not synthesize an output-ready port where the source interface
has none. Verification for such an interface can cover continuous-valid
traffic, input bubbles, ordering, latency, and flush, but must not claim
output-backpressure coverage.

## Raw/manual VHDL and fixed boundaries

User `vhdl(...)` passthrough and other VHDL-text modules are opaque to normal
interior slicing. Their declared/fixed latency and boundary behavior must be
honored by the surrounding pipeline map. Clock crossings, memories, stateful
logic, and black boxes similarly form atomic or fixed-latency regions unless
their own implementation explicitly exposes a legal pipeline structure.

## Synthesis boundary and verification

The VHDL writer is intentionally independent of the Yosys/ABC recipe. A
recipe comparison is valid only when the `vhdl_files.txt` contents and every
listed file hash are byte-identical; recipe-specific artifacts and caches are
documented in `DEVICE_MODELS_DESIGN.md`.

The opt-in Divider QoR harness in
`src/tests/pypeline_tests/divider_qor_bench.py` copies the dependency-ordered
final files into an immutable evidence snapshot, compiles that snapshot with
GHDL, and remaps the same bytes for the accepted STA and cell result. This
prevents a restored best sweep snapshot from being paired with the mapped
netlist of a later failed probe. Its testbench checks continuous traffic,
bubbles, divide-by-zero, ordering, valid latency, pipeline flush, and an
always-ready input. Fast unit/elaboration tests cover entity hashing,
dependency lists, I/O registers, fork/join and bypass alignment, and
flat-versus-hierarchical placement; full sky130 runs remain opt-in.

The accepted gate artifact exercises this association end to end: the generic
planner's 31-slice / 32-stage VHDL snapshot passes 141 ordered vectors at
31-cycle latency, and mapping those same bytes produces 160.43 MHz with zero
unmapped cells. The arithmetic fixture independently passes at 32 slices /
33 stages and 180.05 MHz despite having no stage-sized helper function. Exact
hashes are recorded in
[`divider_qor_acceptance.json`](../src/tests/pypeline_tests/qor/divider_qor_acceptance.json).

The arithmetic continuity benchmark independently freezes and verifies the
model-V4 artifacts returned by normal sweeps. At 180 MHz, the first 49-stage
shape measured 164.69 MHz; the bounded chunked-MUX neighbor then produced 49
slices / 50 stages, passed all 141 vectors at 49-cycle latency, and remapped
to 194.22 MHz from the same VHDL bytes. Its machine-readable evidence lives
under the benchmark's caller-selected output directory rather than in the
normal test suite.

`divider_struct_mux_bench.py` applies the same immutable-byte check after
wrapping the Divider's loop-carried 32-bit values in a struct. The emitted
composite-MUX VHDL compiles and simulates all 141 vectors, and the exact
49-slice snapshot remaps to 194.2227 MHz. This specifically exercises the
stage-0 pack, two stage-local SLV selections, final unpack, and ordinary
pipeline-map alignment rather than merely testing the scalar MUX path again.
