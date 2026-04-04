import asyncio
import os
import re

import discord
from discord import app_commands

from bot import ssh as ssh_helper
from bot.autocomplete import server_autocomplete, version_autocomplete
from bot.aws import format_boto_error, manage_sg_port
from bot.config import load_config, save_config
from bot.helpers import slugify_name
from bot.permissions import CONFIGURABLE_COMMANDS, DEFAULT_PERMISSIONS, get_permission_summary
from bot.port_manager import assign_port


def setup(tree: app_commands.CommandTree) -> None:

    @tree.command(name="createserver", description="Crée un nouveau serveur Minecraft avec attribution automatique de port")
    @app_commands.describe(
        name="Nom affiché du serveur",
        instance_id="ID de l'instance EC2 AWS (ex: i-xxxxxxxxxxxxx)",
        ram="RAM allouée au serveur (ex: 2G, 1536M, 512M) — entiers uniquement",
        region="Région AWS de l'instance (ex: eu-north-1, eu-west-3, us-east-1)",
        version="Version de Minecraft (ex: 1.21.4, latest)",
    )
    @app_commands.autocomplete(version=version_autocomplete)
    async def createserver_command(
        interaction: discord.Interaction,
        name: str,
        instance_id: str = "i-XXXXXXXXXXXXXXXXX",
        ram: str = "1536M",
        region: str = "eu-north-1",
        version: str = "latest",
    ):
        if not interaction.guild:
            await interaction.response.send_message(
                ":x: Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                ":x: Seuls les administrateurs peuvent créer des serveurs.", ephemeral=True
            )
            return

        if not instance_id.startswith("i-") or len(instance_id) != 19:
            await interaction.response.send_message(
                ":x: Format d'instance_id invalide. Exemple: `i-0123456789abcdef0`", ephemeral=True
            )
            return

        ram_upper = ram.upper()
        if not re.match(r"^\d+[GM]$", ram_upper):
            await interaction.response.send_message(
                ":x: Format de RAM invalide. Exemples : `2G`, `1536M`, `512M` (entiers uniquement — pas de décimales).",
                ephemeral=True,
            )
            return

        guild_str = str(interaction.guild.id)
        config = load_config()

        if guild_str not in config["guilds"]:
            config["guilds"][guild_str] = {"name": interaction.guild.name, "servers": {}}

        key = slugify_name(name) or "world"
        if key in config["guilds"][guild_str]["servers"]:
            counter = 2
            base = key
            while key in config["guilds"][guild_str]["servers"]:
                key = f"{base}-{counter}"
                counter += 1

        try:
            port = assign_port(config, interaction.guild.id)
        except ValueError as e:
            await interaction.response.send_message(f":x: {e}", ephemeral=True)
            return

        server_data: dict = {
            "name": name,
            "instance_id": instance_id,
            "region": region,
            "port": port,
            "minecraft_port": str(port),
            "max_ram": ram_upper,
            "min_ram": "1G",
        }
        config["guilds"][guild_str]["servers"][key] = server_data

        try:
            save_config(config)
        except Exception as e:
            await interaction.response.send_message(f":x: Erreur lors de la sauvegarde : {e}", ephemeral=True)
            return

        confirm = (
            f":white_check_mark: Serveur **{name}** enregistré avec succès !\n\n"
            f":clipboard: **Configuration :**\n"
            f"• Nom: `{name}`\n"
            f"• Port Minecraft: `{port}`\n"
            f"• RAM: `{ram_upper}`\n"
            f"• Version: `{version}`\n\n"
            f":hourglass: **Installation en cours sur l'instance EC2...**"
        )
        await interaction.response.send_message(confirm)

        # Setup SSH en arrière-plan
        asyncio.create_task(_run_ssh_setup(interaction, key, port, name, instance_id, region, version))

    @tree.command(name="removeserver", description="Supprime un serveur Minecraft de la configuration")
    @app_commands.describe(server="Sélectionnez le serveur à supprimer")
    @app_commands.autocomplete(server=server_autocomplete)
    async def removeserver_command(interaction: discord.Interaction, server: str):
        if not interaction.guild:
            await interaction.response.send_message(
                ":x: Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                ":x: Seuls les administrateurs peuvent supprimer des serveurs.", ephemeral=True
            )
            return

        guild_str = str(interaction.guild.id)
        config = load_config()

        if guild_str not in config["guilds"] or server not in config["guilds"][guild_str]["servers"]:
            await interaction.response.send_message(
                ":x: Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        server_data = config["guilds"][guild_str]["servers"][server]
        name = server_data.get("name", server)
        port = server_data.get("port")
        instance_id = server_data.get("instance_id")
        region = server_data.get("region", "eu-north-1")
        del config["guilds"][guild_str]["servers"][server]

        try:
            save_config(config)
        except Exception as e:
            await interaction.response.send_message(f":x: Erreur lors de la sauvegarde : {e}", ephemeral=True)
            return

        sg_info = ""
        if port and instance_id:
            try:
                await asyncio.to_thread(manage_sg_port, instance_id, region, port, "revoke")
                sg_info = ""
            except Exception as e:
                sg_info = f"\n:warning: Port `{port}` non fermé dans le Security Group : {format_boto_error(e, action='révoquer le port', instance_id=instance_id, region=region)}"
        await interaction.response.send_message(
            f":white_check_mark: Serveur **{name}** (`{server}`) supprimé avec succès.{sg_info}"
        )

    @tree.command(name="editserver", description="Modifie la configuration d'un serveur existant")
    @app_commands.describe(
        server="Sélectionnez le serveur à modifier",
        name="Nouveau nom affiché",
        instance_id="Nouvel ID d'instance EC2",
        region="Nouvelle région AWS",
        hourly_cost="Nouveau coût horaire en $",
    )
    @app_commands.autocomplete(server=server_autocomplete)
    async def editserver_command(
        interaction: discord.Interaction,
        server: str,
        name: str | None = None,
        instance_id: str | None = None,
        region: str | None = None,
        hourly_cost: float | None = None,
    ):
        if not interaction.guild:
            await interaction.response.send_message(
                ":x: Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                ":x: Seuls les administrateurs peuvent modifier des serveurs.", ephemeral=True
            )
            return

        if instance_id is not None and (not instance_id.startswith("i-") or len(instance_id) != 19):
            await interaction.response.send_message(
                ":x: Format d'instance_id invalide. Exemple: `i-0123456789abcdef0`", ephemeral=True
            )
            return

        guild_str = str(interaction.guild.id)
        config = load_config()

        if guild_str not in config["guilds"] or server not in config["guilds"][guild_str]["servers"]:
            await interaction.response.send_message(
                ":x: Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        server_data = config["guilds"][guild_str]["servers"][server]
        changes = []

        if name is not None:
            server_data["name"] = name
            changes.append(f"• Nom: `{name}`")
        if instance_id is not None:
            server_data["instance_id"] = instance_id
            changes.append(f"• Instance: `{instance_id}`")
        if region is not None:
            server_data["region"] = region
            changes.append(f"• Région: `{region}`")
        if hourly_cost is not None:
            server_data["hourly_cost"] = hourly_cost
            changes.append(f"• Coût horaire: `${hourly_cost:.4f}`")

        if not changes:
            await interaction.response.send_message(
                ":warning: Aucun paramètre fourni. Rien n'a été modifié.", ephemeral=True
            )
            return

        try:
            save_config(config)
            display_name = server_data.get("name", server)
            await interaction.response.send_message(
                f":white_check_mark: Serveur **{display_name}** (`{server}`) mis à jour :\n\n" + "\n".join(changes)
            )
        except Exception as e:
            await interaction.response.send_message(f":x: Erreur lors de la sauvegarde : {e}", ephemeral=True)

    # ── Permissions ─────────────────────────────────────────────────────────

    @tree.command(name="setpermission", description="Autorise un rôle à utiliser une commande")
    @app_commands.describe(
        command="Commande à configurer",
        role="Rôle Discord à autoriser",
    )
    @app_commands.choices(command=[app_commands.Choice(name=c, value=c) for c in CONFIGURABLE_COMMANDS])
    async def setpermission_command(interaction: discord.Interaction, command: str, role: discord.Role):
        if not interaction.guild:
            await interaction.response.send_message(
                ":x: Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                ":x: Seuls les administrateurs peuvent modifier les permissions.", ephemeral=True
            )
            return

        guild_str = str(interaction.guild.id)
        config = load_config()

        guild_data = config["guilds"].setdefault(guild_str, {"name": interaction.guild.name, "servers": {}})
        perms = guild_data.setdefault("permissions", {})
        cmd_perm = perms.setdefault(command, dict(DEFAULT_PERMISSIONS[command]))

        role_id = str(role.id)
        if role_id not in [str(r) for r in cmd_perm.get("allowed_roles", [])]:
            cmd_perm.setdefault("allowed_roles", []).append(role_id)

        try:
            save_config(config)
            await interaction.response.send_message(
                f":white_check_mark: Le rôle **{role.name}** peut maintenant utiliser `/{command}`."
            )
        except Exception as e:
            await interaction.response.send_message(f":x: Erreur : {e}", ephemeral=True)

    @tree.command(name="resetpermission", description="Remet les permissions d'une commande aux valeurs par défaut")
    @app_commands.describe(command="Commande à réinitialiser")
    @app_commands.choices(command=[app_commands.Choice(name=c, value=c) for c in CONFIGURABLE_COMMANDS])
    async def resetpermission_command(interaction: discord.Interaction, command: str):
        if not interaction.guild:
            await interaction.response.send_message(
                ":x: Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                ":x: Seuls les administrateurs peuvent modifier les permissions.", ephemeral=True
            )
            return

        guild_str = str(interaction.guild.id)
        config = load_config()

        perms = config.get("guilds", {}).get(guild_str, {}).get("permissions", {})
        perms.pop(command, None)

        try:
            save_config(config)
            default = DEFAULT_PERMISSIONS[command]
            admin_str = "admin uniquement" if default["admin_only"] else "tout le monde"
            await interaction.response.send_message(
                f":white_check_mark: Permissions de `/{command}` réinitialisées (défaut : {admin_str})."
            )
        except Exception as e:
            await interaction.response.send_message(f":x: Erreur : {e}", ephemeral=True)

    @tree.command(name="listpermissions", description="Affiche les permissions configurées pour ce serveur Discord")
    async def listpermissions_command(interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                ":x: Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                ":x: Seuls les administrateurs peuvent voir les permissions.", ephemeral=True
            )
            return

        config = load_config()
        summary = get_permission_summary(interaction.guild.id, config)

        lines = [":closed_lock_with_key: **Permissions des commandes :**\n"]
        for cmd, perm in summary.items():
            admin_only = perm.get("admin_only", False)
            allowed_roles = perm.get("allowed_roles", [])
            if allowed_roles:
                role_mentions = " ".join(f"<@&{r}>" for r in allowed_roles)
                lines.append(f"• `/{cmd}` — {role_mentions} (+ admins)")
            elif admin_only:
                lines.append(f"• `/{cmd}` — admins uniquement")
            else:
                lines.append(f"• `/{cmd}` — tout le monde")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ── Canal de notification ────────────────────────────────────────────────

    @tree.command(name="setchannel", description="Définit le canal Discord pour les notifications du bot")
    @app_commands.describe(channel="Canal où envoyer les notifications (auto-stop, etc.)")
    async def setchannel_command(interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild:
            await interaction.response.send_message(
                ":x: Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                ":x: Seuls les administrateurs peuvent configurer les canaux.", ephemeral=True
            )
            return

        guild_str = str(interaction.guild.id)
        config = load_config()

        config["guilds"].setdefault(guild_str, {"name": interaction.guild.name, "servers": {}})
        config["guilds"][guild_str]["notification_channel_id"] = channel.id

        try:
            save_config(config)
            await interaction.response.send_message(
                f":white_check_mark: Les notifications seront envoyées dans {channel.mention}."
            )
        except Exception as e:
            await interaction.response.send_message(f":x: Erreur : {e}", ephemeral=True)


async def _run_ssh_setup(
    interaction: discord.Interaction,
    server_key: str,
    port: int,
    name: str,
    instance_id: str,
    region: str,
    version: str = "latest",
) -> None:
    """Lance le setup SSH et envoie un follow-up dans le canal."""
    try:
        jar_url = await ssh_helper.get_jar_url_for_version(version)
    except Exception:
        jar_url = None  # Fallback sur MC_SERVER_JAR_URL par défaut

    success, message = ssh_helper.setup_minecraft_server(server_key, port, jar_url=jar_url)

    if success:
        duckdns_domain = os.getenv("DUCKDNS_DOMAIN")
        extra = ""
        if duckdns_domain:
            full_domain = duckdns_domain if "." in duckdns_domain else f"{duckdns_domain}.duckdns.org"
            extra = f"\nDomaine: `{full_domain}:{port}`"

        sg_info = ""
        try:
            await asyncio.to_thread(manage_sg_port, instance_id, region, port, "authorize")
            sg_info = f""
        except Exception as e:
            sg_info = f"\n:warning: Port `{port}` non ouvert dans le Security Group : {format_boto_error(e, action='ouvrir le port', instance_id=instance_id, region=region)}"

        await interaction.followup.send(
            f":tada: **Installation terminée !**\n\n{message}{extra}{sg_info}\n\n"
            f":point_right: Utilisez `/start` pour démarrer le serveur."
        )
    else:
        await interaction.followup.send(
            f":warning: **Configuration enregistrée mais installation automatique échouée**\n\n"
            f"{message}\n\n"
            f"Créez manuellement le dossier :\n"
            f"```bash\n"
            f"ssh ec2-user@$MC_SERVER_HOST\n"
            f"mkdir -p ~/minecraft-servers/{server_key}\n"
            f"cd ~/minecraft-servers/{server_key}\n"
            f"# Ajouter server.jar, eula.txt et server.properties (port {port})\n"
            f"```"
        )
