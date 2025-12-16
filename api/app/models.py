from pydantic import BaseModel
from typing import Optional

class SearchRequest(BaseModel):
    query: str

class TrackRequest(BaseModel):
    track_uri: str
    track_name: Optional[str] = None
    artist: Optional[str] = None
    album_art: Optional[str] = None

class PlaylistInfo(BaseModel):
    name: str
    color: str

class NowPlayingResponse(BaseModel):
    is_playing: bool
    song_name: Optional[str] = None
    artist: Optional[str] = None
    album_art: Optional[str] = None
    duration_ms: Optional[int] = None
    progress_ms: Optional[int] = None
    time_left_ms: Optional[int] = None
    track_uri: Optional[str] = None
