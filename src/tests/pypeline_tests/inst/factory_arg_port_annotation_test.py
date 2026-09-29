# pyright: reportInvalidTypeForm=none
"""Port annotations that reach a type through a factory argument (`p: src.pair_t`).

Python evaluates a parameter or return annotation once, at def time, in the
enclosing scope, so a factory argument used only there (`pair_src`, `src`
below) never becomes a closure cell of the inner function. PY_TO_LOGIC used
to re-evaluate the annotation's AST during elaboration, where that name is
out of scope:

- `rom_consumer`'s `pair_src` resolved nowhere. The fallback typed the port
  with the bare attribute name 'pair_t' instead of the struct's canonical
  name, and the first field read raised `KeyError: 'pair_t'`. This hit
  pypelinec builds, and plain `sim_call` too: the ROM is a @pipeline_latency
  callee, so sim_call elaborates the caller (ELABORATE_LIVE_ROOTS) for
  alignment.
- `sum_consumer`'s `src` resolved to the unrelated module global `src` below.
  The port silently took that producer's uint16_t-field record while its
  caller drove the uint8_t-field one, which GHDL rejects at the port map.
- `diff_consumer`'s `hw_return_type(pair_src)` also resolved nowhere, and a
  call has no static fallback: NotImplementedError("Unsupported type
  annotation").

Ports now take the function's own resolved __annotations__. Registered in
native_sim (test_* below: the sim_call path) and native_vs_vhdl_sim --comb
(the MAIN: the pypelinec path, with GHDL checking the port types).
"""
import os
import sys

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
from pypeline import (
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    hw_return_type,
    sim_assert,
    sim_call,
    sim_finish,
    sim_print,
    sim_reset,
    struct,
    uint1_t,
    uint4_t,
    uint8_t,
    uint16_t,
)
from ram import make_ram


def make_producer(b_t):
    # pair_t exists only inside this factory; callers reach it as an attribute
    # of the returned function (like PDW's pulse_detect.freq_accum_t).
    @struct
    class pair_t(NamedTuple):
        a: uint4_t
        b: b_t

    @hw_func
    def producer(x: uint4_t) -> pair_t:
        o: pair_t
        o.a = x
        o.b = 100
        return o

    producer.pair_t = pair_t
    return producer


def make_rom_consumer(pair_src):
    rom, _rom_t = make_ram(
        uint8_t, 16, ports=("r",), read_latency=1, init=list(range(16))
    )

    @hw_func
    def rom_consumer(p: pair_src.pair_t) -> uint8_t:
        # Stateful, so the ROM's rd_data is its physical output: the data for
        # the previous cycle's address.
        held: Reg[uint8_t]
        res: uint8_t = held
        r = rom(rom.p0_in_t(addr=p.a, valid=1))
        held = r.p0.rd_data + p.b
        return res

    return rom_consumer


def make_sum_consumer(src):
    @hw_func
    def sum_consumer(p: src.pair_t) -> uint16_t:
        return p.a + p.b

    return sum_consumer


def make_diff_consumer(pair_src):
    @hw_func
    def diff_consumer(p: hw_return_type(pair_src)) -> uint8_t:
        return p.b - p.a

    return diff_consumer


narrow = make_producer(uint8_t)
# Unrelated global sharing make_sum_consumer's parameter name, with a
# different pair_t (uint16_t b field).
src = make_producer(uint16_t)
rom_consumer = make_rom_consumer(narrow)
sum_consumer = make_sum_consumer(narrow)
diff_consumer = make_diff_consumer(narrow)


@MAIN
def factory_arg_port_annotation_test() -> uint16_t:
    c: Reg[uint4_t]
    done: Reg[uint1_t]
    pair = narrow(c)
    summed: uint16_t = sum_consumer(pair)
    diffed: uint8_t = diff_consumer(pair)
    # Two cycles behind: one in the ROM, one in rom_consumer's own register.
    rom_summed: uint8_t = rom_consumer(pair)
    if done:
        sim_finish()  # no debug print on this cycle
    elif c >= 2:
        sim_assert(summed == c + 100, "sum_consumer through src.pair_t")
        sim_assert(diffed == 100 - c, "diff_consumer through hw_return_type")
        sim_assert(rom_summed == c + 98, "rom_consumer through pair_src.pair_t")
        sim_print(
            f"c={c} summed={summed} diffed={diffed} rom_summed={rom_summed}",
            debug=True,
        )
    if c == 11:
        done = 1
    c = c + 1
    return summed


def test_sim_call_through_rom():
    sim_reset()
    got = [
        int(sim_call(rom_consumer, narrow.pair_t(a=v, b=100))) for v in (1, 2, 3, 4)
    ]
    assert got == [0, 100, 101, 102], got


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
