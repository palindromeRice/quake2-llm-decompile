#include "common.h"
int Q_strncasecmp (char *s1, char *s2, int n);
int RECON (char *s1, char *s2, int n);
static void check (char *a, char *b, int n) { int o = Q_strncasecmp (a, b, n), r = RECON (a, b, n); CHECK (o != r, "in=(\"%s\",\"%s\",%d) orig=%d recon=%d", a, b, n, o, r); }
static void rand_str (char *s, int len)
{
	static const char al[] = "aAbBzZ@[`{09_ .\x7f\x80\xff";   /* case boundaries + high bytes */
	for (int i = 0; i < len; i++) s[i] = al[rng_u32 () % (sizeof al - 1)];
	s[len] = 0;
}
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (is_dev (argv)) {
		char *fx[] = {"", "a", "A", "abc", "ABC", "abd", "ab", "@", "`", "[", "{", "Quake", "qUAKE2"};
		int nf = sizeof fx / sizeof fx[0];
		for (int i = 0; i < nf; i++) for (int j = 0; j < nf; j++) for (int n = -2; n < 8; n++) check (fx[i], fx[j], n);
	}
	char a[32], b[32];
	for (int i = 0; i < 80000; i++) {
		rand_str (a, rng_u32 () % 12);
		if (rng_u32 () % 2) { strcpy (b, a); for (char *p = b; *p; p++) if (rng_u32 () % 3 == 0 && ((*p | 32) >= 'a' && (*p | 32) <= 'z')) *p ^= 32; }
		else rand_str (b, rng_u32 () % 12);
		check (a, b, (int)(rng_u32 () % 16) - 2);
	}
	return finish (argv[1]);
}
