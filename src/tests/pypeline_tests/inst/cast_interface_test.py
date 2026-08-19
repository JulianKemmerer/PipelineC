# pyright: reportInvalidTypeForm=none
"""Casts for stream-interface halves (stream.make_stream_interface's
wrap/unwrap casts, registered lazily -- see stream.py's
_register_stream_casts). The unwrap direction (fwd_t -> stream_t,
fb_t -> feedback_t) rewrites no production code anywhere in this repo (a
cast is longer than the plain field read `.stream`/`.ready` it would
replace -- see the plan's call-site survey), so this file is its only
coverage; it must exercise both directions directly, not rely on a
refactored call site.
"""
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from typing import NamedTuple

from pypeline import MAIN, hw_func, sim_call, sim_reset, struct, uint1_t, uint4_t, uint8_t

from stream.stream import make_stream_interface
from stream.stream_fifo import make_stream_fifo

axis8_intrf = make_stream_interface(uint8_t)
stream_t = axis8_intrf.stream_t
fwd_t = axis8_intrf.fwd_t
fb_t = axis8_intrf.fb_t

# feedback_t != uint1_t: a wide (credit-style) backpressure signal.
wide_intrf = make_stream_interface(uint8_t, feedback_t=uint4_t)
wide_stream_t = wide_intrf.stream_t
wide_fwd_t = wide_intrf.fwd_t
wide_fb_t = wide_intrf.fb_t


@MAIN
def wrap_fwd(d: uint8_t, v: uint1_t) -> fwd_t:
    return fwd_t(stream_t(data=d, valid=v))


@MAIN
def wrap_fb(r: uint1_t) -> fb_t:
    return fb_t(r)


# The unwrap direction takes an interface half as an ARGUMENT (a real port),
# which a plain (non-@cast) hw_func may only do paired with its other half
# -- see _check_partial_interface_ports -- so these wrap the unwrap result
# in a plain one-field struct (mirroring interface_type_error_test.py's
# consumer_t idiom) rather than returning fb_t/fwd_t directly, which would
# trip the SAME pairing check a second time on the way out, and rather than
# ever declaring a bare fwd_t/fb_t-typed LOCAL, which the interface-half-
# local ban (correctly) rejects regardless of whether it came from a cast.


# Both halves of one port share the SAME name (interface.py's own
# convention -- see its module docstring) -- an arg named "fwd_if" paired
# with a return field named anything else is two unrelated, still-partial
# ports as far as _check_partial_interface_ports is concerned, not one
# paired port.


@struct
class fwd_unwrap_result_t(NamedTuple):
    port_if: fb_t


@hw_func
def unwrap_fwd_paired(port_if: fwd_t) -> fwd_unwrap_result_t:
    unwrapped: stream_t = stream_t(port_if)
    o: fwd_unwrap_result_t
    o.port_if = fb_t(unwrapped.valid)
    return o


@struct
class fb_unwrap_result_t(NamedTuple):
    port_if: fwd_t


@hw_func
def unwrap_fb_paired(port_if: fb_t) -> fb_unwrap_result_t:
    r: uint1_t = uint1_t(port_if)
    o: fb_unwrap_result_t
    o.port_if = fwd_t(stream_t(data=0, valid=r))
    return o


@MAIN
def unwrap_fwd(d: uint8_t, v: uint1_t) -> uint1_t:
    r = unwrap_fwd_paired(fwd_t(stream_t(data=d, valid=v)))
    return r.port_if.ready


@MAIN
def unwrap_fb(r: uint1_t) -> uint1_t:
    x = unwrap_fb_paired(fb_t(r))
    return x.port_if.stream.valid


@MAIN
def wrap_wide_fb(credit: uint4_t) -> wide_fb_t:
    return wide_fb_t(credit)


@struct
class wide_fb_unwrap_result_t(NamedTuple):
    port_if: wide_fwd_t


@hw_func
def unwrap_wide_fb_paired(port_if: wide_fb_t) -> wide_fb_unwrap_result_t:
    credit: uint4_t = uint4_t(port_if)
    o: wide_fb_unwrap_result_t
    o.port_if = wide_fwd_t(wide_stream_t(data=0, valid=0))
    o.port_if.stream.data = credit
    return o


@MAIN
def unwrap_wide_fb(credit: uint4_t) -> uint8_t:
    x = unwrap_wide_fb_paired(wide_fb_t(credit))
    return x.port_if.stream.data


def test_wrap_fwd():
    sim_reset()
    r = sim_call(wrap_fwd, 42, 1)
    assert int(r.stream.data) == 42 and int(r.stream.valid) == 1, r


def test_wrap_fb():
    sim_reset()
    r = sim_call(wrap_fb, 1)
    assert int(r.ready) == 1, r


def test_unwrap_fwd():
    sim_reset()
    r = sim_call(unwrap_fwd, 42, 1)
    assert int(r) == 1, r
    sim_reset()
    r0 = sim_call(unwrap_fwd, 42, 0)
    assert int(r0) == 0, r0


def test_unwrap_fb():
    sim_reset()
    r = sim_call(unwrap_fb, 1)
    assert int(r) == 1, r


def test_wide_feedback_wrap_unwrap():
    sim_reset()
    w = sim_call(wrap_wide_fb, 9)
    assert int(w.ready) == 9, w
    sim_reset()
    u = sim_call(unwrap_wide_fb, 9)
    assert int(u) == 9, u


# ── aliased call form: stream_fifo.fb_t(...) / .fwd_t(...) via an attribute
# stamped on the returned hw_func, not a direct .fwd_t/.fb_t AST attribute
# on an _intrf variable -- exercises _try_eval_const resolving an arbitrary
# attribute chain, per _elab_cast_call/_is_pypeline_type. ──

stream_fifo, stream_fifo_t = make_stream_fifo(uint8_t, 4)


@MAIN
def aliased_wrap_fwd(d: uint8_t, v: uint1_t) -> stream_fifo.fwd_t:
    return stream_fifo.fwd_t(stream_fifo.stream_intrf.stream_t(data=d, valid=v))


@MAIN
def aliased_wrap_fb(r: uint1_t) -> stream_fifo.fb_t:
    return stream_fifo.fb_t(r)


def test_aliased_call_form_wrap_fwd():
    sim_reset()
    r = sim_call(aliased_wrap_fwd, 7, 1)
    assert int(r.stream.data) == 7 and int(r.stream.valid) == 1, r


def test_aliased_call_form_wrap_fb():
    sim_reset()
    r = sim_call(aliased_wrap_fb, 1)
    assert int(r.ready) == 1, r


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
