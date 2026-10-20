"""Reduced-capacity unchanged Poly1305 fixture through native and GHDL.

Select KERNEL=prologue or epilogue; full-capacity manual runs use the QoR top.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qor", "poly1305"))
from self_check import self_check_poly1305_auto_fsm  # noqa: F401, E402
