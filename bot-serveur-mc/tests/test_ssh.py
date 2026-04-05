"""
Tests pour bot/ssh.py — get_jar_url_for_version.

Stratégie :
- Les requêtes HTTP (aiohttp) sont mockées avec AsyncMock pour éviter
  tout appel réseau réel lors des tests.
- On vérifie le chemin nominal (release connue, alias "latest") ainsi que
  les cas d'erreur (version inconnue, erreur réseau).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.mojang import MOJANG_MANIFEST_URL, get_jar_url_for_version

# ── Fixtures de données ───────────────────────────────────────────────────────

MANIFEST = {
    "latest": {"release": "1.21.4", "snapshot": "24w09a"},
    "versions": [
        {
            "id": "1.21.4",
            "type": "release",
            "url": "https://piston-meta.mojang.com/v1/packages/abc/1.21.4.json",
        },
        {
            "id": "1.20.1",
            "type": "release",
            "url": "https://piston-meta.mojang.com/v1/packages/def/1.20.1.json",
        },
        {
            "id": "24w09a",
            "type": "snapshot",
            "url": "https://piston-meta.mojang.com/v1/packages/ghi/24w09a.json",
        },
    ],
}

VERSION_MANIFEST_1_21_4 = {
    "downloads": {
        "server": {
            "url": "https://piston-data.mojang.com/v1/objects/abc123/server.jar",
            "size": 51234567,
            "sha1": "abc123",
        }
    }
}

VERSION_MANIFEST_1_20_1 = {
    "downloads": {
        "server": {
            "url": "https://piston-data.mojang.com/v1/objects/def456/server.jar",
            "size": 48000000,
            "sha1": "def456",
        }
    }
}

VERSION_MANIFEST_SNAPSHOT = {
    "downloads": {
        "server": {
            "url": "https://piston-data.mojang.com/v1/objects/ghi789/server.jar",
        }
    }
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_resp(data: dict) -> MagicMock:
    """Crée un faux objet de réponse aiohttp (async context manager)."""
    resp = MagicMock()
    resp.json = AsyncMock(return_value=data)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_session(responses: list[dict]) -> MagicMock:
    """
    Crée un faux aiohttp.ClientSession dont les appels successifs à session.get()
    retournent les dicts fournis dans `responses` (dans l'ordre).

    aiohttp utilise session.get() comme async context manager directement :
        async with session.get(url) as resp: ...
    donc session.get() doit retourner un objet supportant __aenter__/__aexit__,
    pas une coroutine.
    """
    remaining = list(responses)

    def _get(url, **kwargs):
        return _make_resp(remaining.pop(0))

    session = MagicMock()
    session.get = _get
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# ── Tests nominaux ────────────────────────────────────────────────────────────

async def test_get_jar_url_for_known_version():
    """Résout correctement une version explicite (1.21.4)."""
    session = _make_session([MANIFEST, VERSION_MANIFEST_1_21_4])

    with patch("bot.ssh.aiohttp.ClientSession", return_value=session):
        url = await get_jar_url_for_version("1.21.4")

    assert url == "https://piston-data.mojang.com/v1/objects/abc123/server.jar"


async def test_get_jar_url_for_latest_resolves_to_release():
    """L'alias 'latest' se résout en la dernière release du manifeste."""
    session = _make_session([MANIFEST, VERSION_MANIFEST_1_21_4])

    with patch("bot.ssh.aiohttp.ClientSession", return_value=session):
        url = await get_jar_url_for_version("latest")

    assert url == "https://piston-data.mojang.com/v1/objects/abc123/server.jar"


async def test_get_jar_url_for_older_version():
    """Résout une version ancienne (1.20.1)."""
    session = _make_session([MANIFEST, VERSION_MANIFEST_1_20_1])

    with patch("bot.ssh.aiohttp.ClientSession", return_value=session):
        url = await get_jar_url_for_version("1.20.1")

    assert url == "https://piston-data.mojang.com/v1/objects/def456/server.jar"


async def test_get_jar_url_for_snapshot():
    """Résout une version snapshot."""
    session = _make_session([MANIFEST, VERSION_MANIFEST_SNAPSHOT])

    with patch("bot.ssh.aiohttp.ClientSession", return_value=session):
        url = await get_jar_url_for_version("24w09a")

    assert url == "https://piston-data.mojang.com/v1/objects/ghi789/server.jar"


# ── Tests d'erreur ────────────────────────────────────────────────────────────

async def test_get_jar_url_raises_for_unknown_version():
    """Lève ValueError si la version n'existe pas dans le manifeste.

    On utilise un ID textuel non reconnu par _parse_mc_version (retourne None),
    donc le garde Java ne se déclenche pas et l'on atteint bien la vérification
    «version inconnue».
    """
    session = _make_session([MANIFEST])

    with patch("bot.ssh.aiohttp.ClientSession", return_value=session):
        with pytest.raises(ValueError, match="inconnue"):
            await get_jar_url_for_version("version-inexistante")


async def test_get_jar_url_raises_on_network_error():
    """Propage l'exception réseau si aiohttp échoue."""
    # On utilise un resp dont __aenter__ lève une exception réseau
    bad_resp = MagicMock()
    bad_resp.__aenter__ = AsyncMock(side_effect=ConnectionError("réseau indisponible"))
    bad_resp.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=bad_resp)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    with patch("bot.ssh.aiohttp.ClientSession", return_value=session):
        with pytest.raises(ConnectionError):
            await get_jar_url_for_version("1.21.4")


# ── Test : une seule session pour les deux requêtes ───────────────────────────

async def test_single_session_used_for_both_requests():
    """Vérifie que get_jar_url_for_version réutilise la même session ClientSession."""
    call_count = 0

    def _get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        data = MANIFEST if call_count == 1 else VERSION_MANIFEST_1_21_4
        return _make_resp(data)

    session = MagicMock()
    session.get = _get
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    session_constructor = MagicMock(return_value=session)

    with patch("bot.ssh.aiohttp.ClientSession", session_constructor):
        await get_jar_url_for_version("1.21.4")

    # Le constructeur ClientSession ne doit avoir été appelé qu'une seule fois
    session_constructor.assert_called_once()
    assert call_count == 2  # deux requêtes HTTP via la même session
