# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import (
    MAIN,
    uint1_t,
    uint4_t,
    uint8_t,
    uint16_t,
    uint32_t,
    uint64_t,
    bit_dup,
    rotl,
    rotr,
    bswap,
    bit_assign,
    array_to_uint_be,
    array_to_uint_le,
    uint_to_array_be,
    uint_to_array_le,
)


@MAIN
def test_bit_select(x: uint32_t) -> uint1_t:
    return x[15]


@MAIN
def test_bit_slice(x: uint32_t) -> uint16_t:
    return x[15:0]


@MAIN
def test_bit_slice_assign(x: uint32_t, y: uint16_t) -> uint32_t:
    x[15:0] = y
    return x


@MAIN
def test_tuple_concat2(a: uint32_t, b: uint32_t) -> uint64_t:
    return (a, b)


@MAIN
def test_tuple_concat3(a: uint16_t, b: uint16_t, c: uint32_t) -> uint64_t:
    return (a, b, c)


@MAIN
def test_bit_dup(x: uint4_t) -> uint16_t:
    return bit_dup(x, 4)


@MAIN
def test_rotl(x: uint64_t) -> uint64_t:
    return rotl(x, 7)


@MAIN
def test_rotr(x: uint32_t) -> uint32_t:
    return rotr(x, 3)


@MAIN
def test_bswap(x: uint32_t) -> uint32_t:
    return bswap(x)


@MAIN
def test_bit_assign(base: uint64_t, x: uint16_t) -> uint64_t:
    return bit_assign(base, x, 2)


@MAIN
def test_array_to_uint_be(arr: uint8_t[8]) -> uint64_t:
    return array_to_uint_be(arr)


@MAIN
def test_array_to_uint_le(arr: uint8_t[8]) -> uint64_t:
    return array_to_uint_le(arr)


@MAIN
def test_uint_to_array_be(x: uint64_t) -> uint8_t[8]:
    return uint_to_array_be(x, 8)


@MAIN
def test_uint_to_array_le(x: uint64_t) -> uint8_t[8]:
    return uint_to_array_le(x, 8)
