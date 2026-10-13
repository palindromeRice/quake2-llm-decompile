#include "common.h"
int bit_span (unsigned v);
int RECON (unsigned v);
static void check (unsigned v) { int o = bit_span (v), r = RECON (v); CHECK (o != r, "in=%#x orig=%d recon=%d", v, o, r); }
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (is_dev (argv)) { for (unsigned i = 0; i < 4096; i++) check (i); for (int b = 0; b < 32; b++) { check (1u << b); check ((1u << b) - 1); check (~0u << b); } }
	for (int i = 0; i < 100000; i++) check (rng_u32 () >> (rng_u32 () % 32) << (rng_u32 () % 32));
	return finish (argv[1]);
}
