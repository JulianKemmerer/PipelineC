# pyright: reportInvalidTypeForm=none
"""Global wires used directly in the body of a pipelined function
(pypeline_guide.md, "Global wires in pipelined code").

A function with pipeline stages treats every global wire it touches like an
extra argument/return value: reads are sampled with its arguments, writes are
published with its return value. Native sim models exactly this case: it
evaluates the body at entry and publishes the writes with the delayed return.
The hardware is free to consume a read late or to compute a write early; its
alignment registers make the two sims agree anyway.

Each AUTO_PIPELINE(core, latency=2) below uses its own global wires in its own
body:
  read_late        a scalar read used only after the multiplier chain
  read_compound    two fields of one struct wire, one used early, one late
  read_separate    two separate wires, one used early, one late
  write_shallow    a wire written from the input while the return is deep
  write_partial    one field written late, the other left zero
  write_array      both elements of an array wire, one deep, one shallow
  write_split      a struct wire split between this pipeline (deep field)
                   and a combinational writer (the other field)
  readback         read own field before writing it (zero), write, rewrite,
                   read after the write
  readback_unused  reads only after its own writes. The readback input is
                   then trimmed away; its read in the VHDL prologue used to
                   name an undeclared variable.
  volatile_comb    a VOLATILE read and write through an unconstrained
                   AUTO_PIPELINE. Zero latency in --comb builds, so VOLATILE
                   and aligned timing coincide and native sim models it.

The stateful checker asserts every value against its counter, in both sims
independently. It also prints count-gated probes for the cycle diff
(native_vs_vhdl_sim_tests.py).
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    VOLATILE,
    NamedTuple,
    Reg,
    Wire,
    hw_func,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint16_t,
)

LAT = 2
START_CHECK = LAT + 2
END = 32


@struct
class pair_t(NamedTuple):
    a: uint16_t
    b: uint16_t


# Driven by the checker from its counter
g_late: Wire[uint16_t]
g_pair: Wire[pair_t]
g_early: Wire[uint16_t]
g_late2: Wire[uint16_t]
g_vol: Wire[uint16_t, VOLATILE]
# Written by the pipelines
w_shallow: Wire[pair_t]
w_partial: Wire[pair_t]
w_array: Wire[uint16_t[2]]
w_split: Wire[pair_t]
w_readback: Wire[pair_t]
w_unused: Wire[pair_t]
w_vol: Wire[uint16_t, VOLATILE]


@hw_func
def deep(x: uint16_t) -> uint16_t:
    # Constant multiplier chain the fixed latency slices: x * 105
    y: uint16_t = x * 3
    z: uint16_t = y * 5
    return z * 7


@hw_func
def read_late(x: uint16_t) -> uint16_t:
    return deep(x) + g_late


@hw_func
def read_compound(x: uint16_t) -> uint16_t:
    return deep(x + g_pair.a) + g_pair.b


@hw_func
def read_separate(x: uint16_t) -> uint16_t:
    return deep(x + g_early) + g_late2


@hw_func
def write_shallow(x: uint16_t) -> uint16_t:
    w_shallow.a = x
    w_shallow.b = x + 1
    return deep(x)


@hw_func
def write_partial(x: uint16_t) -> uint16_t:
    q: uint16_t = deep(x)
    w_partial.a = q
    return q


@hw_func
def write_array(x: uint16_t) -> uint16_t:
    q: uint16_t = deep(x)
    w_array[0] = q
    w_array[1] = x
    return q


@hw_func
def write_split(x: uint16_t) -> uint16_t:
    q: uint16_t = deep(x)
    w_split.a = q
    return q


@hw_func
def split_other(x: uint16_t) -> uint16_t:
    w_split.b = x
    return x


@hw_func
def readback(x: uint16_t) -> uint16_t:
    prior: uint16_t = w_readback.a  # own field before this call writes it: zero
    w_readback.a = x
    w_readback.a = deep(x)
    w_readback.b = w_readback.a + 1
    return w_readback.a + prior


@hw_func
def readback_unused(x: uint16_t) -> uint16_t:
    w_unused.a = x
    w_unused.a = deep(x)
    w_unused.b = w_unused.a + 1
    return w_unused.a


@hw_func
def volatile_comb(x: uint16_t) -> uint16_t:
    w_vol = x + 1
    return x + g_vol


AP_READ_LATE = AUTO_PIPELINE(read_late, latency=LAT)
AP_READ_COMPOUND = AUTO_PIPELINE(read_compound, latency=LAT)
AP_READ_SEPARATE = AUTO_PIPELINE(read_separate, latency=LAT)
AP_WRITE_SHALLOW = AUTO_PIPELINE(write_shallow, latency=LAT)
AP_WRITE_PARTIAL = AUTO_PIPELINE(write_partial, latency=LAT)
AP_WRITE_ARRAY = AUTO_PIPELINE(write_array, latency=LAT)
AP_WRITE_SPLIT = AUTO_PIPELINE(write_split, latency=LAT)
AP_READBACK = AUTO_PIPELINE(readback, latency=LAT)
AP_READBACK_UNUSED = AUTO_PIPELINE(readback_unused, latency=LAT)
AP_VOLATILE_COMB = AUTO_PIPELINE(volatile_comb)


@MAIN
def global_wire_pipeline_aligned_checker() -> uint16_t:
    count: Reg[uint16_t]
    t: uint16_t = count - LAT  # the transaction the pipelines publish this cycle
    deep_t: uint16_t = t * 105

    g_late = count + 100
    g_pair.a = count + 200
    g_pair.b = count + 300
    g_early = count + 400
    g_late2 = count + 500
    g_vol = count + 600

    r_late: uint16_t = AP_READ_LATE(count)
    r_compound: uint16_t = AP_READ_COMPOUND(count)
    r_separate: uint16_t = AP_READ_SEPARATE(count)
    r_shallow: uint16_t = AP_WRITE_SHALLOW(count)
    r_partial: uint16_t = AP_WRITE_PARTIAL(count)
    r_array: uint16_t = AP_WRITE_ARRAY(count)
    r_split: uint16_t = AP_WRITE_SPLIT(count)
    r_readback: uint16_t = AP_READBACK(count)
    r_unused: uint16_t = AP_READBACK_UNUSED(count)
    r_vol: uint16_t = AP_VOLATILE_COMB(count)
    other: uint16_t = split_other(count)

    if (count >= START_CHECK) & (count < END):
        # Reads sampled with the arguments, at the transaction's entry
        sim_assert(r_late == deep_t + t + 100, f"read_late {r_late}")
        sim_assert(
            r_compound == (t + t + 200) * 105 + t + 300, f"read_compound {r_compound}"
        )
        sim_assert(
            r_separate == (t + t + 400) * 105 + t + 500, f"read_separate {r_separate}"
        )
        # Writes published with the return value
        sim_assert(r_shallow == deep_t, f"write_shallow return {r_shallow}")
        sim_assert(
            (w_shallow.a == t) & (w_shallow.b == t + 1),
            f"w_shallow {w_shallow.a} {w_shallow.b}",
        )
        sim_assert(
            (w_partial.a == deep_t) & (w_partial.b == 0),
            f"w_partial {w_partial.a} {w_partial.b}",
        )
        sim_assert(
            (w_array[0] == deep_t) & (w_array[1] == t),
            f"w_array {w_array[0]} {w_array[1]}",
        )
        # Each writer of a split wire keeps its own timing
        sim_assert(
            (w_split.a == deep_t) & (w_split.b == count),
            f"w_split {w_split.a} {w_split.b}",
        )
        sim_assert(r_readback == deep_t, f"readback return {r_readback}")
        sim_assert(
            (w_readback.a == deep_t) & (w_readback.b == deep_t + 1),
            f"w_readback {w_readback.a} {w_readback.b}",
        )
        sim_assert(
            (r_unused == deep_t) & (w_unused.a == deep_t) & (w_unused.b == deep_t + 1),
            f"readback_unused {r_unused} {w_unused.a} {w_unused.b}",
        )
        sim_assert(
            (r_vol == count + count + 600) & (w_vol == count + 1),
            f"volatile_comb {r_vol} {w_vol}",
        )
        sim_print(
            f"count={count} reads={r_late},{r_compound},{r_separate} "
            f"returns={r_shallow},{r_partial},{r_array},{r_split},{r_readback},{r_unused},{r_vol} "
            f"w_shallow={w_shallow.a},{w_shallow.b} w_partial={w_partial.a},{w_partial.b} "
            f"w_array={w_array[0]},{w_array[1]} w_split={w_split.a},{w_split.b} "
            f"w_readback={w_readback.a},{w_readback.b} "
            f"w_unused={w_unused.a},{w_unused.b} w_vol={w_vol}",
            debug=True,
        )
    if count == END:
        sim_finish()
    count += 1
    return other
