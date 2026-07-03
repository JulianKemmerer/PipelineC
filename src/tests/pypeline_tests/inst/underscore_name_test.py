# pyright: reportInvalidTypeForm=none
"""Regression test for leading-underscore Python names producing illegal VHDL
identifiers. PY_TO_LOGIC's identifier mangling (_sanitize_vhdl_name) covered
illegal *variable* names (e.g. 'block' -> 'block_v') but not callee-derived
instance names or VHDL entity names.

A module-level Python-private-style alias to a hardware function
(`_round_alias = round_a`) elaborated fine, but the call-site instance/signal
names embedded the alias verbatim, producing VHDL like
`signal _round_alias[...]____CLOCK_ENABLE` -- illegal (identifiers can't start
with '_'). A top-level function literally named with a leading underscore
(`_helper`) hit the same gap on the VHDL entity name itself. Run through real
synthesis (not just elaboration) since that's what actually parses/rejects
the generated VHDL text -- an in-process FuncLogicLookupTable inspection
would only prove the compiler's own bookkeeping is underscore-free, not that
the emitted VHDL is legal.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, hw_func, uint32_t


@hw_func
def round_a(x: uint32_t) -> uint32_t:
    return x + 1


@hw_func
def _helper(x: uint32_t) -> uint32_t:
    return x + 2


_round_alias = round_a


@MAIN
def underscore_name_main(x: uint32_t) -> uint32_t:
    return _helper(_round_alias(x))
