import asyncio

import discord
from discord import app_commands

from bot.autocomplete import server_autocomplete
from bot.aws import format_boto_error, get_ec2_client
from bot.config import get_server_config, load_config
from bot.helpers import is_valid_instance_id, require_guild
from bot.permissions import check_permission
from bot.minecraft_process import check_other_mc_servers_running, stop_minecraft_server
from bot.ssh import get_instance_public_ip
from bot.tasks import notify_server_ready


def _get_instance_state(instance_id: str, region: str) -> str | None:
    """Retourne l'état courant de l'instance EC2 ou None en cas d'erreur."""
    try:
        ec2 = get_ec2_client(region)
        resp = ec2.describe_instances(InstanceIds=[instance_id])
        return resp["Reservations"][0]["Instances"][0]["State"]["Name"]
    except Exception:
        return None


def setup(tree: app_commands.CommandTree) -> None:

    @tree.command(name="start", description="Démarre le serveur Minecraft")
    @app_commands.describe(server="Sélectionnez le serveur à démarrer")
    @app_commands.autocomplete(server=server_autocomplete)
    @require_guild
    async def start_command(interaction: discord.Interaction, server: str):

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
        if not is_valid_instance_id(instance_id):
            await interaction.response.send_message(
                ":x: L'ID d'instance configuré est invalide. Corrigez la configuration du serveur.",
                ephemeral=True,
            )
            return

        name = server_config.get("name", server)
        region = server_config.get("region", "eu-north-1")

        try:
            current_state = await asyncio.to_thread(_get_instance_state, instance_id, region)
            ec2 = get_ec2_client(region)

            if current_state not in ("running", "pending"):
                ec2.start_instances(InstanceIds=[instance_id])
                status_msg = f":green_circle: Le serveur **{name}** est en cours de démarrage… Je vous notifie dès qu'il est prêt !"
            else:
                status_msg = f":arrows_counterclockwise: Le serveur **{name}** est déjà actif — lancement du processus Minecraft…"

            await interaction.response.send_message(status_msg)

            # Lance le pipeline complet en arrière-plan : EC2 poll → DuckDNS → SSH → Java
            asyncio.create_task(
                notify_server_ready(
                    bot=interaction.client,
                    channel_id=interaction.channel_id,
                    server_name=name,
                    instance_id=instance_id,
                    region=region,
                    server_key=server,
                    server_config=server_config,
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
    @require_guild
    async def stop_command(interaction: discord.Interaction, server: str):

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

        name = server_config.get("name", server)
        instance_id = server_config.get("instance_id")
        region = server_config.get("region", "eu-north-1")
        ssh_host = server_config.get("ssh_host") or None

        # En multi-instance, /stop doit viser explicitement l'hôte du serveur ciblé.
        # Sinon le helper peut retomber sur MC_SERVER_INSTANCE_ID global.
        if not ssh_host and isinstance(instance_id, str) and instance_id.startswith("i-"):
            try:
                ssh_host = await asyncio.to_thread(get_instance_public_ip, instance_id, region)
            except Exception:
                ssh_host = None

        await interaction.response.defer()
        success, output = await asyncio.to_thread(stop_minecraft_server, server, host=ssh_host)
        if not success:
            if "Connection refused" in output or "Error 111" in output:
                msg = (
                    f":x: Impossible d'arrêter le serveur **{name}** : "
                    "le serveur Minecraft ne répond pas (RCON refusé).\n"
                    "Il est peut-être encore en cours de démarrage — réessayez dans quelques secondes."
                )
            else:
                host_info = ssh_host or "(résolution par défaut)"
                msg = (
                    f":x: Impossible d'arrêter le serveur **{name}** (hôte SSH: `{host_info}`) :\n"
                    f"```\n{output}\n```"
                )
            await interaction.followup.send(msg, ephemeral=True)
            return

        # Vérifier si d'autres serveurs MC tournent sur la même instance
        # On passe ssh_host explicitement pour les contextes multi-instances
        check_success, running_others = await asyncio.to_thread(
            check_other_mc_servers_running, server, host=ssh_host
        )

        if not check_success:
            # SSH indisponible : on ne peut pas déterminer l'état des autres serveurs
            # → on conserve l'instance EC2 par précaution
            await interaction.followup.send(
                f":red_circle: Le serveur **{name}** a été arrêté.\n"
                ":warning: Impossible de vérifier les autres serveurs actifs (SSH injoignable) — "
                "l'instance EC2 est conservée par précaution."
            )
            return

        if running_others:
            others_str = ", ".join(f"`{k}`" for k in running_others)
            await interaction.followup.send(
                f":red_circle: Le serveur **{name}** a été arrêté.\n"
                f":information_source: D'autres serveurs sont encore actifs ({others_str}) — l'instance EC2 reste en marche."
            )
            return

        # Aucun autre serveur actif → arrêt de l'instance EC2
        if isinstance(instance_id, str) and instance_id.startswith("i-"):
            try:
                ec2 = get_ec2_client(region)
                ec2.stop_instances(InstanceIds=[instance_id])
                await interaction.followup.send(
                    f":red_circle: Le serveur **{name}** a été arrêté. "
                    "Aucun autre serveur actif — l'instance EC2 est en cours d'arrêt."
                )
            except Exception as e:
                await interaction.followup.send(
                    f":red_circle: Le serveur **{name}** a été arrêté.\n"
                    ":warning: Impossible d'arrêter l'instance EC2 : "
                    + format_boto_error(e, action="arrêter l'instance", instance_id=instance_id, region=region)
                )
        else:
            await interaction.followup.send(
                f":red_circle: Le serveur Minecraft **{name}** a été arrêté."
            )

    @tree.command(name="status", description="Vérifie le statut du serveur Minecraft")
    @app_commands.describe(server="Sélectionnez le serveur à vérifier")
    @app_commands.autocomplete(server=server_autocomplete)
    @require_guild
    async def status_command(interaction: discord.Interaction, server: str):

        server_config = get_server_config(interaction.guild.id, server, load_config())
        if not server_config:
            await interaction.response.send_message(
                ":x: Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        instance_id = server_config.get("instance_id")
        if not is_valid_instance_id(instance_id):
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
