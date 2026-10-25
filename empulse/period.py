"""The Period: the last N local days, today included, in the display timezone.

See GLOSSARY.md and docs/adr/0001-period-is-calendar-days.md.
"""

import ipaddress
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import aiosqlite

MAX_DAYS = 365


@dataclass(frozen=True)
class Period:
    days: int
    tz: str
    last_day: date

    @classmethod
    def last(cls, days: int, tz: str = "UTC", now: datetime | None = None) -> "Period":
        """The last *days* local days (clamped to 1..MAX_DAYS), ending today in *tz*."""
        now = now or datetime.now(timezone.utc)
        return cls(max(1, min(days, MAX_DAYS)), tz, now.astimezone(_zone(tz)).date())

    @property
    def first_day(self) -> date:
        return self.last_day - timedelta(days=self.days - 1)

    @property
    def bounds(self) -> tuple[str, str]:
        """Half-open UTC range [start, end) as ISO strings comparable to stored timestamps."""
        return _utc_midnight(self.first_day, self.tz), _utc_midnight(
            self.last_day + timedelta(days=1), self.tz
        )

    def previous(self) -> "Period":
        """The period of the same length that ends where this one begins."""
        return Period(self.days, self.tz, self.first_day - timedelta(days=1))

    def day_keys(self) -> list[str]:
        return [
            (self.first_day + timedelta(days=i)).isoformat() for i in range(self.days)
        ]

    def fill_days(self, rows: list[dict], by: str | None = None, **zero) -> list[dict]:
        """One row per local day (per category of *by*, if given), zero-filled with *zero*.

        Rows whose date falls outside the period are dropped.
        """
        if by is None:
            existing = {r["date"]: r for r in rows}
            return [existing.get(d) or {"date": d, **zero} for d in self.day_keys()]
        existing = {(r["date"], r[by]): r for r in rows}
        categories = sorted(
            {r[by] for r in rows}, key=lambda c: "" if c is None else str(c)
        )
        return [
            existing.get((d, c)) or {"date": d, by: c, **zero}
            for d in self.day_keys()
            for c in categories
        ]


@lru_cache(maxsize=32)
def _zone(tz: str) -> ZoneInfo:
    return ZoneInfo(tz)


def _utc_midnight(day: date, tz: str) -> str:
    local = datetime.combine(day, time.min, tzinfo=_zone(tz))
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _local(ts: str | None, tz: str) -> datetime | None:
    if ts is None:
        return None
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_zone(tz))


def _local_date(ts, tz):
    dt = _local(ts, tz)
    return dt and dt.date().isoformat()


def _local_hour(ts, tz):
    dt = _local(ts, tz)
    return dt and dt.hour


def _local_dow(ts, tz):
    """0 = Sunday, like SQLite's strftime('%w')."""
    dt = _local(ts, tz)
    return dt and dt.isoweekday() % 7


def _local_month(ts, tz):
    dt = _local(ts, tz)
    return dt and dt.strftime("%Y-%m")


def ip_scope(ip: str | None) -> str:
    """'lan' for private/loopback/link-local addresses, 'remote' for any other, else 'unknown'.

    CGNAT (100.64.0.0/10, e.g. Tailscale) counts as remote: that traffic leaves the LAN.
    Accepts an optional port ("1.2.3.4:5678", "[::1]:8096") and IPv4-mapped IPv6.
    """
    host = (ip or "").strip()
    if host.startswith("[") and "]" in host:
        host = host[1 : host.index("]")]
    elif host.count(":") == 1:
        host = host.partition(":")[0]
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return "unknown"
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return (
        "lan" if addr.is_private or addr.is_loopback or addr.is_link_local else "remote"
    )


async def register_sql_functions(conn: aiosqlite.Connection) -> None:
    """Add local_date/local_hour/local_dow/local_month(ts, tz) and ip_scope(ip) to *conn*.

    Each row is converted with its own UTC offset, so grouping stays correct across DST.
    """
    for name, fn in (
        ("local_date", _local_date),
        ("local_hour", _local_hour),
        ("local_dow", _local_dow),
        ("local_month", _local_month),
    ):
        await conn.create_function(name, 2, fn, deterministic=True)
    await conn.create_function("ip_scope", 1, ip_scope, deterministic=True)
