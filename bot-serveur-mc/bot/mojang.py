"""
Résolution des versions Minecraft et téléchargement de server.jar via l'API Mojang.
"""
import re

import aiohttp

MOJANG_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
MAX_MC_VERSION = (1, 21, 4)  # version maximale compatible Java 21


def _parse_mc_version(version_id: str) -> tuple[int, ...] | None:
    """Parse '1.21.4' → (1, 21, 4). Retourne None si le format n'est pas reconnu."""
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?$", version_id)
    if not m:
        return None
    return tuple(int(x) for x in m.groups() if x is not None)


async def get_jar_url_for_version(version_id: str) -> str:
    """Résout un ID de version Minecraft (ex: '1.21.4', 'latest') en URL de server.jar.

    Raises ValueError si la version dépasse MAX_MC_VERSION.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(MOJANG_MANIFEST_URL) as resp:
            manifest = await resp.json()

        if version_id == "latest":
            version_id = manifest["latest"]["release"]

        parsed = _parse_mc_version(version_id)
        if parsed is not None and parsed > MAX_MC_VERSION:
            max_str = ".".join(str(x) for x in MAX_MC_VERSION)
            raise ValueError(
                f"La version {version_id} requiert Java > 21. "
                f"Version maximale supportée : {max_str}."
            )

        version_entry = next((v for v in manifest["versions"] if v["id"] == version_id), None)
        if version_entry is None:
            raise ValueError(f"Version Minecraft inconnue : {version_id}")

        async with session.get(version_entry["url"]) as resp:
            version_manifest = await resp.json()

    return version_manifest["downloads"]["server"]["url"]
