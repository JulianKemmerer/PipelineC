# pyright: reportInvalidTypeForm=none
"""Plain-Python (no hardware elaboration) native-sim driver/monitor pair for
an axis-shaped interface's byte-stream traffic, API-inspired by cocotb's
cocotbext-axi (https://github.com/alexforencich/cocotbext-axi)'s
AxiStreamSource/AxiStreamSink -- queue-backed `send()`/`recv()`, a
`set_pause_generator()` backpressure hook -- but NOT that library itself:
cocotbext-axi's classes are `async def`, hard-wired to cocotb's
`await RisingEdge(clock)` coroutine scheduler and `cocotb.queue.Queue`.
Pypeline's native sim (`sim_call`/`pypeline_sim.py`'s `_run_clock_cycle`) is a
synchronous, non-async, delta-cycle-converging plain Python function-call
model -- no `SimHandle`/`Trigger` objects to hook cocotb's scheduler onto.
So `AxisSimSource`/`AxisSimSink` are plain stateful classes, stepped once per
cycle from inside a user's own `@sim_input`/`@sim_output` glue function (the
same shape already used by `@sim_model`-attached classes elsewhere in this
codebase), not coroutines.

Usage (mirrors wireguard-fpga's `encrypt_tb.py`/`decrypt_tb.py` shape):

    from pypeline import sim_input, sim_output
    from aead_types import axis128_intrf

    src = AxisSimSource(axis128_intrf, 16)
    snk = AxisSimSink(axis128_intrf, 16)

    @sim_input
    def drive_in_word():
        return src.step(chacha20poly1305_encrypt_ports.axis_in_ready)

    @sim_output
    def check_out():
        snk.step(chacha20poly1305_encrypt_ports.axis_out)
        frame = snk.recv_nowait()
        if frame is not None:
            check_frame(frame)

    @MAIN
    def encrypt_tb() -> axis128_intrf.fwd_t:
        chacha20poly1305_encrypt_ports.axis_in = drive_in_word()
        chacha20poly1305_encrypt_ports.axis_out_ready = 1
        check_out()
        return chacha20poly1305_encrypt_ports.axis_out

Neither class drives/expects the OTHER side's ready to be randomized -- same
scope as `make_axis_byte_source`/`make_axis_byte_sink` in `axis.py`. A caller
wanting backpressure on the source side uses `set_pause_generator`; nothing
analogous is provided for the sink (it always presents ready=1 to its step()
caller's own port-driving code, matching every existing testbench).
"""

from collections import deque


class AxisSimSource:
    """Queue-backed byte-frame generator. `send()`/`send_nowait()` queue a
    frame (any bytes-like object); `step(ready)` should be called exactly
    once per simulated cycle (typically from a `@sim_input` zero-arg
    function), advancing the in-flight frame once `ready` is true, and
    returns the `axis_intrf.fwd_t` value for that cycle."""

    def __init__(self, axis_intrf, n):
        self.axis_intrf = axis_intrf
        self.n = n
        self._queue = deque()
        self._current = None  # bytes remaining of the in-flight frame, or None
        self._pause_iter = None

    def send_nowait(self, frame):
        """Queues `frame` (any bytes-like object). Every byte up to the
        frame's own length is kept; `keep[i] = remaining > i` on the final
        beat, matching `make_axis_byte_source` -- this is already
        Xilinx-style AXIS-interop shaped (full keep except a trailing-only
        partial `eod` beat). A frame that is really multiple concatenated
        sub-messages (e.g. wireguard's ciphertext-then-auth-tag framing) must
        be packed contiguously by the caller before `send()`, not given
        padding gaps (see wireguard-fpga issue #44: no embedded null
        bytes)."""
        self._queue.append(bytes(frame))

    # Synchronous model -- no real waiting involved, `send` is just the
    # cocotbext-axi-familiar name for the same operation as send_nowait.
    send = send_nowait

    def set_pause_generator(self, gen):
        """`gen` is an iterable (or zero-arg callable returning one) of
        truthy/falsy values -- consumed one per `step()` call; while truthy,
        the emitted word is held at valid=0 (a stall), regardless of queued
        data. `None` clears any previously-set generator."""
        if gen is None:
            self._pause_iter = None
            return
        self._pause_iter = iter(gen() if callable(gen) else gen)

    def clear_pause_generator(self):
        self._pause_iter = None

    def idle(self):
        """True when no frame is in flight or queued -- safe to `send()` the
        next frame without it queueing behind an unfinished one (mirrors
        `make_axis_byte_source`'s `.idle` output field)."""
        return self._current is None and not self._queue

    def _paused(self):
        if self._pause_iter is None:
            return False
        try:
            return bool(next(self._pause_iter))
        except StopIteration:
            self._pause_iter = None
            return False

    def _null_word(self):
        return self.axis_intrf.fwd_t(
            self.axis_intrf.stream_t(
                data=self._zero_frag(),
                valid=0,
            )
        )

    def _zero_frag(self):
        frag_t = self.axis_intrf.stream_t.typeof("data")
        bus_t = frag_t.typeof("frag")
        return frag_t(
            frag=bus_t(data=[0] * self.n, keep=[0] * self.n),
            eod=[0],
        )

    def step(self, ready):
        if self._current is None:
            if not self._queue:
                return self._null_word()
            self._current = self._queue.popleft()

        if self._paused():
            return self._null_word()

        chunk = self._current[: self.n]
        eod = 1 if len(self._current) <= self.n else 0
        data = [0] * self.n
        keep = [0] * self.n
        for i, b in enumerate(chunk):
            data[i] = b
            keep[i] = 1

        frag_t = self.axis_intrf.stream_t.typeof("data")
        bus_t = frag_t.typeof("frag")
        word = self.axis_intrf.fwd_t(
            self.axis_intrf.stream_t(
                data=frag_t(frag=bus_t(data=data, keep=keep), eod=[eod]),
                valid=1,
            )
        )

        if ready:
            if eod:
                self._current = None
            else:
                self._current = self._current[self.n :]

        return word


class AxisSimSink:
    """Queue-backed byte-frame collector. `step(word)` should be called
    exactly once per simulated cycle (typically from a `@sim_output` zero-arg
    function reading the real converged port value) with the interface's
    current `axis_intrf.fwd_t` value; on `eod` it completes a frame, poppable
    via `recv()`/`recv_nowait()`. Always behaves as if its own `ready` is 1
    (matching every existing testbench in this codebase) -- it has no
    backpressure/pause hook of its own.

    Every accepted beat is checked for Xilinx-style AXIS-interop compliance
    (wireguard-fpga issue #44): `keep` must be all-ones unless the beat
    carries `eod`, and on the `eod` beat `keep` must be a contiguous prefix
    (lanes `[0, popcount)` kept, the rest not) -- never a mid-packet or
    mid-beat hole/embedded null byte. A violation raises `AssertionError`
    immediately, independent of whatever the caller separately checks about
    the collected frame bytes.

    `scoreboard`, if given, lets `check_nowait()` pop a completed frame and
    compare it against the next `Scoreboard.expect()`-ed value in one call --
    see `Scoreboard` below."""

    def __init__(self, axis_intrf, n, scoreboard=None):
        self.axis_intrf = axis_intrf
        self.n = n
        self.scoreboard = scoreboard
        self._queue = deque()
        self._current = bytearray()

    def step(self, word):
        if not word.stream.valid:
            return
        keep = [word.stream.data.frag.keep[i] for i in range(self.n)]
        eod = word.stream.data.eod[0]
        popcount = sum(1 for k in keep if k)
        assert popcount == self.n or eod, (
            "AXIS Xilinx-style tkeep violation: partial-keep beat without tlast "
            "(embedded null bytes)"
        )
        assert keep == [1] * popcount + [0] * (self.n - popcount), (
            "AXIS Xilinx-style tkeep violation: tkeep is not a contiguous prefix"
        )
        for i in range(self.n):
            if keep[i]:
                self._current.append(word.stream.data.frag.data[i])
        if eod:
            self._queue.append(bytes(self._current))
            self._current = bytearray()

    def recv_nowait(self):
        if not self._queue:
            return None
        return self._queue.popleft()

    recv = recv_nowait

    def empty(self):
        return not self._queue

    def check_nowait(self):
        """Pop a completed frame (if any) and check it against `self.scoreboard`
        in one step. Returns `self.scoreboard.check(frame)`'s result dict, or
        `None` if no frame has completed yet. Requires a scoreboard to have
        been passed to `__init__`."""
        frame = self.recv_nowait()
        if frame is None:
            return None
        return self.scoreboard.check(frame)


class Scoreboard:
    """Generic ordered expected-vs-actual comparison queue -- NOT AXIS-
    specific, just factored out because every testbench in this codebase
    reinvented the same "dict of expected packets + a manually-incremented
    index" bookkeeping around its own checker. `expect(value, **meta)` queues
    an expected value (plus arbitrary caller metadata -- packet index, a
    tamper flag, whatever the caller wants back at check time); `check(got)`
    pops the oldest expectation, compares it to `got` (`==`), and returns a
    dict: `{"passed": bool, "expected": ..., "got": ..., **meta}`. Comparing
    with nothing queued ("unexpected value") is reported as a failure via the
    same dict shape, with `"expected": None` and an `"error"` key, rather than
    raising -- a testbench's own `@sim_output` checker can uniformly branch on
    `result["passed"]` either way."""

    def __init__(self):
        self._queue = deque()

    def expect(self, value, **meta):
        self._queue.append((value, meta))

    def pending(self):
        return len(self._queue)

    def check(self, got):
        if not self._queue:
            return {
                "passed": False,
                "expected": None,
                "got": got,
                "error": "unexpected value with nothing queued",
            }
        expected, meta = self._queue.popleft()
        result = dict(meta)
        result["passed"] = expected == got
        result["expected"] = expected
        result["got"] = got
        return result
