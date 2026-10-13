#include "common.h"
float blend_turn (float cur, float target, float rate);
float RECON (float cur, float target, float rate);
static void check (float a, float b, float c) { float o = blend_turn (a, b, c), r = RECON (a, b, c); CHECK (fdiff (o, r), "in=(%a,%a,%a) orig=%a recon=%a", a, b, c, o, r); }
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (is_dev (argv)) for (int i = 0; i < N_EDGE; i++) for (int j = 0; j < N_EDGE; j++) for (int k = 0; k < N_EDGE; k++) check (EDGE[i], EDGE[j], EDGE[k]);
	for (int i = 0; i < 50000; i++) check (rng_range (-720, 720), rng_range (-720, 720), rng_range (-200, 200));
	for (int i = 0; i < 30000; i++) check (rng_bits_float (), rng_bits_float (), rng_bits_float ());
	return finish (argv[1]);
}
