typedef struct pred_resp_t
{
    //uint32_t pred;
    uint8_t pred; // Digit 0-9
    uint32_t nanosec_since; // ns since last prediction
    uint8_t pad6;
    uint8_t pad7;
    uint8_t pad8;
}pred_resp_t;