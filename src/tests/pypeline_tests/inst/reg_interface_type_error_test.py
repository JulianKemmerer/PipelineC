import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

# In-process regression tests for the Reg[T]-may-not-be-interface-derived
# check: `Reg[some_intrf.fwd_t]`/`Reg[some_intrf.fb_t]` must be a hard
# ElaborationError (a register is internal state, never a port, so it never
# needs -- or should imply -- the .fwd_t/.fb_t port-pairing signal), while
# `Reg[some_intrf.stream_t]` (the plain, never-paired data+valid half) and
# `Feedback[some_intrf.fwd_t]` (a real forward-referenced port value, not
# internal state -- deliberately exempt) must both elaborate cleanly. Checked
# in-process via PY_TO_LOGIC.PARSE_FILE, same pattern as
# global_wire_errors_test.py/pylist_value_context_error_test.py, since the
# check is "which ElaborationError (if any) is raised."

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
sys.path.insert(0, {pypeline_dir!r})
from pypeline import MAIN, NamedTuple, Reg, Feedback, uint1_t, uint8_t
from stream.stream import make_stream_interface

chan_intrf = make_stream_interface(uint8_t)

"""

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
PYPELINE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "include", "pypeline"
)


def _parse(src, name):
    with tempfile.TemporaryDirectory(prefix="reg_interface_type_error_test_") as tmpdir:
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


def test_reg_fwd_t_errors():
    src = """
@MAIN
def m():
    r: Reg[chan_intrf.fwd_t]
"""
    _expect_elaboration_error(src, "reg_fwd_t_test.py", ["r", "stream_t"])


def test_reg_fb_t_errors():
    src = """
@MAIN
def m():
    r: Reg[chan_intrf.fb_t]
"""
    _expect_elaboration_error(src, "reg_fb_t_test.py", ["r", "stream_t"])


def test_reg_fwd_t_array_errors():
    # Array-of-interface-type Reg must also be caught (element-type unwrap).
    src = """
@MAIN
def m():
    r: Reg[chan_intrf.fwd_t[2]]
"""
    _expect_elaboration_error(src, "reg_fwd_t_array_test.py", ["r", "stream_t"])


def test_reg_stream_t_is_clean():
    # The correct replacement type must not trip the check.
    src = """
@MAIN
def m():
    r: Reg[chan_intrf.stream_t]
    r.valid = 1
"""
    _expect_clean(src, "reg_stream_t_test.py")


def test_feedback_fwd_t_is_clean():
    # Feedback[T] is a real forward-referenced port value, not internal
    # state -- deliberately exempt from this check.
    src = """
@MAIN
def m():
    r: Feedback[chan_intrf.fwd_t]
    x: uint1_t = r.stream.valid
    r = chan_intrf.fwd_t(stream=chan_intrf.stream_t(data=0, valid=0))
"""
    _expect_clean(src, "feedback_fwd_t_test.py")


if __name__ == "__main__":
    test_reg_fwd_t_errors()
    test_reg_fb_t_errors()
    test_reg_fwd_t_array_errors()
    test_reg_stream_t_is_clean()
    test_feedback_fwd_t_is_clean()
    print("All reg_interface_type_error tests passed.")
