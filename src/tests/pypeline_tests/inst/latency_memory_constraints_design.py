"""In-process latency-memory bounds fixture; MEMORY_CAP=0 leaves the tag uncapped."""
from pypeline import AUTO_PIPELINE, MAIN, hw_func, param, uint8_t, wires, Input, make_reset, uint1_t


@hw_func
def bounds_work(x: uint8_t) -> uint8_t:
    return x * x + x


cap = param("MEMORY_CAP", 0, type=int)
CORE = AUTO_PIPELINE(bounds_work, name="bounds_core", **({"max_latency": cap} if cap else {}))


# Synchronous reset pin (pulsed in cycle 0 by the simulators): every @MAIN
# resets every register with it
rst: Input[uint1_t] = make_reset()


@MAIN(50.0, reset=rst, reset_registers="all")
def latency_memory_bounds_top(x: uint8_t) -> uint8_t:
    return CORE(x)


@MAIN(50.0, reset=rst, reset_registers="all")
@wires
def latency_memory_bounds_io(x: uint8_t) -> uint8_t:
    return x
