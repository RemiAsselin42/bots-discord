import json
import re
import threading
from typing import Final

config_lock = threading.Lock()

GUILD_DEFAULT_PARAMS: Final[list[str]] = ["instance_id", "region", "hourly_cost", "max_ram"]

# Types de serveurs Minecraft supportés.
# Utiliser ces constantes plutôt que des chaînes littérales pour éviter les
# problèmes d'encodage et garantir la cohérence entre les modules.
SERVER_TYPE_VANILLA: Final[str] = "Vanilla"
SERVER_TYPE_BEDROCK: Final[str] = "Bedrock"
SERVER_TYPE_FABRIC: Final[str] = "Fabric"

# Liste ordonnée utilisée pour les choix Discord et les validations.
SERVER_TYPES: Final[list[str]] = [SERVER_TYPE_VANILLA, SERVER_TYPE_BEDROCK, SERVER_TYPE_FABRIC]

# Coût horaire EC2 par défaut (t3.small eu-north-1, ~0.0416 $/h).
# Mettre à jour si le type ou la région d'instance change.
DEFAULT_HOURLY_COST: Final[float] = 0.0416


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


def get_guild_defaults(guild_id: int, config: dict) -> dict:
    """Retourne les paramètres par défaut configurés pour la guild."""
    return config.get("guilds", {}).get(str(guild_id), {}).get("defaults", {})


def get_optimization_mods(config: dict) -> list[str]:
    """Retourne la liste des slugs Modrinth à installer sur un serveur Fabric.

    Si une clé "optimization_mods" est définie dans la config globale, elle
    prend le dessus sur la liste par défaut définie dans fabric.py. Cela permet
    de personnaliser les mods sans modifier le code source.

    Exemple dans servers_config.json :
        { "optimization_mods": ["ferrite-core", "lithium"] }
    """
    from bot.fabric import OPTIMIZATION_MODS as _DEFAULT_MODS  # import local pour éviter les cycles

    return config.get("optimization_mods", _DEFAULT_MODS)


def set_guild_default(guild_id: int, param: str, value: str, config: dict) -> None:
    """
    Stocke un paramètre par défaut dans config["guilds"][guild_id]["defaults"].
    Modifie config en place — appeler save_config() après.

    Raises:
        ValueError si le paramètre est inconnu ou si la valeur est invalide.
    """
    if param not in GUILD_DEFAULT_PARAMS:
        raise ValueError(f"Paramètre inconnu : {param}")

    guild_str = str(guild_id)
    guild_data = config["guilds"].setdefault(guild_str, {"servers": {}, "defaults": {}})
    defaults = guild_data.setdefault("defaults", {})

    if param == "instance_id":
        if not value.startswith("i-") or len(value) != 19:
            raise ValueError("Format instance_id invalide. Exemple : `i-0123456789abcdef0`")
        defaults[param] = value
    elif param == "region":
        if not re.match(r"^[a-z]{2}-[a-z]+-\d+$", value):
            raise ValueError("Format de région invalide. Exemple : `eu-north-1`, `us-east-1`")
        defaults[param] = value
    elif param == "hourly_cost":
        try:
            defaults[param] = float(value)
        except ValueError:
            raise ValueError(
                "Le coût horaire doit être un nombre décimal. Exemple : `0.0416`"
            ) from None
    elif param == "max_ram":
        if not re.match(r"^\d+[GM]$", value.upper()):
            raise ValueError("Format RAM invalide. Exemples : `2G`, `1536M` (entiers uniquement)")
        defaults[param] = value.upper()
