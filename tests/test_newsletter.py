import pytest


class TestNewsletter:
    @pytest.mark.asyncio
    async def test_config_crud(self, db):
        from empulse.newsletter import get_newsletter_config, save_newsletter_config
        # Initially empty
        config = await get_newsletter_config(db)
        assert config is None

        # Save
        await save_newsletter_config(db, {
            "enabled": True,
            "schedule": "weekly",
            "day_of_week": 1,
            "hour": 10,
            "recently_added_days": 7,
            "recently_added_limit": 20,
            "include_stats": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_user": "user",
            "smtp_pass": "pass",
            "smtp_tls": True,
            "from_addr": "from@example.com",
            "to_addrs": "to@example.com",
        })

        config = await get_newsletter_config(db)
        assert config is not None
        assert config["enabled"] == 1
        assert config["schedule"] == "weekly"

        # Update
        await save_newsletter_config(db, {
            "enabled": False,
            "schedule": "daily",
            "day_of_week": 0,
            "hour": 8,
            "recently_added_days": 3,
            "recently_added_limit": 10,
            "include_stats": False,
            "smtp_host": "mail.example.com",
            "smtp_port": 465,
            "smtp_user": "",
            "smtp_pass": "",
            "smtp_tls": False,
            "from_addr": "",
            "to_addrs": "",
        })
        config = await get_newsletter_config(db)
        assert config["schedule"] == "daily"
        assert config["enabled"] == 0

    @pytest.mark.asyncio
    async def test_config_preserves_masked_password(self, db):
        from empulse.newsletter import get_newsletter_config, save_newsletter_config

        await save_newsletter_config(db, {
            "enabled": True,
            "schedule": "weekly",
            "day_of_week": 1,
            "hour": 10,
            "recently_added_days": 7,
            "recently_added_limit": 20,
            "include_stats": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_user": "user",
            "smtp_pass": "original-secret",
            "smtp_tls": True,
            "from_addr": "from@example.com",
            "to_addrs": "to@example.com",
        })

        await save_newsletter_config(db, {
            "enabled": True,
            "schedule": "daily",
            "day_of_week": 0,
            "hour": 8,
            "recently_added_days": 3,
            "recently_added_limit": 10,
            "include_stats": False,
            "smtp_host": "mail.example.com",
            "smtp_port": 465,
            "smtp_user": "user",
            "smtp_pass": "***",
            "smtp_tls": False,
            "from_addr": "from@example.com",
            "to_addrs": "to@example.com",
        })

        config = await get_newsletter_config(db)
        from empulse.crypto import decrypt_secret

        # Stored encrypted at rest (I-1) — decrypt to compare the real value.
        assert config["smtp_pass"] != "original-secret"
        assert decrypt_secret(config["smtp_pass"]) == "original-secret"
        assert config["schedule"] == "daily"

    @pytest.mark.asyncio
    async def test_build_newsletter_html(self, db):
        from empulse.newsletter import build_newsletter_html
        config = {"recently_added_days": 7, "recently_added_limit": 10, "include_stats": 1}
        html = await build_newsletter_html(db, config)
        assert "Empulse Newsletter" in html
        assert "Watch Statistics" in html

    @pytest.mark.asyncio
    async def test_build_newsletter_html_recently_added_layout(self, db):
        from empulse.newsletter import build_newsletter_html

        class FakeEmbyClient:
            async def get_recently_added(self, limit=10):
                return [
                    {
                        "Id": "movie-1",
                        "Name": "Arco",
                        "Type": "Movie",
                        "ProductionYear": 2025,
                        "RunTimeTicks": 88 * 600_000_000,
                        "Genres": ["Animation", "Science Fiction"],
                        "CommunityRating": 9.2,
                        "Taglines": ["What if rainbows were people from the future traveling in time?"],
                        "Overview": "Als der Junge Arco aus einer fernen Zukunft zufaellig in die Welt der Iris stuerzt.",
                        "DateCreated": "2026-03-08T12:00:00.0000000Z",
                    },
                    {
                        "Id": "episode-1",
                        "SeriesId": "series-1",
                        "SeriesName": "Dark Winds - Der Wind des Boesen",
                        "Name": "Folge #4.3",
                        "Type": "Episode",
                        "ProductionYear": 2022,
                        "RunTimeTicks": 49 * 600_000_000,
                        "Genres": ["Krimi", "Drama"],
                        "CommunityRating": 8.0,
                        "Overview": "Eine neue Spur fuehrt tiefer in den Fall.",
                        "ParentIndexNumber": 4,
                        "IndexNumber": 3,
                        "DateCreated": "2026-03-08T11:00:00.0000000Z",
                    },
                    {
                        "Id": "episode-2",
                        "SeriesId": "series-1",
                        "SeriesName": "Dark Winds - Der Wind des Boesen",
                        "Name": "Folge #4.2",
                        "Type": "Episode",
                        "ProductionYear": 2022,
                        "RunTimeTicks": 49 * 600_000_000,
                        "Genres": ["Krimi", "Drama"],
                        "CommunityRating": 8.0,
                        "Overview": "Die Ermittlungen gehen weiter.",
                        "ParentIndexNumber": 4,
                        "IndexNumber": 2,
                        "DateCreated": "2026-03-07T11:00:00.0000000Z",
                    },
                ]

            async def get_image_data_url(self, item_id, image_type="Primary", max_width=300):
                return "data:image/jpeg;base64,ZmFrZQ=="

        html = await build_newsletter_html(
            db,
            {"recently_added_days": 7, "recently_added_limit": 10, "include_stats": 0},
            FakeEmbyClient(),
        )

        assert "Recently Added Movies" in html
        assert "1 movie" in html
        assert "Arco" in html
        assert "Animation" in html
        assert "Science Fiction" in html
        assert "Recently Added TV Shows" in html
        assert "1 show / 2 episodes" in html
        assert "Dark Winds - Der Wind des Boesen" in html
        assert "2 episodes" in html
        assert "Season 4 &middot; Episodes 02-03" in html
        assert "data:image/jpeg;base64,ZmFrZQ==" in html


async def test_saved_newsletter_still_sends_with_encrypted_password(db, monkeypatch):
    from unittest.mock import Mock

    from empulse.newsletter import (
        get_newsletter_config, save_newsletter_config, send_newsletter,
    )

    smtp_send = Mock()
    monkeypatch.setattr("empulse.newsletter._smtp_send", smtp_send)
    await save_newsletter_config(db, {
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_user": "sender",
        "smtp_pass": "newsletter-password",
        "smtp_tls": True,
        "from_addr": "sender@example.com",
        "to_addrs": "reader@example.com",
        "include_stats": True,
    })
    config = await get_newsletter_config(db)
    assert config["smtp_pass"].startswith("enc:v1:")
    success, message = await send_newsletter(db, config)
    assert success, message
    smtp_send.assert_called_once()
    args = smtp_send.call_args.args
    assert args[:7] == (
        "smtp.example.com", 587, "sender", "newsletter-password", True,
        "sender@example.com", ["reader@example.com"],
    )
    assert args[7]["Subject"] == "Empulse Newsletter"
    assert "Watch Statistics" in args[7].get_payload()[1].get_payload(decode=True).decode()
    assert (await get_newsletter_config(db))["last_sent"]
