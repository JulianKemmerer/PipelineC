# pyright: reportInvalidTypeForm=none
"""Wire-convergence stress test for the RAM simulation model: run only via
the multi-MAIN runner (pypeline_sim.py ram_sim_model_test.py --run N). Not a
plain-python3 test (no __main__ block) and not built by pypelinec -- mirrors
fifo_sim_model_test.py's structure and registration.

`ram.ram_model_class` shares one memory list between the committed instance
and each evaluation's working copy, applying writes lazily when the next
evaluation deep-copies the committed state. That is only correct if an
evaluation that gets re-run (or discarded) never touches the shared memory.
This design makes every cycle re-run the RAM with stale inputs: each RAM is an
accumulator closed through wires and a second MAIN,

    acc_now  = ram[2]                 (combinational read, ram_acc_main)
    acc_next = acc_now + inc          (ram_acc_adder, queued later)
    ram[2]  <= acc_next               (the same RAM call's write)

so the RAM MAIN first evaluates with last cycle's acc_next, then again once the
adder updates it. If a stale write ever landed, or landed twice, the running
sum would diverge from n*(n+1)/2. The stream RAM variant runs the same loop
through make_stream_ram's handshake core.
"""
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from pypeline import MAIN, Reg, Wire, sim_output, uint32_t

from ram import make_ram
from stream.stream_ram import make_stream_ram

acc_ram, acc_ram_out_t = make_ram(uint32_t, 4, ports=("rw",), read_latency=0)
acc_in_t = acc_ram.p0_in_t
sacc_ram, sacc_ram_t = make_stream_ram(uint32_t, 4, ports=("rw",), read_latency=0)
sacc_req_stream_t = sacc_ram.p0_req_intrf.stream_t
sacc_req_fwd_t = sacc_ram.p0_req_intrf.fwd_t
sacc_resp_fb_t = sacc_ram.p0_resp_intrf.fb_t

inc: Wire[uint32_t]
acc_now: Wire[uint32_t]
acc_next: Wire[uint32_t]
sacc_now: Wire[uint32_t]
sacc_next: Wire[uint32_t]


# Registered (and so queued) before the adder and the driver: each cycle these
# first evaluate against the previous cycle's acc_next / inc.
@MAIN
def ram_acc_main():
    req: acc_in_t
    req.addr = 2
    req.wr_data = acc_next
    req.wr_en = 1
    req.valid = 1
    resp: acc_ram_out_t = acc_ram(req)
    acc_now = resp.p0.rd_data


@MAIN
def ram_stream_acc_main():
    req: sacc_req_stream_t
    req.valid = 1
    req.data.addr = 2
    req.data.wr_data = sacc_next
    req.data.wr_en = 1
    resp: sacc_ram_t = sacc_ram(sacc_req_fwd_t(stream=req), sacc_resp_fb_t(ready=1))
    sacc_now = resp.p0_resp_if.stream.data.rd_data


@MAIN
def ram_acc_adder():
    acc_next = acc_now + inc
    sacc_next = sacc_now + inc


@MAIN
def ram_acc_driver():
    n: Reg[uint32_t]
    inc = n + 1
    n = n + 1


@sim_output
def check_acc(cycle, now, stream_now):
    # Cycle n reads the sum of inc over cycles 0..n-1, i.e. 1 + 2 + ... + n.
    expected = (int(cycle) * (int(cycle) + 1)) // 2
    assert int(now) == expected, (
        f"cycle {int(cycle)}: RAM accumulator={int(now)} expected={expected} "
        f"(a re-evaluated RAM model wrote more than once, or wrote stale data)"
    )
    assert int(stream_now) == expected, (
        f"cycle {int(cycle)}: stream RAM accumulator={int(stream_now)} expected={expected}"
    )


@MAIN
def ram_acc_checker():
    n: Reg[uint32_t]
    check_acc(n, acc_now, sacc_now)
    n = n + 1
