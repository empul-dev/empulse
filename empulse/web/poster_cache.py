import asyncio
import logging

logger = logging.getLogger("empulse.poster_cache")

POSTER_WIDTH = 40
REFRESH_INTERVAL = 300  # 5 minutes
POSTER_COUNT = 36


class PosterWallCache:
    """Pre-fetches and caches random poster thumbnails for the login page."""

    def __init__(self, emby_client):
        self.emby_client = emby_client
        self._posters: list[tuple[str, bytes, str]] = []  # (id, bytes, content_type)
        self._image_map: dict[
            str, tuple[bytes, str]
        ] = {}  # id -> (bytes, content_type)
        self._ready = asyncio.Event()

    @property
    def item_ids(self) -> list[str]:
        return [item_id for item_id, _, _ in self._posters]

    def get_image(self, item_id: str) -> tuple[bytes, str] | None:
        return self._image_map.get(item_id)

    async def run(self):
        """Background refresh loop."""
        while True:
            try:
                await self._refresh()
            except Exception as e:
                logger.error(f"Poster cache refresh failed: {e}")
            await asyncio.sleep(REFRESH_INTERVAL)

    async def _refresh(self):
        """Fetch random item IDs from Emby, then fetch all images in parallel."""
        params = {
            **self.emby_client._params,
            "SortBy": "Random",
            "Recursive": "true",
            "Limit": str(POSTER_COUNT),
            "IncludeItemTypes": "Movie,Series",
            "ImageTypes": "Primary",
            "Fields": "PrimaryImageAspectRatio",
        }
        r = await self.emby_client._client.get(
            f"{self.emby_client.base_url}/Items", params=params
        )
        r.raise_for_status()
        items = r.json().get("Items", [])
        ids = [item["Id"] for item in items if item.get("Id")]

        if not ids:
            logger.warning("No poster items returned from Emby")
            self._ready.set()
            return

        async def fetch_one(item_id: str) -> tuple[str, bytes, str] | None:
            url = f"{self.emby_client.base_url}/Items/{item_id}/Images/Primary"
            try:
                resp = await self.emby_client._client.get(
                    url,
                    params={
                        "api_key": self.emby_client.api_key,
                        "maxWidth": str(POSTER_WIDTH),
                    },
                )
                if resp.status_code == 200:
                    ct = resp.headers.get("content-type", "image/jpeg")
                    return (item_id, resp.content, ct)
            except Exception:
                pass
            return None

        results = await asyncio.gather(*[fetch_one(id) for id in ids])
        posters = [r for r in results if r is not None]

        # Atomic swap
        self._posters = posters
        self._image_map = {item_id: (data, ct) for item_id, data, ct in posters}
        self._ready.set()
        logger.info(f"Poster cache refreshed: {len(posters)} images cached")
