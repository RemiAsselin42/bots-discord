"""Whitelist : durcissement au démarrage (bash requis) et affichage /list-properties."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bot.commands.logs import _FILE_SEP, _format_properties
from bot.minecraft_process import _WHITELIST_HARDENING, whitelist_notice

BASH = shutil.which("bash")
ALICE = "11111111-1111-1111-1111-111111111111"
BOB = "22222222-2222-2222-2222-222222222222"
CAROL = "33333333-3333-3333-3333-333333333333"


def _run(server_dir: Path) -> str:
    # python3 redirigé vers l'interpréteur des tests (absent ou stub sous Windows)
    shim = f'python3() {{ "{Path(sys.executable).as_posix()}" "$@"; }}\nset -e\n'
    result = subprocess.run(
        [BASH, "-c", shim + _WHITELIST_HARDENING],
        cwd=server_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.skipif(BASH is None, reason="bash introuvable")
def test_migration_keeps_data_and_is_idempotent(tmp_path: Path):
    (tmp_path / "server.properties").write_text(
        "motd=Mon serveur\nwhite-list=false\nlevel-name=monde\n"
    )
    (tmp_path / "whitelist.json").write_text(json.dumps([{"uuid": ALICE, "name": "Alice"}]))
    (tmp_path / "usercache.json").write_text(json.dumps([{"uuid": BOB, "name": "Bob"}]))
    playerdata = tmp_path / "monde" / "playerdata"
    playerdata.mkdir(parents=True)
    for uuid in (ALICE, BOB, CAROL):
        (playerdata / f"{uuid}.dat").write_bytes(b"")
    (playerdata / f"{BOB}.dat_old").write_bytes(b"")

    notice = whitelist_notice(_run(tmp_path))
    assert "Bob" in notice and CAROL in notice

    props = (tmp_path / "server.properties").read_text().splitlines()
    assert "motd=Mon serveur" in props
    assert "white-list=true" in props and "enforce-whitelist=true" in props
    whitelist = json.loads((tmp_path / "whitelist.json").read_text())
    assert whitelist == [
        {"uuid": ALICE, "name": "Alice"},
        {"uuid": BOB, "name": "Bob"},
        {"uuid": CAROL, "name": CAROL},
    ]

    # Serveur déjà migré : un joueur retiré par un admin n'est pas ré-ajouté
    (tmp_path / "whitelist.json").write_text(json.dumps(whitelist[:1]))
    assert whitelist_notice(_run(tmp_path)) == ""
    assert json.loads((tmp_path / "whitelist.json").read_text()) == whitelist[:1]


@pytest.mark.skipif(BASH is None, reason="bash introuvable")
def test_migration_accepts_empty_whitelist_file(tmp_path: Path):
    # Cas réel (dimicraft) : whitelist.json de 0 octet, enforce-whitelist déjà à true
    (tmp_path / "server.properties").write_text("white-list=false\nenforce-whitelist=true\n")
    (tmp_path / "whitelist.json").write_text("")
    (tmp_path / "world" / "playerdata").mkdir(parents=True)
    (tmp_path / "world" / "playerdata" / f"{ALICE}.dat").write_bytes(b"")

    assert "Whitelist activée" in whitelist_notice(_run(tmp_path))
    assert json.loads((tmp_path / "whitelist.json").read_text()) == [{"uuid": ALICE, "name": ALICE}]


def test_format_properties_masks_secrets_and_lists_players():
    raw = _FILE_SEP.join(
        [
            "#Minecraft server properties\nmotd=Salut\nrcon.password=hunter2\nwhite-list=true\n",
            json.dumps([{"uuid": BOB, "name": "bob"}, {"uuid": ALICE, "name": "Alice"}]),
            "",
        ]
    )
    out = _format_properties(raw)
    assert "hunter2" not in out and "rcon.password=********" in out
    assert "motd=Salut" in out and "#Minecraft" not in out
    assert "[whitelist.json] 2 joueur(s)\nAlice\nbob" in out
    assert out.endswith("[ops.json] absent")
