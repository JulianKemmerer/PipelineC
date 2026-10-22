"""In-process checks of global instances (Inst[f]) and their errors: each
design below is written to a temp .py file and parsed with
PY_TO_LOGIC.PARSE_FILE, then checked against the parser state or the raised
ElaborationError (the pattern of global_fifo_elab_test.py).

Registration: the MAIN <key>_INST is a made @MAIN that clock inference gives
its users' rate through the wire (a bare user MAIN takes it too), a protected
emission name, and in func_no_added_latency; an unused instance stays bare; a
function that drives and reads one interface port is a handshake user; an
instance in an imported module gets a prefixed MAIN; an AUTO_PIPELINE call
site inside an instance MAIN is validated like any other. Errors: driving an
output, users on two rates, an initializer, Inst[f] inside a function,
AUTO_PIPELINE of a handshake user, and a function already named <key>_INST.
"""

import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
from pypeline import *
from stream.skid_buffer import make_skid_buffer

@hw_func
def add(a: uint8_t, b: uint8_t) -> uint8_t:
    return a + b

"""

# Drivers of adder's two inputs and a reader of its output; designs vary it
_USERS = """
@MAIN(100.0)
def drive_a():
    adder.a = 3

@MAIN
def drive_b():
    adder.b = 4

@MAIN
def reader():
    sink = adder.out
"""


def _parse(src, name, extra_files=None):
    with tempfile.TemporaryDirectory(prefix="global_inst_elab_test_") as tmpdir:
        for fname, text in (extra_files or {}).items():
            with open(os.path.join(tmpdir, fname), "w") as f:
                f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)) + text)
        path = os.path.join(tmpdir, name)
        with open(path, "w") as f:
            f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)))
            f.write(src)
        return PY_TO_LOGIC.PARSE_FILE(path)


def _expect_error(src, name, must_contain, extra_files=None):
    try:
        _parse(src, name, extra_files)
    except PY_TO_LOGIC.ElaborationError as e:
        msg = str(e)
        for token in must_contain:
            assert token.lower() in msg.lower(), (
                f"{name}: expected the error to mention {token!r}, got: {msg}"
            )
        print(f"{name} PASS  ({msg})")
        return
    raise AssertionError(f"{name}: expected an ElaborationError, PARSE_FILE succeeded")


def test_registration():
    state = _parse("\nadder: Inst[add]\n" + _USERS, "registration_test.py")
    # A bare MAIN, inferred through the wire from drive_a's rate; so are the
    # bare users, which take it through the instance like through a wire
    for main in ("adder_INST", "drive_b", "reader"):
        assert state.main_mhz[main] == 100.0, (main, state.main_mhz)
    assert state.main_syn_mhz["adder_INST"] == 100.0, state.main_syn_mhz
    assert state.main_clk_group["adder_INST"] is None
    assert "adder_INST" in state.pypeline_emission_names.protected
    assert state.func_no_added_latency["adder_INST"] == "global instance"
    decl = state.pypeline_global_insts["adder"]
    assert decl.joins_clocks and decl.main_name == "adder_INST", vars(decl)
    assert decl.describe() == "global instance adder [registration_test.py:12]"
    table = state.FuncLogicLookupTable
    # out is a VHDL reserved word: its record field and recorded path are out_v
    assert set(table["adder_INST"].global_wire_write_locs["adder"]) == {("out_v",)}
    assert set(table["adder_INST"].global_wire_read_paths["adder"]) == {
        ("a",),
        ("b",),
    }
    print("registration PASS")


def test_unused_instance_is_bare():
    src = """
lone: Inst[add]

@MAIN(100.0)
def elsewhere():
    unused: uint8_t = 1
"""
    state = _parse(src, "unused_test.py")
    assert state.main_mhz["lone_INST"] is None, state.main_mhz
    print("unused_instance_is_bare PASS")


def test_handshake_user():
    src = """
sb: Inst[make_skid_buffer(uint8_t)]

@MAIN
def producer():
    n: Reg[uint8_t]
    sb.stream_in_if.stream.data = n
    sb.stream_in_if.stream.valid = 1
    if sb.stream_in_if.ready:
        n += 1

@MAIN
def consumer():
    sb.stream_out_if.ready = 1
    sink = sb.stream_out_if.stream.data
"""
    state = _parse(src, "handshake_test.py")
    no_latency = state.func_no_added_latency
    assert no_latency["producer"] == "global instance handshake", no_latency
    assert no_latency["consumer"] == "global instance handshake", no_latency
    assert no_latency["sb_INST"] == "global instance", no_latency
    print("handshake_user PASS")


def test_imported_module_instance():
    sub = """
acc: Inst[add]

@MAIN
def acc_driver():
    acc.a = 5
    acc.b = 6
"""
    src = """
import inst_sub_design

@MAIN
def acc_reader():
    sink = inst_sub_design.acc.out
"""
    state = _parse(src, "imported_inst_test.py", {"inst_sub_design.py": sub})
    assert "inst_sub_design_acc_INST" in state.main_mhz, sorted(state.main_mhz)
    print("imported_module_instance PASS")


def test_auto_pipeline_inside_instance_is_validated():
    src = """
@hw_func
def counter(step: uint8_t) -> uint8_t:
    n: Reg[uint8_t]
    rv = n
    n += step
    return rv

piped: Inst[AUTO_PIPELINE(counter, latency=2)]

@MAIN
def driver():
    piped.step = 1
"""
    _expect_error(
        src,
        "validated_test.py",
        ["AUTO_PIPELINE(counter, latency=2)", "called in 'piped_INST'"],
    )


def test_driving_an_output():
    src = (
        "\nadder: Inst[add]\n"
        + _USERS
        + """
@MAIN
def meddler():
    adder.out = 1
"""
    )
    _expect_error(
        src,
        "drive_output_test.py",
        [
            "global instance adder",
            "'meddler' drives 'adder.out' (drive_output_test.py:28)",
            "the instance drives 'adder.out'",
            "'adder.a', 'adder.b'",
        ],
    )


def test_users_on_two_rates():
    src = "\nadder: Inst[add]\n" + _USERS.replace(
        "@MAIN\ndef reader", "@MAIN(50.0)\ndef reader"
    )
    _expect_error(
        src,
        "two_rates_test.py",
        ["global instance adder", "clk_100p0", "clk_50p0", "runs on one clock"],
    )


def test_initializer():
    src = "\nadder: Inst[add] = 3\n" + _USERS
    _expect_error(src, "initializer_test.py", ["'adder'", "takes no initializer"])


def test_inst_inside_function():
    src = (
        "\nadder: Inst[add]\n"
        + _USERS
        + """
@MAIN
def local_inst():
    q: Inst[add]
"""
    )
    _expect_error(src, "local_inst_test.py", ["Inst[add]", "global declaration", "local_inst"])


def test_auto_pipeline_of_handshake_user():
    src = """
sb: Inst[make_skid_buffer(uint8_t)]

@hw_func
def produce(x: uint8_t) -> uint1_t:
    sb.stream_in_if.stream.data = x
    sb.stream_in_if.stream.valid = 1
    return sb.stream_in_if.ready

AP = AUTO_PIPELINE(produce)

@MAIN
def producer():
    n: Reg[uint8_t]
    if AP(n):
        n += 1

@MAIN
def consumer():
    sb.stream_out_if.ready = 1
"""
    _expect_error(
        src,
        "auto_pipeline_handshake_test.py",
        ["AUTO_PIPELINE(produce)", "port 'sb.stream_in_if'", "make_stream_auto_pipeline"],
    )


def test_inst_main_name_collision():
    src = (
        "\nadder: Inst[add]\n"
        + _USERS
        + """
@hw_func
def adder_INST(x: uint8_t) -> uint8_t:
    return x
"""
    )
    _expect_error(src, "name_collision_test.py", ["'adder_INST'", "already uses"])


if __name__ == "__main__":
    test_registration()
    test_unused_instance_is_bare()
    test_handshake_user()
    test_imported_module_instance()
    test_auto_pipeline_inside_instance_is_validated()
    test_driving_an_output()
    test_users_on_two_rates()
    test_initializer()
    test_inst_inside_function()
    test_auto_pipeline_of_handshake_user()
    test_inst_main_name_collision()
    print("global_inst_elab_test: all PASS")
