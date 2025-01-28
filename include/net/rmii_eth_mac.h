#include "uintN_t.h"  // uintN_t types for any N
#include "compiler.h"
#include "axi/axis.h"

// Serializer 8bit -> 2bit
typedef struct ser82_t
{
	uint2_t o;
	uint1_t rdy;
}ser82_t;
ser82_t ser82(uint8_t byte, uint8_t en){
	static uint8_t reg;
	static uint3_t ctr;
	uint8_t tx_bits8[8] = {reg(0), reg(1), reg(2), reg(3), reg(4), reg(5), reg(6), reg(7)};
	uint3_t bitpos0 = (uint3_t)(ctr);
	uint3_t bitpos1 = (uint3_t)(ctr + 1);
	ser82_t o = {.o = uint1_uint1(tx_bits8[bitpos1],tx_bits8[bitpos0]), .rdy = ctr == 6};
	if(ctr == 6){
		ctr = 0;
	}
	else{
		ctr += 2;
	}
	if(en){
		reg = byte;
	}
	return o;
}

// RX-MAC Outputs
typedef struct rmii_rx_mac_t{
	stream(axis8_t) rx_mac_axis_out;
	uint1_t rx_mac_error;
}rmii_rx_mac_t;
rmii_rx_mac_t rmii_rx_mac(
	// RX-MAC Inputs
	uint2_t rx_mac_data_in,
	uint1_t rx_mac_data_valid
){
	static uint1_t last_reg;
	static uint1_t valid_reg;
	static uint1_t error_reg;
	static uint8_t data_reg;
    static uint8_t data_fifo[4];
    static uint32_t fcs_reg;
	static uint32_t crc32_reg;
	static uint2_t state;
	static uint3_t bit_counter;
    static uint32_t byte_counter;
	rmii_rx_mac_t o;

    uint1_t bit_end = (bit_counter == 6);
	uint1_t preamble_bits = (rx_mac_data_valid && rx_mac_data_in == 0b01);
	uint1_t sfd_bits = (rx_mac_data_valid && rx_mac_data_in == 0b11);

	if(state == 0){ // IDLE (Find Preamble)
		last_reg = 0;
		valid_reg = 0;
		data_reg = 0;
		bit_counter = 0;
        byte_counter = 0;
		if(preamble_bits){ // preamble start
			error_reg = 0; // reset error ?
			state = 1; // Goto Preamble
		}
	}
	else if(state == 1){ // PREAMBLE (Find SFD)
		if(preamble_bits){
			state = 1; // Repeat Preamble
		}
		else if(sfd_bits){
			state = 2; // Found SFD goto DATA
		}
		else{
			state = 0; // ERROR
			error_reg = 1;
		}
	}
	else if(state == 2){ // DATA
		if(rx_mac_data_valid){
            data_reg = uint2_uint6(rx_mac_data_in,data_reg(7,2));
			if(byte_counter == 1517 && bit_end){ // frame too long
                valid_reg = 0;
				error_reg = 1; // error
				state = 0; // ERROR
			}
            else {
                valid_reg = bit_end;
                if(bit_end){
                    byte_counter += 1;
                    bit_counter = 0;
                }
                else{
                    bit_counter += 2;
                }
            }
		}
		else if(!rx_mac_data_valid && byte_counter >= 64){ // Frame end
			last_reg = 1;
			bit_counter = 0; // reset for crc
            byte_counter = 0; // reset for crc
			state = 0; // Goto Idle
		}
		else if(!rx_mac_data_valid && byte_counter < 64){ // Frame too short
            valid_reg = 0;
			error_reg = 1; // error
			state = 0; // Error
		}
	}

	// AXIS Output
	o.rx_mac_axis_out.data.tdata[0] = data_reg;
	o.rx_mac_axis_out.data.tkeep[0] = valid_reg;
	o.rx_mac_axis_out.valid = valid_reg;
	o.rx_mac_axis_out.data.tlast = last_reg;
	//rx_mac_error = error_reg;
	return o;
}


// AXI-S 8bit TX-MAC Outputs
typedef struct rmii_tx_mac_t{
	uint2_t tx_mac_output_data;
	uint1_t tx_mac_output_valid;
	uint1_t tx_mac_input_ready;
}rmii_tx_mac_t;
rmii_tx_mac_t rmii_tx_mac(
	// AXI-S 8bit TX-MAC Inputs
	stream(axis8_t) tx_mac_axis_in
){
	// AXI-S TX-MAC FSM
	// Gen. full Eth Frame
	// Appends PREAMBLE + SFD
	// Appends Data
	// Appends FCS
	static uint3_t state;
	static uint1_t mac_output_valid_reg;
	static uint1_t mac_input_ready_reg;
	static uint1_t mac_output_valid_reg;
	static uint1_t mac_output_last_reg;
	static uint8_t preamble_ctr;
	static uint2_t fcs_ctr;
	static uint32_t crc32;
	static uint1_t loaded;
	rmii_tx_mac_t o;
	uint32_t POLY = 0x04C11DB7;
	uint8_t crc32_4[4] = {crc32(0,7), crc32(8,15), crc32(16,23), crc32(24,31)};
	uint1_t preamble_ctr_end = (preamble_ctr == 27);
	uint1_t fcs_ctr_end = (fcs_ctr == 3);

	o.tx_mac_output_valid = mac_output_valid_reg;
	o.tx_mac_input_ready = mac_input_ready_reg;

	if(state == 0){ // IDLE
		mac_input_ready_reg = 0;
		o.tx_mac_output_data = 0;
		mac_output_valid_reg = 0;
		crc32 = 0xFFFFFFFF;
		state = tx_mac_axis_in.valid; // Send preamble if ready
		loaded = 0;
	}
	else if(state == 1){ // PREAMBLE
		mac_input_ready_reg = 0;
        o.tx_mac_output_data = 0b01;
		mac_output_valid_reg = 1;
		if(preamble_ctr_end){
			state = 2; // Goto SFD
			preamble_ctr = 0;
		}
		else{
			preamble_ctr += 1;
		}
	}
	else if(state == 2){ // SFD
		mac_input_ready_reg = 0;
		mac_output_valid_reg = 1;
        o.tx_mac_output_data = 0b11;
		state = 3; // Goto DATA
	}
	else if(state == 3){ // DATA
		uint8_t b = tx_mac_axis_in.data.tdata[0];
		b = (b << 4) | (b >> 4);
		mac_output_valid_reg = 1;
		ser82_t ser = ser82(b, tx_mac_axis_in.valid);
		if(!loaded){
			o.tx_mac_output_data = uint1_uint1(b(1),b(0));
			loaded = 1;
		}
		else
			o.tx_mac_output_data = ser.o;
		mac_input_ready_reg = tx_mac_axis_in.valid && ser.rdy;
		if(tx_mac_axis_in.valid){
			uint32_t crc_next = crc32 ^ (uint32_t)(tx_mac_axis_in.data.tdata[0]); // XOR input data
			uint4_t i = 0;
            for (i = 0; i < 8; i = i + 1){
                if (crc_next(31))
                    crc_next = (crc_next << 1) ^ POLY;
                else
                    crc_next = crc_next << 1;
			}
            crc32 = crc_next;
		}
		else if(tx_mac_axis_in.data.tlast){
			state = 4; // Goto FCS
		}
		else
		{
			if(ser.rdy)
				state = 3; // Goto DATA
		}
	}
	else if(state == 4){ // FCS
		mac_input_ready_reg = 0;
		mac_output_valid_reg = 0;
		o.tx_mac_output_data = 0b00;
		state = 5; // Goto Finsih
		//tx_byte = crc32_4[fcs_ctr];
        //tx_mac_output_data = uint1_uint1(tx_bits8[bitpos1], tx_bits8[bitpos0]);
		//if(fcs_ctr_end){
		//	if(bitend){
		//			fcs_ctr = 0;
        //			state = 5; // Goto Finsih
		//			bit_idx = 0;
		//		}
		//		else
		//			bit_idx += 2;
		//}
		//else{
		//	if(bitend){
		//			fcs_ctr += 1;
		//			bit_idx = 0;
		//		}
		//		else
		//			bit_idx += 2;
		//	
		//}
	}
	else if(state == 5){ // Finsih
		o.tx_mac_output_data = 0b00;
		mac_output_valid_reg = 0;
        state = 0; // Goto IDLE
	}
	return o;
}
