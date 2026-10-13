#include "common.h"
void aim_angles (float *dir, float *out);
void RECON (float *dir, float *out);
static void check (float x, float y, float z)
{
	float a[9] = {1234.5f, x, y, z, 11.0f, 22.0f, 33.0f, -777.25f, 0}, b[9];
	memcpy (b, a, sizeof a);
	aim_angles (a + 1, a + 4);
	RECON (b + 1, b + 4);
	CHECK (bufdiff (a, b, 9), "in=(%a,%a,%a) orig=(%a,%a,%a) recon=(%a,%a,%a)", x, y, z, a[4], a[5], a[6], b[4], b[5], b[6]);
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
