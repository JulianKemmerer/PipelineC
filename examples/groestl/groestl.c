#include "uintN_t.h"

#pragma MAIN_MHZ groestl 500.0
#define NUM_COLS 16
typedef struct state_t {
	uint8_t words[8][NUM_COLS];
} state_t;

typedef struct col_t {
	uint8_t words[8];
} col_t;

uint8_t sbox(uint8_t x) {
	uint8_t rom[256];
	rom[0] = 0x63;
	rom[1] = 0x7c;
	rom[2] = 0x77;
	rom[3] = 0x7b;
	rom[4] = 0xf2;
	rom[5] = 0x6b;
	rom[6] = 0x6f;
	rom[7] = 0xc5;
	rom[8] = 0x30;
	rom[9] = 0x01;
	rom[10] = 0x67;
	rom[11] = 0x2b;
	rom[12] = 0xfe;
	rom[13] = 0xd7;
	rom[14] = 0xab;
	rom[15] = 0x76;
	rom[16] = 0xca;
	rom[17] = 0x82;
	rom[18] = 0xc9;
	rom[19] = 0x7d;
	rom[20] = 0xfa;
	rom[21] = 0x59;
	rom[22] = 0x47;
	rom[23] = 0xf0;
	rom[24] = 0xad;
	rom[25] = 0xd4;
	rom[26] = 0xa2;
	rom[27] = 0xaf;
	rom[28] = 0x9c;
	rom[29] = 0xa4;
	rom[30] = 0x72;
	rom[31] = 0xc0;
	rom[32] = 0xb7;
	rom[33] = 0xfd;
	rom[34] = 0x93;
	rom[35] = 0x26;
	rom[36] = 0x36;
	rom[37] = 0x3f;
	rom[38] = 0xf7;
	rom[39] = 0xcc;
	rom[40] = 0x34;
	rom[41] = 0xa5;
	rom[42] = 0xe5;
	rom[43] = 0xf1;
	rom[44] = 0x71;
	rom[45] = 0xd8;
	rom[46] = 0x31;
	rom[47] = 0x15;
	rom[48] = 0x04;
	rom[49] = 0xc7;
	rom[50] = 0x23;
	rom[51] = 0xc3;
	rom[52] = 0x18;
	rom[53] = 0x96;
	rom[54] = 0x05;
	rom[55] = 0x9a;
	rom[56] = 0x07;
	rom[57] = 0x12;
	rom[58] = 0x80;
	rom[59] = 0xe2;
	rom[60] = 0xeb;
	rom[61] = 0x27;
	rom[62] = 0xb2;
	rom[63] = 0x75;
	rom[64] = 0x09;
	rom[65] = 0x83;
	rom[66] = 0x2c;
	rom[67] = 0x1a;
	rom[68] = 0x1b;
	rom[69] = 0x6e;
	rom[70] = 0x5a;
	rom[71] = 0xa0;
	rom[72] = 0x52;
	rom[73] = 0x3b;
	rom[74] = 0xd6;
	rom[75] = 0xb3;
	rom[76] = 0x29;
	rom[77] = 0xe3;
	rom[78] = 0x2f;
	rom[79] = 0x84;
	rom[80] = 0x53;
	rom[81] = 0xd1;
	rom[82] = 0x00;
	rom[83] = 0xed;
	rom[84] = 0x20;
	rom[85] = 0xfc;
	rom[86] = 0xb1;
	rom[87] = 0x5b;
	rom[88] = 0x6a;
	rom[89] = 0xcb;
	rom[90] = 0xbe;
	rom[91] = 0x39;
	rom[92] = 0x4a;
	rom[93] = 0x4c;
	rom[94] = 0x58;
	rom[95] = 0xcf;
	rom[96] = 0xd0;
	rom[97] = 0xef;
	rom[98] = 0xaa;
	rom[99] = 0xfb;
	rom[100] = 0x43;
	rom[101] = 0x4d;
	rom[102] = 0x33;
	rom[103] = 0x85;
	rom[104] = 0x45;
	rom[105] = 0xf9;
	rom[106] = 0x02;
	rom[107] = 0x7f;
	rom[108] = 0x50;
	rom[109] = 0x3c;
	rom[110] = 0x9f;
	rom[111] = 0xa8;
	rom[112] = 0x51;
	rom[113] = 0xa3;
	rom[114] = 0x40;
	rom[115] = 0x8f;
	rom[116] = 0x92;
	rom[117] = 0x9d;
	rom[118] = 0x38;
	rom[119] = 0xf5;
	rom[120] = 0xbc;
	rom[121] = 0xb6;
	rom[122] = 0xda;
	rom[123] = 0x21;
	rom[124] = 0x10;
	rom[125] = 0xff;
	rom[126] = 0xf3;
	rom[127] = 0xd2;
	rom[128] = 0xcd;
	rom[129] = 0x0c;
	rom[130] = 0x13;
	rom[131] = 0xec;
	rom[132] = 0x5f;
	rom[133] = 0x97;
	rom[134] = 0x44;
	rom[135] = 0x17;
	rom[136] = 0xc4;
	rom[137] = 0xa7;
	rom[138] = 0x7e;
	rom[139] = 0x3d;
	rom[140] = 0x64;
	rom[141] = 0x5d;
	rom[142] = 0x19;
	rom[143] = 0x73;
	rom[144] = 0x60;
	rom[145] = 0x81;
	rom[146] = 0x4f;
	rom[147] = 0xdc;
	rom[148] = 0x22;
	rom[149] = 0x2a;
	rom[150] = 0x90;
	rom[151] = 0x88;
	rom[152] = 0x46;
	rom[153] = 0xee;
	rom[154] = 0xb8;
	rom[155] = 0x14;
	rom[156] = 0xde;
	rom[157] = 0x5e;
	rom[158] = 0x0b;
	rom[159] = 0xdb;
	rom[160] = 0xe0;
	rom[161] = 0x32;
	rom[162] = 0x3a;
	rom[163] = 0x0a;
	rom[164] = 0x49;
	rom[165] = 0x06;
	rom[166] = 0x24;
	rom[167] = 0x5c;
	rom[168] = 0xc2;
	rom[169] = 0xd3;
	rom[170] = 0xac;
	rom[171] = 0x62;
	rom[172] = 0x91;
	rom[173] = 0x95;
	rom[174] = 0xe4;
	rom[175] = 0x79;
	rom[176] = 0xe7;
	rom[177] = 0xc8;
	rom[178] = 0x37;
	rom[179] = 0x6d;
	rom[180] = 0x8d;
	rom[181] = 0xd5;
	rom[182] = 0x4e;
	rom[183] = 0xa9;
	rom[184] = 0x6c;
	rom[185] = 0x56;
	rom[186] = 0xf4;
	rom[187] = 0xea;
	rom[188] = 0x65;
	rom[189] = 0x7a;
	rom[190] = 0xae;
	rom[191] = 0x08;
	rom[192] = 0xba;
	rom[193] = 0x78;
	rom[194] = 0x25;
	rom[195] = 0x2e;
	rom[196] = 0x1c;
	rom[197] = 0xa6;
	rom[198] = 0xb4;
	rom[199] = 0xc6;
	rom[200] = 0xe8;
	rom[201] = 0xdd;
	rom[202] = 0x74;
	rom[203] = 0x1f;
	rom[204] = 0x4b;
	rom[205] = 0xbd;
	rom[206] = 0x8b;
	rom[207] = 0x8a;
	rom[208] = 0x70;
	rom[209] = 0x3e;
	rom[210] = 0xb5;
	rom[211] = 0x66;
	rom[212] = 0x48;
	rom[213] = 0x03;
	rom[214] = 0xf6;
	rom[215] = 0x0e;
	rom[216] = 0x61;
	rom[217] = 0x35;
	rom[218] = 0x57;
	rom[219] = 0xb9;
	rom[220] = 0x86;
	rom[221] = 0xc1;
	rom[222] = 0x1d;
	rom[223] = 0x9e;
	rom[224] = 0xe1;
	rom[225] = 0xf8;
	rom[226] = 0x98;
	rom[227] = 0x11;
	rom[228] = 0x69;
	rom[229] = 0xd9;
	rom[230] = 0x8e;
	rom[231] = 0x94;
	rom[232] = 0x9b;
	rom[233] = 0x1e;
	rom[234] = 0x87;
	rom[235] = 0xe9;
	rom[236] = 0xce;
	rom[237] = 0x55;
	rom[238] = 0x28;
	rom[239] = 0xdf;
	rom[240] = 0x8c;
	rom[241] = 0xa1;
	rom[242] = 0x89;
	rom[243] = 0x0d;
	rom[244] = 0xbf;
	rom[245] = 0xe6;
	rom[246] = 0x42;
	rom[247] = 0x68;
	rom[248] = 0x41;
	rom[249] = 0x99;
	rom[250] = 0x2d;
	rom[251] = 0x0f;
	rom[252] = 0xb0;
	rom[253] = 0x54;
	rom[254] = 0xbb;
	rom[255] = 0x16;
	return rom[x];
}

col_t get_col(state_t state, uint32_t col) {
	col_t ret;
	uint32_t j;
	for (j = 0; j < 8; j += 1) {
		ret.words[j] = state.words[j][col];
	}
	return ret;
}

col_t mul2(col_t x) {
	uint8_t rom[256];
	rom[0] = 0x00;
	rom[1] = 0x02;
	rom[2] = 0x04;
	rom[3] = 0x06;
	rom[4] = 0x08;
	rom[5] = 0x0a;
	rom[6] = 0x0c;
	rom[7] = 0x0e;
	rom[8] = 0x10;
	rom[9] = 0x12;
	rom[10] = 0x14;
	rom[11] = 0x16;
	rom[12] = 0x18;
	rom[13] = 0x1a;
	rom[14] = 0x1c;
	rom[15] = 0x1e;
	rom[16] = 0x20;
	rom[17] = 0x22;
	rom[18] = 0x24;
	rom[19] = 0x26;
	rom[20] = 0x28;
	rom[21] = 0x2a;
	rom[22] = 0x2c;
	rom[23] = 0x2e;
	rom[24] = 0x30;
	rom[25] = 0x32;
	rom[26] = 0x34;
	rom[27] = 0x36;
	rom[28] = 0x38;
	rom[29] = 0x3a;
	rom[30] = 0x3c;
	rom[31] = 0x3e;
	rom[32] = 0x40;
	rom[33] = 0x42;
	rom[34] = 0x44;
	rom[35] = 0x46;
	rom[36] = 0x48;
	rom[37] = 0x4a;
	rom[38] = 0x4c;
	rom[39] = 0x4e;
	rom[40] = 0x50;
	rom[41] = 0x52;
	rom[42] = 0x54;
	rom[43] = 0x56;
	rom[44] = 0x58;
	rom[45] = 0x5a;
	rom[46] = 0x5c;
	rom[47] = 0x5e;
	rom[48] = 0x60;
	rom[49] = 0x62;
	rom[50] = 0x64;
	rom[51] = 0x66;
	rom[52] = 0x68;
	rom[53] = 0x6a;
	rom[54] = 0x6c;
	rom[55] = 0x6e;
	rom[56] = 0x70;
	rom[57] = 0x72;
	rom[58] = 0x74;
	rom[59] = 0x76;
	rom[60] = 0x78;
	rom[61] = 0x7a;
	rom[62] = 0x7c;
	rom[63] = 0x7e;
	rom[64] = 0x80;
	rom[65] = 0x82;
	rom[66] = 0x84;
	rom[67] = 0x86;
	rom[68] = 0x88;
	rom[69] = 0x8a;
	rom[70] = 0x8c;
	rom[71] = 0x8e;
	rom[72] = 0x90;
	rom[73] = 0x92;
	rom[74] = 0x94;
	rom[75] = 0x96;
	rom[76] = 0x98;
	rom[77] = 0x9a;
	rom[78] = 0x9c;
	rom[79] = 0x9e;
	rom[80] = 0xa0;
	rom[81] = 0xa2;
	rom[82] = 0xa4;
	rom[83] = 0xa6;
	rom[84] = 0xa8;
	rom[85] = 0xaa;
	rom[86] = 0xac;
	rom[87] = 0xae;
	rom[88] = 0xb0;
	rom[89] = 0xb2;
	rom[90] = 0xb4;
	rom[91] = 0xb6;
	rom[92] = 0xb8;
	rom[93] = 0xba;
	rom[94] = 0xbc;
	rom[95] = 0xbe;
	rom[96] = 0xc0;
	rom[97] = 0xc2;
	rom[98] = 0xc4;
	rom[99] = 0xc6;
	rom[100] = 0xc8;
	rom[101] = 0xca;
	rom[102] = 0xcc;
	rom[103] = 0xce;
	rom[104] = 0xd0;
	rom[105] = 0xd2;
	rom[106] = 0xd4;
	rom[107] = 0xd6;
	rom[108] = 0xd8;
	rom[109] = 0xda;
	rom[110] = 0xdc;
	rom[111] = 0xde;
	rom[112] = 0xe0;
	rom[113] = 0xe2;
	rom[114] = 0xe4;
	rom[115] = 0xe6;
	rom[116] = 0xe8;
	rom[117] = 0xea;
	rom[118] = 0xec;
	rom[119] = 0xee;
	rom[120] = 0xf0;
	rom[121] = 0xf2;
	rom[122] = 0xf4;
	rom[123] = 0xf6;
	rom[124] = 0xf8;
	rom[125] = 0xfa;
	rom[126] = 0xfc;
	rom[127] = 0xfe;
	rom[128] = 0x1b;
	rom[129] = 0x19;
	rom[130] = 0x1f;
	rom[131] = 0x1d;
	rom[132] = 0x13;
	rom[133] = 0x11;
	rom[134] = 0x17;
	rom[135] = 0x15;
	rom[136] = 0x0b;
	rom[137] = 0x09;
	rom[138] = 0x0f;
	rom[139] = 0x0d;
	rom[140] = 0x03;
	rom[141] = 0x01;
	rom[142] = 0x07;
	rom[143] = 0x05;
	rom[144] = 0x3b;
	rom[145] = 0x39;
	rom[146] = 0x3f;
	rom[147] = 0x3d;
	rom[148] = 0x33;
	rom[149] = 0x31;
	rom[150] = 0x37;
	rom[151] = 0x35;
	rom[152] = 0x2b;
	rom[153] = 0x29;
	rom[154] = 0x2f;
	rom[155] = 0x2d;
	rom[156] = 0x23;
	rom[157] = 0x21;
	rom[158] = 0x27;
	rom[159] = 0x25;
	rom[160] = 0x5b;
	rom[161] = 0x59;
	rom[162] = 0x5f;
	rom[163] = 0x5d;
	rom[164] = 0x53;
	rom[165] = 0x51;
	rom[166] = 0x57;
	rom[167] = 0x55;
	rom[168] = 0x4b;
	rom[169] = 0x49;
	rom[170] = 0x4f;
	rom[171] = 0x4d;
	rom[172] = 0x43;
	rom[173] = 0x41;
	rom[174] = 0x47;
	rom[175] = 0x45;
	rom[176] = 0x7b;
	rom[177] = 0x79;
	rom[178] = 0x7f;
	rom[179] = 0x7d;
	rom[180] = 0x73;
	rom[181] = 0x71;
	rom[182] = 0x77;
	rom[183] = 0x75;
	rom[184] = 0x6b;
	rom[185] = 0x69;
	rom[186] = 0x6f;
	rom[187] = 0x6d;
	rom[188] = 0x63;
	rom[189] = 0x61;
	rom[190] = 0x67;
	rom[191] = 0x65;
	rom[192] = 0x9b;
	rom[193] = 0x99;
	rom[194] = 0x9f;
	rom[195] = 0x9d;
	rom[196] = 0x93;
	rom[197] = 0x91;
	rom[198] = 0x97;
	rom[199] = 0x95;
	rom[200] = 0x8b;
	rom[201] = 0x89;
	rom[202] = 0x8f;
	rom[203] = 0x8d;
	rom[204] = 0x83;
	rom[205] = 0x81;
	rom[206] = 0x87;
	rom[207] = 0x85;
	rom[208] = 0xbb;
	rom[209] = 0xb9;
	rom[210] = 0xbf;
	rom[211] = 0xbd;
	rom[212] = 0xb3;
	rom[213] = 0xb1;
	rom[214] = 0xb7;
	rom[215] = 0xb5;
	rom[216] = 0xab;
	rom[217] = 0xa9;
	rom[218] = 0xaf;
	rom[219] = 0xad;
	rom[220] = 0xa3;
	rom[221] = 0xa1;
	rom[222] = 0xa7;
	rom[223] = 0xa5;
	rom[224] = 0xdb;
	rom[225] = 0xd9;
	rom[226] = 0xdf;
	rom[227] = 0xdd;
	rom[228] = 0xd3;
	rom[229] = 0xd1;
	rom[230] = 0xd7;
	rom[231] = 0xd5;
	rom[232] = 0xcb;
	rom[233] = 0xc9;
	rom[234] = 0xcf;
	rom[235] = 0xcd;
	rom[236] = 0xc3;
	rom[237] = 0xc1;
	rom[238] = 0xc7;
	rom[239] = 0xc5;
	rom[240] = 0xfb;
	rom[241] = 0xf9;
	rom[242] = 0xff;
	rom[243] = 0xfd;
	rom[244] = 0xf3;
	rom[245] = 0xf1;
	rom[246] = 0xf7;
	rom[247] = 0xf5;
	rom[248] = 0xeb;
	rom[249] = 0xe9;
	rom[250] = 0xef;
	rom[251] = 0xed;
	rom[252] = 0xe3;
	rom[253] = 0xe1;
	rom[254] = 0xe7;
	rom[255] = 0xe5;

	col_t ret;
	uint32_t j;
	for (j = 0; j < 8; j += 1) {
		ret.words[j] = rom[x.words[j]];
	}

	return ret;
}

state_t mix_bytes(state_t state) 
{
	state_t ret;

	uint32_t i;
	for (i = 0; i < NUM_COLS; i += 1) {
		col_t b = get_col(state, i);
		col_t b2 = mul2(b);
		col_t b4 = mul2(b2);
		uint8_t t1 = b2.words[0] ^ b2.words[2] ^ b.words[5] ^ b4.words[7] ^ b.words[7];
		uint8_t t2 = b2.words[1] ^ b.words[4] ^ b4.words[6] ^ b.words[6] ^ b2.words[7];
		uint8_t t3 = b.words[0] ^ b4.words[2] ^ b.words[2] ^ b2.words[3] ^ b2.words[5];
		uint8_t t4 = b.words[1] ^ b4.words[3] ^ b.words[3] ^ b2.words[4] ^ b2.words[6];
		uint8_t t5 = b4.words[0] ^ b.words[0] ^ b2.words[3] ^ b4.words[5];
		uint8_t t6 = b4.words[1] ^ b4.words[4] ^ b.words[4] ^ b2.words[7];
		uint8_t t7 = b4.words[1] ^ b.words[1] ^ b2.words[4];
		uint8_t t8 = b2.words[0] ^ b4.words[5] ^ b.words[5];
		uint8_t t9 = b.words[2] ^ b2.words[5];
		uint8_t ta = b2.words[1] ^ b.words[6];
		uint8_t tb = b.words[3] ^ b2.words[6];
		uint8_t tc = b2.words[2] ^ b.words[7];

		ret.words[0][i] = t1 ^ t2 ^ t9 ^ b4.words[3] ^ b4.words[4];
		ret.words[1][i] = t1 ^ t5 ^ ta ^ tb ^ b4.words[4];
		ret.words[2][i] = t2 ^ t5 ^ t7 ^ tc;
		ret.words[3][i] = t1 ^ t3 ^ t7 ^ b4.words[6];
		ret.words[4][i] = t3 ^ t4 ^ ta ^ b4.words[0] ^ b4.words[7];
		ret.words[5][i] = t4 ^ t6 ^ t9 ^ tc ^ b4.words[0];
		ret.words[6][i] = t3 ^ t6 ^ t8 ^ tb;
		ret.words[7][i] = t2 ^ t4 ^ t8 ^ b4.words[2];
	}

	return ret;
}

state_t add_round_constant_P(state_t state, uint8_t round) {
	state_t ret;

	uint32_t i;
  uint32_t j;
	for (i = 0; i < 16; i += 1) {
		ret.words[0][i] = state.words[0][i] ^ (uint8_t) (i * 16) ^ round;
	}
	
	for (j = 1; j < 8; j += 1) {
		for (i = 0; i < 16; i += 1) {
			ret.words[j][i] = state.words[j][i];
		}
	}


	return ret;
}

state_t add_round_constant_Q(state_t state, uint8_t round) {
	state_t ret;

	uint32_t j;
	uint32_t i;
	for (j = 0; j < 7; j += 1) {
		for (i = 0; i < 16; i += 1) {
			ret.words[j][i] = state.words[j][i] ^ 0xff;
		}
	}

	for (i = 0; i < 16; i += 1) {
		ret.words[7][i] = state.words[7][i] ^ (uint8_t) (255 - 16 * i) ^ round;
	}

	return ret;
}

state_t sub_bytes(state_t state) {
    state_t ret;

	uint32_t i;
	uint32_t j;
    for (i = 0; i < 8; i += 1) {
    	for (j = 0; j < 16; j += 1) {
    		ret.words[i][j] = sbox(state.words[i][j]);
    	}
    }

    return ret;
}

state_t shift_bytes_P(state_t state) {
    state_t ret;

    uint32_t i;
    for (i = 0; i < 16; i += 1) {
    	ret.words[0][i] = state.words[0][(i - 0) % 16];
    	ret.words[1][i] = state.words[1][(i - 1) % 16];
    	ret.words[2][i] = state.words[2][(i - 2) % 16];
    	ret.words[3][i] = state.words[3][(i - 3) % 16];
    	ret.words[4][i] = state.words[4][(i - 4) % 16];
    	ret.words[5][i] = state.words[5][(i - 5) % 16];
    	ret.words[6][i] = state.words[6][(i - 6) % 16];
    	ret.words[7][i] = state.words[7][(i - 11) % 16];
    }

    return ret;
}

state_t shift_bytes_Q(state_t state) {
	state_t ret;

	uint32_t i;
	for (i = 0; i < 16; i += 1) {
		ret.words[0][i] = state.words[0][(i - 1) % 16];
		ret.words[1][i] = state.words[1][(i - 3) % 16];
		ret.words[2][i] = state.words[2][(i - 5) % 16];
		ret.words[3][i] = state.words[3][(i - 11) % 16];
		ret.words[4][i] = state.words[4][(i - 0) % 16];
		ret.words[5][i] = state.words[5][(i - 2) % 16];
		ret.words[6][i] = state.words[6][(i - 4) % 16];
		ret.words[7][i] = state.words[7][(i - 6) % 16];
	}

	return ret;
}

state_t inner_round_P(state_t state, uint32_t round) {
	state_t ret = add_round_constant_P(state, round);
	ret = sub_bytes(ret);
	ret = shift_bytes_P(ret);
	ret = mix_bytes(ret);

	return ret;
}

state_t inner_round_Q(state_t state, uint32_t round) {
	state_t ret = add_round_constant_Q(state, round);
	ret = sub_bytes(ret);
	ret = shift_bytes_Q(ret);
	ret = mix_bytes(ret);

	return ret;
}

state_t compress_P(state_t state) {
	state_t ret = state;

	uint32_t i;
	for (i = 0; i < 14; i += 1) {
		ret = inner_round_P(ret, i);
	}

	return ret;
}

state_t compress_Q(state_t state) {
	state_t ret = state;

	uint32_t i;
	for (i = 0; i < 14; i += 1) {
		ret = inner_round_Q(ret, i);
	}

	return ret;
}

state_t xor_state(state_t a, state_t b) {
	state_t ret;

	uint32_t i;
	uint32_t j;
	for (i = 0; i < 8; i += 1) {
		for (j = 0; j < 16; j += 1) {
			ret.words[i][j] = a.words[i][j] ^ b.words[i][j];
		}
	}

	return ret;
}

state_t groestl(state_t state) {
	state_t mid = xor_state(compress_P(state), compress_Q(state));
	return compress_P(mid);
}
