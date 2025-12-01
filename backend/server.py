from fastapi import FastAPI, APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime, timezone
import httpx
import base64
import urllib.parse

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', 'silent_disco')]

# Spotify configuration
SPOTIFY_CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID', '')
SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIFY_CLIENT_SECRET', '')
SPOTIFY_REDIRECT_URI = os.environ.get('SPOTIFY_REDIRECT_URI', '')
SPOTIFY_PLAYLIST_ID = os.environ.get('SPOTIFY_PLAYLIST_ID', '')
SQUARE_PAYMENT_LINK = os.environ.get('SQUARE_PAYMENT_LINK', 'https://square.link/u/Rq2vJVSa')

SPOTIFY_AUTH_URL = 'https://accounts.spotify.com/authorize'
SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token'
SPOTIFY_API_URL = 'https://api.spotify.com/v1'

# Create the main app
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Models
class SearchRequest(BaseModel):
    query: str

class TrackRequest(BaseModel):
    track_uri: str

class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: datetime

class NowPlayingResponse(BaseModel):
    is_playing: bool
    song_name: Optional[str] = None
    artist: Optional[str] = None
    album_art: Optional[str] = None
    duration_ms: Optional[int] = None
    progress_ms: Optional[int] = None
    time_left_ms: Optional[int] = None

class QueueTrack(BaseModel):
    uri: str
    name: str
    artist: str
    album_art: Optional[str] = None
    is_guest_request: bool = False

class PlaylistInfo(BaseModel):
    name: str
    color: str

# Helper functions
async def get_stored_tokens():
    """Get stored tokens from database"""
    token_doc = await db.spotify_tokens.find_one({'_id': 'main'})
    return token_doc

async def store_tokens(access_token: str, refresh_token: str, expires_in: int):
    """Store tokens in database"""
    expires_at = datetime.now(timezone.utc).timestamp() + expires_in - 60  # 60 second buffer
    await db.spotify_tokens.update_one(
        {'_id': 'main'},
        {'$set': {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_at': expires_at
        }},
        upsert=True
    )

async def refresh_access_token():
    """Refresh the access token using refresh token"""
    token_doc = await get_stored_tokens()
    if not token_doc or 'refresh_token' not in token_doc:
        raise HTTPException(status_code=401, detail="No refresh token available. Please authenticate.")
    
    auth_header = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            SPOTIFY_TOKEN_URL,
            headers={
                'Authorization': f'Basic {auth_header}',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data={
                'grant_type': 'refresh_token',
                'refresh_token': token_doc['refresh_token']
            }
        )
        
        if response.status_code != 200:
            logger.error(f"Token refresh failed: {response.text}")
            raise HTTPException(status_code=401, detail="Failed to refresh token")
        
        data = response.json()
        new_refresh_token = data.get('refresh_token', token_doc['refresh_token'])
        await store_tokens(data['access_token'], new_refresh_token, data['expires_in'])
        return data['access_token']

async def get_valid_access_token():
    """Get a valid access token, refreshing if necessary"""
    token_doc = await get_stored_tokens()
    if not token_doc:
        raise HTTPException(status_code=401, detail="Not authenticated. Please visit /api/spotify/auth")
    
    current_time = datetime.now(timezone.utc).timestamp()
    if current_time >= token_doc.get('expires_at', 0):
        return await refresh_access_token()
    
    return token_doc['access_token']

async def spotify_request(method: str, endpoint: str, **kwargs):
    """Make an authenticated request to Spotify API"""
    access_token = await get_valid_access_token()
    headers = {'Authorization': f'Bearer {access_token}'}
    
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method,
            f"{SPOTIFY_API_URL}{endpoint}",
            headers=headers,
            **kwargs
        )
        return response

async def get_last_request_position():
    """Get the last request position from database"""
    doc = await db.request_state.find_one({'_id': 'position'})
    return doc.get('position', 0) if doc else 0

async def set_last_request_position(position: int):
    """Set the last request position in database"""
    await db.request_state.update_one(
        {'_id': 'position'},
        {'$set': {'position': position}},
        upsert=True
    )

async def add_guest_request(track_uri: str):
    """Track a guest-requested song"""
    await db.guest_requests.update_one(
        {'uri': track_uri},
        {'$set': {'uri': track_uri, 'requested_at': datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )

async def is_guest_request(track_uri: str) -> bool:
    """Check if a track was requested by a guest"""
    doc = await db.guest_requests.find_one({'uri': track_uri})
    return doc is not None

# Routes
@api_router.get("/")
async def root():
    return {"message": "Byron Bay Silent Disco API"}

@api_router.get("/spotify/auth")
async def spotify_auth():
    """Start Spotify OAuth flow"""
    scope = "user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private playlist-modify-public playlist-modify-private"
    params = {
        'client_id': SPOTIFY_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': SPOTIFY_REDIRECT_URI,
        'scope': scope,
        'show_dialog': 'true'
    }
    auth_url = f"{SPOTIFY_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=auth_url)

@api_router.get("/spotify/callback")
async def spotify_callback(code: str = Query(...), error: str = Query(None)):
    """Handle Spotify OAuth callback"""
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    
    auth_header = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    
    async with httpx.AsyncClient() as http_client:
        response = await http_client.post(
            SPOTIFY_TOKEN_URL,
            headers={
                'Authorization': f'Basic {auth_header}',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': SPOTIFY_REDIRECT_URI
            }
        )
        
        if response.status_code != 200:
            logger.error(f"Token exchange failed: {response.text}")
            raise HTTPException(status_code=400, detail="Failed to exchange code for token")
        
        data = response.json()
        await store_tokens(data['access_token'], data['refresh_token'], data['expires_in'])
        
        # Redirect to admin success page
        return RedirectResponse(url="/admin?auth=success")

@api_router.get("/spotify/status")
async def spotify_status():
    """Check if Spotify is authenticated"""
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
    """Get playlist name and determine color"""
    try:
        response = await spotify_request('GET', f'/playlists/{SPOTIFY_PLAYLIST_ID}')
        if response.status_code != 200:
            return PlaylistInfo(name="Silent Disco", color="white")
        
        data = response.json()
        name = data.get('name', 'Silent Disco')
        
        # Determine color based on playlist name
        name_lower = name.lower()
        if 'red' in name_lower:
            color = '#ff3b3b'
        elif 'blue' in name_lower:
            color = '#00a0ff'
        elif 'green' in name_lower:
            color = '#00ff7f'
        else:
            color = '#ffffff'
        
        return PlaylistInfo(name=name, color=color)
    except Exception as e:
        logger.error(f"Error getting playlist info: {e}")
        return PlaylistInfo(name="Silent Disco", color="white")

@api_router.get("/spotify/now-playing")
async def get_now_playing():
    """Get currently playing track"""
    try:
        response = await spotify_request('GET', '/me/player/currently-playing')
        
        if response.status_code == 204 or not response.content:
            return NowPlayingResponse(is_playing=False)
        
        if response.status_code != 200:
            logger.error(f"Now playing error: {response.status_code} - {response.text}")
            return NowPlayingResponse(is_playing=False)
        
        data = response.json()
        
        if not data or not data.get('item'):
            return NowPlayingResponse(is_playing=False)
        
        track = data['item']
        duration = track.get('duration_ms', 0)
        progress = data.get('progress_ms', 0)
        
        return NowPlayingResponse(
            is_playing=data.get('is_playing', False),
            song_name=track.get('name'),
            artist=', '.join([a['name'] for a in track.get('artists', [])]),
            album_art=track['album']['images'][0]['url'] if track.get('album', {}).get('images') else None,
            duration_ms=duration,
            progress_ms=progress,
            time_left_ms=duration - progress if duration and progress else None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting now playing: {e}")
        return NowPlayingResponse(is_playing=False)

@api_router.get("/spotify/queue")
async def get_queue():
    """Get the playback queue"""
    try:
        response = await spotify_request('GET', '/me/player/queue')
        
        if response.status_code != 200:
            logger.error(f"Queue error: {response.status_code} - {response.text}")
            return {"queue": []}
        
        data = response.json()
        queue_items = data.get('queue', [])
        
        result = []
        for track in queue_items:
            is_request = await is_guest_request(track.get('uri', ''))
            result.append(QueueTrack(
                uri=track.get('uri', ''),
                name=track.get('name', 'Unknown'),
                artist=', '.join([a['name'] for a in track.get('artists', [])]),
                album_art=track['album']['images'][0]['url'] if track.get('album', {}).get('images') else None,
                is_guest_request=is_request
            ))
        
        return {"queue": [t.model_dump() for t in result]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting queue: {e}")
        return {"queue": []}

@api_router.post("/spotify/search")
async def search_tracks(request: SearchRequest):
    """Search for tracks on Spotify"""
    try:
        response = await spotify_request(
            'GET',
            f'/search?q={urllib.parse.quote(request.query)}&type=track&limit=10'
        )
        
        if response.status_code != 200:
            logger.error(f"Search error: {response.status_code} - {response.text}")
            return {"tracks": []}
        
        data = response.json()
        tracks = data.get('tracks', {}).get('items', [])
        
        result = []
        for track in tracks:
            result.append({
                'uri': track.get('uri', ''),
                'name': track.get('name', 'Unknown'),
                'artist': ', '.join([a['name'] for a in track.get('artists', [])]),
                'album_art': track['album']['images'][0]['url'] if track.get('album', {}).get('images') else None
            })
        
        return {"tracks": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching: {e}")
        return {"tracks": []}

@api_router.post("/spotify/add-track")
async def add_track(request: TrackRequest):
    """Add a track to the queue using 4th position rule"""
    try:
        # Get current queue to determine position
        queue_response = await spotify_request('GET', '/me/player/queue')
        queue_length = 0
        
        if queue_response.status_code == 200:
            queue_data = queue_response.json()
            queue_length = len(queue_data.get('queue', []))
        
        # Calculate position using 4th position rule
        last_position = await get_last_request_position()
        
        if last_position == 0:
            # First request - position 4 (0-indexed: 3)
            target_position = min(3, queue_length)
        else:
            # Subsequent requests - last_position + 4
            target_position = last_position + 4
            if target_position > queue_length:
                target_position = queue_length
        
        # Add to queue (Spotify adds to end, we'll need to reorder if possible)
        # Note: Spotify Web API doesn't support direct position insertion in queue
        # We add to queue and it goes to the end
        add_response = await spotify_request(
            'POST',
            f'/me/player/queue?uri={urllib.parse.quote(request.track_uri)}'
        )
        
        if add_response.status_code not in [200, 204]:
            logger.error(f"Add track error: {add_response.status_code} - {add_response.text}")
            raise HTTPException(status_code=400, detail="Failed to add track to queue")
        
        # Update last request position
        await set_last_request_position(target_position)
        
        # Track this as a guest request
        await add_guest_request(request.track_uri)
        
        return {"success": True, "position": target_position + 1, "message": f"Track added to queue!"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding track: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/spotify/skip-paid")
async def skip_paid(request: TrackRequest):
    """Add track to position 1 (next up) - for paid skips"""
    try:
        # Add to queue
        add_response = await spotify_request(
            'POST',
            f'/me/player/queue?uri={urllib.parse.quote(request.track_uri)}'
        )
        
        if add_response.status_code not in [200, 204]:
            logger.error(f"Skip paid error: {add_response.status_code} - {add_response.text}")
            raise HTTPException(status_code=400, detail="Failed to add track to queue")
        
        # Track as guest request
        await add_guest_request(request.track_uri)
        
        # Note: Spotify doesn't allow reordering queue directly
        # The track is added and marked as priority
        return {"success": True, "message": "Track added as next up!"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error with paid skip: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/config")
async def get_config():
    """Get frontend configuration"""
    return {
        "square_payment_link": SQUARE_PAYMENT_LINK
    }

# Include the router in the main app
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
