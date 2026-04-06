import os

import discord
from discord import app_commands

from bot.autocomplete import server_autocomplete
from bot.aws import format_boto_error, get_ec2_client
from bot.commands.helpers import get_uptime_and_cost
from bot.config import get_guild_servers, get_server_config, load_config
from bot.helpers import is_valid_instance_id, require_guild, resolve_duckdns_host


def _format_bedrock_block(address: str, bedrock_port: int) -> str:
    return (
        f"\n**Bedrock :**\n"
        f"Adresse et Port : ```{address}```\n"
        f"```{bedrock_port}```"  # format souhaité pour que le port soit sur une ligne séparée, améliorant la lisibilité
    ) 


def setup(tree: app_commands.CommandTree) -> None:

    @tree.command(name="list", description="Liste tous les serveurs Minecraft disponibles")
    @require_guild
    async def list_command(interaction: discord.Interaction):

        servers = get_guild_servers(interaction.guild.id, load_config())
        if not servers:
            await interaction.response.send_message(
                ":x: Aucun serveur Minecraft configuré pour ce serveur Discord.", ephemeral=True
            )
            return

        lines = "\n".join(f"• **{data.get('name', key)}** (`{key}`)" for key, data in servers.items())
        await interaction.response.send_message(f":desktop: **Serveurs Minecraft disponibles :**\n\n{lines}")

    @tree.command(name="ip", description="Obtient l'adresse IP ou le domaine du serveur Minecraft")
    @app_commands.describe(server="Sélectionnez le serveur")
    @app_commands.autocomplete(server=server_autocomplete)
    @require_guild
    async def ip_command(interaction: discord.Interaction, server: str):

        server_config = get_server_config(interaction.guild.id, server, load_config())
        if not server_config:
            await interaction.response.send_message(
                ":x: Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        name = server_config.get("name", server)
        minecraft_port = server_config.get("minecraft_port", "25565")
        duckdns_domain = os.getenv("DUCKDNS_DOMAIN")

        if duckdns_domain:
            full_domain = resolve_duckdns_host(duckdns_domain)
            bedrock_port = server_config.get("bedrock_port")
            bedrock_info = ""
            if bedrock_port:
                bedrock_info = _format_bedrock_block(full_domain, bedrock_port)
            await interaction.response.send_message(
                f":globe_with_meridians: Adresse du serveur **{name}** :\n\n"
                f"**Java :**\n```{full_domain}:{minecraft_port}```{bedrock_info}"
            )
            return

        instance_id = server_config.get("instance_id")
        if not is_valid_instance_id(instance_id):
            await interaction.response.send_message(
                ":x: L'ID d'instance configuré est invalide. Impossible de récupérer l'IP.", ephemeral=True
            )
            return

        try:
            await interaction.response.defer()
            ec2 = get_ec2_client(server_config["region"])
            response = ec2.describe_instances(InstanceIds=[instance_id])

            if not response["Reservations"]:
                await interaction.followup.send(":x: Instance introuvable.")
                return

            instance = response["Reservations"][0]["Instances"][0]
            state = instance["State"]["Name"]

            if state != "running":
                await interaction.followup.send(
                    f":warning: Le serveur **{name}** n'est pas en cours d'exécution (état: **{state}**).\n"
                    f"Démarrez-le d'abord avec `/start {server}`"
                )
                return

            public_ip = instance.get("PublicIpAddress")
            if not public_ip:
                await interaction.followup.send(f":x: Le serveur **{name}** n'a pas d'adresse IP publique.")
                return

            bedrock_port = server_config.get("bedrock_port")
            bedrock_info = ""
            if bedrock_port:
                bedrock_info = _format_bedrock_block(public_ip, bedrock_port)
            await interaction.followup.send(
                f":globe_with_meridians: **Adresse du serveur {name} :**\n\n"
                f"**Java :**\n```{public_ip}:{minecraft_port}```{bedrock_info}"
            )
        except Exception as e:
            await interaction.followup.send(
                format_boto_error(e, action="récupérer l'IP du serveur", instance_id=instance_id, region=server_config.get("region")),
                ephemeral=True,
            )

    @tree.command(name="uptime", description="Affiche l'uptime et le coût estimé du serveur")
    @app_commands.describe(server="Sélectionnez le serveur")
    @app_commands.autocomplete(server=server_autocomplete)
    @require_guild
    async def uptime_command(interaction: discord.Interaction, server: str):

        server_config = get_server_config(interaction.guild.id, server, load_config())
        if not server_config:
            await interaction.response.send_message(
                ":x: Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        instance_id = server_config.get("instance_id")
        name = server_config.get("name", server)
        region = server_config.get("region", "eu-north-1")
        hourly_cost = server_config.get("hourly_cost", 0.0416)

        if not is_valid_instance_id(instance_id):
            await interaction.response.send_message(
                ":x: L'ID d'instance configuré est invalide.", ephemeral=True
            )
            return

        try:
            data = get_uptime_and_cost(instance_id, region, hourly_cost)

            if data is None:
                await interaction.response.send_message(f":white_circle: Le serveur **{name}** est **arrêté**.")
                return

            if not data["running"]:
                await interaction.response.send_message(f":white_circle: Le serveur **{name}** est à l'état **{data['state']}**.")
                return

            await interaction.response.send_message(
                f":bar_chart: **Uptime — {name}**\n\n"
                f":green_circle: **État :** {data['state']}\n"
                f":clock1: **En ligne depuis :** {data['delta'].days}j {data['hours'] % 24}h {data['minutes']}min\n"
                f":stopwatch: **Démarré le :** {data['launch_dt'].strftime('%d/%m/%Y à %H:%M')} UTC\n"
                f":moneybag: **Coût horaire :** ${hourly_cost:.4f}/h\n"
                f":chart_with_upwards_trend: **Coût total :** ${data['cost']:.4f}"
            )
        except Exception as e:
            await interaction.response.send_message(
                format_boto_error(e, action="vérifier l'uptime", instance_id=instance_id, region=region),
                ephemeral=True,
            )
