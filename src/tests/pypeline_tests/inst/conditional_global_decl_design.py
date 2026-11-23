# pyright: reportInvalidTypeForm=none
"""Known-issue fixture: an Output[T] declared inside a module-level `if` that
ran. The build makes no `led` port and drops the @MAIN's write to it, with no
error. See conditional_global_decl_test.py.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Output, uint1_t

USE_LED = True  # always taken: the declaration below runs
if USE_LED:
    led: Output[uint1_t]


@MAIN
def top():
    led = 1
