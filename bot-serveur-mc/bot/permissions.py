from typing import Final

import discord

# Permissions par défaut si aucune config n'est définie pour la guild
DEFAULT_PERMISSIONS: Final[dict[str, dict]] = {
    "start": {"admin_only": False, "allowed_roles": []},
    "stop": {"admin_only": True, "allowed_roles": []},
}

# Commandes dont les permissions sont configurables par les admins
CONFIGURABLE_COMMANDS: Final[list[str]] = ["start", "stop"]

# Visibilité de toutes les commandes du bot (pour /listpermissions).
# MAINTENANCE : mettre à jour cette map à chaque ajout ou suppression de commande
# dans bot/commands/. Les entrées "configurable" doivent correspondre exactement
# à CONFIGURABLE_COMMANDS ci-dessus.
ALL_COMMANDS_VISIBILITY: Final[dict[str, str]] = {
    # Configurables (permission stockée en config)
    "start": "configurable",
    "stop": "configurable",
    # Admin uniquement
    "restart": "admin",
    "logs": "admin",
    "createserver": "admin",
    "removeserver": "admin",
    "editserver": "admin",
    "setpermission": "admin",
    "resetpermission": "admin",
    "listpermissions": "admin",
    "setdefault": "admin",
    "showdefaults": "admin",
    "properties": "admin",
    "setchannel": "admin",
    # Publiques
    "list": "public",
    "ip": "public",
    "uptime": "public",
    "status": "public",
    "players": "public",
}

# Assertion de cohérence : les commandes "configurable" dans ALL_COMMANDS_VISIBILITY
# doivent correspondre exactement à CONFIGURABLE_COMMANDS.
assert set(CONFIGURABLE_COMMANDS) == {
    cmd for cmd, vis in ALL_COMMANDS_VISIBILITY.items() if vis == "configurable"
}, (
    "Incohérence entre CONFIGURABLE_COMMANDS et ALL_COMMANDS_VISIBILITY. "
    "Mettez à jour les deux structures en même temps."
)


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

    assert isinstance(interaction.user, discord.Member)

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
    return {cmd: stored.get(cmd, DEFAULT_PERMISSIONS[cmd]) for cmd in CONFIGURABLE_COMMANDS}


def get_full_permission_summary(guild_id: int, config: dict) -> dict[str, dict]:
    """Retourne le statut de permission de toutes les commandes du bot."""
    guild_str = str(guild_id)
    stored = config.get("guilds", {}).get(guild_str, {}).get("permissions", {})
    result = {}
    for cmd, visibility in ALL_COMMANDS_VISIBILITY.items():
        if visibility == "configurable":
            effective = stored.get(
                cmd, DEFAULT_PERMISSIONS.get(cmd, {"admin_only": False, "allowed_roles": []})
            )
            result[cmd] = {"visibility": visibility, **effective}
        else:
            result[cmd] = {"visibility": visibility}
    return result
