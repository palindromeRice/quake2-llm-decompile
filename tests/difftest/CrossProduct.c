/* Checks output and aliasing behaviour (output buffer == an input). */
#include "common.h"
void CrossProduct (float *v1, float *v2, float *cross);
void RECON (float *v1, float *v2, float *cross);
static void check (const float *in)   /* in: 6 floats, v1 then v2 */
{
	for (int alias = 0; alias < 3; alias++) {   /* 0: separate, 1: cross==v1, 2: cross==v2 */
		float a[11], b[11];
		a[0] = 1234.5f; memcpy (a + 1, in, 6 * sizeof (float)); a[7] = a[8] = a[9] = 42.0f; a[10] = -777.25f;
		memcpy (b, a, sizeof a);
		float *oa = alias == 1 ? a + 1 : alias == 2 ? a + 4 : a + 7;
		float *ob = alias == 1 ? b + 1 : alias == 2 ? b + 4 : b + 7;
		CrossProduct (a + 1, a + 4, oa);
		RECON (b + 1, b + 4, ob);
		CHECK (memcmp (a, b, sizeof a), "alias=%d in=(%a,%a,%a)x(%a,%a,%a)", alias, in[0], in[1], in[2], in[3], in[4], in[5]);
	}
}
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	float in[6];
	if (is_dev (argv)) for (int i = 0; i < N_EDGE; i++) for (int j = 0; j < N_EDGE; j++) { for (int k = 0; k < 6; k++) in[k] = (k % 2) ? EDGE[i] : EDGE[j]; check (in); }
	for (int i = 0; i < 30000; i++) { for (int k = 0; k < 6; k++) in[k] = rng_range (-4096, 4096); check (in); }
	for (int i = 0; i < 20000; i++) { for (int k = 0; k < 6; k++) in[k] = rng_bits_float (); check (in); }
	return finish (argv[1]);
}
