#include "common.h"
typedef struct { float dir[3]; float offset; unsigned char kind, flags; } probe_t;
int classify_box (float *center, float *half, probe_t *p);
int RECON (float *center, float *half, probe_t *p);
static void check (float *c, float *h, probe_t p)
{
	probe_t q = p;
	int o = classify_box (c, h, &p), r = RECON (c, h, &q);
	CHECK (o != r || memcmp (&p, &q, sizeof p), "kind=%d flags=%d c=(%a,%a,%a) h0=%a off=%a orig=%d recon=%d", p.kind, p.flags, c[0], c[1], c[2], h[0], p.offset, o, r);
}
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	for (int i = 0; i < 80000; i++) {
		float c[3], h[3];
		probe_t p;
		memset (&p, 0, sizeof p);
		int wild = i % 5 == 0;
		for (int k = 0; k < 3; k++) {
			c[k] = wild ? rng_bits_float () : rng_range (-512, 512);
			h[k] = wild ? rng_bits_float () : rng_range (0, 128);
			p.dir[k] = wild ? rng_bits_float () : rng_range (-1, 1);
		}
		p.offset = wild ? rng_bits_float () : rng_range (-600, 600);
		p.kind = rng_u32 () % 7;     /* includes unknown kinds 5, 6 */
		p.flags = rng_u32 () % 4;    /* bit 1 is unused by the function */
		check (c, h, p);
	}
	return finish (argv[1]);
}
