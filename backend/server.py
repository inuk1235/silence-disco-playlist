from fastapi import FastAPI, APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
import httpx
import base64
import urllib.parse

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Spotify configuration
SPOTIFY_CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID', '')
SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIFY_CLIENT_SECRET', '')
SPOTIFY_REDIRECT_URI = os.environ.get('SPOTIFY_REDIRECT_URI', '')
SPOTIFY_PLAYLIST_ID = os.environ.get('SPOTIFY_PLAYLIST_ID', '')

SPOTIFY_AUTH_URL = 'https://accounts.spotify.com/authorize'
SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token'
SPOTIFY_API_URL = 'https://api.spotify.com/v1'

# Cooldown: 1 hour in seconds
COOLDOWN_SECONDS = 3600

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Models
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

# Helper functions
async def get_stored_tokens():
    return await db.spotify_tokens.find_one({'_id': 'main'})

async def store_tokens(access_token: str, refresh_token: str, expires_in: int):
    expires_at = datetime.now(timezone.utc).timestamp() + expires_in - 60
    await db.spotify_tokens.update_one(
        {'_id': 'main'},
        {'$set': {'access_token': access_token, 'refresh_token': refresh_token, 'expires_at': expires_at}},
        upsert=True
    )

async def refresh_access_token():
    token_doc = await get_stored_tokens()
    if not token_doc or 'refresh_token' not in token_doc:
        raise HTTPException(status_code=401, detail="Not authenticated. Please visit /admin")
    
    auth_header = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    async with httpx.AsyncClient() as http_client:
        response = await http_client.post(
            SPOTIFY_TOKEN_URL,
            headers={'Authorization': f'Basic {auth_header}', 'Content-Type': 'application/x-www-form-urlencoded'},
            data={'grant_type': 'refresh_token', 'refresh_token': token_doc['refresh_token']}
        )
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Failed to refresh token")
        data = response.json()
        await store_tokens(data['access_token'], data.get('refresh_token', token_doc['refresh_token']), data['expires_in'])
        return data['access_token']

async def get_valid_access_token():
    token_doc = await get_stored_tokens()
    if not token_doc:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if datetime.now(timezone.utc).timestamp() >= token_doc.get('expires_at', 0):
        return await refresh_access_token()
    return token_doc['access_token']

async def spotify_request(method: str, endpoint: str, **kwargs):
    access_token = await get_valid_access_token()
    async with httpx.AsyncClient() as http_client:
        return await http_client.request(method, f"{SPOTIFY_API_URL}{endpoint}", headers={'Authorization': f'Bearer {access_token}'}, **kwargs)

async def check_cooldown(track_uri: str) -> tuple[bool, str]:
    """Check if track is in cooldown. Returns (can_add, error_message)"""
    track_id = track_uri.split(':')[-1] if ':' in track_uri else track_uri
    doc = await db.track_cooldown.find_one({'track_id': track_id})
    if not doc:
        return True, ""
    
    last_time = doc.get('timestamp')
    if not last_time:
        return True, ""
    
    # Handle different datetime formats
    if isinstance(last_time, str):
        last_time = datetime.fromisoformat(last_time.replace('Z', '+00:00'))
    elif last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
    time_diff = (now - last_time).total_seconds()
    if time_diff < COOLDOWN_SECONDS:
        mins_left = int((COOLDOWN_SECONDS - time_diff) / 60)
        return False, f"This song was played recently. Try again in {mins_left} minutes!"
    return True, ""

async def set_cooldown(track_uri: str):
    """Set cooldown timestamp for a track"""
    track_id = track_uri.split(':')[-1] if ':' in track_uri else track_uri
    await db.track_cooldown.update_one(
        {'track_id': track_id},
        {'$set': {'track_id': track_id, 'track_uri': track_uri, 'timestamp': datetime.now(timezone.utc)}},
        upsert=True
    )

async def add_guest_request(track_uri: str, track_name: str, artist: str, album_art: str):
    """Track a guest request"""
    await db.guest_requests.update_one(
        {'uri': track_uri},
        {'$set': {'uri': track_uri, 'name': track_name, 'artist': artist, 'album_art': album_art, 'requested_at': datetime.now(timezone.utc)}},
        upsert=True
    )

async def is_guest_request(track_uri: str) -> bool:
    doc = await db.guest_requests.find_one({'uri': track_uri})
    return doc is not None

async def is_in_cooldown(track_uri: str) -> bool:
    can_add, _ = await check_cooldown(track_uri)
    return not can_add

async def get_cooldown_minutes_left(track_uri: str) -> int:
    track_id = track_uri.split(':')[-1] if ':' in track_uri else track_uri
    doc = await db.track_cooldown.find_one({'track_id': track_id})
    if not doc:
        return 0
    last_time = doc.get('timestamp')
    if not last_time:
        return 0
    
    # Handle different datetime formats
    if isinstance(last_time, str):
        last_time = datetime.fromisoformat(last_time.replace('Z', '+00:00'))
    elif last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
    time_diff = (now - last_time).total_seconds()
    if time_diff < COOLDOWN_SECONDS:
        return int((COOLDOWN_SECONDS - time_diff) / 60)
    return 0

# Routes
@api_router.get("/")
async def root():
    return {"message": "Byron Bay Silent Disco API"}

@api_router.get("/spotify/auth")
async def spotify_auth():
    scope = "user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private"
    params = {
        'client_id': SPOTIFY_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': SPOTIFY_REDIRECT_URI,
        'scope': scope,
        'show_dialog': 'true'
    }
    return RedirectResponse(url=f"{SPOTIFY_AUTH_URL}?{urllib.parse.urlencode(params)}")

@api_router.get("/spotify/callback")
async def spotify_callback(code: str = Query(...), error: str = Query(None)):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    
    auth_header = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    async with httpx.AsyncClient() as http_client:
        response = await http_client.post(
            SPOTIFY_TOKEN_URL,
            headers={'Authorization': f'Basic {auth_header}', 'Content-Type': 'application/x-www-form-urlencoded'},
            data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': SPOTIFY_REDIRECT_URI}
        )
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange code for token")
        data = response.json()
        await store_tokens(data['access_token'], data['refresh_token'], data['expires_in'])
        return RedirectResponse(url="/admin?auth=success")

@api_router.get("/spotify/status")
async def spotify_status():
    token_doc = await get_stored_tokens()
    if not token_doc:
        return {"authenticated": False}
    try:
        await get_valid_access_token()
        return {"authenticated": True}
    except:
        return {"authenticated": False}

@api_router.get("/spotify/playlist-info")
async def get_playlist_info():
    try:
        response = await spotify_request('GET', f'/playlists/{SPOTIFY_PLAYLIST_ID}')
        if response.status_code != 200:
            return PlaylistInfo(name="Silent Disco", color="#ffffff")
        data = response.json()
        name = data.get('name', 'Silent Disco')
        name_lower = name.lower()
        if 'on red' in name_lower:
            color = '#ff3b3b'
        elif 'on blue' in name_lower:
            color = '#00a0ff'
        elif 'on green' in name_lower:
            color = '#00ff7f'
        else:
            color = '#ffffff'
        return PlaylistInfo(name=name, color=color)
    except Exception as e:
        logger.error(f"Error getting playlist info: {e}")
        return PlaylistInfo(name="Silent Disco", color="#ffffff")

@api_router.get("/spotify/now-playing")
async def get_now_playing():
    try:
        response = await spotify_request('GET', '/me/player/currently-playing')
        if response.status_code == 204 or not response.content:
            return NowPlayingResponse(is_playing=False)
        if response.status_code != 200:
            return NowPlayingResponse(is_playing=False)
        
        data = response.json()
        if not data or not data.get('item'):
            return NowPlayingResponse(is_playing=False)
        
        track = data['item']
        track_uri = track.get('uri')
        
        # Mark as played (set cooldown) when a track is now playing
        if track_uri:
            await set_cooldown(track_uri)
        
        duration = track.get('duration_ms', 0)
        progress = data.get('progress_ms', 0)
        
        return NowPlayingResponse(
            is_playing=data.get('is_playing', False),
            song_name=track.get('name'),
            artist=', '.join([a['name'] for a in track.get('artists', [])]),
            album_art=track['album']['images'][0]['url'] if track.get('album', {}).get('images') else None,
            duration_ms=duration,
            progress_ms=progress,
            time_left_ms=duration - progress if duration and progress else None,
            track_uri=track_uri
        )
    except Exception as e:
        logger.error(f"Error getting now playing: {e}")
        return NowPlayingResponse(is_playing=False)

@api_router.get("/spotify/queue")
async def get_queue():
    try:
        response = await spotify_request('GET', '/me/player/queue')
        if response.status_code != 200:
            return {"queue": []}
        
        data = response.json()
        queue_items = data.get('queue', [])[:25]  # Limit to 25
        
        # Batch fetch: Get all track URIs
        track_uris = [track.get('uri', '') for track in queue_items]
        track_ids = [uri.split(':')[-1] if ':' in uri else uri for uri in track_uris]
        
        # Batch query for guest requests
        guest_requests_cursor = db.guest_requests.find({'uri': {'$in': track_uris}})
        guest_request_uris = {doc['uri'] async for doc in guest_requests_cursor}
        
        # Batch query for cooldowns
        cooldown_cursor = db.track_cooldown.find({'track_id': {'$in': track_ids}})
        cooldown_map = {}
        now = datetime.now(timezone.utc)
        async for doc in cooldown_cursor:
            last_time = doc.get('timestamp')
            if last_time:
                if isinstance(last_time, str):
                    last_time = datetime.fromisoformat(last_time.replace('Z', '+00:00'))
                elif last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=timezone.utc)
                time_diff = (now - last_time).total_seconds()
                if time_diff < COOLDOWN_SECONDS:
                    cooldown_map[doc['track_id']] = int((COOLDOWN_SECONDS - time_diff) / 60)
        
        result = []
        for track in queue_items:
            uri = track.get('uri', '')
            track_id = uri.split(':')[-1] if ':' in uri else uri
            is_request = uri in guest_request_uris
            cooldown_mins = cooldown_map.get(track_id, 0)
            in_cooldown = cooldown_mins > 0
            
            result.append({
                'uri': uri,
                'name': track.get('name', 'Unknown'),
                'artist': ', '.join([a['name'] for a in track.get('artists', [])]),
                'album_art': track['album']['images'][0]['url'] if track.get('album', {}).get('images') else None,
                'is_guest_request': is_request,
                'in_cooldown': in_cooldown,
                'cooldown_minutes': cooldown_mins
            })
        
        return {"queue": result}
    except Exception as e:
        logger.error(f"Error getting queue: {e}")
        return {"queue": []}

@api_router.post("/spotify/search")
async def search_tracks(request: SearchRequest):
    try:
        response = await spotify_request('GET', f'/search?q={urllib.parse.quote(request.query)}&type=track&limit=10')
        if response.status_code != 200:
            return {"tracks": []}
        
        data = response.json()
        tracks = data.get('tracks', {}).get('items', [])
        
        # Batch fetch: Get all track IDs
        track_ids = [track.get('uri', '').split(':')[-1] for track in tracks if track.get('uri')]
        
        # Batch query for cooldowns
        cooldown_cursor = db.track_cooldown.find({'track_id': {'$in': track_ids}})
        cooldown_map = {}
        now = datetime.now(timezone.utc)
        async for doc in cooldown_cursor:
            last_time = doc.get('timestamp')
            if last_time:
                if isinstance(last_time, str):
                    last_time = datetime.fromisoformat(last_time.replace('Z', '+00:00'))
                elif last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=timezone.utc)
                time_diff = (now - last_time).total_seconds()
                if time_diff < COOLDOWN_SECONDS:
                    cooldown_map[doc['track_id']] = int((COOLDOWN_SECONDS - time_diff) / 60)
        
        result = []
        for track in tracks:
            uri = track.get('uri', '')
            track_id = uri.split(':')[-1] if ':' in uri else uri
            cooldown_mins = cooldown_map.get(track_id, 0)
            in_cooldown = cooldown_mins > 0
            
            result.append({
                'uri': uri,
                'name': track.get('name', 'Unknown'),
                'artist': ', '.join([a['name'] for a in track.get('artists', [])]),
                'album_art': track['album']['images'][0]['url'] if track.get('album', {}).get('images') else None,
                'in_cooldown': in_cooldown,
                'cooldown_minutes': cooldown_mins
            })
        
        return {"tracks": result}
    except Exception as e:
        logger.error(f"Error searching: {e}")
        return {"tracks": []}

@api_router.post("/spotify/add-track")
async def add_track(request: TrackRequest):
    try:
        # Check cooldown
        can_add, error_msg = await check_cooldown(request.track_uri)
        if not can_add:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Add to Spotify queue
        response = await spotify_request('POST', f'/me/player/queue?uri={urllib.parse.quote(request.track_uri)}')
        
        if response.status_code not in [200, 204]:
            logger.error(f"Add track error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=400, detail="Failed to add track to queue")
        
        # Track as guest request
        await add_guest_request(
            track_uri=request.track_uri,
            track_name=request.track_name or "Unknown",
            artist=request.artist or "Unknown",
            album_art=request.album_art or ""
        )
        
        # Set cooldown
        await set_cooldown(request.track_uri)
        
        return {"success": True, "message": "Added to queue!"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding track: {e}")
        raise HTTPException(status_code=500, detail=str(e))

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
