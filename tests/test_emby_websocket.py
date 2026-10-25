import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from empulse.emby.websocket import EmbyWebSocket


@pytest.mark.parametrize(
    "message_type",
    [
        "PlaybackStart",
        "PlaybackStopped",
        "PlaybackProgress",
        "SessionEnded",
        "Play",
        "Playstate",
    ],
)
async def test_playback_events_trigger_poll(monkeypatch, message_type):
    connection = AsyncMock()
    connection.__aenter__.return_value.__aiter__.return_value = [
        "invalid JSON",
        json.dumps({"MessageType": "KeepAlive"}),
        json.dumps({"MessageType": message_type}),
    ]
    monkeypatch.setattr(
        "empulse.emby.websocket.websockets.connect", Mock(return_value=connection)
    )
    poller = AsyncMock()

    await EmbyWebSocket(poller)._connect()

    poller.trigger_poll.assert_awaited_once_with()


async def test_connection_failure_retries_and_cancellation_stops_listener(monkeypatch):
    listener = EmbyWebSocket(AsyncMock())
    connect = AsyncMock(side_effect=[OSError("disconnected"), asyncio.CancelledError()])
    sleep = AsyncMock()
    monkeypatch.setattr(listener, "_connect", connect)
    monkeypatch.setattr("empulse.emby.websocket.asyncio.sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await listener.run()

    assert connect.await_count == 2
    sleep.assert_awaited_once_with(5)
