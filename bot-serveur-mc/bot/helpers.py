import functools
import re
from typing import Any, Callable, Coroutine, TypeVar

import discord


def is_valid_instance_id(instance_id: str | None) -> bool:
    if not instance_id or not isinstance(instance_id, str):
        return False
    return instance_id.startswith("i-") and len(instance_id) == 19


def slugify_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]", "", name.strip().lower().replace(" ", "-"))
    return slug.strip("-")


def calculate_monthly_cost(hourly_cost: float, hours: int) -> float:
    return hourly_cost * hours


def format_uptime(seconds: int) -> str:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60

    parts = []
    if days > 0:
        parts.append(f"{days}j")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or not parts:
        parts.append(f"{minutes}min")

    return " ".join(parts)


def resolve_duckdns_host(domain: str) -> str:
    """Retourne le FQDN DuckDNS complet (ajoute '.duckdns.org' si nécessaire)."""
    return domain if "." in domain else f"{domain}.duckdns.org"


F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, None]])


def require_guild(func: F) -> F:
    """Décorateur qui bloque un app_command utilisé hors d'un serveur Discord.

    Préserve __annotations__ pour que discord.py puisse inspecter les paramètres
    slash et les enregistrer correctement.
    """

    @functools.wraps(func)
    async def wrapper(interaction: discord.Interaction, *args: Any, **kwargs: Any) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                ":x: Cette commande ne peut être utilisée que dans un serveur Discord.",
                ephemeral=True,
            )
            return
        await func(interaction, *args, **kwargs)

    wrapper.__annotations__ = func.__annotations__  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]


def require_admin(func: F) -> F:
    """Décorateur qui réserve un app_command aux administrateurs du serveur Discord.

    Doit être appliqué après @require_guild (ou combiné avec lui) puisqu'il
    accède à interaction.user.guild_permissions.
    Préserve __annotations__ pour que discord.py enregistre correctement les
    paramètres slash.
    """

    @functools.wraps(func)
    async def wrapper(interaction: discord.Interaction, *args: Any, **kwargs: Any) -> None:
        if not interaction.user.guild_permissions.administrator:  # type: ignore[union-attr]
            await interaction.response.send_message(
                ":x: Cette commande est réservée aux administrateurs.",
                ephemeral=True,
            )
            return
        await func(interaction, *args, **kwargs)

    wrapper.__annotations__ = func.__annotations__  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]
