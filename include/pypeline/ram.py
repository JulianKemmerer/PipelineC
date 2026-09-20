# pyright: reportInvalidTypeForm=none
"""RAMs: one parameterized generator for every shape old PipelineC's
`include/ram.h` spelled out as a separate macro (single/dual/triple port,
read+write/read-only/write-only ports, 0/1/2 clocks of latency, byte write
enables).

`make_auto_pipeline_ram` adds measured BRAM register placement and depth
splitting. It has a minimum one-cycle read and a relaxed collision contract;
see docs/AUTO_PIPELINE_DESIGN.md. The manual factory's semantics follow below.

    ram, ram_out_t = make_ram(uint32_t, 1024, ports=("w", "r"), read_latency=1)
    o = ram(ram.p0_in_t(addr=wa, wr_data=wd, wr_en=we, valid=1),
            ram.p1_in_t(addr=ra, valid=1))
    o.p1.rd_data    # ram.latency clocks after the request, aligned with o.p1.addr/.valid

Like `fifo.py`, the hardware is a raw `vhdl()` body with a Python `@sim_model`
attached. Unlike a FIFO, a plain RAM is a fixed pipeline: every output appears
exactly `in_regs + read_latency + out_regs` clocks after its request, so the
function is declared `@pipeline_latency(latency)` and pure callers get their
other paths aligned around it. `stream/stream_ram.py`'s `make_stream_ram`
reuses everything here with a valid/ready handshake instead (variable latency,
so that one is not tagged).

The VHDL and the simulation model are both driven by one `RamConfig`, and walk
the same per-port stage structure:

    stage 0            the port's request (addr, wr_data, wr_en, valid) as a bundle
    stages 1..in_regs  input registers
    stage R=in_regs    the RAM stage: writes happen here, and the read address is taken here
    read_latency=1     the registered (BRAM) read
    out_regs           output registers, carrying read data plus the whole bundle

Semantics shared by both:
  - read-first: every read sees the memory as of the start of the cycle;
  - several writes to the same address/bits in one cycle: the highest port
    index wins (VHDL last-assignment order; undefined on real block RAM);
  - every register is gated by CLOCK_ENABLE (and, for a stream RAM, by that
    port's ready-as-clock-enable);
  - a `size` that is not a power of two wraps the address `mod size` in
    simulation only; an out-of-range address is undefined in hardware.

The memory is a signal-based array of std_logic_vector written from one
clocked process (no shared variables: the cocotb/PyRTL GHDL runs do not pass
-frelaxed). Elements are packed with the same leaf walk `type_to_bytes` uses,
so `init=` becomes a plain bit-string aggregate generated here from Python
values, and the model starts from the very same normalized values.
"""
import copy
import hashlib
import pypeline as py
import operator
from typing import NamedTuple

from pypeline import (
    _array_elem_ctype,
    _array_len,
    _collect_enum_types,
    _collect_struct_types,
    _enumerate_leaves,
    _exec_generated_func,
    _finalize_hw_name,
    _is_scalar_pypeline_int,
    _leaf_bit_width,
    _mangle_type,
    _sim_cast,
    _sim_cast_deep,
    _sw_leaf_get,
    ctype_name,
    make_uint_t,
    pipeline_latency,
    sim_model,
    sim_zero,
    struct,
    uint1_t,
    vhdl,
)

# One entry per port in `ports=`: what the port can do.
RAM_PORT_KINDS = ("rw", "r", "w")

# Where generated RAM functions' synthetic source files live (cosmetic: it is
# only the directory component of the linecache path / generated VHDL folder).
RAM_GENERATED_FOLDER = "pypeline_generated_rams"

_RAM_CACHE = {}


# ─────────────────────────────────────────────
# Element types: widths, VHDL conversions, init values
# ─────────────────────────────────────────────


def _is_enum(t):
    return getattr(t, "_pypeline_is_enum", False)


def _is_scalar(t):
    """uintN_t/intN_t/char_t/@enum -- carried as unsigned/signed in VHDL.
    (Arrays are excluded explicitly: an array ctype also answers `.width`.)"""
    return (
        not hasattr(t, "_fields")
        and _array_elem_ctype(t) is None
        and _is_scalar_pypeline_int(t)
    )


def _is_signed_scalar(t):
    return _is_scalar(t) and not _is_enum(t) and str(t).startswith("int")


def _type_label(t):
    return getattr(t, "_pypeline_ctype_name", None) or str(t)


def ram_elem_width(t):
    """Bits one element occupies: the sum of its scalar leaves, exactly the
    `<T>_to_slv` packing (first field / element 0 in the lowest bits)."""
    return sum(_leaf_bit_width(leaf_t) for _, leaf_t in _enumerate_leaves(t))


def _check_elem_t(func_name, t):
    if _is_scalar(t) or hasattr(t, "_fields") or _array_elem_ctype(t) is not None:
        return
    raise TypeError(
        f"{func_name}: elem_t must be a pypeline type (uintN_t/intN_t/char_t, an "
        f"@enum, an @struct, or an array of those), got {t!r}"
    )


def _vhdl_to_slv(t, expr):
    """VHDL expression packing a value of type t into std_logic_vector."""
    if _is_scalar(t):
        return f"std_logic_vector({expr})"
    return f"{_mangle_type(ctype_name(t))}_to_slv({expr})"


def _vhdl_from_slv(t, slv):
    """VHDL expression unpacking a `downto` std_logic_vector into type t.

    Scalars convert directly: an @enum wire is `unsigned(W-1 downto 0)` and
    has no slv_to_ helper, and int1_t has none either. `slv` must be a
    `(W-1 downto 0)` signal: the generated struct/array helpers index their
    argument from bit 0, so neither an offset slice nor a bit-string literal
    (ascending range) may be passed to them."""
    if _is_scalar(t):
        return f"{'signed' if _is_signed_scalar(t) else 'unsigned'}({slv})"
    return f"slv_to_{_mangle_type(ctype_name(t))}({slv})"


def ram_flatten(t, value):
    """A canonical value of type t as one unsigned integer, leaf 0 in the
    lowest bits, each leaf masked to its width (two's complement)."""
    flat, off = 0, 0
    for path, leaf_t in _enumerate_leaves(t):
        w = _leaf_bit_width(leaf_t)
        flat |= (int(_sw_leaf_get(value, path)) & ((1 << w) - 1)) << off
        off += w
    return flat


def ram_canon_value(t, v, where):
    """Normalize a user-supplied Python value into the shape native sim holds
    for type t (typed SimVal leaves, struct instances, lists/CharArray).

    Accepted: ints (anything with __index__, e.g. numpy integers), bools, enum
    members, a one-character str for a char_t; for arrays a same-length
    sequence (or a str for char_t[N]/uint8_t[N], zero-padded); for @structs an
    instance, a dict (missing fields are zero) or a positional sequence.
    Out-of-range integers are masked like any typed assignment."""
    if _is_scalar(t):
        if isinstance(v, str) and len(v) == 1 and str(t) == "char":
            v = ord(v)
        try:
            iv = operator.index(v)
        except TypeError:
            raise TypeError(
                f"{where}: expected an integer for {_type_label(t)}, got {v!r}"
            ) from None
        return _sim_cast(iv, t)
    elem = _array_elem_ctype(t)
    if elem is not None:
        n = _array_len(t)
        if isinstance(v, str):
            return _sim_cast_deep(v, t)
        try:
            seq = list(v)
        except TypeError:
            raise TypeError(
                f"{where}: expected a sequence of {n} for {_type_label(t)}, got {v!r}"
            ) from None
        if len(seq) != n:
            raise ValueError(
                f"{where}: {_type_label(t)} needs exactly {n} elements, got {len(seq)}"
            )
        items = [ram_canon_value(elem, x, f"{where}[{j}]") for j, x in enumerate(seq)]
        return _sim_cast_deep(items, t)
    fields = t._fields
    if isinstance(v, dict):
        unknown = sorted(set(v) - set(fields))
        if unknown:
            raise ValueError(f"{where}: {_type_label(t)} has no field(s) {unknown}")
        given = v
    elif isinstance(v, tuple) and hasattr(v, "_fields"):
        if tuple(v._fields) != tuple(fields):
            raise TypeError(
                f"{where}: expected a {_type_label(t)} value, got {type(v).__name__}"
            )
        given = {f: getattr(v, f) for f in fields}
    elif isinstance(v, (tuple, list)):
        if len(v) != len(fields):
            raise ValueError(
                f"{where}: {_type_label(t)} has {len(fields)} fields, got {len(v)} values"
            )
        given = dict(zip(fields, v))
    else:
        raise TypeError(f"{where}: expected a {_type_label(t)} value, got {v!r}")
    out = {}
    for f in fields:
        ft = t.__annotations__[f]
        out[f] = (
            ram_canon_value(ft, given[f], f"{where}.{f}")
            if f in given
            else sim_zero(ft)
        )
    return t(**out)


# ─────────────────────────────────────────────
# Configuration shared by make_ram and make_stream_ram
# ─────────────────────────────────────────────


def _check_nonneg_int(func_name, name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{func_name}: {name} must be a non-negative int, got {value!r}")


class RamConfig:
    """Validated, normalized RAM factory arguments and everything derived from
    them. The VHDL generator and the simulation model both read only this, so
    they cannot disagree about widths, stages or initial contents."""

    def __init__(
        self,
        func_name,
        elem_t,
        size,
        ports,
        read_latency,
        in_regs,
        out_regs,
        init,
        byte_write_enables,
    ):
        _check_elem_t(func_name, elem_t)
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ValueError(f"{func_name}: size must be a positive int, got {size!r}")
        if isinstance(ports, str):
            ports = (ports,)
        try:
            ports = tuple(ports)
        except TypeError:
            raise TypeError(
                f"{func_name}: ports must be a sequence of {RAM_PORT_KINDS}, got {ports!r}"
            ) from None
        if not ports:
            raise ValueError(f"{func_name}: ports must name at least one port")
        for kind in ports:
            if kind not in RAM_PORT_KINDS:
                raise ValueError(
                    f"{func_name}: each port must be one of {RAM_PORT_KINDS}, got {kind!r}"
                )
        if isinstance(read_latency, bool) or read_latency not in (0, 1):
            raise ValueError(
                f"{func_name}: read_latency must be 0 (combinational read) or 1 "
                f"(registered/BRAM read), got {read_latency!r}"
            )
        _check_nonneg_int(func_name, "in_regs", in_regs)
        _check_nonneg_int(func_name, "out_regs", out_regs)
        if not isinstance(byte_write_enables, bool):
            raise TypeError(
                f"{func_name}: byte_write_enables must be a bool, got {byte_write_enables!r}"
            )

        self.elem_t = elem_t
        self.size = size
        self.ports = ports
        self.read_latency = read_latency
        self.in_regs = in_regs
        self.out_regs = out_regs
        self.latency = in_regs + read_latency + out_regs
        self.width = ram_elem_width(elem_t)
        self.addr_width = max(1, (size - 1).bit_length())
        # Only then can an address exceed size-1: wrap it (in simulation).
        self.addr_wraps = (1 << self.addr_width) != size
        self.addr_t = make_uint_t(self.addr_width)
        self.compound = not _is_scalar(elem_t)

        self.byte_write_enables = byte_write_enables
        if byte_write_enables:
            if not _is_scalar(elem_t) or _is_enum(elem_t) or self.width % 8 != 0:
                raise ValueError(
                    f"{func_name}: byte_write_enables=True needs a uintN_t/intN_t "
                    f"elem_t whose width is a multiple of 8, got {_type_label(elem_t)}"
                )
            if not any(kind != "r" for kind in ports):
                raise ValueError(
                    f"{func_name}: byte_write_enables=True needs a writable port "
                    f"('rw' or 'w'), got ports={ports!r}"
                )
            self.we_bits = self.width // 8
            self.we_t = uint1_t[self.we_bits]
        else:
            self.we_bits = 1
            self.we_t = uint1_t

        self.init_template, self.init_bits = self._normalize_init(func_name, init)
        key = (
            _type_label(elem_t),
            self.width,
            size,
            ports,
            read_latency,
            in_regs,
            out_regs,
            byte_write_enables,
            tuple(sorted(self.init_bits.items())),
        )
        self.key = repr(key)
        self.digest = hashlib.sha256(self.key.encode()).hexdigest()[:12]
        # What a generated function's name description shows for `init`: the
        # contents' digest, never the contents (see make_ram).
        self.init_desc = (
            "h" + hashlib.sha256(repr(key[-1]).encode()).hexdigest()[:12]
            if self.init_bits
            else None
        )
        self.name_fragment = (
            f"{_mangle_type(_type_label(elem_t))}_{size}_{'_'.join(ports)}"
            f"_rl{read_latency}_in{in_regs}_out{out_regs}"
            + ("_bwe" if byte_write_enables else "")
        )

    def _normalize_init(self, func_name, init):
        size, elem_t = self.size, self.elem_t
        if init is None:
            items = []
        elif isinstance(init, dict):
            items = []
            for k, v in init.items():
                if isinstance(k, bool) or not isinstance(k, int) or not 0 <= k < size:
                    raise ValueError(
                        f"{func_name}: init index {k!r} is not an int in 0..{size - 1}"
                    )
                items.append((k, v))
            items.sort(key=lambda kv: kv[0])
        elif isinstance(init, str) and str(elem_t) != "char":
            raise TypeError(
                f"{func_name}: init must be a sequence or dict of {_type_label(elem_t)} "
                f"values, got a str"
            )
        else:
            try:
                seq = list(init)
            except TypeError:
                raise TypeError(
                    f"{func_name}: init must be None, a sequence, or a dict "
                    f"{{index: value}}, got {init!r}"
                ) from None
            if len(seq) > size:
                raise ValueError(
                    f"{func_name}: init has {len(seq)} values for a RAM of size {size}"
                )
            items = list(enumerate(seq))
        zero = sim_zero(elem_t)
        template = [None] * size
        bits = {}
        for k, v in items:
            value = ram_canon_value(elem_t, v, f"{func_name}: init[{k}]")
            template[k] = value
            flat = ram_flatten(elem_t, value)
            if flat:
                bits[k] = flat
        for k in range(size):
            if template[k] is None:
                template[k] = copy.deepcopy(zero) if self.compound else zero
        return template, bits

    def describe(self):
        return (
            f"{_type_label(self.elem_t)} x {self.size}, ports={self.ports}, "
            f"read_latency={self.read_latency}, in_regs={self.in_regs}, "
            f"out_regs={self.out_regs}, latency={self.latency}"
            + (", byte_write_enables" if self.byte_write_enables else "")
        )


def ram_port_payload_fields(cfg, kind):
    """(request fields, response fields) for one port, no valid bit: the
    stream RAM's payloads. Writable ports carry wr_data/wr_en, readable ports
    add rd_data to the response."""
    req = [("addr", cfg.addr_t)]
    if kind != "r":
        req += [("wr_data", cfg.elem_t), ("wr_en", cfg.we_t)]
    resp = list(req)
    if kind != "w":
        resp.append(("rd_data", cfg.elem_t))
    return req, resp


def ram_make_struct(name, fields):
    """An @struct built from a field list (the RAM's field sets depend on the
    port kinds, so they cannot be written as class bodies)."""
    return struct(NamedTuple(name, fields))


def ram_exec_globals(ns, *types):
    """Seed a generated function's exec globals with every struct/enum type it
    reaches, so the elaborator registers nested types it only sees there
    (same reason make_type_to_bytes does this)."""
    for t in types:
        ns.update(_collect_struct_types(t))
        ns.update(_collect_enum_types(t))
    return ns


# ─────────────────────────────────────────────
# VHDL
# ─────────────────────────────────────────────


class _PortLayout:
    """One port's bundle bit layout and VHDL names.

    Bundle (LSB first): addr | wr_data | wr_en bit(s) | valid. Read-only ports
    have no wr_data/wr_en bits."""

    def __init__(self, cfg, i, kind, handshake):
        self.i = i
        self.writable = kind != "r"
        self.readable = kind != "w"
        aw = cfg.addr_width
        if self.writable:
            self.wd_lo = aw
            self.wd_hi = aw + cfg.width - 1
            self.we_lo = aw + cfg.width
            self.valid_bit = self.we_lo + cfg.we_bits
        else:
            self.valid_bit = aw
        self.bw = self.valid_bit + 1
        self.sig = f"ram_p{i}"
        if handshake:
            self.in_valid = f"p{i}_req.valid"
            self.in_prefix = f"p{i}_req.data."
            self.out_prefix = f"return_output.p{i}_resp.data."
            self.out_valid = f"return_output.p{i}_resp.valid"
        else:
            self.in_valid = f"p{i}.valid"
            self.in_prefix = f"p{i}."
            self.out_prefix = f"return_output.p{i}."
            self.out_valid = f"return_output.p{i}.valid"

    def b(self, stage):
        return f"{self.sig}_b{stage}"


def _vhdl_init_aggregate(cfg):
    if not cfg.init_bits:
        return "(others => (others => '0'))"
    entries = [
        f'    {k} => "{format(v, "0" + str(cfg.width) + "b")}"'
        for k, v in sorted(cfg.init_bits.items())
    ]
    if len(cfg.init_bits) < cfg.size:
        entries.append("    others => (others => '0')")
    return "(\n" + ",\n".join(entries) + "\n  )"


def ram_vhdl_text(cfg, handshake):
    """The raw VHDL architecture body (declarations, begin, statements) for a
    RAM whose ports are `p{i}` (make_ram) or `p{i}_req`/`p{i}_resp_ready`
    (make_stream_ram's handshake core)."""
    L, R = cfg.latency, cfg.in_regs
    layouts = [_PortLayout(cfg, i, kind, handshake) for i, kind in enumerate(cfg.ports)]
    aw = cfg.addr_width
    decl = []
    body = []
    d, s = decl.append, body.append

    d(f"-- {'stream ' if handshake else ''}RAM: {cfg.describe()}")
    d(f"constant RAM_SIZE : integer := {cfg.size};")
    d(f"type ram_mem_t is array(0 to RAM_SIZE-1) of std_logic_vector({cfg.width - 1} downto 0);")
    d(f"signal ram_mem : ram_mem_t := {_vhdl_init_aggregate(cfg)};")
    for p in layouts:
        for stage in range(L + 1):
            d(
                f"signal {p.b(stage)} : std_logic_vector({p.bw - 1} downto 0) "
                f":= (others => '0');"
            )
        if p.readable:
            for stage in range(R + 1, L + 1):
                d(
                    f"signal {p.sig}_rd{stage} : std_logic_vector({cfg.width - 1} downto 0) "
                    f":= (others => '0');"
                )
        if p.writable:
            # Zero-based copy of the echoed wr_data: the generated slv_to_<T>
            # helpers index their argument from bit 0, so an offset slice of
            # the bundle cannot be passed to them directly.
            d(f"signal {p.sig}_wd : std_logic_vector({cfg.width - 1} downto 0);")
        d(f"signal {p.sig}_a : integer range 0 to RAM_SIZE-1 := 0;")
        d(f"signal {p.sig}_en : std_logic;")
        if handshake:
            d(f"signal {p.sig}_adv : std_logic;")

    for p in layouts:
        i = p.i
        # Stage 0: the port's request packed into one bundle.
        parts = [f"std_logic_vector({p.in_valid})"]
        if p.writable:
            if cfg.byte_write_enables:
                parts += [
                    f"std_logic_vector({p.in_prefix}wr_en({j}))"
                    for j in reversed(range(cfg.we_bits))
                ]
            else:
                parts.append(f"std_logic_vector({p.in_prefix}wr_en)")
            parts.append(_vhdl_to_slv(cfg.elem_t, p.in_prefix + "wr_data"))
        parts.append(f"std_logic_vector({p.in_prefix}addr)")
        s(f"{p.b(0)} <= " + " & ".join(parts) + ";")

        # The RAM stage's memory index.
        addr = f"to_integer(unsigned({p.b(R)}({aw - 1} downto 0)))"
        if cfg.addr_wraps:
            s(
                f"{p.sig}_a <= {addr}\n"
                "  -- synthesis translate_off\n"
                "  mod RAM_SIZE\n"
                "  -- synthesis translate_on\n"
                "  ;"
            )
        else:
            s(f"{p.sig}_a <= {addr};")

        # Stage enable: the clock enable, and for a stream RAM that port's
        # ready-as-clock-enable (hold everything while the last stage is an
        # unaccepted response).
        if handshake:
            if L > 0:
                s(f"{p.sig}_adv <= p{i}_resp_ready(0) or not {p.b(L)}({p.valid_bit});")
            else:
                s(f"{p.sig}_adv <= p{i}_resp_ready(0);")
            s(f"{p.sig}_en <= CLOCK_ENABLE(0) and {p.sig}_adv;")
            s(f"return_output.p{i}_req_ready(0) <= {p.sig}_adv;")
        else:
            s(f"{p.sig}_en <= CLOCK_ENABLE(0);")

        # Outputs: the last stage's bundle, plus its read data.
        last = p.b(L)
        s(f"{p.out_prefix}addr <= unsigned({last}({aw - 1} downto 0));")
        if p.writable:
            s(f"{p.sig}_wd <= {last}({p.wd_hi} downto {p.wd_lo});")
            s(f"{p.out_prefix}wr_data <= " + _vhdl_from_slv(cfg.elem_t, f"{p.sig}_wd") + ";")
            if cfg.byte_write_enables:
                for j in range(cfg.we_bits):
                    bit = p.we_lo + j
                    s(f"{p.out_prefix}wr_en({j}) <= unsigned({last}({bit} downto {bit}));")
            else:
                s(f"{p.out_prefix}wr_en <= unsigned({last}({p.we_lo} downto {p.we_lo}));")
        s(f"{p.out_valid} <= unsigned({last}({p.valid_bit} downto {p.valid_bit}));")
        if p.readable:
            # A combinational read with no register after it is a live read.
            rd = f"{p.sig}_rd{L}" if L > R else f"ram_mem({p.sig}_a)"
            s(f"{p.out_prefix}rd_data <= " + _vhdl_from_slv(cfg.elem_t, rd) + ";")

    # One clocked process: ports in index order, so a later port's write to
    # the same bits wins, and every read sees the pre-edge memory (read-first).
    s("process(clk) begin")
    s("  if rising_edge(clk) then")
    for p in layouts:
        stmts = []
        t = stmts.append
        bR = p.b(R)
        if p.writable:
            if cfg.byte_write_enables:
                for j in range(cfg.we_bits):
                    t(f"if {bR}({p.valid_bit}) = '1' and {bR}({p.we_lo + j}) = '1' then")
                    t(
                        f"  ram_mem({p.sig}_a)({8 * j + 7} downto {8 * j}) <= "
                        f"{bR}({p.wd_lo + 8 * j + 7} downto {p.wd_lo + 8 * j});"
                    )
                    t("end if;")
            else:
                t(f"if {bR}({p.valid_bit}) = '1' and {bR}({p.we_lo}) = '1' then")
                t(f"  ram_mem({p.sig}_a) <= {bR}({p.wd_hi} downto {p.wd_lo});")
                t("end if;")
        for stage in range(1, L + 1):
            t(f"{p.b(stage)} <= {p.b(stage - 1)};")
        if p.readable and L > R:
            t(f"{p.sig}_rd{R + 1} <= ram_mem({p.sig}_a);")
            for stage in range(R + 2, L + 1):
                t(f"{p.sig}_rd{stage} <= {p.sig}_rd{stage - 1};")
        if stmts:
            s(f"    if {p.sig}_en = '1' then")
            body.extend("      " + line for line in stmts)
            s("    end if;")
    s("  end if;")
    s("end process;")

    return "\n".join(decl) + "\nbegin\n" + "\n".join(body) + "\n"


# ─────────────────────────────────────────────
# Simulation model
# ─────────────────────────────────────────────


def _bind_args(names, args, kwargs):
    if not kwargs and len(args) == len(names):
        return args
    values = list(args) + [_MISSING] * (len(names) - len(args))
    for k, v in kwargs.items():
        values[names.index(k)] = v
    if _MISSING in values:
        raise TypeError(f"RAM model: missing argument(s) for {names}")
    return values


_MISSING = object()


def ram_model_class(cfg, handshake, port_out_types, out_t, resp_stream_types=None):
    """The @sim_model class for one RAM configuration: cycle-exact against
    ram_vhdl_text(cfg, handshake).

    State: `mem` (the memory), `pending` (writes from the last committed
    evaluation, applied at the next clock edge), and per port a list of the
    committed stage registers `(bundle, rd)` for stages 1..latency.

    `_call_sim_model` deep-copies the committed instance before every
    evaluation, which would copy the whole memory every cycle. `__deepcopy__`
    instead applies the committed instance's pending writes to the shared
    memory list once (then clears them) and returns an instance sharing that
    list: re-evaluations and discarded evaluations only ever append to their
    own `pending`, so the shared memory changes exactly once per clock edge.
    """
    size, L, R = cfg.size, cfg.latency, cfg.in_regs
    kinds = cfg.ports
    elem_t = cfg.elem_t
    compound = cfg.compound
    template = cfg.init_template
    zero_elem = sim_zero(elem_t)
    zero_we = [0] * cfg.we_bits if cfg.byte_write_enables else 0
    byte_masks = (
        [0xFF << (8 * j) for j in range(cfg.we_bits)] if cfg.byte_write_enables else None
    )
    empty = ((0, 0, zero_elem, zero_we), zero_elem)
    if handshake:
        names = [n for i in range(len(kinds)) for n in (f"p{i}_req", f"p{i}_resp_ready")]
        payload_types = [t.__annotations__["data"] for t in resp_stream_types]
    else:
        names = [f"p{i}" for i in range(len(kinds))]

    def own(value):
        return copy.deepcopy(value) if compound else value

    def write_value(value):
        return copy.deepcopy(value) if compound else _sim_cast(value, elem_t)

    class RamModel:
        def __init__(self):
            self.mem = copy.deepcopy(template) if compound else list(template)
            self.pending = []
            self.stages = [[empty] * L for _ in kinds]

        def __deepcopy__(self, memo):
            mem = self.mem
            for addr, value, mask in self.pending:
                if mask is None:
                    mem[addr] = value
                else:
                    merged = (int(mem[addr]) & ~mask) | (int(value) & mask)
                    mem[addr] = _sim_cast(merged, elem_t)
            self.pending = []
            new = RamModel.__new__(RamModel)
            memo[id(self)] = new
            new.mem = mem
            new.pending = []
            new.stages = [list(stage) for stage in self.stages]
            return new

        def __call__(self, *args, **kwargs):
            args = _bind_args(names, args, kwargs)
            mem = self.mem
            out_fields = {}
            for i, kind in enumerate(kinds):
                writable = kind != "r"
                readable = kind != "w"
                stages = self.stages[i]
                if handshake:
                    req = args[2 * i]
                    resp_ready = int(args[2 * i + 1]) & 1
                    x, valid = req.data, int(req.valid) & 1
                else:
                    x = args[i]
                    valid = int(x.valid) & 1
                if writable:
                    we = [int(e) & 1 for e in x.wr_en] if byte_masks else int(x.wr_en) & 1
                    b0 = (valid, x.addr, own(x.wr_data), we)
                else:
                    b0 = (valid, x.addr, zero_elem, zero_we)

                def bundle(stage):
                    return b0 if stage == 0 else stages[stage - 1][0]

                out = bundle(L)
                if readable:
                    rd = stages[L - 1][1] if L > R else mem[int(bundle(R)[1]) % size]

                if handshake:
                    advance = resp_ready | (1 - out[0]) if L > 0 else resp_ready
                else:
                    advance = 1
                if advance:
                    at_ram = bundle(R)
                    index = int(at_ram[1]) % size
                    if writable and at_ram[0]:
                        if byte_masks is None:
                            if at_ram[3]:
                                self.pending.append((index, write_value(at_ram[2]), None))
                        else:
                            mask = 0
                            for j, m in enumerate(byte_masks):
                                if at_ram[3][j]:
                                    mask |= m
                            if mask:
                                self.pending.append((index, at_ram[2], mask))
                    shifted = []
                    for stage in range(1, L + 1):
                        if stage <= R:
                            rd_stage = zero_elem
                        elif stage == R + 1:
                            rd_stage = own(mem[index]) if readable else zero_elem
                        else:
                            rd_stage = stages[stage - 2][1]
                        shifted.append((bundle(stage - 1), rd_stage))
                    self.stages[i] = shifted

                fields = {"addr": out[1]}
                if writable:
                    fields["wr_data"] = own(out[2])
                    fields["wr_en"] = list(out[3]) if byte_masks else out[3]
                if readable:
                    fields["rd_data"] = own(rd)
                if handshake:
                    payload = payload_types[i](**fields)
                    out_fields[f"p{i}_resp"] = resp_stream_types[i](data=payload, valid=out[0])
                    out_fields[f"p{i}_req_ready"] = advance
                else:
                    fields["valid"] = out[0]
                    out_fields[f"p{i}"] = port_out_types[i](**fields)
            return out_t(**out_fields)

    RamModel.__qualname__ = RamModel.__name__ = (
        "StreamRamModel" if handshake else "RamModel"
    )
    return RamModel


# ─────────────────────────────────────────────
# make_ram
# ─────────────────────────────────────────────


def make_ram(
    elem_t,
    size: int,
    ports=("rw",),
    read_latency: int = 1,
    in_regs: int = 0,
    out_regs: int = 0,
    init=None,
    byte_write_enables: bool = False,
):
    """A RAM of `size` elements of `elem_t`, with one port per entry of `ports`.

    Returns (ram, ram_out_t):
        ram(p0: ram.p0_in_t, p1: ram.p1_in_t, ...) -> ram_out_t
        ram_out_t fields: .p0 (ram.p0_out_t), .p1 (ram.p1_out_t), ...

    Port kinds and their structs:
        "rw"  in: addr, wr_data, wr_en, valid    out: addr, wr_data, wr_en, valid, rd_data
        "w"   in: addr, wr_data, wr_en, valid    out: addr, wr_data, wr_en, valid
        "r"   in: addr, valid                    out: addr, valid, rd_data
    A write happens when wr_en & valid. Every output field is the request's
    input piped through, aligned with that request's rd_data.

    Latency (the function is @pipeline_latency(ram.latency)):
        read_latency  0 = combinational (LUTRAM-style) read, 1 = registered (BRAM) read
        in_regs       input register stages before the memory (writes are delayed too)
        out_regs      output register stages after the read
        latency       in_regs + read_latency + out_regs, the same for every port

    `addr` is uintN_t, N = ceil(log2(size)) (ram.addr_t). `init` is None
    (zeros), a sequence of up to `size` values, or a dict {index: value}; values
    are plain Python/pypeline values of elem_t (ints, @struct instances or
    dicts, nested lists for array elements, enum members, str for char_t[N]).
    `byte_write_enables=True` makes wr_en a uint1_t[N // 8] for a uintN_t/intN_t
    elem_t. A RAM with only "r" ports and an init is a ROM.

    attrs: .elem_t .size .addr_t .ports .read_latency .in_regs .out_regs
           .latency .byte_write_enables .we_t .in_ts .out_ts .out_t
           .p{i}_in_t .p{i}_out_t
    """
    cfg = RamConfig(
        "make_ram",
        elem_t,
        size,
        ports,
        read_latency,
        in_regs,
        out_regs,
        init,
        byte_write_enables,
    )
    cached = _RAM_CACHE.get(cfg.key)
    if cached is not None:
        return cached

    in_ts, out_ts = [], []
    for kind in cfg.ports:
        req_fields, resp_fields = ram_port_payload_fields(cfg, kind)
        in_ts.append(ram_make_struct(f"ram_{kind}_in_t", req_fields + [("valid", uint1_t)]))
        out_fields = [f for f in resp_fields if f[0] != "rd_data"] + [("valid", uint1_t)]
        if kind != "w":
            out_fields.append(("rd_data", cfg.elem_t))
        out_ts.append(ram_make_struct(f"ram_{kind}_out_t", out_fields))
    ram_out_t = ram_make_struct(
        "ram_out_t", [(f"p{i}", t) for i, t in enumerate(out_ts)]
    )

    func_name = _finalize_hw_name(f"ram_{cfg.name_fragment}_h{cfg.digest}")
    params = ", ".join(f"p{i}: P{i}_IN_T" for i in range(len(cfg.ports)))
    src = (
        f"@pipeline_latency({cfg.latency})\n"
        f"def {func_name}({params}) -> RAM_OUT_T:\n"
        f"    vhdl(VHDL_TEXT)\n"
    )
    ns = {
        "pipeline_latency": pipeline_latency,
        "vhdl": vhdl,
        "RAM_OUT_T": ram_out_t,
        "VHDL_TEXT": ram_vhdl_text(cfg, handshake=False),
    }
    for i, t in enumerate(in_ts):
        ns[f"P{i}_IN_T"] = t
    ram_exec_globals(ns, cfg.elem_t, ram_out_t, *in_ts)
    # _exec_generated_func describes the generated entity from THIS frame's
    # arguments; name it after the contents' digest, never the contents (a
    # 64K-entry list, or a numpy array whose repr truncates).
    init = cfg.init_desc  # noqa: F841
    ram = _exec_generated_func(func_name, src, ns, folder=RAM_GENERATED_FOLDER)
    sim_model(ram)(ram_model_class(cfg, False, out_ts, ram_out_t))

    ram.elem_t = cfg.elem_t
    ram.size = cfg.size
    ram.addr_t = cfg.addr_t
    ram.ports = cfg.ports
    ram.read_latency = cfg.read_latency
    ram.in_regs = cfg.in_regs
    ram.out_regs = cfg.out_regs
    ram.latency = cfg.latency
    ram.byte_write_enables = cfg.byte_write_enables
    ram.we_t = cfg.we_t
    ram.in_ts = tuple(in_ts)
    ram.out_ts = tuple(out_ts)
    ram.out_t = ram_out_t
    for i in range(len(cfg.ports)):
        setattr(ram, f"p{i}_in_t", in_ts[i])
        setattr(ram, f"p{i}_out_t", out_ts[i])
    _RAM_CACHE[cfg.key] = (ram, ram_out_t)
    return ram, ram_out_t


# Auto-pipelined synchronous RAMs (see AUTO_PIPELINE_DESIGN.md).


def _auto_pipeline_ram_vhdl(cfg, plan):
    """A binary request tree and return tree around synchronous leaf arrays.

    Request valid selects one bank. Return valid travels with the data, avoiding
    a high-fanout global bank-select bus on the read tree. Echo fields use the
    same total latency but need not fan out to every memory leaf.
    """
    decl, body, clocked = [], [], []
    d, s, c = decl.append, body.append, clocked.append
    L, D = plan.latency, plan.split_depth
    bank_depth = 1 << max(0, cfg.addr_width - D)
    local_bits = max(0, cfg.addr_width - D)
    layouts = [_PortLayout(cfg, i, k, False) for i, k in enumerate(cfg.ports)]
    d(f"-- auto-pipelined RAM: {plan.record()}")
    d(
        f"type auto_pipeline_ram_mem_t is array(0 to {bank_depth - 1}) of std_logic_vector({cfg.width-1} downto 0);"
    )
    d("attribute ram_style : string;")
    d("attribute no_rw_check : boolean;")
    for b in range(plan.banks):
        entries = [
            f'{a-b*bank_depth} => "{v:0{cfg.width}b}"'
            for a, v in sorted(cfg.init_bits.items())
            if a // bank_depth == b
        ]
        if len(entries) < bank_depth:
            entries.append("others => (others => '0')")
        mem = f"auto_pipeline_ram_mem_b{b}"
        d(f"signal {mem} : auto_pipeline_ram_mem_t := ({', '.join(entries)});")
        d(f'attribute ram_style of {mem} : signal is "block";')
        d(f"attribute no_rw_check of {mem} : signal is true;")

    def qdecl(name):
        d(
            f"signal {name} : std_logic_vector({cfg.width-1} downto 0) := (others => '0');"
        )
        d(f"signal {name}_v : std_logic := '0';")

    for p in layouts:
        for stage in range(L + 1):
            d(
                f"signal {p.b(stage)} : std_logic_vector({p.bw-1} downto 0) := (others => '0');"
            )
        parts = [f"std_logic_vector({p.in_valid})"]
        if p.writable:
            if cfg.byte_write_enables:
                parts += [
                    f"std_logic_vector({p.in_prefix}wr_en({j}))"
                    for j in reversed(range(cfg.we_bits))
                ]
            else:
                parts.append(f"std_logic_vector({p.in_prefix}wr_en)")
            parts.append(_vhdl_to_slv(cfg.elem_t, p.in_prefix + "wr_data"))
        parts.append(f"std_logic_vector({p.in_prefix}addr)")
        s(f"{p.b(0)} <= {' & '.join(parts)};")
        for stage in range(1, L + 1):
            c(f"{p.b(stage)} <= {p.b(stage-1)};")

        root = f"rq_p{p.i}_d0_n0"
        d(f"signal {root} : std_logic_vector({p.bw-1} downto 0);")
        src = p.b(plan.input_regs)
        s(
            f"{root}({p.bw-1} downto {cfg.addr_width}) <= {src}({p.bw-1} downto {cfg.addr_width});"
        )
        addr_expr = f"to_integer(unsigned({src}({cfg.addr_width-1} downto 0)))"
        if cfg.addr_wraps:
            addr_expr += f"\n-- synthesis translate_off\nmod {cfg.size}\n-- synthesis translate_on\n"
        s(
            f"{root}({cfg.addr_width-1} downto 0) <= std_logic_vector(to_unsigned({addr_expr}, {cfg.addr_width}));"
        )
        for level in range(1, D + 1):
            bit = cfg.addr_width - level
            for n in range(1 << level):
                name = f"rq_p{p.i}_d{level}_n{n}"
                parent = f"rq_p{p.i}_d{level-1}_n{n//2}"
                d(
                    f"signal {name} : std_logic_vector({p.bw-1} downto 0) := (others => '0');"
                )
                emit = c if level <= plan.request_levels else s
                emit(
                    f"{name}({p.valid_bit-1} downto 0) <= {parent}({p.valid_bit-1} downto 0);"
                )
                condition = f"{parent}({bit})" if n % 2 else f"not {parent}({bit})"
                emit(
                    f"{name}({p.valid_bit}) <= {parent}({p.valid_bit}) and {condition};"
                )

        for b in range(plan.banks):
            req = f"rq_p{p.i}_d{D}_n{b}"
            mem = f"auto_pipeline_ram_mem_b{b}"
            addr = (
                f"to_integer(unsigned({req}({local_bits-1} downto 0)))"
                if local_bits
                else "0"
            )
            if p.readable:
                q = f"rd_p{p.i}_d{D}_n{b}"
                qdecl(q)
                memory_q = q
                if D and plan.output_regs:
                    # Keep the first extra output register directly beside
                    # each BRAM, BEFORE any return mux. Placing it only at the
                    # root leaves a LUT on the slow BRAM clk-to-Q path.
                    memory_q = q + "_memory"
                    qdecl(memory_q)
                    c(f"{q} <= {memory_q};")
                    c(f"{q}_v <= {memory_q}_v;")
                c(f"{memory_q}_v <= {req}({p.valid_bit});")
                c(
                    f"if {req}({p.valid_bit}) = '1' then {memory_q} <= {mem}({addr}); end if;"
                )
            if p.writable:
                for byte in range(cfg.we_bits):
                    lo, hi = (
                        (8 * byte, 8 * byte + 7)
                        if cfg.byte_write_enables
                        else (0, cfg.width - 1)
                    )
                    c(
                        f"if {req}({p.valid_bit}) = '1' and {req}({p.we_lo+byte}) = '1' then"
                    )
                    c(
                        f"  {mem}({addr})({hi} downto {lo}) <= {req}({p.wd_lo+hi} downto {p.wd_lo+lo});"
                    )
                    c("end if;")
        if p.readable:
            for level in reversed(range(D)):
                # Register the levels nearest the leaves first.
                registered = D - level <= plan.response_levels
                for n in range(1 << level):
                    q = f"rd_p{p.i}_d{level}_n{n}"
                    left, right = (f"rd_p{p.i}_d{level+1}_n{2*n+j}" for j in (0, 1))
                    qdecl(q)
                    emit = c if registered else s
                    emit(f"{q}_v <= {left}_v or {right}_v;")
                    if registered:
                        emit(
                            f"if {left}_v = '1' then {q} <= {left}; else {q} <= {right}; end if;"
                        )
                    else:
                        emit(f"{q} <= {left} when {left}_v = '1' else {right};")
            q = f"rd_p{p.i}_d0_n0"
            for stage in range(plan.output_regs - int(bool(D and plan.output_regs))):
                reg = f"rd_p{p.i}_out{stage}"
                qdecl(reg)
                c(f"{reg} <= {q};")
                c(f"{reg}_v <= {q}_v;")
                q = reg
            s(f"{p.out_prefix}rd_data <= {_vhdl_from_slv(cfg.elem_t, q)};")
        last = p.b(L)
        s(f"{p.out_prefix}addr <= unsigned({last}({cfg.addr_width-1} downto 0));")
        s(f"{p.out_valid} <= unsigned({last}({p.valid_bit} downto {p.valid_bit}));")
        if p.writable:
            wd = f"ram_p{p.i}_wd"
            d(f"signal {wd} : std_logic_vector({cfg.width-1} downto 0);")
            s(f"{wd} <= {last}({p.wd_hi} downto {p.wd_lo});")
            s(f"{p.out_prefix}wr_data <= {_vhdl_from_slv(cfg.elem_t, wd)};")
            for j in range(cfg.we_bits):
                target = (
                    f"{p.out_prefix}wr_en({j})"
                    if cfg.byte_write_enables
                    else f"{p.out_prefix}wr_en"
                )
                s(f"{target} <= unsigned({last}({p.we_lo+j} downto {p.we_lo+j}));")
    s(
        "process(clk) begin\n  if rising_edge(clk) then\n    if CLOCK_ENABLE(0) = '1' then"
    )
    body.extend("      " + line for line in clocked)
    s("    end if;\n  end if;\nend process;")
    # The same caller contract as the native model. These checks have no
    # hardware cost and do not impose read-first/priority logic on inference.
    s("-- synthesis translate_off")
    s("process(clk)")
    writers = [p for p in layouts if p.writable]
    gap = plan.read_after_write_gap
    if gap > 1:
        s(f"  type history_t is array(0 to {gap-2}) of integer;")
        for p in writers:
            s(f"  variable history_p{p.i} : history_t := (others => -1);")
    s("begin\n  if rising_edge(clk) then\n    if CLOCK_ENABLE(0) = '1' then")

    def address(p):
        return f"(to_integer(unsigned(p{p.i}.addr)) mod {cfg.size})"

    def enabled(p):
        mask = f"unsigned({p.b(0)}({p.we_lo+cfg.we_bits-1} downto {p.we_lo}))"
        return f"(p{p.i}.valid(0) = '1' and {mask} /= 0)"

    for p in layouts:
        if p.readable:
            condition = f"p{p.i}.valid(0) = '1'"
            if p.writable:
                condition += f" and not {enabled(p)}"
            s(f"      if {condition} then")
            for w in writers:
                s(
                    f'        assert not ({enabled(w)} and {address(w)} = {address(p)}) report "auto-pipelined RAM: read_after_write_gap violation" severity failure;'
                )
                if gap > 1:
                    s(f"        for age in 0 to {gap-2} loop")
                    s(
                        f'          assert history_p{w.i}(age) /= {address(p)} report "auto-pipelined RAM: read_after_write_gap violation" severity failure;'
                    )
                    s("        end loop;")
            s("      end if;")
    for j, p in enumerate(writers):
        for w in writers[j + 1 :]:
            pm = f"unsigned({p.b(0)}({p.we_lo+cfg.we_bits-1} downto {p.we_lo}))"
            wm = f"unsigned({w.b(0)}({w.we_lo+cfg.we_bits-1} downto {w.we_lo}))"
            s(
                f'      assert not ({enabled(p)} and {enabled(w)} and {address(p)} = {address(w)} and ({pm} and {wm}) /= 0) report "auto-pipelined RAM: overlapping writes" severity failure;'
            )
    if gap > 1:
        for p in writers:
            for age in reversed(range(1, gap - 1)):
                s(f"      history_p{p.i}({age}) := history_p{p.i}({age-1});")
            s(
                f"      if {enabled(p)} then history_p{p.i}(0) := {address(p)}; else history_p{p.i}(0) := -1; end if;"
            )
    s("    end if;\n  end if;\nend process;")
    s("-- synthesis translate_on")
    return "\n".join(decl) + "\nbegin\n" + "\n".join(body) + "\n"


def _auto_pipeline_ram_model(cfg, plan, out_ts, out_t):
    # Equal-depth bank paths are equivalent to this shared logical memory.
    base = ram_model_class(cfg, False, out_ts, out_t)

    class AutoPipelineRamModel(base):
        def __init__(self):
            super().__init__()
            self.recent_writes = []

        def __deepcopy__(self, memo):
            new = super().__deepcopy__(memo)
            new.__class__ = AutoPipelineRamModel
            new.recent_writes = list(self.recent_writes)
            return new

        def __call__(self, *args, **kwargs):
            args = _bind_args([f"p{i}" for i in range(len(cfg.ports))], args, kwargs)
            writes, reads = [], []
            for i, (x, kind) in enumerate(zip(args, cfg.ports)):
                if not int(x.valid):
                    continue
                addr = int(x.addr) % cfg.size
                mask = 0
                if kind != "r":
                    mask = (
                        sum((int(e) & 1) << j for j, e in enumerate(x.wr_en))
                        if cfg.byte_write_enables
                        else int(x.wr_en) & 1
                    )
                if mask:
                    writes.append((addr, mask, i))
                elif kind != "w":
                    reads.append((addr, i))
            for addr, mask, i in writes:
                if any(a == addr and m & mask and j != i for a, m, j in writes):
                    raise ValueError(
                        f"auto-pipelined RAM: overlapping writes at address {addr}"
                    )
            for addr, i in reads:
                if any(a == addr for a, _, _ in writes) or any(
                    a == addr for a, _ in self.recent_writes
                ):
                    raise ValueError(
                        f"auto-pipelined RAM: read at address {addr} violates read_after_write_gap={plan.read_after_write_gap}"
                    )
            self.recent_writes = [
                (a, age + 1)
                for a, age in self.recent_writes
                if age + 1 < plan.read_after_write_gap - 1
            ]
            if plan.read_after_write_gap > 1:
                self.recent_writes.extend((a, 0) for a, _, _ in writes)
            return super().__call__(*args)

    return AutoPipelineRamModel


def make_auto_pipeline_ram(
    elem_t,
    size,
    ports=("rw",),
    init=None,
    byte_write_enables=False,
    *,
    latency=None,
    start_latency=None,
    max_latency=None,
):
    """BRAM with automatically selected registers and depth partitioning.

    The ports and return types match make_ram. Latency constraints count TOTAL
    cycles, never less than one. .read_after_write_gap is the conservative
    enabled-cycle separation required before a dependent read. Same-address
    collisions and rd_data on an rw write are unspecified. See the RAM section
    of docs/AUTO_PIPELINE_DESIGN.md.
    """
    import AUTO_PIPELINE

    AUTO_PIPELINE.RAM_VALIDATE_CONSTRAINTS(latency, start_latency, max_latency)
    cfg = RamConfig(
        "make_auto_pipeline_ram", elem_t, size, ports, 1, 0, 0, init, byte_write_enables
    )
    AUTO_PIPELINE.RAM_VALIDATE_PORTS(cfg.ports)
    key = hashlib.sha256(
        repr((cfg.key, latency, start_latency, max_latency)).encode()
    ).hexdigest()
    options = dict(
        size=size,
        width=cfg.width,
        ports=cfg.ports,
        byte_write_enables=byte_write_enables,
        latency=latency,
        start_latency=start_latency,
        max_latency=max_latency,
    )
    plan = py.AUTO_PIPELINE_RAM_PLAN_CACHE().get(key)
    if plan is None:
        native_options = dict(options)
        if py.AUTO_PIPELINE_BUILD_MODE() != "sweep":
            native_options["start_latency"] = None
        plan = AUTO_PIPELINE.RAM_CANDIDATES(**native_options)[0]
    cfg.in_regs = plan.write_stage
    cfg.out_regs = plan.output_regs + plan.response_levels
    cfg.latency = plan.latency
    in_ts, out_ts = [], []
    for kind in cfg.ports:
        req, resp = ram_port_payload_fields(cfg, kind)
        in_ts.append(ram_make_struct(f"ram_{kind}_in_t", req + [("valid", py.uint1_t)]))
        out_ts.append(
            ram_make_struct(
                f"ram_{kind}_out_t",
                [f for f in resp if f[0] != "rd_data"]
                + [("valid", py.uint1_t)]
                + ([("rd_data", elem_t)] if kind != "w" else []),
            )
        )
    out_t = ram_make_struct("ram_out_t", [(f"p{i}", t) for i, t in enumerate(out_ts)])
    name = f"auto_pipeline_ram_h{key[:12]}_p{plan.fingerprint}"
    params = ", ".join(f"p{i}: P{i}_IN_T" for i in range(len(in_ts)))
    source = f"@pipeline_latency({plan.latency})\ndef {name}({params}) -> OUT_T:\n    vhdl(VHDL_TEXT)\n"
    ns = dict(
        pipeline_latency=py.pipeline_latency,
        vhdl=py.vhdl,
        OUT_T=out_t,
        VHDL_TEXT=_auto_pipeline_ram_vhdl(cfg, plan),
    )
    ns.update({f"P{i}_IN_T": t for i, t in enumerate(in_ts)})
    ram_exec_globals(ns, elem_t, out_t, *in_ts)
    init = cfg.init_desc
    ram = py._exec_generated_func(name, source, ns, folder=RAM_GENERATED_FOLDER)
    info = py._names.replace(
        ram._pypeline_name_info,
        params=(("implementation", plan.fingerprint),) + ram._pypeline_name_info.params,
    )
    ram._pypeline_name_info = py._inspect.unwrap(ram)._pypeline_name_info = info
    py.sim_model(ram)(_auto_pipeline_ram_model(cfg, plan, out_ts, out_t))
    ram._auto_pipeline_ram = dict(key=key, plan=plan, options=options)
    for attr in (
        "elem_t",
        "size",
        "addr_t",
        "ports",
        "read_latency",
        "in_regs",
        "out_regs",
        "latency",
        "byte_write_enables",
        "we_t",
    ):
        setattr(ram, attr, getattr(cfg, attr))
    ram.read_after_write_gap = plan.read_after_write_gap
    ram.plan = plan
    ram.in_ts, ram.out_ts, ram.out_t = tuple(in_ts), tuple(out_ts), out_t
    for i, (in_t, port_out_t) in enumerate(zip(in_ts, out_ts)):
        setattr(ram, f"p{i}_in_t", in_t)
        setattr(ram, f"p{i}_out_t", port_out_t)
    return ram, out_t
