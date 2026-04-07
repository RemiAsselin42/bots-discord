import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Les modules sont importés depuis le package bot/
from bot.aws import format_boto_error
from bot.config import get_guild_servers, get_server_config, load_config
from bot.helpers import calculate_monthly_cost, format_uptime, is_valid_instance_id, slugify_name
from bot.permissions import check_permission, get_permission_summary
from bot.port_manager import (
    BEDROCK_PORT_RANGE_END,
    BEDROCK_PORT_RANGE_START,
    PORT_RANGE_END,
    PORT_RANGE_START,
    assign_bedrock_port,
    assign_port,
    get_available_bedrock_port,
    get_available_port,
)

SAMPLE_CONFIG = {
    "guilds": {
        "123456789": {
            "name": "Test Discord",
            "servers": {
                "survival": {
                    "name": "Survie",
                    "instance_id": "i-0123456789abcdef0",
                    "region": "eu-north-1",
                    "hourly_cost": 0.0416,
                    "minecraft_port": "25565",
                }
            },
        }
    }
}


# ── format_boto_error ────────────────────────────────────────────────────────


def test_format_boto_error_no_credentials():
    from botocore.exceptions import NoCredentialsError

    result = format_boto_error(NoCredentialsError(), action="test")
    assert "Identifiants AWS introuvables" in result
    assert "test" in result


def test_format_boto_error_instance_not_found():
    from botocore.exceptions import ClientError

    error = ClientError(
        {"Error": {"Code": "InvalidInstanceID.NotFound", "Message": "Instance not found"}},
        "DescribeInstances",
    )
    result = format_boto_error(error, action="test", instance_id="i-123", region="eu-west-1")
    assert "n'a pas été trouvée" in result
    assert "eu-west-1" in result


def test_format_boto_error_unauthorized():
    from botocore.exceptions import ClientError

    error = ClientError(
        {"Error": {"Code": "UnauthorizedOperation", "Message": "Unauthorized"}},
        "StartInstances",
    )
    result = format_boto_error(error, action="test")
    assert "Permissions AWS insuffisantes" in result


def test_format_boto_error_incorrect_state():
    from botocore.exceptions import ClientError

    error = ClientError(
        {"Error": {"Code": "IncorrectInstanceState", "Message": "State incorrect"}},
        "StopInstances",
    )
    result = format_boto_error(error, action="test")
    assert "état qui ne permet pas l'opération" in result


# ── config helpers ───────────────────────────────────────────────────────────


def test_get_guild_servers_returns_servers():
    result = get_guild_servers(123456789, SAMPLE_CONFIG)
    assert "survival" in result
    assert result["survival"]["name"] == "Survie"


def test_get_guild_servers_unknown_guild():
    result = get_guild_servers(999999999, SAMPLE_CONFIG)
    assert result == {}


def test_get_server_config_returns_server():
    result = get_server_config(123456789, "survival", SAMPLE_CONFIG)
    assert result is not None
    assert result["instance_id"] == "i-0123456789abcdef0"


def test_get_server_config_unknown_server():
    result = get_server_config(123456789, "unknown", SAMPLE_CONFIG)
    assert result is None


def test_load_and_save_config_roundtrip():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, dir=".") as f:
        json.dump(SAMPLE_CONFIG, f)
        temp_name = f.name

    # Remplace temporairement le fichier cible de load_config
    original_open = open

    def patched_open(path, *args, **kwargs):
        if path == "servers_config.json":
            return original_open(temp_name, *args, **kwargs)
        return original_open(path, *args, **kwargs)

    try:
        with patch("builtins.open", side_effect=patched_open):
            data = load_config()
        assert data["guilds"]["123456789"]["name"] == "Test Discord"
    finally:
        os.unlink(temp_name)


# ── helpers ──────────────────────────────────────────────────────────────────


def test_instance_id_validation_valid():
    assert is_valid_instance_id("i-0123456789abcdef0") is True
    assert is_valid_instance_id("i-abc123def456789ab") is True


def test_instance_id_validation_invalid():
    assert is_valid_instance_id("i-0123456789abcdef") is False
    assert is_valid_instance_id("invalid") is False
    assert is_valid_instance_id("") is False
    assert is_valid_instance_id(None) is False


def test_slugify_server_name():
    assert slugify_name("Mon Serveur") == "mon-serveur"
    assert slugify_name("Serveur 1") == "serveur-1"
    assert slugify_name("Test@Serveur!") == "testserveur"
    assert slugify_name("  Spaces  ") == "spaces"


def test_calculate_monthly_cost():
    assert calculate_monthly_cost(0.0416, 720) == pytest.approx(29.952, rel=0.01)
    assert calculate_monthly_cost(0.0832, 0) == 0


def test_format_uptime():
    assert "2h" in format_uptime(7200)
    assert "30min" in format_uptime(1800)
    assert "1j" in format_uptime(86400)


# ── permissions ──────────────────────────────────────────────────────────────


def _make_interaction(is_admin: bool, role_ids: list[int] | None = None) -> MagicMock:
    """Crée un faux objet Interaction Discord."""
    interaction = MagicMock()
    interaction.guild = MagicMock()
    interaction.user.guild_permissions.administrator = is_admin
    roles = []
    for rid in role_ids or []:
        r = MagicMock()
        r.id = rid
        roles.append(r)
    interaction.user.roles = roles
    return interaction


def test_permission_admin_always_allowed():
    interaction = _make_interaction(is_admin=True)
    assert check_permission(interaction, "stop", SAMPLE_CONFIG) is True


def test_permission_stop_default_denied_for_non_admin():
    interaction = _make_interaction(is_admin=False)
    assert check_permission(interaction, "stop", SAMPLE_CONFIG) is False


def test_permission_start_default_allowed_for_everyone():
    interaction = _make_interaction(is_admin=False)
    assert check_permission(interaction, "start", SAMPLE_CONFIG) is True


def test_permission_allowed_role_grants_access():
    role_id = 999
    config = {
        "guilds": {
            "123456789": {
                "name": "Test",
                "servers": {},
                "permissions": {"stop": {"admin_only": True, "allowed_roles": [str(role_id)]}},
            }
        }
    }
    interaction = _make_interaction(is_admin=False, role_ids=[role_id])
    interaction.guild.id = 123456789
    assert check_permission(interaction, "stop", config) is True


def test_permission_wrong_role_denied():
    config = {
        "guilds": {
            "123456789": {
                "name": "Test",
                "servers": {},
                "permissions": {"stop": {"admin_only": True, "allowed_roles": ["111"]}},
            }
        }
    }
    interaction = _make_interaction(is_admin=False, role_ids=[999])
    interaction.guild.id = 123456789
    assert check_permission(interaction, "stop", config) is False


def test_get_permission_summary_uses_defaults_when_no_config():
    summary = get_permission_summary(123456789, SAMPLE_CONFIG)
    assert summary["start"]["admin_only"] is False
    assert summary["stop"]["admin_only"] is True


# ── port_manager ─────────────────────────────────────────────────────────────


def _config_with_ports(java_ports: list[int], bedrock_ports: list[int]) -> dict:
    """Construit une config avec des serveurs occupant les ports donnés."""
    servers = {}
    for i, jp in enumerate(java_ports):
        entry = {"port": jp}
        if i < len(bedrock_ports):
            entry["bedrock_port"] = bedrock_ports[i]
        servers[f"server-{i}"] = entry
    return {"guilds": {"1": {"servers": servers}}}


def test_get_available_port_returns_first_free():
    config = _config_with_ports([PORT_RANGE_START], [])
    port = get_available_port(config, 1)
    assert port == PORT_RANGE_START + 1


def test_get_available_port_empty_config():
    config = {"guilds": {}}
    assert get_available_port(config, 1) == PORT_RANGE_START


def test_get_available_port_all_taken():
    all_ports = list(range(PORT_RANGE_START, PORT_RANGE_END + 1))
    config = _config_with_ports(all_ports, [])
    assert get_available_port(config, 1) is None


def test_assign_port_raises_when_exhausted():
    all_ports = list(range(PORT_RANGE_START, PORT_RANGE_END + 1))
    config = _config_with_ports(all_ports, [])
    with pytest.raises(ValueError, match="Aucun port disponible"):
        assign_port(config, 1)


def test_get_available_bedrock_port_returns_first_free():
    config = _config_with_ports([], [BEDROCK_PORT_RANGE_START])
    port = get_available_bedrock_port(config, 1)
    assert port == BEDROCK_PORT_RANGE_START + 1


def test_get_available_bedrock_port_empty_config():
    config = {"guilds": {}}
    assert get_available_bedrock_port(config, 1) == BEDROCK_PORT_RANGE_START


def test_get_available_bedrock_port_all_taken():
    all_ports = list(range(BEDROCK_PORT_RANGE_START, BEDROCK_PORT_RANGE_END + 1))
    config = _config_with_ports([], all_ports)
    assert get_available_bedrock_port(config, 1) is None


def test_assign_bedrock_port_raises_when_exhausted():
    all_ports = list(range(BEDROCK_PORT_RANGE_START, BEDROCK_PORT_RANGE_END + 1))
    config = _config_with_ports([], all_ports)
    with pytest.raises(ValueError, match="Aucun port Bedrock disponible"):
        assign_bedrock_port(config, 1)


def test_bedrock_ports_isolated_from_java_ports():
    """Les ports Bedrock et Java sont indépendants : un port Java plein n'affecte pas Bedrock."""
    all_java = list(range(PORT_RANGE_START, PORT_RANGE_END + 1))
    config = _config_with_ports(all_java, [])
    # Java épuisé, mais Bedrock doit rester disponible
    assert get_available_bedrock_port(config, 1) == BEDROCK_PORT_RANGE_START


def test_assign_port_ignores_other_guilds():
    """Les ports d'une autre guild ne bloquent pas l'allocation."""
    config = {
        "guilds": {
            "1": {"servers": {"s": {"port": PORT_RANGE_START}}},
            "2": {"servers": {}},
        }
    }
    # Guild 2 n'a aucun serveur, le premier port doit être libre
    assert assign_port(config, 2) == PORT_RANGE_START
