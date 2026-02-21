"""Validate outbound URLs to prevent SSRF attacks."""

import ipaddress
import socket
from urllib.parse import urlparse

# Private/reserved networks that should not be reachable from notifications
BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / cloud metadata
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]

# Known safe external services that are always allowed
ALLOWED_HOSTS = {
    "discord.com",
    "discordapp.com",
    "api.telegram.org",
    "ntfy.sh",
}


def validate_outbound_url(url: str, *, allow_private: bool = False) -> str | None:
    """Validate a URL for outbound requests (SSRF protection).

    Returns an error message string if the URL is blocked, or None if it's safe.
    """
    if not url:
        return "URL is empty"

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return f"URL scheme '{parsed.scheme}' is not allowed (use http or https)"

    hostname = parsed.hostname
    if not hostname:
        return "URL has no hostname"

    # Always allow known safe external services
    if any(hostname == h or hostname.endswith(f".{h}") for h in ALLOWED_HOSTS):
        return None

    if allow_private:
        return None

    # Resolve hostname to check for private IPs
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return f"Cannot resolve hostname '{hostname}'"

    for family, _, _, _, sockaddr in results:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        for net in BLOCKED_NETWORKS:
            if addr in net:
                return f"URL resolves to a private/reserved address ({ip_str})"

    return None
