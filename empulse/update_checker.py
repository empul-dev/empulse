from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger("empulse.update_checker")

GITHUB_RELEASES_URL = "https://api.github.com/repos/empul-dev/empulse/releases/latest"


@dataclass
class UpdateInfo:
    update_available: bool = False
    latest_version: str = ""
    current_version: str = ""
    release_url: str = ""
    release_notes: str = ""


def _parse_version(v: str) -> tuple[int, ...] | None:
    """Parse a version string like '0.1.0' or 'v0.1.0' into a tuple of ints."""
    v = v.strip().lstrip("v")
    try:
        return tuple(int(p) for p in v.split("."))
    except (ValueError, AttributeError):
        return None


def _is_newer(latest: str, current: str) -> bool:
    """Return True if latest is strictly newer than current."""
    lat = _parse_version(latest)
    cur = _parse_version(current)
    if lat is None or cur is None:
        return False
    return lat > cur


class UpdateChecker:
    def __init__(self, current_version: str, interval: int = 86400) -> None:
        self.current_version = current_version
        self.interval = interval
        self.info: UpdateInfo = UpdateInfo(current_version=current_version)

    async def check_once(self) -> UpdateInfo:
        """Perform a single check against the GitHub releases API."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                GITHUB_RELEASES_URL,
                headers={"Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            data = resp.json()

        tag = data.get("tag_name", "")
        url = data.get("html_url", "")
        notes = data.get("body", "")

        info = UpdateInfo(
            update_available=_is_newer(tag, self.current_version),
            latest_version=tag.lstrip("v"),
            current_version=self.current_version,
            release_url=url,
            release_notes=notes,
        )
        self.info = info
        return info

    async def run(self) -> None:
        """Background loop: check on startup, then every `interval` seconds."""
        while True:
            try:
                await self.check_once()
                if self.info.update_available:
                    logger.info(
                        "Update available: v%s (current: v%s)",
                        self.info.latest_version,
                        self.current_version,
                    )
                else:
                    logger.debug("No update available (latest: v%s)", self.info.latest_version)
            except Exception:
                logger.debug("Update check failed", exc_info=True)
            await asyncio.sleep(self.interval)
