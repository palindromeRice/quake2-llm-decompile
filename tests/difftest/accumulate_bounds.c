/* Checks return value, mins/maxs, and that the point array is untouched. */
#include "common.h"
int accumulate_bounds (float *pts, int n, float *mins, float *maxs);
int RECON (float *pts, int n, float *mins, float *maxs);
#define MAXP 12
static void check (const float *pts, int n)
{
	float a[3 * MAXP + 8], b[3 * MAXP + 8];
	for (int i = 0; i < 3 * MAXP + 8; i++) a[i] = 99.0f;
	memcpy (a + 1, pts, 3 * MAXP * sizeof (float));
	memcpy (b, a, sizeof a);
	int o = accumulate_bounds (a + 1, n, a + 1 + 3 * MAXP, a + 4 + 3 * MAXP);
	int r = RECON (b + 1, n, b + 1 + 3 * MAXP, b + 4 + 3 * MAXP);
	CHECK (o != r || bufdiff (a, b, 3 * MAXP + 8), "n=%d p0=(%a,%a,%a) orig=%d recon=%d", n, pts[0], pts[1], pts[2], o, r);
}
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	float p[3 * MAXP];
	for (int i = 0; i < 60000; i++) {
		int mode = i % 3;
		for (int k = 0; k < 3 * MAXP; k++)
			p[k] = mode == 0 ? rng_range (-4096, 4096) : mode == 1 ? rng_bits_float () : EDGE[rng_u32 () % N_EDGE];
		check (p, (int)(rng_u32 () % (MAXP + 3)) - 2);   /* n in -2..MAXP */
	}
	return finish (argv[1]);
}
