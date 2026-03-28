import discord
from discord import app_commands

from bot.config import get_guild_servers, load_config


async def server_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Propose uniquement les serveurs de la guild courante."""
    if not interaction.guild:
        return []

    servers = get_guild_servers(interaction.guild.id, load_config())
    choices = [
        app_commands.Choice(name=data.get("name", key), value=key)
        for key, data in servers.items()
        if current.lower() in data.get("name", key).lower() or current.lower() in key.lower()
    ]
    return choices[:25]
