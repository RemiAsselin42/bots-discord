"""
Gestion des ports pour les serveurs Minecraft multi-instances.
Plage par défaut : 25565-25600.
"""

PORT_RANGE_START = 25565
PORT_RANGE_END = 25600


def get_available_port(config: dict, guild_id: int) -> int | None:
    """
    Retourne le premier port disponible dans la plage 25565-25600 pour la guild.
    Retourne None si tous les ports sont utilisés.
    """
    guild_str = str(guild_id)
    used: set[int] = set()

    for server_data in config.get("guilds", {}).get(guild_str, {}).get("servers", {}).values():
        port = server_data.get("port")
        if isinstance(port, int):
            used.add(port)

    for port in range(PORT_RANGE_START, PORT_RANGE_END + 1):
        if port not in used:
            return port

    return None


def assign_port(config: dict, guild_id: int) -> int:
    """
    Retourne le premier port disponible.
    Lève ValueError si aucun port n'est disponible dans la plage.
    """
    port = get_available_port(config, guild_id)
    if port is None:
        raise ValueError(
            f"Aucun port disponible dans la plage {PORT_RANGE_START}-{PORT_RANGE_END}. "
            "Supprimez un serveur existant pour libérer un port."
        )
    return port
