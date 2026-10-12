# pyright: reportInvalidTypeForm=none
"""Fixture for latency_constant_entity_reuse_test.py: a top-level function whose
body folds a module-level value read from an AUTO_PIPELINE's .latency."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from pypeline import AUTO_PIPELINE, MAIN, hw_func, uint8_t  # noqa: E402


@hw_func
def core(x: uint8_t) -> uint8_t:
    return x * x


AP = AUTO_PIPELINE(core, name="core")
LAT = AP.latency


@hw_func
def folds_latency(x: uint8_t) -> uint8_t:
    # A top-level function's key is its module and name: the constant folded
    # from LAT is not part of it
    return (x + LAT) * x


@MAIN
def reuse_main(x: uint8_t) -> uint8_t:
    return folds_latency(AP(x))
