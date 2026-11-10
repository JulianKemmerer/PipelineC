"""Manual Vivado probe: how deep AUTO_PIPELINE slices the Poly1305 body math.

    pypelinec src/tests/pypeline_tests/qor/poly1305/body.py -D MHZ=80 \
        --no_latency_memory --out_dir <new-directory> --syn_cache <isolated-store> -j 1

The body is WireGuard's paired feedback and coefficient arithmetic, a*b + c mod p,
with the hybrid_square 130-bit Karatsuba product of `arithmetic.py`. Registered
boundary ports are for timing characterization; the region's latency excludes them.

-D HELPER=0 (default) tags the arithmetic directly, so the region root is the
arithmetic itself. -D HELPER=1 adds the helper level WireGuard's body once had,
so the hotspot is a helper inside the region. Either way the sweep locks the
hotspot with its isolated mini-sweep: 10 slices at 87.64 MHz in 3 whole-design
syntheses at 80 MHz (Vivado 2019.2). Before region roots were mini-swept
(compiler at 9fbd5d9f), HELPER=0 grew the region to 34 slices (82.05 MHz, 7).
"""

from pypeline import AUTO_PIPELINE, MAIN, PART, Reg, hw_func, param, NamedTuple, struct

from arithmetic import residue_mul_add_mod, uint130_t

# Match the accepted WireGuard hardware target.
PART("xc7a200tffg1156-2")
# The clock goal and the region's structure are compile-time fixture parameters.
MHZ = param("MHZ", 80)
HELPER = param("HELPER", 0, choices=(0, 1))


@struct
class body_in_t(NamedTuple):
    a: uint130_t
    b: uint130_t
    c: uint130_t


@hw_func
def body_helper(x: body_in_t) -> uint130_t:
    return residue_mul_add_mod(x.a, x.b, x.c)


# The helper level is optional: a region root is mini-swept like a helper
# inside it (issue #387).
if HELPER:

    @hw_func
    def body_region(x: body_in_t) -> uint130_t:
        return body_helper(x)

else:

    @hw_func
    def body_region(x: body_in_t) -> uint130_t:
        return residue_mul_add_mod(x.a, x.b, x.c)


# The probe's own region name, so production latency memory never applies.
body = AUTO_PIPELINE(body_region, name="qor_poly1305_body")


@MAIN(MHZ)
def poly1305_body(x: body_in_t) -> uint130_t:
    input_reg: Reg[body_in_t]
    output_reg: Reg[uint130_t]
    result: uint130_t = output_reg
    output_reg = body(input_reg)
    input_reg = x
    return result
