"""IP geolocation lookup with database caching."""

import logging
from ipaddress import ip_address

import aiosqlite
import httpx

logger = logging.getLogger("empulse.geo")

# ip-api.com free tier: 45 requests/minute, no key needed
_API_URL = "http://ip-api.com/json/{ip}?fields=status,country,city,lat,lon,query"


def _is_private_ip(ip: str) -> bool:
    """Check if IP is private/reserved and shouldn't be looked up."""
    try:
        addr = ip_address(ip)
        return addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local
    except (ValueError, TypeError):
        return True


async def lookup_ip(db: aiosqlite.Connection, ip: str) -> dict | None:
    """Look up geo-location for an IP. Returns cached result or fetches from API.

    Returns dict with keys: city, country, latitude, longitude, or None if lookup fails.
    """
    if not ip or _is_private_ip(ip):
        return None

    # Check cache first
    cursor = await db.execute(
        "SELECT city, country, latitude, longitude FROM ip_locations WHERE ip = ?", [ip]
    )
    row = await cursor.fetchone()
    if row:
        return dict(row)

    # Fetch from API
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(_API_URL.format(ip=ip))
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning(f"Geo lookup failed for {ip}: {e}")
        return None

    if data.get("status") != "success":
        return None

    result = {
        "city": data.get("city", ""),
        "country": data.get("country", ""),
        "latitude": data.get("lat", 0),
        "longitude": data.get("lon", 0),
    }

    # Cache result
    try:
        await db.execute(
            "INSERT OR REPLACE INTO ip_locations (ip, city, country, latitude, longitude) "
            "VALUES (?, ?, ?, ?, ?)",
            [ip, result["city"], result["country"], result["latitude"], result["longitude"]],
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to cache geo result: {e}")

    return result


async def get_all_locations(db: aiosqlite.Connection) -> list[dict]:
    """Get all stored IP locations with latest activity info for map display."""
    cursor = await db.execute("""
        SELECT ip_locations.ip, ip_locations.city, ip_locations.country,
               ip_locations.latitude, ip_locations.longitude,
               h.user_name, h.item_name, h.started_at
        FROM ip_locations
        INNER JOIN (
            SELECT ip_address, user_name, item_name, started_at,
                   ROW_NUMBER() OVER (PARTITION BY ip_address ORDER BY started_at DESC) as rn
            FROM history
            WHERE ip_address IS NOT NULL AND ip_address != ''
        ) h ON h.ip_address = ip_locations.ip AND h.rn = 1
        WHERE ip_locations.latitude != 0 OR ip_locations.longitude != 0
    """)
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
