import cocotb
from cocotb.triggers import Timer

from pipelinec_cocotb import *  # Generated


def check_cpu_debug(dut):
    # DUMP_PIPELINEC_DEBUG(dut)
    if halt(dut) == 1:
        print(f"CPU Halted: returned {int(main_return(dut))}")
        raise cocotb.result.TestSuccess("RISC-V Test Passed!")
    assert unknown_op(dut) == 0, "Unknown Instruction!"
    assert mem_out_of_range(dut) == 0, "Memory Access Error!"


@cocotb.test()
async def run_cpu(dut):
    # Do first cycle print a little different
    # to work around 'metavalue detected' warnings from ieee libs
    cycle = 0
    print("Clock:", cycle, flush=True)
    dut.clk_60p0.value = 1
    await Timer(0.5, units="ns")
    check_cpu_debug(dut)
    print("^End Clock:", cycle, flush=True)
    while True:
        dut.clk_60p0.value = 0
        await Timer(0.5, units="ns")
        print("")
        print("Clock:", cycle + 1, flush=True)
        dut.clk_60p0.value = 1
        await Timer(0.5, units="ns")
        check_cpu_debug(dut)
        cycle += 1
