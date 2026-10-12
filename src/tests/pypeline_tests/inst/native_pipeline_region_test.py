"""Native sim's pipelined-region model of global wires (pypeline._sim_regions,
docs/pypeline_sim_DESIGN.md "Pipelined native sim"), unit-tested without a
build.

1. Invocation-local view: while a pipelined MAIN's writes are diverted into
   its delayed collector, its own reads still see this invocation's values.
   Read-before-write is zero and read-after-write is the new value. It used
   to read the old published value for both.
2. AUTO_PIPELINE(latency=N) delays its global writes together with its
   return value (Layer-1 sim_call cycles), instead of writing them live.
3. A global read inside a function called by the pipelined function raises
   SimPipelineModelError instead of silently using the entry-cycle value.

Run standalone: python3 native_pipeline_region_test.py
"""

import os
import sys
import tempfile
import textwrap
from collections import deque

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import pypeline

FAILURES = []


def check(cond, msg):
    print(("  ok: " if cond else "  FAIL: ") + msg)
    if not cond:
        FAILURES.append(msg)


DESIGN = textwrap.dedent(
    """
    from pypeline import *

    @struct
    class pair_t(NamedTuple):
        a: uint16_t
        b: uint16_t

    w: Wire[uint16_t]
    aw: Wire[uint16_t]
    g: Wire[uint16_t]

    @MAIN
    def compute(x: uint16_t) -> pair_t:
        before: uint16_t = w
        w = x
        after: uint16_t = w
        return pair_t(a=before, b=after)

    @hw_func
    def ap_core(x: uint16_t) -> uint16_t:
        aw = x + 1
        return x

    AP = AUTO_PIPELINE(ap_core, latency=2)

    @hw_func
    def read_g(x: uint16_t) -> uint16_t:
        return x + g

    @hw_func
    def nested_core(x: uint16_t) -> uint16_t:
        return read_g(x)

    NESTED = AUTO_PIPELINE(nested_core, latency=2)
    """
)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "region_design.py"), "w") as f:
            f.write(DESIGN)
        sys.path.insert(0, tmp)
        import region_design as d

        u16 = pypeline.uint16_t
        for name in ("w", "aw", "g"):
            key = "region_design." + name
            pypeline._sim_wire_ctype[key] = u16
            pypeline._sim_wire_state[key] = u16(0)
        w_key = "region_design.w"

        print("1. invocation-local view of a pipelined MAIN's own wire")
        pypeline.sim_call(d.compute, 3)  # records compute's claim on w
        pypeline._sim_wire_state[w_key] = u16(9)  # an old published value
        region = {"latency": 2, "queue": deque(), "collector": [], "root": d.compute, "name": "compute"}
        pypeline._sim_pipelined_main_info[d.compute] = region
        pypeline._sim_current_main = d.compute
        try:
            r = pypeline._sim_run_in_region(region, pypeline.sim_call, d.compute, 3)
        finally:
            pypeline._sim_current_main = None
            pypeline._sim_pipelined_main_info.clear()
        check((int(r.a), int(r.b)) == (0, 3), f"own reads see (0, 3), got ({int(r.a)}, {int(r.b)})")
        check(
            [(n, p, int(v)) for n, p, v in region["collector"]] == [(w_key, (), 0), (w_key, (), 3)],
            "collector holds the reset zero then the write",
        )
        check(int(pypeline._sim_wire_state[w_key]) == 9, "published state untouched until replay")

        print("2. AUTO_PIPELINE global writes delayed with the return")
        aw_key = "region_design.aw"
        seen = []
        for cycle in range(5):
            ret = pypeline.sim_call(d.AP, 10 + cycle)
            seen.append((int(ret), int(pypeline._sim_wire_state[aw_key])))
        # Cycle c returns x(c-2); aw published at the start of cycle c is x(c-2)+1
        check(
            seen == [(0, 0), (0, 0), (10, 11), (11, 12), (12, 13)],
            f"return and write both 2 cycles late: {seen}",
        )

        print("3. nested global read refused")
        try:
            pypeline.sim_call(d.NESTED, 1)
            check(False, "nested read raised SimPipelineModelError")
        except pypeline.SimPipelineModelError as e:
            check("'read_g' is called inside the pipeline" in str(e), "nested read raised SimPipelineModelError")

    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
