"""
Tâches asyncio de fond :
- notify_server_ready : poll EC2 après /start, notifie quand le serveur est prêt.
- auto_stop_loop      : surveille l'inactivité des serveurs et les arrête automatiquement.
"""
import asyncio
import datetime
import logging

import discord
from mcstatus import JavaServer

from bot.aws import get_ec2_client
from bot.config import load_config

logger = logging.getLogger(__name__)

# Tracker d'inactivité : {(guild_id_str, server_key) -> datetime de début d'inactivité | None}
_idle_since: dict[tuple[str, str], datetime.datetime | None] = {}

_NOTIFY_POLL_INTERVAL = 10   # secondes entre chaque check EC2 lors du démarrage
_NOTIFY_TIMEOUT = 300        # 5 minutes max d'attente avant abandon
_AUTO_STOP_INTERVAL = 300    # intervalle de la boucle auto-stop (5 minutes)
_DEFAULT_IDLE_TIMEOUT = 30   # minutes d'inactivité avant arrêt automatique


# ── Notification de démarrage ────────────────────────────────────────────────

async def notify_server_ready(
    bot: discord.Client,
    channel_id: int,
    server_name: str,
    instance_id: str,
    region: str,
    timeout: int = _NOTIFY_TIMEOUT,
    poll_interval: int = _NOTIFY_POLL_INTERVAL,
) -> None:
    """
    Poll EC2 jusqu'à ce que l'instance soit en état 'running',
    puis envoie un message dans le canal Discord d'origine.
    """
    ec2 = get_ec2_client(region)
    elapsed = 0

    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        try:
            response = ec2.describe_instances(InstanceIds=[instance_id])
            state = response["Reservations"][0]["Instances"][0]["State"]["Name"]
            if state == "running":
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(
                        f"✅ Le serveur **{server_name}** est prêt ! Utilisez `/ip` pour obtenir l'adresse."
                    )
                return
        except Exception as exc:
            logger.warning("Polling démarrage [%s]: %s", server_name, exc)

    # Timeout atteint
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(
            f"⚠️ Le serveur **{server_name}** met plus de {timeout // 60} minutes à démarrer. "
            "Vérifiez la console AWS."
        )


# ── Auto-stop ────────────────────────────────────────────────────────────────

async def auto_stop_loop(bot: discord.Client) -> None:
    """
    Boucle infinie lancée au démarrage du bot.
    Toutes les 5 minutes, vérifie chaque serveur running dans toutes les guilds.
    Si aucun joueur depuis N minutes (idle_timeout_minutes), arrête l'instance EC2.
    """
    logger.info("Auto-stop activé (intervalle : %ds)", _AUTO_STOP_INTERVAL)

    while True:
        await asyncio.sleep(_AUTO_STOP_INTERVAL)
        try:
            config = load_config()
            for guild_str, guild_data in config.get("guilds", {}).items():
                notification_channel_id = guild_data.get("notification_channel_id")
                for server_key, server_config in guild_data.get("servers", {}).items():
                    await _check_and_stop_if_idle(
                        bot=bot,
                        guild_str=guild_str,
                        server_key=server_key,
                        server_config=server_config,
                        notification_channel_id=notification_channel_id,
                    )
        except Exception as exc:
            logger.error("Erreur dans la boucle auto-stop : %s", exc)


async def _check_and_stop_if_idle(
    bot: discord.Client,
    guild_str: str,
    server_key: str,
    server_config: dict,
    notification_channel_id: int | None,
) -> None:
    instance_id: str | None = server_config.get("instance_id")
    region: str = server_config.get("region", "eu-north-1")
    name: str = server_config.get("name", server_key)
    idle_timeout: int = server_config.get("idle_timeout_minutes", _DEFAULT_IDLE_TIMEOUT)

    if not isinstance(instance_id, str) or not instance_id.startswith("i-"):
        return

    # 1. Vérifier que l'instance est bien running
    try:
        ec2 = get_ec2_client(region)
        statuses = ec2.describe_instance_status(InstanceIds=[instance_id]).get("InstanceStatuses", [])
        if not statuses or statuses[0]["InstanceState"]["Name"] != "running":
            _idle_since.pop((guild_str, server_key), None)
            return
    except Exception as exc:
        logger.debug("Auto-stop [%s] vérification EC2 : %s", name, exc)
        return

    # 2. Interroger le serveur Minecraft pour le nombre de joueurs
    host = _resolve_mc_host(server_config, ec2)
    if not host:
        return

    port = int(server_config.get("minecraft_port", "25565"))
    try:
        mc = JavaServer.lookup(f"{host}:{port}")
        status = await asyncio.wait_for(mc.async_status(), timeout=5.0)
        player_count = status.players.online
    except (asyncio.TimeoutError, Exception):
        # Serveur MC injoignable ou timeout : peut-être en démarrage, on ne compte pas comme inactif
        _idle_since.pop((guild_str, server_key), None)
        return

    key = (guild_str, server_key)
    now = datetime.datetime.now(datetime.timezone.utc)

    if player_count > 0:
        # Des joueurs sont connectés → reset du compteur
        _idle_since[key] = None
        return

    # 0 joueur
    if _idle_since.get(key) is None:
        _idle_since[key] = now
        logger.debug("Auto-stop [%s] : démarrage du compteur d'inactivité", name)
        return

    idle_minutes = (now - _idle_since[key]).total_seconds() / 60
    if idle_minutes < idle_timeout:
        return

    # Seuil atteint : arrêt automatique
    try:
        ec2.stop_instances(InstanceIds=[instance_id])
        _idle_since.pop(key, None)
        logger.info("Auto-stop [%s] : arrêté après %.0f min d'inactivité", name, idle_minutes)

        if notification_channel_id:
            channel = bot.get_channel(int(notification_channel_id))
            if channel:
                await channel.send(
                    f"🔴 **Auto-stop** — Le serveur **{name}** a été arrêté automatiquement "
                    f"après **{int(idle_minutes)} minutes** sans joueur connecté."
                )
    except Exception as exc:
        logger.error("Auto-stop [%s] : échec de l'arrêt — %s", name, exc)


def _resolve_mc_host(server_config: dict, ec2_client) -> str | None:
    """Retourne l'adresse MC à pinguer (DuckDNS prioritaire, sinon IP publique EC2)."""
    import os
    duckdns = os.getenv("DUCKDNS_DOMAIN")
    if duckdns:
        return duckdns if "." in duckdns else f"{duckdns}.duckdns.org"

    # Récupération de l'IP publique EC2
    instance_id = server_config.get("instance_id")
    try:
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        instance = response["Reservations"][0]["Instances"][0]
        return instance.get("PublicIpAddress")
    except Exception:
        return None
