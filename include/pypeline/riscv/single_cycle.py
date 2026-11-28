"""Single-cycle RV32I core with separate instruction and data memories.

The core follows the textbook single-cycle datapath (Patterson & Hennessy,
"Computer Organization and Design, RISC-V Edition", section 4.4; Harris &
Harris, "Digital Design and Computer Architecture, RISC-V Edition", section
7.3). Each clock cycle runs one instruction through the five stages that a
five-stage pipeline would spread over five cycles. Each stage is a `@hw_func`,
so the design diagram draws the core as these blocks:

    PC   pc_register  the PC and the halt flag, updated at the clock edge
    IF   if_stage     read the instruction at the PC, and add 4 to the PC
    ID   id_stage     decode (control unit), imm_gen, and read rs1 and rs2
    EX   ex_stage     execute (ALU and branch compare), and the next-PC mux
    MEM  mem_stage    load or store through the data RAM or a device
    WB   wb_stage     the result mux; rd is written at the clock edge

A stage's output struct holds the values that leave it: roughly what a
pipelined core keeps in the register after that stage (IF/ID, ID/EX, EX/MEM,
MEM/WB). Two values go backwards, through `Feedback`: write-back's register
write to the register file in ID, and the next PC and halt request to the PC.

The core differs from the textbook figure in a few ways. Execute also decides
branches and produces the next PC for every jump and branch. Loads and stores
handle bytes and halfwords as well as words. Addresses at or above the
memory-mapped I/O base go to a device instead of the data RAM. ECALL, EBREAK
and a device request halt the core.

See examples/risc-v/risc-v_decl.h for its PipelineC predecessor.
"""

from typing import NamedTuple
from pypeline import *
from ram import make_ram
from cpu.mem_map import AddressMap
from cpu.mem_map_port import address_in_range, region_offset
from riscv.rv32i import (
    BYTE_MASK,
    HALF_MASK,
    decode,
    decoded_t,
    execute,
    imm_gen,
    next_pc_mux,
    result_mux,
)

# Enable a tagged architectural trace in native and HDL simulation.
RISCV_TRACE = param(
    name="RISCV_TRACE",
    default=False,
    help="Trace instruction, register write and store each cycle",
)


@struct
class riscv_out_t(NamedTuple):
    """Status of the instruction executing this cycle."""

    halt: uint1_t  # ECALL, EBREAK or the device stopped the core
    device_status: uint32_t  # a word the memory-mapped device reports
    pc: uint32_t
    illegal_instruction: uint1_t  # an encoding RV32I does not define
    mem_out_of_range: uint1_t  # a misaligned or unmapped load or store


@struct
class pc_out_t(NamedTuple):
    pc: uint32_t  # the address of this cycle's instruction
    running: uint1_t  # 0 once the core has halted
    halt: uint1_t  # halted, or halting at the end of this cycle


@struct
class if_out_t(NamedTuple):
    pc: uint32_t  # the instruction's address, for the stages that need it
    instr: uint32_t
    pc_plus4: uint32_t


@struct
class reg_file_out_t(NamedTuple):
    read_data1: uint32_t  # the value of register rs1
    read_data2: uint32_t  # the value of register rs2


@struct
class id_out_t(NamedTuple):
    decoded: decoded_t  # the instruction's fields and control signals
    imm: int32_t
    read_data1: uint32_t
    read_data2: uint32_t


@struct
class ex_out_t(NamedTuple):
    alu_result: uint32_t  # arithmetic result, memory address or jump target
    next_pc: uint32_t


@struct
class mem_out_t(NamedTuple):
    read_data: uint32_t  # the loaded byte, halfword or word, extended to 32 bits
    mem_out_of_range: uint1_t
    device_halt: uint1_t  # the device asks the core to halt
    device_status: uint32_t


@struct
class reg_write_t(NamedTuple):
    """The register file's write port: write `write_data` to `rd` if `reg_write`."""

    rd: uint5_t
    write_data: uint32_t
    reg_write: uint1_t


@struct
class wb_out_t(NamedTuple):
    rd_write: reg_write_t  # to the register file, written at the clock edge
    halt: uint1_t  # ECALL, EBREAK or the device: stop after this instruction


def make_rv32i_single_cycle_core(*, imem_init, dmem_init, mem_map, layout=AddressMap()):
    """Return the core as a hardware function with no arguments.

    `imem_init` and `dmem_init` are the memories' initial 32-bit words.
    `mem_map` is the `@hw_func` that answers loads and stores in the
    memory-mapped I/O window. `layout` gives each region's base and size in bytes.
    """
    reset_vector = layout.imem_base
    data_base = layout.dmem_base
    mmio_base = layout.mmio_base
    # Inclusive last addresses also represent regions ending at 2**32.
    imem_last = layout.imem_last
    dmem_last = layout.dmem_last
    mmio_last = layout.mmio_last
    # The instruction memory is a ROM; the register file has two read ports
    # and one write port; the data memory writes individual bytes. All three
    # read combinationally (read_latency=0) and write at the clock edge.
    imem = make_ram(
        elem_t=uint32_t,
        size=layout.imem_size // 4,
        ports=("r",),
        read_latency=0,
        init=imem_init,
    )
    regs = make_ram(elem_t=uint32_t, size=32, ports=("r", "r", "w"), read_latency=0)
    dmem = make_ram(
        elem_t=uint32_t,
        size=layout.dmem_size // 4,
        ports=("rw",),
        read_latency=0,
        byte_write_enables=True,
        init=dmem_init,
    )
    # A RAM's word index is bits hi:2 of the byte offset from its base; bits
    # 1:0 pick the byte within the word.
    imem_hi = 1 + len(imem.addr_t)
    dmem_hi = 1 + len(dmem.addr_t)
    # A power-of-two DMEM uses every index value, so any address can index it.
    # Otherwise an address past the end needs guarding before it indexes the RAM.
    full_index_range = (
        layout.dmem_size > 4 and layout.dmem_size & (layout.dmem_size - 1) == 0
    )

    @hw_func
    def pc_register(next_pc: uint32_t, halt_request: uint1_t) -> pc_out_t:
        """PC: the program counter, loaded with the next PC at the clock edge.

        A halt sends the PC back to the reset vector and holds it there; while
        halted, `running` is 0 and the core writes no register or memory.
        Only IF reads the PC from here; IF passes it on to the later stages.
        """
        pc: Reg[uint32_t] = reset_vector
        halted: Reg[uint1_t]
        rv: pc_out_t
        rv.pc = pc
        rv.running = ~halted
        rv.halt = halted | halt_request
        pc = next_pc
        if rv.halt:
            pc = reset_vector
            halted = 1
        return rv

    @hw_func
    def if_stage(pc: uint32_t) -> if_out_t:
        """IF: read the instruction at the PC, and compute PC + 4."""
        offset: uint32_t = region_offset(addr=pc, base=reset_vector)
        in_rom = address_in_range(addr=pc, base=reset_vector, last=imem_last)
        rom = imem(p0=imem.p0_in_t(addr=offset[imem_hi:2], valid=1))
        pc_plus4: uint32_t = pc + 4
        rv: if_out_t
        rv.pc = pc
        rv.instr = rom.p0.rd_data
        rv.pc_plus4 = pc_plus4
        sim_assert(
            in_rom & (pc[1:0] == 0),
            f"invalid fetch pc={hex(pc)} instr={hex(rv.instr)}",
        )
        return rv

    @hw_func
    def register_file(
        rs1: uint5_t, rs2: uint5_t, rd_write: reg_write_t, running: uint1_t
    ) -> reg_file_out_t:
        """Read registers rs1 and rs2 (ID). Write register rd at the clock edge (WB).

        Register x0 always reads zero and is never written. Reads see the
        values from before this cycle's write. A halted core writes nothing.
        """
        ram = regs(
            p0=regs.p0_in_t(addr=rs1, valid=1),
            p1=regs.p1_in_t(addr=rs2, valid=1),
            p2=regs.p2_in_t(
                addr=rd_write.rd,
                wr_data=rd_write.write_data,
                wr_en=running & rd_write.reg_write & (rd_write.rd != 0),
                valid=1,
            ),
        )
        rv: reg_file_out_t
        if rs1 != 0:
            rv.read_data1 = ram.p0.rd_data
        if rs2 != 0:
            rv.read_data2 = ram.p1.rd_data
        return rv

    @hw_func
    def id_stage(
        pc: uint32_t, instr: uint32_t, rd_write: reg_write_t, running: uint1_t
    ) -> id_out_t:
        """ID: decode the instruction, generate its immediate, read rs1 and rs2.

        `rd_write` is write-back's register write, which comes back from WB.
        """
        rv: id_out_t
        rv.decoded = decode(instr=instr)
        sim_assert(
            ~rv.decoded.illegal_instruction,
            f"illegal instruction pc={hex(pc)} instr={hex(instr)}",
        )
        rv.imm = imm_gen(instr=instr)
        regs_read = register_file(
            rs1=rv.decoded.rs1,
            rs2=rv.decoded.rs2,
            rd_write=rd_write,
            running=running,
        )
        rv.read_data1 = regs_read.read_data1
        rv.read_data2 = regs_read.read_data2
        return rv

    @hw_func
    def ex_stage(pc: uint32_t, pc_plus4: uint32_t, id_out: id_out_t) -> ex_out_t:
        """EX: compute the result, the memory address or the jump target, and the next PC."""
        rv: ex_out_t
        rv.alu_result = execute(
            pc=pc,
            pc_plus4=pc_plus4,
            decoded=id_out.decoded,
            imm=id_out.imm,
            read_data1=id_out.read_data1,
            read_data2=id_out.read_data2,
        )
        rv.next_pc = next_pc_mux(
            decoded=id_out.decoded, alu_result=rv.alu_result, pc_plus4=pc_plus4
        )
        return rv

    @hw_func
    def mem_stage(
        pc: uint32_t,
        address: uint32_t,
        write_data: uint32_t,
        decoded: decoded_t,
        running: uint1_t,
    ) -> mem_out_t:
        """MEM: load or store through the data RAM, or through the device.

        Memory is 32 bits wide. A byte or halfword access uses some byte lanes
        of the word at `address` with its low two bits cleared: a store
        shifts its data and byte mask up to the lanes it writes, and a load
        selects its lanes from the word it reads.
        """
        # Which bytes of the word: the decoder's mask moved up by the byte
        # offset, and store data moved up by eight bits per byte of offset.
        byte_offset = address[1:0]
        mask = decoded.mem_byte_mask
        lanes: uint4_t = mask << byte_offset
        shift: uint5_t = concat(byte_offset, uint3_t(0))
        lane_data: uint32_t = write_data << shift
        # Natural alignment: a word at a multiple of 4, a halfword at an even
        # address. mask[3] is set only for a word, mask[1] for a halfword or word.
        aligned = ~((mask[3] & (byte_offset != 0)) | (mask[1] & address[0]))
        in_ram = address_in_range(addr=address, base=data_base, last=dmem_last)
        in_mmio = address_in_range(addr=address, base=mmio_base, last=mmio_last)

        # The data RAM. The read address can change freely; only an aligned
        # store inside the RAM, while the core runs, writes it.
        ram_offset: uint32_t = region_offset(addr=address, base=data_base)
        index: dmem.addr_t = 0
        if full_index_range:
            index = ram_offset[dmem_hi:2]
        elif in_ram:
            index = ram_offset[dmem_hi:2]
        ram_write: uint4_t = 0
        if running & aligned & in_ram & decoded.mem_write:
            ram_write = lanes
        ram = dmem(
            p0=dmem.p0_in_t(
                addr=index,
                wr_data=lane_data,
                wr_en=uint_to_array_le(ram_write, 1),
                valid=1,
            )
        )

        # The memory-mapped device sees every cycle, idle ones included, so it
        # keeps its own clock. Only nonzero byte enables make a transfer, and
        # only addresses inside the I/O window reach it.
        device_write: uint4_t = 0
        device_read: uint4_t = 0
        if running & aligned & in_mmio:
            if decoded.mem_write:
                device_write = lanes
            if decoded.mem_read:
                device_read = lanes
        device = mem_map(
            addr=concat(address[31:2], uint2_t(0)),
            wr_data=lane_data,
            wr_byte_ens=uint_to_array_le(device_write, 1),
            rd_byte_ens=uint_to_array_le(device_read, 1),
        )

        rv: mem_out_t
        rv.mem_out_of_range = (
            running
            & (decoded.mem_read | decoded.mem_write)
            & ~(aligned & (in_ram | (in_mmio & device.addr_is_mapped)))
        )
        sim_assert(
            ~rv.mem_out_of_range,
            f"bad data address={hex(address)} pc={hex(pc)}",
        )
        rv.device_halt = device.halt
        rv.device_status = device.device_status
        # A load picks its byte or halfword out of the word, then extends it
        # to 32 bits with copies of its sign bit or with zeros.
        word: uint32_t = device.rd_data if in_mmio else ram.p0.rd_data
        rv.read_data = word
        if mask == BYTE_MASK:
            bytes_of_word: uint8_t[4] = uint_to_array_le(word, 8)
            byte_val: uint8_t = bytes_of_word[byte_offset]
            rv.read_data = byte_val
            if decoded.mem_sign_extend:
                rv.read_data = int32_t(int8_t(byte_val))
        elif mask == HALF_MASK:
            halves_of_word: uint16_t[2] = uint_to_array_le(word, 16)
            half_val = halves_of_word[address[1]]
            rv.read_data = half_val
            if decoded.mem_sign_extend:
                rv.read_data = int32_t(int16_t(half_val))
        return rv

    @hw_func
    def wb_stage(
        decoded: decoded_t,
        alu_result: uint32_t,
        read_data: uint32_t,
        pc_plus4: uint32_t,
        device_halt: uint1_t,
    ) -> wb_out_t:
        """WB: pick the result for rd, and finish the instruction.

        ECALL, EBREAK and a device request halt the core after this instruction.
        """
        rv: wb_out_t
        rv.rd_write.rd = decoded.rd
        rv.rd_write.write_data = result_mux(
            decoded=decoded,
            alu_result=alu_result,
            read_data=read_data,
            pc_plus4=pc_plus4,
        )
        rv.rd_write.reg_write = decoded.reg_write
        rv.halt = decoded.is_ecall | decoded.is_ebreak | device_halt
        return rv

    @hw_func
    def single_cycle_core() -> riscv_out_t:
        # Values that later stages compute and earlier ones use, in the same
        # clock cycle: the next PC and halt request, and the register write.
        ex_out: Feedback[ex_out_t]
        wb_out: Feedback[wb_out_t]

        pc_out = pc_register(next_pc=ex_out.next_pc, halt_request=wb_out.halt)
        if_out = if_stage(pc=pc_out.pc)
        id_out = id_stage(
            pc=if_out.pc,
            instr=if_out.instr,
            rd_write=wb_out.rd_write,
            running=pc_out.running,
        )
        ex_out = ex_stage(pc=if_out.pc, pc_plus4=if_out.pc_plus4, id_out=id_out)
        # Print before the memory stage: a store to the simulation-control
        # device ends the simulation during that call.
        if RISCV_TRACE:
            if pc_out.running:
                sim_print(
                    f"pc={hex(if_out.pc)} instr={hex(if_out.instr)} "
                    f"reg_write={wb_out.rd_write.reg_write} rd={wb_out.rd_write.rd} "
                    f"data={hex(wb_out.rd_write.write_data)} "
                    f"mem_write={id_out.decoded.mem_write} addr={hex(ex_out.alu_result)} "
                    f"store={hex(id_out.read_data2)} mask={hex(id_out.decoded.mem_byte_mask)}",
                    debug=True,
                )
        # rs2's value is the store data.
        mem_out = mem_stage(
            pc=if_out.pc,
            address=ex_out.alu_result,
            write_data=id_out.read_data2,
            decoded=id_out.decoded,
            running=pc_out.running,
        )
        wb_out = wb_stage(
            decoded=id_out.decoded,
            alu_result=ex_out.alu_result,
            read_data=mem_out.read_data,
            pc_plus4=if_out.pc_plus4,
            device_halt=mem_out.device_halt,
        )

        rv: riscv_out_t
        rv.pc = pc_out.pc
        rv.halt = pc_out.halt
        rv.illegal_instruction = id_out.decoded.illegal_instruction
        rv.mem_out_of_range = mem_out.mem_out_of_range
        rv.device_status = mem_out.device_status
        return rv

    return single_cycle_core
