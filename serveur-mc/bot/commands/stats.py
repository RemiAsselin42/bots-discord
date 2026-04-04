import os

import discord
from discord import app_commands
from mcstatus import JavaServer
from mcstatus.responses import JavaStatusResponse

from bot.autocomplete import server_autocomplete
from bot.aws import format_boto_error, get_ec2_client
from bot.commands.helpers import get_uptime_and_cost
from bot.config import get_server_config, load_config
from bot.helpers import is_valid_instance_id, require_guild, resolve_duckdns_host


def setup(tree: app_commands.CommandTree) -> None:

    @tree.command(name="cost", description="Affiche le coût réel depuis le démarrage de l'instance")
    @app_commands.describe(server="Sélectionnez le serveur")
    @app_commands.autocomplete(server=server_autocomplete)
    @require_guild
    async def cost_command(interaction: discord.Interaction, server: str):

        server_config = get_server_config(interaction.guild.id, server, load_config())
        if not server_config:
            await interaction.response.send_message(
                ":x: Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        instance_id = server_config.get("instance_id")
        name = server_config.get("name", server)
        region = server_config.get("region", "eu-north-1")
        hourly_cost: float = server_config.get("hourly_cost", 0.0416)

        if not is_valid_instance_id(instance_id):
            await interaction.response.send_message(
                ":x: L'ID d'instance configuré est invalide.", ephemeral=True
            )
            return

        try:
            data = get_uptime_and_cost(instance_id, region, hourly_cost)

            if data is None:
                await interaction.response.send_message(f":white_circle: Le serveur **{name}** est arrêté. Coût actuel : $0.00")
                return

            if not data["running"]:
                await interaction.response.send_message(
                    f":white_circle: Le serveur **{name}** est à l'état **{data['state']}**. Impossible de calculer le coût."
                )
                return

            await interaction.response.send_message(
                f":moneybag: **Coût - {name}**\n\n"
                f":stopwatch: **En ligne depuis:** {data['hours']}h {data['minutes']}min\n"
                f":1234: **Coût horaire:** ${hourly_cost:.4f}/h\n"
                f":money_with_wings: **Coût total actuel:** `${data['cost']:.4f}` (≈ ${data['cost']:.2f})"
            )
        except Exception as e:
            await interaction.response.send_message(
                format_boto_error(e, action="calculer le coût", instance_id=instance_id, region=region),
                ephemeral=True,
            )

    @tree.command(name="players", description="Affiche les joueurs connectés au serveur Minecraft")
    @app_commands.describe(server="Sélectionnez le serveur")
    @app_commands.autocomplete(server=server_autocomplete)
    @require_guild
    async def players_command(interaction: discord.Interaction, server: str):

        server_config = get_server_config(interaction.guild.id, server, load_config())
        if not server_config:
            await interaction.response.send_message(
                ":x: Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        name = server_config.get("name", server)
        port = int(server_config.get("minecraft_port", "25565"))
        duckdns_domain: str | None = os.getenv("DUCKDNS_DOMAIN")

        await interaction.response.defer()

        # Résolution de l'adresse du serveur
        host = resolve_duckdns_host(duckdns_domain) if duckdns_domain else None
        if host is None:
            # Pas de DuckDNS → on récupère l'IP publique EC2
            instance_id = server_config.get("instance_id")
            region = server_config.get("region", "eu-north-1")

            if not is_valid_instance_id(instance_id):
                await interaction.followup.send(
                    ":x: L'ID d'instance configuré est invalide. Impossible de joindre le serveur.",
                    ephemeral=True,
                )
                return

            try:
                host = _get_ec2_public_ip(instance_id, region, name, server)
            except Exception as e:
                await interaction.followup.send(
                    format_boto_error(e, action="récupérer l'IP", instance_id=instance_id, region=region),
                    ephemeral=True,
                )
                return

            if host is None:
                await interaction.followup.send(
                    f":warning: Le serveur **{name}** n'est pas en cours d'exécution ou n'a pas d'IP publique.\n"
                    f"Démarrez-le d'abord avec `/start {server}`"
                )
                return

        # Ping Minecraft
        try:
            mc = JavaServer.lookup(f"{host}:{port}")
            status: JavaStatusResponse = await mc.async_status()
        except (ConnectionRefusedError, TimeoutError, OSError):
            await interaction.followup.send(
                f":warning: Le serveur Minecraft **{name}** ne répond pas sur `{host}:{port}`.\n"
                "Il est peut-être en cours de démarrage, ou le port n'est pas accessible."
            )
            return

        online = status.players.online
        max_players = status.players.max
        sample = status.players.sample or []

        if online == 0:
            msg = f":busts_in_silhouette: **{name}** — `0/{max_players}` joueurs connectés."
        else:
            player_names = ", ".join(p.name for p in sample) if sample else "noms non disponibles"
            msg = (
                f":busts_in_silhouette: **{name}** — `{online}/{max_players}` joueur(s) connecté(s)\n"
                f":video_game: {player_names}"
            )

        await interaction.followup.send(msg)


def _get_ec2_public_ip(instance_id: str, region: str, name: str, server_key: str) -> str | None:
    ec2 = get_ec2_client(region)
    response = ec2.describe_instances(InstanceIds=[instance_id])
    if not response["Reservations"]:
        return None
    instance = response["Reservations"][0]["Instances"][0]
    if instance["State"]["Name"] != "running":
        return None
    return instance.get("PublicIpAddress")
