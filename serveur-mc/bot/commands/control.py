import asyncio

import discord
from discord import app_commands

from bot.autocomplete import server_autocomplete
from bot.aws import format_boto_error, get_ec2_client
from bot.config import get_server_config, load_config
from bot.permissions import check_permission


def setup(tree: app_commands.CommandTree) -> None:

    @tree.command(name="start", description="Démarre le serveur Minecraft")
    @app_commands.describe(server="Sélectionnez le serveur à démarrer")
    @app_commands.autocomplete(server=server_autocomplete)
    async def start_command(interaction: discord.Interaction, server: str):
        if not interaction.guild:
            await interaction.response.send_message(
                ":x: Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        config = load_config()

        if not check_permission(interaction, "start", config):
            await interaction.response.send_message(
                ":x: Vous n'avez pas la permission de démarrer ce serveur.", ephemeral=True
            )
            return

        server_config = get_server_config(interaction.guild.id, server, config)
        if not server_config:
            await interaction.response.send_message(
                ":x: Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        instance_id = server_config.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id.startswith("i-"):
            await interaction.response.send_message(
                ":x: L'ID d'instance configuré est invalide. Corrigez la configuration du serveur.",
                ephemeral=True,
            )
            return

        name = server_config.get("name", server)
        region = server_config.get("region", "eu-north-1")

        try:
            ec2 = get_ec2_client(region)
            ec2.start_instances(InstanceIds=[instance_id])
            await interaction.response.send_message(
                f":green_circle: Le serveur **{name}** est en cours de démarrage… "
                "Je vous notifie dès qu'il est prêt !"
            )
            # Lance le polling en arrière-plan — notifie dans ce même salon
            from bot.tasks import notify_server_ready
            asyncio.create_task(
                notify_server_ready(
                    bot=interaction.client,
                    channel_id=interaction.channel_id,
                    server_name=name,
                    instance_id=instance_id,
                    region=region,
                )
            )
        except Exception as e:
            await interaction.response.send_message(
                format_boto_error(e, action="démarrer le serveur", instance_id=instance_id, region=region),
                ephemeral=True,
            )

    @tree.command(name="stop", description="Arrête le serveur Minecraft")
    @app_commands.describe(server="Sélectionnez le serveur à arrêter")
    @app_commands.autocomplete(server=server_autocomplete)
    async def stop_command(interaction: discord.Interaction, server: str):
        if not interaction.guild:
            await interaction.response.send_message(
                ":x: Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        config = load_config()

        if not check_permission(interaction, "stop", config):
            await interaction.response.send_message(
                ":x: Vous n'avez pas la permission d'arrêter ce serveur.", ephemeral=True
            )
            return

        server_config = get_server_config(interaction.guild.id, server, config)
        if not server_config:
            await interaction.response.send_message(
                ":x: Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        instance_id = server_config.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id.startswith("i-"):
            await interaction.response.send_message(
                ":x: L'ID d'instance configuré est invalide. Corrigez la configuration du serveur.",
                ephemeral=True,
            )
            return

        name = server_config.get("name", server)
        region = server_config.get("region", "eu-north-1")
        try:
            ec2 = get_ec2_client(region)
            ec2.stop_instances(InstanceIds=[instance_id])
            await interaction.response.send_message(f":red_circle: Le serveur **{name}** est en cours d'arrêt...")
        except Exception as e:
            await interaction.response.send_message(
                format_boto_error(e, action="arrêter le serveur", instance_id=instance_id, region=region),
                ephemeral=True,
            )

    @tree.command(name="status", description="Vérifie le statut du serveur Minecraft")
    @app_commands.describe(server="Sélectionnez le serveur à vérifier")
    @app_commands.autocomplete(server=server_autocomplete)
    async def status_command(interaction: discord.Interaction, server: str):
        if not interaction.guild:
            await interaction.response.send_message(
                ":x: Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        server_config = get_server_config(interaction.guild.id, server, load_config())
        if not server_config:
            await interaction.response.send_message(
                ":x: Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        instance_id = server_config.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id.startswith("i-"):
            await interaction.response.send_message(
                ":x: L'ID d'instance configuré est invalide. Corrigez la configuration du serveur.",
                ephemeral=True,
            )
            return

        name = server_config.get("name", server)
        try:
            ec2 = get_ec2_client(server_config["region"])
            statuses = ec2.describe_instance_status(InstanceIds=[instance_id]).get("InstanceStatuses", [])
            if not statuses:
                await interaction.response.send_message(f":white_circle: Le serveur **{name}** est **arrêté**.")
            else:
                state = statuses[0]["InstanceState"]["Name"]
                await interaction.response.send_message(f":information_source: Statut du serveur **{name}** : **{state}**")
        except Exception as e:
            await interaction.response.send_message(
                format_boto_error(e, action="vérifier le statut", instance_id=instance_id, region=server_config.get("region")),
                ephemeral=True,
            )
