import logging
import base64

import httpx
from empulse.config import settings
from empulse.emby.models import EmbySessionInfo, EmbyUser, EmbyLibrary

logger = logging.getLogger("empulse.emby")


class EmbyClient:
    def __init__(self):
        self.base_url = settings.emby_url.rstrip("/")
        self.api_key = settings.emby_api_key
        self._client = httpx.AsyncClient(
            timeout=15.0,
            headers={"X-Emby-Token": self.api_key} if self.api_key else {},
        )
        if self.base_url.startswith("http://") and not any(
            self.base_url.startswith(f"http://{h}")
            for h in ("localhost", "127.0.0.1", "[::1]")
        ):
            logger.warning(
                "Emby URL uses plain HTTP (%s). API key will be sent unencrypted. "
                "Consider using HTTPS.",
                self.base_url,
            )

    async def get_server_info(self) -> dict:
        r = await self._client.get(f"{self.base_url}/System/Info")
        r.raise_for_status()
        return r.json()

    async def get_sessions(self) -> list[EmbySessionInfo]:
        r = await self._client.get(f"{self.base_url}/Sessions")
        r.raise_for_status()
        data = r.json()
        return [EmbySessionInfo(**s) for s in data]

    async def get_users(self) -> list[EmbyUser]:
        r = await self._client.get(f"{self.base_url}/Users")
        r.raise_for_status()
        data = r.json()
        return [EmbyUser(**u) for u in data]

    async def get_libraries(self) -> list[EmbyLibrary]:
        r = await self._client.get(f"{self.base_url}/Library/VirtualFolders")
        r.raise_for_status()
        data = r.json()
        return [EmbyLibrary(**lib) for lib in data]

    async def get_library_item_count(self, library_id: str) -> int:
        r = await self._client.get(
            f"{self.base_url}/Items",
            params={"ParentId": library_id, "Recursive": "true", "Limit": 0},
        )
        r.raise_for_status()
        return r.json().get("TotalRecordCount", 0)

    async def get_item(self, item_id: str) -> dict:
        """Fetch full item metadata. Uses /Items?Ids= which works without user context."""
        r = await self._client.get(
            f"{self.base_url}/Items",
            params={
                "Ids": item_id,
                "Fields": "Overview,People,Genres,Studios,CommunityRating,CriticRating,"
                          "OfficialRating,ProductionYear,PremiereDate,ExternalUrls,"
                          "ProviderIds,MediaStreams,RunTimeTicks,Taglines,OriginalTitle",
            },
        )
        r.raise_for_status()
        items = r.json().get("Items", [])
        if not items:
            return {}
        return items[0]

    async def get_recently_added(self, limit: int = 10, item_type: str = "") -> list[dict]:
        params = {
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "Recursive": "true",
            "Limit": str(limit),
            "Fields": (
                "DateCreated,ProductionYear,Overview,Genres,CommunityRating,"
                "RunTimeTicks,Taglines,SeriesName,SeriesId,ParentIndexNumber,"
                "IndexNumber,OriginalTitle"
            ),
            "IncludeItemTypes": item_type or "Movie,Episode",
        }
        r = await self._client.get(f"{self.base_url}/Items", params=params)
        r.raise_for_status()
        return r.json().get("Items", [])

    async def get_image_data_url(
        self,
        item_id: str,
        image_type: str = "Primary",
        max_width: int = 300,
    ) -> str:
        """Fetch an Emby image and return it as a data URL for email embedding."""
        r = await self._client.get(
            f"{self.base_url}/Items/{item_id}/Images/{image_type}",
            params={"maxWidth": str(max_width)},
        )
        r.raise_for_status()
        content_type = r.headers.get("content-type", "image/jpeg")
        encoded = base64.b64encode(r.content).decode("ascii")
        return f"data:{content_type};base64,{encoded}"

    async def authenticate_user(self, username: str, password: str) -> dict | None:
        """Authenticate a user against Emby via AuthenticateByName.

        Returns {"user_id": ..., "username": ..., "is_admin": bool} on success,
        None for bad credentials. Raises httpx exceptions on network/timeout errors.
        """
        auth_header = (
            'MediaBrowser Client="Empulse", Device="Server", '
            'DeviceId="empulse-auth", Version="1.0"'
        )
        r = await self._client.post(
            f"{self.base_url}/Users/AuthenticateByName",
            headers={"X-Emby-Authorization": auth_header},
            json={"Username": username, "Pw": password},
        )
        if r.status_code == 401:
            return None
        r.raise_for_status()
        data = r.json()
        user = data["User"]
        return {
            "user_id": user["Id"],
            "username": user["Name"],
            "is_admin": bool(user.get("Policy", {}).get("IsAdministrator", False)),
        }

    async def stop_session(self, session_id: str) -> bool:
        """Send a stop command to an active Emby session. Returns True on success."""
        try:
            r = await self._client.post(
                f"{self.base_url}/Sessions/{session_id}/Playing/Stop",
            )
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to stop session {session_id}: {e}")
            return False

    def get_user_image_url(self, user_id: str) -> str:
        return f"/api/img/user/{user_id}"

    async def close(self):
        await self._client.aclose()
