#include "uintN_t.h"

#pragma MAIN_MHZ keccak1600 500.0

#define ROTL64(x, y) rotl64_##y(x)

typedef struct state_t {
    uint64_t words[5][5];
} state_t;

state_t keccak1600_round(state_t state) {
	uint64_t c[5];
	uint64_t d[5];
	uint64_t b[5][5];
	state_t a2;

	uint32_t x, y;
	for (x = 0; x < 5; x += 1) {
		c[x] = state.words[x][0] ^ state.words[x][1] ^ state.words[x][2] ^ state.words[x][3] ^ state.words[x][4];
	}

	d[0] = c[4] ^ ROTL64(c[1], 1);
	d[1] = c[0] ^ ROTL64(c[2], 1);
	d[2] = c[1] ^ ROTL64(c[3], 1);
	d[3] = c[2] ^ ROTL64(c[4], 1);
	d[4] = c[3] ^ ROTL64(c[0], 1);

	b[0][(2 * 0 + 3 * 0) % 5] = ROTL64(state.words[0][0] ^ d[0], 0);
	b[1][(2 * 0 + 3 * 1) % 5] = ROTL64(state.words[0][1] ^ d[0], 36);
	b[2][(2 * 0 + 3 * 2) % 5] = ROTL64(state.words[0][2] ^ d[0], 3);
	b[3][(2 * 0 + 3 * 3) % 5] = ROTL64(state.words[0][3] ^ d[0], 41);
	b[4][(2 * 0 + 3 * 4) % 5] = ROTL64(state.words[0][4] ^ d[0], 18);

	b[0][(2 * 1 + 3 * 0) % 5] = ROTL64(state.words[1][0] ^ d[1], 1);
	b[1][(2 * 1 + 3 * 1) % 5] = ROTL64(state.words[1][1] ^ d[1], 44);
	b[2][(2 * 1 + 3 * 2) % 5] = ROTL64(state.words[1][2] ^ d[1], 10);
	b[3][(2 * 1 + 3 * 3) % 5] = ROTL64(state.words[1][3] ^ d[1], 45);
	b[4][(2 * 1 + 3 * 4) % 5] = ROTL64(state.words[1][4] ^ d[1], 2);

	b[0][(2 * 2 + 3 * 0) % 5] = ROTL64(state.words[2][0] ^ d[2], 62);
	b[1][(2 * 2 + 3 * 1) % 5] = ROTL64(state.words[2][1] ^ d[2], 6);
	b[2][(2 * 2 + 3 * 2) % 5] = ROTL64(state.words[2][2] ^ d[2], 43);
	b[3][(2 * 2 + 3 * 3) % 5] = ROTL64(state.words[2][3] ^ d[2], 15);
	b[4][(2 * 2 + 3 * 4) % 5] = ROTL64(state.words[2][4] ^ d[2], 61);

	b[0][(2 * 3 + 3 * 0) % 5] = ROTL64(state.words[3][0] ^ d[3], 28);
	b[1][(2 * 3 + 3 * 1) % 5] = ROTL64(state.words[3][1] ^ d[3], 55);
	b[2][(2 * 3 + 3 * 2) % 5] = ROTL64(state.words[3][2] ^ d[3], 25);
	b[3][(2 * 3 + 3 * 3) % 5] = ROTL64(state.words[3][3] ^ d[3], 21);
	b[4][(2 * 3 + 3 * 4) % 5] = ROTL64(state.words[3][4] ^ d[3], 56);

	b[0][(2 * 4 + 3 * 0) % 5] = ROTL64(state.words[4][0] ^ d[4], 27);
	b[1][(2 * 4 + 3 * 1) % 5] = ROTL64(state.words[4][1] ^ d[4], 20);
	b[2][(2 * 4 + 3 * 2) % 5] = ROTL64(state.words[4][2] ^ d[4], 39);
	b[3][(2 * 4 + 3 * 3) % 5] = ROTL64(state.words[4][3] ^ d[4], 8);
	b[4][(2 * 4 + 3 * 4) % 5] = ROTL64(state.words[4][4] ^ d[4], 14);

	for (x = 0; x < 5; x += 1) {
			for (y = 0; y < 5; y += 1) {
				a2.words[x][y] = b[x][y] ^ ~b[(x + 1) % 5][y] & b[(x + 2) % 5][y];
			}
	}
	
	return a2;
}

state_t keccak1600(state_t state) {
	uint64_t rc[24];
	rc[0] = 0x0000000000000001;
	rc[1] = 0x0000000000008082;
	rc[2] = 0x800000000000808A;
	rc[3] = 0x8000000080008000;
	rc[4] = 0x000000000000808B;
	rc[5] = 0x0000000080000001;
	rc[6] = 0x8000000080008081;
	rc[7] = 0x8000000000008009;
	rc[8] = 0x000000000000008A;
	rc[9] = 0x0000000000000088;
	rc[10] = 0x0000000080008009;
	rc[11] = 0x000000008000000A;
	rc[12] = 0x000000008000808B;
	rc[13] = 0x800000000000008B;
	rc[14] = 0x8000000000008089;
	rc[15] = 0x8000000000008003;
	rc[16] = 0x8000000000008002;
	rc[17] = 0x8000000000000080;
	rc[18] = 0x000000000000800A;
	rc[19] = 0x800000008000000A;
	rc[20] = 0x8000000080008081;
	rc[21] = 0x8000000000008080;
	rc[22] = 0x0000000080000001;
	rc[23] = 0x8000000080008008;

	state_t tmp;
	tmp = keccak1600_round(state);
	tmp.words[0][0] ^= rc[0];

	uint32_t i;
	for (i = 1; i < 24; i += 1) {
		tmp = keccak1600_round(tmp);
		tmp.words[0][0] ^= rc[i];
	}

	return tmp;
}
