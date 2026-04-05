import json
import threading

config_lock = threading.Lock()


def load_config() -> dict:
    try:
        with config_lock, open("servers_config.json", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        default = {"guilds": {}}
        save_config(default)
        return default


def save_config(config_data: dict) -> None:
    with config_lock, open("servers_config.json", "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)


def get_guild_servers(guild_id: int, config: dict) -> dict:
    """Retourne les serveurs Minecraft d'une guild Discord."""
    guild_data: dict = config["guilds"].get(str(guild_id), {})
    return guild_data.get("servers", {})


def get_server_config(guild_id: int, server_key: str, config: dict) -> dict | None:
    """Retourne la config d'un serveur spécifique, ou None s'il est introuvable."""
    return get_guild_servers(guild_id, config).get(server_key)
