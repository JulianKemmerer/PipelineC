#include <stdio.h>
#include <stdint.h>

#define ROTL64(x, y)			(((x) << (y)) | ((x) >> (64 - (y))))

#define SKEIN_KS_PARITY			0x5555555555555555ULL

const uint64_t SKEIN1024_IV[16] =
{
	0x5A4352BE62092156ULL, 0x5F6E8B1A72F001CAULL, 0xFFCBFE9CA1A2CE26ULL, 0x6C23C39667038BCAULL,
	0x583A8BFCCE34EB6CULL, 0x3FDBFB11D4A46A3EULL, 0x3304ACFCA8300998ULL, 0xB2F6675FA17F0FD2ULL,
	0x9D2599730EF7AB6BULL, 0x0914A20D3DFEA9E4ULL, 0xCC1A9CAFA494DBD3ULL, 0x9828030DA0A6388CULL,
	0x0D339D5DAADEE3DCULL, 0xFC46DE35C4E2A086ULL, 0x53D6E4F52E19A6D1ULL, 0x5663952F715D1DDDULL
};

const uint64_t keccakf_rnd_consts[24] = 
{
    0x0000000000000001ULL, 0x0000000000008082ULL, 0x800000000000808AULL,
    0x8000000080008000ULL, 0x000000000000808BULL, 0x0000000080000001ULL,
    0x8000000080008081ULL, 0x8000000000008009ULL, 0x000000000000008AULL,
    0x0000000000000088ULL, 0x0000000080008009ULL, 0x000000008000000AULL,
    0x000000008000808BULL, 0x800000000000008BULL, 0x8000000000008089ULL,
    0x8000000000008003ULL, 0x8000000000008002ULL, 0x8000000000000080ULL, 
    0x000000000000800AULL, 0x800000008000000AULL, 0x8000000080008081ULL,
    0x8000000000008080ULL, 0x0000000080000001ULL, 0x8000000080008008ULL
};

//#define SKEIN_INJECT_KEY(p, s)	do { \
	p += h; \
	p.sd += t[(s) % 3]; \
	p.se += t[((s) + 1) % 3]; \
	p.sf += (s); \
} while(0)

static void RotateSkeinKey(uint64_t *h)
{
	uint64_t tmp = h[0];

	for(int i = 0; i < 16; ++i) h[i] = h[i + 1];

	h[16] = tmp;
}

void SkeinInjectKey(uint64_t *p, const uint64_t *h, const uint64_t *t, int s)
{
	for(int i = 0; i < 16; ++i) p[i] += h[i];

	p[13] += t[s % 3];
	p[14] += t[(s + 1) % 3];
	p[15] += s;
}

void SkeinMix8(uint64_t *pv0, uint64_t *pv1, const uint32_t rc0, const uint32_t rc1, const uint32_t rc2, const uint32_t rc3, const uint32_t rc4, const uint32_t rc5, const uint32_t rc6, const uint32_t rc7)
{
	uint64_t Temp[8];
	
	for(int i = 0; i < 8; ++i) pv0[i] += pv1[i];
		
	pv1[0] = ROTL64(pv1[0], rc0);
	pv1[1] = ROTL64(pv1[1], rc1);
	pv1[2] = ROTL64(pv1[2], rc2);
	pv1[3] = ROTL64(pv1[3], rc3);
	pv1[4] = ROTL64(pv1[4], rc4);
	pv1[5] = ROTL64(pv1[5], rc5);
	pv1[6] = ROTL64(pv1[6], rc6);
	pv1[7] = ROTL64(pv1[7], rc7);
	
	for(int i = 0; i < 8; ++i) pv1[i] ^= pv0[i];
	
	memcpy(Temp, pv0, 64);
	
	pv0[0] = Temp[0];
	pv0[1] = Temp[1];
	pv0[2] = Temp[3];
	pv0[3] = Temp[2];
	pv0[4] = Temp[5];
	pv0[5] = Temp[6];
	pv0[6] = Temp[7];
	pv0[7] = Temp[4];
	
	memcpy(Temp, pv1, 64);

	pv1[0] = Temp[4];
	pv1[1] = Temp[6];
	pv1[2] = Temp[5];
	pv1[3] = Temp[7];
	pv1[4] = Temp[3];
	pv1[5] = Temp[1];
	pv1[6] = Temp[2];
	pv1[7] = Temp[0];
}

void SkeinEvenRound(uint64_t *p)
{
	uint64_t pv0[8], pv1[8];

	for(int i = 0; i < 16; i++)
	{
		if(i & 1) pv1[i >> 1] = p[i];
		else pv0[i >> 1] = p[i];
	}	
	
	SkeinMix8(pv0, pv1, 55, 43, 37, 40, 16, 22, 38, 12);
	
	SkeinMix8(pv0, pv1, 25, 25, 46, 13, 14, 13, 52, 57);
	
	SkeinMix8(pv0, pv1, 33, 8, 18, 57, 21, 12, 32, 54);
	
	SkeinMix8(pv0, pv1, 34, 43, 25, 60, 44, 9, 59, 34);
	
	for(int i = 0; i < 16; ++i)
	{
		if(i & 1) p[i] = pv1[i >> 1];
		else p[i] = pv0[i >> 1];
	}
}

void SkeinOddRound(uint64_t *p)
{
	uint64_t pv0[8], pv1[8];

	for(int i = 0; i < 16; i++)
	{
		if(i & 1) pv1[i >> 1] = p[i];
		else pv0[i >> 1] = p[i];
	}
	
	SkeinMix8(pv0, pv1, 28, 7, 47, 48, 51, 9, 35, 41);
	
	SkeinMix8(pv0, pv1, 17, 6, 18, 25, 43, 42, 40, 15);
	
	SkeinMix8(pv0, pv1, 58, 7, 32, 45, 19, 18, 2, 56);
	
	SkeinMix8(pv0, pv1, 47, 49, 27, 58, 37, 48, 53, 56);
	
	for(int i = 0; i < 16; ++i)
	{
		if(i & 1) p[i] = pv1[i >> 1];
		else p[i] = pv0[i >> 1];
	}
}

void SkeinRoundTest(uint64_t *State, uint64_t *Key, uint64_t *Type)
{
	//uint64_t StateBak[16];

	//memcpy(StateBak, State, 128);
	
	for(int i = 0; i < 20; i += 2)
	{
		SkeinInjectKey(State, Key, Type, i);
		
		//printf("\nState after key injection %d:\n", i);
		//DumpVerilogStyle(State, 128);
		
		SkeinEvenRound(State);
		RotateSkeinKey(Key);

		//printf("\nState after round %d:\n", i);
		//DumpVerilogStyle(State, 128);

		//printf("\nKey after rotation:\n");
		//DumpVerilogStyle(Key, 136);
		
		SkeinInjectKey(State, Key, Type, i + 1);
		
		//printf("\nState after key injection %d:\n", i + 1);
		//DumpVerilogStyle(State, 128);
		
		SkeinOddRound(State);
		RotateSkeinKey(Key);

		//printf("\nState after round %d:\n", i + 1);
		//DumpVerilogStyle(State, 128);

		//printf("\nKey after rotation:\n");
		//DumpVerilogStyle(Key, 136);
	}

	SkeinInjectKey(State, Key, Type, 20);

	//for(int i = 0; i < 16; ++i) State[i] ^= StateBak[i];
	
	// I am cheap and dirty. x.x
	RotateSkeinKey(Key);
	RotateSkeinKey(Key);
	RotateSkeinKey(Key);
	RotateSkeinKey(Key);
	RotateSkeinKey(Key);
}

void NXSMidstate(uint64_t *OutputKey, uint64_t *Input)
{
	uint64_t h[17], p[16], t[3];

	memcpy(p, Input, 128);
	memcpy(h, SKEIN1024_IV, 128);
	
	h[16] = SKEIN_KS_PARITY;
	for(int i = 0; i < 16; ++i) h[16] ^= h[i];
		
	t[0] = 0x80ULL;
	t[1] = 0x7000000000000000ULL;
	t[2] = 0x7000000000000080ULL;

	SkeinRoundTest(p, h, t);

	h[16] = SKEIN_KS_PARITY;
	for(int i = 0; i < 16; ++i)
	{
		h[i] = Input[i] ^ p[i];
		h[16] ^= h[i];
	}
	
	printf("Key output (after midstate, the feed-forward data for Skein-1024):\n");
	DumpQwords(h, 17);
	DumpVerilogStyle(h, 136);
	
	memcpy(OutputKey, h, 136);
}

void keccakf(uint64_t *st)
{
    for(int i = 0; i < 24; ++i) 
    {
		uint64_t bc[5], tmp;
		
		bc[0] = st[4] ^ st[9] ^ st[14] ^ st[19] ^ st[24] ^ ROTL64(st[1] ^ st[6] ^ st[11] ^ st[16] ^ st[21], 1); 
		bc[1] = st[0] ^ st[5] ^ st[10] ^ st[15] ^ st[20] ^ ROTL64(st[2] ^ st[7] ^ st[12] ^ st[17] ^ st[22], 1); 
		bc[2] = st[1] ^ st[6] ^ st[11] ^ st[16] ^ st[21] ^ ROTL64(st[3] ^ st[8] ^ st[13] ^ st[18] ^ st[23], 1); 
		bc[3] = st[2] ^ st[7] ^ st[12] ^ st[17] ^ st[22] ^ ROTL64(st[4] ^ st[9] ^ st[14] ^ st[19] ^ st[24], 1); 
		bc[4] = st[3] ^ st[8] ^ st[13] ^ st[18] ^ st[23] ^ ROTL64(st[0] ^ st[5] ^ st[10] ^ st[15] ^ st[20], 1); 
		st[0] ^= bc[0]; 
		
		tmp = ROTL64(st[ 1] ^ bc[1], 1); 
		st[ 1] = ROTL64(st[ 6] ^ bc[1], 44); 
		st[ 6] = ROTL64(st[ 9] ^ bc[4], 20); 
		st[ 9] = ROTL64(st[22] ^ bc[2], 61); 
		st[22] = ROTL64(st[14] ^ bc[4], 39); 
		st[14] = ROTL64(st[20] ^ bc[0], 18); 
		st[20] = ROTL64(st[ 2] ^ bc[2], 62); 
		st[ 2] = ROTL64(st[12] ^ bc[2], 43); 
		st[12] = ROTL64(st[13] ^ bc[3], 25); 
		st[13] = ROTL64(st[19] ^ bc[4],  8); 
		st[19] = ROTL64(st[23] ^ bc[3], 56); 
		st[23] = ROTL64(st[15] ^ bc[0], 41); 
		st[15] = ROTL64(st[ 4] ^ bc[4], 27); 
		st[ 4] = ROTL64(st[24] ^ bc[4], 14); 
		st[24] = ROTL64(st[21] ^ bc[1],  2); 
		st[21] = ROTL64(st[ 8] ^ bc[3], 55); 
		st[ 8] = ROTL64(st[16] ^ bc[1], 45); 
		st[16] = ROTL64(st[ 5] ^ bc[0], 36); 
		st[ 5] = ROTL64(st[ 3] ^ bc[3], 28); 
		st[ 3] = ROTL64(st[18] ^ bc[3], 21); 
		st[18] = ROTL64(st[17] ^ bc[2], 15); 
		st[17] = ROTL64(st[11] ^ bc[1], 10); 
		st[11] = ROTL64(st[ 7] ^ bc[2],  6); 
		st[ 7] = ROTL64(st[10] ^ bc[0],  3); 
		st[10] = tmp; 
		
		bc[0] = st[ 0]; bc[1] = st[ 1]; st[ 0] ^= (~bc[1]) & st[ 2]; st[ 1] ^= (~st[ 2]) & st[ 3]; st[ 2] ^= (~st[ 3]) & st[ 4]; st[ 3] ^= (~st[ 4]) & bc[0]; st[ 4] ^= (~bc[0]) & bc[1]; 
		bc[0] = st[ 5]; bc[1] = st[ 6]; st[ 5] ^= (~bc[1]) & st[ 7]; st[ 6] ^= (~st[ 7]) & st[ 8]; st[ 7] ^= (~st[ 8]) & st[ 9]; st[ 8] ^= (~st[ 9]) & bc[0]; st[ 9] ^= (~bc[0]) & bc[1]; 
		bc[0] = st[10]; bc[1] = st[11]; st[10] ^= (~bc[1]) & st[12]; st[11] ^= (~st[12]) & st[13]; st[12] ^= (~st[13]) & st[14]; st[13] ^= (~st[14]) & bc[0]; st[14] ^= (~bc[0]) & bc[1]; 
		bc[0] = st[15]; bc[1] = st[16]; st[15] ^= (~bc[1]) & st[17]; st[16] ^= (~st[17]) & st[18]; st[17] ^= (~st[18]) & st[19]; st[18] ^= (~st[19]) & bc[0]; st[19] ^= (~bc[0]) & bc[1]; 
		bc[0] = st[20]; bc[1] = st[21]; st[20] ^= (~bc[1]) & st[22]; st[21] ^= (~st[22]) & st[23]; st[22] ^= (~st[23]) & st[24]; st[23] ^= (~st[24]) & bc[0]; st[24] ^= (~bc[0]) & bc[1]; 
		
		st[0] ^= keccakf_rnd_consts[i];

		//printf("\nState after round %d:\n", i);
		//DumpVerilogStyle(st, 200);
    }
}

uint8_t RandomTestVector[128] =
{
	0x31,0xfa,0x46,0xa4,0xb3,0xcb,0xce,0x1b,0xb1,0xb3,0xd8,0xd9,0x33,0x35,0x6b,0xfd,
	0x6d,0xe5,0x04,0xc5,0x8f,0x85,0x6e,0x3d,0xf7,0xfa,0x9d,0xb6,0xcd,0x94,0x4b,0xa3,
	0x46,0x8e,0x2b,0x89,0x45,0x48,0x6c,0xa1,0x3f,0x1f,0xbe,0x09,0x59,0x7d,0xb0,0x41,
	0xf4,0x1d,0x4b,0xad,0x1b,0x8c,0xf7,0xf7,0xb7,0x81,0x9e,0x3b,0x0a,0x5f,0x1e,0x37,
	0x55,0x03,0x7c,0x64,0xdb,0xac,0x8f,0xf9,0x8b,0x82,0x8a,0x09,0x8d,0x7b,0xf2,0x60,
	0xa1,0x74,0xd8,0x8e,0xa6,0xd3,0x43,0x57,0x13,0x6c,0xe1,0x0d,0xb9,0xd5,0xff,0x1b,
	0xb2,0x4f,0xb9,0x29,0xca,0x42,0xd4,0xae,0x19,0x65,0x7b,0xb3,0x9e,0x33,0x49,0x26,
	0x2e,0xc2,0x4c,0xc7,0x49,0x61,0x54,0xf4,0x34,0xcd,0x91,0x12,0xa6,0xa0,0xd8,0xa6
};

uint8_t RandomKey[136] =
{
	0xd4, 0xc7, 0xb4, 0xa8, 0x20, 0x61, 0x64, 0x34, 0x0a, 0xf3, 0xfe, 0xa8, 0xff, 0x6f, 0x98, 0xab,
	0x9e, 0xbf, 0x87, 0x87, 0xdf, 0x5e, 0x24, 0x3e, 0x7b, 0xb7, 0x79, 0xd4, 0x03, 0x10, 0x7a, 0x79,
	0xa4, 0x47, 0x9e, 0xcb, 0x80, 0x48, 0x67, 0x5e, 0xd7, 0xb3, 0x5f, 0x60, 0x18, 0x7a, 0x6f, 0xd8,
	0x1e, 0xe8, 0x30, 0x88, 0x71, 0x4d, 0x27, 0x3e, 0x27, 0x65, 0x5c, 0x06, 0x42, 0x5d, 0x1d, 0x10,
	0x67, 0xc9, 0xf0, 0x28, 0x8e, 0x23, 0x9f, 0x9b, 0xf9, 0x89, 0xc5, 0x23, 0x48, 0x24, 0xab, 0xe2,
	0x85, 0x52, 0x9b, 0x73, 0xa1, 0x2f, 0xcb, 0xf3, 0x76, 0xbe, 0x8d, 0x64, 0x63, 0xd2, 0xe9, 0xb1,
	0xb8, 0xec, 0xfd, 0x77, 0xf8, 0x6d, 0xb5, 0xab, 0xf3, 0x27, 0x61, 0xa9, 0x9e, 0xd6, 0xc1, 0x57,
	0xf0, 0xc8, 0x6c, 0xcc, 0x6a, 0x08, 0xa3, 0x71, 0x19, 0xf8, 0x97, 0x78, 0xbe, 0x80, 0x76, 0x16,
	0xf7, 0x86, 0xe3, 0xa2, 0x5e, 0x28, 0x40, 0x51
};

uint8_t RandomType[24] =
{
	0x3c, 0xb2, 0xe1, 0xa3, 0x83, 0x76, 0x2e, 0x24, 0x9c, 0x8f, 0xe0, 0xcb, 0xc0, 0x44, 0x3f, 0xaa,
	0xa3, 0x49, 0xd0, 0x80, 0xbc, 0x18, 0x48, 0xcd
};

// Nonce: 0x000000006498537B
uint64_t NXSTestHeader[27] =
{
	0x27B654ED00000008, 0xEE1D76908B505DD8, 0x9C802A52F6DF8AE4, 0xBE8C37115DD10DC7, 0xA79AB7E9CE491C06, 0x7C3CDDB70ABBC413, 0x9803FEB0767BD078, 0x55B423CB6D5631C8, 
	0x4696F99671448C1D, 0xC5189959FCA6F28D, 0xE6DC9BA87FDF6999, 0x1C30A6B7908A2A56, 0xBF2B59262FA90644, 0xF50E8C60F82604BC, 0x9516C15DABF27CF5, 0x7E2AF50CCE5C74DD, 
	0xDBCD6FE21B65A290, 0x06DF1973D1E4438E, 0x5BBED36C31570239, 0xE4A0A20A3C343BA8, 0x159BF93BBD8FDE57, 0xC63E601430361FFA, 0x0F3F29B6F456862D, 0xDB09CB623352A916, 
	0x00000002BD97BE01, 0x7B01B1D000396D8D,
};

void DumpQwords(void *data, int len)
{
	putchar('\n');
	for(int i = 0; i < len; ++i)
	{
		if(!(i & 3) && i) printf("0x%016llX,\n", ((uint64_t *)data)[i]);
		else if(i == (len - 1)) printf("0x%016llX\n\n", ((uint64_t *)data)[i]);
		else printf("0x%016llX, ", ((uint64_t *)data)[i]);
	}
}

void DumpVerilogStyle(void *data, int len)
{
	printf("%d'h", len << 3);
	
	for(int i = len - 1; i >= 0; --i) printf("%02X", ((uint8_t *)data)[i]);
	printf("\n");
}

uint64_t DoNXSTest(uint64_t *State, uint64_t *Key, uint64_t Nonce)
{
	uint64_t Type[3], P[16];
	
	((uint64_t *)Type)[0] = 0xD8ULL;
	((uint64_t *)Type)[1] = 0xB000000000000000ULL;
	((uint64_t *)Type)[2] = 0xB0000000000000D8ULL;
	
	// loads low 8 qwords
	// remember that we skip past the old data already processed
	// during the midstate - see vload8(2, uMessage) in ref OCL.
	memcpy(P, State + 16, 64);
	
	P[8] = State[24];
	P[9] = State[25];
	P[10] = Nonce;
	
	for(int i = 11; i < 16; ++i) P[i] = 0ULL;
	
	printf("State before Skein block:\n");
	DumpQwords(P, 16);
	DumpVerilogStyle(P, 128);
	
	printf("Key before Skein block:\n");
	DumpQwords(Key, 16);
	DumpVerilogStyle(P, 128);
	
	SkeinRoundTest(P, Key, Type);
	
	printf("\nResult after full Skein block process #2:\n");
	DumpQwords(P, 16);
	DumpVerilogStyle(P, 128);
	
	for(int i = 0; i < 8; ++i) Key[i] = P[i] ^ State[16 + i];
	
	Key[8] = P[8] ^ State[24];
	Key[9] = P[9] ^ State[25];
	Key[10] = P[10] ^ Nonce;
	
	for(int i = 11; i < 16; ++i) Key[i] = P[i];
	
	// Clear P, the state argument to the final block is zero.
	memset(P, 0x00, 128);
	((uint64_t *)Key)[16] = SKEIN_KS_PARITY;
	for(int i = 0; i < 16; ++i) ((uint64_t *)Key)[16] ^= ((uint64_t *)Key)[i];
	
	((uint64_t *)Type)[0] = 0x08ULL;
	((uint64_t *)Type)[1] = 0xFF00000000000000ULL;
	((uint64_t *)Type)[2] = 0xFF00000000000008ULL;

	SkeinRoundTest(P, Key, Type);
	
	printf("\nResult after full Skein block process #3:\n");
	DumpQwords(P, 16);
	DumpVerilogStyle(P, 128);
	
	uint64_t KeccakState[25];

	memset(KeccakState, 0x00, 200);
	
	// Copying qwords 0 - 8 (inclusive, so 9 qwords).
	// Note this is technically an XOR operation, just
	// with zero in this instance.
	memcpy(KeccakState, P, 72);
	
	keccakf(KeccakState);
	
	for(int i = 0; i < 7; ++i)	KeccakState[i] ^= ((uint64_t *)P)[i + 9];

	KeccakState[7] ^= 0x0000000000000005ULL;
	KeccakState[8] ^= 0x8000000000000000ULL;
	
	keccakf(KeccakState);

	keccakf(KeccakState);
	
	return(KeccakState[6]);
}

int main()
{
	uint8_t State[216], Key[136], Type[24];
	
	memcpy(State, NXSTestHeader, 216);
	
	printf("Block input (after midstate, the remainder of the data to be hashed):\n");
	DumpQwords(State + 128, 10);
	DumpVerilogStyle(State + 128, 80);
	
	NXSMidstate(Key, State);
	
	printf("Key output:\n");
	DumpQwords(Key, 17);
	DumpVerilogStyle(Key, 136);
	
	//memcpy(State, RandomTestVector, 128);
	//memcpy(Key, RandomKey, 136);
	//memcpy(Type, RandomType, 24);
	

	//memset(State + 80, 0x00, 128 - 80);
	
	printf("Test vector input:\n");
	DumpQwords(State + 16, 16);
	DumpVerilogStyle(State, 128);

	printf("Test key input:\n");
	DumpQwords(Key, 17);
	DumpVerilogStyle(Key, 136);
	
	//0x00000001FCAFC045
	uint64_t res = DoNXSTest(State, Key, 0x00000001FCAFC045ULL);
	
	printf("Output qword: 0x%016llX\n", res);
	
	return(0);
}
