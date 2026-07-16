# pyright: reportInvalidTypeForm=none
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
from pypeline import MAIN, uint1_t, uint32_t, sim_call, sim_reset

from fifo import make_fifo

# depth=5 rounds up to the real hardware's capacity of 8 (2**ceil(log2(5))) --
# small on purpose, so fill/drain tests are fast and readable.
fifo_fwft, fifo_fwft_t = make_fifo(uint32_t, 5)
CAPACITY = 8


@MAIN
def fifo_test_top(
    ready_for_data_out: uint1_t, data_in: uint32_t, data_in_valid: uint1_t
) -> fifo_fwft_t:
    return fifo_fwft(ready_for_data_out, data_in, data_in_valid)


def test_fifo_empty_behavior():
    sim_reset()
    r = sim_call(fifo_test_top, 0, 0, 0)
    assert int(r.data_out_valid) == 0
    assert int(r.data_in_ready) == 1


def test_fifo_fwft_order():
    sim_reset()
    values = [10, 20, 30]
    for v in values:
        sim_call(fifo_test_top, 0, v, 1)
    popped = []
    for _ in range(len(values)):
        r = sim_call(fifo_test_top, 1, 0, 0)
        assert int(r.data_out_valid) == 1
        popped.append(int(r.data_out))
    assert popped == values, f"expected FWFT order {values}, got {popped}"


def test_fifo_backpressure_at_capacity():
    sim_reset()
    # The real FIFO's addressed memory holds CAPACITY words (what data_in_ready
    # backpressures against, see make_fifo's `capacity` calc), but the FWFT
    # read side adds one more word of storage in its output register (see
    # _FifoFwftModel / pipelinec_fifo_fwft.vhd's data_out_pipe_reg) that isn't
    # counted by that capacity check. So with no pops at all, CAPACITY + 1
    # pushes are accepted before backpressure kicks in.
    values = list(range(100, 100 + CAPACITY + 1))
    for v in values:
        r = sim_call(fifo_test_top, 0, v, 1)
        assert int(r.data_in_ready) == 1, "must accept up to capacity + 1 output reg"
    # A push attempt while full must be dropped, not corrupt existing state.
    r = sim_call(fifo_test_top, 0, 999, 1)
    assert int(r.data_in_ready) == 0, "must backpressure once full"
    popped = []
    for _ in range(len(values)):
        r = sim_call(fifo_test_top, 1, 0, 0)
        assert int(r.data_out_valid) == 1
        popped.append(int(r.data_out))
    assert popped == values, "overflowed push must not appear/corrupt the queue"
    r = sim_call(fifo_test_top, 0, 0, 0)
    assert int(r.data_out_valid) == 0, "must be empty after full drain"


def test_fifo_simultaneous_push_pop():
    sim_reset()
    a, b = 111, 222
    sim_call(fifo_test_top, 0, a, 1)  # seed one item (still in mem, not yet
    # loaded into the FWFT output register -- see _FifoFwftModel's extra
    # register stage)
    sim_call(fifo_test_top, 0, 0, 0)  # idle: lets a move into the output register
    r = sim_call(fifo_test_top, 0, 0, 0)  # confirm visible without popping
    assert int(r.data_out_valid) == 1
    assert int(r.data_out) == a
    # Simultaneous pop (of a) and push (of b) in the same cycle.
    r = sim_call(fifo_test_top, 1, b, 1)
    assert int(r.data_out_valid) == 1
    assert int(r.data_out) == a, "same-cycle push must not be same-cycle poppable"
    assert int(r.data_in_ready) == 1
    # b was only pushed into mem this same cycle, so the output register empties
    # for one cycle (nothing was queued yet to reload it from) before it can
    # load b -- two idle cycles are needed: one for b to land in mem, one more
    # for the output register to pick it up.
    r = sim_call(fifo_test_top, 0, 0, 0)
    assert int(r.data_out_valid) == 0
    r = sim_call(fifo_test_top, 0, 0, 0)
    assert int(r.data_out_valid) == 1
    assert int(r.data_out) == b, "b must become visible once it reaches the output reg"


def test_fifo_reference_model_soak():
    """Drive a scripted mix of idle/push/pop/simultaneous/full/empty phases,
    checking every cycle against an independent plain-Python reference model
    (not the implementation's own _FifoFwftModel). The reference is built as
    a bounded list "mem" plus a separate one-word output register, mirroring
    pipelinec_fifo_fwft.vhd's mem + data_out_pipe_reg/valid_out_pipe_reg
    structure -- CAPACITY words fit in mem, plus 1 more in the output
    register, so up to CAPACITY + 1 words can be buffered with no pops."""
    sim_reset()
    ref_mem = []  # bounded to CAPACITY; index 0 = oldest
    ref_out_valid = [0]
    ref_out_data = [None]
    next_val = [0]

    def step(do_push, do_pop):
        exp_valid = ref_out_valid[0]
        exp_out = ref_out_data[0] if exp_valid else None
        exp_ready = 1 if len(ref_mem) < CAPACITY else 0
        data_in = 0
        if do_push:
            next_val[0] += 1
            data_in = next_val[0]
        r = sim_call(fifo_test_top, 1 if do_pop else 0, data_in, 1 if do_push else 0)
        assert int(r.data_out_valid) == exp_valid
        if exp_valid:
            assert int(r.data_out) == exp_out
        assert int(r.data_in_ready) == exp_ready

        # Advance the reference model's registers for the next cycle, in the
        # same order as the real read process: reload the output register
        # whenever it's consumed or currently empty, then apply the push.
        consume = bool(do_pop) or not ref_out_valid[0]
        if consume:
            if ref_mem:
                ref_out_data[0] = ref_mem.pop(0)
                ref_out_valid[0] = 1
            else:
                ref_out_valid[0] = 0
        if do_push and exp_ready:
            ref_mem.append(data_in)

    step(False, False)  # idle
    for _ in range(CAPACITY + 1):  # fill to capacity + 1 (mem + output reg)
        step(True, False)
    step(True, True)  # push attempt while full, simultaneous with a pop
    step(True, False)  # push into the slot just freed
    step(False, True)
    for _ in range(CAPACITY + 3):  # drain to empty and past it
        step(False, True)
    pattern = [
        (True, False),
        (True, True),
        (False, True),
        (True, False),
        (False, False),
        (True, True),
        (False, True),
        (False, True),
    ]
    for do_push, do_pop in pattern:
        step(do_push, do_pop)


if __name__ == "__main__":
    test_fifo_empty_behavior()
    test_fifo_fwft_order()
    test_fifo_backpressure_at_capacity()
    test_fifo_simultaneous_push_pop()
    test_fifo_reference_model_soak()
    print("OK: fifo(...) simulation model behaves correctly")
