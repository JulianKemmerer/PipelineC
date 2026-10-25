"""In-process checks of async global FIFOs: a Fifo[T] whose ends are used on
two clocks. Each design is written to a temp .py file and parsed with
PY_TO_LOGIC.PARSE_FILE, then checked against the parser state, the raised
ElaborationError, or the written crossing report.

- Realization: the crossing <key>_FIFO is a ClkCrossVarInfo with flow
  control, its two side MAINs and their clocks, and a global var T[depth]
  (n rounded up to a power of two, at least 4); its stubs <key>_FIFO_WRITE_1
  and <key>_FIFO_READ_1 are tagged as the crossing's functions and protected
  emission names; the side MAINs <key>_FIFO_wr / _rd run on the write and
  read clocks and take no added latency; the FIFO wire is checked leaf by
  leaf; impl="builtin" reaches async_impl.
- Kind errors: global_async_fifo on one clock, a module initializer across
  two clocks, and a name the back end would cut at "_READ".
- The crossing report lists ASYNC wires and both FIFO kinds, with the
  built-in async FIFO's hardware and depth.
"""

import json
import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC
import SYN

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
from pypeline import *
from stream.stream_fifo import make_stream_fifo

eth_clk = make_clock(125.0, name="eth_rx")
"""

_ENDS = """
@MAIN(eth_clk)
def producer():
    n: Reg[uint8_t]
    rx.wr.stream.data = n
    rx.wr.stream.valid = 1
    if rx.wr.ready:
        n += 1

@MAIN(100.0)
def consumer():
    total: Reg[uint8_t]
    rx.rd.ready = 1
    if rx.rd.stream.valid:
        total += rx.rd.stream.data
"""


def _parse(src, name):
    with tempfile.TemporaryDirectory(prefix="async_fifo_elab_test_") as tmpdir:
        path = os.path.join(tmpdir, name)
        with open(path, "w") as f:
            f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)))
            f.write(src)
        return PY_TO_LOGIC.PARSE_FILE(path)


def _expect_error(src, name, must_contain):
    try:
        _parse(src, name)
    except PY_TO_LOGIC.ElaborationError as e:
        msg = str(e)
        for token in must_contain:
            assert token in msg, f"{name}: expected {token!r} in the error, got: {msg}"
        print(f"{name} PASS  ({msg})")
        return
    raise AssertionError(f"{name}: expected an ElaborationError, PARSE_FILE succeeded")


def test_realization():
    state = _parse("\nrx: Fifo[uint8_t] = global_fifo(10)\n" + _ENDS, "realization_test.py")
    info = state.clk_cross_var_info["rx_FIFO"]
    assert info.flow_control and info.write_read_sizes == (1, 1)
    assert info.write_read_funcs == ("rx_FIFO_WRITE_1", "rx_FIFO_READ_1")
    assert info.write_read_main_funcs == ({"rx_FIFO_wr"}, {"rx_FIFO_rd"})
    assert info.async_impl is None
    assert state.global_vars["rx_FIFO"].type_name == "uint8_t[16]", state.global_vars["rx_FIFO"].type_name
    assert (state.main_mhz["rx_FIFO_wr"], state.main_clk_group["rx_FIFO_wr"]) == (125.0, "eth_rx")
    assert (state.main_mhz["rx_FIFO_rd"], state.main_clk_group["rx_FIFO_rd"]) == (100.0, None)
    assert "rx_FIFO" not in state.main_mhz
    table = state.FuncLogicLookupTable
    for stub in ("rx_FIFO_WRITE_1", "rx_FIFO_READ_1"):
        assert table[stub].is_clock_crossing and table[stub].uses_nonvolatile_state_regs
        assert stub in state.pypeline_emission_names.protected
    for side in ("rx_FIFO_wr", "rx_FIFO_rd"):
        assert state.func_no_added_latency[side] == "global FIFO", state.func_no_added_latency
    decl = state.pypeline_global_insts["rx"]
    assert decl.crossing == "rx_FIFO" and decl.main_names == ["rx_FIFO_wr", "rx_FIFO_rd"]
    assert "rx" in state.wire_clocks_checked
    print("test_realization PASS")


def test_builtin_impl_and_depth():
    state = _parse(
        "\nrx: Fifo[uint8_t] = global_async_fifo(3, impl='builtin')\n" + _ENDS,
        "builtin_test.py",
    )
    assert state.clk_cross_var_info["rx_FIFO"].async_impl == "builtin"
    assert state.global_vars["rx_FIFO"].type_name == "uint8_t[4]"
    print("test_builtin_impl_and_depth PASS")


def test_kind_errors():
    _expect_error(
        "\nrx: Fifo[uint8_t] = global_async_fifo(8)\n"
        + _ENDS.replace("@MAIN(eth_clk)", "@MAIN(100.0)"),
        "async_one_clock_test.py",
        ["global FIFO rx", "global_async_fifo says its ends are on two clocks", "clk_100p0"],
    )
    _expect_error(
        "\nrx: Fifo[uint8_t] = make_stream_fifo(uint8_t, 8)\n" + _ENDS,
        "module_two_clocks_test.py",
        ["global FIFO rx", "single-clock module, which cannot cross clocks", "global_async_fifo(n)"],
    )
    _expect_error(
        "\nrx_READ: Fifo[uint8_t] = global_fifo(8)\n" + _ENDS.replace("rx.", "rx_READ."),
        "read_name_test.py",
        ["may not contain '_READ'", "Rename it"],
    )


def test_report_rows():
    src = (
        """
rx: Fifo[uint8_t] = global_fifo(8)
cmds: Fifo[uint8_t] = global_sync_fifo(2)
link_up: Wire[uint1_t, ASYNC]
"""
        + _ENDS.replace("    rx.wr.stream.valid = 1\n", "    rx.wr.stream.valid = 1\n    link_up = 1\n")
        + """
@MAIN(100.0)
def fwd():
    cmds.wr.stream.data = 3
    cmds.wr.stream.valid = link_up
    cmds.rd.ready = 1
"""
    )
    state = _parse(src, "report_test.py")
    rows = [(r.name, r.kind, r.write_clock, r.read_clock) for r in state.pypeline_clock_crossings]
    assert rows == [
        ("rx", "global_fifo", (125.0, "eth_rx"), (100.0, None)),
        ("cmds", "global_sync_fifo", (100.0, None), (100.0, None)),
        ("link_up", "ASYNC wire", (125.0, "eth_rx"), (100.0, None)),
    ], rows
    saved = SYN.SYN_TOOL
    try:
        SYN.SYN_TOOL = None
        with tempfile.TemporaryDirectory(prefix="async_fifo_elab_report_") as out_dir:
            PY_TO_LOGIC.WRITE_CLOCK_CROSSING_REPORT(state, out_dir)
            text = open(os.path.join(out_dir, "clock_crossings.log")).read()
            records = json.load(open(os.path.join(out_dir, "clock_crossings.json")))
    finally:
        SYN.SYN_TOOL = saved
    header = text.splitlines()[0].split()
    assert header == ["crossing", "clocks", "kind", "hardware", "depth", "source"], text
    assert "eth_clk -> clk_100p0" in text and "built-in async" in text, text
    by_name = {r["crossing"]: r for r in records}
    assert by_name["rx"]["hardware"] == "built-in async" and by_name["rx"]["depth"] == 8
    assert by_name["rx"]["write_clock"] == "clk_125p0_eth_rx", by_name["rx"]
    assert by_name["cmds"]["hardware"] == "make_stream_fifo" and by_name["cmds"]["depth"] == 2
    assert by_name["link_up"]["hardware"] == "none" and by_name["link_up"]["source"] == "report_test.py:11"
    print("test_report_rows PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
