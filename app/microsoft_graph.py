"""Microsoft Graph delegated OAuth support for personal Microsoft accounts."""
import base64
import logging
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

import msal

AUTHORITY = 'https://login.microsoftonline.com/consumers'
SCOPES = ['https://graph.microsoft.com/Mail.Send']
GRAPH_SEND = 'https://graph.microsoft.com/v1.0/me/sendMail'
LOCK = threading.Lock()


def _cache_path():
    data = Path(os.getenv('DATA_DIR', '/data'))
    data.mkdir(parents=True, exist_ok=True)
    return data / 'microsoft-token-cache.json'


def _load():
    cache = msal.SerializableTokenCache()
    path = _cache_path()
    if path.exists():
        try:
            cache.deserialize(path.read_text(encoding='utf-8'))
        except Exception:
            logging.exception('Microsoft OAuth token cache could not be read.')
    return cache


def _save(cache):
    if not cache.has_state_changed:
        return
    path = _cache_path()
    temporary = path.with_suffix('.tmp')
    temporary.write_text(cache.serialize(), encoding='utf-8')
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def _app(client_id, cache):
    return msal.PublicClientApplication(client_id, authority=AUTHORITY, token_cache=cache)


def access_token(client_id):
    """Return a cached/refreshed Graph token, or None when interactive sign-in is required."""
    with LOCK:
        cache = _load()
        app = _app(client_id, cache)
        accounts = app.get_accounts()
        result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
        _save(cache)
    if result and 'access_token' in result:
        return result['access_token']
    return None


def connect(client_id, output=print):
    """Run one-time device-code sign-in and persist the refresh-token cache under /data."""
    with LOCK:
        cache = _load()
        app = _app(client_id, cache)
        flow = app.initiate_device_flow(scopes=SCOPES)
        if 'user_code' not in flow:
            raise RuntimeError('Microsoft device sign-in could not start: ' + str(flow.get('error_description') or flow.get('error') or 'unknown error'))
        output(flow.get('message') or ('Open ' + flow.get('verification_uri', 'https://microsoft.com/devicelogin') + ' and enter code ' + flow['user_code']))
        result = app.acquire_token_by_device_flow(flow)
        _save(cache)
    if 'access_token' not in result:
        raise RuntimeError('Microsoft sign-in failed: ' + str(result.get('error_description') or result.get('error') or 'unknown error'))
    claims = result.get('id_token_claims') or {}
    return claims.get('preferred_username') or claims.get('email') or 'Microsoft account'


def send_mime(client_id, mime_bytes, timeout=20):
    """Submit a MIME message to Graph. Returns the HTTP status code."""
    token = access_token(client_id)
    if not token:
        raise RuntimeError('Microsoft account is not connected. Run: python /app/connect_microsoft.py')
    body = base64.b64encode(mime_bytes)
    request = urllib.request.Request(
        GRAPH_SEND,
        data=body,
        method='POST',
        headers={
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'text/plain',
            'Content-Length': str(len(body)),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        detail = error.read(2048).decode('utf-8', 'replace').replace('\r', ' ').replace('\n', ' ')
        raise RuntimeError('Microsoft Graph rejected the message (HTTP %s): %s' % (error.code, detail[:1000])) from None
