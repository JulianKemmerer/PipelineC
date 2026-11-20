"""In-process checks of ParserState.global_wire_access, the table of who writes
and reads each global wire (LOGIC.BUILD_GLOBAL_WIRE_ACCESS): each design below
is written to a temp .py file and parsed with PY_TO_LOGIC.PARSE_FILE, or a C
example is parsed with C_TO_LOGIC.PARSE_FILE, then the table is checked.

- Split wire: two writers of disjoint fields, one of them a helper one call deep
  below its MAIN, a writer that reads a leaf it does not drive back, a reader
  helper with two instances under two MAINs, an Input pin and an Output.
- Variable-index writes: a writer with a constant-field write and a variable
  array-index write keeps the index's constant prefix in write_paths().
- A global FIFO's MAIN, added after clock assignment, is in the table.
- The table agrees with the per-function records it is built from, for every
  design here (the function set the front-end checks used to scan, the whole
  Logic table, is the table's).
- C: whole-wire uses, a global state register is a writer, and every use has
  instances.
- The top level's connections (VHDL.GLOBAL_WIRE_CONNECTIONS, planned from the
  table): a split wire is fed region by region from each owner, readers in
  sorted order, a writer's readback input zero in its own regions and the
  owner's value in the others, an Output and an Input pin; an unshared wire's
  readback input is fed zero; the package is written for a readback alone.
"""

import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import LOGIC
import PY_TO_LOGIC
import VHDL

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
from pypeline import *

"""

# Compound types and wires the Pypeline cases below share
_SPLIT_DESIGN = """
@struct
class point_t(NamedTuple):
    x: uint8_t
    y: uint8_t

@struct
class mixed_t(NamedTuple):
    flag: uint8_t
    vals: uint8_t[4]

w: Wire[point_t]  # .x by wx, .y by y_helper (below wy), .y read back by wx
m: Wire[mixed_t]  # one writer: a constant field and a variable-index write
pin: Input[uint8_t]
pout: Output[uint8_t]
pout2: Output[uint8_t]

@hw_func
def y_helper(n: uint8_t) -> uint8_t:
    w.y = n
    return n

@hw_func
def peek() -> uint8_t:
    return w.x + w.y

@MAIN
def wx():
    n: Reg[uint8_t]
    w.x = n + w.y
    n += 1

@MAIN
def wy():
    n: Reg[uint8_t]
    y_helper(n)
    n += 1

@MAIN
def mw():
    n: Reg[uint8_t]
    idx: uint8_t = n & 3
    m.flag = n
    m.vals[idx] = n
    n += 1

@MAIN
def rd_a():
    pout = peek() + pin

@MAIN
def rd_b():
    pout2 = peek() + m.flag + m.vals[0]
"""

# One wire only its writer uses, which reads it back (issue #384's design)
_UNSHARED_DESIGN = """
priv: Wire[uint8_t]

@MAIN
def solo():
    n: Reg[uint8_t]
    seen: uint8_t = priv
    priv = n + seen
    n += 1
"""

_FIFO_DESIGN = """
rx: Fifo[uint8_t] = global_fifo(4)

@MAIN(100.0)
def producer():
    n: Reg[uint8_t]
    rx.wr.stream.data = n
    rx.wr.stream.valid = 1
    if rx.wr.ready:
        n += 1

@MAIN(100.0)
def consumer():
    rx.rd.ready = 1
    sink = rx.rd.stream.data
"""


def _parse(src, name):
    with tempfile.TemporaryDirectory(prefix="global_wire_access_test_") as tmpdir:
        path = os.path.join(tmpdir, name)
        with open(path, "w") as f:
            f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)))
            f.write(src)
        return PY_TO_LOGIC.PARSE_FILE(path)


def _record_pairs(state):
    """{(wire, func)} of the functions whose Logic records name a global wire."""
    pairs = set()
    for func, logic in state.FuncLogicLookupTable.items():
        for wire in state.global_vars:
            if (
                wire in logic.write_only_global_wires
                or wire in logic.read_only_global_wires
                or wire in logic.state_regs
                or wire in logic.readback_global_wires
                or wire in logic.global_wire_read_paths
                or wire in logic.global_wire_write_locs
            ):
                pairs.add((wire, func))
    return pairs


def _table_pairs(state):
    return {
        (wire, func)
        for wire, uses in state.global_wire_access.items()
        for func in uses
    }


def _funcs(state, wire):
    return sorted(state.global_wire_access[wire])


def test_split_wire_writers_and_readers():
    state = _parse(_SPLIT_DESIGN, "split_wire_test.py")
    uses = state.global_wire_access["w"]
    assert sorted(uses) == ["peek", "wx", "y_helper"], sorted(uses)

    wx = uses["wx"]
    assert wx.writes and not wx.reads, wx
    assert wx.driven == frozenset({("x",)}), wx.driven
    assert wx.readback == "w_PYPELINE_READBACK", wx.readback
    assert set(wx.write_locs) == {("x",)} and set(wx.read_paths) == {("y",)}, wx
    assert wx.mains == ("wx",) and wx.insts == ("wx",), (wx.mains, wx.insts)
    assert not wx.dynamic

    helper = uses["y_helper"]
    assert helper.writes and not helper.reads and helper.readback is None, helper
    assert helper.driven == frozenset({("y",)}), helper.driven
    assert helper.mains == ("wy",), helper.mains
    assert len(helper.insts) == 1 and helper.insts[0].startswith(
        "wy" + LOGIC.SUBMODULE_MARKER
    ), helper.insts

    peek = uses["peek"]
    assert peek.reads and not peek.writes and peek.readback is None, peek
    assert set(peek.read_paths) == {("x",), ("y",)}, peek.read_paths
    assert peek.mains == ("rd_a", "rd_b"), peek.mains
    assert len(peek.insts) == 2, peek.insts

    assert [u.func for u in LOGIC.GLOBAL_WIRE_WRITERS(state, "w")] == ["wx", "y_helper"]
    # A writer that reads its own wire back is not a reader of the wire itself
    assert [u.func for u in LOGIC.GLOBAL_WIRE_READERS(state, "w")] == ["peek"]
    print("test_split_wire_writers_and_readers PASS")


def test_pin_and_output():
    state = _parse(_SPLIT_DESIGN, "pin_output_test.py")
    assert LOGIC.GLOBAL_WIRE_WRITERS(state, "pin") == []
    pin = state.global_wire_access["pin"]
    assert sorted(pin) == ["rd_a"] and pin["rd_a"].reads, pin
    assert set(pin["rd_a"].read_paths) == {()}, pin["rd_a"].read_paths
    out = state.global_wire_access["pout"]
    assert [u.func for u in LOGIC.GLOBAL_WIRE_WRITERS(state, "pout")] == ["rd_a"]
    assert out["rd_a"].write_paths() == {()}, out["rd_a"].write_paths()
    print("test_pin_and_output PASS")


def test_variable_index_write_keeps_its_prefix():
    state = _parse(_SPLIT_DESIGN, "variable_index_test.py")
    mw = state.global_wire_access["m"]["mw"]
    assert mw.dynamic, mw
    assert mw.driven == frozenset({("flag",)}), mw.driven
    # The index's constant prefix is a path the function writes, though no
    # leaf of it is a driven region
    assert mw.write_paths() == {("flag",), ("vals",)}, mw.write_paths()
    readers = {u.func for u in LOGIC.GLOBAL_WIRE_READERS(state, "m")}
    assert readers == {"rd_b"}, readers
    print("test_variable_index_write_keeps_its_prefix PASS")


def test_global_fifo_main_is_in_the_table():
    state = _parse(_FIFO_DESIGN, "fifo_access_test.py")
    uses = state.global_wire_access["rx"]
    fifo_mains = {u.func for u in uses.values() if u.func.endswith("_FIFO")}
    assert fifo_mains == {"rx_FIFO"}, sorted(uses)
    assert {"producer", "consumer"} <= set(uses), sorted(uses)
    assert uses["rx_FIFO"].mains == ("rx_FIFO",), uses["rx_FIFO"].mains
    print("test_global_fifo_main_is_in_the_table PASS")


def test_table_agrees_with_the_function_records():
    for name, src in (
        ("agree_split_test.py", _SPLIT_DESIGN),
        ("agree_fifo_test.py", _FIFO_DESIGN),
    ):
        state = _parse(src, name)
        records, table = _record_pairs(state), _table_pairs(state)
        assert records == table, (name, sorted(records ^ table))
    print("test_table_agrees_with_the_function_records PASS")


def test_c_design_uses_whole_wires():
    import C_TO_LOGIC
    import SYN

    example = os.path.join(REPO_ROOT, "..", "examples", "shared_globals.c")
    C_TO_LOGIC.MULT_STYLE = C_TO_LOGIC.MULT_STYLE_INFERRED  # the driver's --mult default
    with tempfile.TemporaryDirectory(prefix="global_wire_access_c_") as tmpdir:
        SYN.SYN_OUTPUT_DIRECTORY = tmpdir
        state = C_TO_LOGIC.PARSE_FILE(example)
    assert state.global_wire_access, "the C design has shared globals"
    for wire, uses in state.global_wire_access.items():
        writers = [u for u in uses.values() if u.writes]
        assert len(writers) == 1, (wire, sorted(uses))
        for use in uses.values():
            assert use.insts, (wire, use.func)
            assert use.driven == frozenset() and use.readback is None, use
        assert writers[0].write_paths() == {()}, (wire, writers[0])
    print("test_c_design_uses_whole_wires PASS")


def test_connection_plan_of_a_split_wire():
    state = _parse(_SPLIT_DESIGN, "connection_plan_test.py")
    connections, unshared = VHDL.GLOBAL_WIRE_CONNECTIONS(state)
    assert unshared == [], unshared
    assert [c.wire for c in connections] == ["m", "pin", "pout", "pout2", "w"]
    by_wire = {c.wire: c for c in connections}

    def pairs(wire):
        return [
            (a.target, a.source, a.c_type) for a in by_wire[wire].assignments
        ]

    # One writer, one reader: the whole wire; a pin drives its reader; an Output
    # port is driven by its writer
    assert pairs("m") == [
        ("global_to_module.rd_b.m", "module_to_global.mw.m", "mixed_t_flag_uint8_t_vals_uint8_t_4")
    ], pairs("m")
    assert pairs("pin") == [("global_to_module.rd_a.pin", "pin", "uint8_t")]
    assert pairs("pout") == [("pout", "module_to_global.rd_a.pout", "uint8_t")]

    # Split wire: readers' instances sorted (peek's two instances), each field
    # sourced from its owner's instance; the readback input of wx is zero in
    # wx's own field and wy's value in the other
    w = by_wire["w"]
    assert list(w.insts) == sorted(w.insts), w.insts
    targets = [a.target for a in w.assignments]
    reads = [t for t in targets if ".peek_" in t]
    assert reads == sorted(reads) and len(reads) == 4, reads
    by_target = {a.target: a for a in w.assignments}
    for target in reads:
        a = by_target[target]
        if target.endswith(".w.x"):
            assert a.source == "module_to_global.wx.w.x", a
        else:
            assert target.endswith(".w.y"), target
            assert a.source.startswith("module_to_global.wy.y_helper_"), a
            assert a.source.endswith(".w.y"), a
    rb_x = by_target["global_to_module.wx.w_PYPELINE_READBACK.x"]
    rb_y = by_target["global_to_module.wx.w_PYPELINE_READBACK.y"]
    assert rb_x.source is None and rb_x.c_type == "uint8_t", rb_x
    assert rb_y.source.startswith("module_to_global.wy.y_helper_"), rb_y
    assert targets[-2:] == [rb_x.target, rb_y.target], targets
    print("test_connection_plan_of_a_split_wire PASS")


def test_unshared_readback_is_fed_zero():
    state = _parse(_UNSHARED_DESIGN, "unshared_readback_test.py")
    connections, unshared = VHDL.GLOBAL_WIRE_CONNECTIONS(state)
    assert connections == [], connections
    assert [(a.target, a.source, a.c_type) for a in unshared] == [
        ("global_to_module.solo.priv_PYPELINE_READBACK", None, "uint8_t")
    ], unshared
    # Issue #384: nothing is shared, but the readback input is a
    # global_to_module record field, so the package that declares it is written
    assert not LOGIC.GLOBAL_VAR_IS_SHARED("priv", state)
    assert VHDL.NEEDS_GLOBAL_WIRES_VHDL_PACKAGE(state)
    print("test_unshared_readback_is_fed_zero PASS")


def test_package_is_not_written_for_a_design_without_records():
    state = _parse(
        """
@MAIN
def blink() -> uint8_t:
    n: Reg[uint8_t]
    n += 1
    return n
""",
        "no_records_test.py",
    )
    assert not state.global_vars and not VHDL.NEEDS_GLOBAL_WIRES_VHDL_PACKAGE(state)
    print("test_package_is_not_written_for_a_design_without_records PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
