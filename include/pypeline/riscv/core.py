"""Single-cycle Harvard RV32I core, with a pluggable combinational MMIO port."""

from typing import NamedTuple

from pypeline import (
    Feedback,
    Reg,
    array_to_uint_le,
    concat,
    hex,
    hw_func,
    int8_t,
    int16_t,
    int32_t,
    param,
    sim_assert,
    sim_print,
    struct,
    uint1_t,
    uint4_t,
    uint5_t,
    uint8_t,
    uint16_t,
    uint32_t,
    uint_to_array_le,
)
from ram import make_ram
from cpu.mem_map import DMEM_BASE_ADDR, memory_windows
from riscv.rv32i import decode, decoded_t, execute, select_next_pc, select_reg_wr_data

# Enable a tagged architectural trace in native and HDL simulation.
RISCV_TRACE = param(
    "RISCV_TRACE", False, help="Trace instruction, register write and store each cycle"
)


@struct
class riscv_out_t(NamedTuple):
    halt: uint1_t
    return_value: uint32_t
    pc: uint32_t
    unknown_op: uint1_t
    mem_out_of_range: uint1_t


@struct
class reg_file_out_t(NamedTuple):
    rd_data1: uint32_t
    rd_data2: uint32_t


@struct
class riscv_dmem_out_t(NamedTuple):
    rd_data: uint32_t
    mem_out_of_range: uint1_t
    halt: uint1_t
    return_value: uint32_t


def make_rv32i_core(imem_size, dmem_size, imem_init, dmem_init, mem_map):
    """Return a no-argument hardware function. Memory sizes are in bytes."""
    memory_windows(imem_size, dmem_size)
    imem = make_ram(
        uint32_t, imem_size // 4, ports=("r",), read_latency=0, init=imem_init
    )
    regs = make_ram(uint32_t, 32, ports=("r", "r", "w"), read_latency=0)
    dmem = make_ram(
        uint32_t,
        dmem_size // 4,
        ports=("rw",),
        read_latency=0,
        byte_write_enables=True,
        init=dmem_init,
    )
    imem_hi = 1 + len(imem.addr_t)
    dmem_hi = 1 + len(dmem.addr_t)
    dmem_end = DMEM_BASE_ADDR + dmem_size
    wr_port_t = regs.p2_in_t

    @hw_func(name="reg_file")
    def reg_file(rd_addr1: uint5_t, rd_addr2: uint5_t, wr: wr_port_t) -> reg_file_out_t:
        o = regs(
            regs.p0_in_t(addr=rd_addr1, valid=1),
            regs.p1_in_t(addr=rd_addr2, valid=1),
            wr,
        )
        rv: reg_file_out_t
        if rd_addr1 != 0:
            rv.rd_data1 = o.p0.rd_data
        if rd_addr2 != 0:
            rv.rd_data2 = o.p1.rd_data
        return rv

    @hw_func(name="riscv_dmem")
    def riscv_dmem(
        addr: uint32_t, wr_data: uint32_t, decoded: decoded_t
    ) -> riscv_dmem_out_t:
        offset = addr[1:0]
        wr = array_to_uint_le(decoded.mem_wr_byte_ens)
        rd = array_to_uint_le(decoded.mem_rd_byte_ens)
        lanes: uint4_t = wr | rd
        aligned = ~((lanes[3] & (offset != 0)) | (lanes[1] & addr[0]))
        in_ram = (addr >= DMEM_BASE_ADDR) & (addr < dmem_end)
        in_mmio = addr[31]
        shifted_wr: uint4_t = wr << offset
        shifted_rd: uint4_t = rd << offset
        shift: uint5_t = concat(offset, uint1_t(0), uint1_t(0), uint1_t(0))
        shifted_data: uint32_t = wr_data << shift
        ram_wr: uint4_t = 0
        index: dmem.addr_t = 0
        if aligned & in_ram:
            index = addr[dmem_hi:2]
            ram_wr = shifted_wr
        ram_out = dmem(
            dmem.p0_in_t(
                addr=index,
                wr_data=shifted_data,
                wr_en=uint_to_array_le(ram_wr, 1),
                valid=1,
            )
        )
        mm_wr: uint4_t = 0
        mm_rd: uint4_t = 0
        if aligned & in_mmio:
            mm_wr = shifted_wr
            mm_rd = shifted_rd
        mm = mem_map(
            addr & 0xFFFFFFFC,
            shifted_data,
            uint_to_array_le(mm_wr, 1),
            uint_to_array_le(mm_rd, 1),
        )
        rv: riscv_dmem_out_t
        rv.mem_out_of_range = (lanes != 0) & ~(
            aligned & (in_ram | (in_mmio & mm.addr_is_mapped))
        )
        rv.halt = mm.halt
        rv.return_value = mm.return_value
        word: uint32_t = mm.rd_data if in_mmio else ram_out.p0.rd_data
        rv.rd_data = word
        if rd == 1:
            byte_lanes: uint8_t[4] = uint_to_array_le(word, 8)
            byte_val: uint8_t = byte_lanes[offset]
            rv.rd_data = byte_val
            if decoded.mem_rd_sign_ext:
                rv.rd_data = int32_t(int8_t(byte_val))
        elif rd == 3:
            halves: uint16_t[2] = uint_to_array_le(word, 16)
            half = halves[addr[1]]
            rv.rd_data = half
            if decoded.mem_rd_sign_ext:
                rv.rd_data = int32_t(int16_t(half))
        return rv

    @hw_func(name="rv32i_step")
    def step() -> riscv_out_t:
        pc: Reg[uint32_t]
        pc_plus4: uint32_t = pc + 4
        fetch = imem(imem.p0_in_t(addr=pc[imem_hi:2], valid=1))
        inst = fetch.p0.rd_data
        sim_assert(
            (pc < imem_size) & (pc[1:0] == 0),
            f"invalid fetch pc={hex(pc)} inst={hex(inst)}",
        )
        decoded = decode(inst)
        sim_assert(
            ~decoded.unknown_op, f"unknown instruction pc={hex(pc)} inst={hex(inst)}"
        )
        wr: Feedback[wr_port_t]
        regs_out = reg_file(decoded.src1, decoded.src2, wr)
        exe = execute(pc, pc_plus4, decoded, regs_out.rd_data1, regs_out.rd_data2)
        if RISCV_TRACE:
            store = array_to_uint_le(decoded.mem_wr_byte_ens)
            sim_print(
                f"pc={hex(pc)} inst={hex(inst)} wr={wr.wr_en} rd={wr.addr} data={hex(wr.wr_data)} "
                f"addr={hex(exe.result)} store={hex(regs_out.rd_data2)} enables={hex(store)}",
                debug=True,
            )
        mem = riscv_dmem(exe.result, regs_out.rd_data2, decoded)
        sim_assert(
            ~mem.mem_out_of_range,
            f"bad data address={hex(exe.result)} pc={hex(pc)} inst={hex(inst)}",
        )
        data = select_reg_wr_data(decoded, exe, mem.rd_data, pc_plus4)
        wr = wr_port_t(
            addr=decoded.dest,
            wr_data=data,
            wr_en=decoded.reg_wr & (decoded.dest != 0),
            valid=1,
        )
        rv: riscv_out_t
        rv.halt = decoded.halt | mem.halt
        rv.return_value = mem.return_value
        rv.pc = pc
        rv.unknown_op = decoded.unknown_op
        rv.mem_out_of_range = mem.mem_out_of_range
        if ~rv.halt:
            pc = select_next_pc(decoded, exe, pc_plus4)
        return rv

    @hw_func(name="rv32i_core")
    def core() -> riscv_out_t:
        held: Reg[riscv_out_t]
        if ~held.halt:
            held = step()
        return held

    return core
