import httpx
import base64
import urllib.parse
import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from .config import get_settings
from .database import db

settings = get_settings()
logger = logging.getLogger(__name__)

SPOTIFY_AUTH_URL = 'https://accounts.spotify.com/authorize'
SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token'
SPOTIFY_API_URL = 'https://api.spotify.com/v1'

async def get_stored_tokens():
    return await db.get_db().spotify_tokens.find_one({'_id': 'main'}, {'_id': 1, 'access_token': 1, 'refresh_token': 1, 'expires_at': 1})

async def store_tokens(access_token: str, refresh_token: str, expires_in: int):
    expires_at = datetime.now(timezone.utc).timestamp() + expires_in - 60
    await db.get_db().spotify_tokens.update_one(
        {'_id': 'main'},
        {'$set': {'access_token': access_token, 'refresh_token': refresh_token, 'expires_at': expires_at}},
        upsert=True
    )

async def refresh_access_token():
    token_doc = await get_stored_tokens()
    if not token_doc or 'refresh_token' not in token_doc:
        raise HTTPException(status_code=401, detail="Not authenticated. Please visit /admin")
    
    auth_header = base64.b64encode(f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()).decode()
    async with httpx.AsyncClient() as http_client:
        response = await http_client.post(
            SPOTIFY_TOKEN_URL,
            headers={'Authorization': f'Basic {auth_header}', 'Content-Type': 'application/x-www-form-urlencoded'},
            data={'grant_type': 'refresh_token', 'refresh_token': token_doc['refresh_token']}
        )
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Failed to refresh token")
        data = response.json()
        # Some refresh responses don't include a new refresh token, so we fallback to the old one
        new_refresh_token = data.get('refresh_token', token_doc['refresh_token'])
        await store_tokens(data['access_token'], new_refresh_token, data['expires_in'])
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

def get_auth_url():
    scope = "user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private"
    params = {
        'client_id': settings.spotify_client_id,
        'response_type': 'code',
        'redirect_uri': settings.spotify_redirect_uri,
        'scope': scope,
        'show_dialog': 'true'
    }
    return f"{SPOTIFY_AUTH_URL}?{urllib.parse.urlencode(params)}"

async def exchange_code_for_token(code: str):
    auth_header = base64.b64encode(f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()).decode()
    logger.info(f"Exchanging code for token with redirect_uri: {settings.spotify_redirect_uri}")
    async with httpx.AsyncClient() as http_client:
        response = await http_client.post(
            SPOTIFY_TOKEN_URL,
            headers={'Authorization': f'Basic {auth_header}', 'Content-Type': 'application/x-www-form-urlencoded'},
            data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': settings.spotify_redirect_uri}
        )
        if response.status_code != 200:
            error_detail = response.text
            logger.error(f"Spotify token exchange failed: {response.status_code} - {error_detail}")
            raise HTTPException(status_code=400, detail=f"Failed to exchange code for token: {error_detail}")
        data = response.json()
        await store_tokens(data['access_token'], data['refresh_token'], data['expires_in'])

