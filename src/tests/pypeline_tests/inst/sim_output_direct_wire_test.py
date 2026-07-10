# pyright: reportInvalidTypeForm=none
"""Direct-read-by-bare-name test for @sim_output + Wire[T]/Output[T]: proves a
@sim_output function can reference a global wire directly inside its own body
(not merely receive it as a passed-in argument, the only pattern used by every
pre-existing @sim_output usage in this repo), including when called from a
nested non-MAIN helper rather than straight from a @MAIN body. Run only via
the multi-MAIN runner (pypeline_sim.py sim_output_direct_wire_test.py --run N).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, Wire, sim_output, uint32_t

out0: Wire[uint32_t]


@MAIN
def driver():
    r: Reg[uint32_t]
    out0 = r
    r = r + 1


# Mutable single-element container, not a Wire -- deliberately not read/written
# via a rebound module-level name, since @sim_output's rewritten body runs
# against a detached snapshot of this module's globals (see pypeline_sim_DESIGN.md);
# in-place mutation of an already-existing object is unaffected by that snapshot.
_expected = [0]


@sim_output
def check_direct_read():
    # Bare-name read of a global Wire[T] from inside @sim_output's own body --
    # not passed in as an argument, unlike every pre-existing @sim_output usage.
    v = int(out0)
    assert (
        v == _expected[0]
    ), f"direct wire read stale/wrong: got {v}, expected {_expected[0]}"
    _expected[0] += 1


def _nested_helper():
    # Plain (non-hw_func, non-MAIN) Python helper -- proves the direct-wire-read
    # capability works no matter where in the design the call happens, not just
    # called straight from a @MAIN body.
    check_direct_read()


@MAIN
def checker_main():
    _nested_helper()
