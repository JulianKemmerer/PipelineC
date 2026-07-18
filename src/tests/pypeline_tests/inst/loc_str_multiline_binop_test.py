import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, uint8_t

# Regression test for the _loc_str() multiline-instance-collision bug:
# a left-associative chain of BinOp nodes spanning multiple lines gets the
# same lineno/col_offset (leftmost operand) for every nested node, and
# _loc_str used to key instance names only on end_col_offset -- which can
# coincidentally collide across nodes that end on different lines whenever
# their trailing operands have equal textual width. That collapsed distinct
# instances to the same name and _add_submodule_instance raised
# "Duplicate submodule instance name". Operand names below are all 2 chars
# wide (aa/bb/cc/dd/ee), so every nested BinOp node's end_col_offset is
# identical even though each ends on a different source line -- only
# node.end_lineno tells them apart. See global_wire_nested_split_test.py
# for the original failure this was extracted from.


@MAIN
def combiner(
    aa: uint8_t, bb: uint8_t, cc: uint8_t, dd: uint8_t, ee: uint8_t
) -> uint8_t:
    return aa ^ bb ^ cc ^ dd ^ ee


def test_multiline_binop_chain_elaborates_without_duplicate_instance_error():
    import tempfile
    import PY_TO_LOGIC
    import SYN

    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="loc_str_multiline_binop_test_")

    PY_TO_LOGIC.PARSE_FILE(os.path.abspath(__file__))
    print("test_multiline_binop_chain_elaborates_without_duplicate_instance_error PASS")


if __name__ == "__main__":
    test_multiline_binop_chain_elaborates_without_duplicate_instance_error()
    print("All loc_str_multiline_binop tests passed.")
