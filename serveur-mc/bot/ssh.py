"""
Helper SSH pour la connexion aux instances EC2 Minecraft.
Supporte les formats de clé RSA PEM et OpenSSH (ainsi que ECDSA, Ed25519, DSS).
"""
import logging
import os
import secrets
import string

import paramiko

logger = logging.getLogger(__name__)

MC_SERVER_HOST = os.getenv("MC_SERVER_HOST", "")
MC_SERVER_USER = os.getenv("MC_SERVER_USER", "ec2-user")
MC_SERVER_KEY_PATH = os.getenv("MC_SERVER_KEY_PATH", "")
MC_SERVER_JAR_URL = os.getenv(
    "MC_SERVER_JAR_URL",
    "https://piston-data.mojang.com/v1/objects/"
    "59353fb40c36d304f2035d51e7d6e6baa98dc05c/server.jar",
)

_KEY_TYPES = [
    paramiko.RSAKey,
    paramiko.Ed25519Key,
    paramiko.ECDSAKey,
    paramiko.DSSKey,
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
        output = stdout.read().decode() + stderr.read().decode()
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
    _host = host or MC_SERVER_HOST
    _user = user or MC_SERVER_USER
    _key_path = key_path or MC_SERVER_KEY_PATH
    _jar_url = jar_url or MC_SERVER_JAR_URL

    if not _host or not _key_path:
        return (False, "Variables MC_SERVER_HOST et MC_SERVER_KEY_PATH requises.")

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
            f"✅ Serveur `{server_key}` configuré\n"
            f"📁 Dossier : `/home/ec2-user/minecraft-servers/{server_key}`\n"
            f"🔌 Port : `{port}`",
        )
    return (False, f"❌ Erreur lors de la configuration:\n{output}")
