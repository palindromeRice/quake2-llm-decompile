/* Domain: val >= 0. The original never terminates for negative val
 * (arithmetic right shift of -1 stays -1), so negatives are excluded. */
#include "common.h"
int Q_log2 (int val);
int RECON (int val);
static void check (int v) { int o = Q_log2 (v), r = RECON (v); CHECK (o != r, "in=%d orig=%d recon=%d", v, o, r); }
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (is_dev (argv)) { for (int i = 0; i < 4096; i++) check (i); for (int b = 0; b < 31; b++) { check (1 << b); check ((1 << b) - 1); check ((1 << b) + 1); } check (0x7fffffff); }
	for (int i = 0; i < 100000; i++) check ((int)(rng_u32 () & 0x7fffffff) >> (rng_u32 () % 31));
	return finish (argv[1]);
}
