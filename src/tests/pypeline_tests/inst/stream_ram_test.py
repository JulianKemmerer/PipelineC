# pyright: reportInvalidTypeForm=none
"""make_stream_ram (include/pypeline/stream/stream_ram.py): handshake checks
plus synthesis tops.

Registered in native_sim_tests.py (plain `python3` runs the test_* functions
against the shared RAM simulation model) and synth_tests.py (--comb builds every
@MAIN below). The memory semantics themselves are covered by ram_test.py; this
file is about ready used as a clock enable:
  - a request's response appears `latency` cycles later when ready stays high,
    one per cycle, echoing the request;
  - while a port's last stage holds an unaccepted response, that port's whole
    pipeline and its req_ready freeze, and the response stays stable;
  - a write executes exactly once per accepted request, however long it stalls;
  - ports stall independently.
"""
import os
import random
import sys

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
from pypeline import MAIN, sim_call, sim_reset, uint8_t, uint16_t

from stream.stream_ram import make_stream_ram

# Single rw port, BRAM read + output register: latency 2.
bram, bram_t = make_stream_ram(
    uint16_t, 8, ports=("rw",), read_latency=1, out_regs=1, init=[1, 2, 3]
)
# Write port + read port, combinational read, no registers: latency 0.
comb, comb_t = make_stream_ram(uint8_t, 4, ports=("w", "r"), read_latency=0)
# Write port + read port with an input register and a BRAM read: latency 2.
sdp, sdp_t = make_stream_ram(uint8_t, 16, ports=("w", "r"), read_latency=1, in_regs=1)


@MAIN
def stream_ram_test_bram(
    p0_req_if: bram.p0_req_intrf.fwd_t, p0_resp_if: bram.p0_resp_intrf.fb_t
) -> bram_t:
    return bram(p0_req_if, p0_resp_if)


@MAIN
def stream_ram_test_comb(
    p0_req_if: comb.p0_req_intrf.fwd_t,
    p0_resp_if: comb.p0_resp_intrf.fb_t,
    p1_req_if: comb.p1_req_intrf.fwd_t,
    p1_resp_if: comb.p1_resp_intrf.fb_t,
) -> comb_t:
    return comb(p0_req_if, p0_resp_if, p1_req_if, p1_resp_if)


@MAIN
def stream_ram_test_sdp(
    p0_req_if: sdp.p0_req_intrf.fwd_t,
    p0_resp_if: sdp.p0_resp_intrf.fb_t,
    p1_req_if: sdp.p1_req_intrf.fwd_t,
    p1_resp_if: sdp.p1_resp_intrf.fb_t,
) -> sdp_t:
    return sdp(p0_req_if, p0_resp_if, p1_req_if, p1_resp_if)


# ── Helpers ──


def request(sram, i, valid, **payload):
    intrf = getattr(sram, f"p{i}_req_intrf")
    data = getattr(sram, f"p{i}_req_t")(**payload)
    return intrf.fwd_t(stream=intrf.stream_t(data=data, valid=valid))


def ready(sram, i, value):
    return getattr(sram, f"p{i}_resp_intrf").fb_t(ready=value)


def fields(v):
    return tuple(int(getattr(v, f)) for f in v._fields)


def bram_step(addr=0, wd=0, we=0, valid=0, rdy=1):
    r = sim_call(
        bram,
        request(bram, 0, valid, addr=addr, wr_data=wd, wr_en=we),
        ready(bram, 0, rdy),
    )
    s = r.p0_resp_if.stream
    return int(r.p0_req_if.ready), int(s.valid), fields(s.data)


# ── Tests ──


def test_attributes():
    assert (bram.latency, comb.latency, sdp.latency) == (2, 0, 2)
    assert not hasattr(bram, "_pipeline_latency") or bram._pipeline_latency is None
    assert bram.p0_req_t._fields == ("addr", "wr_data", "wr_en")
    assert bram.p0_resp_t._fields == ("addr", "wr_data", "wr_en", "rd_data")
    assert comb.p1_req_t._fields == ("addr",) and comb.p1_resp_t._fields == ("addr", "rd_data")
    assert comb.p0_resp_t._fields == ("addr", "wr_data", "wr_en")
    assert bram_t._fields == ("p0_resp_if", "p0_req_if")


def test_steady_flow_one_response_per_cycle():
    sim_reset()
    trace = [
        bram_step(addr=0, valid=1),
        bram_step(addr=1, wd=77, we=1, valid=1),
        bram_step(addr=1, valid=1),
        bram_step(),
        bram_step(),
        bram_step(),
    ]
    assert [t[0] for t in trace] == [1] * 6, "an unstalled port is always ready"
    assert [t[1] for t in trace] == [0, 0, 1, 1, 1, 0]
    # (addr, wr_data, wr_en, rd_data): the write's own read is read-first.
    assert [t[2] for t in trace[2:5]] == [(0, 0, 0, 1), (1, 77, 1, 2), (1, 0, 0, 77)]


def test_stall_freezes_pipeline_and_holds_response():
    sim_reset()
    bram_step(addr=2, valid=1)
    bram_step(addr=0, valid=1)
    held = bram_step(addr=1, valid=1, rdy=0)
    assert held == (0, 1, (2, 0, 0, 3)), held
    for _ in range(3):
        assert bram_step(addr=1, valid=1, rdy=0) == held, "stalled output must not move"
    assert bram_step(addr=1, valid=1, rdy=1) == (1, 1, (2, 0, 0, 3))
    assert bram_step(rdy=1)[1:] == (1, (0, 0, 0, 1))
    assert bram_step(rdy=1)[1:] == (1, (1, 0, 0, 2)), "request accepted on the resume cycle"
    assert bram_step(rdy=1)[1] == 0, "nothing else was accepted while stalled"


def test_last_stage_bubble_is_filled():
    sim_reset()
    bram_step(addr=0, valid=1)  # c0: request A
    bram_step(valid=0)  # c1: bubble
    assert bram_step(addr=2, valid=1) == (1, 1, (0, 0, 0, 1))  # c2: A out, B in
    # c3: ready low, but the last stage holds c1's bubble, so the port still
    # advances (and accepts) instead of stalling behind nothing.
    assert bram_step(valid=0, rdy=0)[:2] == (1, 0)
    # c4: now B is in the last stage and unaccepted: the port freezes.
    assert bram_step(valid=0, rdy=0) == (0, 1, (2, 0, 0, 3))


def test_write_executes_once_per_accepted_request():
    """A write request held in the RAM stage by a stall writes once, when it
    finally advances; a request refused while stalled never writes at all."""
    sim_reset()

    def step(p0_valid, p0_addr, p0_data, p0_rdy, p1_valid=0, p1_addr=0):
        return sim_call(
            sdp,
            request(sdp, 0, p0_valid, addr=p0_addr, wr_data=p0_data, wr_en=1),
            ready(sdp, 0, p0_rdy),
            request(sdp, 1, p1_valid, addr=p1_addr),
            ready(sdp, 1, 1),
        )

    def read_all(addrs, p0_rdy):
        got = []
        for addr in addrs:
            r = step(0, 0, 0, p0_rdy, 1, addr)
            if int(r.p1_resp_if.stream.valid):
                got.append((int(r.p1_resp_if.stream.data.addr), int(r.p1_resp_if.stream.data.rd_data)))
        for _ in range(sdp.latency):
            r = step(0, 0, 0, p0_rdy)
            if int(r.p1_resp_if.stream.valid):
                got.append((int(r.p1_resp_if.stream.data.addr), int(r.p1_resp_if.stream.data.rd_data)))
        return got

    # Write port latency 2 (input register + registered read): with ready low,
    # (5, 11) and (6, 22) are accepted while the last stage is still empty;
    # then (5, 11) reaches the last stage and the port freezes with (6, 22)
    # sitting in the RAM stage. (7, 33) is refused for the whole stall.
    assert int(step(1, 5, 11, 0).p0_req_if.ready) == 1
    assert int(step(1, 6, 22, 0).p0_req_if.ready) == 1
    for _ in range(4):
        assert int(step(1, 7, 33, 0).p0_req_if.ready) == 0
    # The read port is independent: (5, 11) wrote on entering the last stage,
    # (6, 22) is still held in the RAM stage and has not written.
    assert read_all([5, 6, 7], 0) == [(5, 11), (6, 0), (7, 0)]
    for _ in range(3):
        step(0, 0, 0, 0)
    assert read_all([6], 0) == [(6, 0)], "a frozen RAM stage must not write"
    # Release: (6, 22) advances and writes exactly once; (7, 33) never does.
    for _ in range(4):
        step(0, 0, 0, 1)
    assert read_all([5, 6, 7], 1) == [(5, 11), (6, 22), (7, 0)]


def test_combinational_stream_ram():
    sim_reset()
    r = sim_call(
        comb,
        request(comb, 0, 1, addr=2, wr_data=42, wr_en=1),
        ready(comb, 0, 0),
        request(comb, 1, 1, addr=2),
        ready(comb, 1, 1),
    )
    assert int(r.p0_req_if.ready) == 0, "latency 0: req_ready is resp_ready"
    assert int(r.p0_resp_if.stream.valid) == 1 and int(r.p1_resp_if.stream.data.rd_data) == 0
    r = sim_call(
        comb,
        request(comb, 0, 0, addr=0, wr_data=0, wr_en=0),
        ready(comb, 0, 1),
        request(comb, 1, 1, addr=2),
        ready(comb, 1, 1),
    )
    assert int(r.p1_resp_if.stream.data.rd_data) == 0, "the refused write did not land"
    sim_call(
        comb,
        request(comb, 0, 1, addr=2, wr_data=42, wr_en=1),
        ready(comb, 0, 1),
        request(comb, 1, 0, addr=0),
        ready(comb, 1, 1),
    )
    r = sim_call(
        comb,
        request(comb, 0, 0, addr=0, wr_data=0, wr_en=0),
        ready(comb, 0, 1),
        request(comb, 1, 1, addr=2),
        ready(comb, 1, 1),
    )
    assert int(r.p1_resp_if.stream.data.rd_data) == 42


def test_random_backpressure_soak():
    """Random valid/ready on a single rw port: the accepted responses, in order,
    must equal an independent replay of the accepted requests."""
    rng = random.Random(7)
    sim_reset()
    mem = [1, 2, 3, 0, 0, 0, 0, 0]
    accepted, responses = [], []
    for _ in range(400):
        valid = rng.randrange(3) != 0
        rdy = rng.randrange(3) != 0
        req = dict(addr=rng.randrange(8), wr_data=rng.randrange(1 << 16), wr_en=rng.randrange(2))
        r = sim_call(bram, request(bram, 0, valid, **req), ready(bram, 0, rdy))
        if valid and int(r.p0_req_if.ready):
            accepted.append(req)
        if rdy and int(r.p0_resp_if.stream.valid):
            responses.append(fields(r.p0_resp_if.stream.data))
    expected = []
    for req in accepted:
        expected.append((req["addr"], req["wr_data"], req["wr_en"], mem[req["addr"]]))
        if req["wr_en"]:
            mem[req["addr"]] = req["wr_data"]
    assert len(responses) >= len(accepted) - bram.latency
    assert responses == expected[: len(responses)], "responses diverge from replay"


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
