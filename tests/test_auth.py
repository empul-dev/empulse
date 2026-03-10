import time
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from empulse.web.auth import (
    create_session_token, verify_session_token, hash_token,
    _encode_user_id, _decode_user_id,
)


class TestTokens:
    def test_create_and_verify(self):
        token = create_session_token("secret123", "user-abc", "admin")
        result = verify_session_token(token, "secret123")
        assert result is not None
        assert result.user_id == "user-abc"
        assert result.role == "admin"

    def test_viewer_role(self):
        token = create_session_token("secret123", "user-xyz", "viewer")
        result = verify_session_token(token, "secret123")
        assert result is not None
        assert result.user_id == "user-xyz"
        assert result.role == "viewer"

    def test_tampered_token(self):
        token = create_session_token("secret123", "user-abc", "admin")
        tampered = token[:-5] + "xxxxx"
        assert verify_session_token(tampered, "secret123") is None

    def test_wrong_secret(self):
        token = create_session_token("secret123", "user-abc", "admin")
        assert verify_session_token(token, "wrongsecret") is None

    def test_expired_token(self):
        """Tokens older than 7 days should be rejected."""
        import hmac
        import hashlib
        old_ts = str(int(time.time()) - 8 * 24 * 3600)
        nonce = "a" * 32
        uid_b64 = _encode_user_id("user1")
        role = "admin"
        payload = f"{old_ts}.{nonce}.{uid_b64}.{role}"
        sig = hmac.new(b"secret", payload.encode(), hashlib.sha256).hexdigest()
        token = f"{payload}.{sig}"
        assert verify_session_token(token, "secret") is None

    def test_invalid_format(self):
        assert verify_session_token("garbage", "secret") is None
        assert verify_session_token("", "secret") is None
        # Old 3-part tokens are automatically rejected
        assert verify_session_token("123.abc.def", "secret") is None

    def test_old_3part_token_rejected(self):
        """Legacy 3-part tokens must be rejected."""
        # Simulate old-style token
        import hmac
        import hashlib
        ts = str(int(time.time()))
        nonce = "a" * 32
        payload = f"{ts}.{nonce}"
        sig = hmac.new(b"secret", payload.encode(), hashlib.sha256).hexdigest()
        old_token = f"{payload}.{sig}"
        assert verify_session_token(old_token, "secret") is None

    def test_invalid_role_rejected(self):
        """Tokens with invalid roles should be rejected."""
        import hmac
        import hashlib
        ts = str(int(time.time()))
        nonce = "a" * 32
        uid_b64 = _encode_user_id("user1")
        role = "superuser"
        payload = f"{ts}.{nonce}.{uid_b64}.{role}"
        sig = hmac.new(b"secret", payload.encode(), hashlib.sha256).hexdigest()
        token = f"{payload}.{sig}"
        assert verify_session_token(token, "secret") is None

    def test_role_tamper_detected(self):
        """Changing role in token invalidates signature."""
        token = create_session_token("secret123", "user-abc", "viewer")
        parts = token.split(".")
        parts[3] = "admin"
        tampered = ".".join(parts)
        assert verify_session_token(tampered, "secret123") is None

    def test_user_id_encoding_roundtrip(self):
        for uid in ["abc-123", "__admin__", "a" * 64, "user@host"]:
            assert _decode_user_id(_encode_user_id(uid)) == uid

    def test_hash_token(self):
        token = "some.test.token.value.sig"
        h = hash_token(token)
        assert len(h) == 64  # SHA-256 hex
        assert hash_token(token) == h  # deterministic


def _make_test_app(auth_password="", emby_api_key="", secret_key="testsecret"):
    """Helper to create a test app with given settings."""
    with patch("empulse.app.init_db", new_callable=AsyncMock), \
         patch("empulse.app.settings") as mock_settings:
        mock_settings.emby_api_key = emby_api_key
        mock_settings.emby_url = "http://localhost:8096"
        mock_settings.poll_interval = 10
        mock_settings.db_path = ":memory:"
        mock_settings.auth_password = auth_password
        mock_settings.secret_key = secret_key

        from empulse.app import create_app
        return create_app(), mock_settings


class TestMiddleware:
    @pytest.mark.asyncio
    async def test_no_auth_redirects_to_login(self):
        """When no password/api_key is set, unauthenticated requests still redirect to login."""
        with patch("empulse.app.init_db", new_callable=AsyncMock), \
             patch("empulse.app.settings") as mock_settings:
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = ""
            mock_settings.secret_key = "testsecret"

            from empulse.app import create_app
            app = create_app()

            import aiosqlite
            from empulse.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            with patch("empulse.web.router.get_db", return_value=db), \
                 patch("empulse.web.api.get_db", return_value=db), \
                 patch("empulse.database.get_db", return_value=db):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
                    r = await ac.get("/")
                    assert r.status_code == 302
                    assert "/login" in r.headers.get("location", "")

                    # Login page itself should still be accessible
                    r = await ac.get("/login")
                    assert r.status_code == 200

            await db.close()

    @pytest.mark.asyncio
    async def test_password_redirects_to_login(self):
        """When password is set, unauthenticated requests redirect to login."""
        with patch("empulse.app.init_db", new_callable=AsyncMock), \
             patch("empulse.app.settings") as mock_settings:
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = "testpass"
            mock_settings.secret_key = "testsecret"

            from empulse.app import create_app
            app = create_app()

            import aiosqlite
            from empulse.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            with patch("empulse.web.router.get_db", return_value=db), \
                 patch("empulse.web.api.get_db", return_value=db), \
                 patch("empulse.database.get_db", return_value=db):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
                    r = await ac.get("/")
                    assert r.status_code == 302
                    assert "/login" in r.headers.get("location", "")

                    # Login page itself should be accessible
                    r = await ac.get("/login")
                    assert r.status_code == 200

            await db.close()

    @pytest.mark.asyncio
    async def test_fallback_login_success(self):
        """AUTH_PASSWORD fallback login works when no username given."""
        with patch("empulse.app.init_db", new_callable=AsyncMock), \
             patch("empulse.app.settings") as mock_settings:
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = "testpass"
            mock_settings.secret_key = "testsecret"

            from empulse.app import create_app
            app = create_app()

            import aiosqlite
            from empulse.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            with patch("empulse.web.router.get_db", return_value=db), \
                 patch("empulse.web.api.get_db", return_value=db), \
                 patch("empulse.web.router.settings", mock_settings), \
                 patch("empulse.database.get_db", return_value=db):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
                    r = await ac.post("/login", data={"username": "", "password": "testpass"}, headers={"Origin": "http://test"})
                    assert r.status_code == 302
                    assert r.headers.get("location") == "/"
                    assert "empulse_session" in r.headers.get("set-cookie", "")

            await db.close()

    @pytest.mark.asyncio
    async def test_login_failure(self):
        """Wrong password shows error."""
        with patch("empulse.app.init_db", new_callable=AsyncMock), \
             patch("empulse.app.settings") as mock_settings:
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = "testpass"
            mock_settings.secret_key = "testsecret"

            from empulse.app import create_app
            app = create_app()

            import aiosqlite
            from empulse.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            with patch("empulse.web.router.get_db", return_value=db), \
                 patch("empulse.web.api.get_db", return_value=db), \
                 patch("empulse.web.router.settings", mock_settings), \
                 patch("empulse.database.get_db", return_value=db):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    r = await ac.post("/login", data={"username": "", "password": "wrong"}, headers={"Origin": "http://test"}, follow_redirects=False)
                    assert r.status_code == 302
                    assert "/login?error=invalid" in r.headers["location"]

            await db.close()

    @pytest.mark.asyncio
    async def test_logout_revokes_session(self):
        """Logout revokes the session and redirects to login."""
        with patch("empulse.app.init_db", new_callable=AsyncMock), \
             patch("empulse.app.settings") as mock_settings:
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = "testpass"
            mock_settings.secret_key = "testsecret"

            from empulse.app import create_app
            app = create_app()

            import aiosqlite
            from empulse.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            with patch("empulse.web.router.get_db", return_value=db), \
                 patch("empulse.web.api.get_db", return_value=db), \
                 patch("empulse.web.router.settings", mock_settings), \
                 patch("empulse.database.get_db", return_value=db):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
                    # Login first
                    r = await ac.post("/login", data={"username": "", "password": "testpass"}, headers={"Origin": "http://test"})
                    assert r.status_code == 302
                    cookie = r.cookies.get("empulse_session")
                    assert cookie

                    # Logout (POST since V-08 fix)
                    ac.cookies.set("empulse_session", cookie)
                    r = await ac.post("/logout", headers={"Origin": "http://test"})
                    assert r.status_code == 302
                    assert "/login" in r.headers["location"]

                    # Old token should now be rejected (session revoked in DB)
                    r = await ac.get("/", follow_redirects=False)
                    assert r.status_code == 302
                    assert "/login" in r.headers["location"]

            await db.close()

    @pytest.mark.asyncio
    async def test_viewer_blocked_from_settings(self):
        """Viewer role users cannot access admin-only routes."""
        with patch("empulse.app.init_db", new_callable=AsyncMock), \
             patch("empulse.app.settings") as mock_settings:
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = "testpass"
            mock_settings.secret_key = "testsecret"

            from empulse.app import create_app
            app = create_app()

            import aiosqlite
            from empulse.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            # Create a viewer token directly
            token = create_session_token("testsecret", "viewer-user", "viewer")
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            expires = now + timedelta(days=7)
            await db.execute(
                """INSERT INTO login_sessions
                   (token_hash, emby_user_id, username, role, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [hash_token(token), "viewer-user", "TestViewer", "viewer",
                 now.isoformat(), expires.isoformat()],
            )
            await db.commit()

            with patch("empulse.web.router.get_db", return_value=db), \
                 patch("empulse.web.api.get_db", return_value=db), \
                 patch("empulse.database.get_db", return_value=db):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
                    ac.cookies.set("empulse_session", token)

                    # Dashboard should work
                    r = await ac.get("/")
                    assert r.status_code == 200

                    # Settings should be blocked (403)
                    r = await ac.get("/settings")
                    assert r.status_code == 403

                    # Manual update checks should also be blocked
                    r = await ac.post("/api/update-check", headers={"Origin": "http://test"})
                    assert r.status_code == 403

            await db.close()

    @pytest.mark.asyncio
    async def test_disabled_emby_user_rejected(self):
        """Non-admin Emby users are disabled by default and can't log in."""
        with patch("empulse.app.init_db", new_callable=AsyncMock), \
             patch("empulse.app.settings") as mock_settings:
            mock_settings.emby_api_key = "testkey"
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = ""
            mock_settings.secret_key = "testsecret"

            from empulse.app import create_app
            app = create_app()

            import aiosqlite
            from empulse.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            # Mock Emby auth to return a non-admin user
            mock_emby = AsyncMock()
            mock_emby.authenticate_user = AsyncMock(return_value={
                "user_id": "emby-user-1",
                "username": "RegularUser",
                "is_admin": False,
            })
            app.state.emby_client = mock_emby

            with patch("empulse.web.router.get_db", return_value=db), \
                 patch("empulse.web.api.get_db", return_value=db), \
                 patch("empulse.web.router.settings", mock_settings), \
                 patch("empulse.database.get_db", return_value=db):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
                    r = await ac.post("/login", data={"username": "RegularUser", "password": "pass"}, headers={"Origin": "http://test"})
                    assert r.status_code == 302
                    assert "/login?error=disabled" in r.headers["location"]

            await db.close()

    @pytest.mark.asyncio
    async def test_emby_admin_auto_enabled(self):
        """Emby admin users are auto-enabled and can log in immediately."""
        with patch("empulse.app.init_db", new_callable=AsyncMock), \
             patch("empulse.app.settings") as mock_settings:
            mock_settings.emby_api_key = "testkey"
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = ""
            mock_settings.secret_key = "testsecret"

            from empulse.app import create_app
            app = create_app()

            import aiosqlite
            from empulse.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            mock_emby = AsyncMock()
            mock_emby.authenticate_user = AsyncMock(return_value={
                "user_id": "emby-admin-1",
                "username": "AdminUser",
                "is_admin": True,
            })
            app.state.emby_client = mock_emby

            with patch("empulse.web.router.get_db", return_value=db), \
                 patch("empulse.web.api.get_db", return_value=db), \
                 patch("empulse.web.router.settings", mock_settings), \
                 patch("empulse.database.get_db", return_value=db):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
                    r = await ac.post("/login", data={"username": "AdminUser", "password": "pass"}, headers={"Origin": "http://test"})
                    assert r.status_code == 302
                    assert r.headers.get("location") == "/"
                    assert "empulse_session" in r.headers.get("set-cookie", "")

            await db.close()

    @pytest.mark.asyncio
    async def test_admin_can_enable_user(self):
        """Admin can enable a disabled user via API, and disabled user gets sessions revoked."""
        with patch("empulse.app.init_db", new_callable=AsyncMock), \
             patch("empulse.app.settings") as mock_settings:
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.poll_interval = 10
            mock_settings.db_path = ":memory:"
            mock_settings.auth_password = "testpass"
            mock_settings.secret_key = "testsecret"

            from empulse.app import create_app
            app = create_app()

            import aiosqlite
            from empulse.database import SCHEMA
            db = await aiosqlite.connect(":memory:")
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()

            # Create admin token
            admin_token = create_session_token("testsecret", "__admin__", "admin")
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            expires = now + timedelta(days=7)
            await db.execute(
                """INSERT INTO login_sessions
                   (token_hash, emby_user_id, username, role, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [hash_token(admin_token), None, "Admin", "admin",
                 now.isoformat(), expires.isoformat()],
            )
            # Create a disabled user
            await db.execute(
                """INSERT INTO users (emby_user_id, username, is_admin, enabled)
                   VALUES (?, ?, ?, ?)""",
                ["user-1", "TestUser", 0, 0],
            )
            await db.commit()

            with patch("empulse.web.router.get_db", return_value=db), \
                 patch("empulse.web.api.get_db", return_value=db), \
                 patch("empulse.database.get_db", return_value=db):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    ac.cookies.set("empulse_session", admin_token)

                    # Enable the user
                    r = await ac.put("/api/users/user-1/enabled",
                                     json={"enabled": True},
                                     headers={"Origin": "http://test"})
                    assert r.status_code == 200
                    data = r.json()
                    assert data["enabled"] is True

                    # Verify in DB
                    cursor = await db.execute(
                        "SELECT enabled FROM users WHERE emby_user_id = ?", ["user-1"])
                    row = await cursor.fetchone()
                    assert row[0] == 1

                    # Disable the user
                    r = await ac.put("/api/users/user-1/enabled",
                                     json={"enabled": False},
                                     headers={"Origin": "http://test"})
                    assert r.status_code == 200

                    cursor = await db.execute(
                        "SELECT enabled FROM users WHERE emby_user_id = ?", ["user-1"])
                    row = await cursor.fetchone()
                    assert row[0] == 0

            await db.close()
