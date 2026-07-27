import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

# In-process regression tests for the "no plain local variable may be declared
# with an @interface's .fwd_t/.fb_t port-pairing type" check (the same
# _pypeline_interface_role-based mechanism as the shipped Reg[T] restriction,
# generalized in _elab_ann_assign to any local AnnAssign, not just Reg[T]).
# `.fwd_t`/`.fb_t` may still appear as: hw_func signature args/return-struct
# fields (parsed elsewhere, not via this AnnAssign path -- never even reaches
# this check), Feedback[T] (existing, separate exemption), and inline
# `intrf.fwd_t(...)`/`intrf.fb_t(...)` constructor-call *expressions* at a real
# port crossing (a call argument, or an assignment RHS) -- never as any other
# local's own declared type. Checked in-process via PY_TO_LOGIC.PARSE_FILE,
# same pattern as reg_interface_type_error_test.py.

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
sys.path.insert(0, {pypeline_dir!r})
from pypeline import MAIN, NamedTuple, struct, hw_func, Reg, Feedback, uint1_t, uint8_t
from stream.stream import make_stream_interface

chan_intrf = make_stream_interface(uint8_t)

@struct
class consumer_t(NamedTuple):
    stream_in_if: chan_intrf.fb_t

@hw_func
def consumer(stream_in_if: chan_intrf.fwd_t) -> consumer_t:
    o: consumer_t
    o.stream_in_if.ready = 1
    return o

"""

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
PYPELINE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "include", "pypeline"
)


def _parse(src, name):
    with tempfile.TemporaryDirectory(prefix="local_var_interface_type_error_test_") as tmpdir:
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


def test_local_fwd_t_errors():
    src = """
@MAIN
def m() -> uint1_t:
    bad: chan_intrf.fwd_t
    return bad.stream.valid
"""
    _expect_elaboration_error(src, "local_fwd_t_test.py", ["bad", "stream_t"])


def test_local_fb_t_errors():
    src = """
@MAIN
def m() -> uint1_t:
    bad: chan_intrf.fb_t
    return bad.ready
"""
    _expect_elaboration_error(src, "local_fb_t_test.py", ["bad", "stream_t"])


def test_local_stream_t_is_clean():
    # The correct replacement type must not trip the check.
    src = """
@MAIN
def m() -> uint1_t:
    good: chan_intrf.stream_t
    good.valid = 1
    return good.valid
"""
    _expect_clean(src, "local_stream_t_test.py")


def test_feedback_fwd_t_is_still_clean():
    # Feedback[T] remains exempt under the generalized check too.
    src = """
@MAIN
def m() -> uint1_t:
    r: Feedback[chan_intrf.fwd_t]
    x: chan_intrf.fb_t = chan_intrf.fb_t(ready=1)
    r = chan_intrf.fwd_t(stream=chan_intrf.stream_t(data=0, valid=0))
    return x.ready
"""
    # x itself is a plain local declared as .fb_t -- this must still error
    # (proves Feedback[T]'s exemption doesn't accidentally widen to cover
    # every other local declaration in the same function).
    _expect_elaboration_error(src, "feedback_fwd_t_test.py", ["x", "stream_t"])


def test_inline_ctor_call_argument_is_clean():
    # No local at all: .fwd_t/.fb_t constructed inline, directly as call
    # arguments -- the intended replacement idiom for every case above.
    src = """
@MAIN
def m(data: uint8_t, valid: uint1_t) -> uint1_t:
    fb = consumer(stream_in_if=chan_intrf.fwd_t(stream=chan_intrf.stream_t(data=data, valid=valid)))
    return fb.stream_in_if.ready
"""
    _expect_clean(src, "inline_ctor_call_argument_test.py")


if __name__ == "__main__":
    test_local_fwd_t_errors()
    test_local_fb_t_errors()
    test_local_stream_t_is_clean()
    test_feedback_fwd_t_is_still_clean()
    test_inline_ctor_call_argument_is_clean()
    print("All local_var_interface_type_error tests passed.")
