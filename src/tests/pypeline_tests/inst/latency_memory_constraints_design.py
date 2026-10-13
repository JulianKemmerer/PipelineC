"""In-process latency-memory bounds fixture; MEMORY_CAP=0 leaves the tag uncapped."""
from pypeline import AUTO_PIPELINE, MAIN, hw_func, param, uint8_t, wires


@hw_func
def bounds_work(x: uint8_t) -> uint8_t:
    return x * x + x


cap = param("MEMORY_CAP", 0, type=int)
CORE = AUTO_PIPELINE(bounds_work, name="bounds_core", **({"max_latency": cap} if cap else {}))


@MAIN(50.0)
def latency_memory_bounds_top(x: uint8_t) -> uint8_t:
    return CORE(x)


@MAIN(50.0)
@wires
def latency_memory_bounds_io(x: uint8_t) -> uint8_t:
    return x
