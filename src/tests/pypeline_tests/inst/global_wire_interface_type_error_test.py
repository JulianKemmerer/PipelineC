import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

# In-process regression tests for "a global Wire[T]/Input[T]/Output[T] may
# never be declared with an @interface's .fwd_t/.fb_t port-pairing type"
# (mirrors the local-variable and Reg[T] restrictions, generalized in
# _discover_global_wires). None of Wire/Input/Output are themselves a paired
# port-pairing construct -- Wire is plain internal wiring, Input/Output are
# single flattened top-level chip signals -- so none of them ever need (or
# should imply) pairing. Use .stream_t plus a separate Wire/Input/Output
# [uint1_t] for the ready/valid half, and construct '.fwd_t'/'.fb_t' inline
# only at a real port crossing.

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
sys.path.insert(0, {pypeline_dir!r})
from pypeline import MAIN, wires, Wire, Input, Output, NamedTuple, struct, hw_func, uint1_t, uint8_t
from stream.stream import make_stream_interface

chan_intrf = make_stream_interface(uint8_t)

"""

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
PYPELINE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "include", "pypeline"
)


def _parse(src, name):
    with tempfile.TemporaryDirectory(prefix="global_wire_interface_type_error_test_") as tmpdir:
        path = os.path.join(tmpdir, name)
        with open(path, "w") as f:
            f.write(
                _HEADER.format(
                    repo_root=os.path.abspath(REPO_ROOT),
                    pypeline_dir=os.path.abspath(PYPELINE_DIR),
                )
            )
            f.write(src)
        return PY_TO_LOGIC.PARSE_FILE(path)


def _expect_elaboration_error(src, name, must_contain):
    try:
        _parse(src, name)
    except PY_TO_LOGIC.ElaborationError as e:
        msg = str(e)
        for token in must_contain:
            assert token.lower() in msg.lower(), (
                f"{name}: expected ElaborationError message to mention "
                f"{token!r}, got: {msg}"
            )
        print(f"{name} PASS  ({msg})")
        return
    raise AssertionError(
        f"{name}: expected an ElaborationError, but PARSE_FILE succeeded"
    )


def _expect_clean(src, name):
    try:
        _parse(src, name)
    except PY_TO_LOGIC.ElaborationError as e:
        raise AssertionError(
            f"{name}: expected clean elaboration, got ElaborationError: {e}"
        )
    print(f"{name} PASS (no error, as expected)")


def test_global_wire_fwd_t_errors():
    src = """
bad: Wire[chan_intrf.fwd_t]

@MAIN
@wires
def m():
    bad = chan_intrf.fwd_t(stream=chan_intrf.stream_t(data=0, valid=0))
"""
    _expect_elaboration_error(src, "global_wire_fwd_t_test.py", ["bad", "stream_t"])


def test_global_wire_fb_t_errors():
    src = """
bad: Wire[chan_intrf.fb_t]

@MAIN
@wires
def m():
    bad = chan_intrf.fb_t(ready=1)
"""
    _expect_elaboration_error(src, "global_wire_fb_t_test.py", ["bad", "stream_t"])


def test_global_input_fwd_t_errors():
    src = """
bad: Input[chan_intrf.fwd_t]

@MAIN
@wires
def m():
    x: chan_intrf.stream_t = bad.stream
"""
    _expect_elaboration_error(src, "global_input_fwd_t_test.py", ["bad", "stream_t"])


def test_global_output_fb_t_errors():
    src = """
bad: Output[chan_intrf.fb_t]

@MAIN
@wires
def m():
    bad = chan_intrf.fb_t(ready=1)
"""
    _expect_elaboration_error(src, "global_output_fb_t_test.py", ["bad", "stream_t"])


def test_global_wire_stream_t_is_clean():
    # The correct replacement type must not trip the check.
    src = """
good: Wire[chan_intrf.stream_t]
good_ready: Wire[uint1_t]

@MAIN
@wires
def m():
    good = chan_intrf.stream_t(data=0, valid=0)
    good_ready = 1
"""
    _expect_clean(src, "global_wire_stream_t_test.py")


def test_bare_interface_wire_is_clean_and_multi_writer():
    # Wire[SomeInterface] (the bare @interface class) is sugar for
    # Wire[SomeInterface.wire_t] -- a flat, non-directional struct that gets
    # full flattened multi-writer support for free: .stream written by one
    # function, .ready written by another, both read by a third.
    src = """
good_if: Wire[chan_intrf]

@hw_func
def drive_stream():
    good_if.stream = chan_intrf.stream_t(data=0, valid=1)

@hw_func
def drive_ready():
    good_if.ready = 1

@MAIN
@wires
def m() -> uint1_t:
    drive_stream()
    drive_ready()
    return good_if.stream.valid & good_if.ready
"""
    _expect_clean(src, "bare_interface_wire_test.py")


def test_bare_interface_wire_fwd_t_still_errors():
    # The bare-class sugar must not weaken the existing .fwd_t/.fb_t ban.
    src = """
bad: Wire[chan_intrf.fwd_t]

@MAIN
@wires
def m():
    bad = chan_intrf.fwd_t(stream=chan_intrf.stream_t(data=0, valid=0))
"""
    _expect_elaboration_error(src, "bare_interface_wire_fwd_t_test.py", ["bad", "stream_t"])


if __name__ == "__main__":
    test_global_wire_fwd_t_errors()
    test_global_wire_fb_t_errors()
    test_global_input_fwd_t_errors()
    test_global_output_fb_t_errors()
    test_global_wire_stream_t_is_clean()
    test_bare_interface_wire_is_clean_and_multi_writer()
    test_bare_interface_wire_fwd_t_still_errors()
    print("All global_wire_interface_type_error tests passed.")
