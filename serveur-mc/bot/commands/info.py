import discord
from discord import app_commands

from bot.autocomplete import server_autocomplete
from bot.aws import format_boto_error, get_ec2_client
from bot.commands.helpers import get_uptime_and_cost
from bot.config import get_guild_servers, get_server_config, load_config


def setup(tree: app_commands.CommandTree) -> None:

    @tree.command(name="list", description="Liste tous les serveurs Minecraft disponibles")
    async def list_command(interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        servers = get_guild_servers(interaction.guild.id, load_config())
        if not servers:
            await interaction.response.send_message(
                "❌ Aucun serveur Minecraft configuré pour ce serveur Discord.", ephemeral=True
            )
            return

        lines = "\n".join(f"• **{data.get('name', key)}** (`{key}`)" for key, data in servers.items())
        await interaction.response.send_message(f"🖥️ **Serveurs Minecraft disponibles :**\n\n{lines}")

    @tree.command(name="ip", description="Obtient l'adresse IP ou le domaine du serveur Minecraft")
    @app_commands.describe(server="Sélectionnez le serveur")
    @app_commands.autocomplete(server=server_autocomplete)
    async def ip_command(interaction: discord.Interaction, server: str):
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        server_config = get_server_config(interaction.guild.id, server, load_config())
        if not server_config:
            await interaction.response.send_message(
                "❌ Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        name = server_config.get("name", server)
        minecraft_port = server_config.get("minecraft_port", "25565")
        duckdns_domain = server_config.get("duckdns_domain")

        if duckdns_domain:
            full_domain = duckdns_domain if "." in duckdns_domain else f"{duckdns_domain}.duckdns.org"
            await interaction.response.send_message(
                f"🌐 **Adresse du serveur {name} :**\n\n```{full_domain}:{minecraft_port}```"
            )
            return

        instance_id = server_config.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id.startswith("i-"):
            await interaction.response.send_message(
                "❌ L'ID d'instance configuré est invalide. Impossible de récupérer l'IP.", ephemeral=True
            )
            return

        try:
            await interaction.response.defer()
            ec2 = get_ec2_client(server_config["region"])
            response = ec2.describe_instances(InstanceIds=[instance_id])

            if not response["Reservations"]:
                await interaction.followup.send("❌ Instance introuvable.")
                return

            instance = response["Reservations"][0]["Instances"][0]
            state = instance["State"]["Name"]

            if state != "running":
                await interaction.followup.send(
                    f"⚠️ Le serveur **{name}** n'est pas en cours d'exécution (état: **{state}**).\n"
                    f"Démarrez-le d'abord avec `/start {server}`"
                )
                return

            public_ip = instance.get("PublicIpAddress")
            if not public_ip:
                await interaction.followup.send(f"❌ Le serveur **{name}** n'a pas d'adresse IP publique.")
                return

            await interaction.followup.send(
                f"🌐 **Adresse du serveur {name} :**\n\n```{public_ip}:{minecraft_port}```"
            )
        except Exception as e:
            await interaction.followup.send(
                format_boto_error(e, action="récupérer l'IP du serveur", instance_id=instance_id, region=server_config.get("region")),
                ephemeral=True,
            )

    @tree.command(name="uptime", description="Affiche l'uptime et le coût estimé du serveur")
    @app_commands.describe(server="Sélectionnez le serveur")
    @app_commands.autocomplete(server=server_autocomplete)
    async def uptime_command(interaction: discord.Interaction, server: str):
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        server_config = get_server_config(interaction.guild.id, server, load_config())
        if not server_config:
            await interaction.response.send_message(
                "❌ Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        instance_id = server_config.get("instance_id")
        name = server_config.get("name", server)
        region = server_config.get("region", "eu-north-1")
        hourly_cost = server_config.get("hourly_cost", 0.0416)

        if not isinstance(instance_id, str) or not instance_id.startswith("i-"):
            await interaction.response.send_message(
                "❌ L'ID d'instance configuré est invalide.", ephemeral=True
            )
            return

        try:
            data = get_uptime_and_cost(instance_id, region, hourly_cost)

            if data is None:
                await interaction.response.send_message(f"⚪ Le serveur **{name}** est **arrêté**.")
                return

            if not data["running"]:
                await interaction.response.send_message(f"⚪ Le serveur **{name}** est à l'état **{data['state']}**.")
                return

            await interaction.response.send_message(
                f"📊 **Uptime - {name}**\n\n"
                f"⏱️ **État:** {data['state']}\n"
                f"🕐 **En ligne depuis:** {data['hours']}h {data['minutes']}min ({data['delta'].days} jours)\n"
                f"💰 **Coût horaire:** ${hourly_cost:.4f}\n"
                f"📈 **Coût depuis le démarrage:** ${data['cost']:.2f}"
            )
        except Exception as e:
            await interaction.response.send_message(
                format_boto_error(e, action="vérifier l'uptime", instance_id=instance_id, region=region),
                ephemeral=True,
            )
