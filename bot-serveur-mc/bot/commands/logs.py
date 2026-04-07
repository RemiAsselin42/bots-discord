import asyncio

import discord
from discord import app_commands

from bot.autocomplete import server_autocomplete
from bot.config import get_server_config, load_config
from bot.helpers import require_admin, require_guild
from bot.minecraft_process import MC_SERVER_KEY_PATH, MC_SERVER_USER
from bot.ssh import _resolve_host, get_instance_public_ip, ssh_execute

MAX_LINES = 100
DISCORD_LIMIT = 2000


def _fetch_logs(ssh_host: str, server_key: str, n_lines: int) -> tuple[bool, str]:
    """Récupère les dernières lignes de log du serveur via SSH.

    Essaie logs/latest.log en premier, puis stdout.log en fallback.
    """
    base = f"/home/{MC_SERVER_USER}/minecraft-servers/{server_key}"
    command = (
        f'if [ -f "{base}/logs/latest.log" ]; then '
        f'  tail -n {n_lines} "{base}/logs/latest.log"; '
        f"else "
        f'  tail -n {n_lines} "{base}/stdout.log" 2>/dev/null '
        f'    || echo "(aucun fichier de log trouvé)"; '
        f"fi"
    )
    return ssh_execute(ssh_host, MC_SERVER_USER, MC_SERVER_KEY_PATH, command)


def _split_for_discord(header: str, content: str) -> list[str]:
    """Découpe le contenu en messages Discord de max 2000 caractères.

    Le premier message inclut le header, les suivants sont des blocs seuls.
    """
    lines = content.splitlines()
    messages: list[str] = []
    current: list[str] = []
    first = True

    def _format(chunk: list[str], include_header: bool) -> str:
        block = "```\n" + "\n".join(chunk) + "\n```"
        return f"{header}\n{block}" if include_header else block

    for line in lines:
        candidate = current + [line]
        if len(_format(candidate, first)) > DISCORD_LIMIT and current:
            messages.append(_format(current, first))
            first = False
            current = [line]
        else:
            current = candidate

    if current:
        messages.append(_format(current, first))
    elif not messages:
        messages.append(f"{header}\n```\n(vide)\n```")

    return messages


def setup(tree: app_commands.CommandTree) -> None:

    @tree.command(
        name="logs",
        description="Affiche les dernières lignes de logs de la console du serveur Minecraft",
    )
    @app_commands.describe(
        server="Sélectionnez le serveur",
        number="Nombre de lignes à afficher (max 100)",
    )
    @app_commands.autocomplete(server=server_autocomplete)
    @require_guild
    @require_admin
    async def logs_command(interaction: discord.Interaction, server: str, number: int = 25):
        assert interaction.guild is not None

        n_lines = max(1, min(number, MAX_LINES))

        server_key = server
        server_config = get_server_config(interaction.guild.id, server_key, load_config())
        if not server_config:
            await interaction.response.send_message(
                ":x: Serveur introuvable dans la configuration.", ephemeral=True
            )
            return

        name = server_config.get("name", server_key)
        instance_id = server_config.get("instance_id")
        region = server_config.get("region", "eu-north-1")
        ssh_host = server_config.get("ssh_host") or None

        if not ssh_host and isinstance(instance_id, str) and instance_id.startswith("i-"):
            try:
                ssh_host = await asyncio.to_thread(get_instance_public_ip, instance_id, region)
            except Exception:
                await interaction.response.send_message(
                    f":x: Impossible de résoudre l'hôte SSH pour **{name}** "
                    "(l'instance est peut-être arrêtée).",
                    ephemeral=True,
                )
                return

        try:
            resolved_host = _resolve_host(ssh_host)
        except RuntimeError as e:
            await interaction.response.send_message(f":x: {e}", ephemeral=True)
            return

        await interaction.response.defer()

        success, output = await asyncio.to_thread(_fetch_logs, resolved_host, server_key, n_lines)

        if not success:
            await interaction.followup.send(
                f":x: Impossible de récupérer les logs de **{name}** :\n```\n{output[:1800]}\n```",
                ephemeral=True,
            )
            return

        header = f":scroll: **Logs de {name}** ({n_lines} dernière(s) ligne(s))"
        messages = _split_for_discord(header, output.strip() or "(vide)")

        await interaction.followup.send(messages[0])
        if isinstance(interaction.channel, discord.abc.Messageable):
            for page in messages[1:]:
                await interaction.channel.send(page)
