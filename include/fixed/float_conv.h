#define fixed_to_float(x, type_t) ((float)(x.bits) / (float)((uint32_t)1 << PPCAT(PPCAT(type_t,_),FRAC_BITS)))

#define fixed_init_from_float(f, type_t) {.bits = (int64_t)((f) * (float)((uint32_t)1 << PPCAT(PPCAT(type_t,_),FRAC_BITS)))}
