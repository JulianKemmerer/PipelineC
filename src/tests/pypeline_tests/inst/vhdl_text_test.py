# pyright: reportInvalidTypeForm=none
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import (
    MAIN,
    uint64_t,
    vhdl,
    sim_call,
)


@MAIN
def vhdl_text_add(x: uint64_t, y: uint64_t) -> uint64_t:
    vhdl(
        """
        begin
        return_output <= x + y;
        """
    )


def test_vhdl_text_sim_raises():
    try:
        sim_call(vhdl_text_add, 1, 2)
    except NotImplementedError:
        return
    raise AssertionError("expected NotImplementedError from vhdl(...) simulation")


if __name__ == "__main__":
    test_vhdl_text_sim_raises()
    print("OK: vhdl(...) simulation correctly raises NotImplementedError")
