"""
Tests pour bot/tasks.py — notify_server_ready et auto_stop_loop.

Stratégie :
- Les appels boto3 (synchrones) sont mockés via MagicMock.
- Les appels mcstatus (async) sont mockés via AsyncMock.
- Les phases SSH et RCON (bot.ssh.*) sont mockées via patch + MagicMock/AsyncMock.
- Le bot Discord est un MagicMock dont get_channel() retourne un canal fictif.
"""

import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.tasks import (
    _DEFAULT_IDLE_TIMEOUT,
    _RCON_READY_RETRIES,
    _RCON_READY_INTERVAL,
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
        "Reservations": [{"Instances": [{"State": {"Name": state}, "PublicIpAddress": "1.2.3.4"}]}]
    }
    ec2.describe_instance_status.return_value = {
        "InstanceStatuses": [{"InstanceState": {"Name": state}}]
    }
    return ec2


# ── notify_server_ready ───────────────────────────────────────────────────────


async def test_notify_sends_when_running():
    """Phase heureuse : EC2 running → SSH OK → MC démarré → RCON OK → message 'prêt'."""
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = _ec2_state("running")

    # asyncio.to_thread est appelé pour : ssh_execute (×1), start_minecraft_process (×1),
    # check_rcon_ready (×1). On retourne un succès pour chaque appel.
    ssh_results = iter([(True, "ok"), (True, "Started PID 1"), (True, "There are 0 players")])

    async def fake_to_thread(fn, *args, **kwargs):
        return next(ssh_results)

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.asyncio.sleep", new=AsyncMock()),
        patch("bot.tasks.asyncio.to_thread", side_effect=fake_to_thread),
        # update_duckdns est maintenant importé en tête de bot.tasks
        patch("bot.tasks.update_duckdns", new=AsyncMock(return_value=True)),
        patch("bot.tasks.MC_SERVER_KEY_PATH", "/fake/key.pem"),
    ):
        await notify_server_ready(
            bot=bot,
            channel_id=42,
            server_name="Survie",
            instance_id="i-0123456789abcdef0",
            region="eu-north-1",
            server_key="survival",
            server_config={"duckdns_domain": "mc-test"},
            poll_interval=0,
        )

    # Le canal doit avoir reçu au moins deux messages :
    # - le message intermédiaire (EC2 active, attente SSH)
    # - le message final "prêt"
    assert send.await_count >= 2
    final_msg = send.call_args_list[-1][0][0]
    assert "prêt" in final_msg


async def test_notify_timeout_sends_warning():
    """EC2 reste en 'pending' → timeout → message d'avertissement AWS."""
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = _ec2_state("pending")  # ne passe jamais à running

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.asyncio.sleep", new=AsyncMock()),
    ):
        await notify_server_ready(
            bot=bot,
            channel_id=42,
            server_name="Survie",
            instance_id="i-0123456789abcdef0",
            region="eu-north-1",
            server_key="survival",
            server_config={},
            timeout=0,  # timeout immédiat
            poll_interval=0,
        )

    send.assert_awaited_once()
    msg = send.call_args[0][0]
    assert "démarrer" in msg
    assert "AWS" in msg


async def test_notify_handles_ec2_exception_gracefully():
    """Exception boto3 → ne doit pas lever d'exception, sort proprement après timeout."""
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = MagicMock()
    ec2.describe_instances.side_effect = Exception("AWS down")

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.asyncio.sleep", new=AsyncMock()),
    ):
        # Ne doit pas lever d'exception
        await notify_server_ready(
            bot=bot,
            channel_id=42,
            server_name="Survie",
            instance_id="i-0123456789abcdef0",
            region="eu-north-1",
            server_key="survival",
            server_config={},
            timeout=0,
            poll_interval=0,
        )


async def test_notify_rcon_timeout_after_mc_started():
    """MC démarré mais RCON ne répond jamais → message d'avertissement RCON timeout."""
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = _ec2_state("running")

    # ssh_execute → SSH ready ; start_minecraft_process → succès ; check_rcon_ready → toujours False
    call_index = 0

    async def fake_to_thread(fn, *args, **kwargs):
        nonlocal call_index
        call_index += 1
        # 1er appel : ssh_execute (check SSH)
        if call_index == 1:
            return (True, "ok")
        # 2e appel : start_minecraft_process
        if call_index == 2:
            return (True, "Started PID 42")
        # Appels suivants : check_rcon_ready → toujours échec
        return (False, "Connection refused")

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.asyncio.sleep", new=AsyncMock()),
        patch("bot.tasks.asyncio.to_thread", side_effect=fake_to_thread),
        # update_duckdns est maintenant importé en tête de bot.tasks
        patch("bot.tasks.update_duckdns", new=AsyncMock(return_value=True)),
        patch("bot.tasks.MC_SERVER_KEY_PATH", "/fake/key.pem"),
    ):
        await notify_server_ready(
            bot=bot,
            channel_id=42,
            server_name="Survie",
            instance_id="i-0123456789abcdef0",
            region="eu-north-1",
            server_key="survival",
            server_config={"duckdns_domain": "mc-test"},
            poll_interval=0,
        )

    # Doit avoir reçu : message intermédiaire + message RCON timeout
    assert send.await_count >= 2
    final_msg = send.call_args_list[-1][0][0]
    assert "RCON" in final_msg
    # Le délai calculé doit correspondre aux constantes
    expected_minutes = _RCON_READY_RETRIES * _RCON_READY_INTERVAL // 60
    assert str(expected_minutes) in final_msg


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

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.JavaServer") as mock_java,
    ):
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

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.JavaServer") as mock_java,
    ):
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

    # asyncio.to_thread appelle stop_minecraft_server puis check_other_mc_servers_running
    to_thread_results = iter([(True, "stopped"), (True, [])])

    async def fake_to_thread_autostop(fn, *args, **kwargs):
        return next(to_thread_results)

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.JavaServer") as mock_java,
        patch("bot.tasks.asyncio.to_thread", side_effect=fake_to_thread_autostop),
    ):
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

    to_thread_results = iter([(True, "stopped"), (True, [])])

    async def fake_to_thread_autostop(fn, *args, **kwargs):
        return next(to_thread_results)

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.JavaServer") as mock_java,
        patch("bot.tasks.asyncio.to_thread", side_effect=fake_to_thread_autostop),
    ):
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


# ── Logique zombie (MC injoignable) ──────────────────────────────────────────


async def test_zombie_ssh_unreachable_instance_preserved():
    """Branche zombie 1 : SSH injoignable → is_minecraft_process_running retourne (False, False)
    → instance conservée (on ne sait pas si Java tourne)."""
    bot = _make_bot()
    ec2 = _ec2_state("running")

    mc_server = MagicMock()
    mc_server.async_status = AsyncMock(side_effect=Exception("Connection refused"))

    async def fake_to_thread(fn, *args, **kwargs):
        # SSH injoignable : ssh_ok=False
        return (False, False)

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.JavaServer") as mock_java,
        patch("bot.tasks.asyncio.to_thread", side_effect=fake_to_thread),
    ):
        mock_java.lookup.return_value = mc_server
        await _check_and_stop_if_idle(
            bot=bot,
            guild_str="123",
            server_key="survival",
            server_config=_server_config(),
            notification_channel_id=None,
        )

    ec2.stop_instances.assert_not_called()


async def test_zombie_java_running_instance_preserved():
    """Branche zombie 2 : SSH ok mais Java toujours en cours d'exécution
    → serveur en démarrage, instance conservée sans arrêt."""
    bot = _make_bot()
    ec2 = _ec2_state("running")

    mc_server = MagicMock()
    mc_server.async_status = AsyncMock(side_effect=asyncio.TimeoutError())

    async def fake_to_thread(fn, *args, **kwargs):
        # SSH ok, Java tourne encore
        return (True, True)

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.JavaServer") as mock_java,
        patch("bot.tasks.asyncio.to_thread", side_effect=fake_to_thread),
    ):
        mock_java.lookup.return_value = mc_server
        await _check_and_stop_if_idle(
            bot=bot,
            guild_str="123",
            server_key="survival",
            server_config=_server_config(),
            notification_channel_id=None,
        )

    ec2.stop_instances.assert_not_called()


async def test_zombie_other_servers_active_instance_preserved():
    """Branche zombie 3 : SSH ok, Java arrêté, mais d'autres serveurs MC tournent
    → instance conservée."""
    bot = _make_bot()
    ec2 = _ec2_state("running")

    mc_server = MagicMock()
    mc_server.async_status = AsyncMock(side_effect=Exception("Connection refused"))

    call_index = 0

    async def fake_to_thread(fn, *args, **kwargs):
        nonlocal call_index
        call_index += 1
        if call_index == 1:
            # is_minecraft_process_running : SSH ok, Java arrêté
            return (True, False)
        # check_other_mc_servers_running : check réussi, autres serveurs actifs
        return (True, ["creative"])

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.JavaServer") as mock_java,
        patch("bot.tasks.asyncio.to_thread", side_effect=fake_to_thread),
    ):
        mock_java.lookup.return_value = mc_server
        await _check_and_stop_if_idle(
            bot=bot,
            guild_str="123",
            server_key="survival",
            server_config=_server_config(),
            notification_channel_id=None,
        )

    ec2.stop_instances.assert_not_called()


async def test_zombie_no_other_servers_instance_stopped():
    """Branche zombie 4 (nominale) : SSH ok, Java arrêté, aucun autre serveur actif
    → instance EC2 arrêtée et notification envoyée."""
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = _ec2_state("running")

    mc_server = MagicMock()
    mc_server.async_status = AsyncMock(side_effect=Exception("Connection refused"))

    call_index = 0

    async def fake_to_thread(fn, *args, **kwargs):
        nonlocal call_index
        call_index += 1
        if call_index == 1:
            # is_minecraft_process_running : SSH ok, Java arrêté
            return (True, False)
        # check_other_mc_servers_running : check réussi, aucun autre serveur
        return (True, [])

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.JavaServer") as mock_java,
        patch("bot.tasks.asyncio.to_thread", side_effect=fake_to_thread),
    ):
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
    msg = send.call_args[0][0]
    assert "zombie" in msg.lower()
    assert "Auto-stop" in msg
