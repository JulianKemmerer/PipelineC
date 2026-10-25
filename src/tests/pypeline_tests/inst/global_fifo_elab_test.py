"""In-process checks of global FIFO (Fifo[T]) realization and its errors:
each design below is written to a temp .py file and parsed with
PY_TO_LOGIC.PARSE_FILE, then checked against the parser state or the raised
ElaborationError (the pattern of global_wire_errors_test.py).

Realization: the FIFO MAIN <key>_FIFO is a MAIN on its ends' clock, a
protected emission name, and in func_no_added_latency, like each function
that both drives and reads one end; the access records hold each user's
first read and write lines; a FIFO in an imported module gets a prefixed
MAIN. Errors: an unused end, two users of one end, a user with two
instances, driving wr.ready or rd.stream, a missing initializer, a module
whose ports do not carry T, a global_sync_fifo's ends on two clocks, Fifo[T]
inside a function,
AUTO_PIPELINE of a handshake user, and a function already named <key>_FIFO.
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
from stream.stream_fifo import make_stream_fifo

"""

# A producer and a consumer through rx; designs below vary it
_PRODUCER = """
@MAIN(100.0)
def producer():
    n: Reg[uint8_t]
    rx.wr.stream.data = n
    rx.wr.stream.valid = 1
    if rx.wr.ready:
        n += 1
"""
_CONSUMER = """
@MAIN(100.0)
def consumer():
    rx.rd.ready = 1
    sink = rx.rd.stream.data
"""


def _parse(src, name, extra_files=None):
    with tempfile.TemporaryDirectory(prefix="global_fifo_elab_test_") as tmpdir:
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


def test_realization():
    src = (
        """
rx: Fifo[uint8_t] = global_fifo(4)
"""
        + _PRODUCER
        + _CONSUMER
        + """
@MAIN(100.0)
def fire_and_forget():
    tx.wr.stream.data = 7
    tx.wr.stream.valid = 1

tx: Fifo[uint8_t] = global_sync_fifo(2)

@MAIN(100.0)
def tx_reader():
    tx.rd.ready = 1
    sink2 = tx.rd.stream.data
"""
    )
    state = _parse(src, "realization_test.py")
    assert state.main_mhz["rx_FIFO"] == 100.0, state.main_mhz
    assert state.main_syn_mhz["rx_FIFO"] == 100.0, state.main_syn_mhz
    assert state.main_clk_group["rx_FIFO"] is None
    assert "rx_FIFO" in state.pypeline_emission_names.protected
    assert set(state.LogicInstLookupTable["rx_FIFO"].submodule_instances.values())
    no_latency = state.func_no_added_latency
    assert no_latency["rx_FIFO"] == "global FIFO", no_latency
    assert no_latency["tx_FIFO"] == "global FIFO", no_latency
    assert no_latency["producer"] == "global FIFO handshake", no_latency
    assert no_latency["consumer"] == "global FIFO handshake", no_latency
    assert no_latency["tx_reader"] == "global FIFO handshake", no_latency
    # Drives the write end, never reads it: no handshake to break
    assert "fire_and_forget" not in no_latency, no_latency
    table = state.FuncLogicLookupTable
    assert not table["rx_FIFO"].CAN_HAVE_ADDED_LATENCY(state)
    assert not table["producer"].CAN_HAVE_ADDED_LATENCY(state)
    # Access records: the source's own first accesses, with their lines
    producer = table["producer"]
    writes = producer.global_wire_write_locs["rx"]
    reads = producer.global_wire_read_paths["rx"]
    assert set(writes) == {("wr", "stream", "data"), ("wr", "stream", "valid")}, writes
    assert set(reads) == {("wr", "ready")}, reads
    lines = {line for _, line in list(writes.values()) + list(reads.values())}
    assert lines == {13, 14, 15}, (writes, reads)
    assert set(table["rx_FIFO"].global_wire_write_locs["rx"]) == {
        ("wr", "ready"),
        ("rd", "stream"),
    }
    assert set(table["rx_FIFO"].global_wire_read_paths["rx"]) == {
        ("wr", "stream"),
        ("rd", "ready"),
    }
    decl = state.pypeline_global_insts["rx"]
    assert (decl.kind, decl.n, decl.line) == ("global_fifo", 4, 8), vars(decl)
    assert decl.describe() == "global FIFO rx [realization_test.py:8]"
    print("realization PASS")


def test_imported_module_fifo():
    sub = """
q: Fifo[uint16_t] = global_fifo(8)

@MAIN
def q_producer():
    q.wr.stream.data = 5
    q.wr.stream.valid = 1
"""
    src = """
import fifo_sub_design

@MAIN
def q_consumer():
    fifo_sub_design.q.rd.ready = 1
    sink = fifo_sub_design.q.rd.stream.data
"""
    state = _parse(src, "imported_fifo_test.py", {"fifo_sub_design.py": sub})
    assert "fifo_sub_design_q_FIFO" in state.main_mhz, sorted(state.main_mhz)
    assert state.func_no_added_latency["q_consumer"] == "global FIFO handshake"
    print("imported_module_fifo PASS")


def test_unused_end():
    src = "\nrx: Fifo[uint8_t] = global_fifo(4)\n" + _PRODUCER
    _expect_error(src, "unused_end_test.py", ["global FIFO rx", "'rx.rd'", "not used"])


def test_two_users_of_one_end():
    src = (
        "\nrx: Fifo[uint8_t] = global_fifo(4)\n"
        + _PRODUCER
        + _CONSUMER
        + """
@MAIN(100.0)
def snooper():
    sink = rx.rd.stream.valid
"""
    )
    _expect_error(
        src,
        "two_users_test.py",
        ["'rx.rd'", "2 functions", "'consumer' (two_users_test.py:", "'snooper'"],
    )


def test_user_with_two_instances():
    src = (
        "\nrx: Fifo[uint8_t] = global_fifo(4)\n"
        + _PRODUCER
        + """
@hw_func
def take(x: uint8_t) -> uint8_t:
    rx.rd.ready = 1
    return rx.rd.stream.data + x

@MAIN(100.0)
def consumer():
    a = take(1)
    b = take(2)
"""
    )
    _expect_error(src, "two_instances_test.py", ["'take'", "2 instance(s)"])


def test_driving_wr_ready():
    src = (
        "\nrx: Fifo[uint8_t] = global_fifo(4)\n"
        + """
@MAIN(100.0)
def producer():
    rx.wr.stream.valid = 1
    rx.wr.ready = 1
"""
        + _CONSUMER
    )
    _expect_error(
        src,
        "drive_wr_ready_test.py",
        ["'producer' drives 'rx.wr.ready'", "drive_wr_ready_test.py:13", "the FIFO drives"],
    )


def test_driving_rd_stream():
    src = (
        "\nrx: Fifo[uint8_t] = global_fifo(4)\n"
        + _PRODUCER
        + """
@MAIN(100.0)
def consumer():
    rx.rd.ready = 1
    rx.rd = rx.rd
"""
    )
    _expect_error(src, "drive_rd_stream_test.py", ["'consumer' drives 'rx.rd'", "rx.rd.stream"])


def test_missing_initializer():
    src = "\nrx: Fifo[uint8_t]\n" + _PRODUCER + _CONSUMER
    _expect_error(src, "missing_init_test.py", ["'rx'", "global_fifo(n)", "missing_init_test.py:8"])


def test_module_port_mismatch():
    src = "\nrx: Fifo[uint8_t] = make_stream_fifo(uint16_t, 4)\n" + _PRODUCER + _CONSUMER
    _expect_error(
        src,
        "port_mismatch_test.py",
        ["global FIFO 'rx'", "make_stream_t(uint8_t)", "port_mismatch_test.py:8"],
    )


def test_sync_fifo_ends_on_two_clocks():
    # global_sync_fifo states one clock; global_fifo across two clocks is an
    # async FIFO (async_fifo_elab_test.py)
    src = (
        "\nrx: Fifo[uint8_t] = global_sync_fifo(4)\n"
        + _PRODUCER
        + _CONSUMER.replace("@MAIN(100.0)", "@MAIN(50.0)")
    )
    _expect_error(
        src,
        "two_clocks_test.py",
        ["clk_100p0", "clk_50p0", "'producer'", "'consumer'", "global_sync_fifo"],
    )
    # Clock inference does not follow a FIFO: a bare consumer stays clk_None
    src = (
        "\nrx: Fifo[uint8_t] = global_sync_fifo(4)\n"
        + _PRODUCER
        + _CONSUMER.replace("@MAIN(100.0)", "@MAIN")
    )
    _expect_error(
        src,
        "bare_end_test.py",
        ["clk_100p0", "clk_None", "does not take its clock through a FIFO"],
    )


def test_fifo_inside_function():
    src = (
        "\nrx: Fifo[uint8_t] = global_fifo(4)\n"
        + _PRODUCER
        + _CONSUMER
        + """
@MAIN(100.0)
def local_fifo():
    q: Fifo[uint8_t]
"""
    )
    _expect_error(src, "local_fifo_test.py", ["Fifo[T]", "global declarations", "local_fifo"])


def test_auto_pipeline_of_handshake_user():
    src = (
        "\nrx: Fifo[uint8_t] = global_fifo(4)\n"
        + """
@hw_func
def produce(x: uint8_t) -> uint1_t:
    rx.wr.stream.data = x
    rx.wr.stream.valid = 1
    return rx.wr.ready

AP = AUTO_PIPELINE(produce)

@MAIN(100.0)
def producer():
    n: Reg[uint8_t]
    if AP(n):
        n += 1
"""
        + _CONSUMER
    )
    _expect_error(
        src,
        "auto_pipeline_handshake_test.py",
        ["AUTO_PIPELINE(produce)", "'rx.wr'", "make_stream_auto_pipeline"],
    )


def test_fifo_main_name_collision():
    src = (
        "\nrx: Fifo[uint8_t] = global_fifo(4)\n"
        + _PRODUCER
        + _CONSUMER
        + """
@MAIN(100.0)
def rx_FIFO():
    unused: uint8_t = 1
"""
    )
    _expect_error(src, "name_collision_test.py", ["'rx_FIFO'", "already uses"])


if __name__ == "__main__":
    test_realization()
    test_imported_module_fifo()
    test_unused_end()
    test_two_users_of_one_end()
    test_user_with_two_instances()
    test_driving_wr_ready()
    test_driving_rd_stream()
    test_missing_initializer()
    test_module_port_mismatch()
    test_sync_fifo_ends_on_two_clocks()
    test_fifo_inside_function()
    test_auto_pipeline_of_handshake_user()
    test_fifo_main_name_collision()
    print("global_fifo_elab_test: all PASS")
