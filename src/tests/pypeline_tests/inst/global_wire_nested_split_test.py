# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test for a compound Wire[T] split across THREE writer
functions at NESTED struct paths, criss-crossed so no writer owns a whole
top-level field of w:

    main_a drives w.a.x and w.b.y
    main_b drives w.a.y and w.b.x
    main_c drives w.tag

VHDL.py's BUILD_MULTI_WRITER_REGIONS must recurse into the nested structs and
emit one concurrent assignment per leaf region, each sourced from its owning
writer's module_to_global record. Native sim must reset only each function's
own claimed nested paths per invocation (runtime claim tracking) -- a
whole-wire reset would clobber the other writers' already-committed leaves
within one cycle's convergence loop.

w2 covers the mixed-depth case: main_a claims the ENTIRE w2.a subtree with a
single whole-field struct write, while main_b claims individual nested leaves
(w2.b.x) and a scalar field (w2.tag) -- regions at different depths of the
same type tree ((w2.b.y is claimed by nobody and must read zero).

Registered in native_sim_tests.py (--sim --comb --run all) and synth_tests.py
(--comb), so the per-region VHDL is also proven through real synthesis. NOT
in native_vs_vhdl_sim_tests.py: under --comb --sim --cocotb --ghdl this
design currently trips an elaboration error misidentifying an internal
soft-compare submodule as a second writer of `combined` -- see that file's
own comment.

`sim_assert`/`sim_finish` are simulation-only built-ins invisible to real
synthesis, so a design that only ever touches the split wires through them
has no observable output for PYRTL to keep -- the whole design (including the
per-region multi-writer wiring under test) optimizes away to nothing, which
manifests as a "ZeroDivisionError: float division by zero" in PyRTL's
max_freq (no real critical path exists once everything is trimmed). `combined`
below is a real `Output[T]` port driven by XOR-folding every leaf of w and w2
together -- an actual combinational function of the split-wire logic that
synthesis must keep, giving PYRTL a real critical path to time.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    NamedTuple,
    Output,
    Reg,
    Wire,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint8_t,
)


@struct
class point_t(NamedTuple):
    x: uint8_t
    y: uint8_t


@struct
class pair_t(NamedTuple):
    a: point_t
    b: point_t
    tag: uint8_t


w: Wire[pair_t]
w2: Wire[pair_t]
combined: Output[uint8_t]  # real synthesizable function of every split leaf

NUM_CHECKS = 10


@MAIN
def main_a():
    n: Reg[uint8_t]
    w.a.x = n
    w.b.y = n + 10
    # Whole-subtree claim on w2: one struct-typed write owns all of w2.a.
    # Assigning a struct VARIABLE (not a struct literal, which elaboration
    # decomposes into per-leaf writes) records the interior path ('a',) so the
    # top level emits a single whole-record region assignment for w2.a.
    p: point_t = point_t(x=n + 50, y=n + 60)
    w2.a = p
    n += 1


@MAIN
def main_b():
    n: Reg[uint8_t]
    w.a.y = n + 20
    w.b.x = n + 30
    w2.b.x = n + 70
    w2.tag = n + 80
    n += 1


@MAIN
def main_c():
    n: Reg[uint8_t]
    w.tag = n + 40
    # main_c is also a READER of a foreign nested leaf it does not drive
    # (w.a.x belongs to main_a) -- exercises the readback input on a wire
    # split across three writers.
    sim_assert(w.a.x == n, f"main_c reads foreign w.a.x expected {n} got {w.a.x}")
    n += 1


@MAIN
def checker():
    n: Reg[uint8_t]
    sim_assert(w.a.x == n, f"w.a.x expected {n} got {w.a.x}")
    sim_assert(w.b.y == n + 10, f"w.b.y expected {n + 10} got {w.b.y}")
    sim_assert(w.a.y == n + 20, f"w.a.y expected {n + 20} got {w.a.y}")
    sim_assert(w.b.x == n + 30, f"w.b.x expected {n + 30} got {w.b.x}")
    sim_assert(w.tag == n + 40, f"w.tag expected {n + 40} got {w.tag}")
    sim_assert(w2.a.x == n + 50, f"w2.a.x expected {n + 50} got {w2.a.x}")
    sim_assert(w2.a.y == n + 60, f"w2.a.y expected {n + 60} got {w2.a.y}")
    sim_assert(w2.b.x == n + 70, f"w2.b.x expected {n + 70} got {w2.b.x}")
    sim_assert(w2.b.y == 0, f"unclaimed w2.b.y expected 0 got {w2.b.y}")
    sim_assert(w2.tag == n + 80, f"w2.tag expected {n + 80} got {w2.tag}")
    # No debug print on the sim_finish() cycle -- see global_wire_partial_field_test.py.
    if n < NUM_CHECKS - 1:
        sim_print(
            f"global_wire_nested_split wax={w.a.x} wby={w.b.y} way={w.a.y} "
            f"wbx={w.b.x} wtag={w.tag} w2ax={w2.a.x} w2ay={w2.a.y} "
            f"w2bx={w2.b.x} w2tag={w2.tag}",
            debug=True,
        )
    if n == NUM_CHECKS - 1:
        sim_finish()
    n += 1


@MAIN
def combiner():
    # Real synthesizable logic reading every leaf of both split wires -- keeps
    # the whole multi-writer wiring under test from being optimized away.
    combined = (
        w.a.x
        ^ w.a.y
        ^ w.b.x
        ^ w.b.y
        ^ w.tag
        ^ w2.a.x
        ^ w2.a.y
        ^ w2.b.x
        ^ w2.b.y
        ^ w2.tag
    )
