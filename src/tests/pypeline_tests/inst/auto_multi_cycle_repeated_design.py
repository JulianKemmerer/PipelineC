# pyright: reportInvalidTypeForm=none
"""Two calls of one uncached service factory, one per MAIN, as a design builds
one setup service per direction: make_stream_auto_multi_cycle over equal
kernel closures, once unnamed and once under a shared name=. Each pair is one
group (one key, one count) held by one function instanced twice. Used by
auto_multi_cycle_unit_test (groups) and double_parse_file_test (names)."""
from pypeline import MAIN, Reg, hw_func, uint32_t

from stream.stream import make_stream_interface
from stream.stream_multi_cycle import make_stream_auto_multi_cycle

word_intrf = make_stream_interface(uint32_t)


def make_kernel(k):
    @hw_func
    def kernel(x: uint32_t) -> uint32_t:
        acc: uint32_t = x
        for i in range(4):
            acc = acc + ((acc << 3) ^ (acc >> 5)) + k
        return acc

    return kernel


def make_service(k, name=None):
    return make_stream_auto_multi_cycle(make_kernel(k), start_latency=2, name=name)


def make_lane(service):
    @hw_func
    def lane() -> uint32_t:
        x: Reg[uint32_t] = 1
        in_stream_if: word_intrf.stream_t
        in_stream_if.data = x
        in_stream_if.valid = 1
        f = service(word_intrf.fwd_t(stream=in_stream_if), service.out_fb_t(ready=1))
        if f.stream_in_if.ready:
            x = x + 1
        return f.stream_out_if.stream.data

    return lane


encrypt_unnamed = make_lane(make_service(3))
decrypt_unnamed = make_lane(make_service(3))
encrypt_named = make_lane(make_service(5, name="setup"))
decrypt_named = make_lane(make_service(5, name="setup"))


@MAIN
def encrypt_main() -> uint32_t:
    return encrypt_unnamed() + encrypt_named()


@MAIN
def decrypt_main() -> uint32_t:
    return decrypt_unnamed() + decrypt_named()
