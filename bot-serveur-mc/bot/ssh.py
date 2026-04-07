"""
Helper SSH pour la connexion aux instances EC2 Minecraft.
Supporte les formats de clé RSA PEM et OpenSSH (ainsi que ECDSA, Ed25519, DSS).
"""

import logging
import os
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

_KEY_TYPES: list[type[paramiko.PKey]] = [
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
    raise RuntimeError("Hôte SSH introuvable : définissez MC_SERVER_HOST ou MC_SERVER_INSTANCE_ID.")


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
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp,
        ):
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
