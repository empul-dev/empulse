import logging
import httpx
from emtulli.config import settings
from emtulli.emby.models import EmbySessionInfo, EmbyUser, EmbyLibrary

logger = logging.getLogger("emtulli.emby")


class EmbyClient:
    def __init__(self):
        self.base_url = settings.emby_url.rstrip("/")
        self.api_key = settings.emby_api_key
        self._client = httpx.AsyncClient(timeout=15.0)

    @property
    def _params(self) -> dict:
        return {"api_key": self.api_key}

    async def get_server_info(self) -> dict:
        r = await self._client.get(f"{self.base_url}/System/Info", params=self._params)
        r.raise_for_status()
        return r.json()

    async def get_sessions(self) -> list[EmbySessionInfo]:
        r = await self._client.get(f"{self.base_url}/Sessions", params=self._params)
        r.raise_for_status()
        data = r.json()
        return [EmbySessionInfo(**s) for s in data]

    async def get_users(self) -> list[EmbyUser]:
        r = await self._client.get(f"{self.base_url}/Users", params=self._params)
        r.raise_for_status()
        data = r.json()
        return [EmbyUser(**u) for u in data]

    async def get_libraries(self) -> list[EmbyLibrary]:
        r = await self._client.get(
            f"{self.base_url}/Library/VirtualFolders", params=self._params
        )
        r.raise_for_status()
        data = r.json()
        return [EmbyLibrary(**lib) for lib in data]

    async def get_library_item_count(self, library_id: str) -> int:
        r = await self._client.get(
            f"{self.base_url}/Items",
            params={**self._params, "ParentId": library_id, "Recursive": "true", "Limit": 0},
        )
        r.raise_for_status()
        return r.json().get("TotalRecordCount", 0)

    async def get_item(self, item_id: str) -> dict:
        r = await self._client.get(
            f"{self.base_url}/Items/{item_id}",
            params=self._params,
        )
        r.raise_for_status()
        return r.json()

    def get_user_image_url(self, user_id: str) -> str:
        return f"/api/img/user/{user_id}"

    async def close(self):
        await self._client.aclose()
