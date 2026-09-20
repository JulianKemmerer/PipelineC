# pyright: reportInvalidTypeForm=none
"""Cycle oracle: banked raw RAM, pure-caller alignment, and stalled streams."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
from pypeline import (
    MAIN,
    Reg,
    NamedTuple,
    hw_func,
    struct,
    uint1_t,
    uint8_t,
    uint16_t,
    uint32_t,
    sim_assert,
    sim_print,
    sim_finish,
)
from ram import make_auto_pipeline_ram
from stream.stream_ram import make_stream_auto_pipeline_ram

L = int(os.environ.get("AUTO_PIPELINE_RAM_LATENCY", "7"))
constraints = (
    dict(start_latency=3, max_latency=3)
    if os.environ.get("AUTO_PIPELINE_RAM_AUTO")
    else dict(latency=L)
)
raw, raw_t = make_auto_pipeline_ram(uint32_t, 4096, ports=("w", "r"), **constraints)
stream, stream_t = make_stream_auto_pipeline_ram(
    uint32_t, 4096, ports=("w", "r"), **constraints
)
addr_t = raw.addr_t
wr_t, rd_t = raw.p0_in_t, raw.p1_in_t
wreq_t, rreq_t = stream.p0_req_t, stream.p1_req_t
wif_t, rif_t = stream.p0_req_intrf.fwd_t, stream.p1_req_intrf.fwd_t
wfb_t, rfb_t = stream.p0_resp_intrf.fb_t, stream.p1_resp_intrf.fb_t
wstream_t, rstream_t = stream.p0_req_intrf.stream_t, stream.p1_req_intrf.stream_t


@struct
class aligned_t(NamedTuple):
    data: uint32_t
    addr: addr_t
    valid: uint1_t


@hw_func
def aligned(w: wr_t, r: rd_t) -> aligned_t:
    result: raw_t = raw(w, r)
    out: aligned_t
    out.data = result.p1.rd_data
    out.valid = result.p1.valid
    out.addr = r.addr  # compiler must align this bypass with the RAM response
    return out


@MAIN(20.0)
def self_check_auto_pipeline_ram() -> uint32_t:
    tick: Reg[uint16_t]
    raw_cycle: Reg[uint16_t]
    written: Reg[uint8_t]
    requested: Reg[uint8_t]
    received: Reg[uint8_t]
    acks: Reg[uint8_t]
    checked: Reg[uint8_t]
    index: addr_t = addr_t(raw_cycle & 15)
    address: addr_t = index | ((index & 1) << 11)
    w: wr_t
    w.addr = address
    w.valid = (raw_cycle >= 8) & (raw_cycle < 24)
    w.wr_en = 1
    w.wr_data = uint32_t(index) + 100
    r: rd_t
    r.addr = address
    r.valid = (raw_cycle >= 48) & (raw_cycle < 64)
    raw_data: uint32_t = 0
    # A conditional call gates CLOCK_ENABLE for every stage and memory write.
    if (tick & 3) != 1:
        plain: aligned_t = aligned(w, r)
        raw_data = plain.data
        if plain.valid:
            sim_assert(
                plain.data == uint32_t(plain.addr & 15) + 100,
                "raw RAM read / alignment",
            )
            sim_print(f"raw {plain.addr} {plain.data}", debug=True)
            checked += 1
        raw_cycle += 1

    wi: wstream_t
    wi.data.addr = addr_t(written) | ((addr_t(written) & 1) << 11)
    wi.data.wr_data = uint32_t(written) + 100
    wi.data.wr_en = 1
    wi.valid = written < 16
    ri: rstream_t
    ri.data.addr = addr_t(requested) | ((addr_t(requested) & 1) << 11)
    ri.valid = (tick > 80) & (requested < 16)
    wo: uint1_t = (tick > 40) & uint1_t(tick & 1)
    ro: uint1_t = uint1_t((tick >> 1) & 1)
    streamed: stream_t = stream(
        wif_t(stream=wi), wfb_t(ready=wo), rif_t(stream=ri), rfb_t(ready=ro)
    )
    if wi.valid & streamed.p0_req_if.ready:
        written += 1
    if ri.valid & streamed.p1_req_if.ready:
        requested += 1
    if streamed.p0_resp_if.stream.valid & wo:
        sim_assert(
            streamed.p0_resp_if.stream.data.wr_data == uint32_t(acks) + 100,
            "write ack order",
        )
        acks += 1
    if streamed.p1_resp_if.stream.valid & ro:
        sim_assert(
            streamed.p1_resp_if.stream.data.rd_data == uint32_t(received) + 100,
            "stream read order",
        )
        sim_print(
            f"stream {received} {streamed.p1_resp_if.stream.data.rd_data}", debug=True
        )
        received += 1
    if tick == 200:
        sim_assert(checked == 16, "raw response count")
        sim_assert(acks == 16, "write acknowledgement count")
        sim_assert(received == 16, "stream response count")
        sim_finish()
    tick += 1
    # Keep memory data observable during the synthesis-selected-plan test.
    return raw_data ^ streamed.p1_resp_if.stream.data.rd_data
