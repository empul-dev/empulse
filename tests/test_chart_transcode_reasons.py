"""Transcode Reasons by Client chart: query aggregation and endpoint."""

import json
from datetime import UTC, datetime
from unittest.mock import patch

from empulse.db import history as history_db
from empulse.db import stats as stats_db
from empulse.period import Period
from empulse.web.api import chart_transcode_reasons

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
PERIOD = Period.last(30, "UTC", now=NOW)
INSIDE = "2026-10-20T12:00:00+00:00"

_n = 0


async def play(db, client="Fire TV", reasons=None, *, stream_info=None, **extra):
    global _n
    _n += 1
    if stream_info is None:
        stream_info = {"transcode": {"reasons": reasons}} if reasons is not None else {}
    await history_db.insert_history(
        db,
        {
            "session_key": f"s{_n}",
            "user_id": "u1",
            "user_name": "Alice",
            "item_id": "i1",
            "item_name": "Film",
            "item_type": "Movie",
            "started_at": INSIDE,
            "stopped_at": INSIDE,
            "duration_seconds": 3600,
            "play_method": "Transcode",
            "client": client,
            "stream_info": json.dumps(stream_info),
            **extra,
        },
    )


def by_client(data):
    """{client: {reason: n}} with zero segments dropped, for readable asserts."""
    return {
        c: {r: data["counts"][r][i] for r in data["reasons"] if data["counts"][r][i]}
        for i, c in enumerate(data["clients"])
    }


async def test_multiple_reasons_count_once_each_and_are_humanized(db):
    await play(db, reasons=["AudioCodecNotSupported", "VideoBitrateNotSupported"])
    await play(db, reasons=["AudioCodecNotSupported"])

    data = await stats_db.get_transcode_reasons_by_client(db, PERIOD)

    assert data["reasons"] == [
        "Audio codec not supported",
        "Video bitrate not supported",
    ]
    assert by_client(data) == {
        "Fire TV": {"Audio codec not supported": 2, "Video bitrate not supported": 1}
    }


async def test_direct_plays_excluded(db):
    await play(db, play_method="DirectPlay", reasons=["AudioCodecNotSupported"])
    await play(db, play_method="DirectStream", reasons=["ContainerNotSupported"])

    data = await stats_db.get_transcode_reasons_by_client(db, PERIOD)

    assert data == {"clients": [], "reasons": [], "counts": {}}


async def test_missing_reasons_count_as_unknown(db):
    await play(db, reasons=[])  # Emby gave none
    await play(db, stream_info={"transcode": {}})  # pre-0.2.8 row, no key
    await play(db, stream_info={})  # no transcode block at all
    for raw in (None, "not json"):  # NULL / corrupt column must not break the chart
        await history_db.insert_history(
            db,
            {
                "session_key": f"raw-{raw}",
                "user_id": "u1",
                "item_id": "i1",
                "started_at": INSIDE,
                "stopped_at": INSIDE,
                "duration_seconds": 3600,
                "play_method": "Transcode",
                "client": "Fire TV",
                "stream_info": raw,
            },
        )

    data = await stats_db.get_transcode_reasons_by_client(db, PERIOD)

    assert by_client(data) == {"Fire TV": {"Unknown": 5}}


async def test_top_clients_and_reasons_cutoff(db):
    # 10 clients; client c<i> transcodes 20-i times -> top 8 are c0..c7.
    for i in range(10):
        for _ in range(20 - i):
            await play(db, client=f"c{i}", reasons=["ContainerNotSupported"])
    # 8 distinct reasons on c0, decreasing frequency R0 (8x) .. R7 (1x).
    codes = [f"Reason{k}Code" for k in range(8)]
    for k, code in enumerate(codes):
        for _ in range(8 - k):
            await play(db, client="c0", reasons=[code])
    await play(db, client="c1", reasons=[])

    data = await stats_db.get_transcode_reasons_by_client(db, PERIOD)

    assert data["clients"] == [f"c{i}" for i in range(8)]
    assert data["reasons"] == [
        "Container not supported",
        "Reason0 code",
        "Reason1 code",
        "Reason2 code",
        "Reason3 code",
        "Reason4 code",
        "Other",
        "Unknown",
    ]
    # Other = Reason5 (3) + Reason6 (2) + Reason7 (1), all on c0.
    assert data["counts"]["Other"][0] == 6
    assert data["counts"]["Unknown"][1] == 1
    assert all(len(v) == 8 for v in data["counts"].values())


async def test_period_bounds(db):
    start, end = PERIOD.bounds
    await play(db, reasons=["AudioCodecNotSupported"], started_at=start)
    await play(
        db, reasons=["AudioCodecNotSupported"], started_at="2026-01-01T00:00:00+00:00"
    )
    await play(db, reasons=["AudioCodecNotSupported"], started_at=end)
    await play(
        db, reasons=["AudioCodecNotSupported"], duration_seconds=60
    )  # not counted

    data = await stats_db.get_transcode_reasons_by_client(db, PERIOD)

    assert by_client(data) == {"Fire TV": {"Audio codec not supported": 1}}


async def test_endpoint_returns_json(db):
    await play(db, client="Emby for Android TV", reasons=["AudioCodecNotSupported"])

    with patch("empulse.web.api.get_db", return_value=db):
        resp = await chart_transcode_reasons(period=PERIOD)

    assert resp.status_code == 200
    assert json.loads(resp.body) == {
        "clients": ["Emby for Android TV"],
        "reasons": ["Audio codec not supported"],
        "counts": {"Audio codec not supported": [1]},
    }
