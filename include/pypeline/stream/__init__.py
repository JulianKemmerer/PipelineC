"""Valid/ready streams.

The package exports the stream types defined in `stream/stream.py`, so a design
writes `from stream import make_stream_interface, make_stream_t`. The other
modules are stream building blocks, imported by name (`stream.stream_fifo`,
`stream.skid_buffer`, ...). The code stays in `stream/stream.py`, not here:
generated names include the defining module, and instance names its file.
"""

# The stream types: a plain {data, valid} struct, and the valid/ready interface
from stream.stream import make_stream_interface, make_stream_t  # noqa: F401
