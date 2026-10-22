# pyright: reportInvalidTypeForm=none
"""Known issue: after the sweep meets timing, a failed trim trial is kept.

On device_models at 80 MHz, the first measured implementation meets timing
(lane0 at 2 cuts, lane1 at 1 cut, 88.7 MHz). The sweep then trims both lanes
to 0 cuts to prove the stage count minimal. That trial fails at 47.7 MHz on a
path from counter's register to the digest output port, which has no end
register, so the timing report is blamed on every MAIN of the clock. Only
counter and check, which nothing can pipeline, are named in the verdict
("nothing_auto_pipelinable"), and the build ends TIMING NOT MET with the failed
trial instead of restoring the passing implementation (SWEEP_DESIGN: "A failed
zero-cut probe restores the actual previously passing implementation").

Registered in known_issues_tests.py with expect_fail=True: pypelinec exits
nonzero while the build ends TIMING NOT MET.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Output, Reg, Wire, uint8_t, uint16_t, uint32_t

cnt: Wire[uint16_t]
vals: Wire[uint32_t[2]]
digest: Output[uint32_t]


@MAIN(80.0)
def counter():
    n: Reg[uint16_t]
    cnt = n
    n += 1


@MAIN(80.0)
def lane0():
    a: uint32_t = cnt
    vals[0] = (a * a + 1) * (a + 3)


@MAIN(80.0)
def lane1():
    a: uint32_t = cnt
    vals[1] = (a * a + 2) * (a + 3)


@MAIN(80.0)
def check():
    t: Reg[uint8_t]
    t += 1
    digest = vals[0] ^ vals[1]
