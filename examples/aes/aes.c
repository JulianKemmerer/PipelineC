#include "uintN_t.h"

#pragma MAIN_MHZ aes_ten_rounds 850.0

typedef struct state_t {
    uint8_t words[4][4];
} state_t;

uint8_t mulX(uint8_t x) {
    uint1_t tmp[8];
    uint1_t a = uint8_0_0(x);
    uint1_t b = uint8_1_1(x);
    uint1_t c = uint8_2_2(x);
    uint1_t d = uint8_3_3(x);
    uint1_t e = uint8_4_4(x);
    uint1_t f = uint8_5_5(x);
    uint1_t g = uint8_6_6(x);
    uint1_t h = uint8_7_7(x);

    tmp[0] = h;
    tmp[1] = h ^ a;
    tmp[2] = b;
    tmp[3] = h ^ c;
    tmp[4] = h ^ d;
    tmp[5] = e;
    tmp[6] = f;
    tmp[7] = g;

    return uint1_array8_le(tmp);
}

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

state_t sub_bytes(state_t state) {
    state_t res;
    
    uint32_t i;
    for (i = 0; i < 4; i += 1) {
        res.words[i][0] = sbox(state.words[i][0]);
        res.words[i][1] = sbox(state.words[i][1]);
        res.words[i][2] = sbox(state.words[i][2]);
        res.words[i][3] = sbox(state.words[i][3]);
    }
    return res;
}

state_t shift_rows(state_t state) {
    state_t res;

    uint32_t i;
    for (i = 0; i < 4; i += 1) {
        res.words[i][0] = state.words[i][(0 + i) % 4];
        res.words[i][1] = state.words[i][(1 + i) % 4];
        res.words[i][2] = state.words[i][(2 + i) % 4];
        res.words[i][3] = state.words[i][(3 + i) % 4];
    }
    return res;
}

state_t mix_cols(state_t state) {
    uint8_t innerTmp[4][4];
    uint8_t outerTmp[4];
    state_t res;

    uint32_t j;
    for (j = 0; j < 4; j += 1) {
        innerTmp[0][j] = state.words[0][j] ^ state.words[1][j];
        innerTmp[1][j] = state.words[1][j] ^ state.words[2][j];
        innerTmp[2][j] = state.words[2][j] ^ state.words[3][j];
        innerTmp[3][j] = state.words[3][j] ^ state.words[0][j];

        outerTmp[j] = innerTmp[0][j] ^ innerTmp[2][j];

        res.words[0][j] = state.words[0][j] ^ outerTmp[j] ^ mulX(innerTmp[0][j]);
        res.words[1][j] = state.words[1][j] ^ outerTmp[j] ^ mulX(innerTmp[1][j]);
        res.words[2][j] = state.words[2][j] ^ outerTmp[j] ^ mulX(innerTmp[2][j]);
        res.words[3][j] = state.words[3][j] ^ outerTmp[j] ^ mulX(innerTmp[3][j]);
    }
    return res;
}

state_t add_key(state_t state, uint128_t key) {
    state_t res;
    
    uint32_t i;
    for (i = 0; i < 4; i += 1) {
        res.words[i][0] = state.words[i][0] ^ (uint8_t) (key >> (i * 4 + 0));
        res.words[i][1] = state.words[i][1] ^ (uint8_t) (key >> (i * 4 + 8));
        res.words[i][2] = state.words[i][2] ^ (uint8_t) (key >> (i * 4 + 16));
        res.words[i][3] = state.words[i][3] ^ (uint8_t) (key >> (i * 4 + 24));
    }
    return res;
}

state_t aesenc(state_t state, uint128_t key) {
    state_t tmp;
    tmp = sub_bytes(state);
    tmp = shift_rows(tmp);
    tmp = mix_cols(tmp);
    tmp = add_key(tmp, key);
    return tmp;
}

state_t aesenclast(state_t state, uint128_t key) {
    state_t tmp;
    tmp = sub_bytes(state);
    tmp = shift_rows(tmp);
    tmp = add_key(tmp, key);
    return tmp;
}

state_t aes_ten_rounds(state_t state, uint128_t keys[10]) {
    state_t tmp = state;
    uint32_t i;
    for (i = 0; i < 9; i += 1) {
        tmp = aesenc(tmp, keys[i]);
    }
    tmp = aesenclast(tmp, keys[9]);
    return tmp;
}
