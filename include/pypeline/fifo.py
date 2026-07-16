import math
from collections import deque

from pypeline import (
    struct,
    NamedTuple,
    uint1_t,
    vhdl,
    ctype_name,
    hw_func,
    sim_model,
    sim_zero,
)


def make_fifo(data_t, depth: int, mode: str = "fwft"):
    """Single-clock-domain FIFO wrapping the raw VHDL pipelinec_fifo_fwft entity.

    Returns (fifo_func, fifo_t):
        fifo_func(ready_for_data_out: uint1_t, data_in: data_t, data_in_valid: uint1_t) -> fifo_t
        fifo_t fields: .data_out (data_t), .data_out_valid (uint1_t), .data_in_ready (uint1_t)
    """
    if mode != "fwft":
        raise ValueError(
            f"make_fifo: unsupported mode {mode!r}, only 'fwft' is currently implemented"
        )
    if depth < 2:
        raise ValueError(f"make_fifo: depth must be >= 2, got {depth}")

    # Real hardware always rounds capacity up to a power of two (DEPTH_LOG2 =
    # ceil(log2(depth)) in the VHDL below) -- match it exactly so data_in_ready
    # deasserts at the same fill level as real hardware.
    capacity = 2 ** math.ceil(math.log2(depth))

    type_name = ctype_name(data_t)

    @struct
    class fifo_t(NamedTuple):
        data_out: data_t
        data_out_valid: uint1_t
        data_in_ready: uint1_t

    vhdl_text = f"""
constant WIDTH : integer := {type_name}_SLV_LEN;
constant DEPTH_LOG2 : positive := positive(ieee.math_real.ceil(ieee.math_real.log2(real({depth}))));
signal din_slv : std_logic_vector(WIDTH-1 downto 0);
signal dout_slv : std_logic_vector(WIDTH-1 downto 0);
begin
din_slv <= {type_name}_to_slv(data_in);
return_output.data_out <= slv_to_{type_name}(dout_slv);
fifo_fwft_inst : entity work.pipelinec_fifo_fwft
generic map(
  DEPTH_LOG2 => DEPTH_LOG2,
  DATA_WIDTH => WIDTH
)port map(
  clk => clk,
  data_in => din_slv,
  valid_in => data_in_valid(0) and CLOCK_ENABLE(0),
  ready_out => return_output.data_in_ready(0),
  data_out => dout_slv,
  valid_out => return_output.data_out_valid(0),
  ready_in => ready_for_data_out(0) and CLOCK_ENABLE(0)
);
"""

    @hw_func
    def fifo(
        ready_for_data_out: uint1_t, data_in: data_t, data_in_valid: uint1_t
    ) -> fifo_t:
        vhdl(vhdl_text)

    @sim_model(fifo)
    class _FifoFwftModel:
        # Functional (not cycle-accurate in the address/pointer sense, but
        # cycle-accurate in observable timing) FWFT model, mirroring
        # pipelinec_fifo_fwft.vhd's structure exactly: self.q models the
        # addressed memory (mem/wr_ptr_reg/rd_ptr_reg -- what data_in_ready's
        # capacity check is based on), and self.out_valid/self.out_data model
        # the *separate* one-word output register (valid_out_pipe_reg/
        # data_out_pipe_reg) sitting between mem and the data_out/
        # data_out_valid pins. That output register is what gives the real
        # FIFO its 2-cycle push-to-valid latency (one cycle for the push to
        # land in mem, one more for the read process to load it into the
        # output register) instead of the 1 cycle you'd get by exposing
        # self.q[0] directly -- see docs/pypeline_guide.md.
        def __init__(self):
            self.q = deque()
            self.out_valid = 0
            self.out_data = sim_zero(data_t)
            self.empty_data = sim_zero(data_t)

        def __call__(self, ready_for_data_out, data_in, data_in_valid):
            data_out_valid = self.out_valid
            data_out = self.out_data if self.out_valid else self.empty_data
            data_in_ready = 1 if len(self.q) < capacity else 0

            # consume <=> VHDL's "ready_in = '1' or valid_out_pipe_reg = '0'":
            # the output register reloads whenever the consumer takes the
            # current word, or whenever it's not currently holding one.
            consume = int(ready_for_data_out) or not self.out_valid
            if consume:
                if self.q:
                    self.out_data = self.q.popleft()
                    self.out_valid = 1
                else:
                    self.out_valid = 0
            if int(data_in_valid) and data_in_ready:
                self.q.append(data_in)

            return fifo_t(
                data_out=data_out,
                data_out_valid=data_out_valid,
                data_in_ready=data_in_ready,
            )

    return fifo, fifo_t
