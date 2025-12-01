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
from datetime import datetime, timezone, timedelta
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

# No repeat window (1 hour in seconds)
NO_REPEAT_WINDOW_SECONDS = 3600

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
    track_name: Optional[str] = None
    artist: Optional[str] = None
    album_art: Optional[str] = None

class NowPlayingResponse(BaseModel):
    is_playing: bool
    song_name: Optional[str] = None
    artist: Optional[str] = None
    album_art: Optional[str] = None
    duration_ms: Optional[int] = None
    progress_ms: Optional[int] = None
    time_left_ms: Optional[int] = None
    track_uri: Optional[str] = None

class QueueTrack(BaseModel):
    uri: str
    name: str
    artist: str
    album_art: Optional[str] = None
    is_guest_request: bool = False
    is_priority: bool = False
    position: int = 0

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
    expires_at = datetime.now(timezone.utc).timestamp() + expires_in - 60
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

async def reset_last_request_position():
    """Reset the last request position when queue changes significantly"""
    await db.request_state.update_one(
        {'_id': 'position'},
        {'$set': {'position': 0}},
        upsert=True
    )

async def add_to_managed_queue(track_uri: str, track_name: str, artist: str, album_art: str, position: int, is_priority: bool = False):
    """Add a track to our managed queue"""
    await db.managed_queue.insert_one({
        'uri': track_uri,
        'name': track_name,
        'artist': artist,
        'album_art': album_art,
        'position': position,
        'is_priority': is_priority,
        'added_at': datetime.now(timezone.utc),
        'played': False
    })

async def get_managed_queue():
    """Get our managed queue sorted by position"""
    # Priority tracks first (position 0), then by position
    cursor = db.managed_queue.find({'played': False}).sort([('is_priority', -1), ('position', 1)])
    return await cursor.to_list(100)

async def mark_track_played(track_uri: str):
    """Mark a track as played"""
    await db.managed_queue.update_many(
        {'uri': track_uri},
        {'$set': {'played': True}}
    )

async def is_in_managed_queue(track_uri: str) -> bool:
    """Check if track is already in managed queue"""
    doc = await db.managed_queue.find_one({'uri': track_uri, 'played': False})
    return doc is not None

async def move_to_priority(track_uri: str):
    """Move a track to priority (position 1)"""
    await db.managed_queue.update_one(
        {'uri': track_uri, 'played': False},
        {'$set': {'is_priority': True, 'position': 0}}
    )

async def cleanup_old_queue_entries():
    """Remove old played entries"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    await db.managed_queue.delete_many({'played': True, 'added_at': {'$lt': cutoff}})

async def check_no_repeat_rule(track_uri: str) -> tuple[bool, str]:
    """Check if a track was played/queued in the last hour"""
    track_id = track_uri.split(':')[-1] if ':' in track_uri else track_uri
    
    doc = await db.track_history.find_one({'track_id': track_id})
    if not doc:
        return True, ""
    
    last_time = doc.get('last_queued_at')
    if not last_time:
        return True, ""
    
    if isinstance(last_time, str):
        last_time = datetime.fromisoformat(last_time.replace('Z', '+00:00'))
    
    now = datetime.now(timezone.utc)
    time_diff = (now - last_time).total_seconds()
    
    if time_diff < NO_REPEAT_WINDOW_SECONDS:
        minutes_left = int((NO_REPEAT_WINDOW_SECONDS - time_diff) / 60)
        return False, f"This song was played recently. Try again in {minutes_left} minutes!"
    
    return True, ""

async def record_track_play(track_uri: str):
    """Record when a track is queued/played"""
    track_id = track_uri.split(':')[-1] if ':' in track_uri else track_uri
    await db.track_history.update_one(
        {'track_id': track_id},
        {'$set': {
            'track_id': track_id,
            'track_uri': track_uri,
            'last_queued_at': datetime.now(timezone.utc)
        }},
        upsert=True
    )

async def get_spotify_queue_length():
    """Get the current Spotify queue length"""
    try:
        response = await spotify_request('GET', '/me/player/queue')
        if response.status_code == 200:
            data = response.json()
            return len(data.get('queue', []))
    except:
        pass
    return 0

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
        
        # Reset queue state on new auth
        await reset_last_request_position()
        await db.managed_queue.delete_many({})
        
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
        return PlaylistInfo(name="Silent Disco", color="white")

@api_router.get("/spotify/now-playing")
async def get_now_playing():
    """Get currently playing track"""
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
        duration = track.get('duration_ms', 0)
        progress = data.get('progress_ms', 0)
        
        # Mark this track as played in our managed queue
        track_uri = track.get('uri')
        if track_uri:
            await mark_track_played(track_uri)
        
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting now playing: {e}")
        return NowPlayingResponse(is_playing=False)

@api_router.get("/spotify/queue")
async def get_queue():
    """Get the combined queue (priority requests first, then Spotify queue)"""
    try:
        # Get Spotify's actual queue
        response = await spotify_request('GET', '/me/player/queue')
        
        spotify_queue = []
        if response.status_code == 200:
            data = response.json()
            spotify_queue = data.get('queue', [])
        
        # Get our managed requests
        managed = await get_managed_queue()
        managed_uris = {m['uri'] for m in managed}
        
        # Build combined queue
        result = []
        position = 1
        
        # First, add priority requests (paid $1 Play Next)
        priority_tracks = [m for m in managed if m.get('is_priority')]
        for track in priority_tracks:
            result.append(QueueTrack(
                uri=track['uri'],
                name=track['name'],
                artist=track['artist'],
                album_art=track.get('album_art'),
                is_guest_request=True,
                is_priority=True,
                position=position
            ))
            position += 1
        
        # Then add Spotify queue tracks, marking guest requests
        for track in spotify_queue:
            uri = track.get('uri', '')
            is_request = uri in managed_uris
            result.append(QueueTrack(
                uri=uri,
                name=track.get('name', 'Unknown'),
                artist=', '.join([a['name'] for a in track.get('artists', [])]),
                album_art=track['album']['images'][0]['url'] if track.get('album', {}).get('images') else None,
                is_guest_request=is_request,
                is_priority=False,
                position=position
            ))
            position += 1
        
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
    """Add a track to Spotify queue (Free Queue)
    
    NOTE: Spotify API only allows adding to END of queue.
    The 4th position rule is tracked internally for display purposes.
    """
    try:
        # Check 1-hour no-repeat rule
        can_add, error_msg = await check_no_repeat_rule(request.track_uri)
        if not can_add:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Check if already in queue
        if await is_in_managed_queue(request.track_uri):
            raise HTTPException(status_code=400, detail="This song is already in the queue!")
        
        # Add to Spotify queue (always goes to end - API limitation)
        add_response = await spotify_request(
            'POST',
            f'/me/player/queue?uri={urllib.parse.quote(request.track_uri)}'
        )
        
        if add_response.status_code not in [200, 204]:
            logger.error(f"Add track error: {add_response.status_code} - {add_response.text}")
            raise HTTPException(status_code=400, detail="Failed to add track to queue")
        
        # Track the request position for internal logic
        last_position = await get_last_request_position()
        if last_position == 0:
            target_position = 4
        else:
            target_position = last_position + 4
        
        await set_last_request_position(target_position)
        
        # Add to our managed queue
        await add_to_managed_queue(
            track_uri=request.track_uri,
            track_name=request.track_name or "Unknown",
            artist=request.artist or "Unknown",
            album_art=request.album_art or "",
            position=target_position,
            is_priority=False
        )
        
        # Record for no-repeat rule
        await record_track_play(request.track_uri)
        
        # Cleanup old entries
        await cleanup_old_queue_entries()
        
        logger.info(f"Free queue: Added track (goes to end of Spotify queue)")
        
        return {
            "success": True, 
            "message": "Track added to queue!"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding track: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/spotify/skip-paid")
async def skip_paid(request: TrackRequest):
    """Add track to position 1 (next up) - for paid $1 Play Next"""
    try:
        # Check 1-hour no-repeat rule
        can_add, error_msg = await check_no_repeat_rule(request.track_uri)
        if not can_add:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Check if already in queue
        if await is_in_managed_queue(request.track_uri):
            # If already in queue, just make it priority
            await move_to_priority(request.track_uri)
            return {"success": True, "message": "Track moved to play next!"}
        
        # Add to Spotify queue
        add_response = await spotify_request(
            'POST',
            f'/me/player/queue?uri={urllib.parse.quote(request.track_uri)}'
        )
        
        if add_response.status_code not in [200, 204]:
            logger.error(f"Skip paid error: {add_response.status_code} - {add_response.text}")
            raise HTTPException(status_code=400, detail="Failed to add track to queue")
        
        # Add to managed queue as PRIORITY (position 1)
        await add_to_managed_queue(
            track_uri=request.track_uri,
            track_name=request.track_name or "Unknown",
            artist=request.artist or "Unknown",
            album_art=request.album_art or "",
            position=0,  # Priority position
            is_priority=True
        )
        
        # Record for no-repeat rule
        await record_track_play(request.track_uri)
        
        # NOTE: Do NOT update last_request_position for paid skips
        
        logger.info(f"Paid skip: Added track as priority (position 1)")
        
        return {"success": True, "message": "Track will play next!"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error with paid skip: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/spotify/move-to-next")
async def move_to_next(request: TrackRequest):
    """Move an existing track to position 1 (paid skip from queue list)"""
    try:
        # Check 1-hour no-repeat rule
        can_add, error_msg = await check_no_repeat_rule(request.track_uri)
        if not can_add:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Check if in our managed queue
        if await is_in_managed_queue(request.track_uri):
            await move_to_priority(request.track_uri)
        else:
            # Add to managed queue as priority
            await add_to_managed_queue(
                track_uri=request.track_uri,
                track_name=request.track_name or "Unknown",
                artist=request.artist or "Unknown",
                album_art=request.album_art or "",
                position=0,
                is_priority=True
            )
        
        # Record for no-repeat rule (refresh timestamp)
        await record_track_play(request.track_uri)
        
        logger.info(f"Move to next: Track marked as priority")
        
        return {"success": True, "message": "Track will play next!"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error moving track: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/config")
async def get_config():
    """Get frontend configuration"""
    return {
        "square_payment_link": SQUARE_PAYMENT_LINK
    }

@api_router.post("/admin/reset-queue-state")
async def reset_queue_state():
    """Admin endpoint to reset the queue tracking state"""
    await reset_last_request_position()
    await db.managed_queue.delete_many({})
    return {"success": True, "message": "Queue state reset"}

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
