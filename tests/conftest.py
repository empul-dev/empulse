import asyncio
import os
import pytest
import pytest_asyncio
import aiosqlite

# Use in-memory or temp DB for tests
os.environ["EMBY_URL"] = "http://localhost:8096"
os.environ["EMBY_API_KEY"] = ""
os.environ["DB_PATH"] = ":memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db():
    """Create a fresh in-memory database for each test."""
    from empulse.database import SCHEMA
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()
    yield conn
    await conn.close()


@pytest.fixture
def sample_emby_session_data():
    """Raw Emby session JSON as dict."""
    return {
        "Id": "sess123",
        "UserId": "user1",
        "UserName": "TestUser",
        "Client": "Emby Web",
        "DeviceName": "Chrome",
        "DeviceId": "dev1",
        "RemoteEndPoint": "192.168.1.100",
        "NowPlayingItem": {
            "Id": "item1",
            "Name": "Test Movie",
            "Type": "Movie",
            "ProductionYear": 2024,
            "RunTimeTicks": 72000000000,
        },
        "PlayState": {
            "PositionTicks": 36000000000,
            "IsPaused": False,
            "PlayMethod": "DirectPlay",
        },
        "TranscodingInfo": None,
    }


@pytest.fixture
def sample_emby_episode_data():
    """Raw Emby session JSON for an episode."""
    return {
        "Id": "sess456",
        "UserId": "user2",
        "UserName": "AnotherUser",
        "Client": "Infuse",
        "DeviceName": "Apple TV",
        "DeviceId": "dev2",
        "RemoteEndPoint": "10.0.0.5",
        "NowPlayingItem": {
            "Id": "ep1",
            "Name": "Pilot",
            "Type": "Episode",
            "SeriesName": "Test Show",
            "ParentIndexNumber": 1,
            "IndexNumber": 1,
            "ProductionYear": 2023,
            "RunTimeTicks": 30000000000,
        },
        "PlayState": {
            "PositionTicks": 15000000000,
            "IsPaused": False,
            "PlayMethod": "Transcode",
        },
        "TranscodingInfo": {
            "VideoCodec": "h264",
            "AudioCodec": "aac",
            "TranscodeReasons": ["ContainerNotSupported"],
        },
    }
