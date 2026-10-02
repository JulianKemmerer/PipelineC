# pyright: reportInvalidTypeForm=none
"""Fixture for c_structs_pkg_relayout_test.py, shaped like WireGuard's
make_poly1305_mac_pipelined(direction).

powers_t.values is sized by body_ap.latency + 2, a lane count that is not a
factory parameter. powers_t's logical C type therefore changes between
AUTO_PIPELINE pin-and-confirm passes, while its emitted VHDL name
(powers_t_from_..._direction_encrypt) does not. acc_t depends on powers_t.
lane_sel_t holds a lane index whose bit width follows the lane count, and
pick() reads a lane through it (a dynamic array-mux leaf sized by lanes).
The two directions' bodies differ (salt), so each has its own latency.
"""
import os
import sys
from typing import NamedTuple

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    hw_func,
    make_uint_t,
    struct,
    uint1_t,
    uint8_t,
    uint32_t,
)


def make_mac(direction: str):
    salt = 1 if direction == "encrypt" else 3

    @hw_func
    def body(x: uint32_t) -> uint32_t:
        return x * x + salt

    body_ap = AUTO_PIPELINE(body)
    lanes = body_ap.latency + 2

    @struct
    class powers_t(NamedTuple):
        values: uint32_t[lanes]

    @struct
    class acc_t(NamedTuple):
        powers: powers_t
        valid: uint1_t

    lane_idx_t = make_uint_t(max(1, (lanes - 1).bit_length()))

    @struct
    class lane_sel_t(NamedTuple):
        lane: lane_idx_t

    @hw_func
    def mac(x: uint32_t) -> acc_t:
        rv: acc_t
        for i in range(lanes):
            rv.powers.values[i] = body_ap(x + i)
        rv.valid = 1
        return rv

    @hw_func
    def pick(acc: acc_t, sel: uint8_t) -> uint32_t:
        s: lane_sel_t
        s.lane = sel
        return acc.powers.values[s.lane]

    return mac, pick


encrypt_mac, encrypt_pick = make_mac("encrypt")
decrypt_mac, decrypt_pick = make_mac("decrypt")


@MAIN
def c_structs_pkg_relayout_encrypt(x: uint32_t, sel: uint8_t) -> uint32_t:
    acc = encrypt_mac(x)
    return acc.powers.values[0] ^ acc.valid ^ encrypt_pick(acc, sel)


@MAIN
def c_structs_pkg_relayout_decrypt(x: uint32_t, sel: uint8_t) -> uint32_t:
    acc = decrypt_mac(x)
    return acc.powers.values[0] ^ acc.valid ^ decrypt_pick(acc, sel)
