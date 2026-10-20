"""Unchanged shared Poly1305 kernels, with standalone factory scaffolding.

Source: wireguard-fpga/3.build/pypeline_build/src/poly1305/poly1305_mcp_shared.py.
"""
# Extracted from wireguard-fpga, accepted shared-poly1305-fsm64-latest-qor-20261017.
# WireGuard revision: a9eb0608 (plus the archived working-tree design).
# Archive SHA-256: 2c0989d316e83abd7c68e9126b541bd0537ec38266f4eb500ab4c17a17971cea.
from types import SimpleNamespace
from pypeline import NamedTuple, hw_func, make_uint_t, struct, uint1_t
from arithmetic import (wireguard_env, uint128_t, uint130_t, residue_mul_mod,
                        residue_add_mod, residue_square_mod)


def make_shared_compute(capacity):
    """Return named prologue/epilogue kernels and their payload types.

    powers_t is the prologue result payload; epilogue_in_t is the epilogue
    request payload. Each kernel also exposes its complete return_t.
    """
    lane_t = make_uint_t(max(1, (capacity - 1).bit_length()))
    count_t = make_uint_t(capacity.bit_length())
    index_t = make_uint_t((2 * capacity).bit_length())
    tree_size = 1 << (capacity - 1).bit_length()

    @struct
    class powers_t(NamedTuple):
        values: uint130_t[capacity]

    @struct
    class epilogue_in_t(NamedTuple):
        accumulators: uint130_t[capacity]
        powers: powers_t
        lane_count: count_t
        next_lane: lane_t
        s: uint128_t

    @hw_func
    def prologue(r: uint130_t) -> powers_t:
        o: powers_t
        o.values[0] = r
        for k in range(2, capacity + 1):
            if wireguard_env.POLY1305_MULT_IMPL == "hybrid_square" and k % 2 == 0:
                o.values[k - 1] = residue_square_mod(o.values[k // 2 - 1])
            else:
                o.values[k - 1] = residue_mul_mod(
                    o.values[k // 2 - 1], o.values[(k + 1) // 2 - 1]
                )
        return o

    @hw_func
    def epilogue(x: epilogue_in_t) -> uint128_t:
        tree: uint130_t[2 * tree_size]
        for j in range(tree_size):
            tree[tree_size + j] = 0
        for j in range(capacity):
            weight: uint130_t = 0
            if j < x.lane_count:
                power_index: index_t = x.next_lane
                power_index += x.lane_count
                power_index -= 1 + j
                if x.next_lane > j:
                    power_index = x.next_lane - 1 - j
                # AUTO_FSM cannot regenerate a read at a hardware index.
                for k in range(capacity):
                    if power_index == k:
                        weight = x.powers.values[k]
            # Exactly one product per capacity slot, not one set per direction.
            tree[tree_size + j] = residue_mul_mod(x.accumulators[j], weight)
        for k in range(tree_size - 1, 0, -1):
            tree[k] = residue_add_mod(tree[2 * k], tree[2 * k + 1])
        low: uint128_t = tree[1]
        tag: uint128_t = low + x.s
        return tag

    return SimpleNamespace(
        prologue=prologue,
        epilogue=epilogue,
        powers_t=powers_t,
        epilogue_in_t=epilogue_in_t,
    )


def make_tagged_compute(func, input_t, output_t):
    @struct
    class tagged_in_t(NamedTuple):
        data: input_t
        is_encrypt: uint1_t

    @struct
    class tagged_out_t(NamedTuple):
        data: output_t
        is_encrypt: uint1_t

    @hw_func
    def tagged_compute(x: tagged_in_t) -> tagged_out_t:
        o: tagged_out_t
        o.data = func(x.data)
        o.is_encrypt = x.is_encrypt
        return o

    return tagged_compute
