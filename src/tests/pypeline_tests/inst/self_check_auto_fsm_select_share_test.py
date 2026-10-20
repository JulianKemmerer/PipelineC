"""Indexed compound reads, exclusive selection and arithmetic sharing in GHDL.

Independent host formulas include unsigned overflow, narrow/wide products and
fused add/selection groups and multiply/add pair emission. Four FSMs may have different schedules; each result
is checked before the next vector launches.
"""

from pypeline import (
    AUTO_FSM,
    INFERRED,
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    register_operator,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint2_t,
    uint4_t,
    make_uint_t,
    uint16_t,
    uint17_t,
    uint32_t,
    uint34_t,
)
from operators.soft_mult import make_inferred_mult

import AUTO
import AUTO_FSM as fsm_compiler
import LOGIC

# The fused selector keeps a wide intermediate before a narrow assignment.
uint130_t = make_uint_t(130)


@struct
class cell_t(NamedTuple):
    lo: uint16_t
    values: uint16_t[2]


@struct
class input_t(NamedTuple):
    a: uint16_t
    b: uint16_t
    c: uint17_t
    d: uint17_t
    bias: uint32_t
    idx: uint4_t
    cells: cell_t[4]
    matrix: uint16_t[2][4]


# These original scoped leaves remain the authority for multiplication.
multiply16 = make_inferred_mult(uint16_t, uint16_t)
multiply17 = make_inferred_mult(uint17_t, uint17_t)


def make_test_fused_pair():
    """Exercise the production pair emitter even when area search declines fusion."""
    parser = LOGIC.ParserState()
    parser.pypeline_builtin_op_info = {
        "product": ("INFERRED_MULT", ("uint16_t", "uint16_t")),
        "sum": ("PLUS", ("uint32_t", "uint32_t")),
    }
    producer = dict(
        kind="binop",
        op=dict(kind="binop", op="*"),
        entity="product",
        operands=[["in", "a"], ["in", "b"]],
        casts=[[], []],
        port_types=["uint16_t", "uint16_t"],
        out_type="uint32_t",
        delay_du=1,
    )
    consumer = dict(
        kind="binop",
        op=dict(kind="binop", op="+"),
        entity="sum",
        operands=[["node", "product"], ["in", "bias"]],
        casts=[[], []],
        port_types=["uint32_t", "uint32_t"],
        out_type="uint33_t",
        delay_du=1,
    )
    key = AUTO.fingerprint((producer, consumer, 0))
    return fsm_compiler._pair_function(
        key, producer, consumer, 0, parser, AUTO._TypeResolver()
    )


# No test-only compiler policy or area threshold: this checks the pair emitter
# directly, while recurring_pairs below separately exercises automatic search.
FUSED_PAIR = make_test_fused_pair()


@hw_func
def indexed_selection(x: input_t) -> uint32_t:
    index: uint2_t = x.idx
    half: uint1_t = x.idx
    row: uint16_t[4] = x.matrix[half]
    item: cell_t = x.cells[index]
    values: uint16_t[2] = item.values
    base: uint32_t = row[index] + values[half]
    selected: uint16_t = 12345
    for k in range(4):
        if x.idx == k:
            selected = x.cells[k].lo
    return base + selected


@hw_func
def width_sharing(x: input_t) -> uint34_t:
    narrow: uint32_t = multiply16(x.a, x.b)
    wide: uint34_t = multiply17(x.c, x.d)
    return narrow + wide


@hw_func
def recurring_pairs(x: input_t) -> uint32_t:
    total: uint2_t = x.a
    increment: uint2_t = x.b
    for k in range(4):
        added: uint2_t = total + increment
        selected: uint130_t = (1 << 129) + 17
        if (x.idx >> k) & 1:
            selected = added
        low: uint2_t = selected
        total = low + increment
    return total


# Keep the written two-bit arithmetic leaves, as for the scoped multipliers.
register_operator("PLUS", uint2_t, uint2_t, INFERRED, scope=recurring_pairs)


@hw_func
def emitted_pair(x: input_t) -> uint32_t:
    narrowed: uint32_t = FUSED_PAIR(x.a, x.b, x.bias)
    return narrowed


# Pure Python vectors cover every equality case and its out-of-range default.
CASES = tuple(
    input_t(
        a=(0, 1, 65535, 32768, 255, 65534, 511, 65535)[seed],
        b=(65535, 2, 65535, 32767, 256, 17, 7, 0)[seed],
        c=(131071 - seed * 997),
        d=(131071 if seed % 2 else seed * 511),
        bias=0xFFFFFFFF if seed % 2 else seed * 1234567,
        idx=(0, 1, 2, 3, 8, 9, 14, 15)[seed],
        cells=tuple(
            cell_t(
                (seed * 997 + j * 337) & 65535,
                ((seed + j * 17) & 65535, (65535 - seed - j * 41) & 65535),
            )
            for j in range(4)
        ),
        matrix=tuple(
            tuple((seed * 331 + i * 101 + j * 17) & 65535 for j in range(4))
            for i in range(2)
        ),
    )
    for seed in range(8)
)
# Golden expressions apply each original assignment's modular width.
SELECT_EXPECTED = tuple(
    x.matrix[x.idx & 1][x.idx & 3]
    + x.cells[x.idx & 3].values[x.idx & 1]
    + (x.cells[x.idx].lo if x.idx < 4 else 12345)
    for x in CASES
)
MERGE_EXPECTED = tuple((x.a * x.b + x.c * x.d) & ((1 << 34) - 1) for x in CASES)


def fused_expected(x):
    total = x.a & 3
    increment = x.b & 3
    for k in range(4):
        selected = ((total + increment) & 3) if (x.idx >> k) & 1 else (1 << 129) + 17
        total = ((selected & 3) + increment) & 3
    return total


# The formula models every narrow assignment independently of the emitted pair.
FUSE_EXPECTED = tuple(fused_expected(x) for x in CASES)
PAIR_EXPECTED = tuple((x.a * x.b + x.bias) & 0xFFFFFFFF for x in CASES)
# Independent call sites permit different latency and sharing decisions.
SELECT = AUTO_FSM(indexed_selection)
MERGE = AUTO_FSM(width_sharing)
FUSE = AUTO_FSM(recurring_pairs)
PAIR = AUTO_FSM(emitted_pair)

# A scheduled pass must exercise the transformations, not just their input math.
if SELECT.schedule is not None:
    assert SELECT.schedule["cleanup"]["balanced_selections"] > 0
if MERGE.schedule is not None:
    assert MERGE.schedule["cleanup"]["width_adapters"] > 0
if FUSE.schedule is not None:
    assert FUSE.schedule["cleanup"]["fused_pairs"] > 0


@MAIN(5.0)
def self_check_auto_fsm_select_share() -> uint32_t:
    index: Reg[uint4_t]
    busy: Reg[uint1_t]
    done: Reg[uint4_t]
    result: Reg[uint32_t]
    cases: input_t[8] = CASES
    selected: uint32_t[8] = SELECT_EXPECTED
    merged: uint34_t[8] = MERGE_EXPECTED
    fused: uint32_t[8] = FUSE_EXPECTED
    pair_values: uint32_t[8] = PAIR_EXPECTED
    launch: uint1_t = ~busy
    if launch:
        done = 0
        busy = 1
    s: SELECT.in_stream_t
    s.data = cases[index]
    s.valid = launch
    m: MERGE.in_stream_t
    m.data = cases[index]
    m.valid = launch
    f: FUSE.in_stream_t
    f.data = cases[index]
    f.valid = launch
    p: PAIR.in_stream_t
    p.data = cases[index]
    p.valid = launch
    a = SELECT(s)
    b = MERGE(m)
    c = FUSE(f)
    d = PAIR(p)
    if a.valid:
        sim_assert(
            a.data == selected[index],
            "indexed compound/array read or default selection",
        )
        done |= 1
    if b.valid:
        sim_assert(
            b.data == merged[index], "unsigned width sharing and result truncation"
        )
        done |= 2
    if c.valid:
        sim_assert(c.data == fused[index], "fused add/selection preserves truncation")
        result = c.data
        done |= 4
    if d.valid:
        sim_assert(
            d.data == pair_values[index],
            "emitted fused pair restores output truncation",
        )
        done |= 8
    if done == 15:
        if index == 7:
            sim_finish()
        else:
            sim_print(f"select/share case={index} passed", debug=True)
        index += 1
        busy = 0
    return result
