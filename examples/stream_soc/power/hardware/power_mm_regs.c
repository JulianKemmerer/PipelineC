// Power output descriptors read from handshake into registers
// power_out_desc_written handshake = power_desc_written stream
HANDSHAKE_MM_READ(mm_regs, power_desc_written, power_out_desc_written, power_out_desc_written_ready)
// Power descriptors to write stream written by handshake registers
// power_in_desc_to_write stream = power_desc_to_write handshake
HANDSHAKE_MM_WRITE(power_in_desc_to_write, power_in_desc_to_write_ready, mm_regs, power_desc_to_write)
