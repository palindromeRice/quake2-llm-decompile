/* Shared helpers for differential test drivers (evaluation side). */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint64_t rng_state;
static uint32_t rng_u32 (void)   /* xorshift64*: libc-independent, reproducible */
{
	rng_state ^= rng_state >> 12; rng_state ^= rng_state << 25; rng_state ^= rng_state >> 27;
	return (uint32_t)((rng_state * 2685821657736338717ULL) >> 32);
}
static float rng_bits_float (void) { uint32_t u = rng_u32 (); float f; memcpy (&f, &u, 4); return f; }
static float rng_range (float lo, float hi) { return lo + (hi - lo) * (rng_u32 () / 4294967296.0f); }
static uint32_t fbits (float f) { uint32_t u; memcpy (&u, &f, 4); return u; }

/* argv[2] == "relaxed": any NaN equals any NaN (sign/payload ignored).
 * Default is strict bit equality. */
static int relaxed;
static int fdiff (float a, float b) { return relaxed ? !((a != a && b != b) || fbits (a) == fbits (b)) : fbits (a) != fbits (b); }
static int bufdiff (const float *a, const float *b, int n) { for (int i = 0; i < n; i++) if (fdiff (a[i], b[i])) return 1; return 0; }

static int n_cases, n_fail;
static void report_mismatch (const char *what)
{
	if (n_fail++ < 10) fprintf (stderr, "MISMATCH %s\n", what);
}
static int finish (const char *split)
{
	printf ("{\"split\": \"%s\", \"relaxed\": %d, \"cases\": %d, \"mismatches\": %d}\n", split, relaxed, n_cases, n_fail);
	return n_fail != 0;
}
/* argv[1] = dev | heldout */
#define SPLIT_SEED(argv) (relaxed = (argv)[2] && strcmp ((argv)[2], "relaxed") == 0, \
                          strcmp ((argv)[1], "dev") == 0 ? 1ULL : 0x9e3779b97f4a7c15ULL)

/* mismatch helper: record one case, report if bad */
#define CHECK(bad, ...) do { n_cases++; if (bad) { char m_[300]; snprintf (m_, sizeof m_, __VA_ARGS__); report_mismatch (m_); } } while (0)

/* float edge values shared by float drivers (dev split only) */
static const float EDGE[] = {0.0f, -0.0f, 1.0f, -1.0f, 0.5f, 1e-30f, -1e-30f, 1e-45f, 1e30f, -1e30f,
                             1.0f / 0.0f, -1.0f / 0.0f, 0.0f / 0.0f, 3.0f, -3.0f, 100.0f, 180.0f, -180.0f, 360.0f, 359.5f};
#define N_EDGE ((int)(sizeof EDGE / sizeof EDGE[0]))
static int is_dev (char **argv) { return strcmp (argv[1], "dev") == 0; }
