"""
Résolution des versions Paper et URLs de téléchargement Geyser/Floodgate.
"""

import aiohttp

from bot.mojang import MAX_MC_VERSION, _parse_mc_version

PAPER_API_BASE = "https://api.papermc.io/v2/projects/paper"

GEYSER_SPIGOT_URL = (
    "https://download.geysermc.org/v2/projects/geyser/versions/latest/builds/latest/downloads/spigot"
)
FLOODGATE_SPIGOT_URL = (
    "https://download.geysermc.org/v2/projects/floodgate/versions/latest/builds/latest/downloads/spigot"
)


async def get_paper_jar_url(version_id: str) -> str:
    """Résout un ID de version Minecraft (ex: '1.21.4', 'latest') en URL de Paper JAR.

    Raises ValueError si la version n'est pas disponible pour Paper ou dépasse MAX_MC_VERSION.
    """
    async with aiohttp.ClientSession() as session:
        # 1. Récupérer la liste des versions Paper disponibles
        async with session.get(PAPER_API_BASE) as resp:
            project = await resp.json()

        versions: list[str] = project["versions"]

        if version_id == "latest":
            # L'API PaperMC retourne les versions triées par ordre croissant,
            # donc le dernier élément est toujours la version la plus récente.
            version_id = versions[-1]

        # Vérifier la contrainte Java 21
        parsed = _parse_mc_version(version_id)
        if parsed is not None and parsed > MAX_MC_VERSION:
            max_str = ".".join(str(x) for x in MAX_MC_VERSION)
            raise ValueError(
                f"La version {version_id} requiert Java > 21. "
                f"Version maximale supportée : {max_str}."
            )

        if version_id not in versions:
            raise ValueError(
                f"Version Minecraft {version_id} non disponible pour Paper. "
                f"Versions disponibles : {', '.join(versions[-5:])}"
            )

        # 2. Récupérer le dernier build pour cette version
        async with session.get(f"{PAPER_API_BASE}/versions/{version_id}") as resp:
            version_data = await resp.json()

        builds: list[int] = version_data["builds"]
        latest_build = builds[-1]

        # 3. Récupérer les métadonnées du build pour le nom du fichier
        async with session.get(
            f"{PAPER_API_BASE}/versions/{version_id}/builds/{latest_build}"
        ) as resp:
            build_data = await resp.json()

        filename = build_data["downloads"]["application"]["name"]

    return f"{PAPER_API_BASE}/versions/{version_id}/builds/{latest_build}/downloads/{filename}"
