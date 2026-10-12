/*
 * Link-only stubs so unmodified game/q_shared.c and game/g_utils.c can be
 * linked into a standalone executable. None of the pilot target functions
 * call anything defined here; these exist only to satisfy the linker for
 * the non-target functions that share those translation units.
 */
#include "g_local.h"

game_locals_t	game;
level_locals_t	level;
game_import_t	gi;
game_export_t	globals;
edict_t		*g_edicts;
cvar_t		*maxclients;

void Com_Printf (char *msg, ...) { (void)msg; }

void T_Damage (edict_t *targ, edict_t *inflictor, edict_t *attacker, vec3_t dir,
	vec3_t point, vec3_t normal, int damage, int knockback, int dflags, int mod)
{
}
