import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from empulse.update_checker import (
    _parse_version,
    _is_newer,
    UpdateChecker,
)


class TestParseVersion:
    def test_simple(self):
        assert _parse_version("0.1.0") == (0, 1, 0)

    def test_with_v_prefix(self):
        assert _parse_version("v1.2.3") == (1, 2, 3)

    def test_two_part(self):
        assert _parse_version("1.0") == (1, 0)

    def test_whitespace(self):
        assert _parse_version("  v0.2.0  ") == (0, 2, 0)

    def test_invalid_returns_none(self):
        assert _parse_version("not-a-version") is None

    def test_empty_returns_none(self):
        assert _parse_version("") is None

    def test_dev_returns_none(self):
        assert _parse_version("dev") is None


class TestIsNewer:
    def test_newer(self):
        assert _is_newer("0.2.0", "0.1.0") is True

    def test_same(self):
        assert _is_newer("0.1.0", "0.1.0") is False

    def test_older(self):
        assert _is_newer("0.1.0", "0.2.0") is False

    def test_major_bump(self):
        assert _is_newer("1.0.0", "0.9.9") is True

    def test_patch_bump(self):
        assert _is_newer("0.1.1", "0.1.0") is True

    def test_with_v_prefix(self):
        assert _is_newer("v0.2.0", "v0.1.0") is True

    def test_invalid_latest(self):
        assert _is_newer("bad", "0.1.0") is False

    def test_invalid_current(self):
        assert _is_newer("0.2.0", "dev") is False

    def test_both_invalid(self):
        assert _is_newer("bad", "dev") is False


class TestUpdateChecker:
    async def test_check_once_update_available(self):
        checker = UpdateChecker("0.1.0")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "tag_name": "v0.2.0",
            "html_url": "https://github.com/empul-dev/empulse/releases/tag/v0.2.0",
            "body": "New release",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("empulse.update_checker.httpx.AsyncClient", return_value=mock_client):
            info = await checker.check_once()

        assert info.update_available is True
        assert info.latest_version == "0.2.0"
        assert info.current_version == "0.1.0"
        assert "v0.2.0" in info.release_url
        assert info.last_checked_at
        assert info.last_error == ""
        assert info.checking is False
        assert checker.info is info

    async def test_check_once_no_update(self):
        checker = UpdateChecker("0.2.0")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "tag_name": "v0.2.0",
            "html_url": "https://github.com/empul-dev/empulse/releases/tag/v0.2.0",
            "body": "",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("empulse.update_checker.httpx.AsyncClient", return_value=mock_client):
            info = await checker.check_once()

        assert info.update_available is False
        assert info.latest_version == "0.2.0"

    async def test_check_once_http_error_raises(self):
        """check_once propagates exceptions (run() catches them)."""
        import httpx

        checker = UpdateChecker("0.1.0")
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("empulse.update_checker.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await checker.check_once()

        # info should retain failure metadata for the UI
        assert checker.info.update_available is False
        assert checker.info.last_checked_at
        assert checker.info.last_error
        assert checker.info.checking is False

    async def test_default_info(self):
        checker = UpdateChecker("1.0.0")
        assert checker.info.update_available is False
        assert checker.info.current_version == "1.0.0"
        assert checker.info.latest_version == ""
        assert checker.info.last_checked_at == ""
        assert checker.info.last_error == ""


class TestGetVersion:
    def test_returns_installed_version(self):
        from empulse.app import get_version

        with patch("empulse.app.pkg_version", return_value="0.1.0"):
            assert get_version() == "0.1.0"

    def test_returns_dev_when_not_installed(self):
        from empulse.app import get_version, PackageNotFoundError

        with patch("empulse.app.pkg_version", side_effect=PackageNotFoundError("empulse")):
            assert get_version() == "dev"
