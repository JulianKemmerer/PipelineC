# pyright: reportInvalidTypeForm=none
"""Native-sim testbench for the PDW pulse generator (pulse_gen.py).

Checks pulse_gen's output stream is always valid, holds amplitude for
exactly `TEST_WIDTH` cycles starting at the top of each period, is zero
the rest of the period, and repeats every `TEST_PRI` cycles -- using
sim_assert (elaborates to a real hardware assert, not a printed trace) as
the actual pass/fail mechanism.

Run:
    pypelinec examples/pypeline/dsp/pdw/pulse_gen/pulse_gen_tb.py --sim --comb --run 500
"""

from pypeline import MAIN, Reg, int16_t, sim_assert, sim_print, uint1_t, uint32_t

from pulse_gen import make_pulse_gen

TEST_PRI = 50
TEST_WIDTH = 12
TEST_AMPLITUDE = 1000

pulse_gen, out_stream_t = make_pulse_gen()


@MAIN(125.0)
def pulse_gen_tb():
    o = pulse_gen(TEST_PRI, TEST_WIDTH, TEST_AMPLITUDE)

    # Golden reference: independent free-running phase counter. Compute
    # expected_active from the *pre-update* phase value, mirroring
    # pulse_gen's own read-before-write order (pulse_active is derived from
    # pri_counter before it's incremented that same cycle).
    phase: Reg[uint32_t] = 0
    expected_active: uint1_t = phase < TEST_WIDTH
    exp_i: int16_t = TEST_AMPLITUDE if expected_active else 0

    if phase == (TEST_PRI - 1):
        phase = 0
    else:
        phase = phase + 1

    sim_print(f"phase={phase} i={o.data.i} q={o.data.q} valid={o.valid}")

    sim_assert(o.valid == 1, "pulse_gen output must always be valid")
    sim_assert(
        o.data.i == exp_i, f"phase={phase}: expected i={exp_i} got i={o.data.i}"
    )
    sim_assert(o.data.q == 0, f"phase={phase}: expected q=0 got q={o.data.q}")

    # Rising-edge period check, measured directly off the observed stream
    # (not the golden phase counter) to catch off-by-one boundary bugs.
    prev_active: Reg[uint1_t] = 0
    cycles_since_edge: Reg[uint32_t] = 0
    observed_active: uint1_t = o.data.i != 0

    rising_edge: uint1_t = observed_active & ~prev_active

    if rising_edge:
        # First rising edge (cycles_since_edge still at its reset value) has
        # no prior edge to measure a period against -- skip just that one.
        if cycles_since_edge != 0:
            sim_assert(
                cycles_since_edge == TEST_PRI,
                f"pulse period wrong: expected {TEST_PRI}, measured {cycles_since_edge}",
            )
        cycles_since_edge = 1
    else:
        cycles_since_edge = cycles_since_edge + 1

    # Every cycle (not just on edges): a stalled/dead generator -- no rising
    # edge ever again -- fails loudly here instead of a truncated run
    # silently "passing" by never reaching the mismatch above.
    sim_assert(
        cycles_since_edge <= TEST_PRI,
        f"pulse generator stalled: no rising edge within one PRI period (TEST_PRI={TEST_PRI})",
    )

    prev_active = observed_active
