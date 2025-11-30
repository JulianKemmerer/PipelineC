// FFT output descriptors read from handshake into registers
// fft_out_desc_written handshake = fft_desc_written stream
HANDSHAKE_MM_READ(mm_regs, fft_desc_written, fft_out_desc_written, fft_out_desc_written_ready)
// FFT descriptors to write stream written by handshake registers
// fft_in_desc_to_write stream = fft_desc_to_write handshake
HANDSHAKE_MM_WRITE(fft_in_desc_to_write, fft_in_desc_to_write_ready, mm_regs, fft_desc_to_write)
