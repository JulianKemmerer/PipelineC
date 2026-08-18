import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

# In-process regression tests for one rule, checked at every declaration site
# that could carry it: no non-port construct may be declared with an
# @interface's .fwd_t/.fb_t port-pairing type. That type only means something
# at a real port crossing (a hw_func's own signature, or an inline
# `intrf.fwd_t(...)`/`intrf.fb_t(...)` constructor call used directly as a
# call argument) -- everywhere else, the correct type is the plain,
# never-paired `.stream_t`. Merged from four originally separate files (each
# probing a different declaration site, same mechanism and message shape):
#   - Reg[T]/Feedback[T]           (was reg_interface_type_error_test.py)
#   - local variables + Feedback[T], generalized
#                                   (was local_var_interface_type_error_test.py)
#   - global Wire[T]/Input[T]/Output[T]
#                                   (was global_wire_interface_type_error_test.py)
#   - a plain (non-hw_func) function's return value
#                                   (was indirect_interface_pairing_return_error_test.py)
# Checked in-process via PY_TO_LOGIC.PARSE_FILE, same pattern as
# global_wire_errors_test.py/pylist_value_context_error_test.py, since the
# check is "which ElaborationError (if any) is raised."
#
# Two functions from the original files were true duplicates once merged
# (both declared a bare `Feedback[chan_intrf.fwd_t]` and asserted the same
# error) and were combined into one: see test_feedback_fwd_t_errors below.
# Everything else that shared a name across the originals exercised a
# distinct nuance and was kept, disambiguated.

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
sys.path.insert(0, {pypeline_dir!r})
from pypeline import MAIN, NamedTuple, struct, hw_func, Reg, Feedback, wires, Wire, Input, Output, uint1_t, uint8_t
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
    with tempfile.TemporaryDirectory(prefix="interface_type_error_test_") as tmpdir:
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


# ── Reg[T]/Feedback[T] (was reg_interface_type_error_test.py) ──
# A register is internal state, never a port, so it never needs -- or should
# imply -- the .fwd_t/.fb_t port-pairing signal.


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


def test_feedback_fwd_t_errors():
    # Feedback[T] is a real forward-referenced port value, not internal state
    # like Reg[T] -- but it is not itself a port either, so it is banned from
    # using an @interface's .fwd_t/.fb_t port-pairing type too.
    src = """
@MAIN
def m():
    r: Feedback[chan_intrf.fwd_t]
    x: uint1_t = r.stream.valid
    r = chan_intrf.fwd_t(stream=chan_intrf.stream_t(data=0, valid=0))
"""
    _expect_elaboration_error(src, "feedback_fwd_t_test.py", ["r", "stream_t"])


def test_feedback_stream_t_is_clean():
    # The correct replacement: feed back the plain stream value.
    src = """
@MAIN
def m():
    r: Feedback[chan_intrf.stream_t]
    x: uint1_t = r.valid
    r = chan_intrf.stream_t(data=0, valid=0)
"""
    _expect_clean(src, "feedback_stream_t_test.py")


# ── Local variables + Feedback[T], generalized (was
# local_var_interface_type_error_test.py) ──
# The same _pypeline_interface_role-based mechanism as the Reg[T] restriction
# above, generalized in _elab_ann_assign to any local AnnAssign, not just
# Reg[T]. `.fwd_t`/`.fb_t` may still appear as: hw_func signature args/
# return-struct fields (parsed elsewhere, never reaches this check), and
# inline `intrf.fwd_t(...)`/`intrf.fb_t(...)` constructor-call *expressions*
# at a real port crossing (a call argument, or an assignment RHS) -- never as
# any other local's or Feedback wire's own declared type.


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


def test_feedback_fb_t_errors():
    src = """
@MAIN
def m() -> uint1_t:
    r: Feedback[chan_intrf.fb_t]
    r = chan_intrf.fb_t(ready=1)
    return r.ready
"""
    _expect_elaboration_error(src, "feedback_fb_t_test.py", ["r", "stream_t"])


def test_feedback_stream_t_is_clean_via_port_crossing():
    # A fuller version of test_feedback_stream_t_is_clean above: not just a
    # clean declaration, but the full idiom end to end -- feed back the plain
    # stream value, and construct '.fwd_t' inline only at the point it meets
    # a real port (consumer's own hw_func signature).
    src = """
@MAIN
def m() -> uint1_t:
    r: Feedback[chan_intrf.stream_t]
    x: chan_intrf.stream_t
    x.valid = 1
    r = x
    fb = consumer(stream_in_if=chan_intrf.fwd_t(stream=r))
    return fb.stream_in_if.ready
"""
    _expect_clean(src, "feedback_stream_t_via_port_crossing_test.py")


def test_unannotated_local_fwd_t_assign_errors():
    # The same ban, but via a bare 'x = intrf.fwd_t(...)' assignment with no
    # type annotation at all -- must not be a loophole around the annotated
    # form's check (a plain assignment RHS that is itself a struct-constructor
    # call takes a different elaboration code path than AnnAssign).
    src = """
@MAIN
def m() -> uint1_t:
    bad = chan_intrf.fwd_t(stream=chan_intrf.stream_t(data=0, valid=0))
    return bad.stream.valid
"""
    _expect_elaboration_error(src, "unannotated_local_fwd_t_assign_test.py", ["bad", "stream_t"])


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


# ── Global Wire[T]/Input[T]/Output[T] (was
# global_wire_interface_type_error_test.py) ──
# None of Wire/Input/Output are themselves a paired port-pairing construct --
# Wire is plain internal wiring, Input/Output are single flattened top-level
# chip signals -- so none of them ever need (or should imply) pairing. Use
# .stream_t plus a separate Wire/Input/Output[uint1_t] for the ready/valid
# half, and construct '.fwd_t'/'.fb_t' inline only at a real port crossing.


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


# ── A plain (non-hw_func) function's return value (was
# indirect_interface_pairing_return_error_test.py) ──
# Checked in _try_eval_const's _check_no_indirect_interface_pairing_return: a
# helper function that internally builds and returns a .fwd_t/.fb_t hides the
# pairing construction behind a call boundary -- the value must be
# constructed inline, `intrf.fwd_t(...)`/`intrf.fb_t(...)`, only at the point
# it meets a real port. The one exemption is that sanctioned inline
# constructor call itself.


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
    # test_inline_ctor_call_argument_from_helper_is_clean below), never
    # "assign to a local first." Covered by _elab_assign's own struct-ctor-
    # call path, a different code path than _try_eval_const's indirect-return
    # check above (which exempts direct '.fwd_t'/'.fb_t' calls specifically
    # so they still work as inline call arguments).
    src = """
@MAIN
def m() -> uint1_t:
    x = chan_intrf.fwd_t(stream=good_stream_null())
    return x.stream.valid
"""
    _expect_elaboration_error(src, "bare_assign_of_direct_ctor_call_test.py", ["x", "stream_t"])


def test_inline_ctor_call_argument_from_helper_is_clean():
    # Same sanctioned idiom as test_inline_ctor_call_argument_is_clean above,
    # but sourcing the stream value from a plain-function return
    # (good_stream_null()) instead of live MAIN port args -- staying clean
    # here specifically distinguishes this from the banned pattern one test
    # up, where the *fwd_t-typed* return value (not its stream_t input) is
    # what gets stashed in a local.
    src = """
@MAIN
def m() -> uint1_t:
    fb = consumer(stream_in_if=chan_intrf.fwd_t(stream=good_stream_null()))
    return fb.stream_in_if.ready
"""
    _expect_clean(src, "inline_ctor_call_argument_from_helper_test.py")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
