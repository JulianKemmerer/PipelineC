"""Small hardware body for the isolated-wrapper naming reproducer."""

from pypeline import MAIN, uint8_t


@MAIN(25.0)
def leaf(x: uint8_t) -> uint8_t:
    return x + 1
