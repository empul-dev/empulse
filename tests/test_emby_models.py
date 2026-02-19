from emtulli.emby.models import EmbySessionInfo, EmbyUser, EmbyLibrary


class TestEmbySessionInfo:
    def test_parse_movie_session(self, sample_emby_session_data):
        s = EmbySessionInfo(**sample_emby_session_data)
        assert s.user_name == "TestUser"
        assert s.now_playing_item is not None
        assert s.now_playing_item.name == "Test Movie"
        assert s.now_playing_item.type == "Movie"
        assert s.play_state.position_ticks == 36000000000
        assert s.play_state.is_paused is False
        assert s.play_state.play_method == "DirectPlay"
        assert s.transcoding_info is None

    def test_parse_episode_session(self, sample_emby_episode_data):
        s = EmbySessionInfo(**sample_emby_episode_data)
        assert s.user_name == "AnotherUser"
        assert s.now_playing_item.series_name == "Test Show"
        assert s.now_playing_item.parent_index_number == 1
        assert s.now_playing_item.index_number == 1
        assert s.transcoding_info is not None
        assert s.transcoding_info.video_codec == "h264"

    def test_parse_idle_session(self):
        """Session with no NowPlayingItem."""
        s = EmbySessionInfo(**{
            "Id": "idle1",
            "UserName": "IdleUser",
            "Client": "Emby Web",
            "DeviceName": "Firefox",
        })
        assert s.now_playing_item is None
        assert s.play_state is None


class TestEmbyUser:
    def test_parse_user(self):
        u = EmbyUser(**{
            "Id": "u1",
            "Name": "admin",
            "HasPassword": True,
            "PrimaryImageTag": "abc123",
            "Policy": {"IsAdministrator": True},
        })
        assert u.name == "admin"
        assert u.policy.is_administrator is True

    def test_parse_user_no_policy(self):
        u = EmbyUser(**{"Id": "u2", "Name": "guest"})
        assert u.policy is None


class TestEmbyLibrary:
    def test_parse_library(self):
        lib = EmbyLibrary(**{
            "Id": "lib1",
            "Name": "Movies",
            "CollectionType": "movies",
        })
        assert lib.name == "Movies"
        assert lib.collection_type == "movies"
