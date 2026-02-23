import asyncio
import logging

logger = logging.getLogger("empulse.poster_cache")

POSTER_WIDTH = 120
REFRESH_INTERVAL = 1800  # 30 minutes
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
        """Fetch random item IDs from Emby, only download images not already cached."""
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

        # Only fetch images we don't already have
        new_ids = [id for id in ids if id not in self._image_map]

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

        if new_ids:
            results = await asyncio.gather(*[fetch_one(id) for id in new_ids])
            for r in results:
                if r is not None:
                    item_id, data, ct = r
                    self._image_map[item_id] = (data, ct)

        # Build poster list from new IDs, reusing cached images
        posters = []
        for item_id in ids:
            if item_id in self._image_map:
                data, ct = self._image_map[item_id]
                posters.append((item_id, data, ct))

        # Prune image_map: keep only images still in active poster list
        active_ids = {item_id for item_id, _, _ in posters}
        self._image_map = {k: v for k, v in self._image_map.items() if k in active_ids}

        self._posters = posters
        self._ready.set()
        logger.info(
            f"Poster cache refreshed: {len(posters)} posters "
            f"({len(new_ids)} fetched, {len(posters) - len(new_ids)} reused)"
        )
