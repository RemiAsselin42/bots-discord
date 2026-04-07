"""
Gestion des ports pour les serveurs Minecraft multi-instances.
Plage Java par défaut : 25565-25600.
Plage Bedrock par défaut : 19132-19200.
"""

PORT_RANGE_START = 25565
PORT_RANGE_END = 25600

BEDROCK_PORT_RANGE_START = 19132
BEDROCK_PORT_RANGE_END = 19200


def get_available_port(config: dict, guild_id: int, instance_id: str | None = None) -> int | None:
    """
    Retourne le premier port disponible dans la plage 25565-25600.

    Si instance_id est fourni, scanne toutes les guilds pour éviter les conflits
    sur la même instance EC2. Sinon, scanne uniquement la guild courante.
    Retourne None si tous les ports sont utilisés.
    """
    used: set[int] = set()

    if instance_id is not None:
        for guild_data in config.get("guilds", {}).values():
            for server_data in guild_data.get("servers", {}).values():
                if server_data.get("instance_id") == instance_id:
                    port = server_data.get("port")
                    if isinstance(port, int):
                        used.add(port)
    else:
        guild_str = str(guild_id)
        for server_data in config.get("guilds", {}).get(guild_str, {}).get("servers", {}).values():
            port = server_data.get("port")
            if isinstance(port, int):
                used.add(port)

    for port in range(PORT_RANGE_START, PORT_RANGE_END + 1):
        if port not in used:
            return port

    return None


def assign_port(config: dict, guild_id: int, instance_id: str | None = None) -> int:
    """
    Retourne le premier port disponible.
    Lève ValueError si aucun port n'est disponible dans la plage.
    """
    port = get_available_port(config, guild_id, instance_id=instance_id)
    if port is None:
        raise ValueError(
            f"Aucun port disponible dans la plage {PORT_RANGE_START}-{PORT_RANGE_END}. "
            "Supprimez un serveur existant pour libérer un port."
        )
    return port


def get_available_bedrock_port(
    config: dict, guild_id: int, instance_id: str | None = None
) -> int | None:
    """
    Retourne le premier port Bedrock (UDP) disponible dans la plage 19132-19200.

    Si instance_id est fourni, scanne toutes les guilds pour éviter les conflits
    sur la même instance EC2. Sinon, scanne uniquement la guild courante.
    Retourne None si tous les ports sont utilisés.
    """
    used: set[int] = set()

    if instance_id is not None:
        for guild_data in config.get("guilds", {}).values():
            for server_data in guild_data.get("servers", {}).values():
                if server_data.get("instance_id") == instance_id:
                    bedrock_port = server_data.get("bedrock_port")
                    if isinstance(bedrock_port, int):
                        used.add(bedrock_port)
    else:
        guild_str = str(guild_id)
        for server_data in config.get("guilds", {}).get(guild_str, {}).get("servers", {}).values():
            bedrock_port = server_data.get("bedrock_port")
            if isinstance(bedrock_port, int):
                used.add(bedrock_port)

    for port in range(BEDROCK_PORT_RANGE_START, BEDROCK_PORT_RANGE_END + 1):
        if port not in used:
            return port

    return None


def assign_bedrock_port(config: dict, guild_id: int, instance_id: str | None = None) -> int:
    """
    Retourne le premier port Bedrock disponible.
    Lève ValueError si aucun port n'est disponible dans la plage.
    """
    port = get_available_bedrock_port(config, guild_id, instance_id=instance_id)
    if port is None:
        raise ValueError(
            f"Aucun port Bedrock disponible dans la plage {BEDROCK_PORT_RANGE_START}-{BEDROCK_PORT_RANGE_END}. "
            "Supprimez un serveur existant pour libérer un port."
        )
    return port
