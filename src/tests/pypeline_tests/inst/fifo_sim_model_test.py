# pyright: reportInvalidTypeForm=none
"""Wire-convergence stress test for make_fifo's _FifoFwftModel: run only via
the multi-MAIN runner (pypeline_sim.py fifo_sim_model_test.py --run N). Not a
plain-python3 test (no __main__ block) and not elaborated/synthesized by
pypelinec -- mirrors global_wires_sim_test.py's structure/registration.
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
from pypeline import MAIN, Reg, Wire, sim_output, uint1_t, uint32_t

from fifo import make_fifo

CAPACITY = 8  # already a power of two, no rounding ambiguity
fifo_conv, fifo_conv_t = make_fifo(uint32_t, CAPACITY)

push_in: Wire[uint32_t]
fifo_ready: Wire[uint1_t]


# Registered (and thus queued) before driver_main, so each cycle it first
# evaluates the model against the stale push_in from the previous cycle, then
# gets re-queued once driver_main advances the wire later the same cycle --
# the same re-evaluation stress sim_model_test.py's accum_main uses to prove
# no double-mutation, applied here to the FIFO's deque state.
@MAIN
def fifo_conv_main():
    r = fifo_conv(0, push_in, 1)  # never pop; always attempt to push
    fifo_ready = r.data_in_ready


@MAIN
def driver_main():
    count: Reg[uint32_t]
    push_in = count
    count = count + 1


@sim_output
def check_fifo_ready(cycle, ready):
    # CAPACITY words fit in the addressed memory that data_in_ready
    # backpressures against, plus one more word fits in the FWFT output
    # register (see _FifoFwftModel's extra register stage / fifo_test.py's
    # test_fifo_backpressure_at_capacity) -- with no pops, CAPACITY + 1
    # pushes are accepted before ready deasserts.
    expected = 1 if int(cycle) < CAPACITY + 1 else 0
    assert int(ready) == expected, (
        f"cycle {int(cycle)}: fifo_ready={int(ready)} expected={expected} "
        f"(sim model pushed more than once per cycle?)"
    )


@MAIN
def checker_main():
    n: Reg[uint32_t]
    check_fifo_ready(n, fifo_ready)
    n = n + 1
