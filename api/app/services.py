from datetime import datetime, timezone
from .database import db
from .spotify import spotify_request

# Cooldown: 1 hour in seconds
COOLDOWN_SECONDS = 3600

# Duplicate prevention: Lock time in seconds (prevents rapid clicks)
DUPLICATE_LOCK_SECONDS = 30

# In-memory lock for preventing duplicate submissions
pending_requests = {}

async def check_cooldown(track_uri: str) -> tuple[bool, str]:
    """Check if track is in cooldown. Returns (can_add, error_message)"""
    track_id = track_uri.split(':')[-1] if ':' in track_uri else track_uri
    doc = await db.get_db().track_cooldown.find_one({'track_id': track_id}, {'_id': 0, 'track_id': 1, 'timestamp': 1})
    if not doc:
        return True, ""
    
    last_time = doc.get('timestamp')
    if not last_time:
        return True, ""
    
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

async def check_duplicate_lock(track_uri: str) -> tuple[bool, str]:
    """Check if track is currently being added (prevent rapid duplicate clicks)"""
    track_id = track_uri.split(':')[-1] if ':' in track_uri else track_uri
    
    # Check in-memory lock first (for very rapid clicks)
    if track_id in pending_requests:
        lock_time = pending_requests[track_id]
        if (datetime.now(timezone.utc) - lock_time).total_seconds() < 5:
            return False, "This song is already being added. Please wait."
    
    # Check database for recent additions
    doc = await db.get_db().recent_additions.find_one({'track_id': track_id}, {'_id': 0, 'track_id': 1, 'added_at': 1})
    if doc:
        added_time = doc.get('added_at')
        if added_time:
            if isinstance(added_time, str):
                added_time = datetime.fromisoformat(added_time.replace('Z', '+00:00'))
            elif added_time.tzinfo is None:
                added_time = added_time.replace(tzinfo=timezone.utc)
            
            time_diff = (datetime.now(timezone.utc) - added_time).total_seconds()
            if time_diff < DUPLICATE_LOCK_SECONDS:
                return False, "This song was just added! Check the queue."
    
    return True, ""

async def set_duplicate_lock(track_uri: str):
    """Set a lock to prevent duplicate additions"""
    track_id = track_uri.split(':')[-1] if ':' in track_uri else track_uri
    pending_requests[track_id] = datetime.now(timezone.utc)
    await db.get_db().recent_additions.update_one(
        {'track_id': track_id},
        {'$set': {'track_id': track_id, 'added_at': datetime.now(timezone.utc)}},
        upsert=True
    )

async def release_duplicate_lock(track_uri: str):
    """Release the in-memory lock"""
    track_id = track_uri.split(':')[-1] if ':' in track_uri else track_uri
    if track_id in pending_requests:
        del pending_requests[track_id]

async def set_cooldown(track_uri: str):
    """Set cooldown timestamp for a track"""
    track_id = track_uri.split(':')[-1] if ':' in track_uri else track_uri
    await db.get_db().track_cooldown.update_one(
        {'track_id': track_id},
        {'$set': {'track_id': track_id, 'track_uri': track_uri, 'timestamp': datetime.now(timezone.utc)}},
        upsert=True
    )

async def add_guest_request(track_uri: str, track_name: str, artist: str, album_art: str):
    """Track a guest request"""
    await db.get_db().guest_requests.update_one(
        {'uri': track_uri},
        {'$set': {'uri': track_uri, 'name': track_name, 'artist': artist, 'album_art': album_art, 'requested_at': datetime.now(timezone.utc)}},
        upsert=True
    )

async def get_queue_position(track_uri: str) -> int:
    """Get the position of a track in the current queue"""
    try:
        response = await spotify_request('GET', '/me/player/queue')
        if response.status_code == 200:
            data = response.json()
            queue_items = data.get('queue', [])
            for i, track in enumerate(queue_items):
                if track.get('uri') == track_uri:
                    return i + 1  # 1-indexed position
        return -1
    except:
        return -1
