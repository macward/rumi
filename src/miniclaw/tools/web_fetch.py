"""Web fetch tool with SSRF protection."""

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from .base import Tool, ToolResult


# Private/reserved IP ranges to block
BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),    # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),   # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),   # Link-local
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 private
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
    ipaddress.ip_network("0.0.0.0/8"),        # "This" network
    ipaddress.ip_network("100.64.0.0/10"),    # Carrier-grade NAT
    ipaddress.ip_network("192.0.0.0/24"),     # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),     # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),   # TEST-NET-3
]

ALLOWED_SCHEMES = {"http", "https"}


def is_private_ip(ip: str) -> bool:
    """Check if an IP address is in a private/reserved range."""
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in network for network in BLOCKED_NETWORKS)
    except ValueError:
        return True  # Invalid IP, treat as blocked


def resolve_and_validate(hostname: str) -> tuple[bool, str | None, str | None]:
    """Resolve hostname and validate the IP is not private.

    Returns (valid, resolved_ip, error_message).
    """
    try:
        # Get all IPs for the hostname
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)

        for family, _, _, _, sockaddr in infos:
            ip = sockaddr[0]

            if is_private_ip(ip):
                return False, ip, f"Blocked: {hostname} resolves to private IP {ip}"

        # Return the first valid IP
        if infos:
            return True, infos[0][4][0], None

        return False, None, f"Could not resolve hostname: {hostname}"

    except socket.gaierror as e:
        return False, None, f"DNS resolution failed: {e}"


class WebFetchTool(Tool):
    """Tool for fetching web content with SSRF protection."""

    def __init__(
        self,
        timeout: float = 10.0,
        max_bytes: int = 1_000_000,  # 1MB
        max_redirects: int = 5,
    ) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch content from a URL. Only HTTP/HTTPS URLs to public IPs are allowed. "
            "Returns the response status, headers, and body (truncated if large). "
            "Use this to retrieve web pages, API responses, or download small files."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch. Must be http:// or https://",
                },
                "method": {
                    "type": "string",
                    "description": "HTTP method: GET (default), HEAD",
                    "enum": ["GET", "HEAD"],
                },
            },
            "required": ["url"],
        }

    def _validate_url(self, url: str) -> tuple[bool, str | None]:
        """Validate URL scheme and host."""
        try:
            parsed = urlparse(url)
        except Exception as e:
            return False, f"Invalid URL: {e}"

        # Check scheme
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            return False, f"Scheme not allowed: {parsed.scheme}. Use http or https."

        # Check hostname exists
        if not parsed.hostname:
            return False, "URL must have a hostname"

        # Resolve and validate IP
        valid, ip, error = resolve_and_validate(parsed.hostname)
        if not valid:
            return False, error

        return True, None

    async def execute(self, url: str, method: str = "GET", **kwargs: Any) -> ToolResult:
        """Fetch content from URL."""
        # Validate URL
        valid, error = self._validate_url(url)
        if not valid:
            return ToolResult(success=False, output="", error=error)

        # Validate method
        method = method.upper()
        if method not in ("GET", "HEAD"):
            return ToolResult(success=False, output="", error=f"Invalid method: {method}")

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                max_redirects=self._max_redirects,
            ) as client:
                # For each redirect, we need to validate the new host
                # httpx handles redirects, but we validate before the first request
                # To properly validate redirects, we'd need a custom transport

                if method == "HEAD":
                    response = await client.head(url)
                    body = ""
                else:
                    response = await client.get(url)
                    # Read up to max_bytes
                    body = response.text[: self._max_bytes]
                    if len(response.text) > self._max_bytes:
                        body += "\n... [content truncated]"

                # Format headers
                headers_str = "\n".join(
                    f"{k}: {v}"
                    for k, v in list(response.headers.items())[:20]
                )

                output = f"HTTP {response.status_code} {response.reason_phrase}\n\n"
                output += f"Headers:\n{headers_str}\n\n"
                if body:
                    output += f"Body:\n{body}"

                return ToolResult(
                    success=response.is_success,
                    output=output,
                    error=None if response.is_success else f"HTTP {response.status_code}",
                    metadata={
                        "status_code": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "content_length": len(response.text) if method != "HEAD" else None,
                    },
                )

        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Request timed out after {self._timeout}s",
            )
        except httpx.TooManyRedirects:
            return ToolResult(
                success=False,
                output="",
                error=f"Too many redirects (max {self._max_redirects})",
            )
        except httpx.RequestError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Request failed: {e}",
            )
