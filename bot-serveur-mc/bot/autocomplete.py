import logging
import re
import time

import aiohttp
import discord
from discord import app_commands

from bot.config import get_guild_servers, load_config
from bot.mojang import MAX_MC_VERSION, MOJANG_MANIFEST_URL, _parse_mc_version

logger = logging.getLogger(__name__)

# Cache global des versions Minecraft :
#   - _mc_versions_cache : liste brute retournée par l'API Mojang (clés "id", "type", "url"…)
#   - _mc_versions_cache_time : horodatage (time.monotonic) du dernier rafraîchissement
#   - _CACHE_TTL : durée de vie du cache en secondes (1 heure) ; passé ce délai,
#     le prochain appel à version_autocomplete re-interroge l'API Mojang.
_mc_versions_cache: list[dict] | None = None
_mc_versions_cache_time: float = 0.0
_CACHE_TTL = 3600  # 1 heure


async def version_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Propose les versions de Minecraft disponibles via l'API Mojang."""
    global _mc_versions_cache, _mc_versions_cache_time

    if _mc_versions_cache is None or (time.monotonic() - _mc_versions_cache_time) > _CACHE_TTL:
        try:
            async with aiohttp.ClientSession() as session, session.get(MOJANG_MANIFEST_URL) as resp:
                data = await resp.json()
            _mc_versions_cache = data["versions"]
            _mc_versions_cache_time = time.monotonic()
        except Exception:
            logger.warning(
                "version_autocomplete : impossible de récupérer le manifeste Mojang", exc_info=True
            )
            return []

    # Afficher les snapshots uniquement si l'input contient des lettres (ex: "24w", "pre", "rc")
    show_snapshots = bool(re.search(r"[a-zA-Z]", current))

    choices: list[app_commands.Choice[str]] = []

    if not current:
        choices.append(app_commands.Choice(name="latest (dernière version stable)", value="latest"))

    for v in _mc_versions_cache:
        if v["type"] not in ("release", "snapshot"):
            continue
        if v["type"] == "snapshot" and not show_snapshots:
            continue
        if v["type"] == "release":
            parsed = _parse_mc_version(v["id"])
            if parsed is not None and parsed > MAX_MC_VERSION:
                continue
        if current and current.lower() not in v["id"].lower():
            continue
        choices.append(app_commands.Choice(name=v["id"], value=v["id"]))
        if len(choices) >= 25:
            break

    return choices


async def server_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Propose uniquement les serveurs de la guild courante."""
    if not interaction.guild:
        return []

    servers = get_guild_servers(interaction.guild.id, load_config())
    choices = [
        app_commands.Choice(name=data.get("name", key), value=key)
        for key, data in servers.items()
        if current.lower() in data.get("name", key).lower() or current.lower() in key.lower()
    ]
    return choices[:25]
