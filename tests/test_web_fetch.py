"""Tests for web_fetch tool."""

import pytest

from miniclaw.tools.web_fetch import (
    BLOCKED_NETWORKS,
    SSRFBlockedError,
    WebFetchTool,
    check_redirect_ssrf,
    is_private_ip,
    resolve_and_validate,
    validate_url_for_ssrf,
)


class TestIsPrivateIp:
    def test_loopback(self):
        assert is_private_ip("127.0.0.1") is True
        assert is_private_ip("127.0.0.2") is True

    def test_private_class_a(self):
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("10.255.255.255") is True

    def test_private_class_b(self):
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.255") is True
        assert is_private_ip("172.15.0.1") is False  # Just outside range

    def test_private_class_c(self):
        assert is_private_ip("192.168.0.1") is True
        assert is_private_ip("192.168.255.255") is True

    def test_link_local(self):
        assert is_private_ip("169.254.0.1") is True

    def test_public_ips(self):
        assert is_private_ip("8.8.8.8") is False
        assert is_private_ip("1.1.1.1") is False
        assert is_private_ip("142.250.185.14") is False  # google.com

    def test_invalid_ip(self):
        assert is_private_ip("not-an-ip") is True  # Treat as blocked


class TestResolveAndValidate:
    def test_public_domain(self):
        valid, ip, error = resolve_and_validate("google.com")
        assert valid is True
        assert ip is not None
        assert error is None

    def test_localhost(self):
        valid, ip, error = resolve_and_validate("localhost")
        assert valid is False
        assert "private" in error.lower() or "blocked" in error.lower()

    def test_nonexistent_domain(self):
        valid, ip, error = resolve_and_validate("this-domain-does-not-exist-12345.com")
        assert valid is False
        assert "resolution" in error.lower() or "resolve" in error.lower()


class TestUrlValidation:
    @pytest.fixture
    def tool(self) -> WebFetchTool:
        return WebFetchTool()

    def test_https_allowed(self, tool: WebFetchTool):
        valid, error = tool._validate_url("https://httpbin.org")
        assert valid is True, f"Should be valid but got: {error}"

    def test_http_allowed(self, tool: WebFetchTool):
        valid, error = tool._validate_url("http://httpbin.org")
        assert valid is True, f"Should be valid but got: {error}"

    def test_file_scheme_blocked(self, tool: WebFetchTool):
        valid, error = tool._validate_url("file:///etc/passwd")
        assert valid is False
        assert "scheme" in error.lower()

    def test_ftp_scheme_blocked(self, tool: WebFetchTool):
        valid, error = tool._validate_url("ftp://ftp.example.com")
        assert valid is False

    def test_localhost_blocked(self, tool: WebFetchTool):
        valid, error = tool._validate_url("http://localhost/admin")
        assert valid is False

    def test_127_blocked(self, tool: WebFetchTool):
        valid, error = tool._validate_url("http://127.0.0.1:8080/api")
        assert valid is False

    def test_private_ip_blocked(self, tool: WebFetchTool):
        valid, error = tool._validate_url("http://192.168.1.1/")
        assert valid is False

    def test_no_hostname(self, tool: WebFetchTool):
        valid, error = tool._validate_url("http:///path")
        assert valid is False


@pytest.mark.asyncio
class TestExecution:
    @pytest.fixture
    def tool(self) -> WebFetchTool:
        return WebFetchTool(timeout=5.0, max_bytes=10_000)

    async def test_fetch_public_site(self, tool: WebFetchTool):
        result = await tool.execute("https://httpbin.org/get")

        assert result.success is True
        assert "200" in result.output
        assert result.metadata["status_code"] == 200

    async def test_fetch_404(self, tool: WebFetchTool):
        result = await tool.execute("https://httpbin.org/status/404")

        assert result.success is False
        assert result.metadata["status_code"] == 404

    async def test_ssrf_blocked(self, tool: WebFetchTool):
        result = await tool.execute("http://127.0.0.1:8080/admin")

        assert result.success is False
        assert "blocked" in result.error.lower() or "private" in result.error.lower()

    async def test_head_request(self, tool: WebFetchTool):
        result = await tool.execute("https://httpbin.org/get", method="HEAD")

        assert result.success is True
        # HEAD should not have body
        assert "Body:" not in result.output or result.output.split("Body:")[-1].strip() == ""

    async def test_content_truncation(self, tool: WebFetchTool):
        tool._max_bytes = 100
        result = await tool.execute("https://httpbin.org/bytes/1000")

        assert result.success is True
        assert "truncated" in result.output.lower()


class TestRedirectSSRF:
    """Test redirect SSRF protection."""

    def test_validate_url_public(self):
        valid, error = validate_url_for_ssrf("https://httpbin.org/get")
        assert valid is True

    def test_validate_url_private(self):
        valid, error = validate_url_for_ssrf("http://192.168.1.1/admin")
        assert valid is False
        assert "private" in error.lower() or "blocked" in error.lower()

    def test_validate_url_localhost(self):
        valid, error = validate_url_for_ssrf("http://localhost/admin")
        assert valid is False

    @pytest.mark.asyncio
    async def test_redirect_hook_blocks_private(self):
        """Test that redirect hook blocks redirects to private IPs."""
        from unittest.mock import MagicMock

        # Mock a redirect response to localhost
        response = MagicMock()
        response.is_redirect = True
        response.headers = {"location": "http://127.0.0.1/evil"}

        with pytest.raises(SSRFBlockedError):
            await check_redirect_ssrf(response)

    @pytest.mark.asyncio
    async def test_redirect_hook_allows_public(self):
        """Test that redirect hook allows redirects to public IPs."""
        from unittest.mock import MagicMock

        response = MagicMock()
        response.is_redirect = True
        response.headers = {"location": "https://httpbin.org/get"}

        # Should not raise
        await check_redirect_ssrf(response)

    @pytest.mark.asyncio
    async def test_redirect_hook_allows_relative(self):
        """Test that redirect hook allows relative URLs."""
        from unittest.mock import MagicMock

        response = MagicMock()
        response.is_redirect = True
        response.headers = {"location": "/other-path"}

        # Should not raise (relative URLs stay on same host)
        await check_redirect_ssrf(response)
