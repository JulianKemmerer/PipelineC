
// sccb_start_fifo_in stream = sccb_op_start handshake
HANDSHAKE_MM_WRITE(sccb_start_fifo_in, sccb_start_fifo_in_ready, mm_regs, sccb_op_start)
// sccb_op_finish handshake = sccb_finish_fifo_out stream
HANDSHAKE_MM_READ(mm_regs, sccb_op_finish, sccb_finish_fifo_out, sccb_finish_fifo_out_ready)