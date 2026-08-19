import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

# In-process regression tests for casting's error paths: an unregistered
# (src, dst) pair, wrong arity/keywords, casting to an array type, and that
# the pre-existing interface-half bans still apply to a cast's OWN local
# handling and that multi-field interface ctors still require keywords (a
# 1-positional-arg call on a 2+-field struct is cast-shaped, so it must
# raise "no cast registered", not silently under-drive one field the way
# the pre-cast positional zip(_fields, args) used to).

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
sys.path.insert(0, {pypeline_dir!r})
from typing import NamedTuple
from pypeline import MAIN, NamedTuple, struct, hw_func, Feedback, uint1_t, uint8_t, uint16_t
from stream.stream import make_stream_interface

chan_intrf = make_stream_interface(uint8_t)


@struct
class two_field_t(NamedTuple):
    a: uint8_t
    b: uint8_t


@struct
class consumer_t(NamedTuple):
    stream_in_if: chan_intrf.fb_t


@hw_func
def consumer(stream_in_if: chan_intrf.fwd_t) -> consumer_t:
    # Real port crossing using chan_intrf.fwd_t/.fb_t in a signature --
    # matching interface_type_error_test.py's shared header -- so
    # stream_t/fwd_t/fb_t are registered in struct_to_field_type_dict the
    # ordinary way (_elaborate_live_func's closure-struct-registration).
    # _discover_structs_from_module explicitly skips @interface objects
    # themselves, so without some real signature use, a design that only
    # ever touches these types via a bare (non-port, non-cast) keyword
    # struct-ctor -- unrelated to anything under test here -- would hit an
    # unrelated pre-existing KeyError in _write_ref before ever reaching the
    # check actually being tested.
    o: consumer_t
    o.stream_in_if.ready = 1
    return o
"""

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
PYPELINE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "include", "pypeline"
)


def _parse(src, name):
    with tempfile.TemporaryDirectory(prefix="cast_error_test_") as tmpdir:
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


def test_unregistered_cast_pair_errors():
    src = """
@MAIN
def m(x: uint16_t) -> two_field_t:
    return two_field_t(x)
"""
    _expect_elaboration_error(
        src, "unregistered_cast_pair_test.py", ["no cast registered", "uint16_t"]
    )


def test_wrong_arity_scalar_cast_errors_clearly():
    # uint8_t() -- zero args -- is not cast-shaped (_is_cast_call requires
    # exactly one positional, zero keyword), so it falls through to being
    # treated as an ordinary call to the live callable `uint8_t`, which
    # previously reached _elaborate_live_func and died with an opaque,
    # uncaught OSError from inspect.getsourcelines (a ctype class has no
    # retrievable Python source) -- now a clear ElaborationError instead.
    src = """
@MAIN
def m() -> uint8_t:
    return uint8_t()
"""
    _expect_elaboration_error(src, "wrong_arity_scalar_cast_test.py", ["cast"])


def test_array_ctype_cast_errors():
    src = """
@MAIN
def m(x: uint8_t[4]) -> uint8_t[4]:
    return uint8_t[4](x)
"""
    _expect_elaboration_error(src, "array_ctype_cast_test.py", ["array"])


def test_bare_local_fwd_t_still_banned_via_cast_call():
    # x = chan_intrf.fwd_t(s) is 1-positional -- cast-shaped -- but the
    # bare-local ban (a .fwd_t/.fb_t local may only be constructed inline at
    # a real port crossing) keys off the DECLARED type, not the call shape,
    # so it must still fire.
    src = """
@MAIN
def m(d: uint8_t, v: uint1_t) -> uint1_t:
    s = chan_intrf.stream_t(data=d, valid=v)
    bad = chan_intrf.fwd_t(s)
    return bad.stream.valid
"""
    _expect_elaboration_error(
        src, "bare_local_fwd_t_via_cast_test.py", ["local variable", "fwd_t"]
    )


def test_multi_field_interface_ctor_still_requires_keywords():
    # chan_intrf.fwd_t has 2 fields ({data, valid} -- the flat, non-stream
    # shape this factory doesn't use, so build one directly) -- a single
    # positional arg on it is cast-shaped, and no cast is registered from a
    # bare uint8_t into it, so it must raise rather than silently binding
    # only the first field (the pre-cast positional-ctor bug).
    src = """
@struct
class flat_chan_t(NamedTuple):
    data: uint8_t
    valid: uint1_t

@MAIN
def m(d: uint8_t) -> uint8_t:
    x: flat_chan_t = flat_chan_t(d)
    return x.data
"""
    _expect_elaboration_error(
        src, "multi_field_ctor_positional_test.py", ["no cast registered"]
    )


def test_multi_field_interface_ctor_with_keywords_is_clean():
    src = """
@struct
class flat_chan_t(NamedTuple):
    data: uint8_t
    valid: uint1_t

@MAIN
def m(d: uint8_t, v: uint1_t) -> uint8_t:
    x: flat_chan_t = flat_chan_t(data=d, valid=v)
    return x.data
"""
    _expect_clean(src, "multi_field_ctor_keyword_test.py")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
