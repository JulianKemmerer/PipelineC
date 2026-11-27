"""Single-cycle Harvard RV32I datapath. See examples/risc-v/risc-v_decl.h for its PipelineC predecessor."""

from typing import NamedTuple
from pypeline import *
from ram import make_ram
from cpu.mem_map import AddressMap
from riscv.core import riscv_out_t
from riscv.rv32i import decode, decoded_t, execute, select_next_pc, select_reg_wr_data

# Enable a tagged architectural trace in native and HDL simulation.
RISCV_TRACE = param(
    name="RISCV_TRACE",
    default=False,
    help="Trace instruction, register write and store each cycle",
)


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


@hw_func
def in_region(addr: uint32_t, base: uint32_t, last: uint32_t) -> uint1_t:
    return (addr >= base) & (addr <= last)


def make_rv32i_single_cycle_core(*, imem_init, dmem_init, mem_map, layout=AddressMap()):
    """Return a no-argument hardware function. Memory sizes are in bytes."""
    layout.memory_windows()
    imem_size = layout.imem_size
    dmem_size = layout.dmem_size
    reset_vector = layout.imem_base
    data_base = layout.dmem_base
    mmio_base = layout.mmio_base
    # Inclusive last addresses also represent regions ending at 2**32.
    imem_last = reset_vector + imem_size - 1
    dmem_last = data_base + dmem_size - 1
    mmio_last = mmio_base + layout.mmio_size - 1
    imem = make_ram(
        elem_t=uint32_t,
        size=imem_size // 4,
        ports=("r",),
        read_latency=0,
        init=imem_init,
    )
    regs = make_ram(elem_t=uint32_t, size=32, ports=("r", "r", "w"), read_latency=0)
    dmem = make_ram(
        elem_t=uint32_t,
        size=dmem_size // 4,
        ports=("rw",),
        read_latency=0,
        byte_write_enables=True,
        init=dmem_init,
    )
    # A partial final address range needs guarding before indexing a non-power-of-two RAM.
    full_index_range = dmem_size > 4 and dmem_size & (dmem_size - 1) == 0
    imem_hi = 1 + len(imem.addr_t)
    dmem_hi = 1 + len(dmem.addr_t)
    rd_port_t = regs.p0_in_t
    rd2_port_t = regs.p1_in_t
    wr_port_t = regs.p2_in_t

    @hw_func
    def reg_file(rd1: rd_port_t, rd2: rd2_port_t, wr: wr_port_t) -> reg_file_out_t:
        o = regs(p0=rd1, p1=rd2, p2=wr)
        rv: reg_file_out_t
        if rd1.addr != 0:
            rv.rd_data1 = o.p0.rd_data
        if rd2.addr != 0:
            rv.rd_data2 = o.p1.rd_data
        return rv

    @hw_func
    def riscv_dmem(
        addr: uint32_t, wr_data: uint32_t, decoded: decoded_t, enabled: uint1_t
    ) -> riscv_dmem_out_t:
        # The decoder supplies low-lane masks 0001, 0011 or 1111. A word
        # needs offset zero and a halfword needs an even byte address.
        offset = addr[1:0]
        wr = array_to_uint_le(decoded.mem_wr_byte_ens)
        rd = array_to_uint_le(decoded.mem_rd_byte_ens)
        lanes: uint4_t = wr | rd
        aligned = ~((lanes[3] & (offset != 0)) | (lanes[1] & addr[0]))
        local_addr: uint32_t = addr - data_base
        in_ram = in_region(addr=addr, base=data_base, last=dmem_last)
        in_mmio = in_region(addr=addr, base=mmio_base, last=mmio_last)
        # Move each enable by the byte offset and store data by eight times
        # that offset. RAM and MMIO see identical little-endian word lanes.
        shifted_wr: uint4_t = wr << offset
        shifted_rd: uint4_t = rd << offset
        shift: uint5_t = concat(offset, uint3_t(0))
        shifted_data: uint32_t = wr_data << shift
        ram_wr: uint4_t = 0
        index: dmem.addr_t = 0
        # The read address can change freely. Only a valid store enables a write.
        if full_index_range:
            index = local_addr[dmem_hi:2]
        elif in_ram:
            index = local_addr[dmem_hi:2]
        if enabled & aligned & in_ram:
            ram_wr = shifted_wr
        ram_out = dmem(
            p0=dmem.p0_in_t(
                addr=index,
                wr_data=shifted_data,
                wr_en=uint_to_array_le(ram_wr, 1),
                valid=1,
            )
        )
        # The peripheral clocks even on idle cycles. Only the byte enables
        # authorize a transfer, and only a device inside MMIO may claim it.
        mm_wr: uint4_t = 0
        mm_rd: uint4_t = 0
        if enabled & aligned & in_mmio:
            mm_wr = shifted_wr
            mm_rd = shifted_rd
        mm = mem_map(
            addr=addr & 0xFFFFFFFC,
            wr_data=shifted_data,
            wr_byte_ens=uint_to_array_le(mm_wr, 1),
            rd_byte_ens=uint_to_array_le(mm_rd, 1),
        )
        rv: riscv_dmem_out_t
        rv.mem_out_of_range = (lanes != 0) & ~(
            aligned & (in_ram | (in_mmio & mm.addr_is_mapped))
        )
        rv.halt = mm.halt
        rv.return_value = mm.return_value
        # Select the addressed byte or halfword before extending to XLEN.
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

    @hw_func
    def single_cycle_core() -> riscv_out_t:
        # Fetch. All five parts execute between the same pair of clock edges.
        pc: Reg[uint32_t] = reset_vector
        halted: Reg[uint1_t]
        enabled = ~halted
        fetch_offset: uint32_t = pc - reset_vector
        in_rom = in_region(addr=pc, base=reset_vector, last=imem_last)
        pc_plus4: uint32_t = pc + 4
        fetch = imem(p0=imem.p0_in_t(addr=fetch_offset[imem_hi:2], valid=1))
        inst = fetch.p0.rd_data
        sim_assert(
            in_rom & (pc[1:0] == 0),
            f"invalid fetch pc={hex(pc)} inst={hex(inst)}",
        )
        # Decode and read both sources. Feedback connects the writeback port
        # below to this same RAM instance. Reads see the pre-edge register values.
        decoded = decode(inst=inst)
        sim_assert(
            ~decoded.unknown_op, f"unknown instruction pc={hex(pc)} inst={hex(inst)}"
        )
        wr: Feedback[wr_port_t]
        regs_out = reg_file(
            rd1=rd_port_t(addr=decoded.src1, valid=1),
            rd2=rd2_port_t(addr=decoded.src2, valid=1),
            wr=wr,
        )
        # Execute the ALU operation, effective address, or control-flow target.
        exe = execute(
            pc=pc,
            pc_plus4=pc_plus4,
            decoded=decoded,
            reg1=regs_out.rd_data1,
            reg2=regs_out.rd_data2,
        )
        if RISCV_TRACE:
            if enabled:
                store = array_to_uint_le(decoded.mem_wr_byte_ens)
                sim_print(
                    f"pc={hex(pc)} inst={hex(inst)} wr={wr.wr_en} rd={wr.addr} data={hex(wr.wr_data)} "
                    f"addr={hex(exe.result)} store={hex(regs_out.rd_data2)} enables={hex(store)}",
                    debug=True,
                )
        # Memory. An idle MMIO port still clocks the peripheral.
        mem = riscv_dmem(
            addr=exe.result, wr_data=regs_out.rd_data2, decoded=decoded, enabled=enabled
        )
        sim_assert(
            halted | ~mem.mem_out_of_range,
            f"bad data address={hex(exe.result)} pc={hex(pc)} inst={hex(inst)}",
        )
        # Writeback. The edge commits rd and feeds the selected PC back to fetch.
        data = select_reg_wr_data(
            decoded=decoded, exe=exe, mem_rd_data=mem.rd_data, pc_plus4=pc_plus4
        )
        wr = wr_port_t(
            addr=decoded.dest,
            wr_data=data,
            wr_en=enabled & decoded.reg_wr & (decoded.dest != 0),
            valid=1,
        )
        rv: riscv_out_t
        # Latch the retirement status, since a live device may change its
        # response once its transfer enables are removed.
        final_value: Reg[uint32_t]
        final_range_error: Reg[uint1_t]
        rv.halt = halted | decoded.halt | mem.halt
        rv.return_value = final_value if halted else mem.return_value
        rv.pc = pc
        rv.unknown_op = decoded.unknown_op
        rv.mem_out_of_range = final_range_error if halted else mem.mem_out_of_range
        if ~rv.halt:
            pc = select_next_pc(decoded=decoded, exe=exe, pc_plus4=pc_plus4)
        elif enabled:
            halted = 1
            final_value = mem.return_value
            final_range_error = mem.mem_out_of_range
        return rv

    return single_cycle_core
