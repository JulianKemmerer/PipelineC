# pyright: reportInvalidTypeForm=none
"""Build fixture for region_root_minisweep_test.py: an AUTO_PIPELINE region
whose root is an imported function, tagged directly (#387). The root's call
is labeled with its bare name (`chain`) while its function is
region_root_minisweep_chain_chain, and nothing inside it matches by name
(region_root_minisweep_math.py), so the sweep finds the critical path in the
root only by the root instance's label path, and must mini-sweep the root
itself.

-D REGION_ROOT_WRAPPER=1 tags the one-line wrapper chain_wrapper instead, the
old workaround: the sweep then finds and mini-sweeps `chain` inside it, whose
same-module call is labeled with its module-prefixed name. Both must reach
the same depth."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pypeline import AUTO_PIPELINE, MAIN, Reg, param, uint1_t  # noqa: E402

from region_root_minisweep_chain import chain, chain_wrapper  # noqa: E402
from region_root_minisweep_math import st4_t  # noqa: E402

CHAIN_AP = AUTO_PIPELINE(
    chain_wrapper if param("REGION_ROOT_WRAPPER", 0, type=int) else chain
)


# Reset-free on purpose (docs/pypeline_TESTS.md#reset-coverage): the whole
# chain's lock holds thousands of registers, and a reset pin's fanout to them
# would be the critical path, not the arithmetic the mini-sweep measures.
@MAIN(param("REGION_ROOT_GOAL", 120.0, type=float))
def region_root_main(s: st4_t) -> st4_t:
    # State makes the main itself unsliceable: only the tagged call site
    # takes registers
    toggle: Reg[uint1_t]
    toggle = ~toggle
    return CHAIN_AP(s)
