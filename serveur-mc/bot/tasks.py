"""
Tâches asyncio de fond :
- notify_server_ready : poll EC2 après /start, met à jour DuckDNS, lance le Java MC, notifie.
- auto_stop_loop      : surveille l'inactivité des serveurs et les arrête automatiquement.
"""
import asyncio
import datetime
import logging
import os

import discord
from mcstatus import JavaServer

from bot.aws import get_ec2_client
from bot.config import load_config

logger = logging.getLogger(__name__)

# Tracker d'inactivité : {(guild_id_str, server_key) -> datetime de début d'inactivité | None}
_idle_since: dict[tuple[str, str], datetime.datetime | None] = {}

_NOTIFY_POLL_INTERVAL = 10   # secondes entre chaque check EC2 lors du démarrage
_NOTIFY_TIMEOUT = 300        # 5 minutes max d'attente avant abandon
_SSH_READY_RETRIES = 12      # tentatives max pour attendre que SSH soit dispo (12 × 5s = 60s)
_SSH_READY_INTERVAL = 5      # secondes entre chaque tentative SSH
_RCON_READY_RETRIES = 18     # tentatives max pour attendre que RCON soit dispo (18 × 10s = 180s)
_RCON_READY_INTERVAL = 10    # secondes entre chaque tentative RCON
_AUTO_STOP_INTERVAL = 300    # intervalle de la boucle auto-stop (5 minutes)
_DEFAULT_IDLE_TIMEOUT = 30   # minutes d'inactivité avant arrêt automatique


# ── Notification de démarrage ────────────────────────────────────────────────

async def notify_server_ready(
    bot: discord.Client,
    channel_id: int,
    server_name: str,
    instance_id: str,
    region: str,
    server_key: str,
    server_config: dict,
    timeout: int = _NOTIFY_TIMEOUT,
    poll_interval: int = _NOTIFY_POLL_INTERVAL,
) -> None:
    """
    Phase 1 : Poll EC2 jusqu'à 'running'.
    Phase 2 : Met à jour DuckDNS avec la nouvelle IP publique.
    Phase 3 : Attend que SSH soit disponible sur l'instance.
    Phase 4 : Lance le processus Java Minecraft.
    Phase 5 : Notifie dans le canal Discord.
    """
    from bot.ssh import (
        get_instance_public_ip,
        update_duckdns,
        start_minecraft_process,
        check_rcon_ready,
        ssh_execute,
        MC_SERVER_USER,
        MC_SERVER_KEY_PATH,
    )

    ec2 = get_ec2_client(region)
    elapsed = 0
    public_ip: str | None = None

    # ── Phase 1 : attendre EC2 running ──────────────────────────────────────
    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        try:
            response = ec2.describe_instances(InstanceIds=[instance_id])
            state = response["Reservations"][0]["Instances"][0]["State"]["Name"]
            if state == "running":
                public_ip = response["Reservations"][0]["Instances"][0].get("PublicIpAddress")
                break
        except Exception as exc:
            logger.warning("Polling démarrage [%s]: %s", server_name, exc)

    if elapsed >= timeout and public_ip is None:
        channel = bot.get_channel(channel_id)
        if channel:
            await channel.send(
                f":warning: Le serveur **{server_name}** met plus de {timeout // 60} minutes à démarrer. "
                "Vérifiez la console AWS."
            )
        return

    # Récupérer l'IP si non obtenue lors du poll
    if not public_ip:
        try:
            public_ip = get_instance_public_ip(instance_id, region)
        except Exception as exc:
            logger.warning("Impossible de récupérer l'IP publique [%s]: %s", server_name, exc)

    # Progression intermédiaire : EC2 prêt, SSH en attente
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(
            f":hourglass: **{server_name}** — Instance EC2 active. "
            "Attente de la disponibilité SSH puis démarrage du serveur Minecraft…"
        )

    # ── Phase 2 : mise à jour DuckDNS ───────────────────────────────────────
    duckdns_ok = True
    if public_ip:
        domain = server_config.get("duckdns_domain") or os.getenv("DUCKDNS_DOMAIN", "")
        token = os.getenv("DUCKDNS_TOKEN", "")
        if domain and token:
            duckdns_ok = await update_duckdns(domain, token, public_ip)
        else:
            logger.debug("DuckDNS ignoré pour [%s] : domaine ou token absent", server_name)

    # ── Phase 3 : attendre que SSH soit disponible ───────────────────────────
    _user = MC_SERVER_USER
    _key_path = MC_SERVER_KEY_PATH
    ssh_host = public_ip  # utiliser l'IP directe plutôt que le domaine

    ssh_ready = False
    if ssh_host and _key_path:
        for attempt in range(_SSH_READY_RETRIES):
            ok, _ = await asyncio.to_thread(
                ssh_execute, ssh_host, _user, _key_path, "echo ok", 10
            )
            if ok:
                ssh_ready = True
                break
            logger.debug("SSH pas encore prêt [%s] tentative %d/%d", server_name, attempt + 1, _SSH_READY_RETRIES)
            await asyncio.sleep(_SSH_READY_INTERVAL)

    # ── Phase 4 : lancer le processus Minecraft ─────────────────────────────
    mc_started = False
    mc_error = ""
    if ssh_ready:
        mc_started, mc_output = await asyncio.to_thread(
            start_minecraft_process,
            server_key,
            max_ram=server_config.get("max_ram", "1536M"),
            min_ram=server_config.get("min_ram", "1024M"),
            host=ssh_host,
        )
        if not mc_started:
            mc_error = mc_output
            logger.error("Démarrage Minecraft [%s] échoué : %s", server_name, mc_output)

    # ── Phase 4bis : attendre que RCON soit opérationnel ───────────────────
    rcon_ready = False
    if mc_started:
        for attempt in range(_RCON_READY_RETRIES):
            rcon_ok, _ = await asyncio.to_thread(
                check_rcon_ready, server_key, host=ssh_host
            )
            if rcon_ok:
                rcon_ready = True
                break
            logger.debug("RCON pas encore prêt [%s] tentative %d/%d", server_name, attempt + 1, _RCON_READY_RETRIES)
            await asyncio.sleep(_RCON_READY_INTERVAL)

    # ── Phase 5 : notifier dans Discord ─────────────────────────────────────
    channel = bot.get_channel(channel_id)
    if not channel:
        return

    if rcon_ready:
        extra = ""
        if not duckdns_ok:
            extra = "\n:warning: La mise à jour DuckDNS a échoué — vérifiez le token/domaine."
        await channel.send(
            f":white_check_mark: Le serveur **{server_name}** est prêt ! Utilisez `/ip` pour obtenir l'adresse.{extra}"
        )
    elif mc_started:
        # Java lancé mais RCON n'a pas répondu dans le délai imparti
        _rcon_timeout_minutes = _RCON_READY_RETRIES * _RCON_READY_INTERVAL // 60
        await channel.send(
            f":warning: Le serveur **{server_name}** : le processus Minecraft a démarré mais RCON "
            f"n'est pas disponible après {_rcon_timeout_minutes} minutes. "
            "Le serveur est peut-être encore en chargement ou a planté."
        )
    elif not ssh_ready:
        await channel.send(
            f":warning: Le serveur **{server_name}** : l'instance EC2 est active mais SSH est injoignable. "
            "Le serveur Minecraft n'a pas pu être démarré automatiquement."
        )
    else:
        await channel.send(
            f":x: Le serveur **{server_name}** : l'instance EC2 est active mais le démarrage Minecraft a échoué.\n"
            f"```\n{mc_error[:500]}\n```"
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
    from bot.ssh import stop_minecraft_server, check_other_mc_servers_running

    # Résolution de l'hôte SSH : priorité à la config par serveur
    ssh_host = server_config.get("ssh_host") or None

    # 1. Arrêt gracieux du processus MC via RCON
    mc_ok, _ = await asyncio.to_thread(stop_minecraft_server, server_key, host=ssh_host)
    if not mc_ok:
        logger.warning("Auto-stop [%s] : RCON stop échoué, on arrête quand même EC2", name)

    # 2. Vérifier si d'autres serveurs tournent sur la même instance
    check_success, running_others = await asyncio.to_thread(
        check_other_mc_servers_running, server_key, host=ssh_host
    )

    if not check_success:
        # SSH indisponible : impossible de déterminer l'état des autres serveurs
        # → on conserve l'instance EC2 par précaution
        logger.warning(
            "Auto-stop [%s] : SSH injoignable pour check_other_mc_servers_running — instance conservée",
            name,
        )
        _idle_since.pop(key, None)
        if notification_channel_id:
            channel = bot.get_channel(int(notification_channel_id))
            if channel:
                await channel.send(
                    f":yellow_circle: **Auto-stop** — Le serveur **{name}** a été arrêté "
                    f"après **{int(idle_minutes)} minutes** sans joueur. "
                    ":warning: Impossible de vérifier les autres serveurs actifs (SSH injoignable) — "
                    "l'instance EC2 est conservée par précaution."
                )
        return

    if running_others:
        logger.info(
            "Auto-stop [%s] : MC arrêté mais instance conservée (autres actifs : %s)",
            name, ", ".join(running_others),
        )
        _idle_since.pop(key, None)
        if notification_channel_id:
            channel = bot.get_channel(int(notification_channel_id))
            if channel:
                await channel.send(
                    f":yellow_circle: **Auto-stop** — Le serveur **{name}** a été arrêté "
                    f"après **{int(idle_minutes)} minutes** sans joueur. "
                    f"L'instance reste active (autres serveurs : {', '.join(running_others)})."
                )
        return

    # 3. Aucun autre serveur actif → arrêt de l'instance EC2
    try:
        ec2.stop_instances(InstanceIds=[instance_id])
        _idle_since.pop(key, None)
        logger.info("Auto-stop [%s] : instance EC2 arrêtée après %.0f min d'inactivité", name, idle_minutes)

        if notification_channel_id:
            channel = bot.get_channel(int(notification_channel_id))
            if channel:
                await channel.send(
                    f":red_circle: **Auto-stop** — Le serveur **{name}** a été arrêté automatiquement "
                    f"après **{int(idle_minutes)} minutes** sans joueur connecté."
                )
    except Exception as exc:
        logger.error("Auto-stop [%s] : échec de l'arrêt EC2 — %s", name, exc)


def _resolve_mc_host(server_config: dict, ec2_client) -> str | None:
    """Retourne l'adresse MC à pinguer (DuckDNS prioritaire, sinon IP publique EC2).

    Ordre de priorité :
    1. server_config["duckdns_domain"] (config par serveur)
    2. Variable d'env DUCKDNS_DOMAIN (fallback global)
    3. IP publique EC2 via boto3
    """
    duckdns = server_config.get("duckdns_domain") or os.getenv("DUCKDNS_DOMAIN")
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
