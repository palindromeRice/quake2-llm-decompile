/* Checks return value and in-place modification (with guard words). */
#include "common.h"
float VectorNormalize (float *v);
float RECON (float *v);
static void check (float x, float y, float z)
{
	float a[5] = {1234.5f, x, y, z, -777.25f}, b[5];
	memcpy (b, a, sizeof a);
	float o = VectorNormalize (a + 1), r = RECON (b + 1);
	CHECK (fdiff (o, r) || bufdiff (a, b, 5), "in=(%a,%a,%a) orig=%a recon=%a out_o=(%a,%a,%a) out_r=(%a,%a,%a)", x, y, z, o, r, a[1], a[2], a[3], b[1], b[2], b[3]);
}
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (is_dev (argv)) for (int i = 0; i < N_EDGE; i++) for (int j = 0; j < N_EDGE; j++) for (int k = 0; k < N_EDGE; k++) check (EDGE[i], EDGE[j], EDGE[k]);
	for (int i = 0; i < 50000; i++) check (rng_range (-4096, 4096), rng_range (-4096, 4096), rng_range (-4096, 4096));
	for (int i = 0; i < 30000; i++) check (rng_bits_float (), rng_bits_float (), rng_bits_float ());
	return finish (argv[1]);
}
