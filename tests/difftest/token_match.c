#include "common.h"
int token_match (const char *pattern, const char *s);
int RECON (const char *pattern, const char *s);
static void check (const char *a, const char *b) { int o = token_match (a, b), r = RECON (a, b); CHECK (o != r, "in=(\"%s\",\"%s\") orig=%d recon=%d", a, b, o, r); }
static void rand_str (char *s, int len, int pat)
{
	static const char al[] = "aAbBzZ@[`{?*09 \x7f\x80\xff";
	int n = sizeof al - 1 - (pat ? 0 : 2);
	for (int i = 0; i < len; i++) s[i] = pat ? al[rng_u32 () % n] : al[(rng_u32 () % n) < 12 ? rng_u32 () % 12 : 14 + rng_u32 () % 6];
	s[len] = 0;
}
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (is_dev (argv)) {
		const char *fx[] = {"", "*", "?", "a*", "A?c", "abc", "ABC", "ab", "*x", "a**", "@", "`", "[", "{"};
		int nf = sizeof fx / sizeof fx[0];
		for (int i = 0; i < nf; i++) for (int j = 0; j < nf; j++) check (fx[i], fx[j]);
	}
	char a[32], b[32];
	for (int i = 0; i < 100000; i++) {
		rand_str (b, rng_u32 () % 12, 0);
		if (rng_u32 () % 2) {   /* derive pattern from the string so matches are common */
			strcpy (a, b);
			for (char *q = a; *q; q++) { unsigned t = rng_u32 () % 6; if (t == 0) *q = '?'; else if (t == 1 && ((*q | 32) >= 'a' && (*q | 32) <= 'z')) *q ^= 32; }
			if (rng_u32 () % 3 == 0) { size_t L = strlen (a); unsigned cut = L ? rng_u32 () % (L + 1) : 0; a[cut] = '*'; a[cut + 1] = 0; }
		} else rand_str (a, rng_u32 () % 12, 1);
		check (a, b);
	}
	return finish (argv[1]);
}
