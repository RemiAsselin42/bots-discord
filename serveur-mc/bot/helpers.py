import re


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
