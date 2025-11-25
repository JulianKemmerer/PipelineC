uint8_t sccb_read(uint8_t id, uint8_t addr){
  // Write sccb start for read op
  sccb_op_start_t start_op;
  start_op.id = id;
  start_op.is_read = 1;
  start_op.addr = addr;
  start_op.write_data = 0; // ignored for read
  mm_handshake_write(sccb_op_start, &start_op);
  // Read sccb finish to get read data
  sccb_op_finish_t finish_op;
  mm_handshake_read(&finish_op, sccb_op_finish);
  return (uint8_t)finish_op.read_data;
}

void sccb_write(uint8_t id, uint8_t addr, uint8_t data){
  // Write sccb start for write op
  sccb_op_start_t start_op;
  start_op.id = id;
  start_op.is_read = 0;
  start_op.addr = addr;
  start_op.write_data = data;
  mm_handshake_write(sccb_op_start, &start_op);
  // Read sccb finish to know write is done
  sccb_op_finish_t finish_op;
  mm_handshake_read(&finish_op, sccb_op_finish);
}