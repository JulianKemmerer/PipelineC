#define N_PIXELS_PER_UPDATE 1
#define pixel_t uint8_t
typedef struct pixels_update_t
{
    pixel_t pixels[N_PIXELS_PER_UPDATE];
    uint16_t addr;
    uint8_t pad0; // temp need to be >= 4 bytes
}pixels_update_t;