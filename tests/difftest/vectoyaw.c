/* Differential test: float f(float vec[3]). Compares return bits and the
 * full input buffer (incl. guard words) after the call. */
#include "common.h"

float vectoyaw (float *vec);   /* original, from build/objs */
float RECON (float *vec);      /* reconstruction, -DRECON=FUN_xxxx */

static void check (float x, float y, float z)
{
	float a[5] = {1234.5f, x, y, z, -777.25f}, b[5];
	char msg[200];
	memcpy (b, a, sizeof a);
	float ro = vectoyaw (a + 1), rr = RECON (b + 1);
	n_cases++;
	if (fdiff (ro, rr) || bufdiff (a, b, 5)) {
		snprintf (msg, sizeof msg, "in=(%a,%a,%a) orig=%a recon=%a", x, y, z, ro, rr);
		report_mismatch (msg);
	}
}

int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (rng_state == 1) {   /* dev: fixed edge-case grid + random */
		float e[] = {0.0f, -0.0f, 1.0f, -1.0f, 0.5f, 1e-30f, -1e-30f, 1e-45f, 1e30f, -1e30f,
		             1.0f / 0.0f, -1.0f / 0.0f, 0.0f / 0.0f, 3.0f, -3.0f, 100.0f};
		int n = sizeof e / sizeof e[0];
		for (int i = 0; i < n; i++) for (int j = 0; j < n; j++) for (int k = 0; k < 3; k++)
			check (e[i], e[j], e[k]);
	}
	for (int i = 0; i < 20000; i++) check (rng_range (-4096, 4096), rng_range (-4096, 4096), rng_range (-4096, 4096));
	for (int i = 0; i < 20000; i++) check (rng_bits_float (), rng_bits_float (), rng_bits_float ());
	for (int i = 0; i < 5000; i++) { float v = rng_range (-10, 10); check (v, (i & 1) ? v : -v, 0); } /* 45-degree diagonals */
	return finish (argv[1]);
}
