import asyncio
import logging
import os

import discord
from discord import app_commands
from dotenv import load_dotenv

from bot.commands import admin, control, info, stats
from bot.minecraft_process import setup_host_instance
from bot.tasks import auto_stop_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Enregistrement des commandes par module
control.setup(tree)
info.setup(tree)
admin.setup(tree)
stats.setup(tree)


async def _setup_host() -> None:
    """Lance le setup de l'instance Minecraft Host en arrière-plan au démarrage."""
    if not os.getenv("MC_SERVER_HOST") and not os.getenv("MC_SERVER_INSTANCE_ID"):
        return
    logger.info("[setup_host] Démarrage du setup de l'instance Minecraft Host...")
    success, msg = await asyncio.to_thread(setup_host_instance)
    if success:
        logger.info("[setup_host] %s", msg)
    else:
        logger.error("[setup_host] %s", msg)


@bot.event
async def on_ready():
    logger.info("Bot en cours de connexion...")
    try:
        synced = await tree.sync()
        logger.info("Bot connecté: %s", bot.user)
        logger.info("Commandes synchronisées: %d", len(synced))
        asyncio.create_task(auto_stop_loop(bot))
        asyncio.create_task(_setup_host())
    except Exception as e:
        logger.error("Erreur synchronisation: %s", e)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN manquant dans l'environnement")
    logger.info("Démarrage du bot...")
    bot.run(DISCORD_TOKEN)
