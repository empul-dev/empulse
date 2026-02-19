from pydantic import BaseModel, Field


class EmbyNowPlayingItem(BaseModel):
    id: str = Field(alias="Id", default="")
    name: str = Field(alias="Name", default="")
    type: str = Field(alias="Type", default="")
    series_name: str | None = Field(alias="SeriesName", default=None)
    series_id: str | None = Field(alias="SeriesId", default=None)
    parent_index_number: int | None = Field(alias="ParentIndexNumber", default=None)
    index_number: int | None = Field(alias="IndexNumber", default=None)
    production_year: int | None = Field(alias="ProductionYear", default=None)
    run_time_ticks: int | None = Field(alias="RunTimeTicks", default=None)

    model_config = {"populate_by_name": True}


class EmbyPlayState(BaseModel):
    position_ticks: int | None = Field(alias="PositionTicks", default=0)
    is_paused: bool = Field(alias="IsPaused", default=False)
    play_method: str | None = Field(alias="PlayMethod", default=None)

    model_config = {"populate_by_name": True}


class EmbyTranscodingInfo(BaseModel):
    video_codec: str | None = Field(alias="VideoCodec", default=None)
    audio_codec: str | None = Field(alias="AudioCodec", default=None)
    transcode_reasons: list[str] = Field(alias="TranscodeReasons", default_factory=list)

    model_config = {"populate_by_name": True}


class EmbySessionInfo(BaseModel):
    id: str = Field(alias="Id", default="")
    user_id: str | None = Field(alias="UserId", default=None)
    user_name: str | None = Field(alias="UserName", default=None)
    client: str | None = Field(alias="Client", default=None)
    device_name: str | None = Field(alias="DeviceName", default=None)
    device_id: str | None = Field(alias="DeviceId", default=None)
    remote_end_point: str | None = Field(alias="RemoteEndPoint", default=None)
    now_playing_item: EmbyNowPlayingItem | None = Field(alias="NowPlayingItem", default=None)
    play_state: EmbyPlayState | None = Field(alias="PlayState", default=None)
    transcoding_info: EmbyTranscodingInfo | None = Field(alias="TranscodingInfo", default=None)

    model_config = {"populate_by_name": True}


class EmbyUser(BaseModel):
    id: str = Field(alias="Id", default="")
    name: str = Field(alias="Name", default="")
    has_password: bool = Field(alias="HasPassword", default=False)
    primary_image_tag: str | None = Field(alias="PrimaryImageTag", default=None)

    class Policy(BaseModel):
        is_administrator: bool = Field(alias="IsAdministrator", default=False)
        model_config = {"populate_by_name": True}

    policy: Policy | None = Field(alias="Policy", default=None)

    model_config = {"populate_by_name": True}


class EmbyLibrary(BaseModel):
    id: str = Field(alias="Id", default="")
    name: str = Field(alias="Name", default="")
    collection_type: str | None = Field(alias="CollectionType", default=None)

    model_config = {"populate_by_name": True}
