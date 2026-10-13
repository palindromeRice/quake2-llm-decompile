#include "common.h"
float clamp_length (float *v, float maxlen);
float RECON (float *v, float maxlen);
static void check (float x, float y, float z, float m)
{
	float a[5] = {1234.5f, x, y, z, -777.25f}, b[5];
	memcpy (b, a, sizeof a);
	float o = clamp_length (a + 1, m), r = RECON (b + 1, m);
	CHECK (fdiff (o, r) || bufdiff (a, b, 5), "in=(%a,%a,%a) max=%a orig=%a recon=%a", x, y, z, m, o, r);
}
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (is_dev (argv)) for (int i = 0; i < N_EDGE; i++) for (int j = 0; j < N_EDGE; j++) for (int k = 0; k < N_EDGE; k += 3) check (EDGE[i], EDGE[j], EDGE[k], EDGE[(i + j + k) % N_EDGE]);
	for (int i = 0; i < 50000; i++) check (rng_range (-4096, 4096), rng_range (-4096, 4096), rng_range (-4096, 4096), rng_range (-100, 8000));
	for (int i = 0; i < 30000; i++) check (rng_bits_float (), rng_bits_float (), rng_bits_float (), rng_bits_float ());
	return finish (argv[1]);
}
