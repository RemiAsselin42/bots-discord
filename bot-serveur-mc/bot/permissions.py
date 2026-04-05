from typing import Final

import discord

# Permissions par défaut si aucune config n'est définie pour la guild
DEFAULT_PERMISSIONS: Final[dict[str, dict]] = {
    "start": {"admin_only": False, "allowed_roles": []},
    "stop":  {"admin_only": True,  "allowed_roles": []},
}

# Commandes dont les permissions sont configurables par les admins
CONFIGURABLE_COMMANDS: Final[list[str]] = ["start", "stop"]


def check_permission(interaction: discord.Interaction, command: str, config: dict) -> bool:
    """
    Retourne True si l'utilisateur est autorisé à utiliser la commande.

    Règles (par ordre de priorité) :
    1. Les administrateurs Discord ont toujours accès.
    2. Si des rôles autorisés sont configurés, un membre ayant l'un d'eux a accès.
    3. Si admin_only est True et qu'aucune règle précédente ne s'applique → refus.
    4. Sinon → accès autorisé.
    """
    if not interaction.guild:
        return False

    # 1. Admins toujours autorisés
    if interaction.user.guild_permissions.administrator:
        return True

    guild_str = str(interaction.guild.id)
    stored = config.get("guilds", {}).get(guild_str, {}).get("permissions", {})
    cmd_perm = stored.get(command, DEFAULT_PERMISSIONS.get(command, {}))

    allowed_roles: list = cmd_perm.get("allowed_roles", [])

    # 2. Vérification des rôles autorisés
    if allowed_roles:
        user_role_ids = {str(role.id) for role in interaction.user.roles}
        if user_role_ids & {str(r) for r in allowed_roles}:
            return True

    # 3. Commande admin-only → refus, sinon accès libre
    return not cmd_perm.get("admin_only", False)


def get_permission_summary(guild_id: int, config: dict) -> dict[str, dict]:
    """Retourne les permissions effectives (config stockée + défauts)."""
    guild_str = str(guild_id)
    stored = config.get("guilds", {}).get(guild_str, {}).get("permissions", {})
    return {
        cmd: stored.get(cmd, DEFAULT_PERMISSIONS[cmd])
        for cmd in CONFIGURABLE_COMMANDS
    }
