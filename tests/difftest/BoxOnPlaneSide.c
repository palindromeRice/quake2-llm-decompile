/* Domain: valid planes as the engine builds them -- signbits consistent with
 * the normal's signs, no NaN. Inconsistent planes can trip the original's
 * assert(sides != 0), so they are excluded. Return compared as int (the
 * original's ABI contract). */
#include "common.h"
typedef struct { float normal[3]; float dist; unsigned char type, signbits, pad[2]; } plane_t;
int BoxOnPlaneSide (float *emins, float *emaxs, plane_t *p);
int RECON (float *emins, float *emaxs, plane_t *p);
static void check (float *mins, float *maxs, plane_t p)
{
	plane_t q = p;
	int o = BoxOnPlaneSide (mins, maxs, &p), r = RECON (mins, maxs, &q);
	CHECK (o != r || memcmp (&p, &q, sizeof p), "type=%d sb=%d n=(%a,%a,%a) d=%a orig=%d recon=%d", p.type, p.signbits, p.normal[0], p.normal[1], p.normal[2], p.dist, o, r);
}
static plane_t make_plane (float nx, float ny, float nz, float d, int axial)
{
	plane_t p = {{nx, ny, nz}, d, 0, 0, {0, 0}};
	for (int i = 0; i < 3; i++) if (p.normal[i] < 0) p.signbits |= 1 << i;
	p.type = axial >= 0 ? axial : 3 + (rng_u32 () % 3);   /* PLANE_X..Z or PLANE_ANYX..ANYZ */
	return p;
}
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	for (int i = 0; i < 60000; i++) {
		float mins[3], maxs[3], c[3];
		float s = is_dev (argv) && i < 10000 ? 16 : 4096;
		for (int k = 0; k < 3; k++) { c[k] = rng_range (-s, s); float h = rng_range (0, s / 4); mins[k] = c[k] - h; maxs[k] = c[k] + h; }
		int axial = (i % 4 == 0) ? (int)(rng_u32 () % 3) : -1;
		float n[3] = {rng_range (-1, 1), rng_range (-1, 1), rng_range (-1, 1)};
		if (i % 7 == 0) n[rng_u32 () % 3] = 0;   /* zero components: -0/+0 sign handling */
		float d = (i % 5 == 0) ? n[0] * c[0] + n[1] * c[1] + n[2] * c[2] : rng_range (-2 * s, 2 * s);
		if (axial >= 0 && i % 8 == 0) d = (i % 16 == 0) ? mins[axial] : maxs[axial];   /* exact-boundary ties */
		check (mins, maxs, make_plane (n[0], n[1], n[2], d, axial));
	}
	return finish (argv[1]);
}
