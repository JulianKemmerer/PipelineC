# pyright: reportInvalidTypeForm=none
"""Stream RAM: `make_ram`'s memory behind valid/ready streams, one request
stream and one response stream per port.

    sram, sram_t = make_stream_ram(uint32_t, 1024, ports=("w", "r"), read_latency=1)

    @MAIN
    def top(p0_req_if: sram.p0_req_intrf.fwd_t, p0_resp_if: sram.p0_resp_intrf.fb_t,
            p1_req_if: sram.p1_req_intrf.fwd_t, p1_resp_if: sram.p1_resp_intrf.fb_t) -> sram_t:
        return sram(p0_req_if, p0_resp_if, p1_req_if, p1_resp_if)

This is the pypeline answer to old PipelineC's `DECL_STREAM_RAM_DP_W_R_1`, for
any `make_ram` shape. Backpressure is **ready used as a clock enable**, not a
skid FIFO and not an in-flight counter: each port's whole pipeline (input
registers, the RAM stage, the registered read, output registers) advances
only when its response is accepted or its last stage is empty,

    advance = resp_ready or not last_stage_valid     (resp_ready when latency is 0)
    req_ready = advance

so a stalled port holds every stage, including the block RAM's own output
register, and a request's write executes exactly once -- when its RAM stage
advances. A bubble in the last stage is filled on the next edge, so a port
whose consumer keeps ready high runs at one request per cycle. Ports stall
independently.

Like `make_stream_fifo` over `make_fifo`, the handshake RAM itself is a raw
`vhdl()` core with plain ports (`ram.ram_vhdl_text(cfg, handshake=True)`, the
same generator and simulation model `make_ram` uses), and the function
returned here only gives it interface ports. It is NOT `@pipeline_latency`:
latency varies with backpressure, so it is a stateful block like a FIFO.
`.latency` is the unstalled request-to-response latency.
"""
from pypeline import (
    _exec_generated_func,
    _finalize_hw_name,
    hw_func,
    sim_model,
    uint1_t,
    vhdl,
)

from ram import (
    RAM_GENERATED_FOLDER,
    RamConfig,
    ram_exec_globals,
    ram_make_struct,
    ram_model_class,
    ram_port_payload_fields,
    ram_vhdl_text,
)
from stream.stream import make_stream_interface

_STREAM_RAM_CACHE = {}


def make_stream_ram(
    elem_t,
    size: int,
    ports=("rw",),
    read_latency: int = 1,
    in_regs: int = 0,
    out_regs: int = 0,
    init=None,
    byte_write_enables: bool = False,
):
    """A valid/ready stream RAM. Same arguments and memory semantics as
    `make_ram` (read-first, highest port index wins a write collision, `init`
    from Python values, byte write enables).

    Returns (stream_ram, stream_ram_t):
        stream_ram(p0_req_if: .p0_req_intrf.fwd_t, p0_resp_if: .p0_resp_intrf.fb_t,
                   p1_req_if: ..., p1_resp_if: ..., ...) -> stream_ram_t
        stream_ram_t fields: .p{i}_resp_if (.p{i}_resp_intrf.fwd_t),
                             .p{i}_req_if  (.p{i}_req_intrf.fb_t)

    Per port i:
        request payload  .p{i}_req_t   addr [, wr_data, wr_en]
        response payload .p{i}_resp_t  addr [, wr_data, wr_en] [, rd_data]
    The response echoes the request (write ports' wr_data/wr_en included), plus
    the read data for "rw"/"r" ports. A write happens when a valid request
    with wr_en set advances through the RAM stage.

    With read_latency=0 and out_regs=0 the response's rd_data is a live read of
    the memory: another port's write to that address while the response is
    stalled is visible. Any registered configuration holds rd_data stable.

    attrs: .elem_t .size .addr_t .ports .read_latency .in_regs .out_regs
           .latency .byte_write_enables .we_t .core .out_t
           .req_intrfs .resp_intrfs .req_ts .resp_ts
           .p{i}_req_intrf .p{i}_resp_intrf .p{i}_req_t .p{i}_resp_t
    """
    cfg = RamConfig(
        "make_stream_ram",
        elem_t,
        size,
        ports,
        read_latency,
        in_regs,
        out_regs,
        init,
        byte_write_enables,
    )
    cached = _STREAM_RAM_CACHE.get(cfg.key)
    if cached is not None:
        return cached
    n = len(cfg.ports)

    # One request/response interface per port kind: ports of the same kind
    # share the interface objects (and so their payload types).
    by_kind = {}
    for kind in cfg.ports:
        if kind not in by_kind:
            req_fields, resp_fields = ram_port_payload_fields(cfg, kind)
            req_t = ram_make_struct(f"ram_{kind}_req_t", req_fields)
            resp_t = ram_make_struct(f"ram_{kind}_resp_t", resp_fields)
            by_kind[kind] = (
                req_t,
                resp_t,
                make_stream_interface(req_t),
                make_stream_interface(resp_t),
            )
    req_ts = [by_kind[k][0] for k in cfg.ports]
    resp_ts = [by_kind[k][1] for k in cfg.ports]
    req_intrfs = [by_kind[k][2] for k in cfg.ports]
    resp_intrfs = [by_kind[k][3] for k in cfg.ports]
    req_stream_ts = [intrf.stream_t for intrf in req_intrfs]
    resp_stream_ts = [intrf.stream_t for intrf in resp_intrfs]

    # The raw handshake core: plain stream structs and ready bits.
    core_fields = []
    for i in range(n):
        core_fields += [(f"p{i}_resp", resp_stream_ts[i]), (f"p{i}_req_ready", uint1_t)]
    core_out_t = ram_make_struct("stream_ram_core_out_t", core_fields)
    core_name = _finalize_hw_name(f"stream_ram_core_{cfg.name_fragment}_h{cfg.digest}")
    core_params = ", ".join(
        f"p{i}_req: P{i}_REQ_STREAM_T, p{i}_resp_ready: uint1_t" for i in range(n)
    )
    core_src = (
        "@hw_func\n"
        f"def {core_name}({core_params}) -> CORE_OUT_T:\n"
        "    vhdl(VHDL_TEXT)\n"
    )
    core_ns = {
        "hw_func": hw_func,
        "vhdl": vhdl,
        "uint1_t": uint1_t,
        "CORE_OUT_T": core_out_t,
        "VHDL_TEXT": ram_vhdl_text(cfg, handshake=True),
    }
    for i in range(n):
        core_ns[f"P{i}_REQ_STREAM_T"] = req_stream_ts[i]
    ram_exec_globals(core_ns, cfg.elem_t, core_out_t, *req_stream_ts)
    # Generated entities are described from this frame's arguments: name them
    # after the init contents' digest, never the contents (see make_ram).
    init = cfg.init_desc  # noqa: F841
    core = _exec_generated_func(core_name, core_src, core_ns, folder=RAM_GENERATED_FOLDER)
    sim_model(core)(ram_model_class(cfg, True, None, core_out_t, resp_stream_ts))

    # The interface face.
    out_fields = []
    for i in range(n):
        out_fields += [
            (f"p{i}_resp_if", resp_intrfs[i].fwd_t),
            (f"p{i}_req_if", req_intrfs[i].fb_t),
        ]
    stream_ram_t = ram_make_struct("stream_ram_t", out_fields)
    wrap_name = _finalize_hw_name(f"stream_ram_{cfg.name_fragment}_h{cfg.digest}")
    wrap_params = ", ".join(
        f"p{i}_req_if: P{i}_REQ_FWD_T, p{i}_resp_if: P{i}_RESP_FB_T" for i in range(n)
    )
    core_args = ", ".join(f"p{i}_req_if.stream, p{i}_resp_if.ready" for i in range(n))
    lines = [
        "@hw_func",
        f"def {wrap_name}({wrap_params}) -> STREAM_RAM_T:",
        "    o: STREAM_RAM_T",
        f"    core_out: CORE_OUT_T = CORE({core_args})",
    ]
    for i in range(n):
        lines.append(f"    o.p{i}_resp_if.stream = core_out.p{i}_resp")
        lines.append(f"    o.p{i}_req_if.ready = core_out.p{i}_req_ready")
    lines.append("    return o")
    wrap_ns = {
        "hw_func": hw_func,
        "CORE": core,
        "CORE_OUT_T": core_out_t,
        "STREAM_RAM_T": stream_ram_t,
    }
    for i in range(n):
        wrap_ns[f"P{i}_REQ_FWD_T"] = req_intrfs[i].fwd_t
        wrap_ns[f"P{i}_RESP_FB_T"] = resp_intrfs[i].fb_t
    ram_exec_globals(wrap_ns, stream_ram_t, core_out_t)
    stream_ram = _exec_generated_func(
        wrap_name, "\n".join(lines) + "\n", wrap_ns, folder=RAM_GENERATED_FOLDER
    )

    stream_ram.elem_t = cfg.elem_t
    stream_ram.size = cfg.size
    stream_ram.addr_t = cfg.addr_t
    stream_ram.ports = cfg.ports
    stream_ram.read_latency = cfg.read_latency
    stream_ram.in_regs = cfg.in_regs
    stream_ram.out_regs = cfg.out_regs
    stream_ram.latency = cfg.latency
    stream_ram.byte_write_enables = cfg.byte_write_enables
    stream_ram.we_t = cfg.we_t
    stream_ram.core = core
    stream_ram.out_t = stream_ram_t
    stream_ram.req_intrfs = tuple(req_intrfs)
    stream_ram.resp_intrfs = tuple(resp_intrfs)
    stream_ram.req_ts = tuple(req_ts)
    stream_ram.resp_ts = tuple(resp_ts)
    for i in range(n):
        setattr(stream_ram, f"p{i}_req_intrf", req_intrfs[i])
        setattr(stream_ram, f"p{i}_resp_intrf", resp_intrfs[i])
        setattr(stream_ram, f"p{i}_req_t", req_ts[i])
        setattr(stream_ram, f"p{i}_resp_t", resp_ts[i])
    _STREAM_RAM_CACHE[cfg.key] = (stream_ram, stream_ram_t)
    return stream_ram, stream_ram_t
