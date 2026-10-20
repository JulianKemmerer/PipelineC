"""Manual Vivado comparison of unchanged Poly1305 services.

    pypelinec src/tests/pypeline_tests/qor/poly1305/auto_fsm.py \
        -D KERNEL=epilogue -D CAPACITY=10 -D MAX_LATENCY=32 -D MHZ=80 \
        --out_dir <new-directory> --syn_cache <isolated-store> -j 1

Registered boundary ports are for timing characterization. FSM latency excludes
these outer registers and the stream wrapper's result holding register.
"""

from pypeline import MAIN, PART, NamedTuple, Reg, hw_return_type, param, struct, uint1_t
from stream.stream_auto_fsm import make_stream_auto_fsm

from arithmetic import uint128_t, uint130_t
from kernels import make_shared_compute, make_tagged_compute

# Match the accepted WireGuard hardware target.
PART("xc7a200tffg1156-2")
# The selected kernel and capacity are compile-time fixture parameters.
KERNEL = param("KERNEL", "epilogue", choices=("prologue", "epilogue"))
CAPACITY = param("CAPACITY", 10)
MAX_LATENCY = param("MAX_LATENCY", 64)
MHZ = param("MHZ", 80)
# Build exactly the arithmetic and direction-tag wrapper used by the service.
compute = make_shared_compute(CAPACITY)
kernel = getattr(compute, KERNEL)
input_t = uint130_t if KERNEL == "prologue" else compute.epilogue_in_t
output_t = compute.powers_t if KERNEL == "prologue" else uint128_t
tagged_compute = make_tagged_compute(kernel, input_t, output_t)
tagged_output_t = hw_return_type(tagged_compute)
service = make_stream_auto_fsm(tagged_compute, max_latency=MAX_LATENCY)


@struct
class boundary_t(NamedTuple):
    data: tagged_output_t
    valid: uint1_t
    ready: uint1_t


@MAIN(MHZ)
def poly1305_auto_fsm(
    request: service.in_intrf.stream_t, response_ready: uint1_t
) -> boundary_t:
    input_reg: Reg[service.in_intrf.stream_t]
    feedback_reg: Reg[uint1_t]
    output_reg: Reg[boundary_t]
    previous: boundary_t = output_reg
    result = service(service.in_fwd_t(stream=input_reg),
                     service.out_fb_t(ready=feedback_reg))
    output_reg = boundary_t(data=result.stream_out_if.stream.data,
                            valid=result.stream_out_if.stream.valid,
                            ready=result.stream_in_if.ready)
    input_reg = request
    feedback_reg = response_ready
    return previous
