#include "common.h"
float wrap_snap (float a);
float RECON (float a);
static void check (float a) { float o = wrap_snap (a), r = RECON (a); CHECK (fdiff (o, r), "in=%a orig=%a recon=%a", a, o, r); }
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (is_dev (argv)) { for (int i = 0; i < N_EDGE; i++) check (EDGE[i]); check (999999.9f); check (1e6f); check (-1e6f); }
	for (int i = 0; i < 50000; i++) check (rng_range (-2e6f, 2e6f));
	for (int i = 0; i < 50000; i++) check (rng_range (-720, 720));
	for (int i = 0; i < 30000; i++) check (rng_bits_float ());
	for (int i = 0; i < 20000; i++) check ((rng_u32 () % 2000 - 1000) * (360.0f / 512.0f));   /* exact half-steps: rounding ties */
	return finish (argv[1]);
}
