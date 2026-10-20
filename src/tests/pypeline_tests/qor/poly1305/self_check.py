"""Independent Python Poly1305 vectors checked against the generated FSM.

CAPACITY defaults to two for regression use. Manual runs select ten and the
desired MAX_LATENCY/KERNEL. This top has no PART so the regression runner can
select sky130 and manual runs can select the Artix-7 part.
"""

import random

from pypeline import (
    MAIN, Reg, hw_arg_types, hw_return_type, param, sim_assert, sim_finish,
    sim_print, uint1_t, uint16_t,
)
from stream.stream_auto_fsm import make_stream_auto_fsm

from arithmetic import POLY1305_P, uint128_t, uint130_t
from kernels import make_shared_compute, make_tagged_compute

# Compile-time knobs match the manual hardware fixture.
KERNEL = param("KERNEL", "epilogue", choices=("prologue", "epilogue"))
CAPACITY = param("CAPACITY", 2)
MAX_LATENCY = param("MAX_LATENCY", 64)
MHZ = param("MHZ", 5)
# Deterministic host-side vector generation never calls a hardware math helper.
rng = random.Random(1305)
compute = make_shared_compute(CAPACITY)
input_t = uint130_t if KERNEL == "prologue" else compute.epilogue_in_t
output_t = compute.powers_t if KERNEL == "prologue" else uint128_t
tagged_compute = make_tagged_compute(getattr(compute, KERNEL), input_t, output_t)
tagged_input_t = hw_arg_types(tagged_compute)[0]
tagged_output_t = hw_return_type(tagged_compute)
requests = []
expected = []
for lane_count in range(1, CAPACITY + 1):
    for next_lane in sorted({0, lane_count - 1}):
        r = rng.randrange(POLY1305_P)
        powers = [pow(r, k, POLY1305_P) for k in range(1, CAPACITY + 1)]
        if KERNEL == "prologue":
            data = r
            result = compute.powers_t(values=powers)
        else:
            accumulators = [rng.randrange(POLY1305_P) for _ in range(CAPACITY)]
            s = rng.getrandbits(128)
            data = input_t(accumulators=accumulators,
                           powers=compute.powers_t(values=powers),
                           lane_count=lane_count, next_lane=next_lane, s=s)
            residue = 0
            for j in range(lane_count):
                index = next_lane + lane_count - 1 - j
                if next_lane > j:
                    index = next_lane - 1 - j
                residue += accumulators[j] * powers[index]
            result = ((residue % POLY1305_P) + s) & ((1 << 128) - 1)
        direction = len(requests) & 1
        requests.append(tagged_input_t(data=data, is_encrypt=direction))
        expected.append(tagged_output_t(data=result, is_encrypt=direction))
# Wrapper backpressure is exercised for every vector.
service = make_stream_auto_fsm(tagged_compute, max_latency=MAX_LATENCY)


@MAIN(MHZ)
def self_check_poly1305_auto_fsm() -> uint128_t:
    index: Reg[uint16_t]
    sent: Reg[uint1_t]
    ready: Reg[uint1_t]
    last: Reg[uint128_t]
    inputs: tagged_input_t[len(requests)] = requests
    answers: tagged_output_t[len(expected)] = expected
    request: service.in_intrf.stream_t
    request.data = inputs[index]
    request.valid = ~sent
    ready_now: uint1_t = ready
    ready = ~ready
    response = service(service.in_fwd_t(stream=request), service.out_fb_t(ready=ready_now))
    if request.valid & response.stream_in_if.ready:
        sent = 1
    if response.stream_out_if.stream.valid & ready_now:
        value: tagged_output_t = response.stream_out_if.stream.data
        want: tagged_output_t = answers[index]
        sim_assert(value.is_encrypt == want.is_encrypt, "Poly1305 direction tag")
        if KERNEL == "prologue":
            for k in range(CAPACITY):
                sim_assert(value.data.values[k] == want.data.values[k], "Poly1305 power")
            last = value.data.values[0]
        else:
            sim_assert(value.data == want.data, "Poly1305 authentication tag")
            last = value.data
        sent = 0
        if index == len(requests) - 1:
            sim_finish()
        else:
            sim_print(f"poly1305 case={index} encrypt={value.is_encrypt}", debug=True)
        index += 1
    return last
