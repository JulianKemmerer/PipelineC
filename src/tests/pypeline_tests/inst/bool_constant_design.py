"""A Python boolean parameter used as a hardware operand must emit a one-bit constant."""

from pypeline import *

# Vary the boolean value while retaining a runtime operand.
ENABLED = param("ENABLED", False)


@MAIN
def masked(signal_bit: uint1_t) -> uint1_t:
    return ENABLED & signal_bit
