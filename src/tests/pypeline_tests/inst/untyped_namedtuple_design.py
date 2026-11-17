"""Issue #394: host-only namedtuples must not become empty hardware records."""

import collections
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "../../../../include/pypeline")
)

from pypeline import MAIN, NamedTuple, struct, uint8_t
from stream import stream_perf

# Python 3.10+ supplies an empty annotations dict even for an untyped class.
UntypedPair = collections.namedtuple("UntypedPair", ("slope", "intercept"))
UntypedPair.__annotations__ = {}


class TypedPair(NamedTuple):
    slope: uint8_t
    intercept: uint8_t


def make_outer_t():
    @struct
    class inner_t(NamedTuple):
        value: uint8_t

    @struct
    class outer_t(NamedTuple):
        inner: inner_t

    return outer_t


# Only the outer class is module-visible; registration must reach its field.
outer_t = make_outer_t()


@MAIN
def main(x: outer_t) -> uint8_t:
    return x.inner.value
