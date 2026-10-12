/* Returns a pointer into a private static buffer (or a literal), so the
 * returned string content is compared, not the pointer. */
#include "common.h"
char *COM_FileExtension (char *in);
char *RECON (char *in);
static void check (char *in)
{
	char co[64], cr[64];
	snprintf (co, sizeof co, "%s", COM_FileExtension (in));
	snprintf (cr, sizeof cr, "%s", RECON (in));
	CHECK (strcmp (co, cr), "in=\"%s\" orig=\"%s\" recon=\"%s\"", in, co, cr);
}
int main (int argc, char **argv)
{
	if (argc < 2) return 2;
	rng_state = SPLIT_SEED (argv);
	if (is_dev (argv)) {
		char *fx[] = {"", ".", "a", "a.", ".a", "pak0.pak", "maps/base1.bsp", "a.b.c", "x.1234567", "x.12345678", "x.123456789abc", "dir.d/file", "noext"};
		for (unsigned i = 0; i < sizeof fx / sizeof fx[0]; i++) check (fx[i]);
	}
	static const char al[] = "ab./_X9";
	char s[40];
	for (int i = 0; i < 100000; i++) {
		int len = rng_u32 () % 24;
		for (int k = 0; k < len; k++) s[k] = al[rng_u32 () % (sizeof al - 1)];
		s[len] = 0;
		check (s);
	}
	return finish (argv[1]);
}
