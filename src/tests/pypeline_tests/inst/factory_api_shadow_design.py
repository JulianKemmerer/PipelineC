"""A hardware input shadows a Python operation bundle with the same name."""

from types import SimpleNamespace

from pypeline import MAIN, hw_func, uint8_t


@hw_func
def increment(x: uint8_t) -> uint8_t:
    return x + 1


# The input named ops below must hide this Python-global bundle.
ops = SimpleNamespace(add=increment)


@MAIN
def shadowed_bundle(ops: uint8_t) -> uint8_t:
    return ops.add(ops)
