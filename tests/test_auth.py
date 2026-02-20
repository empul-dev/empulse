import time
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from emtulli.web.auth import create_session_token, verify_session_token


class TestTokens:
    def test_create_and_verify(self):
        token = create_session_token("secret123")
        assert verify_session_token(token, "secret123")

    def test_tampered_token(self):
        token = create_session_token("secret123")
        tampered = token[:-5] + "xxxxx"
        assert not verify_session_token(tampered, "secret123")

    def test_wrong_secret(self):
        token = create_session_token("secret123")
        assert not verify_session_token(token, "wrongsecret")

    def test_expired_token(self):
        """Tokens older than 30 days should be rejected."""
        import hmac
        import hashlib
        old_ts = str(int(time.time()) - 31 * 24 * 3600)
        sig = hmac.new(b"secret", old_ts.encode(), hashlib.sha256).hexdigest()
        token = f"{old_ts}.{sig}"
        assert not verify_session_token(token, "secret")

    def test_invalid_format(self):
        assert not verify_session_token("garbage", "secret")
        assert not verify_session_token("", "secret")
        assert not verify_session_token("no.dot.valid", "secret")


class TestMiddleware:
    @pytest.mark.asyncio
    async def test_no_password_transparent(self):
        """When no password is set, all routes are accessible."""
        with patch("emtulli.app.init_db", new_callable=AsyncMock), \
             patch("emtulli.app.settings") as mock_settings:
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = ""
            mock_settings.secret_key = ""

            from emtulli.app import create_app
            app = create_app()

            import aiosqlite
            from emtulli.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            with patch("emtulli.web.router.get_db", return_value=db), \
                 patch("emtulli.web.api.get_db", return_value=db):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    r = await ac.get("/")
                    assert r.status_code == 200

            await db.close()

    @pytest.mark.asyncio
    async def test_login_success(self):
        """Correct password sets cookie and redirects to /."""
        with patch("emtulli.app.init_db", new_callable=AsyncMock), \
             patch("emtulli.app.settings") as mock_settings:
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = "testpass"
            mock_settings.secret_key = "testsecret"

            from emtulli.app import create_app
            app = create_app()

            import aiosqlite
            from emtulli.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            with patch("emtulli.web.router.get_db", return_value=db), \
                 patch("emtulli.web.api.get_db", return_value=db), \
                 patch("emtulli.web.router.settings", mock_settings):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
                    r = await ac.post("/login", data={"password": "testpass"})
                    assert r.status_code == 302
                    assert r.headers.get("location") == "/"
                    assert "emtulli_session" in r.headers.get("set-cookie", "")

            await db.close()

    @pytest.mark.asyncio
    async def test_login_failure(self):
        """Wrong password shows error."""
        with patch("emtulli.app.init_db", new_callable=AsyncMock), \
             patch("emtulli.app.settings") as mock_settings:
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = "testpass"
            mock_settings.secret_key = "testsecret"

            from emtulli.app import create_app
            app = create_app()

            import aiosqlite
            from emtulli.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            with patch("emtulli.web.router.get_db", return_value=db), \
                 patch("emtulli.web.api.get_db", return_value=db), \
                 patch("emtulli.web.router.settings", mock_settings):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    r = await ac.post("/login", data={"password": "wrong"}, follow_redirects=False)
                    assert r.status_code == 302
                    assert "/login?error=invalid" in r.headers["location"]

            await db.close()

    @pytest.mark.asyncio
    async def test_password_redirects_to_login(self):
        """When password is set, unauthenticated requests redirect to login."""
        with patch("emtulli.app.init_db", new_callable=AsyncMock), \
             patch("emtulli.app.settings") as mock_settings:
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = "testpass"
            mock_settings.secret_key = "testsecret"

            from emtulli.app import create_app
            app = create_app()

            import aiosqlite
            from emtulli.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            with patch("emtulli.web.router.get_db", return_value=db), \
                 patch("emtulli.web.api.get_db", return_value=db):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
                    r = await ac.get("/")
                    assert r.status_code == 302
                    assert "/login" in r.headers.get("location", "")

                    # Login page itself should be accessible
                    r = await ac.get("/login")
                    assert r.status_code == 200

            await db.close()
