"""Local vs Remote chart: IP classification, daily aggregation, endpoint privacy."""

import json
from datetime import datetime, timezone

import pytest

from empulse.db import history as history_db, stats as stats_db
from empulse.period import Period, ip_scope

NOON = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "ip,scope",
    [
        ("10.1.2.3", "lan"),
        ("172.16.0.1", "lan"),
        ("172.31.255.255", "lan"),
        ("172.32.0.1", "remote"),
        ("192.168.1.5", "lan"),
        ("127.0.0.1", "lan"),
        ("169.254.10.1", "lan"),
        ("100.64.0.1", "remote"),  # CGNAT / Tailscale: traffic leaves the LAN
        ("::1", "lan"),
        ("fe80::1", "lan"),
        ("fe80::1%eth0", "lan"),
        ("fd00::1", "lan"),
        ("::ffff:192.168.1.5", "lan"),
        ("::ffff:8.8.8.8", "remote"),
        ("8.8.8.8", "remote"),
        ("2001:4860:4860::8888", "remote"),
        ("192.168.1.5:54321", "lan"),
        ("8.8.8.8:443", "remote"),
        ("[::1]:8096", "lan"),
        ("[2001:4860:4860::8888]:8096", "remote"),
        (" 10.0.0.1 ", "lan"),
        ("", "unknown"),
        (None, "unknown"),
        ("garbage", "unknown"),
        ("999.1.1.1", "unknown"),
    ],
)
def test_ip_scope(ip, scope):
    assert ip_scope(ip) == scope


_n = 0


async def play(db, started_at: str, ip: str | None, bitrate: int | None = None):
    global _n
    _n += 1
    await history_db.insert_history(
        db,
        {
            "session_key": f"loc{_n}",
            "user_id": "u1",
            "user_name": "Alice",
            "item_id": "i1",
            "item_name": "Film",
            "item_type": "Movie",
            "started_at": started_at,
            "stopped_at": started_at,
            "duration_seconds": 3600,
            "play_method": "DirectPlay",
            "ip_address": ip,
            "stream_info": json.dumps({"media": {"bitrate": bitrate}}),
        },
    )


async def test_daily_aggregation_and_zero_fill(db):
    await play(db, "2026-10-23T10:00:00", "192.168.1.5", 50_000_000)
    await play(db, "2026-10-23T11:00:00", "8.8.8.8", 4_000_000)
    await play(db, "2026-10-23T12:00:00", "1.1.1.1", 8_000_000)
    await play(db, "2026-10-23T13:00:00", "2001:4860::1", None)  # no bitrate
    await play(db, "2026-10-25T09:00:00", None)
    await play(db, "2026-10-25T09:30:00", "::ffff:10.0.0.2")

    rows = await stats_db.get_plays_by_location(db, Period.last(3, now=NOON))

    assert rows == [
        {
            "date": "2026-10-23",
            "lan": 1,
            "remote": 3,
            "unknown": 0,
            "remote_avg_bitrate": 6_000_000,
        },
        {
            "date": "2026-10-24",
            "lan": 0,
            "remote": 0,
            "unknown": 0,
            "remote_avg_bitrate": None,
        },
        {
            "date": "2026-10-25",
            "lan": 1,
            "remote": 0,
            "unknown": 1,
            "remote_avg_bitrate": None,
        },
    ]


async def test_endpoint_returns_no_ips(db, monkeypatch):
    from empulse.web import api

    await play(db, datetime.now(timezone.utc).isoformat(), "93.184.216.34", 1_000_000)
    monkeypatch.setattr(api, "get_db", lambda: db)

    resp = await api.chart_plays_by_location(Period.last(7))
    body = resp.body.decode()

    assert json.loads(body)[-1]["remote"] == 1
    assert "93.184.216.34" not in body
    assert set(json.loads(body)[0]) == {
        "date",
        "lan",
        "remote",
        "unknown",
        "remote_avg_bitrate",
    }
