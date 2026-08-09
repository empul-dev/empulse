import logging
import base64
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from empulse.config import settings
from empulse.emby.models import EmbySessionInfo, EmbyUser, EmbyLibrary

logger = logging.getLogger("empulse.emby")

# (primary_item_type, child_item_type, display_label, empty_unit) per Emby collection type.
LIBRARY_ITEM_TYPES = {
    "movies": ("Movie", "Movie", "Movies", "movie"),
    "tvshows": ("Series", "Episode", "TV Shows", "series"),
    "music": ("Audio", "Audio", "Music", "track"),
}
DEFAULT_ITEM_TYPES = "Movie,Series,Audio"

_LINK_LOCAL_NETS = [
    ipaddress.ip_network("169.254.0.0/16"),  # IPv4 link-local / cloud metadata
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def _resolve_ips(hostname: str) -> list:
    """Resolve hostname to IP addresses; empty list if resolution fails."""
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    ips = []
    for *_, sockaddr in results:
        try:
            ips.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            pass
    return ips


def validate_emby_url() -> None:
    """Refuse to boot on an unsafe EMBY_URL (S-2 key-in-clear, E-4 metadata SSRF).

    Self-hosted Emby normally lives on loopback or a private LAN over plain HTTP,
    so those stay allowed. Only the genuinely dangerous cases are blocked:
    plaintext HTTP to a *public* host (API key sent unencrypted over the WAN) and
    resolution to the link-local / cloud-metadata range. Both have env overrides.
    If the host can't be resolved yet (e.g. DNS not ready at container start) we
    stay lenient rather than block a legitimate start-up.
    """
    parsed = urlparse(settings.emby_url)
    host = parsed.hostname or ""
    if not host:
        raise RuntimeError(f"EMBY_URL '{settings.emby_url}' has no hostname")

    ips = _resolve_ips(host)
    is_loopback = host == "localhost" or any(ip.is_loopback for ip in ips)
    is_private = any(ip.is_private for ip in ips)  # RFC1918 + loopback + link-local
    is_public = bool(ips) and not is_loopback and not is_private

    if not settings.emby_allow_private and any(
        ip in net for ip in ips for net in _LINK_LOCAL_NETS
    ):
        raise RuntimeError(
            f"EMBY_URL '{settings.emby_url}' resolves to the link-local/metadata "
            "range (169.254.0.0/16) — a common SSRF target, not a real Emby server. "
            "Set EMBY_ALLOW_PRIVATE=1 to override."
        )

    if (
        parsed.scheme == "http"
        and is_public
        and not settings.emby_allow_insecure
    ):
        raise RuntimeError(
            f"EMBY_URL '{settings.emby_url}' uses plain http:// to public host "
            f"'{host}' — the Emby API key would be sent unencrypted over the "
            "internet. Use https:// or set EMBY_ALLOW_INSECURE=1 to override."
        )


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

    async def get_library_item_count(self, library_id: str, item_types: str = "") -> int:
        """Count items in a library. Without item_types the recursive count includes
        seasons/extras/box-sets; pass e.g. "Movie" or "Series" for a real count."""
        params = {"ParentId": library_id, "Recursive": "true", "Limit": 0}
        if item_types:
            params["IncludeItemTypes"] = item_types
        r = await self._client.get(f"{self.base_url}/Items", params=params)
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
                          "ProviderIds,MediaStreams,RunTimeTicks,Taglines,OriginalTitle,"
                          "SeriesName,SeriesId,ParentIndexNumber,IndexNumber,ParentId,"
                "DateCreated",
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

    async def get_catalog_page(
        self,
        limit: int = 100,
        start_index: int = 0,
        search: str = "",
        parent_id: str = "",
        include_item_types: str = "Series",
    ) -> dict:
        params = {
            "Recursive": "true",
            "IncludeItemTypes": include_item_types,
            "SortBy": "SortName",
            "SortOrder": "Ascending",
            "StartIndex": str(max(0, start_index)),
            "Limit": str(max(1, limit)),
            "Fields": "ProductionYear,Overview,PremiereDate,DateCreated",
        }
        if search:
            params["SearchTerm"] = search
        if parent_id:
            params["ParentId"] = parent_id
        r = await self._client.get(f"{self.base_url}/Items", params=params)
        r.raise_for_status()
        data = r.json()
        return {
            "items": data.get("Items", []),
            "total": data.get("TotalRecordCount", 0),
        }

    async def get_series_catalog_page(
        self,
        limit: int = 100,
        start_index: int = 0,
        search: str = "",
        parent_id: str = "",
    ) -> dict:
        return await self.get_catalog_page(
            limit=limit,
            start_index=start_index,
            search=search,
            parent_id=parent_id,
            include_item_types="Series",
        )

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
