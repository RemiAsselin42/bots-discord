"""
Résolution du JAR Fabric server et des URLs de mods via l'API Modrinth.
"""

import aiohttp

FABRIC_META_BASE = "https://meta.fabricmc.net/v2/versions"
MODRINTH_API_BASE = "https://api.modrinth.com/v2"

OPTIMIZATION_MODS: list[str] = [
    "fabric-api",
    "ferrite-core",
    "lithium",
    "modernfix",
    "memoryleakfix",
    "krypton",
    "chunky",
    "noisium",
]


async def get_fabric_jar_url(mc_version: str) -> tuple[str, str]:
    """Retourne (URL du JAR Fabric server, version MC résolue).

    Télécharge le JAR combiné Fabric loader + installer pour la version MC donnée.
    Raises ValueError si la version MC n'est pas disponible sur Fabric.
    """
    async with aiohttp.ClientSession() as session:
        # 0. Valider que la version MC est connue de Fabric
        async with session.get(f"{FABRIC_META_BASE}/game") as resp:
            resp.raise_for_status()
            game_versions = await resp.json()
        known_versions = {v["version"] for v in game_versions}
        if mc_version not in known_versions:
            raise ValueError(
                f"Version Minecraft '{mc_version}' non disponible sur Fabric. "
                f"Versions supportées : consultez https://fabricmc.net/develop/"
            )

        # 1. Récupérer la version stable la plus récente du loader
        async with session.get(f"{FABRIC_META_BASE}/loader") as resp:
            resp.raise_for_status()
            loaders = await resp.json()
        loader_version = next(
            (l["version"] for l in loaders if l.get("stable")), loaders[0]["version"]
        )

        # 2. Récupérer la version stable la plus récente de l'installer
        async with session.get(f"{FABRIC_META_BASE}/installer") as resp:
            resp.raise_for_status()
            installers = await resp.json()
        installer_version = next(
            (i["version"] for i in installers if i.get("stable")), installers[0]["version"]
        )

    url = f"{FABRIC_META_BASE}/loader/{mc_version}/{loader_version}/{installer_version}/server/jar"
    return url, mc_version


async def get_modrinth_mod_url(mod_slug: str, mc_version: str) -> str:
    """Retourne l'URL de téléchargement du fichier primary pour un mod Fabric/Modrinth.

    Raises ValueError si le mod n'est pas disponible pour la version MC donnée.
    """
    async with aiohttp.ClientSession() as session:
        params = {
            "game_versions": f'["{mc_version}"]',
            "loaders": '["fabric"]',
        }
        async with session.get(
            f"{MODRINTH_API_BASE}/project/{mod_slug}/version", params=params
        ) as resp:
            resp.raise_for_status()
            versions = await resp.json()

    if not versions:
        raise ValueError(f"Mod '{mod_slug}' non disponible pour MC {mc_version} (Fabric)")

    files = versions[0]["files"]
    # Préférer le fichier marqué primary, sinon prendre le premier
    primary = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not primary:
        raise ValueError(f"Aucun fichier trouvé pour le mod '{mod_slug}' (MC {mc_version})")

    return primary["url"]
