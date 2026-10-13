/*
 * Contamination control set. Written fresh for this project on 2026-10-12;
 * not derived from any public code base. Each function mirrors the shape of
 * one Quake II pilot function (noted per function) so difficulty is roughly
 * matched, but the logic is new. All functions are free of undefined
 * behaviour for every input (float->int conversions are range-guarded).
 */
#include <math.h>
#include <string.h>

/* shape: vectoyaw. Compass sector 0..15 of the xy direction,
 * -1 for a zero vector, -2 for NaN components. */
int heading_to_sector (const float *dir)
{
	float deg;

	if (dir[0] != dir[0] || dir[1] != dir[1])
		return -2;
	if (dir[0] == 0 && dir[1] == 0)
		return -1;
	deg = (float)(atan2 (dir[1], dir[0]) * (180.0 / 3.14159265358979323846));
	if (deg < 0)
		deg += 360.0f;
	deg += 11.25f;			/* centre sector 0 on east */
	if (deg >= 360.0f)
		deg -= 360.0f;
	return (int)(deg / 22.5f) & 15;
}

/* shape: vectoangles. out[0] = elevation clamped to +-80 degrees,
 * out[1] = bearing in [0,360) snapped to half degrees, out[2] = planar length. */
void aim_angles (const float *dir, float *out)
{
	float planar = sqrtf (dir[0] * dir[0] + dir[1] * dir[1]);
	float elev = (float)(atan2 (dir[2], planar) * (180.0 / 3.14159265358979323846));
	float bearing;

	if (elev > 80.0f)
		elev = 80.0f;
	else if (elev < -80.0f)
		elev = -80.0f;

	if (planar == 0)
		bearing = 0;
	else {
		bearing = (float)(atan2 (dir[1], dir[0]) * (180.0 / 3.14159265358979323846));
		bearing = floorf (bearing * 2.0f + 0.5f) * 0.5f;
		if (bearing < 0)
			bearing += 360.0f;
	}
	out[0] = elev;
	out[1] = bearing;
	out[2] = planar;
}

/* shape: anglemod. Snap an angle to 1/256 of a turn, rounding to nearest;
 * out-of-range or NaN input returns 0. */
float wrap_snap (float a)
{
	int step;

	if (!(a > -1.0e6f && a < 1.0e6f))
		return 0;
	step = (int)floorf (a * (256.0f / 360.0f) + 0.5f);
	return (step & 255) * (360.0f / 256.0f);
}

/* shape: LerpAngle. Turn from cur toward target by at most rate degrees
 * along the shorter way round. */
float blend_turn (float cur, float target, float rate)
{
	float diff = fmodf (target - cur, 360.0f);

	if (diff > 180.0f)
		diff -= 360.0f;
	else if (diff <= -180.0f)
		diff += 360.0f;
	if (rate < 0)
		rate = -rate;
	if (diff > rate)
		diff = rate;
	else if (diff < -rate)
		diff = -rate;
	return cur + diff;
}

/* shape: Q_log2. Width of the span between lowest and highest set bit,
 * inclusive; 0 when no bit is set. */
int bit_span (unsigned v)
{
	int lo = 0, hi;

	if (!v)
		return 0;
	while (!(v & 1)) {
		v >>= 1;
		lo++;
	}
	hi = lo;
	while (v >>= 1)
		hi++;
	return hi - lo + 1;
}

/* shape: VectorNormalize. Scale v down in place so its length is at most
 * maxlen; maxlen <= 0 zeroes it. Returns the length before clamping. */
float clamp_length (float *v, float maxlen)
{
	float len = sqrtf (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
	float s;

	if (maxlen <= 0) {
		v[0] = v[1] = v[2] = 0;
		return len;
	}
	if (len > maxlen) {
		s = maxlen / len;
		v[0] *= s;
		v[1] *= s;
		v[2] *= s;
	}
	return len;
}

/* shape: CrossProduct / ClearBounds+AddPointToBounds. Bounds of n packed
 * xyz points; n <= 0 gives zero bounds. Returns how many points were
 * skipped for having a NaN component. */
int accumulate_bounds (const float *pts, int n, float *mins, float *maxs)
{
	int i, k, skipped = 0, seen = 0;

	for (k = 0; k < 3; k++)
		mins[k] = maxs[k] = 0;
	for (i = 0; i < n; i++) {
		const float *p = pts + 3 * i;
		if (p[0] != p[0] || p[1] != p[1] || p[2] != p[2]) {
			skipped++;
			continue;
		}
		for (k = 0; k < 3; k++) {
			if (!seen || p[k] < mins[k])
				mins[k] = p[k];
			if (!seen || p[k] > maxs[k])
				maxs[k] = p[k];
		}
		seen = 1;
	}
	return skipped;
}

/* shape: BoxOnPlaneSide. Where a box (centre + half extents) lies relative
 * to a probe: 1 = front, 2 = back, 3 = straddles; -1 for an unknown kind.
 * flags bit 0 swaps front and back. */
struct probe {
	float dir[3];
	float offset;
	unsigned char kind;		/* 0..2 axial, 3 general plane, 4 sphere */
	unsigned char flags;
};

int classify_box (const float *center, const float *half, const struct probe *p)
{
	float d, r;
	int side;

	switch (p->kind) {
	case 0: case 1: case 2:
		d = center[p->kind] - p->offset;
		r = half[p->kind];
		break;
	case 3:
		d = p->dir[0] * center[0] + p->dir[1] * center[1] + p->dir[2] * center[2] - p->offset;
		r = fabsf (p->dir[0]) * half[0] + fabsf (p->dir[1]) * half[1] + fabsf (p->dir[2]) * half[2];
		break;
	case 4:
		d = sqrtf ((center[0] - p->dir[0]) * (center[0] - p->dir[0])
		         + (center[1] - p->dir[1]) * (center[1] - p->dir[1])
		         + (center[2] - p->dir[2]) * (center[2] - p->dir[2])) - p->offset;
		r = half[0];
		break;
	default:
		return -1;
	}
	if (d > r)
		side = 1;
	else if (d < -r)
		side = 2;
	else
		side = 3;
	if ((p->flags & 1) && side != 3)
		side ^= 3;
	return side;
}

/* shape: Q_strncasecmp. Case-insensitive ASCII match where '?' matches any
 * one character and a trailing '*' matches any rest. 1 = match, 0 = not. */
int token_match (const char *pattern, const char *s)
{
	for (;; pattern++, s++) {
		int a = (unsigned char)*pattern, b = (unsigned char)*s;

		if (a == '*' && pattern[1] == 0)
			return 1;
		if (a >= 'A' && a <= 'Z')
			a += 'a' - 'A';
		if (b >= 'A' && b <= 'Z')
			b += 'a' - 'A';
		if (a == 0 || b == 0)
			return a == b;
		if (a != '?' && a != b)
			return 0;
	}
}

/* shape: COM_FileExtension. Text after the last ':' with leading spaces
 * skipped, at most 11 chars, in a static buffer; "" when there is no ':'. */
char *split_key (const char *in)
{
	static char value[12];
	const char *colon = strrchr (in, ':');
	int i;

	if (!colon)
		return "";
	colon++;
	while (*colon == ' ')
		colon++;
	for (i = 0; i < 11 && colon[i]; i++)
		value[i] = colon[i];
	value[i] = 0;
	return value;
}
