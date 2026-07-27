import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

# In-process regression tests for "a plain (non-hw_func) Python function may
# never return an @interface's .fwd_t/.fb_t port-pairing value" (checked in
# _try_eval_const's _check_no_indirect_interface_pairing_return, alongside the
# local-variable/Reg[T]/global-Wire restrictions). A helper function that
# internally builds and returns a .fwd_t/.fb_t hides the pairing construction
# behind a call boundary -- the value must be constructed inline,
# `intrf.fwd_t(...)`/`intrf.fb_t(...)`, only at the point it meets a real
# port. The one exemption is that sanctioned inline constructor call itself.

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
sys.path.insert(0, {pypeline_dir!r})
from pypeline import MAIN, NamedTuple, struct, hw_func, uint1_t, uint8_t
from stream.stream import make_stream_interface

chan_intrf = make_stream_interface(uint8_t)

def bad_null():
    return chan_intrf.fwd_t(stream=chan_intrf.stream_t(data=0, valid=0))

def good_stream_null():
    return chan_intrf.stream_t(data=0, valid=0)

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
    with tempfile.TemporaryDirectory(prefix="indirect_interface_pairing_return_error_test_") as tmpdir:
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


def test_function_returning_fwd_t_errors():
    src = """
@MAIN
def m() -> uint1_t:
    x: chan_intrf.stream_t = bad_null()
    return x.valid
"""
    _expect_elaboration_error(src, "function_returning_fwd_t_test.py", ["stream_t", "bad_null"])


def test_function_returning_stream_t_is_clean():
    src = """
@MAIN
def m() -> uint1_t:
    x: chan_intrf.stream_t = good_stream_null()
    return x.valid
"""
    _expect_clean(src, "function_returning_stream_t_test.py")


def test_bare_assign_of_direct_ctor_call_still_errors():
    # Even a direct '.fwd_t(...)' constructor call is banned once it's stashed
    # in a plain local via a bare (unannotated) assignment -- only genuine
    # inline use as a call argument/return expression is sanctioned (see
    # test_inline_ctor_call_argument_is_clean below), never "assign to a local
    # first." Covered by _elab_assign's own struct-ctor-call path, a different
    # code path than _try_eval_const's indirect-return check above (which
    # exempts direct '.fwd_t'/'.fb_t' calls specifically so they still work as
    # inline call arguments).
    src = """
@MAIN
def m() -> uint1_t:
    x = chan_intrf.fwd_t(stream=good_stream_null())
    return x.stream.valid
"""
    _expect_elaboration_error(src, "bare_assign_of_direct_ctor_call_test.py", ["x", "stream_t"])


def test_inline_ctor_call_argument_is_clean():
    # The sanctioned replacement idiom -- constructing .fwd_t/.fb_t directly,
    # inline, as a call argument expression, never stored in any local at all
    # -- must not itself trip this check.
    src = """
@MAIN
def m() -> uint1_t:
    fb = consumer(stream_in_if=chan_intrf.fwd_t(stream=good_stream_null()))
    return fb.stream_in_if.ready
"""
    _expect_clean(src, "inline_ctor_call_argument_test.py")


if __name__ == "__main__":
    test_function_returning_fwd_t_errors()
    test_function_returning_stream_t_is_clean()
    test_bare_assign_of_direct_ctor_call_still_errors()
    test_inline_ctor_call_argument_is_clean()
    print("All indirect_interface_pairing_return_error tests passed.")
