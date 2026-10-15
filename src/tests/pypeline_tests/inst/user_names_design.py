# pyright: reportInvalidTypeForm=none
"""Every form of name=: a factory-produced @hw_func, @struct and @enum, two
named AUTO_PIPELINE groups over one function, and named stream AUTO_PIPELINE
and AUTO_MULTI_CYCLE tags. Used by double_parse_file_test (names are stable
across re-parses) and native-simulated by its own __main__ check."""
import os
import sys
from enum import IntEnum

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../include/pypeline")
)

from pypeline import (  # noqa: E402
    AUTO_PIPELINE,
    MAIN,
    NamedTuple,
    enum,
    hw_func,
    struct,
    uint8_t,
    uint16_t,
)
from stream.stream_auto_pipeline import make_stream_auto_pipeline  # noqa: E402
from stream.stream_multi_cycle import make_stream_auto_multi_cycle  # noqa: E402


def make_pair_t(n):
    @struct(name=f"pair{n}_t")
    class pair_t(NamedTuple):
        a: uint8_t
        b: uint8_t

    return pair_t


def make_mode_t():
    @enum(name="mode_t")
    class mode_e(IntEnum):
        IDLE = 0
        RUN = 1

    return mode_e


def make_adder(k):
    @hw_func(name=f"add_{k}")
    def adder(x: uint8_t) -> uint8_t:
        return x + k

    return adder


pair4_t = make_pair_t(4)
mode_t = make_mode_t()
add3 = make_adder(3)
add5 = make_adder(5)


@hw_func
def square(x: uint16_t) -> uint16_t:
    return x * x


@hw_func
def triple(x: uint16_t) -> uint16_t:
    return x * 3


square_encrypt = AUTO_PIPELINE(square, name="square_encrypt")
square_decrypt = AUTO_PIPELINE(square, name="square_decrypt", start_latency=1)
triple_stream = make_stream_auto_pipeline(triple, name="triple")

triple_mcp = make_stream_auto_multi_cycle(triple, name="triple_mcp")


@MAIN
def user_names_main(x: uint8_t, y: uint16_t, z: uint16_t) -> uint16_t:
    p = pair4_t(a=add3(x), b=add5(x))
    m: mode_t = mode_t.RUN
    rv: uint16_t = square_encrypt(y) + square_decrypt(z) + p.a + p.b
    if m == mode_t.IDLE:
        rv = 0
    return rv
