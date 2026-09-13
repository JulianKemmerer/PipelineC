# pyright: reportInvalidTypeForm=none
"""Native/GHDL oracle for fixed pipelines, bypass alignment and added stages."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from pypeline import (
    AUTOPIPELINE,
    MAIN,
    NamedTuple,
    Reg,
    Wire,
    hw_func,
    pipeline_latency,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint16_t,
)


@pipeline_latency(1)
def delay_one(x: uint16_t) -> uint16_t:
    saved: Reg[uint16_t]
    result: uint16_t = saved
    saved = x
    return result


@pipeline_latency(1)
def initialized_delay(x: uint16_t, reset: uint1_t) -> uint16_t:
    saved: Reg[uint16_t] = 9
    result: uint16_t = saved
    if reset:
        saved = 9
    else:
        saved = x
    return result


@hw_func
def enabled_join(x: uint16_t, enable: uint1_t, reset: uint1_t) -> uint16_t:
    delayed: uint16_t
    if enable:
        delayed = initialized_delay(x, reset)
    return delayed + x


@struct
class sample_t(NamedTuple):
    data: uint16_t
    seq: uint16_t
    valid: uint1_t


@pipeline_latency(2)
def delay_sample(value: sample_t) -> sample_t:
    first: Reg[sample_t]
    second: Reg[sample_t]
    result: sample_t = second
    second = first
    first = value
    return result


@hw_func
def mixed(value: sample_t) -> sample_t:
    delayed: sample_t = delay_sample(value)
    shorter: uint16_t = delay_one(value.data)
    result: sample_t
    result.data = delayed.data + shorter + value.data
    result.seq = value.seq
    result.valid = value.valid
    return result


input_sample: Wire[sample_t]
output_sample: Wire[sample_t]
ap_output_sample: Wire[sample_t]
ap = AUTOPIPELINE(mixed)


@MAIN(100.0)
def pipeline_latency_compute():
    output_sample = mixed(input_sample)


@MAIN(100.0)
def pipeline_latency_ap_compute():
    ticks: Reg[uint16_t]
    ticks += 1
    ap_output_sample = ap(input_sample)


@MAIN
def pipeline_latency_checker() -> sample_t:
    count: Reg[uint16_t]
    seen: Reg[uint16_t]
    observed_latency: Reg[uint16_t]
    ap_seen: Reg[uint16_t]
    ap_observed_latency: Reg[uint16_t]
    done: Reg[uint1_t]
    if done:
        sim_finish()
    # These local calls stay outside the auto-pipelined regions. Check the
    # initial register value and synchronous reset, then a clock-enabled
    # fixed child whose mux control and bypass need one clock of alignment.
    initial_input: uint16_t = count + 100
    initial: uint16_t = initialized_delay(initial_input, count == 8)
    initial_expected: uint16_t = count + 99
    if (count == 0) | (count == 9):
        initial_expected = 9
    sim_assert(initial == initial_expected, "fixed register initialization/reset")
    enabled_input: uint16_t = count + 40
    enable: uint1_t = ~(count & 1)
    enabled: uint16_t = enabled_join(enabled_input, enable, count == 8)
    if (count > 0) & ~done:
        enabled_expected: uint16_t = count + 39
        if count & 1:
            if count == 9:
                enabled_expected += 9
            else:
                enabled_expected += count + 39
        sim_assert(enabled == enabled_expected, "fixed clock enable/alignment")
        sim_print(f"enabled={enabled} initial={initial} cycle={count}", debug=True)
    sent: sample_t
    sent.data = count + 7
    sent.seq = count
    sent.valid = count < 24
    input_sample = sent
    received: sample_t = output_sample
    if received.valid & ~done:
        expected: uint16_t = (received.seq + 7) * 3
        sim_assert(received.data == expected, "fixed pipeline data misalignment")
        sim_assert(received.seq == seen, "fixed pipeline sequence misalignment")
        if seen == 0:
            observed_latency = count - received.seq
            sim_assert(observed_latency >= 2, "missing user pipeline latency")
        else:
            sim_assert(count - received.seq == observed_latency, "latency changed")
        sim_print(
            f"fixed data={received.data} seq={received.seq} cycle={count}", debug=True
        )
        seen += 1
    ap_received: sample_t = ap_output_sample
    if ap_received.valid & ~done:
        ap_expected: uint16_t = (ap_received.seq + 7) * 3
        sim_assert(
            ap_received.data == ap_expected, "AP fixed pipeline data misalignment"
        )
        sim_assert(
            ap_received.seq == ap_seen, "AP fixed pipeline sequence misalignment"
        )
        if ap_seen == 0:
            ap_observed_latency = count - ap_received.seq
            sim_assert(ap_observed_latency >= 2, "AP missing user pipeline latency")
        else:
            sim_assert(
                count - ap_received.seq == ap_observed_latency, "AP latency changed"
            )
        sim_print(
            f"ap fixed data={ap_received.data} seq={ap_received.seq} cycle={count}",
            debug=True,
        )
        ap_seen += 1
    if (seen == 24) & (ap_seen == 24):
        done = 1
    sim_assert(count < 150, "fixed pipeline failed to drain")
    count += 1
    return received
