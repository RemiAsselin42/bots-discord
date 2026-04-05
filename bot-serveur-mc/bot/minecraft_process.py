"""
Gestion du cycle de vie du processus Minecraft sur l'instance EC2 :
démarrage, arrêt, vérification RCON, setup de l'instance hôte et du serveur.
"""
import logging
import os
import re

import paramiko

from bot.papermc import FLOODGATE_SPIGOT_URL, GEYSER_SPIGOT_URL
from bot.ssh import _resolve_host, generate_rcon_password, load_ssh_key, ssh_execute

logger = logging.getLogger(__name__)

MC_SERVER_USER = os.getenv("MC_SERVER_USER", "ec2-user")
MC_SERVER_KEY_PATH = os.getenv("MC_SERVER_KEY_PATH", "")
MC_MCRCON_PATH = os.getenv("MC_MCRCON_PATH", "/usr/local/bin/mcrcon")
MC_SERVER_JAR_URL = os.getenv(
    "MC_SERVER_JAR_URL",
    "https://piston-data.mojang.com/v1/objects/"
    "59353fb40c36d304f2035d51e7d6e6baa98dc05c/server.jar",
)


def start_minecraft_process(
    server_key: str,
    *,
    max_ram: str = "1536M",
    min_ram: str = "1024M",
    host: str | None = None,
    user: str | None = None,
    key_path: str | None = None,
) -> tuple[bool, str]:
    """Lance le processus Java Minecraft pour un serveur donné via SSH.

    Idempotent : si le processus tourne déjà, retourne succès sans le relancer.
    Returns:
        (success, message)
    """
    _user = user or MC_SERVER_USER
    _key_path = key_path or MC_SERVER_KEY_PATH

    if not _key_path:
        return (False, "Variable MC_SERVER_KEY_PATH requise.")
    try:
        _host = _resolve_host(host)
    except Exception as e:
        return (False, f"Impossible de résoudre l'hôte SSH : {e}")

    command = f"""
set -e
SERVER_DIR="/home/{_user}/minecraft-servers/{server_key}"
JAR_PATH="$SERVER_DIR/server.jar"
cd "$SERVER_DIR"
MC_PROC_PATTERN="[j]ava .*$JAR_PATH"
if pgrep -f "$MC_PROC_PATTERN" > /dev/null 2>&1; then
    echo "Already running"
    exit 0
fi
if ! command -v java > /dev/null 2>&1; then
    echo "Java introuvable sur l'instance."
    exit 1
fi

# Bootstrap EULA : si absent/non valide, on fait un premier lancement
# pour laisser Minecraft générer ses fichiers, puis on active eula=true.
if [ ! -f eula.txt ] || ! grep -q '^eula=true$' eula.txt; then
    setsid nohup java -Xmx{max_ram} -Xms{min_ram} -jar "$JAR_PATH" nogui < /dev/null > bootstrap.log 2>&1 &
    BOOT_PID=$!

    # Attendre que le processus se termine naturellement (extraction des libs, génération eula.txt)
    # Minecraft 1.21+ peut prendre 2-3 minutes pour décompresser ses bibliothèques.
    BOOT_WAITED=0
    BOOT_MAX=180
    while kill -0 "$BOOT_PID" 2>/dev/null && [ $BOOT_WAITED -lt $BOOT_MAX ]; do
        sleep 5
        BOOT_WAITED=$((BOOT_WAITED + 5))
    done

    # Si toujours en cours après le délai max, forcer l'arrêt
    if kill -0 "$BOOT_PID" 2>/dev/null; then
        kill -TERM "$BOOT_PID" || true
        sleep 2
        if kill -0 "$BOOT_PID" 2>/dev/null; then
            kill -KILL "$BOOT_PID" || true
        fi
    fi

    if [ -f eula.txt ]; then
        if grep -q '^eula=' eula.txt; then
            sed -i 's/^eula=.*/eula=true/' eula.txt
        else
            echo 'eula=true' >> eula.txt
        fi
    else
        echo 'eula=true' > eula.txt
    fi
fi

setsid nohup java -Xmx{max_ram} -Xms{min_ram} -jar "$JAR_PATH" nogui < /dev/null > stdout.log 2>&1 &
# Attendre jusqu'à 90s que Java soit détecté par pgrep.
# On se base uniquement sur pgrep (pas sur $! qui pointe le wrapper setsid/nohup, pas Java).
# La génération du monde peut prendre 30-60s sur une petite instance.
LAUNCH_WAITED=0
while [ $LAUNCH_WAITED -lt 90 ]; do
    sleep 5
    LAUNCH_WAITED=$((LAUNCH_WAITED + 5))
    if pgrep -f "$MC_PROC_PATTERN" > /dev/null 2>&1; then
        echo "Serveur Minecraft démarré."
        exit 0
    fi
done
echo "Le processus Java s'est arrêté immédiatement après le lancement." >&2
tail -n 40 stdout.log 2>/dev/null || true
exit 1
"""
    return ssh_execute(_host, _user, _key_path, command, timeout=240)


def is_minecraft_process_running(
    server_key: str,
    *,
    host: str | None = None,
    user: str | None = None,
    key_path: str | None = None,
) -> tuple[bool, bool]:
    """Vérifie si le processus Java Minecraft tourne pour un serveur donné.

    Returns:
        (ssh_ok, is_running) — ssh_ok=False si SSH injoignable.
    """
    _user = user or MC_SERVER_USER
    _key_path = key_path or MC_SERVER_KEY_PATH

    if not _key_path:
        return (False, False)
    try:
        _host = _resolve_host(host)
    except Exception:
        return (False, False)

    command = f"pgrep -f '[j]ava .*/minecraft-servers/{server_key}/server.jar' > /dev/null 2>&1 && echo running || echo stopped"
    ok, output = ssh_execute(_host, _user, _key_path, command, timeout=10)
    if not ok:
        return (False, False)
    return (True, "running" in output)


def check_other_mc_servers_running(
    exclude_server_key: str,
    *,
    host: str | None = None,
    user: str | None = None,
    key_path: str | None = None,
) -> tuple[bool, list[str]]:
    """Vérifie si d'autres serveurs Minecraft tournent sur la même instance.

    exclude_server_key: le server_key à ignorer (celui qu'on vient d'arrêter)
    Returns:
        (success, list[str]) — liste des server_keys encore actifs (hors exclu)
    """
    _user = user or MC_SERVER_USER
    _key_path = key_path or MC_SERVER_KEY_PATH

    if not _key_path:
        return (False, [])
    try:
        _host = _resolve_host(host)
    except Exception as e:
        logger.warning("check_other_mc_servers_running : impossible de résoudre l'hôte : %s", e)
        return (False, [])

    command = f"""
pgrep -af '[j]ava .*/minecraft-servers/.*/server.jar' | grep -v "minecraft-servers/{exclude_server_key}/" || true
"""
    success, output = ssh_execute(_host, _user, _key_path, command, timeout=15)
    if not success:
        return (False, [])

    running = []
    for line in output.splitlines():
        match = re.search(r"minecraft-servers/([^/]+)/server\.jar", line)
        if match:
            key = match.group(1)
            if key != exclude_server_key and key not in running:
                running.append(key)
    return (True, running)


def check_rcon_ready(
    server_key: str,
    *,
    host: str | None = None,
    user: str | None = None,
    key_path: str | None = None,
) -> tuple[bool, str]:
    """Teste si RCON répond en envoyant 'list' via mcrcon.

    Returns:
        (True, output) si RCON répond, (False, erreur) sinon.
    """
    _user = user or MC_SERVER_USER
    _key_path = key_path or MC_SERVER_KEY_PATH

    if not _key_path:
        return (False, "Variable MC_SERVER_KEY_PATH requise.")
    try:
        _host = _resolve_host(host)
    except Exception as e:
        return (False, f"Impossible de résoudre l'hôte SSH : {e}")

    command = f"""
set -e
PROPS="/home/{_user}/minecraft-servers/{server_key}/server.properties"
SERVER_DIR="/home/{_user}/minecraft-servers/{server_key}"
MC_PROC_PATTERN="[j]ava .*/minecraft-servers/{server_key}/server.jar"
if [ ! -f "$PROPS" ]; then
    echo "Fichier server.properties introuvable : $PROPS"
    exit 1
fi

RCON_PORT=$(grep '^rcon.port=' "$PROPS" | cut -d= -f2)
RCON_PASS=$(grep '^rcon.password=' "$PROPS" | cut -d= -f2)

if [ -x "{MC_MCRCON_PATH}" ]; then
    "{MC_MCRCON_PATH}" -H 127.0.0.1 -P "$RCON_PORT" -p "$RCON_PASS" list
    exit $?
fi

if command -v mcrcon > /dev/null 2>&1; then
    mcrcon -H 127.0.0.1 -P "$RCON_PORT" -p "$RCON_PASS" list
    exit $?
fi

# Fallback : si mcrcon est absent, vérifier que le processus Java tourne ET que le port RCON répond.
if pgrep -f "$MC_PROC_PATTERN" > /dev/null 2>&1 && timeout 2 bash -c "cat < /dev/null > /dev/tcp/127.0.0.1/$RCON_PORT" 2>/dev/null; then
    echo "RCON port ouvert (mcrcon absent)"
    exit 0
fi

echo "RCON indisponible et mcrcon absent."
[ -f "$SERVER_DIR/logs/latest.log" ] && tail -n 30 "$SERVER_DIR/logs/latest.log" || true
[ -f "$SERVER_DIR/stdout.log" ] && tail -n 30 "$SERVER_DIR/stdout.log" || true
exit 1
"""
    return ssh_execute(_host, _user, _key_path, command, timeout=10)


def stop_minecraft_server(
    server_key: str,
    *,
    host: str | None = None,
    user: str | None = None,
    key_path: str | None = None,
) -> tuple[bool, str]:
    """
    Arrête le processus Minecraft d'un serveur via RCON, sans arrêter l'instance EC2.

    Lit les credentials RCON depuis server.properties du serveur cible.

    Returns:
        (success, message)
    """
    _user = user or MC_SERVER_USER
    _key_path = key_path or MC_SERVER_KEY_PATH

    if not _key_path:
        return (False, "Variable MC_SERVER_KEY_PATH requise.")
    try:
        _host = _resolve_host(host)
    except Exception as e:
        return (False, f"Impossible de résoudre l'hôte SSH : {e}")

    command = f"""
set -e
PROPS="/home/{_user}/minecraft-servers/{server_key}/server.properties"
    MC_PROC_PATTERN="[j]ava .*/minecraft-servers/{server_key}/server.jar"
if [ ! -f "$PROPS" ]; then
    echo "Fichier server.properties introuvable : $PROPS"
    exit 1
fi
RCON_PORT=$(grep '^rcon.port=' "$PROPS" | cut -d= -f2)
RCON_PASS=$(grep '^rcon.password=' "$PROPS" | cut -d= -f2)

    if ! pgrep -f "$MC_PROC_PATTERN" > /dev/null 2>&1; then
    echo "Serveur déjà arrêté (aucun PID trouvé)."
    exit 0
fi

if [ -x "{MC_MCRCON_PATH}" ]; then
    if "{MC_MCRCON_PATH}" -H 127.0.0.1 -P "$RCON_PORT" -p "$RCON_PASS" stop; then
        sleep 3
        if ! pgrep -f "$MC_PROC_PATTERN" > /dev/null 2>&1; then
            echo "Serveur arrêté via RCON ({MC_MCRCON_PATH})."
            exit 0
        fi
        echo "RCON stop envoyé mais process encore actif, fallback process stop." >&2
    fi
    echo "RCON stop failed via {MC_MCRCON_PATH}, fallback process stop." >&2
fi

if command -v mcrcon > /dev/null 2>&1; then
    if mcrcon -H 127.0.0.1 -P "$RCON_PORT" -p "$RCON_PASS" stop; then
        sleep 3
        if ! pgrep -f "$MC_PROC_PATTERN" > /dev/null 2>&1; then
            echo "Serveur arrêté via RCON (mcrcon)."
            exit 0
        fi
        echo "RCON stop envoyé mais process encore actif, fallback process stop." >&2
    fi
    echo "RCON stop failed via mcrcon, fallback process stop." >&2
fi

# Fallback process stop : on tue tous les PID correspondant au serveur.
PIDS_BEFORE=$(pgrep -f "$MC_PROC_PATTERN" | tr '\n' ' ' || true)
if [ -z "$PIDS_BEFORE" ]; then
    echo "Serveur déjà arrêté (aucun PID trouvé)."
    exit 0
fi

FIRST_PID=$(echo "$PIDS_BEFORE" | awk '{{print $1}}')
PID_USER=$(ps -o user= -p "$FIRST_PID" 2>/dev/null | tr -d ' ' || true)
echo "Fallback stop sur PID(s): $PIDS_BEFORE (owner principal: ${{PID_USER:-unknown}})"

# 1) TERM ciblé (évite de tuer le shell courant par motif)
for pid in $PIDS_BEFORE; do
    kill -TERM "$pid" || sudo -n kill -TERM "$pid" || true
done

# Attendre jusqu'à 15s l'arrêt propre
for _ in 1 2 3 4 5; do
    if ! pgrep -f "$MC_PROC_PATTERN" > /dev/null 2>&1; then
        echo "Serveur arrêté sans mcrcon (fallback process TERM)."
        exit 0
    fi
    sleep 3
done

# 2) KILL forcé sur PID restants uniquement
PIDS_AFTER_TERM=$(pgrep -f "$MC_PROC_PATTERN" | tr '\n' ' ' || true)
for pid in $PIDS_AFTER_TERM; do
    kill -KILL "$pid" || sudo -n kill -KILL "$pid" || true
done
sleep 1

if pgrep -f "$MC_PROC_PATTERN" > /dev/null 2>&1; then
    PIDS_AFTER=$(pgrep -af "$MC_PROC_PATTERN" || true)
    echo "Impossible d'arrêter le processus Minecraft même après fallback. Process restants:" >&2
    echo "$PIDS_AFTER" >&2
    exit 1
fi

echo "Serveur arrêté sans mcrcon (fallback process KILL)."
exit 0
"""
    return ssh_execute(_host, _user, _key_path, command)


def setup_host_instance(
    *,
    host: str | None = None,
    user: str | None = None,
    key_path: str | None = None,
) -> tuple[bool, str]:
    """
    Prépare l'instance EC2 Minecraft Host pour recevoir des serveurs :
    - Installe Java 21 si absent
    - Crée ~/minecraft-servers/
    - Uploade les scripts (duck.sh, stop_minecraft.sh, check_idle.sh, check_players.sh)
    - Configure les permissions et le crontab DuckDNS
    - Injecte DUCKDNS_DOMAIN et DUCKDNS_TOKEN dans ~/.bashrc

    Idempotent : sans danger si appelé plusieurs fois.

    Returns:
        (success, message)
    """
    _user = user or MC_SERVER_USER
    _key_path = key_path or MC_SERVER_KEY_PATH

    if not _key_path:
        return (False, "Variable MC_SERVER_KEY_PATH requise.")
    try:
        _host = _resolve_host(host)
    except Exception as e:
        return (False, f"Impossible de résoudre l'hôte SSH : {e}")

    # 1. Installer Java 21 et créer le répertoire de base
    install_cmd = f"""
set -e
if ! command -v java &> /dev/null; then
    sudo yum install -y java-21-amazon-corretto-headless
fi
sudo yum install -y python3-pillow 2>/dev/null || sudo pip3 install Pillow -q 2>/dev/null || true
mkdir -p /home/{_user}/minecraft-servers
"""
    success, output = ssh_execute(_host, _user, _key_path, install_cmd)
    if not success:
        return (False, f"Erreur installation Java/répertoire:\n{output}")

    # 2. Uploader les scripts via SFTP
    scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
    script_names = ["duck.sh", "stop_minecraft.sh", "check_idle.sh", "check_players.sh"]

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        key = load_ssh_key(_key_path)
        ssh.connect(hostname=_host, username=_user, pkey=key, timeout=30)
        sftp = ssh.open_sftp()
        for name in script_names:
            local_path = os.path.join(scripts_dir, name)
            sftp.put(local_path, f"/home/{_user}/{name}")
        sftp.close()
    except Exception as e:
        return (False, f"Erreur upload scripts:\n{e}")
    finally:
        ssh.close()

    # 3. Permissions + crontab + variables DuckDNS dans ~/.bashrc
    duckdns_domain = os.getenv("DUCKDNS_DOMAIN", "")
    duckdns_token = os.getenv("DUCKDNS_TOKEN", "")
    bashrc_cmds = ""
    if duckdns_domain and duckdns_token:
        bashrc_cmds = (
            f"grep -qF 'DUCKDNS_DOMAIN' ~/.bashrc || "
            f"echo 'export DUCKDNS_DOMAIN={duckdns_domain}' >> ~/.bashrc\n"
            f"grep -qF 'DUCKDNS_TOKEN' ~/.bashrc || "
            f"echo 'export DUCKDNS_TOKEN={duckdns_token}' >> ~/.bashrc\n"
            # duck.sh lit ~/.env (lu par cron) — on y écrit aussi
            f"touch ~/.env\n"
            f"grep -qF 'DUCKDNS_DOMAIN' ~/.env || "
            f"echo 'DUCKDNS_DOMAIN={duckdns_domain}' >> ~/.env\n"
            f"grep -qF 'DUCKDNS_TOKEN' ~/.env || "
            f"echo 'DUCKDNS_TOKEN={duckdns_token}' >> ~/.env"
        )

    post_cmd = f"""
set -e
chmod +x /home/{_user}/duck.sh /home/{_user}/stop_minecraft.sh /home/{_user}/check_idle.sh /home/{_user}/check_players.sh
crontab -l 2>/dev/null | grep -q duck.sh || (crontab -l 2>/dev/null; echo "*/5 * * * * /home/{_user}/duck.sh >> /home/{_user}/duck.log 2>&1") | crontab -
{bashrc_cmds}
"""
    success, output = ssh_execute(_host, _user, _key_path, post_cmd)
    if not success:
        return (False, f"Erreur configuration post-upload:\n{output}")

    return (True, "Setup de l'instance Minecraft Host terminé avec succès.")


def setup_minecraft_server(
    server_key: str,
    port: int,
    *,
    host: str | None = None,
    user: str | None = None,
    key_path: str | None = None,
    jar_url: str | None = None,
    motd: str | None = None,
    max_players: int = 20,
    gamemode: str = "survival",
    seed: str | None = None,
    icon_url: str | None = None,
    bedrock: bool = False,
    bedrock_port: int | None = None,
    viaversion_url: str | None = None,
) -> tuple[bool, str]:
    """
    Crée la structure d'un serveur Minecraft sur l'instance EC2 :
    - mkdir minecraft-servers/<server_key>
    - télécharge server.jar si absent
    - génère eula.txt et server.properties

    Utilise MC_SERVER_* depuis l'env si les arguments ne sont pas fournis.

    gamemode : "survival" | "creative" | "hardcore"
    Returns:
        (success, message)
    """
    _user = user or MC_SERVER_USER
    _key_path = key_path or MC_SERVER_KEY_PATH
    _jar_url = jar_url or MC_SERVER_JAR_URL

    if not _key_path:
        return (False, "Variable MC_SERVER_KEY_PATH requise.")
    try:
        _host = _resolve_host(host)
    except Exception as e:
        return (False, f"Impossible de résoudre l'hôte SSH : {e}")

    rcon_port = port + 10
    rcon_password = generate_rcon_password()

    _motd = motd or f"Serveur Minecraft - {server_key}"
    _gamemode_value, _hardcore_value = _resolve_gamemode(gamemode)
    _seed = seed or ""

    server_dir = f"/home/{_user}/minecraft-servers/{server_key}"
    if icon_url:
        icon_cmd = f"""
(
  wget -q "{icon_url}" -O {server_dir}/server-icon.png.tmp && python3 - <<'PYEOF'
from PIL import Image
img = Image.open("{server_dir}/server-icon.png.tmp").convert("RGBA")
w, h = img.size
side = min(w, h)
img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
img = img.resize((64, 64), Image.LANCZOS)
img.save("{server_dir}/server-icon.png", "PNG")
PYEOF
  rm -f {server_dir}/server-icon.png.tmp
) || true"""
    else:
        icon_cmd = ""
    command = f"""
set -euo pipefail
exec 2>&1
mkdir -p {server_dir}

PROPS_FILE="{server_dir}/server.properties"
RCON_PORT_DEFAULT="{rcon_port}"
RCON_PASS_DEFAULT="{rcon_password}"

if [ -f "$PROPS_FILE" ]; then
    EXISTING_RCON_PORT=$(grep '^rcon.port=' "$PROPS_FILE" | cut -d= -f2 || true)
    EXISTING_RCON_PASS=$(grep '^rcon.password=' "$PROPS_FILE" | cut -d= -f2 || true)
    if [ -n "$EXISTING_RCON_PORT" ]; then
        RCON_PORT_DEFAULT="$EXISTING_RCON_PORT"
    fi
    if [ -n "$EXISTING_RCON_PASS" ]; then
        RCON_PASS_DEFAULT="$EXISTING_RCON_PASS"
    fi
fi

if [ ! -f {server_dir}/server.jar ]; then
    wget -nv "{_jar_url}" -O {server_dir}/server.jar
fi

echo "eula=true" > {server_dir}/eula.txt

cat > "$PROPS_FILE" <<PROPS
server-port={port}
enable-rcon=true
rcon.port=${{RCON_PORT_DEFAULT}}
rcon.password=${{RCON_PASS_DEFAULT}}
enable-query=true
query.port={port}
max-players={max_players}
gamemode={_gamemode_value}
hardcore={_hardcore_value}
difficulty=normal
spawn-protection=16
view-distance=10
motd={_motd}
level-seed={_seed}
PROPS
{icon_cmd}
"""

    if bedrock and bedrock_port:
        command += f"""
# Geyser + Floodgate + ViaVersion (Bedrock support)
mkdir -p {server_dir}/plugins/Geyser-Spigot
wget -nv "{GEYSER_SPIGOT_URL}" -O {server_dir}/plugins/Geyser-Spigot.jar
wget -nv "{FLOODGATE_SPIGOT_URL}" -O {server_dir}/plugins/floodgate-spigot.jar
wget -nv "{viaversion_url}" -O {server_dir}/plugins/ViaVersion.jar

cat > {server_dir}/plugins/Geyser-Spigot/config.yml <<'GEYSER'
bedrock:
  address: 0.0.0.0
  port: {bedrock_port}
  clone-remote-port: false
  motd1: "{_motd}"
  motd2: ""
remote:
  address: auto
  port: auto
  auth-type: floodgate
GEYSER
"""

    # Les téléchargements de JARs (Paper + plugins Bedrock) peuvent prendre plusieurs minutes
    timeout = 300 if bedrock else 120
    success, output = ssh_execute(_host, _user, _key_path, command, timeout=timeout)

    if success:
        return (
            True,
            f"Serveur `{server_key}` configuré\n"
        )
    return (False, f":x: Erreur lors de la configuration:\n```\n{output}\n```")


def _resolve_gamemode(gamemode: str) -> tuple[str, str]:
    """Retourne (gamemode_value, hardcore_value) pour server.properties."""
    if gamemode == "hardcore":
        return "survival", "true"
    if gamemode == "creative":
        return "creative", "false"
    return "survival", "false"


def edit_minecraft_properties(
    server_key: str,
    *,
    motd: str | None = None,
    max_players: int | None = None,
    gamemode: str | None = None,
    ops_to_add: list[tuple[str, str]] | None = None,
    whitelist_to_add: list[tuple[str, str]] | None = None,
    icon_url: str | None = None,
    host: str | None = None,
    user: str | None = None,
    key_path: str | None = None,
) -> tuple[bool, str]:
    """Modifie les propriétés d'un serveur Minecraft existant via SSH.

    Utilise sed -i pour les propriétés dans server.properties,
    Python 3 inline pour ops.json / whitelist.json.

    gamemode : "survival" | "creative" | "hardcore"
    ops_to_add / whitelist_to_add : liste de (uuid, name)

    Returns:
        (success, message)
    """
    _user = user or MC_SERVER_USER
    _key_path = key_path or MC_SERVER_KEY_PATH

    if not _key_path:
        return (False, "Variable MC_SERVER_KEY_PATH requise.")
    try:
        _host = _resolve_host(host)
    except Exception as e:
        return (False, f"Impossible de résoudre l'hôte SSH : {e}")

    server_dir = f"/home/{_user}/minecraft-servers/{server_key}"
    props_file = f"{server_dir}/server.properties"

    parts: list[str] = [f"set -e", f'PROPS="{props_file}"', ""]

    changes: list[str] = []

    # --- server.properties via sed ---
    def _sed(key: str, value: str) -> str:
        escaped = value.replace("/", r"\/").replace("&", r"\&")
        return (
            f'if grep -q "^{key}=" "$PROPS"; then\n'
            f'    sed -i \'s/^{key}=.*/{key}={escaped}/\' "$PROPS"\n'
            f"else\n"
            f'    echo "{key}={value}" >> "$PROPS"\n'
            f"fi"
        )

    if motd is not None:
        parts.append(_sed("motd", motd))
        changes.append(f"• motd: `{motd}`")

    if max_players is not None:
        parts.append(_sed("max-players", str(max_players)))
        changes.append(f"• max-players: `{max_players}`")

    if gamemode is not None:
        gm_value, hc_value = _resolve_gamemode(gamemode)
        parts.append(_sed("gamemode", gm_value))
        parts.append(_sed("hardcore", hc_value))
        changes.append(f"• gamemode: `{gamemode}`")

    # --- ops.json via Python inline ---
    if ops_to_add:
        for uuid, name in ops_to_add:
            safe_uuid = uuid.replace("'", "")
            safe_name = name.replace("'", "")
            parts.append(
                f"python3 -c \"\n"
                f"import json, os\n"
                f"path = '{server_dir}/ops.json'\n"
                f"ops = json.load(open(path)) if os.path.exists(path) else []\n"
                f"if not any(o.get('uuid') == '{safe_uuid}' for o in ops):\n"
                f"    ops.append({{'uuid': '{safe_uuid}', 'name': '{safe_name}', 'level': 4, 'bypassesPlayerLimit': False}})\n"
                f"    json.dump(ops, open(path, 'w'), indent=2)\n"
                f"    print('op ajouté : {safe_name}')\n"
                f"else:\n"
                f"    print('{safe_name} est déjà op')\n"
                f"\""
            )
            changes.append(f"• op ajouté: `{name}`")

    # --- whitelist.json via Python inline ---
    if whitelist_to_add:
        for uuid, name in whitelist_to_add:
            safe_uuid = uuid.replace("'", "")
            safe_name = name.replace("'", "")
            parts.append(
                f"python3 -c \"\n"
                f"import json, os\n"
                f"path = '{server_dir}/whitelist.json'\n"
                f"wl = json.load(open(path)) if os.path.exists(path) else []\n"
                f"if not any(e.get('uuid') == '{safe_uuid}' for e in wl):\n"
                f"    wl.append({{'uuid': '{safe_uuid}', 'name': '{safe_name}'}})\n"
                f"    json.dump(wl, open(path, 'w'), indent=2)\n"
                f"    print('whitelist ajouté : {safe_name}')\n"
                f"else:\n"
                f"    print('{safe_name} est déjà dans la whitelist')\n"
                f"\""
            )
            changes.append(f"• whitelist: `{name}`")

    # --- server-icon.png ---
    if icon_url:
        parts.append(f"""(
  wget -q "{icon_url}" -O {server_dir}/server-icon.png.tmp && python3 - <<'PYEOF'
from PIL import Image
img = Image.open("{server_dir}/server-icon.png.tmp").convert("RGBA")
w, h = img.size
side = min(w, h)
img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
img = img.resize((64, 64), Image.LANCZOS)
img.save("{server_dir}/server-icon.png", "PNG")
PYEOF
  rm -f {server_dir}/server-icon.png.tmp
) || true""")
        changes.append(f"• icône mise à jour")

    if not changes:
        return (False, "Aucun paramètre fourni.")

    command = "\n".join(parts)
    success, output = ssh_execute(_host, _user, _key_path, command)

    if success:
        summary = "\n".join(changes)
        return (True, summary)
    return (False, f":x: Erreur SSH:\n{output}")
