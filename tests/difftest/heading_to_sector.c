#include "common.h"
int heading_to_sector (float *dir);
int RECON (float *dir);
static void check (float x, float y, float z)
{
	float a[5] = {1234.5f, x, y, z, -777.25f}, b[5];
	memcpy (b, a, sizeof a);
	int o = heading_to_sector (a + 1), r = RECON (b + 1);
	CHECK (o != r || bufdiff (a, b, 5), "in=(%a,%a,%a) orig=%d recon=%d", x, y, z, o, r);
}
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (is_dev (argv)) for (int i = 0; i < N_EDGE; i++) for (int j = 0; j < N_EDGE; j++) check (EDGE[i], EDGE[j], 0);
	for (int i = 0; i < 50000; i++) check (rng_range (-4096, 4096), rng_range (-4096, 4096), 0);
	for (int i = 0; i < 30000; i++) check (rng_bits_float (), rng_bits_float (), rng_bits_float ());
	for (int i = 0; i < 20000; i++) { float t = rng_range (0, 6.2831853f); check (cosf (t), sinf (t), 0); }   /* near sector edges */
	return finish (argv[1]);
}
