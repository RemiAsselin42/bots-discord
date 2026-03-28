"""
Tests pour bot/tasks.py — notify_server_ready et auto_stop_loop.

Stratégie :
- Les appels boto3 (synchrones) sont mockés via MagicMock.
- Les appels mcstatus (async) sont mockés via AsyncMock.
- Le bot Discord est un MagicMock dont get_channel() retourne un canal fictif.
"""
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.tasks import (
    _DEFAULT_IDLE_TIMEOUT,
    _check_and_stop_if_idle,
    _idle_since,
    notify_server_ready,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_bot(channel_send: AsyncMock | None = None) -> MagicMock:
    bot = MagicMock()
    channel = MagicMock()
    channel.send = channel_send or AsyncMock()
    bot.get_channel.return_value = channel
    return bot


def _ec2_state(state: str) -> MagicMock:
    """Retourne un faux client EC2 dont describe_instances retourne l'état donné."""
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"State": {"Name": state}}]}]
    }
    ec2.describe_instance_status.return_value = {
        "InstanceStatuses": [{"InstanceState": {"Name": state}}]
    }
    return ec2


# ── notify_server_ready ───────────────────────────────────────────────────────

async def test_notify_sends_when_running():
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = _ec2_state("running")

    with patch("bot.tasks.get_ec2_client", return_value=ec2):
        await notify_server_ready(
            bot=bot,
            channel_id=42,
            server_name="Survie",
            instance_id="i-0123456789abcdef0",
            region="eu-north-1",
            poll_interval=0,  # pas d'attente en test
        )

    send.assert_awaited_once()
    assert "prêt" in send.call_args[0][0]


async def test_notify_timeout_sends_warning():
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = _ec2_state("pending")  # ne passe jamais à running

    with patch("bot.tasks.get_ec2_client", return_value=ec2):
        await notify_server_ready(
            bot=bot,
            channel_id=42,
            server_name="Survie",
            instance_id="i-0123456789abcdef0",
            region="eu-north-1",
            timeout=0,       # timeout immédiat
            poll_interval=0,
        )

    send.assert_awaited_once()
    assert "démarrer" in send.call_args[0][0]
    assert "AWS" in send.call_args[0][0]


async def test_notify_handles_ec2_exception_gracefully():
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = MagicMock()
    ec2.describe_instances.side_effect = Exception("AWS down")

    with patch("bot.tasks.get_ec2_client", return_value=ec2):
        # Ne doit pas lever d'exception
        await notify_server_ready(
            bot=bot,
            channel_id=42,
            server_name="Survie",
            instance_id="i-0123456789abcdef0",
            region="eu-north-1",
            timeout=0,
            poll_interval=0,
        )


# ── _check_and_stop_if_idle ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_idle_tracker():
    """Remet le tracker d'inactivité à zéro avant chaque test."""
    _idle_since.clear()
    yield
    _idle_since.clear()


def _server_config(duckdns: str | None = "mc-test") -> dict:
    return {
        "name": "Survie",
        "instance_id": "i-0123456789abcdef0",
        "region": "eu-north-1",
        "minecraft_port": "25565",
        "hourly_cost": 0.0416,
        "idle_timeout_minutes": _DEFAULT_IDLE_TIMEOUT,
        "duckdns_domain": duckdns,
    }


async def test_idle_check_skipped_when_instance_stopped():
    bot = _make_bot()
    ec2 = MagicMock()
    ec2.describe_instance_status.return_value = {"InstanceStatuses": []}

    with patch("bot.tasks.get_ec2_client", return_value=ec2):
        await _check_and_stop_if_idle(
            bot=bot,
            guild_str="123",
            server_key="survival",
            server_config=_server_config(),
            notification_channel_id=None,
        )

    ec2.stop_instances.assert_not_called()


async def test_idle_timer_starts_on_zero_players():
    bot = _make_bot()
    ec2 = _ec2_state("running")

    mc_status = MagicMock()
    mc_status.players.online = 0
    mc_server = MagicMock()
    mc_server.async_status = AsyncMock(return_value=mc_status)

    with patch("bot.tasks.get_ec2_client", return_value=ec2), \
         patch("bot.tasks.JavaServer") as mock_java:
        mock_java.lookup.return_value = mc_server
        await _check_and_stop_if_idle(
            bot=bot,
            guild_str="123",
            server_key="survival",
            server_config=_server_config(),
            notification_channel_id=None,
        )

    key = ("123", "survival")
    assert key in _idle_since
    assert _idle_since[key] is not None
    ec2.stop_instances.assert_not_called()


async def test_idle_timer_resets_when_players_join():
    bot = _make_bot()
    ec2 = _ec2_state("running")

    # Pré-remplir le tracker comme si le serveur était déjà inactif
    key = ("123", "survival")
    _idle_since[key] = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)

    mc_status = MagicMock()
    mc_status.players.online = 2  # joueurs connectés
    mc_server = MagicMock()
    mc_server.async_status = AsyncMock(return_value=mc_status)

    with patch("bot.tasks.get_ec2_client", return_value=ec2), \
         patch("bot.tasks.JavaServer") as mock_java:
        mock_java.lookup.return_value = mc_server
        await _check_and_stop_if_idle(
            bot=bot,
            guild_str="123",
            server_key="survival",
            server_config=_server_config(),
            notification_channel_id=None,
        )

    assert _idle_since.get(key) is None
    ec2.stop_instances.assert_not_called()


async def test_auto_stop_triggered_after_timeout():
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = _ec2_state("running")

    key = ("123", "survival")
    # Simuler une inactivité bien au-delà du timeout
    _idle_since[key] = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=60)

    mc_status = MagicMock()
    mc_status.players.online = 0
    mc_server = MagicMock()
    mc_server.async_status = AsyncMock(return_value=mc_status)

    with patch("bot.tasks.get_ec2_client", return_value=ec2), \
         patch("bot.tasks.JavaServer") as mock_java:
        mock_java.lookup.return_value = mc_server
        await _check_and_stop_if_idle(
            bot=bot,
            guild_str="123",
            server_key="survival",
            server_config=_server_config(),
            notification_channel_id=99,
        )

    ec2.stop_instances.assert_called_once_with(InstanceIds=["i-0123456789abcdef0"])
    send.assert_awaited_once()
    assert "Auto-stop" in send.call_args[0][0]
    assert key not in _idle_since


async def test_auto_stop_no_notification_when_no_channel():
    bot = _make_bot()
    ec2 = _ec2_state("running")

    key = ("123", "survival")
    _idle_since[key] = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=60)

    mc_status = MagicMock()
    mc_status.players.online = 0
    mc_server = MagicMock()
    mc_server.async_status = AsyncMock(return_value=mc_status)

    with patch("bot.tasks.get_ec2_client", return_value=ec2), \
         patch("bot.tasks.JavaServer") as mock_java:
        mock_java.lookup.return_value = mc_server
        await _check_and_stop_if_idle(
            bot=bot,
            guild_str="123",
            server_key="survival",
            server_config=_server_config(),
            notification_channel_id=None,  # pas de canal configuré
        )

    ec2.stop_instances.assert_called_once()
    bot.get_channel.assert_not_called()


async def test_idle_check_skipped_on_invalid_instance_id():
    bot = _make_bot()
    ec2 = MagicMock()
    bad_config = {**_server_config(), "instance_id": "invalid"}

    with patch("bot.tasks.get_ec2_client", return_value=ec2):
        await _check_and_stop_if_idle(
            bot=bot,
            guild_str="123",
            server_key="survival",
            server_config=bad_config,
            notification_channel_id=None,
        )

    ec2.describe_instance_status.assert_not_called()
