import discord
from discord import app_commands
from mcstatus import JavaServer
from mcstatus.responses import JavaStatusResponse

from bot.autocomplete import server_autocomplete
from bot.aws import format_boto_error, get_ec2_client
from bot.commands.helpers import get_uptime_and_cost
from bot.config import get_server_config, load_config


def setup(tree: app_commands.CommandTree) -> None:

    @tree.command(name="cost", description="Affiche le coût réel depuis le démarrage de l'instance")
    @app_commands.describe(server="Sélectionnez le serveur")
    @app_commands.autocomplete(server=server_autocomplete)
    async def cost_command(interaction: discord.Interaction, server: str):
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
        hourly_cost: float = server_config.get("hourly_cost", 0.0416)

        if not isinstance(instance_id, str) or not instance_id.startswith("i-"):
            await interaction.response.send_message(
                "❌ L'ID d'instance configuré est invalide.", ephemeral=True
            )
            return

        try:
            data = get_uptime_and_cost(instance_id, region, hourly_cost)

            if data is None:
                await interaction.response.send_message(f"⚪ Le serveur **{name}** est arrêté. Coût actuel : $0.00")
                return

            if not data["running"]:
                await interaction.response.send_message(
                    f"⚪ Le serveur **{name}** est à l'état **{data['state']}**. Impossible de calculer le coût."
                )
                return

            await interaction.response.send_message(
                f"💰 **Coût - {name}**\n\n"
                f"⏱️ **En ligne depuis:** {data['hours']}h {data['minutes']}min\n"
                f"🔢 **Coût horaire:** ${hourly_cost:.4f}/h\n"
                f"💸 **Coût total actuel:** `${data['cost']:.4f}` (≈ ${data['cost']:.2f})"
            )
        except Exception as e:
            await interaction.response.send_message(
                format_boto_error(e, action="calculer le coût", instance_id=instance_id, region=region),
                ephemeral=True,
            )

    @tree.command(name="players", description="Affiche les joueurs connectés au serveur Minecraft")
    @app_commands.describe(server="Sélectionnez le serveur")
    @app_commands.autocomplete(server=server_autocomplete)
    async def players_command(interaction: discord.Interaction, server: str):
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
        port = int(server_config.get("minecraft_port", "25565"))
        duckdns_domain: str | None = server_config.get("duckdns_domain")

        await interaction.response.defer()

        # Résolution de l'adresse du serveur
        host = _resolve_host(duckdns_domain)
        if host is None:
            # Pas de DuckDNS → on récupère l'IP publique EC2
            instance_id = server_config.get("instance_id")
            region = server_config.get("region", "eu-north-1")

            if not isinstance(instance_id, str) or not instance_id.startswith("i-"):
                await interaction.followup.send(
                    "❌ L'ID d'instance configuré est invalide. Impossible de joindre le serveur.",
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
                    f"⚠️ Le serveur **{name}** n'est pas en cours d'exécution ou n'a pas d'IP publique.\n"
                    f"Démarrez-le d'abord avec `/start {server}`"
                )
                return

        # Ping Minecraft
        try:
            mc = JavaServer.lookup(f"{host}:{port}")
            status: JavaStatusResponse = await mc.async_status()
        except (ConnectionRefusedError, TimeoutError, OSError):
            await interaction.followup.send(
                f"⚠️ Le serveur Minecraft **{name}** ne répond pas sur `{host}:{port}`.\n"
                "Il est peut-être en cours de démarrage, ou le port n'est pas accessible."
            )
            return

        online = status.players.online
        max_players = status.players.max
        sample = status.players.sample or []

        if online == 0:
            msg = f"👥 **{name}** — `0/{max_players}` joueurs connectés."
        else:
            player_names = ", ".join(p.name for p in sample) if sample else "noms non disponibles"
            msg = (
                f"👥 **{name}** — `{online}/{max_players}` joueur(s) connecté(s)\n"
                f"🎮 {player_names}"
            )

        await interaction.followup.send(msg)


def _resolve_host(duckdns_domain: str | None) -> str | None:
    if not duckdns_domain:
        return None
    return duckdns_domain if "." in duckdns_domain else f"{duckdns_domain}.duckdns.org"


def _get_ec2_public_ip(instance_id: str, region: str, name: str, server_key: str) -> str | None:
    ec2 = get_ec2_client(region)
    response = ec2.describe_instances(InstanceIds=[instance_id])
    if not response["Reservations"]:
        return None
    instance = response["Reservations"][0]["Instances"][0]
    if instance["State"]["Name"] != "running":
        return None
    return instance.get("PublicIpAddress")
