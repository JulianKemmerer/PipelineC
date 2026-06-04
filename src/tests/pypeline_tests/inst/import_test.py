# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN

import file_a
import file_b


@MAIN
def a_b_connect():
    file_b.i = file_a.o
    file_a.i = file_b.o
