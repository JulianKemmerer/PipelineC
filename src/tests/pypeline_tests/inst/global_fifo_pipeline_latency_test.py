"""A global FIFO's MAIN, added after the other functions are trimmed
(PY_TO_LOGIC._add_late_mains), must not re-check those functions.

The design has a global FIFO, a pipeline_latency(1) function, and a stateful
MAIN calling one AUTO_PIPELINE object twice on identical inputs. Trimming
collapses the two calls into one instance and leaves both original call
sites' AUTO_PIPELINE tags behind, so re-running the pipeline_latency checks
over the whole table after trimming would look up instances that no longer
exist (KeyError), and would recompute the stateful MAIN's self-timed
submodules from the trimmed instances. Checked: PARSE_FILE succeeds, and the
stateful MAIN's submodule_latencies_are_self_timed equals that of the same
design without the FIFO.

Registered in elab_introspect_tests.py.
"""

import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
from pypeline import *

"""

_FIFO = """
rx: Fifo[uint8_t] = global_fifo(4)


@MAIN(100.0)
def producer():
    n: Reg[uint8_t]
    rx.wr.stream.data = n
    rx.wr.stream.valid = 1
    if rx.wr.ready:
        n += 1


@MAIN(100.0)
def consumer():
    rx.rd.ready = 1
    sink = rx.rd.stream.data
"""

_PIPELINE_LATENCY = """
@pipeline_latency(1)
@hw_func
def delay_one(x: uint8_t) -> uint8_t:
    saved: Reg[uint8_t]
    rv = saved
    saved = x
    return rv


@hw_func
def add1(x: uint8_t) -> uint8_t:
    return x + 1


add1_ap = AUTO_PIPELINE(add1)


@MAIN(100.0)
def pl_main(a: uint8_t) -> uint8_t:
    t: Reg[uint8_t]
    y = delay_one(a)
    p = add1_ap(y)
    q = add1_ap(y)
    rv = t
    t = p + q
    return rv
"""


def _parse(src, name):
    with tempfile.TemporaryDirectory(prefix="global_fifo_pipeline_latency_") as tmp:
        path = os.path.join(tmp, name)
        with open(path, "w") as f:
            f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)) + src)
        return PY_TO_LOGIC.PARSE_FILE(path)


def test_late_fifo_main_leaves_trimmed_functions_alone():
    # One file name, FIFO last: pl_main's instance labels (file and line)
    # are the same in both designs
    with_fifo = _parse(_PIPELINE_LATENCY + _FIFO, "fifo_pl_test.py")
    without = _parse(_PIPELINE_LATENCY, "fifo_pl_test.py")
    assert "rx_FIFO" in with_fifo.main_mhz, sorted(with_fifo.main_mhz)
    logic = with_fifo.FuncLogicLookupTable["pl_main"]
    # The design does leave stale tags behind: the case under test
    stale = set(logic.sub_inst_to_auto_pipeline_latency) - set(
        logic.submodule_instances
    )
    assert stale, sorted(logic.sub_inst_to_auto_pipeline_latency)
    got = logic.submodule_latencies_are_self_timed
    want = without.FuncLogicLookupTable["pl_main"].submodule_latencies_are_self_timed
    assert got == want, (got, want)
    print("test_late_fifo_main_leaves_trimmed_functions_alone PASS")


if __name__ == "__main__":
    test_late_fifo_main_leaves_trimmed_functions_alone()
    print("global_fifo_pipeline_latency_test: all PASS")
