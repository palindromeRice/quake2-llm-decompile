#include "common.h"
float anglemod (float a);
float RECON (float a);
static void check (float a) { float o = anglemod (a), r = RECON (a); CHECK (fdiff (o, r), "in=%a orig=%a recon=%a", a, o, r); }
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (is_dev (argv)) for (int i = 0; i < N_EDGE; i++) check (EDGE[i]);
	for (int i = 0; i < 50000; i++) check (rng_range (-100000, 100000));
	for (int i = 0; i < 50000; i++) check (rng_bits_float ());
	return finish (argv[1]);
}
