// I2S samples descriptors read from handshake into registers
HANDSHAKE_MM_READ(mm_regs, i2s_rx_desc_written, i2s_rx_descriptors_monitor_fifo_out, i2s_rx_descriptors_monitor_fifo_out_ready)
// I2S descriptors stream written from regs, i2s_rx_desc_to_write
HANDSHAKE_MM_WRITE(i2s_rx_desc_to_write_fifo_in, i2s_rx_desc_to_write_fifo_in_ready, mm_regs, i2s_rx_desc_to_write)
