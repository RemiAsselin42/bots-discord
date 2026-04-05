import asyncio
import os
import re

import discord
from discord import app_commands

from bot.minecraft_process import edit_minecraft_properties, setup_minecraft_server
from bot.mojang import get_jar_url_for_version, get_player_uuid
from bot.papermc import get_paper_jar_url, get_viaversion_jar_url
from bot.autocomplete import server_autocomplete, version_autocomplete
from botocore.exceptions import ClientError

from bot.aws import format_boto_error, get_ec2_client, get_instance_state, manage_sg_port
from bot.config import load_config, save_config
from bot.helpers import require_guild, resolve_duckdns_host, slugify_name
from bot.permissions import CONFIGURABLE_COMMANDS, DEFAULT_PERMISSIONS, get_permission_summary
from bot.port_manager import assign_bedrock_port, assign_port


class _InstanceStartForPropertiesView(discord.ui.View):
    """Boutons proposant de démarrer l'instance EC2 avant de modifier les propriétés."""

    def __init__(
        self,
        *,
        instance_id: str,
        region: str,
        server_key: str,
        display_name: str,
        motd: str | None,
        max_players: int | None,
        gamemode: str | None,
        ops_to_add: list[tuple[str, str]],
        whitelist_to_add: list[tuple[str, str]],
        icon_url: str | None,
        uuid_errors: list[str],
    ) -> None:
        super().__init__(timeout=120)
        self._instance_id = instance_id
        self._region = region
        self._server_key = server_key
        self._display_name = display_name
        self._motd = motd
        self._max_players = max_players
        self._gamemode = gamemode
        self._ops_to_add = ops_to_add
        self._whitelist_to_add = whitelist_to_add
        self._icon_url = icon_url
        self._uuid_errors = uuid_errors

    def _disable_all(self) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]

    @discord.ui.button(label="Démarrer et modifier", style=discord.ButtonStyle.green, emoji="▶️")
    async def start_and_edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f":arrows_counterclockwise: Démarrage de l'instance…"
        )
        asyncio.create_task(self._start_then_edit(interaction))
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(":information_source: Modification des propriétés annulée.")
        self.stop()

    async def _start_then_edit(self, btn_interaction: discord.Interaction) -> None:
        try:
            ec2 = get_ec2_client(self._region)
            await asyncio.to_thread(ec2.start_instances, InstanceIds=[self._instance_id])
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code != "IncorrectInstanceState":
                await btn_interaction.followup.send(
                    format_boto_error(e, action="démarrer l'instance", instance_id=self._instance_id, region=self._region)
                )
                return
        except Exception as e:
            await btn_interaction.followup.send(
                format_boto_error(e, action="démarrer l'instance", instance_id=self._instance_id, region=self._region)
            )
            return

        for _ in range(30):
            await asyncio.sleep(10)
            state = await asyncio.to_thread(get_instance_state, self._instance_id, self._region)
            if state == "running":
                break
        else:
            await btn_interaction.followup.send(
                f":x: L'instance `{self._instance_id}` n'est pas passée à l'état **running** après 5 minutes.\n"
                "Relancez `/properties` une fois l'instance démarrée."
            )
            return

        await btn_interaction.followup.send(
            f":white_check_mark: Instance démarrée.\n"
            "Attente que SSH soit disponible (30s)…"
        )
        await asyncio.sleep(30)

        success, result = await asyncio.to_thread(
            edit_minecraft_properties,
            self._server_key,
            motd=self._motd,
            max_players=self._max_players,
            gamemode=self._gamemode,
            ops_to_add=self._ops_to_add or None,
            whitelist_to_add=self._whitelist_to_add or None,
            icon_url=self._icon_url,
        )

        if success:
            warning = ""
            if self._motd or self._max_players is not None or self._gamemode:
                warning = f"\n\n:warning: Redémarrez le serveur avec `/restart {self._server_key}` pour appliquer les changements de `server.properties`."
            error_note = ("\n\n:warning: " + "\n".join(self._uuid_errors)) if self._uuid_errors else ""
            await btn_interaction.followup.send(
                f":white_check_mark: Propriétés du serveur **{self._display_name}** mises à jour :\n{result}{warning}{error_note}"
            )
        else:
            await btn_interaction.followup.send(
                f":x: Erreur lors de la modification de **{self._display_name}** :\n{result}"
            )


class _InstanceStartView(discord.ui.View):
    """Boutons proposant de démarrer l'instance EC2 avant l'installation SSH."""

    def __init__(
        self,
        *,
        original_interaction: discord.Interaction,
        server_key: str,
        port: int,
        name: str,
        instance_id: str,
        region: str,
        version: str,
        motd: str | None = None,
        max_players: int = 20,
        gamemode: str = "survival",
        seed: str | None = None,
        icon_url: str | None = None,
        bedrock: bool = False,
        bedrock_port: int | None = None,
    ) -> None:
        super().__init__(timeout=120)
        self._orig = original_interaction
        self._server_key = server_key
        self._port = port
        self._name = name
        self._instance_id = instance_id
        self._region = region
        self._version = version
        self._motd = motd
        self._max_players = max_players
        self._gamemode = gamemode
        self._seed = seed
        self._icon_url = icon_url
        self._bedrock = bedrock
        self._bedrock_port = bedrock_port

    def _disable_all(self) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]

    @discord.ui.button(label="Démarrer et installer", style=discord.ButtonStyle.green, emoji="▶️")
    async def start_and_install(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f":arrows_counterclockwise: Démarrage de l'instance…"
        )
        asyncio.create_task(self._start_then_setup(interaction))
        self.stop()

    @discord.ui.button(label="Installer plus tard", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def install_later(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f":information_source: Installation reportée. Créez manuellement le dossier :\n"
            f"```bash\n"
            f"ssh ec2-user@$MC_SERVER_HOST\n"
            f"mkdir -p ~/minecraft-servers/{self._server_key}\n"
            f"cd ~/minecraft-servers/{self._server_key}\n"
            f"# Ajouter server.jar, eula.txt et server.properties (port {self._port})\n"
            f"```"
        )
        self.stop()

    async def _start_then_setup(self, btn_interaction: discord.Interaction) -> None:
        try:
            ec2 = get_ec2_client(self._region)
            await asyncio.to_thread(ec2.start_instances, InstanceIds=[self._instance_id])
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code != "IncorrectInstanceState":
                await btn_interaction.followup.send(
                    format_boto_error(e, action="démarrer l'instance", instance_id=self._instance_id, region=self._region)
                )
                return
            # IncorrectInstanceState = déjà en cours de démarrage, on poll quand même
        except Exception as e:
            await btn_interaction.followup.send(
                format_boto_error(e, action="démarrer l'instance", instance_id=self._instance_id, region=self._region)
            )
            return

        # Poll jusqu'à "running" (max ~5 min)
        for _ in range(30):
            await asyncio.sleep(10)
            state = await asyncio.to_thread(get_instance_state, self._instance_id, self._region)
            if state == "running":
                break
        else:
            await btn_interaction.followup.send(
                f":x: L'instance `{self._instance_id}` n'est pas passée à l'état **running** après 5 minutes.\n"
                "Relancez `/createserver` une fois l'instance démarrée."
            )
            return

        await btn_interaction.followup.send(
            f":white_check_mark: Instance démarrée.\n"
            "Attente que SSH soit disponible (30s)…"
        )
        await asyncio.sleep(30)
        await _run_ssh_setup(
            self._orig, self._server_key, self._port, self._name, self._instance_id, self._region, self._version,
            motd=self._motd, max_players=self._max_players, gamemode=self._gamemode,
            seed=self._seed, icon_url=self._icon_url,
            bedrock=self._bedrock, bedrock_port=self._bedrock_port,
        )


class _RemoveServerStartForDeleteView(discord.ui.View):
    """Propose de démarrer l'instance stoppée pour pouvoir supprimer les fichiers du serveur."""

    def __init__(
        self,
        *,
        original_interaction: discord.Interaction,
        server_key: str,
        name: str,
        instance_id: str,
        region: str,
        base_result: str,
    ) -> None:
        super().__init__(timeout=120)
        self._orig = original_interaction
        self._server_key = server_key
        self._name = name
        self._instance_id = instance_id
        self._region = region
        self._base_result = base_result

    def _disable_all(self) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]

    @discord.ui.button(label="Démarrer et supprimer", style=discord.ButtonStyle.danger, emoji="▶️")
    async def start_and_delete(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(":arrows_counterclockwise: Démarrage de l'instance…", ephemeral=True)
        asyncio.create_task(self._start_then_delete(interaction))
        self.stop()

    @discord.ui.button(label="Laisser les fichiers", style=discord.ButtonStyle.secondary, emoji="📁")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            self._base_result + "\n:information_source: Les fichiers sur l'instance ont été conservés.",
            ephemeral=True,
        )
        self.stop()

    async def _start_then_delete(self, btn_interaction: discord.Interaction) -> None:
        from bot.aws import get_ec2_client, get_instance_state
        from bot.ssh import get_instance_public_ip
        from botocore.exceptions import ClientError

        try:
            ec2 = get_ec2_client(self._region)
            await asyncio.to_thread(ec2.start_instances, InstanceIds=[self._instance_id])
        except ClientError as e:
            if e.response["Error"]["Code"] != "IncorrectInstanceState":
                await btn_interaction.followup.send(
                    self._base_result
                    + "\n:warning: Impossible de démarrer l'instance : "
                    + format_boto_error(e, action="démarrer l'instance", instance_id=self._instance_id, region=self._region),
                    ephemeral=True,
                )
                return
        except Exception as e:
            await btn_interaction.followup.send(
                self._base_result
                + f"\n:warning: Impossible de démarrer l'instance : {e}",
                ephemeral=True,
            )
            return

        # Poll jusqu'à "running"
        for _ in range(30):
            await asyncio.sleep(10)
            state = await asyncio.to_thread(get_instance_state, self._instance_id, self._region)
            if state == "running":
                break
        else:
            await btn_interaction.followup.send(
                self._base_result
                + f"\n:x: L'instance `{self._instance_id}` n'est pas passée à l'état **running** après 5 minutes.\n"
                "Les fichiers n'ont pas été supprimés.",
                ephemeral=True,
            )
            return

        await btn_interaction.followup.send(":white_check_mark: Instance démarrée. Attente SSH (30s)…", ephemeral=True)
        await asyncio.sleep(30)

        try:
            ssh_host = await asyncio.to_thread(get_instance_public_ip, self._instance_id, self._region)
        except Exception as e:
            await btn_interaction.followup.send(
                self._base_result
                + f"\n:warning: Impossible de récupérer l'IP de l'instance : {e}",
                ephemeral=True,
            )
            return

        delete_view = _RemoveServerDeleteView(
            original_interaction=btn_interaction,
            server_key=self._server_key,
            name=self._name,
            instance_id=self._instance_id,
            region=self._region,
            ssh_host=ssh_host,
            base_result=self._base_result,
        )
        await btn_interaction.followup.send(
            self._base_result
            + f"\n\n:warning: Voulez-vous supprimer les fichiers sur l'instance ?\n"
            f"(`rm -rf ~/minecraft-servers/{self._server_key}`)",
            view=delete_view,
            ephemeral=True,
        )


class _RemoveServerDeleteView(discord.ui.View):
    """Confirmation finale : supprimer les fichiers sur l'instance (rm -rf)."""

    def __init__(
        self,
        *,
        original_interaction: discord.Interaction,
        server_key: str,
        name: str,
        instance_id: str | None,
        region: str,
        ssh_host: str | None,
        base_result: str,
    ) -> None:
        super().__init__(timeout=120)
        self._orig = original_interaction
        self._server_key = server_key
        self._name = name
        self._instance_id = instance_id
        self._region = region
        self._ssh_host = ssh_host
        self._base_result = base_result

    def _disable_all(self) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]

    @discord.ui.button(label="Supprimer les fichiers", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(view=self)
        asyncio.create_task(self._do_delete(interaction))
        self.stop()

    @discord.ui.button(label="Conserver les fichiers", style=discord.ButtonStyle.secondary, emoji="📁")
    async def keep_files(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            self._base_result + "\n:information_source: Les fichiers sur l'instance ont été conservés.",
            ephemeral=True,
        )
        self.stop()

    async def _do_delete(self, btn_interaction: discord.Interaction) -> None:
        from bot.ssh import _resolve_host
        from bot.minecraft_process import MC_SERVER_USER
        from bot.config import load_config
        import os

        _user = MC_SERVER_USER
        _key_path = os.getenv("MC_SERVER_KEY_PATH", "")

        if not _key_path or not self._ssh_host:
            await btn_interaction.followup.send(
                self._base_result
                + "\n:warning: Impossible de supprimer les fichiers : SSH non configuré ou hôte inconnu.",
                ephemeral=True,
            )
            return

        from bot.ssh import ssh_execute
        command = f"rm -rf /home/{_user}/minecraft-servers/{self._server_key}"
        success, output = await asyncio.to_thread(
            ssh_execute, self._ssh_host, _user, _key_path, command, 30
        )

        if success:
            await btn_interaction.followup.send(
                self._base_result
                + f"\n:white_check_mark: Fichiers `~/minecraft-servers/{self._server_key}` supprimés de l'instance.",
                ephemeral=True,
            )
        else:
            await btn_interaction.followup.send(
                self._base_result
                + f"\n:warning: Erreur lors de la suppression des fichiers :\n```\n{output}\n```",
                ephemeral=True,
            )


class _RemoveServerView(discord.ui.View):
    """Confirmation pour supprimer un serveur (avec arrêt Java si nécessaire)."""

    def __init__(
        self,
        *,
        interaction: discord.Interaction,
        server_key: str,
        name: str,
        guild_str: str,
        port: int | None,
        instance_id: str | None,
        region: str,
        ssh_host: str | None,
        java_running: bool,
        bedrock_port: int | None = None,
    ) -> None:
        super().__init__(timeout=120)
        self._orig = interaction
        self._server_key = server_key
        self._name = name
        self._guild_str = guild_str
        self._port = port
        self._instance_id = instance_id
        self._region = region
        self._ssh_host = ssh_host
        self._java_running = java_running
        self._bedrock_port = bedrock_port

        if java_running:
            self.proceed.label = "Arrêter et supprimer"
            self.proceed.emoji = "🛑"
        else:
            self.proceed.label = "Confirmer la suppression"
            self.proceed.emoji = "🗑️"

    def _disable_all(self) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger)
    async def proceed(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(view=self)
        asyncio.create_task(self._do_remove(interaction))
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._disable_all()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(":information_source: Suppression annulée.", ephemeral=True)
        self.stop()

    async def _do_remove(self, btn_interaction: discord.Interaction) -> None:
        from bot.minecraft_process import stop_minecraft_server

        lines: list[str] = []

        # Étape 1 : arrêt du processus Java si nécessaire
        if self._java_running:
            await btn_interaction.followup.send(
                f":arrows_counterclockwise: Arrêt du serveur **{self._name}** en cours…", ephemeral=True
            )
            success, output = await asyncio.to_thread(
                stop_minecraft_server, self._server_key, host=self._ssh_host
            )
            if success:
                lines.append(":red_circle: Processus Java arrêté.")
            else:
                lines.append(f":warning: Impossible d'arrêter le processus Java :\n```\n{output}\n```")

        # Étape 2 : suppression de la config Discord
        config = load_config()
        guild_servers = config.get("guilds", {}).get(self._guild_str, {}).get("servers", {})
        if self._server_key in guild_servers:
            del guild_servers[self._server_key]
            try:
                save_config(config)
                lines.append(":white_check_mark: Configuration Discord supprimée.")
            except Exception as e:
                lines.append(f":warning: Erreur lors de la suppression de la config : {e}")

        # Étape 3 : révocation du port AWS
        if self._port and self._instance_id:
            try:
                await asyncio.to_thread(manage_sg_port, self._instance_id, self._region, self._port, "revoke")
                lines.append(f":white_check_mark: Port `{self._port}` révoqué dans le Security Group.")
            except Exception as e:
                lines.append(
                    f":warning: Port `{self._port}` non révoqué : "
                    + format_boto_error(e, action="révoquer le port", instance_id=self._instance_id, region=self._region)
                )

        # Étape 3b : révocation du port Bedrock UDP
        if self._bedrock_port and self._instance_id:
            try:
                await asyncio.to_thread(manage_sg_port, self._instance_id, self._region, self._bedrock_port, "revoke", "udp")
                lines.append(f":white_check_mark: Port Bedrock `{self._bedrock_port}/udp` révoqué.")
            except Exception as e:
                lines.append(
                    f":warning: Port Bedrock `{self._bedrock_port}/udp` non révoqué : "
                    + format_boto_error(e, action="révoquer le port Bedrock", instance_id=self._instance_id, region=self._region)
                )

        base_result = f":wastebasket: Serveur **{self._name}** (`{self._server_key}`) :\n" + "\n".join(lines)

        # Étape 4 : proposition de supprimer les fichiers sur l'instance
        if self._ssh_host:
            delete_view = _RemoveServerDeleteView(
                original_interaction=btn_interaction,
                server_key=self._server_key,
                name=self._name,
                instance_id=self._instance_id,
                region=self._region,
                ssh_host=self._ssh_host,
                base_result=base_result,
            )
            await btn_interaction.followup.send(
                base_result
                + f"\n\n:warning: Voulez-vous aussi supprimer les fichiers sur l'instance ?\n"
                f"(`rm -rf ~/minecraft-servers/{self._server_key}`)",
                view=delete_view,
                ephemeral=True,
            )
        elif self._instance_id and self._instance_id.startswith("i-"):
            # Instance stoppée : proposer de la démarrer pour pouvoir supprimer les fichiers
            start_view = _RemoveServerStartForDeleteView(
                original_interaction=btn_interaction,
                server_key=self._server_key,
                name=self._name,
                instance_id=self._instance_id,
                region=self._region,
                base_result=base_result,
            )
            await btn_interaction.followup.send(
                base_result
                + f"\n\n:warning: L'instance est arrêtée — impossible de supprimer les fichiers sans la démarrer.\n"
                f"Voulez-vous démarrer l'instance pour supprimer `~/minecraft-servers/{self._server_key}` ?",
                view=start_view,
                ephemeral=True,
            )
        else:
            await btn_interaction.followup.send(
                base_result
                + "\n:information_source: Instance inconnue — les fichiers sur l'instance n'ont pas été supprimés.",
                ephemeral=True,
            )


def setup(tree: app_commands.CommandTree) -> None:

    @tree.command(name="createserver", description="Crée un nouveau serveur Minecraft avec attribution automatique de port")
    @app_commands.describe(
        name="Nom affiché du serveur",
        instance_id="ID de l'instance EC2 AWS (défaut: i-XXXXXXXXXXXXXXXXX)",
        ram="RAM allouée au serveur (ex: 2G, 1536M, 512M) (entiers uniquement)",
        region="Région AWS de l'instance (ex: eu-north-1, eu-west-3, us-east-1)",
        version="Version de Minecraft (ex: 1.21.4, latest)",
        motd="Description affichée dans la liste de serveurs (motd)",
        max_players="Nombre maximum de joueurs (défaut: 20)",
        gamemode="Mode de jeu par défaut",
        seed="Graine de génération du monde",
        icon_url="URL d'une image PNG 64×64 pour l'icône du serveur",
        bedrock="Activer la compatibilité Bedrock (installe Paper + Geyser + Floodgate)",
    )
    @app_commands.choices(gamemode=[
        app_commands.Choice(name="Survie", value="survival"),
        app_commands.Choice(name="Créatif", value="creative"),
        app_commands.Choice(name="Hardcore", value="hardcore"),
    ])
    @app_commands.autocomplete(version=version_autocomplete)
    @require_guild
    async def createserver_command(
        interaction: discord.Interaction,
        name: str,
        instance_id: str = "i-XXXXXXXXXXXXXXXXX",
        ram: str = "1536M",
        region: str = "eu-north-1",
        version: str = "latest",
        motd: str | None = None,
        max_players: int = 20,
        gamemode: str = "survival",
        seed: str | None = None,
        icon_url: str | None = None,
        bedrock: bool = False,
    ):

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
                ":x: Format de RAM invalide. Exemples : `2G`, `1536M`, `512M` (entiers uniquement, pas de décimales).",
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

        bedrock_port = None
        if bedrock:
            try:
                bedrock_port = assign_bedrock_port(config, interaction.guild.id)
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
        if bedrock:
            server_data["bedrock"] = True
            server_data["bedrock_port"] = bedrock_port
        config["guilds"][guild_str]["servers"][key] = server_data

        try:
            save_config(config)
        except Exception as e:
            await interaction.response.send_message(f":x: Erreur lors de la sauvegarde : {e}", ephemeral=True)
            return

        bedrock_info = ""
        if bedrock:
            bedrock_info = (
                f"• Bedrock: activé (port UDP `{bedrock_port}`)\n"
                f"• Moteur: Paper + Geyser + Floodgate + ViaVersion\n"
            )

        base_confirm = (
            f":white_check_mark: Serveur **{name}** enregistré avec succès !\n\n"
            f":clipboard: **Configuration :**\n"
            f"• Nom: `{name}`\n"
            f"• Port Minecraft: `{port}`\n"
            f"• RAM: `{ram_upper}`\n"
            f"• Version: `{version}`\n"
            f"{bedrock_info}"
        )

        instance_state = await asyncio.to_thread(get_instance_state, instance_id, region)

        if instance_state == "running":
            await interaction.response.send_message(
                base_confirm + ":hourglass: **Installation en cours sur l'instance EC2...**"
            )
            asyncio.create_task(_run_ssh_setup(
                interaction, key, port, name, instance_id, region, version,
                motd=motd, max_players=max_players, gamemode=gamemode,
                seed=seed, icon_url=icon_url,
                bedrock=bedrock, bedrock_port=bedrock_port,
            ))
        else:
            state_label = f"**{instance_state}**" if instance_state else "**injoignable**"
            view = _InstanceStartView(
                original_interaction=interaction,
                server_key=key,
                port=port,
                name=name,
                instance_id=instance_id,
                region=region,
                version=version,
                motd=motd,
                max_players=max_players,
                gamemode=gamemode,
                seed=seed,
                icon_url=icon_url,
                bedrock=bedrock,
                bedrock_port=bedrock_port,
            )
            await interaction.response.send_message(
                base_confirm
                + f":warning: L'instance `{instance_id}` est actuellement à l'arrêt.\n"
                "Souhaitez-vous la démarrer pour installer le serveur maintenant ?",
                view=view,
            )

    @tree.command(name="removeserver", description="Supprime un serveur Minecraft de la configuration")
    @app_commands.describe(server="Sélectionnez le serveur à supprimer")
    @app_commands.autocomplete(server=server_autocomplete)
    @require_guild
    async def removeserver_command(interaction: discord.Interaction, server: str):

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
        ssh_host = server_data.get("ssh_host") or None

        # Résoudre l'IP SSH si nécessaire
        from bot.ssh import get_instance_public_ip
        from bot.minecraft_process import is_minecraft_process_running, stop_minecraft_server, MC_SERVER_USER
        if not ssh_host and isinstance(instance_id, str) and instance_id.startswith("i-"):
            try:
                ssh_host = await asyncio.to_thread(get_instance_public_ip, instance_id, region)
            except Exception:
                ssh_host = None

        # Vérifier si le processus Java tourne
        java_running = False
        if ssh_host:
            try:
                _, java_running = await asyncio.to_thread(is_minecraft_process_running, server, host=ssh_host)
            except Exception:
                java_running = False

        bedrock_port = server_data.get("bedrock_port")

        view = _RemoveServerView(
            interaction=interaction,
            server_key=server,
            name=name,
            guild_str=guild_str,
            port=port,
            instance_id=instance_id,
            region=region,
            ssh_host=ssh_host,
            java_running=java_running,
            bedrock_port=bedrock_port,
        )

        if java_running:
            msg = (
                f":warning: Le processus Java de **{name}** est actuellement **en cours d'exécution**.\n\n"
                f"Voulez-vous l'arrêter avant de supprimer le serveur ?"
            )
        else:
            msg = (
                f":wastebasket: Voulez-vous vraiment supprimer le serveur **{name}** (`{server}`) ?\n\n"
                f"• Config Discord : supprimée\n"
                f"• Port `{port}` dans le Security Group AWS : révoqué\n"
                f"• Fichiers sur l'instance (`~/minecraft-servers/{server}`) : à confirmer séparément"
            )

        await interaction.response.send_message(msg, view=view, ephemeral=True)

    @tree.command(name="editserver", description="Modifie la configuration d'un serveur existant")
    @app_commands.describe(
        server="Sélectionnez le serveur à modifier",
        name="Nouveau nom affiché",
        instance_id="Nouvel ID d'instance EC2",
        region="Nouvelle région AWS",
        hourly_cost="Nouveau coût horaire en $",
    )
    @app_commands.autocomplete(server=server_autocomplete)
    @require_guild
    async def editserver_command(
        interaction: discord.Interaction,
        server: str,
        name: str | None = None,
        instance_id: str | None = None,
        region: str | None = None,
        hourly_cost: float | None = None,
    ):

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
    @require_guild
    async def setpermission_command(interaction: discord.Interaction, command: str, role: discord.Role):

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
    @require_guild
    async def resetpermission_command(interaction: discord.Interaction, command: str):

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
    @require_guild
    async def listpermissions_command(interaction: discord.Interaction):

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

    # ── Propriétés Minecraft ─────────────────────────────────────────────────

    @tree.command(name="properties", description="Modifie les propriétés d'un serveur Minecraft existant")
    @app_commands.describe(
        server="Sélectionnez le serveur à modifier",
        motd="Description affichée dans la liste de serveurs (motd)",
        max_players="Nombre maximum de joueurs (ex: 30)",
        gamemode="Mode de jeu par défaut",
        add_admin="Pseudo Minecraft à promouvoir opérateur",
        add_whitelist="Pseudos à ajouter à la whitelist (séparés par virgule)",
        icon_url="URL d'une image PNG 64×64 pour l'icône du serveur",
    )
    @app_commands.choices(gamemode=[
        app_commands.Choice(name="Survie", value="survival"),
        app_commands.Choice(name="Créatif", value="creative"),
        app_commands.Choice(name="Hardcore", value="hardcore"),
    ])
    @app_commands.autocomplete(server=server_autocomplete)
    @require_guild
    async def properties_command(
        interaction: discord.Interaction,
        server: str,
        motd: str | None = None,
        max_players: int | None = None,
        gamemode: str | None = None,
        add_admin: str | None = None,
        add_whitelist: str | None = None,
        icon_url: str | None = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                ":x: Seuls les administrateurs peuvent modifier les propriétés.", ephemeral=True
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
        instance_id = server_data.get("instance_id")
        region = server_data.get("region", "eu-north-1")

        instance_state = await asyncio.to_thread(get_instance_state, instance_id, region)
        if instance_state != "running":
            state_label = f"**{instance_state}**" if instance_state else "**injoignable**"

            # Résoudre les UUIDs Mojang en avance pour les inclure dans la View
            ops_to_add: list[tuple[str, str]] = []
            whitelist_to_add: list[tuple[str, str]] = []
            uuid_errors: list[str] = []

            if add_admin:
                try:
                    uuid, canonical = await get_player_uuid(add_admin.strip())
                    ops_to_add.append((uuid, canonical))
                except ValueError as e:
                    uuid_errors.append(str(e))

            if add_whitelist:
                for raw_name in add_whitelist.split(","):
                    name = raw_name.strip()
                    if not name:
                        continue
                    try:
                        uuid, canonical = await get_player_uuid(name)
                        whitelist_to_add.append((uuid, canonical))
                    except ValueError as e:
                        uuid_errors.append(str(e))

            display_name = server_data.get("name", server)
            view = _InstanceStartForPropertiesView(
                instance_id=instance_id,
                region=region,
                server_key=server,
                display_name=display_name,
                motd=motd,
                max_players=max_players,
                gamemode=gamemode,
                ops_to_add=ops_to_add,
                whitelist_to_add=whitelist_to_add,
                icon_url=icon_url,
                uuid_errors=uuid_errors,
            )
            await interaction.response.send_message(
                f":warning: L'instance `{instance_id}` est actuellement à l'arrêt.\n"
                "Souhaitez-vous la démarrer pour modifier les propriétés maintenant ?",
                view=view,
            )
            return

        # Résoudre les UUIDs Mojang pour ops/whitelist
        ops_to_add: list[tuple[str, str]] = []
        whitelist_to_add: list[tuple[str, str]] = []
        uuid_errors: list[str] = []

        if add_admin:
            try:
                uuid, canonical = await get_player_uuid(add_admin.strip())
                ops_to_add.append((uuid, canonical))
            except ValueError as e:
                uuid_errors.append(str(e))

        if add_whitelist:
            for raw_name in add_whitelist.split(","):
                name = raw_name.strip()
                if not name:
                    continue
                try:
                    uuid, canonical = await get_player_uuid(name)
                    whitelist_to_add.append((uuid, canonical))
                except ValueError as e:
                    uuid_errors.append(str(e))

        if uuid_errors and not motd and max_players is None and gamemode is None and not ops_to_add and not whitelist_to_add and not icon_url:
            await interaction.response.send_message(
                ":x: " + "\n".join(uuid_errors), ephemeral=True
            )
            return

        await interaction.response.defer()

        success, result = await asyncio.to_thread(
            edit_minecraft_properties,
            server,
            motd=motd,
            max_players=max_players,
            gamemode=gamemode,
            ops_to_add=ops_to_add or None,
            whitelist_to_add=whitelist_to_add or None,
            icon_url=icon_url,
        )

        display_name = server_data.get("name", server)
        if success:
            warning = ""
            if motd or max_players is not None or gamemode:
                warning = f"\n\n:warning: Redémarrez le serveur avec `/restart {server}` pour appliquer les changements de `server.properties`."
            error_note = ("\n\n:warning: " + "\n".join(uuid_errors)) if uuid_errors else ""
            await interaction.followup.send(
                f":white_check_mark: Propriétés du serveur **{display_name}** mises à jour :\n{result}{warning}{error_note}"
            )
        else:
            await interaction.followup.send(
                f":x: Erreur lors de la modification de **{display_name}** :\n{result}"
            )

    # ── Canal de notification ────────────────────────────────────────────────

    @tree.command(name="setchannel", description="Définit le canal Discord pour les notifications du bot")
    @app_commands.describe(channel="Canal où envoyer les notifications (auto-stop, etc.)")
    @require_guild
    async def setchannel_command(interaction: discord.Interaction, channel: discord.TextChannel):

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
    *,
    motd: str | None = None,
    max_players: int = 20,
    gamemode: str = "survival",
    seed: str | None = None,
    icon_url: str | None = None,
    bedrock: bool = False,
    bedrock_port: int | None = None,
) -> None:
    """Lance le setup SSH et envoie un follow-up dans le canal."""
    if bedrock and bedrock_port is None:
        await interaction.followup.send(
            ":x: Erreur interne : `bedrock=True` mais aucun `bedrock_port` alloué.", ephemeral=True
        )
        return

    try:
        if bedrock:
            jar_url = await get_paper_jar_url(version)
        else:
            jar_url = await get_jar_url_for_version(version)
    except Exception:
        jar_url = None  # Fallback sur MC_SERVER_JAR_URL par défaut

    viaversion_url: str | None = None
    if bedrock:
        try:
            viaversion_url = await get_viaversion_jar_url()
        except Exception:
            pass  # Le script shell échouera avec un message d'erreur explicite

    success, message = await asyncio.to_thread(
        setup_minecraft_server,
        server_key, port, jar_url=jar_url,
        motd=motd, max_players=max_players, gamemode=gamemode,
        seed=seed, icon_url=icon_url,
        bedrock=bedrock, bedrock_port=bedrock_port,
        viaversion_url=viaversion_url,
    )

    if success:
        duckdns_domain = os.getenv("DUCKDNS_DOMAIN")
        extra = ""
        if duckdns_domain:
            full_domain = resolve_duckdns_host(duckdns_domain)
            extra = f"\nDomaine: `{full_domain}:{port}`"
            if bedrock and bedrock_port:
                extra += f"\nBedrock: `{full_domain}:{bedrock_port}` (UDP)"

        sg_info = ""
        try:
            await asyncio.to_thread(manage_sg_port, instance_id, region, port, "authorize")
            sg_info = f""
        except Exception as e:
            sg_info = f"\n:warning: Port `{port}` non ouvert dans le Security Group : {format_boto_error(e, action='ouvrir le port', instance_id=instance_id, region=region)}"

        if bedrock and bedrock_port:
            try:
                await asyncio.to_thread(manage_sg_port, instance_id, region, bedrock_port, "authorize", "udp")
            except Exception as e:
                sg_info += f"\n:warning: Port Bedrock `{bedrock_port}/udp` non ouvert : {format_boto_error(e, action='ouvrir le port Bedrock', instance_id=instance_id, region=region)}"

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
