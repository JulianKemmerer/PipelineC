# pyright: reportInvalidTypeForm=none
"""64K x 32 block RAM with independent valid/ready write/read ports.

Build: src/pypelinec examples/pypeline/auto_pipeline_ram.py --out_dir <scratch>
Issue dependent reads after a write acknowledgement, or wait the reported
read_after_write_gap enabled clocks between accepted requests.
"""

from pypeline import MAIN, SYN_TOOL, uint32_t
from stream.stream_ram import make_stream_auto_pipeline_ram

SYN_TOOL("open_tools")
memory, result_t = make_stream_auto_pipeline_ram(
    uint32_t,
    65536,
    ports=("w", "r"),
    max_latency=9,
)
write_req_t = memory.p0_req_intrf.fwd_t
write_resp_t = memory.p0_resp_intrf.fb_t
read_req_t = memory.p1_req_intrf.fwd_t
read_resp_t = memory.p1_resp_intrf.fb_t


@MAIN(120.0)
def auto_pipeline_ram(
    p0_req_if: write_req_t,
    p0_resp_if: write_resp_t,
    p1_req_if: read_req_t,
    p1_resp_if: read_resp_t,
) -> result_t:
    return memory(p0_req_if, p0_resp_if, p1_req_if, p1_resp_if)
