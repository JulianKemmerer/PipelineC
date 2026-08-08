# pyright: reportInvalidTypeForm=none
"""Fixture for sim_finish_debug_print_race_test.py: breaks the "no debug
print on the sim_finish() cycle" rule on purpose. See that file's docstring.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, sim_finish, sim_print


@MAIN
def sim_finish_debug_print_race():
    # Breaking the rule on purpose: this debug print fires the SAME cycle as
    # sim_finish() below.
    sim_print("about to finish", debug=True)
    sim_finish()
