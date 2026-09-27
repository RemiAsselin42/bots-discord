"""Mise à jour Bedrock (/update) : remplacement atomique des jars (bash requis)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from bot.minecraft_process import _UPDATE_BEDROCK_PLUGINS

BASH = shutil.which("bash")

# wget simulé : écrit l'URL dans le fichier cible ($4 = "-O <fichier>"), échoue pour Floodgate.
WGET_SHIM = 'wget() { case "$2" in *floodgate*) return 1;; esac; echo "$2" > "$4"; }\n'


@pytest.mark.skipif(BASH is None, reason="bash introuvable")
def test_failed_download_keeps_old_jar(tmp_path: Path):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    for jar in ("Geyser-Spigot.jar", "floodgate-spigot.jar", "ViaVersion.jar"):
        (plugins / jar).write_text("old")

    script = (
        WGET_SHIM + 'set -e\nVIAVERSION_URL="https://x/ViaVersion.jar"\n' + _UPDATE_BEDROCK_PLUGINS
    )
    result = subprocess.run(
        [BASH, "-c", script], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8"
    )

    assert result.returncode != 0
    assert "floodgate-spigot.jar" in result.stderr
    assert "geyser" in (plugins / "Geyser-Spigot.jar").read_text()
    assert (plugins / "floodgate-spigot.jar").read_text() == "old"
    assert (plugins / "ViaVersion.jar").read_text() == "old"  # set -e : arrêt au premier échec
    assert not list(plugins.glob("*.tmp"))
