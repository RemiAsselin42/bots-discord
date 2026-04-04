"""
Helper SSH pour la connexion aux instances EC2 Minecraft.
Supporte les formats de clé RSA PEM et OpenSSH (ainsi que ECDSA, Ed25519, DSS).
"""
import logging
import os
import re
import secrets
import string
import threading

import aiohttp
import boto3
import paramiko

logger = logging.getLogger(__name__)

MC_SERVER_HOST = os.getenv("MC_SERVER_HOST", "")
MC_SERVER_INSTANCE_ID = os.getenv("MC_SERVER_INSTANCE_ID", "")
MC_SERVER_REGION = os.getenv("MC_SERVER_REGION", "eu-north-1")
MC_SERVER_USER = os.getenv("MC_SERVER_USER", "ec2-user")
MC_SERVER_KEY_PATH = os.getenv("MC_SERVER_KEY_PATH", "")
MC_MCRCON_PATH = os.getenv("MC_MCRCON_PATH", "/usr/local/bin/mcrcon")
MC_SERVER_JAR_URL = os.getenv(
    "MC_SERVER_JAR_URL",
    "https://piston-data.mojang.com/v1/objects/"
    "59353fb40c36d304f2035d51e7d6e6baa98dc05c/server.jar",
)

_KEY_TYPES = [
    paramiko.RSAKey,
    paramiko.Ed25519Key,
    paramiko.ECDSAKey,
]


def load_ssh_key(key_path: str) -> paramiko.PKey:
    """
    Charge une clé privée SSH en testant successivement RSA PEM, OpenSSH,
    ECDSA et DSS. Lève SSHException si aucun format ne correspond.
    """
    last_exc: Exception | None = None
    for key_type in _KEY_TYPES:
        try:
            return key_type.from_private_key_file(key_path)
        except (paramiko.ssh_exception.SSHException, ValueError, Exception) as e:
            last_exc = e
            continue
    raise paramiko.ssh_exception.SSHException(
        f"Format de clé SSH non reconnu pour '{key_path}'. "
        f"Formats supportés : RSA PEM, OpenSSH, ECDSA, Ed25519, DSS. "
        f"Dernière erreur : {last_exc}"
    )


def get_instance_public_ip(instance_id: str, region: str = MC_SERVER_REGION) -> str:
    """Retourne l'IP publique courante d'une instance EC2 via boto3."""
    ec2 = boto3.client("ec2", region_name=region)
    resp = ec2.describe_instances(InstanceIds=[instance_id])
    ip = resp["Reservations"][0]["Instances"][0].get("PublicIpAddress")
    if not ip:
        raise RuntimeError(f"Aucune IP publique pour l'instance {instance_id} (arrêtée ?)")
    return ip


def _resolve_host(host_override: str | None) -> str:
    """
    Résout l'hôte SSH dans l'ordre de priorité :
    1. host_override (argument explicite)
    2. MC_SERVER_HOST (variable d'env statique)
    3. IP résolue dynamiquement depuis MC_SERVER_INSTANCE_ID via boto3

    Lève RuntimeError si aucune source n'est disponible.
    """
    if host_override:
        return host_override
    if MC_SERVER_HOST:
        return MC_SERVER_HOST
    if MC_SERVER_INSTANCE_ID:
        return get_instance_public_ip(MC_SERVER_INSTANCE_ID)
    raise RuntimeError(
        "Hôte SSH introuvable : définissez MC_SERVER_HOST ou MC_SERVER_INSTANCE_ID."
    )


def ssh_execute(
    host: str,
    user: str,
    key_path: str,
    command: str,
    timeout: int = 30,
) -> tuple[bool, str]:
    """
    Exécute une commande shell sur un hôte distant via SSH.

    Returns:
        (success, output) — success=True si exit_status == 0.
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        key = load_ssh_key(key_path)
        ssh.connect(hostname=host, username=user, pkey=key, timeout=timeout)
        _, stdout, stderr = ssh.exec_command(command)
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        t_out = threading.Thread(target=lambda: stdout_chunks.append(stdout.read()))
        t_err = threading.Thread(target=lambda: stderr_chunks.append(stderr.read()))
        t_out.start()
        t_err.start()
        t_out.join()
        t_err.join()
        output = (stdout_chunks[0] if stdout_chunks else b"").decode() + (
            stderr_chunks[0] if stderr_chunks else b""
        ).decode()
        exit_status = stdout.channel.recv_exit_status()
        return (exit_status == 0, output)
    except Exception as e:
        return (False, f"Erreur SSH: {e}")
    finally:
        ssh.close()


def generate_rcon_password(length: int = 24) -> str:
    """Génère un mot de passe RCON aléatoire et sûr (lettres + chiffres)."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


MOJANG_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"


async def get_jar_url_for_version(version_id: str) -> str:
    """Résout un ID de version Minecraft (ex: '1.21.4', 'latest') en URL de server.jar."""
    async with aiohttp.ClientSession() as session:
        async with session.get(MOJANG_MANIFEST_URL) as resp:
            manifest = await resp.json()

        if version_id == "latest":
            version_id = manifest["latest"]["release"]

        version_entry = next((v for v in manifest["versions"] if v["id"] == version_id), None)
        if version_entry is None:
            raise ValueError(f"Version Minecraft inconnue : {version_id}")

        async with session.get(version_entry["url"]) as resp:
            version_manifest = await resp.json()

    return version_manifest["downloads"]["server"]["url"]


async def update_duckdns(domain: str, token: str, ip: str) -> bool:
    """Met à jour l'enregistrement DuckDNS avec la nouvelle IP publique EC2.

    domain: sous-domaine seul (ex: 'minecraft-serveur'), sans '.duckdns.org'
    token:  token DuckDNS
    ip:     IP publique à enregistrer
    Returns True si la mise à jour a réussi.
    """
    subdomain = domain.split(".")[0] if "." in domain else domain
    url = f"https://www.duckdns.org/update?domains={subdomain}&token={token}&ip={ip}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                body = await resp.text()
                success = body.strip().upper() == "OK"
                if success:
                    logger.info("DuckDNS mis à jour : %s → %s", subdomain, ip)
                else:
                    logger.warning("DuckDNS réponse inattendue : %r", body)
                return success
    except Exception as e:
        logger.error("Erreur mise à jour DuckDNS : %s", e)
        return False


def start_minecraft_process(
    server_key: str,
    *,
    max_ram: str = "1.5G",
    min_ram: str = "1G",
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
cd /home/{_user}/minecraft-servers/{server_key}
if pgrep -f "minecraft-servers/{server_key}/server.jar" > /dev/null 2>&1; then
    echo "Already running"
    exit 0
fi
setsid nohup java -Xmx{max_ram} -Xms{min_ram} -jar server.jar nogui < /dev/null > stdout.log 2>&1 &
sleep 2
echo "Started PID $!"
"""
    return ssh_execute(_host, _user, _key_path, command, timeout=30)


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
pgrep -af "minecraft-servers/.*/server.jar" | grep -v "minecraft-servers/{exclude_server_key}/" || true
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
PROPS="/home/{_user}/minecraft-servers/{server_key}/server.properties"
RCON_PORT=$(grep '^rcon.port=' "$PROPS" | cut -d= -f2)
RCON_PASS=$(grep '^rcon.password=' "$PROPS" | cut -d= -f2)
{MC_MCRCON_PATH} -H 127.0.0.1 -P "$RCON_PORT" -p "$RCON_PASS" list
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
if [ ! -f "$PROPS" ]; then
    echo "Fichier server.properties introuvable : $PROPS"
    exit 1
fi
RCON_PORT=$(grep '^rcon.port=' "$PROPS" | cut -d= -f2)
RCON_PASS=$(grep '^rcon.password=' "$PROPS" | cut -d= -f2)
{MC_MCRCON_PATH} -H 127.0.0.1 -P "$RCON_PORT" -p "$RCON_PASS" stop
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
if ! java -version 2>&1 | grep -q '21'; then
    sudo dnf install -y java-21-amazon-corretto-headless
fi
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
) -> tuple[bool, str]:
    """
    Crée la structure d'un serveur Minecraft sur l'instance EC2 :
    - mkdir minecraft-servers/<server_key>
    - télécharge server.jar si absent
    - génère eula.txt et server.properties

    Utilise MC_SERVER_* depuis l'env si les arguments ne sont pas fournis.

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

    command = f"""
set -e
mkdir -p /home/ec2-user/minecraft-servers/{server_key}
cd /home/ec2-user/minecraft-servers/{server_key}

if [ ! -f server.jar ]; then
    wget -q "{_jar_url}" -O server.jar
fi

echo "eula=true" > eula.txt

cat > server.properties <<'PROPS'
server-port={port}
enable-rcon=true
rcon.port={rcon_port}
rcon.password={rcon_password}
enable-query=true
query.port={port}
max-players=20
gamemode=survival
difficulty=normal
spawn-protection=16
view-distance=10
motd=Serveur Minecraft - {server_key}
PROPS
"""

    success, output = ssh_execute(_host, _user, _key_path, command)

    if success:
        return (
            True,
            f"Serveur `{server_key}` configuré\n"
        )
    return (False, f":x: Erreur lors de la configuration:\n{output}")
