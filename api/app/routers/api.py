from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import RedirectResponse
import urllib.parse
import logging
from datetime import datetime, timezone

from ..models import SearchRequest, TrackRequest, PlaylistInfo, NowPlayingResponse
from ..database import db
from ..spotify import (
    spotify_request, 
    get_auth_url, 
    exchange_code_for_token, 
    get_valid_access_token,
    get_stored_tokens,
    settings
)
from ..services import (
    check_cooldown, 
    check_duplicate_lock, 
    set_duplicate_lock, 
    release_duplicate_lock, 
    set_cooldown, 
    add_guest_request, 
    get_queue_position, 
    COOLDOWN_SECONDS, 
    DUPLICATE_LOCK_SECONDS
)

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

@router.get("/")
async def root():
    return {"message": "Byron Bay Silent Disco API"}

@router.get("/spotify/auth")
async def spotify_auth():
    return RedirectResponse(url=get_auth_url())

@router.get("/spotify/callback")
async def spotify_callback(code: str = Query(...), error: str = Query(None)):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    
    try:
        await exchange_code_for_token(code)
        return RedirectResponse(url="/admin?auth=success")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Callback error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Callback error: {type(e).__name__}: {str(e)}")

@router.get("/spotify/status")
async def spotify_status():
    token_doc = await get_stored_tokens()
    if not token_doc:
        return {"authenticated": False}
    try:
        await get_valid_access_token()
        return {"authenticated": True}
    except:
        return {"authenticated": False}

@router.get("/spotify/playlist-info")
async def get_playlist_info():
    try:
        response = await spotify_request('GET', f'/playlists/{settings.spotify_playlist_id}')
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

@router.get("/spotify/now-playing")
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
            # We use background task concept here conceptually, but simple await is fine
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

@router.get("/spotify/queue")
async def get_queue():
    try:
        response = await spotify_request('GET', '/me/player/queue')
        if response.status_code != 200:
            return {"queue": []}
        
        data = response.json()
        queue_items = data.get('queue', [])[:25]
        
        # Batch fetch
        track_uris = [track.get('uri', '') for track in queue_items]
        track_ids = [uri.split(':')[-1] if ':' in uri else uri for uri in track_uris]
        
        # Batch query for guest requests
        guest_requests_cursor = db.get_db().guest_requests.find({'uri': {'$in': track_uris}}, {'_id': 0, 'uri': 1})
        guest_request_uris = {doc['uri'] async for doc in guest_requests_cursor}
        
        # Batch query for cooldowns
        cooldown_cursor = db.get_db().track_cooldown.find({'track_id': {'$in': track_ids}}, {'_id': 0, 'track_id': 1, 'timestamp': 1})
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

@router.post("/spotify/search")
async def search_tracks(request: SearchRequest):
    try:
        response = await spotify_request('GET', f'/search?q={urllib.parse.quote(request.query)}&type=track&limit=10')
        if response.status_code != 200:
            return {"tracks": []}
        
        data = response.json()
        tracks = data.get('tracks', {}).get('items', [])
        
        track_ids = [track.get('uri', '').split(':')[-1] for track in tracks if track.get('uri')]
        track_uris = [track.get('uri', '') for track in tracks if track.get('uri')]
        
        # Batch query for cooldowns
        cooldown_cursor = db.get_db().track_cooldown.find({'track_id': {'$in': track_ids}}, {'_id': 0, 'track_id': 1, 'timestamp': 1})
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
        
        # Batch query for recent additions (duplicate prevention)
        recent_cursor = db.get_db().recent_additions.find({'track_id': {'$in': track_ids}}, {'_id': 0, 'track_id': 1, 'added_at': 1})
        recent_map = {}
        async for doc in recent_cursor:
            added_time = doc.get('added_at')
            if added_time:
                if isinstance(added_time, str):
                    added_time = datetime.fromisoformat(added_time.replace('Z', '+00:00'))
                elif added_time.tzinfo is None:
                    added_time = added_time.replace(tzinfo=timezone.utc)
                time_diff = (now - added_time).total_seconds()
                if time_diff < DUPLICATE_LOCK_SECONDS:
                    recent_map[doc['track_id']] = True
        
        result = []
        for track in tracks:
            uri = track.get('uri', '')
            track_id = uri.split(':')[-1] if ':' in uri else uri
            cooldown_mins = cooldown_map.get(track_id, 0)
            in_cooldown = cooldown_mins > 0
            recently_added = recent_map.get(track_id, False)
            
            result.append({
                'uri': uri,
                'name': track.get('name', 'Unknown'),
                'artist': ', '.join([a['name'] for a in track.get('artists', [])]),
                'album_art': track['album']['images'][0]['url'] if track.get('album', {}).get('images') else None,
                'in_cooldown': in_cooldown,
                'cooldown_minutes': cooldown_mins,
                'recently_added': recently_added
            })
        
        return {"tracks": result}
    except Exception as e:
        logger.error(f"Error searching: {e}")
        return {"tracks": []}

@router.post("/spotify/add-track")
async def add_track(request: TrackRequest):
    try:
        # Check cooldown first
        can_add, error_msg = await check_cooldown(request.track_uri)
        if not can_add:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Check duplicate lock (prevent rapid clicks)
        can_add, error_msg = await check_duplicate_lock(request.track_uri)
        if not can_add:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Set lock immediately to prevent concurrent requests
        await set_duplicate_lock(request.track_uri)
        
        try:
            # Add to Spotify queue
            response = await spotify_request('POST', f'/me/player/queue?uri={urllib.parse.quote(request.track_uri)}')
            
            if response.status_code not in [200, 204]:
                await release_duplicate_lock(request.track_uri)
                error_data = response.json() if response.content else {}
                error_reason = error_data.get('error', {}).get('reason', '')
                if error_reason == 'NO_ACTIVE_DEVICE':
                    raise HTTPException(status_code=400, detail="No active Spotify player. Please start playing music first.")
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
            
            # Get queue position from Spotify
            # We don't use 'await asyncio.sleep(0.5)' here in production code usually but let's keep it if we want delay
            # Just relying on next poll is often better, but for immediate feedback:
            import asyncio
            await asyncio.sleep(0.5) 
            
            position = await get_queue_position(request.track_uri)
            
            position_text = f" at position #{position}" if position > 0 else ""
            
            return {
                "success": True, 
                "message": f"Added to queue{position_text}!",
                "position": position,
                "track_name": request.track_name,
                "artist": request.artist
            }
        except HTTPException:
            raise
        except Exception as e:
            await release_duplicate_lock(request.track_uri)
            raise e
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding track: {e}")
        raise HTTPException(status_code=500, detail=str(e))
