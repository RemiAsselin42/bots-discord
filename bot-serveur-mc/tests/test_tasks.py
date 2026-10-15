"""
Tests pour bot/tasks.py — notify_server_ready et auto_stop_loop.

Stratégie :
- Les appels boto3 (synchrones) sont mockés via MagicMock.
- Les appels SSH/RCON (asyncio.to_thread) sont rejoués dans l'ordre d'appel.
- Le bot Discord est un MagicMock dont get_channel() retourne un canal fictif.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from bot.tasks import (
    _DEFAULT_IDLE_TIMEOUT,
    _RCON_READY_INTERVAL,
    _RCON_READY_RETRIES,
    _check_and_stop_if_idle,
    _idle_since,
    notify_server_ready,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_bot(channel_send: AsyncMock | None = None) -> MagicMock:
    bot = MagicMock()
    channel = MagicMock(spec=discord.abc.Messageable)
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


KEY = ("123", "survival")
IP = "1.2.3.4"  # PublicIpAddress servie par _ec2_state()
NO_PLAYERS = (True, "There are 0 of a max of 20 players online: ")
TWO_PLAYERS = (True, "There are 2 of a max of 20 players online: Alice, Bob")
RCON_DOWN = (False, "Connection refused")


def _server_config() -> dict:
    return {
        "name": "Survie",
        "instance_id": "i-0123456789abcdef0",
        "region": "eu-north-1",
        "minecraft_port": "25565",
        "hourly_cost": 0.0416,
        "idle_timeout_minutes": _DEFAULT_IDLE_TIMEOUT,
    }


def _idle_for(minutes: int) -> None:
    """Pré-remplit le tracker comme si « survival » était inactif depuis `minutes`."""
    _idle_since[KEY] = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        minutes=minutes
    )


async def _run(
    bot: MagicMock,
    ec2: MagicMock,
    results: list,
    notification_channel_id: int | None = None,
    server_config: dict | None = None,
) -> list[tuple[str, dict]]:
    """Exécute un cycle auto-stop pour « survival ».

    `results` est rejoué dans l'ordre des appels asyncio.to_thread (RCON list, pgrep,
    stop, check_other…) ; un appel de trop lève StopIteration et fait échouer le test.
    Retourne la liste (nom_fonction, kwargs) des appels effectués.
    """
    calls: list[tuple[str, dict]] = []
    it = iter(results)

    async def fake_to_thread(fn, *args, **kwargs):
        calls.append((fn.__name__, kwargs))
        return next(it)

    with (
        patch("bot.tasks.get_ec2_client", return_value=ec2),
        patch("bot.tasks.asyncio.to_thread", side_effect=fake_to_thread),
    ):
        await _check_and_stop_if_idle(
            bot=bot,
            guild_str="123",
            server_key="survival",
            server_config=server_config or _server_config(),
            notification_channel_id=notification_channel_id,
        )
    return calls


async def test_idle_check_skipped_when_instance_stopped():
    bot = _make_bot()
    ec2 = MagicMock()
    ec2.describe_instance_status.return_value = {"InstanceStatuses": []}

    calls = await _run(bot, ec2, [])

    assert calls == []
    ec2.stop_instances.assert_not_called()


async def test_idle_check_skipped_on_invalid_instance_id():
    bot = _make_bot()
    ec2 = MagicMock()
    bad_config = {**_server_config(), "instance_id": "invalid"}

    await _run(bot, ec2, [], server_config=bad_config)

    ec2.describe_instance_status.assert_not_called()


async def test_skipped_when_no_public_ip():
    """Pas d'IP publique → état inconnu : ni appel SSH, ni arrêt, compteur intact."""
    bot = _make_bot()
    ec2 = _ec2_state("running")
    ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"State": {"Name": "running"}}]}]
    }
    _idle_for(60)

    calls = await _run(bot, ec2, [])

    assert calls == []
    ec2.stop_instances.assert_not_called()
    assert _idle_since[KEY] is not None


async def test_idle_timer_starts_on_zero_players():
    bot = _make_bot()
    ec2 = _ec2_state("running")

    await _run(bot, ec2, [NO_PLAYERS])

    assert _idle_since.get(KEY) is not None
    ec2.stop_instances.assert_not_called()


async def test_idle_timer_resets_when_players_join():
    bot = _make_bot()
    ec2 = _ec2_state("running")
    _idle_for(10)

    await _run(bot, ec2, [TWO_PLAYERS])

    assert _idle_since.get(KEY) is None
    ec2.stop_instances.assert_not_called()


async def test_players_online_block_auto_stop_past_timeout():
    """`list` RCON annonce des joueurs → jamais d'arrêt, même compteur d'inactivité dépassé."""
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = _ec2_state("running")
    _idle_for(60)

    calls = await _run(bot, ec2, [TWO_PLAYERS], notification_channel_id=99)

    ec2.stop_instances.assert_not_called()
    assert _idle_since.get(KEY) is None
    send.assert_not_awaited()
    assert [n for n, _ in calls] == ["check_rcon_ready"]


async def test_rcon_ok_unparsable_output_no_timer():
    """RCON répond mais sans compte de joueurs (mcrcon absent) → inconnu : compteur remis à zéro."""
    bot = _make_bot()
    ec2 = _ec2_state("running")
    _idle_for(60)

    calls = await _run(bot, ec2, [(True, "RCON port ouvert (mcrcon absent)")])

    ec2.stop_instances.assert_not_called()
    assert _idle_since.get(KEY) is None
    assert [n for n, _ in calls] == ["check_rcon_ready"]


async def test_auto_stop_triggered_after_timeout():
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = _ec2_state("running")
    _idle_for(60)

    calls = await _run(
        bot, ec2, [NO_PLAYERS, (True, "stopped"), (True, [])], notification_channel_id=99
    )

    ec2.stop_instances.assert_called_once_with(InstanceIds=["i-0123456789abcdef0"])
    send.assert_awaited_once()
    assert "Auto-stop" in send.call_args[0][0]
    assert KEY not in _idle_since
    assert [n for n, _ in calls] == [
        "check_rcon_ready",
        "stop_minecraft_server",
        "check_other_mc_servers_running",
    ]


async def test_auto_stop_no_notification_when_no_channel():
    bot = _make_bot()
    ec2 = _ec2_state("running")
    _idle_for(60)

    await _run(bot, ec2, [NO_PLAYERS, (True, "stopped"), (True, [])])

    ec2.stop_instances.assert_called_once()
    bot.get_channel.assert_not_called()


async def test_ssh_calls_target_server_instance_ip():
    """Tous les appels SSH visent l'IP publique de l'instance du serveur, pas le fallback global."""
    bot = _make_bot()
    ec2 = _ec2_state("running")
    _idle_for(60)

    calls = await _run(bot, ec2, [NO_PLAYERS, (True, "stopped"), (True, [])])

    ec2.describe_instances.assert_called_with(InstanceIds=["i-0123456789abcdef0"])
    assert all(kw.get("host") == IP for _, kw in calls)
    assert [n for n, _ in calls] == [
        "check_rcon_ready",
        "stop_minecraft_server",
        "check_other_mc_servers_running",
    ]


# ── Logique zombie (RCON injoignable) ────────────────────────────────────────


async def test_zombie_ssh_unreachable_instance_preserved():
    """Branche zombie 1 : SSH injoignable → is_minecraft_process_running retourne (False, False)
    → instance conservée (on ne sait pas si Java tourne)."""
    bot = _make_bot()
    ec2 = _ec2_state("running")

    await _run(bot, ec2, [RCON_DOWN, (False, False)])

    ec2.stop_instances.assert_not_called()


async def test_zombie_java_running_instance_preserved():
    """Branche zombie 2 : SSH ok mais Java toujours en cours d'exécution
    → serveur en démarrage, instance conservée sans arrêt."""
    bot = _make_bot()
    ec2 = _ec2_state("running")

    await _run(bot, ec2, [RCON_DOWN, (True, True)])

    ec2.stop_instances.assert_not_called()


async def test_zombie_other_servers_active_instance_preserved():
    """Branche zombie 3 : SSH ok, Java arrêté, mais d'autres serveurs MC tournent
    → instance conservée."""
    bot = _make_bot()
    ec2 = _ec2_state("running")

    await _run(bot, ec2, [RCON_DOWN, (True, False), (True, ["creative"])])

    ec2.stop_instances.assert_not_called()


async def test_zombie_no_other_servers_instance_stopped():
    """Branche zombie 4 (nominale) : SSH ok, Java arrêté, aucun autre serveur actif
    → instance EC2 arrêtée et notification envoyée."""
    send = AsyncMock()
    bot = _make_bot(send)
    ec2 = _ec2_state("running")

    calls = await _run(bot, ec2, [RCON_DOWN, (True, False), (True, [])], notification_channel_id=99)

    ec2.stop_instances.assert_called_once_with(InstanceIds=["i-0123456789abcdef0"])
    send.assert_awaited_once()
    msg = send.call_args[0][0]
    assert "zombie" in msg.lower()
    assert "Auto-stop" in msg
    assert all(kw.get("host") == IP for _, kw in calls)
    assert [n for n, _ in calls] == [
        "check_rcon_ready",
        "is_minecraft_process_running",
        "check_other_mc_servers_running",
    ]
